"""Unit tests for StagedExecutionService (S8 8c-followup).

覆盖:
  - execute_plan: SUCCESS path CONFIRMED → broker.sell → EXECUTED + UPDATE
  - execute_plan: SUCCESS path TIMEOUT_EXECUTED → broker.sell → EXECUTED + UPDATE
  - execute_plan: broker rejection → FAILED + UPDATE (broker_order_id=None)
  - execute_plan: plan_id not found → NOT_FOUND
  - execute_plan: plan status not executable (PENDING_CONFIRM/CANCELLED/...) → NOT_EXECUTABLE
  - execute_plan: race UPDATE rowcount=0 → RACE outcome
  - 铁律 32: service does NOT call conn.commit / conn.rollback
  - broker_order_id + broker_fill_status persisted in UPDATE params

关联铁律: 32 (caller transaction boundary) / 33 (fail-loud)
关联 ADR: ADR-059 NEW (S8 8c-followup sediment)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from app.services.risk.staged_execution_service import (
    StagedExecutionOutcome,
    StagedExecutionService,
)
from backend.qm_platform.risk.execution.planner import PlanStatus

# ── Mock helpers ──


_PLAN_COLUMNS = [
    "plan_id",
    "status",
    "mode",
    "symbol_id",
    "qty",
    "limit_price",
    "batch_index",
    "batch_total",
    "scheduled_at",
    "cancel_deadline",
    "broker_order_id",
    "broker_fill_status",
    "risk_reason",
    "user_decision",
    "user_decision_at",
    "triggered_by_event_id",
    "risk_metrics",
    "created_at",
]


def _make_plan_row(
    *,
    plan_id: str = "abc12345-0000-0000-0000-000000000001",
    status: str = "CONFIRMED",
    symbol_id: str = "600519.SH",
    qty: int = 1000,
) -> tuple:
    now = datetime.now(UTC)
    return (
        plan_id,  # plan_id
        status,  # status
        "STAGED",  # mode
        symbol_id,  # symbol_id
        qty,  # qty
        98.0,  # limit_price
        1,  # batch_index
        1,  # batch_total
        now,  # scheduled_at
        now + timedelta(minutes=30),  # cancel_deadline
        None,  # broker_order_id
        None,  # broker_fill_status
        "test",  # risk_reason
        "confirm",  # user_decision
        now,  # user_decision_at
        None,  # triggered_by_event_id
        {},  # risk_metrics
        now,  # created_at
    )


class _SqlCapturingConn:
    """psycopg2-compatible mock that records every execute + lets caller stage results."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, tuple]] = []  # (sql, params)
        self._selection_rows: list[tuple | None] = []
        self._rowcounts: list[int] = []
        # Indices persist across cursor() calls so multi-cursor flows (_load_plan
        # → race UPDATE → re-_load_plan) consume staged values in order.
        self._select_idx = 0
        self._rowcount_idx = 0

    def stage_select(self, row: tuple | None) -> None:
        self._selection_rows.append(row)

    def stage_update_rowcount(self, n: int) -> None:
        self._rowcounts.append(n)

    def _next_select(self) -> tuple | None:
        if self._select_idx >= len(self._selection_rows):
            return None
        row = self._selection_rows[self._select_idx]
        self._select_idx += 1
        return row

    def _next_rowcount(self) -> int:
        if self._rowcount_idx >= len(self._rowcounts):
            return 0
        n = self._rowcounts[self._rowcount_idx]
        self._rowcount_idx += 1
        return n

    def cursor(self) -> MagicMock:  # noqa: D401 — match psycopg2
        cur = MagicMock()
        cur.description = [type("Col", (), {"name": n})() for n in _PLAN_COLUMNS]

        def execute(sql: str, params: tuple) -> None:
            self.executes.append((sql.strip(), params))
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("SELECT"):
                cur.fetchone = MagicMock(return_value=self._next_select())
            elif sql_upper.startswith("UPDATE"):
                cur.rowcount = self._next_rowcount()

        cur.execute = MagicMock(side_effect=execute)
        cur.close = MagicMock()
        return cur

    @property
    def update_calls(self) -> list[tuple[str, tuple]]:
        return [e for e in self.executes if e[0].upper().startswith("UPDATE")]


