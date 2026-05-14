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
from typing import Any
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


# ─────────────────────────────────────────────────────────────
# HC-2b2 G7 — broker plan stuck sweep + BROKER_PLAN_STUCK 元告警 (V3 §14 mode 12)
# ─────────────────────────────────────────────────────────────


def _make_stuck_mock_conn(*, select_rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
    """Mock conn for _sweep_stuck_inner — SELECT returns (plan_id, status, stuck_since)."""
    conn = MagicMock()
    cursor = MagicMock()
    desc_items = [type("Col", (), {"name": n})() for n in ("plan_id", "status", "stuck_since")]

    def execute_side_effect(sql: str, params: tuple) -> None:  # noqa: ARG001
        cursor.description = desc_items
        cursor.fetchall = MagicMock(return_value=select_rows or [])

    cursor.execute = MagicMock(side_effect=execute_side_effect)
    cursor.close = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    return conn, cursor


def _stuck_row(
    plan_id: str, status: str = "CONFIRMED", stuck_since: datetime | None = None
) -> tuple:
    if stuck_since is None:
        stuck_since = datetime(2026, 5, 14, 9, 0, tzinfo=UTC)
    return (plan_id, status, stuck_since)


class _StuckStagedStub:
    """execute_plan — returns a result for normal plan_ids, raises for plan_ids in `fail`."""

    def __init__(self, *, fail: dict[str, Exception] | None = None) -> None:
        self._fail = fail or {}
        self.calls: list[str] = []

    def execute_plan(self, *, plan_id: str, conn: Any) -> object:  # noqa: ARG002
        self.calls.append(plan_id)
        if plan_id in self._fail:
            raise self._fail[plan_id]
        from app.services.risk.staged_execution_service import (
            StagedExecutionOutcome,
            StagedExecutionServiceResult,
        )

        return StagedExecutionServiceResult(
            outcome=StagedExecutionOutcome.EXECUTED,
            plan_id=plan_id,
            broker_order_id="stub-order",
            final_status=None,
            error_msg=None,
            message="stub resolved",
        )


_NOW_STUCK = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)


class TestBrokerPlanStuckEnum:
    """BROKER_PLAN_STUCK enum + severity SSOT (HC-2b2 G7)."""

    def test_rule_id_in_enum(self) -> None:
        from backend.qm_platform.risk.metrics.meta_alert_interface import MetaAlertRuleId

        assert MetaAlertRuleId.BROKER_PLAN_STUCK.value == "broker_plan_stuck"

    def test_severity_is_p0(self) -> None:
        """V3 §14 mode 12 ✅ P0 — broker 接口故障 = 系统失效."""
        from backend.qm_platform.risk.metrics.meta_alert_interface import (
            RULE_SEVERITY,
            MetaAlertRuleId,
            MetaAlertSeverity,
        )

        assert RULE_SEVERITY[MetaAlertRuleId.BROKER_PLAN_STUCK] is MetaAlertSeverity.P0

    def test_threshold_const(self) -> None:
        from backend.qm_platform.risk.metrics.meta_alert_interface import (
            BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S,
        )

        assert BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S == 300


