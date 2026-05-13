"""S8 8c-partial Celery sweep task tests — l4_sweep_tasks (PENDING_CONFIRM expired → TIMEOUT_EXECUTED).

Coverage:
- Happy path: 1 expired row → 1 UPDATE → transitioned=1
- Empty path: 0 expired rows → scanned=0, no UPDATE
- Multi-row: 3 expired rows → 3 UPDATEs all transition
- Race: SELECT returned row, but UPDATE rowcount=0 (concurrent webhook) → race counted
- Batch limit: SELECT returns SWEEP_BATCH_LIMIT rows → batch_limited=True
- Beat schedule entry exists with correct cron + queue + expires
- Task registered with celery_app under canonical name
- Task module in celery_app imports list (反 unregistered Beat dispatch)
- 铁律 32: inner sweep does NOT call conn.commit (caller=task body owns transaction)

关联铁律: 32 / 33 / 44 X9
关联 ADR: ADR-058 NEW (8c-partial sediment, post-merge)
关联 LL: LL-152 NEW (8c-partial sediment, post-merge)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.tasks import l4_sweep_tasks as l4t
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app

# ── Test helpers ──


def _make_mock_conn(
    *,
    select_rows: list[tuple] | None = None,
    update_rowcounts: list[int] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build a psycopg2-compatible mock conn that returns select_rows on SELECT
    and reports update_rowcounts in sequence on subsequent UPDATE calls.

    Returns (conn, cursor) for assertion access.
    """
    conn = MagicMock()
    cursor = MagicMock()
    column_names = ["plan_id", "symbol_id", "qty", "cancel_deadline", "created_at"]
    desc_items = [type("Col", (), {"name": n})() for n in column_names]

    update_iter = iter(update_rowcounts or [])

    def execute_side_effect(sql: str, params: tuple) -> None:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT"):
            cursor.description = desc_items
            cursor.fetchall = MagicMock(return_value=select_rows or [])
        else:  # UPDATE
            try:
                cursor.rowcount = next(update_iter)
            except StopIteration:
                cursor.rowcount = 0  # default: race

    cursor.execute = MagicMock(side_effect=execute_side_effect)
    cursor.close = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    return conn, cursor


def _row(
    plan_id: str, symbol_id: str = "600519.SH", qty: int = 100, deadline: datetime | None = None
) -> tuple:
    """Build a tuple matching the SELECT column order."""
    if deadline is None:
        deadline = datetime(2026, 5, 13, 14, 0, tzinfo=UTC) - timedelta(minutes=1)
    created = deadline - timedelta(minutes=30)
    return (plan_id, symbol_id, qty, deadline, created)


# §1 Task registration


def test_task_registered_in_celery_app() -> None:
    """sweep_pending_confirm_plans is registered under canonical task name."""
    assert "app.tasks.l4_sweep_tasks.sweep_pending_confirm_plans" in celery_app.tasks


def test_task_module_in_celery_imports() -> None:
    """celery_app.conf.imports contains the module (反 Beat → unregistered error)."""
    imports = celery_app.conf.get("imports") or []
    assert "app.tasks.l4_sweep_tasks" in imports


# §2 Beat schedule entry


def test_beat_schedule_entry_exists() -> None:
    """risk-l4-sweep-1min entry exists in CELERY_BEAT_SCHEDULE."""
    assert "risk-l4-sweep-1min" in CELERY_BEAT_SCHEDULE


def test_beat_schedule_entry_correct() -> None:
    """Beat entry points to canonical task name with queue+expires."""
    entry = CELERY_BEAT_SCHEDULE["risk-l4-sweep-1min"]
    assert entry["task"] == "app.tasks.l4_sweep_tasks.sweep_pending_confirm_plans"
    assert entry["options"]["queue"] == "default"
    # 45s within next 60s cycle (反 overlap)
    assert entry["options"]["expires"] == 45


def test_beat_schedule_entry_trading_hours_only() -> None:
    """cron: every minute, hour 9-14 (Asia/Shanghai), Mon-Fri."""
    schedule = CELERY_BEAT_SCHEDULE["risk-l4-sweep-1min"]["schedule"]
    # Every minute (0..59)
    assert schedule.minute == set(range(60))
    # Hour 9-14 (covers 9:00-14:59 + the auction window context)
    assert schedule.hour == {9, 10, 11, 12, 13, 14}
    # Mon-Fri
    assert schedule.day_of_week == {1, 2, 3, 4, 5}


