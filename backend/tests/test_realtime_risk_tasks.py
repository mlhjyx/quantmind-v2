"""Tests for realtime_risk_tasks (iter 154 Phase J §1.1 Chunk 2).

MVP 4.5 §3 Chunk 2 test plan: verify Celery task registration + mock
context builder + 10-rule engine fire + scheduler_task_log audit row written.

Sibling pattern: backend/tests/test_wave4_audit_envelope.py (iter 132).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.risk.realtime_context_builder import PositionSourceError
from backend.qm_platform.risk.interface import RiskContext


def _make_ctx(positions: tuple = (), portfolio_nav: float = 100000.0) -> RiskContext:
    """Build minimal RiskContext for test."""
    return RiskContext(
        strategy_id="test-strategy",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=positions,
        portfolio_nav=portfolio_nav,
    )


class TestRealtimeRiskTickHappyPath:
    """Verify clean tick flow writes scheduler_task_log + returns result dict."""

    def test_happy_path_returns_success_dict(self):
        """Clean tick with 0 positions → ok=True + 0 triggered + audit row."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        fake_engine = MagicMock(name="engine")
        fake_engine.on_tick.return_value = []
        fake_engine.on_5min_beat.return_value = []
        fake_engine.on_15min_beat.return_value = []

        fake_builder = MagicMock(name="builder")
        fake_builder.build_context.return_value = _make_ctx(positions=())

        with (
            patch.object(task_mod, "_get_engine", return_value=fake_engine),
            patch.object(task_mod, "_get_context_builder", return_value=fake_builder),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.realtime_risk_tick.apply(args=[]).get()

        assert result["ok"] is True
        assert result["triggered"] == 0
        assert result["positions"] == 0
        assert "at" in result

        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "realtime_risk_tick"
        assert call_args[0][2] == "success"

    def test_stale_data_returns_skipped(self):
        """PositionSourceError → ok=False + reason=stale_market_data + audit status=skipped."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        fake_engine = MagicMock(name="engine")
        fake_builder = MagicMock(name="builder")
        fake_builder.build_context.side_effect = PositionSourceError("synthetic stale data error")

        with (
            patch.object(task_mod, "_get_engine", return_value=fake_engine),
            patch.object(task_mod, "_get_context_builder", return_value=fake_builder),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.realtime_risk_tick.apply(args=[]).get()

        assert result["ok"] is False
        assert result["reason"] == "stale_market_data"
        assert "synthetic stale data error" in result["error"]

        mock_audit.assert_called_once()
        assert mock_audit.call_args[0][2] == "skipped"
        # engine.on_tick NOT called when stale (skip path)
        fake_engine.on_tick.assert_not_called()


class TestEngineLazySingleton:
    """Verify engine instantiated once + 10 rules registered."""

    def test_engine_singleton_with_10_rules(self):
        """_get_engine returns same instance + invokes register_all_realtime_rules once."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        # Reset singleton for clean test
        task_mod._engine = None

        with (
            patch("app.tasks.realtime_risk_tasks.register_all_realtime_rules") as mock_register,
            patch("app.tasks.realtime_risk_tasks.RedisThresholdCache") as mock_cache_cls,
        ):
            engine_a = task_mod._get_engine()
            engine_b = task_mod._get_engine()

        # Same instance returned
        assert engine_a is engine_b
        # register_all_realtime_rules called once
        mock_register.assert_called_once_with(engine_a)
        # iter 155 Chunk 3: RedisThresholdCache constructed + wired
        mock_cache_cls.assert_called_once()

        # Cleanup
        task_mod._engine = None


class TestAuditEnvelopeCanonical:
    """Verify audit envelope canonical signature (sibling iter 132 pattern)."""

    def test_envelope_helper_exists(self):
        """_write_scheduler_log_safe helper present + callable."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        assert hasattr(task_mod, "_write_scheduler_log_safe")
        assert callable(task_mod._write_scheduler_log_safe)

    def test_envelope_silent_on_db_failure(self, caplog: pytest.LogCaptureFixture):
        """DB write failure logs warning, NOT raise (silent_ok 铁律 33(c))."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        with (
            patch("app.services.db.get_sync_conn", side_effect=RuntimeError("PG down")),
            caplog.at_level("WARNING", logger="celery.realtime_risk_tasks"),
        ):
            # Must not raise (silent_ok contract)
            task_mod._write_scheduler_log_safe(
                "realtime_risk_tick",
                datetime.now(UTC),
                "success",
                {"ok": True},
            )

        # Warning logged
        assert any("scheduler_task_log" in rec.message for rec in caplog.records)


class TestAlertDispatcherWire:
    """iter 156 Chunk 4 — AlertDispatcher P0/P1/P2 wire."""

    def test_send_alert_via_dingtalk_calls_send_with_dedup(self):
        """_send_alert_via_dingtalk adapts RuleResult → send_with_dedup."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415
        from backend.qm_platform.risk.interface import RuleResult  # noqa: PLC0415

        result = RuleResult(
            rule_id="p0_limit_down_detection",
            code="600519.SH",
            shares=100,
            reason="跌停触发",
            metrics={"pnl_pct": -0.10},
        )

        with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
            mock_send.return_value = {"sent": True, "reason": "sent", "dedup_hit": False}
            ok = task_mod._send_alert_via_dingtalk(result)

        assert ok is True
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["source"] == "realtime_risk_engine"
        assert "p0_limit_down_detection" in kwargs["dedup_key"]
        assert "600519.SH" in kwargs["dedup_key"]
        assert "L1" in kwargs["title"]

    def test_send_alert_failure_returns_false(self):
        """send_with_dedup raising httpx.HTTPError → returns False (silent_ok)."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415
        from backend.qm_platform.risk.interface import RuleResult  # noqa: PLC0415

        result = RuleResult(
            rule_id="p1_rapid_drop_5min",
            code="000001.SZ",
            shares=0,
            reason="5分钟跌幅 -8%",
            metrics={},
        )

        with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
            mock_send.side_effect = RuntimeError("httpx connection refused")
            ok = task_mod._send_alert_via_dingtalk(result)

        assert ok is False

    def test_dispatcher_singleton(self):
        """_get_dispatcher returns same instance + uses _send_alert_via_dingtalk."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        # Reset singleton
        task_mod._dispatcher = None

        d_a = task_mod._get_dispatcher()
        d_b = task_mod._get_dispatcher()
        assert d_a is d_b

        # Cleanup
        task_mod._dispatcher = None


class TestBeatScheduleRegistration:
    """Verify Beat schedule entry registered correctly (iter 154 Chunk 2)."""

    def test_realtime_risk_tick_in_beat_schedule(self):
        """beat_schedule.py contains realtime-risk-tick entry pointing to task."""
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        assert "realtime-risk-tick" in CELERY_BEAT_SCHEDULE
        entry = CELERY_BEAT_SCHEDULE["realtime-risk-tick"]
        assert entry["task"] == "app.tasks.realtime_risk_tasks.realtime_risk_tick"
        # Verify expires=45 + queue=default per Beat collision tolerance
        assert entry["options"]["expires"] == 45
        assert entry["options"]["queue"] == "default"

    def test_realtime_risk_tasks_imported_by_celery_app(self):
        """celery_app imports list contains realtime_risk_tasks (worker discovers task)."""
        from app.tasks.celery_app import celery_app  # noqa: PLC0415

        # Task should be discoverable via celery_app.tasks
        # (worker registers tasks on bootstrap via imports list)
        assert "app.tasks.realtime_risk_tasks.realtime_risk_tick" in celery_app.tasks
