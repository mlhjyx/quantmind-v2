"""S8 8b DingTalk webhook service tests — DB orchestration + state transition.

Coverage:
- Happy path: PENDING_CONFIRM → CONFIRMED on confirm command
- Happy path: PENDING_CONFIRM → CANCELLED on cancel command
- Idempotent: already CONFIRMED → return ALREADY_TERMINAL without UPDATE
- Idempotent: already CANCELLED → return ALREADY_TERMINAL
- Deadline expired: now >= cancel_deadline → return DEADLINE_EXPIRED
- Plan not found: empty SELECT → PLAN_NOT_FOUND
- Ambiguous prefix: multiple matches → AMBIGUOUS_PREFIX
- Race condition: UPDATE rowcount=0 → ALREADY_TERMINAL (concurrent transition)
- 铁律 32: service.process_command does NOT call conn.commit / conn.rollback

关联铁律: 32 (caller transaction boundary) / 33 (fail-loud on DB error)
关联 ADR: ADR-057 §S8 8b webhook receiver
关联 LL: LL-151 §S8 8b sediment
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from backend.app.services.risk.dingtalk_webhook_service import (
    DingTalkWebhookService,
    WebhookOutcome,
)
from backend.qm_platform.risk.execution.planner import PlanStatus
from backend.qm_platform.risk.execution.webhook_parser import WebhookCommand

# ── Test helpers ──


def _make_mock_conn(
    *,
    resolve_rows: list[tuple] | None = None,
    update_rowcount: int = 1,
    column_names: list[str] | None = None,
) -> MagicMock:
    """Build a psycopg2-compatible mock conn that returns the given resolve_rows
    on first execute (SELECT) and reports update_rowcount on second (UPDATE).
    """
    if column_names is None:
        column_names = [
            "plan_id",
            "status",
            "cancel_deadline",
            "mode",
            "symbol_id",
            "qty",
        ]

    conn = MagicMock()
    cursor = MagicMock()

    # cursor.description for the resolve SELECT — list of named tuples like psycopg2
    desc_items = [type("Col", (), {"name": n})() for n in column_names]

    def execute_side_effect(sql: str, params: tuple) -> None:
        # Distinguish SELECT vs UPDATE by SQL prefix
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT"):
            cursor.description = desc_items
            cursor.fetchall = MagicMock(return_value=resolve_rows or [])
        else:  # UPDATE
            cursor.rowcount = update_rowcount

    cursor.execute = MagicMock(side_effect=execute_side_effect)
    cursor.close = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    return conn


def _row(plan_id: str, status: str, deadline: datetime) -> tuple:
    return (plan_id, status, deadline, "STAGED", "600519.SH", 100)


# §1 Happy paths


class TestProcessCommandHappy:
    def test_pending_to_confirmed(self) -> None:
        plan_id = "abcd1234-dead-beef-0000-000000000000"
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        now = datetime(2026, 5, 13, 14, 15, tzinfo=UTC)  # before deadline
        conn = _make_mock_conn(
            resolve_rows=[_row(plan_id, "PENDING_CONFIRM", deadline)],
            update_rowcount=1,
        )

        svc = DingTalkWebhookService()
        result = svc.process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="abcd1234deadbeef",
            conn=conn,
            at=now,
        )

        assert result.outcome == WebhookOutcome.TRANSITIONED
        assert result.plan_id == plan_id
        assert result.final_status == PlanStatus.CONFIRMED
        # 2 executes: SELECT + UPDATE
        assert conn.cursor().execute.call_count == 2

    def test_pending_to_cancelled(self) -> None:
        plan_id = "00000000-0000-0000-0000-000000000001"
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        now = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
        conn = _make_mock_conn(
            resolve_rows=[_row(plan_id, "PENDING_CONFIRM", deadline)],
            update_rowcount=1,
        )

        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CANCEL,
            plan_id_prefix="00000000",
            conn=conn,
            at=now,
        )

        assert result.outcome == WebhookOutcome.TRANSITIONED
        assert result.final_status == PlanStatus.CANCELLED


# §2 Idempotent paths


class TestProcessCommandIdempotent:
    def test_already_confirmed_returns_terminal(self) -> None:
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        conn = _make_mock_conn(
            resolve_rows=[_row("plan-xyz", "CONFIRMED", deadline)],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="planabcd",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        assert result.outcome == WebhookOutcome.ALREADY_TERMINAL
        assert result.final_status == PlanStatus.CONFIRMED
        # Only 1 execute (SELECT) — no UPDATE
        assert conn.cursor().execute.call_count == 1

    def test_already_cancelled_returns_terminal(self) -> None:
        conn = _make_mock_conn(
            resolve_rows=[_row("p-1", "CANCELLED", datetime(2026, 5, 13, 14, 30, tzinfo=UTC))],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,  # try to confirm a cancelled plan
            plan_id_prefix="planabcd",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        assert result.outcome == WebhookOutcome.ALREADY_TERMINAL
        assert result.final_status == PlanStatus.CANCELLED

    def test_timeout_executed_returns_terminal(self) -> None:
        conn = _make_mock_conn(
            resolve_rows=[
                _row("p-1", "TIMEOUT_EXECUTED", datetime(2026, 5, 13, 14, 30, tzinfo=UTC))
            ],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CANCEL,
            plan_id_prefix="planabcd",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        assert result.outcome == WebhookOutcome.ALREADY_TERMINAL
        assert result.final_status == PlanStatus.TIMEOUT_EXECUTED


# §3 Deadline expiry


class TestProcessCommandDeadline:
    def test_deadline_expired_returns_deadline_expired(self) -> None:
        deadline = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
        now = deadline + timedelta(seconds=1)  # 1s past deadline
        conn = _make_mock_conn(
            resolve_rows=[_row("p-1", "PENDING_CONFIRM", deadline)],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="planabcd",
            conn=conn,
            at=now,
        )
        assert result.outcome == WebhookOutcome.DEADLINE_EXPIRED
        # No UPDATE invoked
        assert conn.cursor().execute.call_count == 1

    def test_deadline_exactly_now_treated_as_expired(self) -> None:
        deadline = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
        now = deadline  # exactly at deadline → expired per `now >= deadline`
        conn = _make_mock_conn(
            resolve_rows=[_row("p-1", "PENDING_CONFIRM", deadline)],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="planabcd",
            conn=conn,
            at=now,
        )
        assert result.outcome == WebhookOutcome.DEADLINE_EXPIRED


# §4 Resolution failures


class TestProcessCommandResolveFailures:
    def test_no_match_returns_plan_not_found(self) -> None:
        conn = _make_mock_conn(resolve_rows=[])
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="ffffffff",
            conn=conn,
            at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        assert result.outcome == WebhookOutcome.PLAN_NOT_FOUND
        assert result.plan_id is None

    def test_multiple_matches_returns_ambiguous(self) -> None:
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        conn = _make_mock_conn(
            resolve_rows=[
                _row("plan-1", "PENDING_CONFIRM", deadline),
                _row("plan-2", "PENDING_CONFIRM", deadline),
            ],
        )
        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="ffffffff",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        assert result.outcome == WebhookOutcome.AMBIGUOUS_PREFIX
        assert result.plan_id is None


# §5 Race condition


class TestProcessCommandRaceCondition:
    def test_concurrent_transition_returns_already_terminal(self) -> None:
        """SELECT showed PENDING_CONFIRM but UPDATE rowcount=0 (concurrent change)."""
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        # First call returns PENDING_CONFIRM, post-UPDATE re-read returns CANCELLED
        # We simulate via dynamic resolve_rows mutation in the mock
        conn = MagicMock()
        cursor = MagicMock()

        # 3 execute calls: SELECT (initial), UPDATE (returns 0 rowcount),
        # SELECT (refreshed re-read showing the concurrent transition)
        call_counter = {"n": 0}

        desc_items = [
            type("Col", (), {"name": n})()
            for n in ("plan_id", "status", "cancel_deadline", "mode", "symbol_id", "qty")
        ]

        def execute_side_effect(sql: str, params: tuple) -> None:
            call_counter["n"] += 1
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("SELECT"):
                cursor.description = desc_items
                if call_counter["n"] == 1:
                    # Initial SELECT → PENDING_CONFIRM
                    cursor.fetchall = MagicMock(
                        return_value=[_row("plan-1", "PENDING_CONFIRM", deadline)]
                    )
                else:
                    # Refresh SELECT after concurrent change → CANCELLED
                    cursor.fetchall = MagicMock(
                        return_value=[_row("plan-1", "CANCELLED", deadline)]
                    )
            else:
                # UPDATE → 0 rows affected (concurrent change blocked us)
                cursor.rowcount = 0

        cursor.execute = MagicMock(side_effect=execute_side_effect)
        cursor.close = MagicMock()
        conn.cursor = MagicMock(return_value=cursor)

        result = DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="ffffffff",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )

        assert result.outcome == WebhookOutcome.ALREADY_TERMINAL
        assert result.final_status == PlanStatus.CANCELLED
        # 3 execute calls (SELECT + UPDATE + SELECT)
        assert call_counter["n"] == 3


# §6 铁律 32 sustained — caller transaction boundary


class TestProcessCommandTransactionBoundary:
    def test_service_does_not_commit_on_success(self) -> None:
        deadline = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        conn = _make_mock_conn(
            resolve_rows=[_row("p-1", "PENDING_CONFIRM", deadline)],
            update_rowcount=1,
        )
        DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="planabcd",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        conn.commit.assert_not_called()
        conn.rollback.assert_not_called()

    def test_service_does_not_commit_on_already_terminal(self) -> None:
        conn = _make_mock_conn(
            resolve_rows=[_row("p-1", "CONFIRMED", datetime(2026, 5, 13, 14, 30, tzinfo=UTC))],
        )
        DingTalkWebhookService().process_command(
            command=WebhookCommand.CONFIRM,
            plan_id_prefix="planabcd",
            conn=conn,
            at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        )
        conn.commit.assert_not_called()
        conn.rollback.assert_not_called()


# §7 Frozen result


def test_result_dataclass_is_frozen() -> None:
    from backend.app.services.risk.dingtalk_webhook_service import DingTalkWebhookResult

    r = DingTalkWebhookResult(
        outcome=WebhookOutcome.TRANSITIONED,
        plan_id="abc",
        final_status=PlanStatus.CONFIRMED,
        message="ok",
    )
    with pytest.raises(Exception):  # noqa: B017
        r.outcome = WebhookOutcome.PLAN_NOT_FOUND  # type: ignore[misc]