class TestSweepStuckInner:
    """_sweep_stuck_inner — detect stuck plans + retry execute_plan."""

    def test_no_stuck_plans_zero_op(self, monkeypatch) -> None:
        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t, "_emit_broker_plan_stuck_meta_alert", lambda *a, **k: emit_calls.append((a, k))
        )
        conn, cur = _make_stuck_mock_conn(select_rows=[])
        stub = _StuckStagedStub()
        result = l4t._sweep_stuck_inner(conn=conn, staged_service=stub, now=_NOW_STUCK)
        assert result == {
            "ok": True,
            "scanned": 0,
            "resolved": 0,
            "still_stuck": 0,
            "still_stuck_plan_ids": [],
            "batch_limited": False,
        }
        assert stub.calls == []
        assert emit_calls == []  # nothing stuck → no 元告警

    def test_stuck_plan_retry_resolves(self, monkeypatch) -> None:
        """retry execute_plan succeeds → resolved, conn.commit per-plan, no 元告警."""
        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t, "_emit_broker_plan_stuck_meta_alert", lambda *a, **k: emit_calls.append((a, k))
        )
        conn, _cur = _make_stuck_mock_conn(select_rows=[_stuck_row("p-1", "TIMEOUT_EXECUTED")])
        stub = _StuckStagedStub()
        result = l4t._sweep_stuck_inner(conn=conn, staged_service=stub, now=_NOW_STUCK)
        assert result["scanned"] == 1
        assert result["resolved"] == 1
        assert result["still_stuck"] == 0
        assert stub.calls == ["p-1"]
        conn.commit.assert_called_once()  # per-plan commit on success
        conn.rollback.assert_not_called()
        assert emit_calls == []

    def test_stuck_plan_retry_raises_emits_meta_alert(self, monkeypatch) -> None:
        """retry raises → rollback + still_stuck + BROKER_PLAN_STUCK 元告警."""
        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t,
            "_emit_broker_plan_stuck_meta_alert",
            lambda stuck, *, now: emit_calls.append({"stuck": stuck, "now": now}),
        )
        conn, _cur = _make_stuck_mock_conn(select_rows=[_stuck_row("p-1", "CONFIRMED")])
        stub = _StuckStagedStub(fail={"p-1": RuntimeError("broker DB write borked")})
        result = l4t._sweep_stuck_inner(conn=conn, staged_service=stub, now=_NOW_STUCK)
        assert result["scanned"] == 1
        assert result["resolved"] == 0
        assert result["still_stuck"] == 1
        assert result["still_stuck_plan_ids"] == ["p-1"]
        conn.rollback.assert_called_once()  # borked txn cleared before next plan
        conn.commit.assert_not_called()
        # 元告警 emitted once, summarizing the still-stuck plan
        assert len(emit_calls) == 1
        stuck = emit_calls[0]["stuck"]
        assert stuck[0][0] == "p-1"
        assert stuck[0][1] == "CONFIRMED"
        assert "broker DB write borked" in stuck[0][2]

    def test_mixed_resolve_and_stuck(self, monkeypatch) -> None:
        """3 stuck plans: 2 resolve, 1 raises → per-plan resilient (1 bad ≠ abort)."""
        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t,
            "_emit_broker_plan_stuck_meta_alert",
            lambda stuck, *, now: emit_calls.append({"stuck": stuck, "now": now}),
        )
        conn, _cur = _make_stuck_mock_conn(
            select_rows=[
                _stuck_row("p-1", "CONFIRMED"),
                _stuck_row("p-2", "TIMEOUT_EXECUTED"),
                _stuck_row("p-3", "CONFIRMED"),
            ]
        )
        stub = _StuckStagedStub(fail={"p-2": RuntimeError("still down")})
        result = l4t._sweep_stuck_inner(conn=conn, staged_service=stub, now=_NOW_STUCK)
        assert result["scanned"] == 3
        assert result["resolved"] == 2  # p-1 + p-3
        assert result["still_stuck"] == 1  # p-2
        assert result["still_stuck_plan_ids"] == ["p-2"]
        assert stub.calls == ["p-1", "p-2", "p-3"]  # all 3 attempted (resilient)
        assert conn.commit.call_count == 2  # p-1 + p-3
        conn.rollback.assert_called_once()  # p-2
        assert len(emit_calls) == 1
        assert len(emit_calls[0]["stuck"]) == 1

    def test_batch_limit_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(l4t, "_emit_broker_plan_stuck_meta_alert", lambda *a, **k: None)
        conn, _cur = _make_stuck_mock_conn(select_rows=[_stuck_row(f"p-{i}") for i in range(3)])
        stub = _StuckStagedStub()
        result = l4t._sweep_stuck_inner(conn=conn, staged_service=stub, now=_NOW_STUCK, limit=3)
        assert result["batch_limited"] is True


