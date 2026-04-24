"""pull_moneyflow.py 铁律 43 硬化回归测试 (Session 27 Task A).

LL-068 扩散第 6 个 schtask script. 覆盖 4 项清单 (a-d):
  (a) STATEMENT_TIMEOUT_MS=60_000 session-level (parametrize %s)
  (b) print-only 豁免 FileHandler
  (c) boot stderr probe (`[pull_moneyflow] boot ... pid=...`)
  (d) main() top-level try/except → FATAL + return 2

Mock 策略: module-top `pro = ts.pro_api(...)` 依赖 TUSHARE_TOKEN (settings 导入即加载
.env, 本地测试已有). 若 CI 无 TOKEN 需补 fixture, 当前 dev env 通过.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# TUSHARE_TOKEN 已由 app.config 的 pydantic-settings 通过 .env 加载.
# 若无 token, 跳过整个模块 (而非 ImportError 炸掉 collection).
import pytest  # noqa: E402

try:
    import pull_moneyflow as pmf  # noqa: E402
except Exception as e:  # pragma: no cover - env guard
    pytest.skip(f"pull_moneyflow import fail (likely missing TUSHARE_TOKEN): {e}", allow_module_level=True)


class TestStatementTimeout:
    """铁律 43-a: PG session-level statement_timeout 硬超时."""

    def test_constant_60s(self):
        """STATEMENT_TIMEOUT_MS 与其他 daily 脚本对齐 (60s, 非 batch 脚本)."""
        assert pmf.STATEMENT_TIMEOUT_MS == 60_000

    def test_apply_statement_timeout_uses_parametrize(self):
        """SET statement_timeout 必须走 %s 参数化 (对齐 compute_daily_ic/pt_watchdog).

        Reviewer python-P3 采纳: 拆分 parametrize-style 校验 vs 值校验 (后者已由
        test_constant_60s 覆盖), 值改变时 error 更易定位.
        """
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        pmf._apply_statement_timeout(mock_conn)

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert call_args[0][0] == "SET statement_timeout = %s", "参数化 SQL 必须含 %s"
        assert isinstance(call_args[0][1], tuple), "第 2 参数必须 tuple (参数化契约)"
        assert isinstance(call_args[0][1][0], int), "tuple[0] 必须 int"


class TestCheckTradingDay:
    """_check_trading_day_or_skip: 非交易日返 False (schtask skip), 其他场景 True."""

    def _make_conn_row(self, row):
        """Build mock conn returning `row` from fetchone (trading_calendar SELECT)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = row
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def test_non_trading_day_returns_false(self, monkeypatch):
        """is_trading_day=False → 返 False (main 据此 skip)."""
        mock_conn = self._make_conn_row((False,))
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)

        assert pmf._check_trading_day_or_skip() is False
        mock_conn.close.assert_called_once()

    def test_trading_day_returns_true(self, monkeypatch):
        """is_trading_day=True → 返 True."""
        mock_conn = self._make_conn_row((True,))
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)

        assert pmf._check_trading_day_or_skip() is True
        mock_conn.close.assert_called_once()

    def test_missing_row_returns_true(self, monkeypatch):
        """trading_calendar 无该日记录 → fetchone=None → 返 True (fail-open)."""
        mock_conn = self._make_conn_row(None)
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)

        assert pmf._check_trading_day_or_skip() is True
        mock_conn.close.assert_called_once()

    def test_db_failure_returns_true_silent_ok(self, monkeypatch, capsys):
        """_get_sync_conn raise → silent_ok degrade 为 True 不阻塞拉取 (铁律 33-d).

        Reviewer python-P2 采纳: 异常 path 必写 stderr 诊断痕迹, 避免 DB outage
        silently swallowed 使下游 FATAL 误归因.
        """
        def _boom():
            raise RuntimeError("DB not reachable")

        monkeypatch.setattr(pmf, "_get_sync_conn", _boom)

        assert pmf._check_trading_day_or_skip() is True

        captured = capsys.readouterr()
        assert "trading_calendar check failed" in captured.err
        assert "RuntimeError" in captured.err
        assert "DB not reachable" in captured.err


class TestMainBootProbe:
    """铁律 43-c: main() 首行 boot stderr probe."""

    def test_boot_probe_to_stderr(self, monkeypatch, capsys):
        """main() 无论后续成败, boot probe 必写 stderr 含 pid + timestamp."""
        # 让 _check_trading_day_or_skip 返 False 使 main 尽早退出, 只验 boot probe.
        monkeypatch.setattr(pmf, "_check_trading_day_or_skip", lambda: False)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py"])

        rc = pmf.main()

        assert rc == 0
        captured = capsys.readouterr()
        # probe 格式: `[pull_moneyflow] boot <iso> pid=<int>`
        assert "[pull_moneyflow] boot" in captured.err
        assert f"pid={os.getpid()}" in captured.err


