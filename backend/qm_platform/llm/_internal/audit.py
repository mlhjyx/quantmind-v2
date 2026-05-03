"""LLM Audit Trail — LLMCallLogger + LLMCallRecord + prompt_hash helper.

归属: Framework #LLM 平台 SDK (S2.3 sub-task, V3 §16.2 sediment + ADR-031 §6).

scope (S2.3 — 本 PR):
- LLMCallRecord dataclass (frozen) — 13 字段对齐 llm_call_log 表
- LLMCallLogger 类 — runtime audit log INSERT (走 conn_factory DI, 沿用 BudgetGuard 体例)
- compute_prompt_hash 函数 — sha256 truncated 16 hex (反 md5 collision)
- audit_log 失败 path: try/except 包络 → logger.warning(structured) (反 break completion, 决议 7)

NOT 含 (留下游 / Sprint 8):
- LL-103 SOP-5 5 condition cite (audit BACKFILL SOP, 反 runtime audit log, 决议 3)
- DingTalk push 触发 (走 scripts/llm_cost_daily_report.py 真 daily aggregate, 决议 6)
- V3 §20.2 #3 signature scheme (Sprint 8 sediment)

关联:
- ADR-031 §6 (S2 渐进 deprecate plan)
- V3 §16.2 (LLM 成本 budget)
- backend/qm_platform/llm/budget.py (BudgetAwareRouter 加 optional audit param 体例)
- backend/migrations/2026_05_03_llm_call_log.sql (本模块真依赖表)
- 决议 5 (sha256 truncated 16 hex) / 决议 6 (decision_id NULL 允许) / 决议 7 (fail-loud)

铁律: 31 (Engine 层纯计算 — Logger 走 conn_factory DI, 边界 IO) /
      33 (fail-loud, INSERT 失败 warning log + 反 break completion) /
      34 (Config SSOT) / 41 (timezone — DB clock 服务器时区)
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ..types import LLMMessage, RiskTaskType
from .budget import BudgetState

logger = logging.getLogger(__name__)


@contextmanager
def _conn_cursor(conn: Any) -> Iterator[Any]:
    """psycopg2 with-cursor helper (沿用 budget.py 体例)."""
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


@dataclass(frozen=True)
class LLMCallRecord:
    """单次 LLM 调用 audit 记录 (跟 llm_call_log 13 列对齐).

    Frozen dataclass — 反 caller 改 record (audit 不可篡改, 沿用铁律 33).

    字段:
        task: RiskTaskType enum (7 任务之一).
        primary_alias: task → primary alias (TASK_TO_MODEL_ALIAS cite, 反 fallback 检测漏报).
        actual_model: LiteLLM 真返 model 名 (含 fallback 情况).
        is_fallback: 是否走 qwen3-local fallback (检测路径沿用 PRIMARY_MODEL_SUBSTRINGS).
        budget_state: BudgetState enum (NORMAL / WARN_80 / CAPPED_100).
        tokens_in: prompt tokens (反负数, CHECK 约束 PG 端).
        tokens_out: completion tokens (反负数).
        cost_usd: Decimal (沿用 LLMResponse 体例, 反 float 漂移).
        latency_ms: 调用延迟 (毫秒, None 允许 — record 写 DB 真 NULL).
        decision_id: caller trace ID (NULL 允许, 决议 6 沿用 — 反 break 老 caller).
        prompt_hash: sha256 truncated 16 hex (NULL 允许 — 沿用决议 5, 反 md5 collision).
        error_class: 错误时 exception class name (None on success, 反 silent miss 铁律 33).
    """

    task: RiskTaskType
    primary_alias: str
    actual_model: str
    is_fallback: bool
    budget_state: BudgetState
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    latency_ms: int | None = None
    decision_id: str | None = None
    prompt_hash: str | None = None
    error_class: str | None = None


def compute_prompt_hash(messages: list[LLMMessage] | list[dict[str, str]]) -> str:
    """messages → sha256 truncated 16 hex (沿用 git short hash 体例).

    用 sha256 反 md5 collision 隐患 (决议 5 沿用).
    truncated 16 hex (64 bit) — 16^16 ≈ 1.8e19 候选, collision 概率 audit trail 内可忽略.

    序列化用 JSON sort_keys=True 保证幂等 (反 dict 顺序漂移).

    Args:
        messages: LLMMessage list 或 dict list ({"role": ..., "content": ...}).

    Returns:
        16-char hex (lowercase).
    """
    normalized: list[dict[str, str]] = []
    for m in messages:
        if isinstance(m, LLMMessage):
            normalized.append({"role": m.role, "content": m.content})
        else:
            normalized.append({"role": m.get("role", ""), "content": m.get("content", "")})

    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return digest[:16]


class LLMCallLogger:
    """Runtime LLM call audit log — INSERT llm_call_log 单行 per call.

    依赖:
        conn_factory: callable 返 psycopg2 conn (DI 体例, 沿用 BudgetGuard).

    使用 (BudgetAwareRouter 内调, composition 沿用 ADR-022):
        audit = LLMCallLogger(conn_factory)
        record = LLMCallRecord(
            task=RiskTaskType.JUDGE,
            primary_alias="deepseek-v4-pro",
            actual_model="deepseek/deepseek-reasoner",
            is_fallback=False,
            budget_state=BudgetState.NORMAL,
            tokens_in=120, tokens_out=80,
            cost_usd=Decimal("0.0042"),
            latency_ms=450,
            decision_id="risk-event-uuid",
            prompt_hash=compute_prompt_hash(messages),
            error_class=None,
        )
        audit.log_call(record)

    failure mode (决议 7 沿用铁律 33):
        - INSERT 失败 → logger.warning(structured) + 反 break caller (audit 失败不阻断 LLM 调用)
        - 反 except: pass silent miss (铁律 33)
    """

    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn_factory = conn_factory

    def log_call(self, record: LLMCallRecord) -> bool:
        """INSERT 1 row to llm_call_log (原子, 沿用 risk engine._log_event 体例).

        Returns:
            True on success, False on failure (反 raise — caller 沿用 completion).

        失败 path (决议 7 + 铁律 33):
            - INSERT 异常捕获 → logger.warning(structured) + return False
            - 反 break BudgetAwareRouter.completion (audit 失败不阻断 LLM)
        """
        try:
            conn = self._conn_factory()
        except Exception as exc:
            logger.warning(
                "llm_audit_conn_factory_failed",
                extra={
                    "event": "llm_audit_conn_factory_failed",
                    "task": record.task.value,
                    "decision_id": record.decision_id,
                    "exc_class": type(exc).__name__,
                    "exc_msg": str(exc),
                },
            )
            return False

        try:
            with _conn_cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO llm_call_log (
                        triggered_at, task, primary_alias, actual_model,
                        is_fallback, budget_state,
                        tokens_in, tokens_out, cost_usd, latency_ms,
                        decision_id, prompt_hash, error_class
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        datetime.now(UTC),
                        record.task.value,
                        record.primary_alias,
                        record.actual_model,
                        record.is_fallback,
                        record.budget_state.value,
                        record.tokens_in,
                        record.tokens_out,
                        record.cost_usd,
                        record.latency_ms,
                        record.decision_id,
                        record.prompt_hash,
                        record.error_class,
                    ),
                )
            conn.commit()
            return True
        except Exception as exc:
            # fail-loud warning (反 silent miss, 铁律 33). caller 沿用走 completion.
            logger.warning(
                "llm_audit_insert_failed",
                extra={
                    "event": "llm_audit_insert_failed",
                    "task": record.task.value,
                    "actual_model": record.actual_model,
                    "decision_id": record.decision_id,
                    "exc_class": type(exc).__name__,
                    "exc_msg": str(exc),
                },
            )
            # silent_ok: rollback 失败时 conn 必将走 close (沿用铁律 33 silent_ok 注释)
            with suppress(Exception):
                conn.rollback()
            return False
        finally:
            # silent_ok: close 失败 0 影响调用方 (沿用铁律 33 silent_ok 注释)
            with suppress(Exception):
                conn.close()