class TestEmitBrokerPlanStuckMetaAlert:
    """_emit_broker_plan_stuck_meta_alert — BROKER_PLAN_STUCK via channel chain."""

    def test_builds_correct_meta_alert_and_pushes(self, monkeypatch) -> None:
        from backend.qm_platform.risk.metrics.meta_alert_interface import (
            MetaAlertRuleId,
            MetaAlertSeverity,
        )

        pushed: list[dict[str, Any]] = []

        class _StubMMS:
            def push_triggered(self, alerts: Any, *, conn: Any) -> list[dict[str, Any]]:
                pushed.append({"alerts": alerts, "conn": conn})
                return [{"channel": "log_p0"}]

        import app.services.risk.meta_monitor_service as mms_mod

        monkeypatch.setattr(mms_mod, "MetaMonitorService", _StubMMS)

        import app.services.db as db_mod

        committed: list[bool] = []

        class _StubConn:
            def commit(self) -> None:
                committed.append(True)

            def rollback(self) -> None:
                committed.append(False)

            def close(self) -> None:
                pass

        monkeypatch.setattr(db_mod, "get_sync_conn", _StubConn)

        l4t._emit_broker_plan_stuck_meta_alert(
            [("p-1", "CONFIRMED", "RuntimeError: broker down")], now=_NOW_STUCK
        )
        assert len(pushed) == 1
        alert = pushed[0]["alerts"][0]
        assert alert.rule_id is MetaAlertRuleId.BROKER_PLAN_STUCK
        assert alert.severity is MetaAlertSeverity.P0
        assert alert.triggered is True
        assert "p-1" in alert.detail
        assert "CONFIRMED" in alert.detail
        assert committed == [True]

    def test_push_failure_is_fail_soft(self, monkeypatch) -> None:
        """元告警 push 自身失败 → log + swallow (NOT raise — sweep 结果不被吞)."""

        class _BoomMMS:
            def push_triggered(self, alerts: Any, *, conn: Any) -> list[dict[str, Any]]:
                raise RuntimeError("all channels down")

        import app.services.risk.meta_monitor_service as mms_mod

        monkeypatch.setattr(mms_mod, "MetaMonitorService", _BoomMMS)

        import app.services.db as db_mod

        rolled_back: list[bool] = []

        class _StubConn:
            def commit(self) -> None:
                pass

            def rollback(self) -> None:
                rolled_back.append(True)

            def close(self) -> None:
                pass

        monkeypatch.setattr(db_mod, "get_sync_conn", _StubConn)

        # Must NOT raise — fail-soft.
        l4t._emit_broker_plan_stuck_meta_alert([("p-1", "CONFIRMED", "err")], now=_NOW_STUCK)
        assert rolled_back == [True]


class TestSweepStuckBeatWiring:
    """risk-l4-broker-stuck-sweep Beat entry + task registration (HC-2b2 G7)."""

    def test_task_registered(self) -> None:
        assert "app.tasks.l4_sweep_tasks.sweep_stuck_broker_plans" in celery_app.tasks

    def test_beat_entry_exists_and_correct(self) -> None:
        assert "risk-l4-broker-stuck-sweep" in CELERY_BEAT_SCHEDULE
        entry = CELERY_BEAT_SCHEDULE["risk-l4-broker-stuck-sweep"]
        assert entry["task"] == "app.tasks.l4_sweep_tasks.sweep_stuck_broker_plans"
        assert entry["options"]["queue"] == "default"
        assert entry["options"]["expires"] == 240

    def test_beat_entry_every_5min_all_hours(self) -> None:
        """*/5 all hours — stuck plans persist across any time incl overnight."""
        schedule = CELERY_BEAT_SCHEDULE["risk-l4-broker-stuck-sweep"]["schedule"]
        assert schedule.minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
        assert schedule.hour == set(range(24))  # all hours (反 9-14 trading-only)
