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
from typing import TYPE_CHECKING, Any

from ..types import LLMMessage, LLMResponse, RiskTaskType
from .router import FALLBACK_ALIAS, TASK_TO_MODEL_ALIAS, LiteLLMRouter

if TYPE_CHECKING:
    from .audit import LLMCallLogger

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
        """UPSERT 当日 row (原子, 沿用 feature_flag.py:151 ON CONFLICT 体例).

        cost_usd == 0 真合法 — call_count 仍自增, audit trail 完整 (沿用
        reviewer Chunk A P2 finding clarify): LiteLLM `_hidden_params.response_cost`
        缺失时 LLMResponse.cost_usd 默认 Decimal("0"), 仍走 UPSERT 一次,
        反 silent skip + 保 call_count + fallback_count + capped_count 完整.
        """
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
        audit: LLMCallLogger | None = None,
    ) -> None:
        self._router = router
        self._budget = budget
        self._strict = strict
        self._audit = audit  # S2.3 PR #224: optional audit log (additive, None → 0 audit)

    @property
    def is_strict(self) -> bool:
        return self._strict

    @property
    def audit(self) -> LLMCallLogger | None:
        return self._audit

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

        # sub-PR 8a-followup-B-audit 5-07 BUG #3 fix: try/except 包络 LiteLLM Router
        # completion call. 真生产 exception (e.g. all-fallback exhausted, network fatal,
        # broker fatal) 真**audit + fail-loud re-raise** sustained 铁律 33.
        try:
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
        except Exception as exc:
            # 真 BUG #3 audit failure path: 真**记 llm_call_log row** with error_class
            # = exception class name + is_fallback=True (反 silent skip), 后 re-raise
            # sustained 铁律 33 fail-loud caller 真知 LLM call fail.
            if self._audit is not None:
                try:
                    self._audit_log_failure(
                        task=task,
                        messages=messages,
                        snapshot=snapshot,
                        is_capped=is_capped,
                        decision_id=decision_id,
                        exc=exc,
                    )
                except Exception as audit_exc:
                    logger.warning(
                        "llm_audit_failure_record_build_failed",
                        extra={
                            "event": "llm_audit_failure_record_build_failed",
                            "task": task.value,
                            "decision_id": decision_id,
                            "primary_exc": type(exc).__name__,
                            "audit_exc": type(audit_exc).__name__,
                            "audit_exc_msg": str(audit_exc),
                        },
                    )
            raise

        self._budget.record_cost(
            response.cost_usd,
            is_fallback=response.is_fallback,
            is_capped=is_capped,
        )

        # S2.3 PR #224: optional audit log (additive, audit None → skip).
        # 失败 path 沿用决议 7 — fail-loud warning + 反 break completion.
        # 沿用 reviewer Chunk A P2-2 修: 即使 _audit_log 内部 raise (e.g. dataclass
        # 构造异常), 这里 try/except 包络 → 反 break completion 真 caller.
        if self._audit is not None:
            try:
                self._audit_log(
                    task=task,
                    messages=messages,
                    response=response,
                    snapshot=snapshot,
                    is_capped=is_capped,
                    decision_id=decision_id,
                )
            except Exception as exc:
                logger.warning(
                    "llm_audit_record_build_failed",
                    extra={
                        "event": "llm_audit_record_build_failed",
                        "task": task.value,
                        "decision_id": decision_id,
                        "exc_class": type(exc).__name__,
                        "exc_msg": str(exc),
                    },
                )

        return response

    def _audit_log(
        self,
        *,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        response: LLMResponse,
        snapshot: BudgetSnapshot,
        is_capped: bool,
        decision_id: str | None,
    ) -> None:
        """构造 LLMCallRecord + 调 self._audit.log_call (S2.3 additive).

        本方法 0 raise — LLMCallLogger.log_call 内部包络 try/except,
        失败 → fail-loud warning log + return False (反 break completion 真 caller).
        """
        # 沿用 reviewer Chunk A P3-1 修: assert 消除 type: ignore[union-attr]
        # (caller 真 if self._audit is not None guard, 这里 assert 反 mypy false-positive).
        assert self._audit is not None

        # lazy import 反循环依赖 (audit.py imports from .budget)
        from .audit import LLMCallRecord, compute_prompt_hash

        primary_alias = TASK_TO_MODEL_ALIAS.get(task, "")
        try:
            prompt_hash = compute_prompt_hash(messages)
        except Exception as exc:  # pragma: no cover — sha256 真不应失败
            logger.warning(
                "llm_audit_prompt_hash_failed",
                extra={
                    "event": "llm_audit_prompt_hash_failed",
                    "task": task.value,
                    "exc_class": type(exc).__name__,
                },
            )
            prompt_hash = None

        # 沿用 reviewer Chunk A P2-1 修: latency_ms 0 真当作 unknown → 写 NULL.
        # LLMResponse.latency_ms float=0.0 default 真**永远非 None**, > 0 真已 measure.
        # 0ms 真不可能 (sha256 速度都 > 0.001ms), 0.0 真**默认未 measure** 信号.
        latency_ms_int: int | None
        if response.latency_ms > 0:
            latency_ms_int = int(round(response.latency_ms))
        else:
            latency_ms_int = None

        # sub-PR 8a-followup-B-audit 5-07 BUG #2 fix: error_class dynamic detect 走
        # response.is_fallback signal (反 hardcoded None). 真**Sprint 1 PR #224 success-only
        # audit deferred 沿用 S2.4 真起手** sediment.
        # 4 case 完整 cover (reviewer P1-F2 adopt — 反 silent budget_capped_routing_anomaly):
        # - is_capped=True + is_fallback=True → "budget_capped" (intentional fallback)
        # - is_capped=True + is_fallback=False → "budget_capped_routing_anomaly"
        #     (router 真**返 primary** but budget 真 capped — 反 silent inconsistency, 真**signal**
        #      _is_fallback substring drift / fallback alias rename / etc.)
        # - is_capped=False + is_fallback=True → "primary_fail_fallback_engaged"
        #     (LiteLLM Router internal fallback chain triggered)
        # - is_capped=False + is_fallback=False → None (success path sustained)
        if is_capped and response.is_fallback:
            error_class = "budget_capped"
        elif is_capped and not response.is_fallback:
            error_class = "budget_capped_routing_anomaly"
        elif response.is_fallback:
            error_class = "primary_fail_fallback_engaged"
        else:
            error_class = None

        record = LLMCallRecord(
            task=task,
            primary_alias=primary_alias,
            actual_model=response.model,
            is_fallback=response.is_fallback,
            budget_state=snapshot.state,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            latency_ms=latency_ms_int,
            decision_id=decision_id,
            prompt_hash=prompt_hash,
            error_class=error_class,
        )
        self._audit.log_call(record)

    def _audit_log_failure(
        self,
        *,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        snapshot: BudgetSnapshot,
        is_capped: bool,
        decision_id: str | None,
        exc: BaseException,
    ) -> None:
        """sub-PR 8a-followup-B-audit 5-07 BUG #3 fix: failure path audit log.

        LiteLLM Router completion exception 真**audit row** + error_class=exception class name
        + is_fallback=True (sentinel signal). caller 真**re-raise** 后 audit row 已 persist.

        Args:
            task: original RiskTaskType.
            messages: original prompt messages (for prompt_hash).
            snapshot: BudgetSnapshot at call time.
            is_capped: budget cap state at call time.
            decision_id: caller trace ID (NULL allowed).
            exc: caught exception (类 name 走 error_class).
        """
        assert self._audit is not None

        # lazy import 反循环依赖 (audit.py imports from .budget)
        from .audit import LLMCallRecord, compute_prompt_hash

        primary_alias = TASK_TO_MODEL_ALIAS.get(task, "")
        try:
            prompt_hash = compute_prompt_hash(messages)
        except Exception:  # pragma: no cover — sha256 真不应失败
            prompt_hash = None

        # actual_model 真**NOT NULL** DDL VARCHAR(80) — sentinel 走 80 char 内.
        # 真**反 empty string** 沿用铁律 33 fail-loud (sentinel 真**signal exception path**).
        record = LLMCallRecord(
            task=task,
            primary_alias=primary_alias,
            actual_model="<exception_no_response>",
            is_fallback=True,  # sentinel: exception 真**fallback signal** (反 success path)
            budget_state=snapshot.state,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            latency_ms=None,
            decision_id=decision_id,
            prompt_hash=prompt_hash,
            error_class=type(exc).__name__,
        )
        self._audit.log_call(record)

        # is_capped 真**已 audit 沿用 record.budget_state**, 反**额外 record_cost** 沿用
        # success path 体例 (反 silent decrement). 真**failure path** 真**0 cost call**
        # sustained — budget.record_cost 走 success path only (反 in 本 method scope).
