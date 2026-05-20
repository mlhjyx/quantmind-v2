"""Calendar gate tests — is_trading_day_today_or_skip (Plan 1, DEV_SCHEDULER §6.12 Phase I).

Closes the zero-coverage gap: prior to Plan 1 the SSOT gate helper relied on by 7
Beat task functions had no real test — only one `@pytest.mark.skip` scaffold stub
(test_flow_schedule_cascade.py).

Includes a regression test for the latent crash bug found during Plan 1 precondition
check (铁律 36): every Beat caller passes a stdlib `logging.Logger`, but the helper's
skip-log previously passed structlog-style kwargs → `TypeError` on the skip path.

关联铁律: 33 (fail-loud) / 36 (precondition) / 10b (生产入口验证) / 40 (no test debt).
关联: LL-181 (节假日 Beat 空跑 lesson) / LL-193 (audit cascade — full-file verify).
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _mock_calendar(is_td: bool, reason: str = "test-reason") -> MagicMock:
    """Build a mock CalendarProvider returning a fixed is_trading_day verdict."""
    cal = MagicMock()
    cal.is_trading_day_with_reason.return_value = (is_td, reason)
    return cal


# ─────────────────────────────────────────────────────────────
# is_trading_day_today_or_skip — the SSOT gate helper
# ─────────────────────────────────────────────────────────────


class TestIsTradingDayTodayOrSkip:
    def test_returns_true_on_trading_day(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch("qm_platform.calendar.get_calendar", return_value=_mock_calendar(True)):
            assert is_trading_day_today_or_skip() is True

    def test_returns_false_on_non_trading_day(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch(
            "qm_platform.calendar.get_calendar",
            return_value=_mock_calendar(False, "heuristic: 周末"),
        ):
            assert is_trading_day_today_or_skip() is False

    def test_stdlib_logger_skip_does_not_crash(self) -> None:
        """Regression (Plan 1 precondition find): every Beat caller passes a stdlib
        logging.Logger. The skip-log must NOT pass structlog-style kwargs — those
        raise TypeError on a stdlib Logger.info. This test guards that crash.
        """
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        stdlib_logger = logging.getLogger("test.calendar_gate.crash")
        with patch(
            "qm_platform.calendar.get_calendar",
            return_value=_mock_calendar(False, "tushare_api: 非交易日"),
        ):
            # Must not raise — the latent bug this test exists to catch.
            result = is_trading_day_today_or_skip(logger=stdlib_logger)
        assert result is False

    def test_logger_records_skip_on_non_trading_day(self, caplog) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        stdlib_logger = logging.getLogger("test.calendar_gate.records")
        with (
            patch(
                "qm_platform.calendar.get_calendar",
                return_value=_mock_calendar(False, "tushare_api: 非交易日"),
            ),
            caplog.at_level(logging.INFO),
        ):
            is_trading_day_today_or_skip(logger=stdlib_logger)
        assert any("non-trading day" in r.getMessage() for r in caplog.records)

    def test_logger_silent_on_trading_day(self, caplog) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        stdlib_logger = logging.getLogger("test.calendar_gate.silent")
        with (
            patch("qm_platform.calendar.get_calendar", return_value=_mock_calendar(True)),
            caplog.at_level(logging.INFO),
        ):
            is_trading_day_today_or_skip(logger=stdlib_logger)
        assert not [r for r in caplog.records if "non-trading day" in r.getMessage()]

    def test_logger_none_does_not_crash(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch(
            "qm_platform.calendar.get_calendar",
            return_value=_mock_calendar(False, "heuristic: 周末"),
        ):
            assert is_trading_day_today_or_skip(logger=None) is False


# ─────────────────────────────────────────────────────────────
# Heuristic fallback limitation — documents the Plan 1.5 follow-up
# ─────────────────────────────────────────────────────────────


class TestHeuristicFallbackLimitation:
    """Documents the Plan 1.5 follow-up: with no DB conn + Tushare unreachable, the
    gate degrades to a Layer-4 weekday heuristic that CANNOT detect 法定节假日.
    """

    def test_heuristic_layer_misclassifies_weekday_holiday(self) -> None:
        from engines.trading_day_checker import TradingDayChecker  # noqa: PLC0415

        checker = TradingDayChecker(conn=None)
        national_day = date(2026, 10, 1)  # 国庆节 — a Thursday (weekday holiday)
        assert national_day.weekday() < 5  # sanity: it IS a weekday

        # Force layers 1-3 off → only the Layer 4 heuristic answers.
        with (
            patch.object(checker, "_check_qmt", return_value=None),
            patch.object(checker, "_check_tushare", return_value=None),
            patch.object(checker, "_check_local_db", return_value=None),
        ):
            is_td, reason = checker.is_trading_day(national_day)

        # The heuristic has NO holiday knowledge → mis-classifies the holiday as a
        # trading day. This is the gap Plan 1.5 closes by wiring the Layer 3 DB table.
        assert is_td is True
        assert "heuristic" in reason


# ─────────────────────────────────────────────────────────────
# Task skip paths — the 3 Beat tasks touched by Plan 1
# ─────────────────────────────────────────────────────────────


class TestTaskSkipPaths:
    def test_fundamental_context_ingest_skips_non_trading_day(self) -> None:
        from app.tasks import fundamental_ingest_tasks as task_mod  # noqa: PLC0415

        with (
            patch("qm_platform.calendar.is_trading_day_today_or_skip", return_value=False),
            patch("app.services.db.get_sync_conn") as mock_conn,
        ):
            result = task_mod.fundamental_context_ingest.apply(kwargs={"symbol_id": "600519"}).get()
        assert result == {"status": "skipped", "reason": "non_trading_day"}
        # Skip happened before the DB layer — no connection opened.
        mock_conn.assert_not_called()

    def test_factor_lifecycle_skips_non_trading_day(self) -> None:
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        with patch("qm_platform.calendar.is_trading_day_today_or_skip", return_value=False):
            result = task_mod.factor_lifecycle_task.apply(args=[]).get()
        assert result == {"status": "skipped", "reason": "non_trading_day"}

    def test_data_quality_report_skips_non_trading_day(self) -> None:
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        with patch(
            "qm_platform.calendar.get_calendar",
            return_value=_mock_calendar(False, "tushare_api: 非交易日"),
        ):
            result = task_mod.data_quality_report_task.apply(
                args=[], kwargs={"trade_date_str": "2026-10-01"}
            ).get()
        assert result["status"] == "skipped"
        assert result["trade_date"] == "2026-10-01"
        assert "非交易日" in result["reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