class TestMainExitOnException:
    """铁律 43-d: main() 顶层 try/except → FATAL stderr + return 2."""

    def test_exit_2_on_run_exception(self, monkeypatch, capsys):
        """_run raise → main 捕获 + FATAL + return 2 (schtask LastResult=2 告警)."""
        monkeypatch.setattr(pmf, "_check_trading_day_or_skip", lambda: True)

        def _boom(args):  # 接 args (reviewer python-P2 采纳 _run(args) 签名)
            raise ValueError("pipeline broken")

        monkeypatch.setattr(pmf, "_run", _boom)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py"])

        rc = pmf.main()

        assert rc == 2, f"铁律 43-d: fatal should return 2, got {rc}"
        captured = capsys.readouterr()
        assert "[pull_moneyflow] FATAL" in captured.err
        assert "ValueError" in captured.err
        assert "pipeline broken" in captured.err

    def test_exit_0_on_non_trading_day(self, monkeypatch, capsys):
        """非交易日 → main 返 0 + 打印跳过消息 (不触发告警)."""
        monkeypatch.setattr(pmf, "_check_trading_day_or_skip", lambda: False)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py"])

        rc = pmf.main()

        assert rc == 0
        captured = capsys.readouterr()
        assert "非交易日" in captured.out

    def test_exit_delegates_to_run_return_code(self, monkeypatch):
        """交易日路径 → main 返 _run(args) 的 return code (0 success).

        Reviewer python-P2 采纳: _run 签名变 (args: argparse.Namespace).
        """
        monkeypatch.setattr(pmf, "_check_trading_day_or_skip", lambda: True)
        monkeypatch.setattr(pmf, "_run", lambda args: 0)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py"])

        assert pmf.main() == 0


class TestRunReturnContract:
    """_run(args) 必须返 int + 保证 conn close (main wrapper 契约依赖).

    Reviewer python-P2 采纳: _run 接 parsed args, 测试直接构造 Namespace
    (不 monkeypatch sys.argv, 更直接 + 不 brittle).
    """

    def _make_args(self, **overrides):
        """Default argparse.Namespace for pull_moneyflow CLI."""
        import argparse
        defaults = {"start": None, "end": pmf.DEFAULT_END, "verify": False, "recent": False}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_verify_mode_returns_0(self, monkeypatch):
        """--verify 路径: verify(conn) + finally close → return 0."""
        mock_conn = MagicMock()
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)
        monkeypatch.setattr(pmf, "verify", lambda c: None)

        rc = pmf._run(self._make_args(verify=True))

        assert rc == 0
        mock_conn.close.assert_called_once()

    def test_close_in_finally_on_exception(self, monkeypatch):
        """Reviewer P1 采纳: 任何异常 path conn 必 finally close 防泄漏.

        原 3 处 happy-path close 异常时漏 close (add_column_comments /
        upsert_moneyflow / verify etc. raise 时 leak). single try/finally 修复.
        """
        mock_conn = MagicMock()
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)

        def _verify_boom(_):
            raise RuntimeError("verify broken")

        monkeypatch.setattr(pmf, "verify", _verify_boom)

        import pytest as _pt

        with _pt.raises(RuntimeError, match="verify broken"):
            pmf._run(self._make_args(verify=True))

        # 即便 verify() raise, conn.close() 仍被 finally 保证调用一次.
        mock_conn.close.assert_called_once()

    def test_early_exit_when_start_after_end_returns_0(self, monkeypatch):
        """Reviewer P2 采纳: 原 3 处 return 0 早退路径, 本 test 覆盖 L321
        (start_date > end_date → 已完成 + verify + close + return 0).

        模拟: DB MAX(trade_date) = 今天 → 下一天 > --end=今天 → 早退.
        """
        today_yyyymmdd = date.today().strftime("%Y%m%d")

        mock_conn = MagicMock()
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)
        monkeypatch.setattr(pmf, "add_column_comments", lambda c: None)
        # MAX(trade_date) = 今天 → start_date = 今天 + 1 > end_date (今天)
        monkeypatch.setattr(pmf, "get_max_trade_date", lambda c: today_yyyymmdd)
        verify_calls = []
        monkeypatch.setattr(pmf, "verify", lambda c: verify_calls.append(c))

        rc = pmf._run(self._make_args(end=today_yyyymmdd))

        assert rc == 0
        assert len(verify_calls) == 1, "早退 path 也调 verify() 确认 DB 完备性"
        mock_conn.close.assert_called_once()
