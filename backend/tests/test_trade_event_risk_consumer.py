"""iter 184 MVP 4.8 Phase J §1.5 — Trade event risk consumer TDD tests.

Batched MVP 4.8 Chunks 1+2+3+4 per iter 183 design + user directive iter 184
"batch instead of chunk-per-iter" efficiency directive.

Tests cover:
- consume_fill_events helper (XREADGROUP + payload parse + consumer group MKSTREAM)
- trade_event_risk_consumer_tick Celery task (events → engine.on_tick → audit envelope)
- Fail-soft per-event (engine raise → log + continue, NOT crash whole task)

Mock strategy: full MagicMock for Redis + engine + builder (no real I/O).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────── consume_fill_events helper ───────────────────────────


def test_consume_fill_events_returns_empty_on_no_new_messages():
    """XREADGROUP returns nothing → consumer helper returns []."""
    from app.services.risk.trade_event_consumer import consume_fill_events

    r = MagicMock()
    r.xreadgroup.return_value = []  # No new messages
    r.xgroup_create.return_value = None

    result = consume_fill_events(r, count=100, block_ms=0)
    assert result == []


def test_consume_fill_events_parses_payload_dict():
    """XREADGROUP returns 1 message → consumer parses JSON payload + returns dict."""
    from app.services.risk.trade_event_consumer import consume_fill_events

    r = MagicMock()
    r.xreadgroup.return_value = [
        (
            "qm:fill:executed",
            [
                (
                    "1716700000000-0",
                    {
                        "payload": '{"strategy_id": "test-1", "fill_count": 5, "mode": "paper"}',
                    },
                )
            ],
        )
    ]
    r.xgroup_create.return_value = None

    result = consume_fill_events(r, count=100, block_ms=0)
    assert len(result) == 1
    event = result[0]
    assert event["event_id"] == "1716700000000-0"
    assert event["data"]["strategy_id"] == "test-1"
    assert event["data"]["fill_count"] == 5


def test_consume_fill_events_handles_busygroup_idempotent():
    """xgroup_create raises BUSYGROUP on 2nd call → idempotent, no propagation."""
    import redis as redis_module

    from app.services.risk.trade_event_consumer import consume_fill_events

    r = MagicMock()
    r.xgroup_create.side_effect = redis_module.exceptions.ResponseError(
        "BUSYGROUP Consumer Group name already exists"
    )
    r.xreadgroup.return_value = []

    # Should NOT raise — BUSYGROUP is expected on re-call
    result = consume_fill_events(r)
    assert result == []


def test_consume_fill_events_raises_on_non_busygroup_redis_error():
    """xgroup_create raises non-BUSYGROUP → propagate (fail-loud per 铁律 33)."""
    import redis as redis_module

    from app.services.risk.trade_event_consumer import consume_fill_events

    r = MagicMock()
    r.xgroup_create.side_effect = redis_module.exceptions.ResponseError(
        "ERR some other error"
    )

    with pytest.raises(redis_module.exceptions.ResponseError) as exc_info:
        consume_fill_events(r)
    assert "ERR some other error" in str(exc_info.value)


def test_ack_fill_event_calls_xack():
    """ack_fill_event delegates to r.xack with correct stream + group + msg_id."""
    from app.services.risk.trade_event_consumer import (
        CONSUMER_GROUP,
        STREAM_NAME,
        ack_fill_event,
    )

    r = MagicMock()
    ack_fill_event(r, "1716700000000-0")

    r.xack.assert_called_once_with(STREAM_NAME, CONSUMER_GROUP, "1716700000000-0")


# ─────────────────────────── trade_event_risk_consumer_tick task ───────────────────────────


def test_task_processes_fill_events_via_engine():
    """Task: each event triggers engine.on_tick via RealtimeRiskContextBuilder."""
    from app.tasks.trade_event_risk_tasks import trade_event_risk_consumer_tick

    mock_redis = MagicMock()
    mock_engine = MagicMock()
    mock_engine.on_tick.return_value = []  # No rule results
    mock_builder_instance = MagicMock()
    mock_builder_instance.build_context.return_value = MagicMock()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    events = [
        {"event_id": "1-0", "data": {"strategy_id": "s1", "mode": "paper"}, "stream": "qm:fill:executed"},
        {"event_id": "2-0", "data": {"strategy_id": "s2", "mode": "paper"}, "stream": "qm:fill:executed"},
    ]

    with (
        patch("app.tasks.trade_event_risk_tasks._get_redis", return_value=mock_redis),
        patch("app.tasks.trade_event_risk_tasks.consume_fill_events", return_value=events),
        patch("app.tasks.trade_event_risk_tasks.get_sync_conn", return_value=mock_conn),
        patch(
            "app.services.risk.realtime_context_builder.RealtimeRiskContextBuilder",
            return_value=mock_builder_instance,
        ),
        patch("app.tasks.realtime_risk_tasks._get_engine", return_value=mock_engine),
        patch("app.tasks.trade_event_risk_tasks.ack_fill_event"),
    ):
        result = trade_event_risk_consumer_tick()

    assert result["events_consumed"] == 2
    assert result["events_processed"] == 2
    assert result["events_failed"] == 0
    # engine.on_tick called per event
    assert mock_engine.on_tick.call_count == 2


def test_task_writes_scheduler_task_log_audit_row():
    """Audit envelope: scheduler_task_log row with task_name='trade_event_risk_consumer'."""
    from app.tasks.trade_event_risk_tasks import trade_event_risk_consumer_tick

    mock_redis = MagicMock()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with (
        patch("app.tasks.trade_event_risk_tasks._get_redis", return_value=mock_redis),
        patch("app.tasks.trade_event_risk_tasks.consume_fill_events", return_value=[]),
        patch("app.tasks.trade_event_risk_tasks.get_sync_conn", return_value=mock_conn),
    ):
        trade_event_risk_consumer_tick()

    # Verify scheduler_task_log INSERT
    insert_calls = [
        c for c in mock_cur.execute.call_args_list
        if c.args and "INSERT INTO scheduler_task_log" in c.args[0]
    ]
    assert len(insert_calls) == 1
    sql = insert_calls[0].args[0]
    assert "trade_event_risk_consumer" in sql
    assert "astock" in sql


def test_task_fail_soft_per_event_does_not_crash_whole_task():
    """Engine raises on 1 event → log + continue with next events + audit envelope."""
    from app.tasks.trade_event_risk_tasks import trade_event_risk_consumer_tick

    mock_redis = MagicMock()
    mock_engine = MagicMock()
    # First event raises, second succeeds
    mock_engine.on_tick.side_effect = [RuntimeError("engine boom"), []]
    mock_builder_instance = MagicMock()
    mock_builder_instance.build_context.return_value = MagicMock()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    events = [
        {"event_id": "1-0", "data": {"strategy_id": "s1"}, "stream": "qm:fill:executed"},
        {"event_id": "2-0", "data": {"strategy_id": "s2"}, "stream": "qm:fill:executed"},
    ]

    with (
        patch("app.tasks.trade_event_risk_tasks._get_redis", return_value=mock_redis),
        patch("app.tasks.trade_event_risk_tasks.consume_fill_events", return_value=events),
        patch("app.tasks.trade_event_risk_tasks.get_sync_conn", return_value=mock_conn),
        patch(
            "app.services.risk.realtime_context_builder.RealtimeRiskContextBuilder",
            return_value=mock_builder_instance,
        ),
        patch("app.tasks.realtime_risk_tasks._get_engine", return_value=mock_engine),
        patch("app.tasks.trade_event_risk_tasks.ack_fill_event"),
    ):
        result = trade_event_risk_consumer_tick()

    # Should NOT crash — fail-soft per-event
    assert result["events_consumed"] == 2
    assert result["events_processed"] == 1  # Only event 2 succeeded
    assert result["events_failed"] == 1


def test_task_returns_summary_dict_with_metrics():
    """Task return dict shape contract for monitoring."""
    from app.tasks.trade_event_risk_tasks import trade_event_risk_consumer_tick

    mock_redis = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = MagicMock()

    with (
        patch("app.tasks.trade_event_risk_tasks._get_redis", return_value=mock_redis),
        patch("app.tasks.trade_event_risk_tasks.consume_fill_events", return_value=[]),
        patch("app.tasks.trade_event_risk_tasks.get_sync_conn", return_value=mock_conn),
    ):
        result = trade_event_risk_consumer_tick()

    assert "events_consumed" in result
    assert "events_processed" in result
    assert "events_failed" in result
    assert "p0_total" in result
    assert "elapsed_sec" in result
