"""data_quality_check hardening regression (Session 26).

验证 4-22/4-23 hang 事故的 fix:
  - statement_timeout / connect_timeout PG 硬超时
  - FileHandler delay=True (Windows 文件锁防御)
  - check_latest_dates future-date guard (2099-04-30 sentinel 不掩盖 lag)
  - check_future_dates P0 alert
  - main() fail-loud exit codes (0=OK, 1=alerts, 2=fatal)
  - per-step try/except 隔离

不覆盖:
  - 真实 DB end-to-end (手工 dry-run + 18:30 natural schtask)
  - 钉钉 webhook HTTP (mock 过)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import data_quality_check as dqc  # noqa: E402


class TestConstants:
    """模块常量合约."""

    def test_statement_timeout_60s(self):
        """statement_timeout 60s = cold scan 17s × 3.5 safety."""
        assert dqc.STATEMENT_TIMEOUT_MS == 60_000

    def test_connect_timeout_30s(self):
        assert dqc.CONNECT_TIMEOUT_S == 30

    def test_future_guard_7days(self):
        """cutoff = today + 7d, 足够 cover A 股长假 (国庆 7 天) 的 schedule slack."""
        assert dqc.FUTURE_DATE_GUARD_DAYS == 7

    def test_row_tolerance_8pct(self):
        assert dqc.ROW_TOLERANCE == 0.08

    def test_null_threshold_5pct(self):
        assert dqc.NULL_THRESHOLD == 0.05


class TestGetConnection:
    """get_connection 注入 statement_timeout + connect_timeout (铁律 33)."""

    def test_passes_statement_timeout(self):
        with patch.object(dqc.psycopg2, "connect") as mock_connect:
            dqc.get_connection()
            _, kwargs = mock_connect.call_args
            assert "options" in kwargs
            assert f"statement_timeout={dqc.STATEMENT_TIMEOUT_MS}" in kwargs["options"]

    def test_passes_connect_timeout(self):
        with patch.object(dqc.psycopg2, "connect") as mock_connect:
            dqc.get_connection()
            _, kwargs = mock_connect.call_args
            assert kwargs["connect_timeout"] == dqc.CONNECT_TIMEOUT_S

    def test_strips_async_driver_prefix(self):
        """psycopg2 不支持 asyncpg driver 前缀, 必须去掉."""
        with patch.object(dqc.psycopg2, "connect") as mock_connect:
            with patch.object(
                dqc.settings,
                "DATABASE_URL",
                "postgresql+asyncpg://u:p@h:5432/d",
            ):
                dqc.get_connection()
            args, _ = mock_connect.call_args
            # URL 在 args[0]
            assert args[0].startswith("postgresql://")
            assert "asyncpg" not in args[0]

    def test_custom_timeouts_respected(self):
        """允许测试/CLI override."""
        with patch.object(dqc.psycopg2, "connect") as mock_connect:
            dqc.get_connection(statement_timeout_ms=5000, connect_timeout_s=10)
            _, kwargs = mock_connect.call_args
            assert "statement_timeout=5000" in kwargs["options"]
            assert kwargs["connect_timeout"] == 10


class TestLoggerFileHandler:
    """logger FileHandler delay=True 防 Windows 文件锁竞争 (4-23 0-log 根因)."""

    def test_file_handler_uses_delay_true(self):
        assert dqc._file_handler.delay is True


class TestCheckFutureDates:
    """未来日期脏数据守护 (P0 alert, 2099-04-30 sentinel 教训)."""

    def _make_cur(self, responses):
        """mock cursor, fetchall 按 execute 调用顺序返回 responses[i]."""
        cur = MagicMock()
        cur.fetchall.side_effect = list(responses)
        return cur

    def test_no_future_rows_no_alerts(self):
        cur = self._make_cur([[], [], []])  # 3 表各 0 future rows
        today = date(2026, 4, 24)
        alerts = dqc.check_future_dates(cur, today)
        assert alerts == []

    def test_detects_2099_sentinel(self):
        """真实 bug 复现: klines_daily 有 2099-04-30 × 1 row."""
        cur = self._make_cur(
            [[(date(2099, 4, 30), 1)], [], []]  # klines 有 1 row, 其他 0
        )
        today = date(2026, 4, 24)
        alerts = dqc.check_future_dates(cur, today)
        assert len(alerts) == 1
        assert "[P0]" in alerts[0]
        assert "klines_daily" in alerts[0]
        assert "2099-04-30" in alerts[0]

    def test_cutoff_is_today_plus_7d(self):
        """SQL 参数必须是 today + 7d, 不是 today."""
        cur = self._make_cur([[], [], []])
        today = date(2026, 4, 24)
        dqc.check_future_dates(cur, today)

        # 第一次 execute 的参数
        first_call = cur.execute.call_args_list[0]
        params = first_call[0][1]
        expected = today + timedelta(days=dqc.FUTURE_DATE_GUARD_DAYS)
        assert params == (expected,)


class TestCheckLatestDatesFutureGuard:
    """check_latest_dates 用 effective_max (排除未来日期), 防脏数据掩盖 lag."""

    def test_sql_filters_trade_date_le_cutoff(self):
        """关键断言: MAX 查询必须含 WHERE trade_date <= cutoff, 否则脏数据回来.

        用 max == expected_date 触发 OK 分支, 避免 lag COUNT 查询污染 mock.
        """
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (date(2026, 4, 23),),  # klines max == expected (no lag)
            (date(2026, 4, 23),),  # daily_basic max
            (date(2026, 4, 23),),  # moneyflow max
        ]
        dqc.check_latest_dates(cur, date(2026, 4, 23), date(2026, 4, 24))

        # 检查第一次 execute 的 SQL
        first_sql = cur.execute.call_args_list[0][0][0]
        assert "WHERE trade_date <=" in first_sql
        assert "MAX(trade_date)" in first_sql

    def test_lag_alert_respects_effective_max(self):
        """若真实 max = 4-20 (非 2099 sentinel), 必须报滞后."""
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (date(2026, 4, 20),),  # klines effective max (脏 sentinel 已排除)
            (3,),  # lag = 3 trading days
            (date(2026, 4, 23),),  # daily_basic max OK
            (date(2026, 4, 23),),  # moneyflow max OK
        ]
        alerts = dqc.check_latest_dates(
            cur, date(2026, 4, 23), date(2026, 4, 24)
        )
        # klines 应有 lag alert (P0 因为 lag>1)
        klines_alerts = [a for a in alerts if "klines_daily" in a]
        assert len(klines_alerts) == 1
        assert "滞后3" in klines_alerts[0]
        assert "[P0]" in klines_alerts[0]

    def test_empty_table_alert(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (None,),  # klines empty
            (date(2026, 4, 23),),  # daily_basic
            (date(2026, 4, 23),),  # moneyflow
        ]
        alerts = dqc.check_latest_dates(
            cur, date(2026, 4, 23), date(2026, 4, 24)
        )
        assert any("表为空" in a for a in alerts)


class TestRunChecksExitCodes:
    """run_checks exit_code (0=OK, 1=alerts, 2=fatal 由 main() 处理)."""

    def _mock_args(self, dry_run=True, date_arg=None):
        a = MagicMock()
        a.dry_run = dry_run
        a.date = date_arg
        return a

    def test_exit_0_when_no_alerts(self):
        with patch.object(dqc, "get_connection") as mock_conn:
            cur = MagicMock()
            # trading_calendar → 2026-04-23
            cur.fetchone.side_effect = [
                (date(2026, 4, 23),),  # get_latest_trading_day
            ]
            # 每个 check 返回 no alerts
            mock_conn.return_value.cursor.return_value = cur
            with (
                patch.object(dqc, "check_future_dates", return_value=[]),
                patch.object(dqc, "check_row_counts", return_value=[]),
                patch.object(dqc, "check_null_ratios", return_value=[]),
                patch.object(dqc, "check_latest_dates", return_value=[]),
            ):
                rc = dqc.run_checks(self._mock_args())
        assert rc == 0

    def test_exit_1_when_alerts(self):
        with patch.object(dqc, "get_connection") as mock_conn:
            cur = MagicMock()
            cur.fetchone.side_effect = [(date(2026, 4, 23),)]
            mock_conn.return_value.cursor.return_value = cur
            with (
                patch.object(dqc, "check_future_dates", return_value=[]),
                patch.object(
                    dqc, "check_row_counts", return_value=["row alert"]
                ),
                patch.object(dqc, "check_null_ratios", return_value=[]),
                patch.object(dqc, "check_latest_dates", return_value=[]),
                patch.object(dqc, "send_dingtalk_alert"),
            ):
                rc = dqc.run_checks(self._mock_args(dry_run=True))
        assert rc == 1

    def test_per_step_exception_does_not_abort(self):
        """铁律 33: 单步异常不阻塞后续 check, 转 P0 alert 继续."""
        with patch.object(dqc, "get_connection") as mock_conn:
            cur = MagicMock()
            cur.fetchone.side_effect = [(date(2026, 4, 23),)]
            mock_conn.return_value.cursor.return_value = cur
            with (
                patch.object(
                    dqc,
                    "check_future_dates",
                    side_effect=RuntimeError("simulated"),
                ),
                patch.object(
                    dqc, "check_row_counts", return_value=[]
                ) as row_check,
                patch.object(dqc, "check_null_ratios", return_value=[]),
                patch.object(dqc, "check_latest_dates", return_value=[]),
                patch.object(dqc, "send_dingtalk_alert"),
            ):
                rc = dqc.run_checks(self._mock_args(dry_run=True))
            # 后续 step 仍被调用
            row_check.assert_called_once()
        # 异常转 alert → exit=1
        assert rc == 1


class TestMainFailLoud:
    """main() 顶层 try/except → stderr + exit(2) (铁律 33)."""

    def test_main_catches_fatal_and_returns_2(self, capsys):
        with (
            patch.object(
                dqc,
                "run_checks",
                side_effect=psycopg2_timeout_error(),
            ),
            patch.object(sys, "argv", ["data_quality_check.py", "--dry-run"]),
        ):
            rc = dqc.main()
        assert rc == 2
        captured = capsys.readouterr()
        assert "FATAL" in captured.err

    def test_main_propagates_run_checks_exit_code(self):
        """OK / alerts 情况下 main 直接 return run_checks 的 exit code."""
        with (
            patch.object(dqc, "run_checks", return_value=1),
            patch.object(sys, "argv", ["data_quality_check.py", "--dry-run"]),
        ):
            assert dqc.main() == 1

        with (
            patch.object(dqc, "run_checks", return_value=0),
            patch.object(sys, "argv", ["data_quality_check.py", "--dry-run"]),
        ):
            assert dqc.main() == 0


def psycopg2_timeout_error() -> Exception:
    """模拟 PG statement_timeout 触发的 QueryCanceled."""
    import psycopg2.errors

    try:
        # psycopg2 的 QueryCanceled 构造方式随版本变化; 退回通用 Exception
        return psycopg2.errors.QueryCanceled("canceling statement due to statement timeout")
    except Exception:
        return RuntimeError("statement timeout")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