def _stub_broker_success(*args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG001
    return {
        "status": "ok",
        "code": "600519.SH",
        "shares": 1000,
        "filled_shares": 0,
        "price": 0.0,
        "order_id": "BROKER-001",
        "error": None,
    }


def _stub_broker_rejection(*args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG001
    return {
        "status": "rejected",
        "code": "600519.SH",
        "shares": 1000,
        "filled_shares": 0,
        "price": 0.0,
        "order_id": None,
        "error": "live_trading_disabled",
    }


# ── SUCCESS path ──


class TestExecutePlanSuccess:
    def test_confirmed_to_executed(self) -> None:
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="CONFIRMED"))
        conn.stage_update_rowcount(1)

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.EXECUTED
        assert result.plan_id == plan_id
        assert result.broker_order_id == "BROKER-001"
        assert result.final_status == PlanStatus.EXECUTED
        # UPDATE persisted the order_id
        update_sql, update_params = conn.update_calls[0]
        assert "broker_order_id" in update_sql
        # params: (status, broker_order_id, broker_fill_status, plan_id, executable_status_tuple)
        assert update_params[0] == "EXECUTED"
        assert update_params[1] == "BROKER-001"
        assert update_params[3] == plan_id

    def test_timeout_executed_to_executed(self) -> None:
        plan_id = "ffff0000-0000-0000-0000-000000000099"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="TIMEOUT_EXECUTED"))
        conn.stage_update_rowcount(1)

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.EXECUTED
        assert result.final_status == PlanStatus.EXECUTED


# ── FAILURE path ──


class TestExecutePlanFailure:
    def test_broker_rejection_marks_failed(self) -> None:
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="CONFIRMED"))
        conn.stage_update_rowcount(1)

        svc = StagedExecutionService(broker_call=_stub_broker_rejection)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.FAILED
        assert result.broker_order_id is None
        assert result.final_status == PlanStatus.FAILED
        assert "live_trading_disabled" in (result.error_msg or "")
        # UPDATE wrote FAILED, broker_order_id=None
        update_sql, update_params = conn.update_calls[0]
        assert update_params[0] == "FAILED"
        assert update_params[1] is None  # broker_order_id

    def test_not_found(self) -> None:
        conn = _SqlCapturingConn()
        conn.stage_select(None)  # no row

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id="nonexistent-uuid", conn=conn)

        assert result.outcome == StagedExecutionOutcome.NOT_FOUND
        assert result.plan_id == "nonexistent-uuid"
        # No UPDATE happened
        assert len(conn.update_calls) == 0

    def test_not_executable_for_pending_confirm(self) -> None:
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="PENDING_CONFIRM"))

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.NOT_EXECUTABLE
        assert result.final_status == PlanStatus.PENDING_CONFIRM
        assert len(conn.update_calls) == 0

    def test_not_executable_for_already_executed(self) -> None:
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="EXECUTED"))

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.NOT_EXECUTABLE
        assert len(conn.update_calls) == 0


# ── Race condition ──


class TestExecutePlanRace:
    def test_race_update_rowcount_zero_returns_race(self) -> None:
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        # First SELECT: row exists in CONFIRMED state
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="CONFIRMED"))
        # UPDATE returns 0 rows (concurrent transition)
        conn.stage_update_rowcount(0)
        # Re-read after race: status now EXECUTED by other worker
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="EXECUTED"))

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        result = svc.execute_plan(plan_id=plan_id, conn=conn)

        assert result.outcome == StagedExecutionOutcome.RACE
        assert result.final_status == PlanStatus.EXECUTED  # refreshed state


# ── 铁律 32 ──


class TestNoCommit:
    def test_service_does_not_commit_on_success(self) -> None:
        """铁律 32: service does NOT call conn.commit() or conn.rollback()."""
        plan_id = "abc12345-0000-0000-0000-000000000001"
        conn = _SqlCapturingConn()
        conn.stage_select(_make_plan_row(plan_id=plan_id, status="CONFIRMED"))
        conn.stage_update_rowcount(1)
        # Sentinel methods on conn to detect any call
        commit_called = MagicMock()
        rollback_called = MagicMock()
        # Wrap on the conn object — the MagicMock cursor is a separate object
        original_cursor = conn.cursor

        wrapper = MagicMock(spec=object)
        wrapper.cursor = original_cursor
        wrapper.commit = commit_called
        wrapper.rollback = rollback_called

        svc = StagedExecutionService(broker_call=_stub_broker_success)
        svc.execute_plan(plan_id=plan_id, conn=wrapper)

        assert commit_called.call_count == 0
        assert rollback_called.call_count == 0
