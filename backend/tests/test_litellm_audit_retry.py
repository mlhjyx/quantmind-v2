"""sub-PR 8b-llm-audit-S2.4 5-07 — LLMCallLogger retry policy smoke tests (ADR-039).

scope (~180 line, single chunk per LL-100):
- transient retry path: OperationalError 1x then success → True (1 retry, 1 success log)
- transient retry path: InterfaceError 2x then success → True (2 retries within max)
- transient exhaustion: OperationalError 3x → False (max retries, fail-loud log)
- permanent fail-fast: ProgrammingError 1x → False (no retry attempt)
- conn_factory failure: caller exception → False (existing behavior preserved)
- backoff timing: total elapsed < 1s for max retries

真生产证据沿用 5-07 sub-PR 8b-llm-audit-S2.4 ADR-039:
- retry policy 真**transient/permanent classifier** sustained (反 silent miss 铁律 33)
- max retry overhead 0.3s 真**caller latency budget** ~5s 反 break completion sustained sub-PR 7c

关联铁律:
- 33 (fail-loud — retry success + retry failure structured event log sustained)
- 41 (timezone — DB clock 服务器时区, retry preserves now() UTC semantics)
- 42 (PR 分级审查制 — backend/qm_platform/llm/** + backend/tests/** 沿用 reviewer 体例)
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock

from backend.qm_platform.llm._internal.audit import (
    _TRANSIENT_DB_EXC_CLASSES,
    LLMCallLogger,
    LLMCallRecord,
)
from backend.qm_platform.llm._internal.budget import BudgetState
from backend.qm_platform.llm.types import RiskTaskType

# ── Fake transient/permanent exception classes ──


class OperationalError(Exception):
    """Mimics psycopg2.OperationalError — class name match _TRANSIENT_DB_EXC_CLASSES."""


class InterfaceError(Exception):
    """Mimics psycopg2.InterfaceError — class name match transient set."""


class SerializationFailure(Exception):  # noqa: N818
    """Mimics psycopg2.errors.SerializationFailure — deadlock retry.

    N818 suppressed: 真生产 psycopg2 class 真**0 Error suffix** sustained.
    Test class name 真 align _TRANSIENT_DB_EXC_CLASSES heuristic match (string compare).
    """


class ProgrammingError(Exception):
    """Mimics psycopg2.ProgrammingError — permanent (schema mismatch)."""


class IntegrityError(Exception):
    """Mimics psycopg2.IntegrityError — permanent (constraint violation)."""


# ── Test helper ──


def _make_record() -> LLMCallRecord:
    return LLMCallRecord(
        task=RiskTaskType.NEWS_CLASSIFY,
        primary_alias="deepseek-v4-flash",
        actual_model="deepseek-v4-flash",
        is_fallback=False,
        budget_state=BudgetState.NORMAL,
        tokens_in=10,
        tokens_out=5,
        cost_usd=Decimal("0.0001"),
        latency_ms=500,
        decision_id="test-001",
        prompt_hash="abc123def456",
        error_class=None,
    )


def _make_conn(execute_side_effects: list) -> MagicMock:
    """Build mock psycopg2 conn whose cursor.execute applies side_effects in order.

    side_effects entries:
      - None → success (no exception)
      - Exception instance → raise on that attempt
    """
    conn = MagicMock()
    cur = MagicMock()
    cur.execute.side_effect = execute_side_effects
    conn.cursor.return_value = cur
    return conn


# ── Whitelist correctness ──


def test_transient_db_exc_classes_contains_psycopg2_transient() -> None:
    """白名单含 psycopg2 真 connection-level / cursor-level / deadlock 体例."""
    assert "OperationalError" in _TRANSIENT_DB_EXC_CLASSES
    assert "InterfaceError" in _TRANSIENT_DB_EXC_CLASSES
    assert "SerializationFailure" in _TRANSIENT_DB_EXC_CLASSES


def test_transient_db_exc_classes_excludes_permanent() -> None:
    """白名单反含 permanent (ProgrammingError / IntegrityError) 沿用 fail-fast 体例."""
    forbidden = {"ProgrammingError", "IntegrityError", "DataError", "NotNullViolation"}
    assert not (set(_TRANSIENT_DB_EXC_CLASSES) & forbidden)


# ── Transient retry success ──


def test_transient_operational_retry_success_first_attempt() -> None:
    """OperationalError 1x then success → True (1 retry, attempts=2)."""
    conn = _make_conn([OperationalError("connection lost"), None])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is True
    assert conn.cursor.return_value.execute.call_count == 2
    assert conn.commit.called


def test_transient_interface_retry_success_second_attempt() -> None:
    """InterfaceError 2x then success → True (2 retries, attempts=3)."""
    conn = _make_conn([InterfaceError("e1"), InterfaceError("e2"), None])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is True
    assert conn.cursor.return_value.execute.call_count == 3


def test_transient_serialization_retry_success() -> None:
    """SerializationFailure 1x then success → True."""
    conn = _make_conn([SerializationFailure("deadlock detected"), None])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is True


# ── Transient retry exhausted ──


def test_transient_operational_retry_exhausted() -> None:
    """OperationalError 3x → False (max_retries=2 → 3 total attempts exhausted)."""
    conn = _make_conn([OperationalError("e1"), OperationalError("e2"), OperationalError("e3")])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is False
    assert conn.cursor.return_value.execute.call_count == 3
    assert conn.rollback.called


# ── Permanent fail-fast (no retry) ──


def test_permanent_programming_error_no_retry() -> None:
    """ProgrammingError 1x → False, NO retry attempt."""
    conn = _make_conn([ProgrammingError("syntax error in SQL")])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is False
    # 真**1 attempt only** sustained (反 retry permanent error)
    assert conn.cursor.return_value.execute.call_count == 1


def test_permanent_integrity_error_no_retry() -> None:
    """IntegrityError 1x → False, NO retry attempt (constraint violation)."""
    conn = _make_conn([IntegrityError("FK violation")])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is False
    assert conn.cursor.return_value.execute.call_count == 1


# ── conn_factory failure (preserved behavior) ──


def test_conn_factory_failure_returns_false() -> None:
    """conn_factory raises → False (no retry, no Insert attempt)."""

    def factory():
        raise OperationalError("DB pool exhausted")

    logger = LLMCallLogger(conn_factory=factory, max_retries=2, retry_wait_base=0.01)
    assert logger.log_call(_make_record()) is False


# ── Happy path (no retry needed) ──


def test_happy_path_first_attempt_success() -> None:
    """成功 first attempt → True (1 attempt, no retry overhead)."""
    conn = _make_conn([None])
    factory = MagicMock(return_value=conn)
    logger = LLMCallLogger(conn_factory=factory)
    assert logger.log_call(_make_record()) is True
    assert conn.cursor.return_value.execute.call_count == 1


# ── Backoff timing ──


def test_backoff_timing_within_budget() -> None:
    """exhausted retries 真**total elapsed** < 1s 沿用 break completion budget sustained."""
    conn = _make_conn([OperationalError("e1"), OperationalError("e2"), OperationalError("e3")])
    factory = MagicMock(return_value=conn)
    # Default retry_wait_base=0.1 → 0.1 + 0.2 = 0.3s expected sleep total
    logger = LLMCallLogger(conn_factory=factory, max_retries=2)
    t0 = time.perf_counter()
    logger.log_call(_make_record())
    elapsed = time.perf_counter() - t0
    # Allow 0.5s headroom for mocking + clock jitter
    assert elapsed < 1.0, f"retry overhead too long: {elapsed:.3f}s"


# ── Default retry config ──


def test_default_max_retries_is_2() -> None:
    """DEFAULT_MAX_RETRIES=2 真**3 total attempts** sustained ADR-039."""
    assert LLMCallLogger.DEFAULT_MAX_RETRIES == 2


def test_default_retry_wait_base_is_0_1() -> None:
    """DEFAULT_RETRY_WAIT_BASE=0.1 真**exponential backoff base** sustained ADR-039."""
    assert LLMCallLogger.DEFAULT_RETRY_WAIT_BASE == 0.1
