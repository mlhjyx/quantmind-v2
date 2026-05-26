"""Tests for execution_plan_persistence (iter 162 Phase J §1.1 Chunk 5).

MVP 4.5 §3 Chunk 5 — Persist ExecutionPlan + risk_event_log audit row
in single transaction. Caller (Celery task) owns commit per 铁律 32.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.risk.execution_plan_persistence import (
    parse_severity_from_rule_id,
    persist_plan_with_audit,
)
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    ExecutionPlan,
    PlanStatus,
)
from backend.qm_platform.risk.interface import RuleResult


def _make_plan() -> ExecutionPlan:
    """Build sample ExecutionPlan for test fixture."""
    now = datetime.now(UTC)
    return ExecutionPlan(
        plan_id="00000000-0000-0000-0000-000000000001",
        mode=ExecutionMode.OFF,
        symbol_id="600519.SH",
        action="SELL",
        qty=100,
        limit_price=2000.0,
        batch_index=1,
        batch_total=1,
        scheduled_at=now,
        cancel_deadline=now + timedelta(minutes=30),
        status=PlanStatus.CONFIRMED,
        triggered_by_event_id=None,
        risk_reason="rapid drop 5% in 5min",
        risk_metrics={"pnl_pct": -0.05},
    )


def _make_result() -> RuleResult:
    """Build sample RuleResult for test fixture."""
    return RuleResult(
        rule_id="p0_rapid_drop_5min",
        code="600519.SH",
        shares=100,
        reason="rapid drop 5% in 5min",
        metrics={"pnl_pct": -0.05},
    )


class TestParseSeverity:
    """parse_severity_from_rule_id maps prefix → severity."""

    def test_p0_prefix(self):
        assert parse_severity_from_rule_id("p0_limit_down_detection") == "p0"

    def test_p1_prefix(self):
        assert parse_severity_from_rule_id("p1_rapid_drop_5min") == "p1"

    def test_p2_prefix(self):
        assert parse_severity_from_rule_id("p2_volume_spike") == "p2"

    def test_unknown_prefix_defaults_p2(self):
        assert parse_severity_from_rule_id("xyz_unknown_rule") == "p2"
        assert parse_severity_from_rule_id("") == "p2"


class TestPersistPlanWithAudit:
    """persist_plan_with_audit INSERTs both execution_plans + risk_event_log."""

    def test_happy_path_returns_plan_event_ids(self):
        """Clean insert → returns dict with plan_id + event_id."""
        plan = _make_plan()
        result = _make_result()

        # Mock conn + cursor with proper fetchone() returns
        fake_cursor = MagicMock()
        # First fetchone: execution_plans RETURNING plan_id
        # Second fetchone: risk_event_log RETURNING id
        fake_cursor.fetchone.side_effect = [
            (plan.plan_id,),
            ("event-uuid-12345",),
        ]
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

        out = persist_plan_with_audit(
            conn=fake_conn,
            plan=plan,
            result=result,
            strategy_id="11111111-2222-3333-4444-555555555555",
            execution_mode="paper",
            severity="p0",
        )

        assert out["plan_id"] == plan.plan_id
        assert out["event_id"] == "event-uuid-12345"
        assert out["status"] == "CONFIRMED"
        assert out["plan_inserted"] is True

        # Both INSERTs invoked
        assert fake_cursor.execute.call_count == 2
        # First call = execution_plans INSERT
        first_sql = fake_cursor.execute.call_args_list[0][0][0]
        assert "INSERT INTO execution_plans" in first_sql
        # Second call = risk_event_log INSERT
        second_sql = fake_cursor.execute.call_args_list[1][0][0]
        assert "INSERT INTO risk_event_log" in second_sql

    def test_on_conflict_returns_inserted_false(self):
        """ON CONFLICT no-op → plan_inserted=False but event still INSERTed."""
        plan = _make_plan()
        result = _make_result()

        fake_cursor = MagicMock()
        # First fetchone: execution_plans RETURNING — None (ON CONFLICT skipped)
        # Second fetchone: risk_event_log RETURNING id (still INSERTed)
        fake_cursor.fetchone.side_effect = [
            None,  # ON CONFLICT
            ("event-uuid-67890",),
        ]
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

        out = persist_plan_with_audit(
            conn=fake_conn,
            plan=plan,
            result=result,
            strategy_id="11111111-2222-3333-4444-555555555555",
            execution_mode="paper",
        )

        assert out["plan_inserted"] is False
        assert out["event_id"] == "event-uuid-67890"

    def test_db_error_propagates(self):
        """psycopg2 errors propagate (caller decides rollback per 铁律 32)."""
        plan = _make_plan()
        result = _make_result()

        fake_cursor = MagicMock()
        fake_cursor.execute.side_effect = RuntimeError("synthetic PG error")
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

        with pytest.raises(RuntimeError) as exc:
            persist_plan_with_audit(
                conn=fake_conn,
                plan=plan,
                result=result,
                strategy_id="11111111-2222-3333-4444-555555555555",
                execution_mode="paper",
            )
        assert "synthetic PG error" in str(exc.value)