# §3 Inner sweep happy paths


def test_sweep_inner_no_rows_zero_op() -> None:
    """Empty SELECT → scanned=0, no UPDATE calls."""
    conn, cur = _make_mock_conn(select_rows=[])
    result = l4t._sweep_inner(conn=conn)
    # 8c-followup added executed/broker_failed/broker_race keys (default 0 when
    # staged_service not injected, sustained for legacy callers).
    assert result == {
        "ok": True,
        "scanned": 0,
        "transitioned": 0,
        "races": 0,
        "executed": 0,
        "broker_failed": 0,
        "broker_race": 0,
        "batch_limited": False,
    }
    # Only 1 execute (the SELECT) — no UPDATE
    assert cur.execute.call_count == 1


def test_sweep_inner_one_expired_row_transitions() -> None:
    """1 expired row + UPDATE rowcount=1 → transitioned=1."""
    conn, cur = _make_mock_conn(
        select_rows=[_row("plan-1")],
        update_rowcounts=[1],
    )
    result = l4t._sweep_inner(conn=conn)
    assert result["scanned"] == 1
    assert result["transitioned"] == 1
    assert result["races"] == 0
    assert result["batch_limited"] is False
    # SELECT + 1 UPDATE = 2 executes
    assert cur.execute.call_count == 2


def test_sweep_inner_three_expired_rows_all_transition() -> None:
    """3 expired rows + 3 UPDATE rowcount=1 → transitioned=3."""
    conn, cur = _make_mock_conn(
        select_rows=[_row("p-1"), _row("p-2"), _row("p-3")],
        update_rowcounts=[1, 1, 1],
    )
    result = l4t._sweep_inner(conn=conn)
    assert result["scanned"] == 3
    assert result["transitioned"] == 3
    assert result["races"] == 0
    # SELECT + 3 UPDATE = 4 executes
    assert cur.execute.call_count == 4


# §4 Race conditions


def test_sweep_inner_race_increments_races_count() -> None:
    """UPDATE rowcount=0 → race counted, NOT transitioned."""
    conn, cur = _make_mock_conn(
        select_rows=[_row("p-1")],
        update_rowcounts=[0],  # concurrent webhook stole it
    )
    result = l4t._sweep_inner(conn=conn)
    assert result["scanned"] == 1
    assert result["transitioned"] == 0
    assert result["races"] == 1


def test_sweep_inner_mixed_transitions_and_races() -> None:
    """5 expired rows; 3 transition + 2 race (concurrent webhook)."""
    conn, _ = _make_mock_conn(
        select_rows=[_row(f"p-{i}") for i in range(5)],
        update_rowcounts=[1, 0, 1, 0, 1],
    )
    result = l4t._sweep_inner(conn=conn)
    assert result["scanned"] == 5
    assert result["transitioned"] == 3
    assert result["races"] == 2


# §5 Batch limit


def test_sweep_inner_batch_limit_flag() -> None:
    """When SELECT returns exactly SWEEP_BATCH_LIMIT rows, batch_limited=True."""
    limit = 3
    conn, _ = _make_mock_conn(
        select_rows=[_row(f"p-{i}") for i in range(limit)],
        update_rowcounts=[1] * limit,
    )
    result = l4t._sweep_inner(conn=conn, limit=limit)
    assert result["scanned"] == limit
    assert result["batch_limited"] is True


def test_sweep_inner_below_batch_limit_flag() -> None:
    """When SELECT returns < limit rows, batch_limited=False."""
    limit = 10
    conn, _ = _make_mock_conn(
        select_rows=[_row(f"p-{i}") for i in range(3)],
        update_rowcounts=[1, 1, 1],
    )
    result = l4t._sweep_inner(conn=conn, limit=limit)
    assert result["scanned"] == 3
    assert result["batch_limited"] is False


# §6 铁律 32 — caller transaction boundary


def test_sweep_inner_does_not_commit() -> None:
    """_sweep_inner never calls conn.commit / conn.rollback (caller owns tx)."""
    conn, _ = _make_mock_conn(
        select_rows=[_row("p-1")],
        update_rowcounts=[1],
    )
    l4t._sweep_inner(conn=conn)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


# §7 SWEEP_BATCH_LIMIT constant


