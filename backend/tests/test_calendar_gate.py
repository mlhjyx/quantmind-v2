"""Calendar gate tests — is_trading_day_today_or_skip (Plan 1 + Plan 1.5).

Plan 1 (DEV_SCHEDULER §6.12 Phase I): closed the zero-coverage gap on the SSOT gate
helper relied on by 7 Beat task functions. Includes a regression test for the latent
crash bug found during precondition check (铁律 36): every Beat caller passes a stdlib
`logging.Logger`, but the helper's skip-log previously passed structlog-style kwargs →
`TypeError` on the skip path.

Plan 1.5 (Layer 3 DB fallback): the gate now runs a conn-backed TradingDayChecker so
the local `trading_calendar` DB table (Layer 3) answers when the Tushare API is
unreachable — without it the chain degrades to a holiday-blind weekday heuristic.

关联铁律: 33 (fail-loud) / 36 (precondition) / 10b (生产入口验证) / 40 (no test debt).
关联: LL-181 (节假日 Beat 空跑 lesson) / LL-193 (audit cascade — full-file verify).
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock, patch


def _mock_calendar(is_td: bool, reason: str = "test-reason") -> MagicMock:
    """Build a mock CalendarProvider returning a fixed is_trading_day verdict."""
    cal = MagicMock()
    cal.is_trading_day_with_reason.return_value = (is_td, reason)
    return cal


# ─────────────────────────────────────────────────────────────
# is_trading_day_today_or_skip — the SSOT gate helper (bool + logger contract)
# ─────────────────────────────────────────────────────────────


class TestIsTradingDayTodayOrSkip:
    """The public gate's bool return + logger behavior. The trading-day verdict is
    resolved by `_resolve_trading_day` — patched here so these tests stay focused on
    the gate's contract (not the resolution layers, covered by TestLayer3DbFallback).
    """

    def test_returns_true_on_trading_day(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch(
            "qm_platform.calendar._resolve_trading_day",
            return_value=(True, "tushare_api: 交易日"),
        ):
            assert is_trading_day_today_or_skip() is True

    def test_returns_false_on_non_trading_day(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch(
            "qm_platform.calendar._resolve_trading_day",
            return_value=(False, "heuristic: 周末"),
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
            "qm_platform.calendar._resolve_trading_day",
            return_value=(False, "tushare_api: 非交易日"),
        ):
            # Must not raise — the latent bug this test exists to catch.
            result = is_trading_day_today_or_skip(logger=stdlib_logger)
        assert result is False

    def test_logger_records_skip_on_non_trading_day(self, caplog) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        stdlib_logger = logging.getLogger("test.calendar_gate.records")
        with (
            patch(
                "qm_platform.calendar._resolve_trading_day",
                return_value=(False, "tushare_api: 非交易日"),
            ),
            caplog.at_level(logging.INFO),
        ):
            is_trading_day_today_or_skip(logger=stdlib_logger)
        assert any("non-trading day" in r.getMessage() for r in caplog.records)

    def test_logger_silent_on_trading_day(self, caplog) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        stdlib_logger = logging.getLogger("test.calendar_gate.silent")
        with (
            patch(
                "qm_platform.calendar._resolve_trading_day",
                return_value=(True, "tushare_api: 交易日"),
            ),
            caplog.at_level(logging.INFO),
        ):
            is_trading_day_today_or_skip(logger=stdlib_logger)
        assert not [r for r in caplog.records if "non-trading day" in r.getMessage()]

    def test_logger_none_does_not_crash(self) -> None:
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        with patch(
            "qm_platform.calendar._resolve_trading_day",
            return_value=(False, "heuristic: 周末"),
        ):
            assert is_trading_day_today_or_skip(logger=None) is False


# ─────────────────────────────────────────────────────────────
# Plan 1.5 — Layer 3 DB fallback (conn-backed TradingDayChecker)
# ─────────────────────────────────────────────────────────────


class TestLayer3DbFallback:
    """Plan 1.5 — the gate runs a conn-backed TradingDayChecker so Layer 3 (local
    `trading_calendar` DB table) answers when the Tushare API is unreachable.
    """

    def test_gate_with_conn_factory_builds_db_backed_checker(self) -> None:
        """conn_factory given → gate builds TradingDayChecker(conn=...) and closes it."""
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        mock_conn = MagicMock()
        mock_checker = MagicMock()
        mock_checker.is_trading_day.return_value = (False, "local_db: 非交易日")
        with patch(
            "engines.trading_day_checker.TradingDayChecker", return_value=mock_checker
        ) as mock_cls:
            result = is_trading_day_today_or_skip(conn_factory=lambda: mock_conn)

        assert result is False
        mock_cls.assert_called_once_with(conn=mock_conn)
        # The short-lived conn must be closed after the single check.
        mock_conn.close.assert_called_once()

    def test_layer3_reads_local_trading_calendar(self) -> None:
        """TradingDayChecker Layer 3 — with QMT+Tushare off, a conn answers from the
        local trading_calendar table (the path Plan 1.5 wires into the gate).
        """
        from engines.trading_day_checker import TradingDayChecker  # noqa: PLC0415

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (False,)  # trading_calendar: non-trading
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        checker = TradingDayChecker(conn=mock_conn)
        with (
            patch.object(checker, "_check_qmt", return_value=None),
            patch.object(checker, "_check_tushare", return_value=None),
        ):
            is_td, reason = checker.is_trading_day(date(2026, 10, 1))

        assert is_td is False
        assert "local_db" in reason

    def test_conn_factory_failure_degrades_gracefully(self) -> None:
        """conn_factory raises → gate falls back to the conn-less path, never crashes."""
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        def _boom():
            raise RuntimeError("DB unreachable")

        with patch(
            "qm_platform.calendar.get_calendar",
            return_value=_mock_calendar(True, "tushare_api: 交易日"),
        ):
            result = is_trading_day_today_or_skip(conn_factory=_boom)
        assert result is True  # degraded to the conn-less get_calendar() path

    def test_checker_runtime_failure_degrades_gracefully(self) -> None:
        """TradingDayChecker raising at runtime → gate degrades to the conn-less
        path, never crashes (铁律 33 fail-safe — the gate must always return a
        verdict; a crash here would take down the Beat task it guards).
        """
        from qm_platform.calendar import is_trading_day_today_or_skip  # noqa: PLC0415

        mock_checker = MagicMock()
        mock_checker.is_trading_day.side_effect = RuntimeError("checker boom")
        with (
            patch("engines.trading_day_checker.TradingDayChecker", return_value=mock_checker),
            patch(
                "qm_platform.calendar.get_calendar",
                return_value=_mock_calendar(True, "tushare_api: 交易日"),
            ),
        ):
            result = is_trading_day_today_or_skip(conn_factory=lambda: MagicMock())
        assert result is True  # degraded to the conn-less get_calendar() path


# ─────────────────────────────────────────────────────────────
# Layer 4 heuristic — holiday-blind by nature (last resort)
# ─────────────────────────────────────────────────────────────


class TestHeuristicFallbackLimitation:
    """Layer 4 (weekday heuristic) is holiday-blind by nature. Plan 1.5 wired Layer 3
    (local trading_calendar DB) into the gate, so the gate only reaches Layer 4 when
    Tushare AND the local DB both lack the date — see TestLayer3DbFallback.
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
        # trading day. Plan 1.5 wired Layer 3 (local DB) ahead of this layer so the
        # gate avoids the heuristic whenever the trading_calendar table has the date.
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
    import pytest

    pytest.main([__file__, "-v"])
