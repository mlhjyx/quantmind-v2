"""LLM 预算守门 — BudgetGuard + BudgetAwareRouter + 状态机.

归属: Framework #LLM 平台 SDK (V3 §20.1 #6 + ADR-031 §6 sediment).

scope (S2.2 — 本 PR):
- BudgetGuard 类: 查月度累计 cost + 状态判定 + UPSERT record_cost (走 llm_cost_daily 表)
- BudgetAwareRouter wrapper class (composition, 0 继承 LiteLLMRouter)
- 3 state enum (Normal / Warn_80 / Capped_100)
- BudgetExceededError (strict mode 反 silent fallback)
- 0 audit trail INSERT (S2.3 scope)
- 0 DingTalk push (S2.3 scope)

V3 §20.1 #6 cite (line 1769): "$50/月 + 80% budget warn / 100% Ollama fallback / 月度 review".
3 阈值 from Settings (LLM_MONTHLY_BUDGET_USD / LLM_BUDGET_WARN_THRESHOLD / LLM_BUDGET_CAP_THRESHOLD).

关联铁律: 31 (Engine 纯计算 — Guard query DB 是边界 IO, 走 conn_factory DI) /
          33 (fail-loud, 反 silent overwrite) / 34 (Config SSOT — 阈值 Settings env var) /
          41 (timezone — DB clock 服务器时区)

LL-109 候选 (race window, P3 audit Week 2 sediment 候选):
    T0 BudgetGuard.check NORMAL → T1 别 task record_cost 撞 capped → T2 当前 task 仍透传 v4-pro
    处置: strict=False 默认走 fallback (软保护); strict=True per-task fail-loud (终极保护).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .router import FALLBACK_ALIAS, LiteLLMRouter
from .types import LLMMessage, LLMResponse, RiskTaskType

logger = logging.getLogger(__name__)


class BudgetState(StrEnum):
    """LLM 月度预算状态 (V3 §20.1 #6 sediment, 3 阈值)."""

    NORMAL = "normal"          # cost < warn_threshold × monthly_budget
    WARN_80 = "warn_80"        # warn ≤ cost < cap × monthly_budget
    CAPPED_100 = "capped_100"  # cost ≥ cap × monthly_budget (强制 Ollama fallback)


class BudgetExceededError(RuntimeError):
    """100% capped + strict mode → caller 显式禁 LLM 调用 (反 silent overwrite, 铁律 33).

    BudgetAwareRouter 默认 strict=False 走强制 fallback (qwen3-local), 不 raise.
    本异常留 caller 显式 strict=True (e.g. RiskReflector V4-Pro only, fallback 不接受).
    """


@dataclass(frozen=True)
class BudgetSnapshot:
    """月度预算实时快照 (BudgetGuard.check 返值)."""

    state: BudgetState
    month_to_date_cost_usd: Decimal
    monthly_budget_usd: Decimal
    warn_threshold_usd: Decimal
    cap_threshold_usd: Decimal


@contextmanager
def _conn_cursor(conn: Any) -> Iterator[Any]:
    """psycopg2 with-cursor helper (沿用 feature_flag.py 体例)."""
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


class BudgetGuard:
    """月度 LLM 预算守门 — 查月聚合 cost + UPSERT 当日 row.

    依赖:
        conn_factory: callable 返 psycopg2 conn (DI 体例, 沿用 risk/engine.py).
        monthly_budget_usd / warn_threshold / cap_threshold: from Settings env var.

    使用:
        guard = BudgetGuard(conn_factory, monthly_budget_usd=Decimal('50'),
                            warn_threshold=Decimal('0.80'),
                            cap_threshold=Decimal('1.00'))
        snapshot = guard.check()
        guard.record_cost(cost_usd=Decimal('0.001'), is_fallback=False, is_capped=False)
    """

    def __init__(
        self,
        conn_factory: Callable[[], Any],
        *,
        monthly_budget_usd: Decimal,
        warn_threshold: Decimal,
        cap_threshold: Decimal,
    ) -> None:
        if monthly_budget_usd <= 0:
            raise ValueError(f"monthly_budget_usd 必须 >0, 实测: {monthly_budget_usd}")
        if not (0 < warn_threshold < cap_threshold):
            raise ValueError(
                f"阈值非法: warn={warn_threshold}, cap={cap_threshold}; "
                "需 0 < warn < cap (e.g. 0.80 < 1.00)"
            )
        self._conn_factory = conn_factory
        self._monthly_budget_usd = monthly_budget_usd
        self._warn_threshold = warn_threshold
        self._cap_threshold = cap_threshold

    @property
    def monthly_budget_usd(self) -> Decimal:
        return self._monthly_budget_usd

    def check(self, *, today: date | None = None) -> BudgetSnapshot:
        """查月聚合 cost + 计算 state (0 cache, 决议 3 沿用).

        Args:
            today: 默认 date.today() (DB clock 服务器时区, 铁律 41).
        """
        d = today or date.today()
        month_start = d.replace(day=1)
        month_to_date = self._sum_cost(month_start=month_start, today=d)

        warn_usd = self._monthly_budget_usd * self._warn_threshold
        cap_usd = self._monthly_budget_usd * self._cap_threshold

        if month_to_date >= cap_usd:
            state = BudgetState.CAPPED_100
        elif month_to_date >= warn_usd:
            state = BudgetState.WARN_80
        else:
            state = BudgetState.NORMAL

        return BudgetSnapshot(
            state=state,
            month_to_date_cost_usd=month_to_date,
            monthly_budget_usd=self._monthly_budget_usd,
            warn_threshold_usd=warn_usd,
            cap_threshold_usd=cap_usd,
        )

    def record_cost(
        self,
        cost_usd: Decimal,
        *,
        is_fallback: bool,
        is_capped: bool,
        today: date | None = None,
    ) -> None:
        """UPSERT 当日 row (原子, 沿用 feature_flag.py:151 ON CONFLICT 体例)."""
        if cost_usd < 0:
            raise ValueError(f"cost_usd 不能为负: {cost_usd}")

        d = today or date.today()
        fallback_inc = 1 if is_fallback else 0
        capped_inc = 1 if is_capped else 0

        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO llm_cost_daily (
                        day, cost_usd_total, call_count, fallback_count, capped_count, updated_at
                    )
                    VALUES (%s, %s, 1, %s, %s, NOW())
                    ON CONFLICT (day) DO UPDATE SET
                        cost_usd_total = llm_cost_daily.cost_usd_total + EXCLUDED.cost_usd_total,
                        call_count     = llm_cost_daily.call_count     + 1,
                        fallback_count = llm_cost_daily.fallback_count + EXCLUDED.fallback_count,
                        capped_count   = llm_cost_daily.capped_count   + EXCLUDED.capped_count,
                        updated_at     = NOW()
                    """,
                    (d, cost_usd, fallback_inc, capped_inc),
                )
            conn.commit()
        finally:
            conn.close()

    def _sum_cost(self, *, month_start: date, today: date) -> Decimal:
        """SELECT SUM(cost_usd_total) WHERE day BETWEEN month_start AND today."""
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(cost_usd_total), 0) "
                    "FROM llm_cost_daily WHERE day BETWEEN %s AND %s",
                    (month_start, today),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return Decimal("0")
        value = row[0]
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class BudgetAwareRouter:
    """LiteLLMRouter + BudgetGuard composition (0 继承, ADR-022 反 silent overwrite).

    completion 流程:
        1. snapshot = budget.check()
        2. CAPPED_100 + strict → BudgetExceededError raise
        3. CAPPED_100 + 0 strict → router.completion_with_alias_override(model_alias=qwen3-local)
        4. WARN_80 → logger.warning structured (extra dict, S2.3 audit ingest 前向兼容)
        5. NORMAL → router.completion 透传
        6. budget.record_cost(response.cost_usd, is_fallback, is_capped=state==CAPPED_100)
    """

    def __init__(
        self,
        router: LiteLLMRouter,
        budget: BudgetGuard,
        *,
        strict: bool = False,
    ) -> None:
        self._router = router
        self._budget = budget
        self._strict = strict

    @property
    def is_strict(self) -> bool:
        return self._strict

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        snapshot = self._budget.check()
        is_capped = snapshot.state is BudgetState.CAPPED_100

        if is_capped and self._strict:
            raise BudgetExceededError(
                f"LLM 月度预算 capped (cost={snapshot.month_to_date_cost_usd} >= "
                f"{snapshot.cap_threshold_usd}); strict mode 拒走 fallback "
                f"(task={task}, decision_id={decision_id})"
            )

        if is_capped:
            response = self._router.completion_with_alias_override(
                task=task,
                messages=messages,
                model_alias=FALLBACK_ALIAS,
                decision_id=decision_id,
                **kwargs,
            )
        else:
            if snapshot.state is BudgetState.WARN_80:
                logger.warning(
                    "llm_budget_warn",
                    extra={
                        "event": "llm_budget_warn",
                        "state": snapshot.state.value,
                        "month_to_date_cost_usd": str(snapshot.month_to_date_cost_usd),
                        "warn_threshold_usd": str(snapshot.warn_threshold_usd),
                        "monthly_budget_usd": str(snapshot.monthly_budget_usd),
                        "task": task.value,
                        "decision_id": decision_id,
                    },
                )
            response = self._router.completion(
                task=task,
                messages=messages,
                decision_id=decision_id,
                **kwargs,
            )

        self._budget.record_cost(
            response.cost_usd,
            is_fallback=response.is_fallback,
            is_capped=is_capped,
        )
        return response