def test_sweep_batch_limit_const() -> None:
    """SWEEP_BATCH_LIMIT is 100 (反 silent change to a value that floods Beat tick)."""
    assert l4t.SWEEP_BATCH_LIMIT == 100


# §8 8c-followup broker wire — staged_service injection


class _StagedServiceStub:
    """Records execute_plan calls + returns staged outcomes via injected sequence."""

    def __init__(self, outcomes: list[str], order_ids: list[str | None] | None = None) -> None:
        # Local import avoids cyclic / unused-import issues at module top
        from app.services.risk.staged_execution_service import (
            StagedExecutionOutcome,
            StagedExecutionServiceResult,
        )

        self._StagedExecutionOutcome = StagedExecutionOutcome
        self._StagedExecutionServiceResult = StagedExecutionServiceResult
        self._outcomes = [StagedExecutionOutcome(o) for o in outcomes]
        self._order_ids = order_ids or [f"stub-{i}" for i in range(len(outcomes))]
        self.calls: list[str] = []

    def execute_plan(self, *, plan_id: str, conn) -> object:  # noqa: ARG002
        self.calls.append(plan_id)
        idx = len(self.calls) - 1
        outcome = self._outcomes[idx] if idx < len(self._outcomes) else self._outcomes[-1]
        order_id = self._order_ids[idx] if idx < len(self._order_ids) else None
        # Build a minimal result — broker_executor.PlanStatus not required here;
        # the inner sweep only reads .outcome / .broker_order_id / .error_msg.
        return self._StagedExecutionServiceResult(
            outcome=outcome,
            plan_id=plan_id,
            broker_order_id=order_id,
            final_status=None,
            error_msg=None if outcome == self._StagedExecutionOutcome.EXECUTED else "stub_err",
            message="stub",
        )


def test_sweep_inner_broker_wire_executed_counter() -> None:
    """staged_service injected → executed counter increments per EXECUTED outcome."""
    conn, _cur = _make_mock_conn(
        select_rows=[_row("p-1"), _row("p-2"), _row("p-3")],
        update_rowcounts=[1, 1, 1],
    )
    stub = _StagedServiceStub(outcomes=["executed", "executed", "executed"])
    result = l4t._sweep_inner(conn=conn, staged_service=stub)
    assert result["transitioned"] == 3
    assert result["executed"] == 3
    assert result["broker_failed"] == 0
    assert result["broker_race"] == 0
    # staged_service invoked once per successful TIMEOUT_EXECUTED transition
    assert len(stub.calls) == 3
    assert stub.calls == ["p-1", "p-2", "p-3"]


def test_sweep_inner_broker_wire_mixed_outcomes() -> None:
    """Mixed broker outcomes → counters increment independently."""
    conn, _cur = _make_mock_conn(
        select_rows=[_row(f"p-{i}") for i in range(4)],
        update_rowcounts=[1, 1, 1, 1],
    )
    stub = _StagedServiceStub(outcomes=["executed", "failed", "executed", "race"])
    result = l4t._sweep_inner(conn=conn, staged_service=stub)
    assert result["transitioned"] == 4
    assert result["executed"] == 2
    assert result["broker_failed"] == 1
    assert result["broker_race"] == 1


def test_sweep_inner_broker_wire_skipped_when_no_service() -> None:
    """staged_service=None (default) — broker counters stay 0; sweep still works."""
    conn, _cur = _make_mock_conn(
        select_rows=[_row("p-1")],
        update_rowcounts=[1],
    )
    result = l4t._sweep_inner(conn=conn)  # default staged_service=None
    assert result["transitioned"] == 1
    assert result["executed"] == 0
    assert result["broker_failed"] == 0
    assert result["broker_race"] == 0


def test_sweep_inner_broker_wire_not_called_on_race() -> None:
    """When TIMEOUT_EXECUTED UPDATE rowcount=0 (race), broker is NOT invoked."""
    conn, _cur = _make_mock_conn(
        select_rows=[_row("p-1")],
        update_rowcounts=[0],  # concurrent webhook stole the row
    )
    stub = _StagedServiceStub(outcomes=["executed"])
    result = l4t._sweep_inner(conn=conn, staged_service=stub)
    # No TIMEOUT_EXECUTED transition happened → no broker call
    assert result["transitioned"] == 0
    assert result["races"] == 1
    assert result["executed"] == 0
    assert len(stub.calls) == 0
