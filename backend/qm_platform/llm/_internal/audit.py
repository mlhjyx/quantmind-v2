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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ..types import LLMMessage, RiskTaskType
from .budget import BudgetState

logger = logging.getLogger(__name__)

# 5-07 sub-PR 8b-llm-audit-S2.4 ADR-039: transient DB error class names 真 heuristic
# (反 hard psycopg2 import couple — audit module 沿用 conn:Any 真**connection-agnostic**
# 体例 sustained sub-PR 7c contract). 真**connection-level / cursor-level transient**:
#   - psycopg2.OperationalError (connection lost, server error)
#   - psycopg2.InterfaceError (cursor or connection state error)
#   - psycopg2.errors.SerializationFailure (deadlock retry)
# 反 permanent (no retry):
#   - psycopg2.ProgrammingError (SQL schema mismatch)
#   - psycopg2.IntegrityError (constraint violation, retry won't help)
_TRANSIENT_DB_EXC_CLASSES: frozenset[str] = frozenset(
    {
        "OperationalError",
        "InterfaceError",
        "SerializationFailure",
    }
)


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

    # 5-07 sub-PR 8b-llm-audit-S2.4 ADR-039 retry policy defaults.
    # max_retries=2 真**3 total attempts** (initial + 2 retry) sustained.
    # backoff: 0.1s → 0.2s (max ~0.3s total) — 反**break completion** sustained
    # sub-PR 7c contract. caller 真生产 latency budget ~5s (V3 §16.2 cost guardrails),
    # audit retry overhead ~0.3s 沿用 acceptable.
    DEFAULT_MAX_RETRIES: int = 2
    DEFAULT_RETRY_WAIT_BASE: float = 0.1

    def __init__(
        self,
        conn_factory: Callable[[], Any],
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_wait_base: float = DEFAULT_RETRY_WAIT_BASE,
    ) -> None:
        """Initialize LLMCallLogger with retry policy (ADR-039 sediment).

        Args:
            conn_factory: callable 返 psycopg2 conn (DI 体例, 沿用 BudgetGuard).
            max_retries: 真**transient DB error retry count** (默认 2 真 3 attempts total).
            retry_wait_base: 真**exponential backoff base seconds** (默认 0.1).
        """
        self._conn_factory = conn_factory
        self._max_retries = max_retries
        self._retry_wait_base = retry_wait_base

    def log_call(self, record: LLMCallRecord) -> bool:
        """INSERT 1 row to llm_call_log (沿用 risk engine._log_event 体例 + ADR-039 retry).

        Returns:
            True on success (含 retry success), False on failure (反 raise).

        失败 path (决议 7 + 铁律 33 + ADR-039 retry):
            - transient DB error (OperationalError/InterfaceError/SerializationFailure)
              真**retry up to max_retries** with exponential backoff (反 silent miss
              真生产 transient connection loss 漂移 sustained S2.4 sub-task closure).
            - permanent error (ProgrammingError/IntegrityError 等) 真**immediate fail-loud**
              (沿用铁律 33 + 反**retry permanent same error** waste budget).
            - exhausted retries → logger.warning(structured) + return False.
            - 反 break BudgetAwareRouter.completion (audit 失败不阻断 LLM).
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
            return self._insert_with_retry(conn, record)
        finally:
            # silent_ok: close 失败 0 影响调用方 (沿用铁律 33 silent_ok 注释)
            with suppress(Exception):
                conn.close()

    def _insert_with_retry(self, conn: Any, record: LLMCallRecord) -> bool:
        """INSERT 真**retry on transient DB error** (5-07 sub-PR 8b-llm-audit-S2.4 ADR-039).

        Retry rule:
            - transient (_TRANSIENT_DB_EXC_CLASSES match): retry with exponential backoff
              `retry_wait_base * 2^attempt` (e.g. 0.1, 0.2, 0.4 ...).
            - permanent (其他 Exception subclass): immediate fail-loud (反 retry
              same permanent error waste budget).
            - exhausted retries: logger.warning + return False (反 break caller completion).
        """
        attempt = 0
        last_exc: Exception | None = None
        is_transient = False

        while attempt <= self._max_retries:
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
                if attempt > 0:
                    # 真**retry success** sediment 沿用铁律 33 fail-loud event log
                    logger.warning(
                        "llm_audit_insert_retry_success",
                        extra={
                            "event": "llm_audit_insert_retry_success",
                            "task": record.task.value,
                            "actual_model": record.actual_model,
                            "decision_id": record.decision_id,
                            "attempts": attempt + 1,
                        },
                    )
                return True
            except Exception as exc:
                last_exc = exc
                is_transient = type(exc).__name__ in _TRANSIENT_DB_EXC_CLASSES
                with suppress(Exception):
                    conn.rollback()
                if not is_transient or attempt >= self._max_retries:
                    break
                # transient + still have retry budget — exponential backoff
                wait_seconds = self._retry_wait_base * (2**attempt)
                time.sleep(wait_seconds)
                attempt += 1

        # Exhausted retries OR permanent error
        logger.warning(
            "llm_audit_insert_failed",
            extra={
                "event": "llm_audit_insert_failed",
                "task": record.task.value,
                "actual_model": record.actual_model,
                "decision_id": record.decision_id,
                "exc_class": type(last_exc).__name__ if last_exc else "Unknown",
                "exc_msg": str(last_exc) if last_exc else "",
                "attempts": attempt + 1,
                "transient": is_transient,
            },
        )
        return False
