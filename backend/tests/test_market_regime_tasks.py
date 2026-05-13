"""V3 §5.3 MarketRegime Celery Beat task — TB-2c unit tests.

Coverage:
  - StubIndicatorsProvider returns all-None fields + tz-aware UTC timestamp
  - classify_market_regime task body — mock service + mock conn + verify persist + commit
  - decision_id auto-generation from UTC timestamp
  - Beat schedule registration (3 entries exist with correct crontab)

Sustains mock pattern (反 real LiteLLM call, 反 real DB):
  - Use monkeypatch to inject MockService + MockProvider into task module globals
  - Use MagicMock for psycopg2 conn (no real DB connection)

关联铁律: 31 (Engine PURE provider) / 32 (task commit) / 33 (fail-loud) / 41 (timezone) / 44 X9 (Beat ops)
关联 V3: §5.3 / ADR-036/064/066
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from celery.schedules import crontab

from backend.qm_platform.risk.regime import (
    MarketIndicators,
    MarketRegime,
    RegimeArgument,
    RegimeLabel,
)
from backend.qm_platform.risk.regime.indicators_provider import (
    StubIndicatorsProvider,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


# ─────────────────────────────────────────────────────────────
# StubIndicatorsProvider
# ─────────────────────────────────────────────────────────────


class TestStubIndicatorsProvider:
    def test_fetch_returns_all_none_numeric(self) -> None:
        """TB-2a design codification sustained: all-None numeric fields allowed."""
        # Reset class-level warning state to test the warning path.
        StubIndicatorsProvider._stub_warned = False

        provider = StubIndicatorsProvider()
        ind = provider.fetch()
        assert isinstance(ind, MarketIndicators)
        # All 5 numeric fields None per TB-2c stub scope.
        assert ind.sse_return is None
        assert ind.hs300_return is None
        assert ind.breadth_up is None
        assert ind.breadth_down is None
        assert ind.north_flow_cny is None
        assert ind.iv_50etf is None
        # Timestamp tz-aware UTC per 铁律 41.
        assert ind.timestamp.tzinfo is not None

    def test_fetch_returns_tz_aware_utc(self) -> None:
        provider = StubIndicatorsProvider()
        ind = provider.fetch()
        assert ind.timestamp.tzinfo == UTC
        # Recent (< 5 sec ago).
        delta = (datetime.now(UTC) - ind.timestamp).total_seconds()
        assert 0 <= delta < 5

    def test_one_time_warning_per_process(self, caplog) -> None:
        """Warning fires once per worker process, not per fetch (反 log noise)."""
        StubIndicatorsProvider._stub_warned = False
        provider = StubIndicatorsProvider()

        import logging  # noqa: PLC0415

        with caplog.at_level(logging.WARNING):
            provider.fetch()
            provider.fetch()
            provider.fetch()

        # Should appear in logs exactly once.
        stub_warnings = [r for r in caplog.records if "STUB IndicatorsProvider" in r.message]
        assert len(stub_warnings) == 1


# ─────────────────────────────────────────────────────────────
# classify_market_regime task
# ─────────────────────────────────────────────────────────────


def _make_mock_regime() -> MarketRegime:
    """Build a fake MarketRegime for service mock."""
    ts = datetime.now(UTC)
    return MarketRegime(
        timestamp=ts,
        regime=RegimeLabel.NEUTRAL,
        confidence=0.55,
        bull_arguments=(
            RegimeArgument(argument="b1", evidence="e1", weight=0.5),
            RegimeArgument(argument="b2", evidence="e2", weight=0.4),
            RegimeArgument(argument="b3", evidence="e3", weight=0.3),
        ),
        bear_arguments=(
            RegimeArgument(argument="r1", evidence="x1", weight=0.5),
            RegimeArgument(argument="r2", evidence="x2", weight=0.4),
            RegimeArgument(argument="r3", evidence="x3", weight=0.3),
        ),
        judge_reasoning="均势, 数据 unavailable → Neutral",
        indicators=MarketIndicators(timestamp=ts),
        cost_usd=0.0042,
    )


class TestClassifyMarketRegimeTask:
    def test_classify_orchestrates_provider_service_persist(self, monkeypatch) -> None:
        """End-to-end task body — mock provider/service/db, verify persist + commit."""
        from app.tasks import market_regime_tasks as task_mod  # noqa: PLC0415

        # Reset singletons.
        task_mod._service = None
        task_mod._provider = None

        # Mock service.
        fake_regime = _make_mock_regime()
        mock_service = MagicMock()
        mock_service.classify.return_value = fake_regime
        monkeypatch.setattr(task_mod, "_get_service", lambda: mock_service)

        # Mock provider.
        mock_provider = MagicMock()
        mock_provider.fetch.return_value = MarketIndicators(timestamp=datetime.now(UTC))
        monkeypatch.setattr(task_mod, "_get_provider", lambda: mock_provider)

        # Mock DB conn + persist function.
        mock_conn = MagicMock()
        with patch("app.tasks.market_regime_tasks.persist_market_regime") as mock_persist:
            mock_persist.return_value = 42  # synthetic regime_id
            with patch("app.services.db.get_sync_conn", return_value=mock_conn):
                result = task_mod.classify_market_regime.apply(
                    args=[], kwargs={"decision_id": "test-decision-1"}
                ).get()

        # Verify orchestration.
        assert result["ok"] is True
        assert result["regime_id"] == 42
        assert result["regime"] == "Neutral"
        assert result["confidence"] == pytest.approx(0.55, abs=1e-4)
        assert result["cost_usd"] == pytest.approx(0.0042, abs=1e-6)
        assert result["decision_id"] == "test-decision-1"

        mock_provider.fetch.assert_called_once()
        mock_service.classify.assert_called_once()
        mock_persist.assert_called_once_with(mock_conn, fake_regime)
        # 铁律 32: task explicitly commits + closes.
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_classify_auto_generates_decision_id(self, monkeypatch) -> None:
        """decision_id=None auto-generates from UTC timestamp."""
        from app.tasks import market_regime_tasks as task_mod  # noqa: PLC0415

        task_mod._service = None
        task_mod._provider = None

        fake_regime = _make_mock_regime()
        mock_service = MagicMock()
        mock_service.classify.return_value = fake_regime
        monkeypatch.setattr(task_mod, "_get_service", lambda: mock_service)

        mock_provider = MagicMock()
        mock_provider.fetch.return_value = MarketIndicators(timestamp=datetime.now(UTC))
        monkeypatch.setattr(task_mod, "_get_provider", lambda: mock_provider)

        mock_conn = MagicMock()
        with (
            patch("app.tasks.market_regime_tasks.persist_market_regime", return_value=1),
            patch("app.services.db.get_sync_conn", return_value=mock_conn),
        ):
            result = task_mod.classify_market_regime.apply(args=[]).get()

        # Auto-generated ID starts with "market-regime-" + ISO datetime.
        assert result["decision_id"].startswith("market-regime-")
        assert "T" in result["decision_id"]  # ISO format contains 'T'

    def test_classify_rolls_back_on_persist_failure(self, monkeypatch) -> None:
        """Persist failure → conn.rollback() + raise (反 silent commit)."""
        from app.tasks import market_regime_tasks as task_mod  # noqa: PLC0415

        task_mod._service = None
        task_mod._provider = None

        fake_regime = _make_mock_regime()
        mock_service = MagicMock()
        mock_service.classify.return_value = fake_regime
        monkeypatch.setattr(task_mod, "_get_service", lambda: mock_service)

        mock_provider = MagicMock()
        mock_provider.fetch.return_value = MarketIndicators(timestamp=datetime.now(UTC))
        monkeypatch.setattr(task_mod, "_get_provider", lambda: mock_provider)

        mock_conn = MagicMock()
        # persist raises → task should rollback + propagate.
        with (
            patch(
                "app.tasks.market_regime_tasks.persist_market_regime",
                side_effect=RuntimeError("persist boom"),
            ),
            patch("app.services.db.get_sync_conn", return_value=mock_conn),
            pytest.raises(RuntimeError, match="persist boom"),
        ):
            task_mod.classify_market_regime.apply(args=[]).get()

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Beat schedule registration
# ─────────────────────────────────────────────────────────────


class TestBeatScheduleRegistration:
    def test_three_market_regime_entries_present(self) -> None:
        """V3 §5.3 cadence: 09:00 / 14:30 / 16:00 Asia/Shanghai trading days."""
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        assert "risk-market-regime-0900" in CELERY_BEAT_SCHEDULE
        assert "risk-market-regime-1430" in CELERY_BEAT_SCHEDULE
        assert "risk-market-regime-1600" in CELERY_BEAT_SCHEDULE

    def test_schedules_target_correct_task(self) -> None:
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        for entry_name in (
            "risk-market-regime-0900",
            "risk-market-regime-1430",
            "risk-market-regime-1600",
        ):
            entry = CELERY_BEAT_SCHEDULE[entry_name]
            assert entry["task"] == "app.tasks.market_regime_tasks.classify_market_regime"

    def test_schedules_use_crontab_with_correct_hour_minute(self) -> None:
        """Verify crontab fields match V3 §5.3 spec."""
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        expected = {
            "risk-market-regime-0900": (9, 0),
            "risk-market-regime-1430": (14, 30),
            "risk-market-regime-1600": (16, 0),
        }
        for entry_name, (hour, minute) in expected.items():
            entry = CELERY_BEAT_SCHEDULE[entry_name]
            schedule = entry["schedule"]
            assert isinstance(schedule, crontab)
            # crontab._orig_hour / _orig_minute access the raw spec.
            assert str(hour) in str(schedule.hour)
            assert str(minute) in str(schedule.minute)

    def test_schedules_restrict_to_weekdays(self) -> None:
        """day_of_week='1-5' — Mon-Fri trading days only."""
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        for entry_name in (
            "risk-market-regime-0900",
            "risk-market-regime-1430",
            "risk-market-regime-1600",
        ):
            entry = CELERY_BEAT_SCHEDULE[entry_name]
            # crontab.day_of_week converts "1-5" to a set {1,2,3,4,5}.
            dow = entry["schedule"].day_of_week
            assert dow == {1, 2, 3, 4, 5}


# ─────────────────────────────────────────────────────────────
# celery_app.py imports list registration
# ─────────────────────────────────────────────────────────────


class TestCeleryAppImports:
    def test_market_regime_tasks_in_imports(self) -> None:
        """app.tasks.market_regime_tasks listed in celery_app.imports for Beat discovery."""
        from app.tasks.celery_app import celery_app  # noqa: PLC0415

        imports = celery_app.conf.imports
        assert "app.tasks.market_regime_tasks" in imports
