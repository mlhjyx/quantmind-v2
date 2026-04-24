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
        """SET statement_timeout 必须走 %s 参数化 (对齐 compute_daily_ic/pt_watchdog)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        pmf._apply_statement_timeout(mock_conn)

        mock_cursor.execute.assert_called_once_with(
            "SET statement_timeout = %s", (60_000,)
        )


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

    def test_db_failure_returns_true_silent_ok(self, monkeypatch):
        """_get_sync_conn raise → silent_ok degrade 为 True 不阻塞拉取 (铁律 33-d)."""
        def _boom():
            raise RuntimeError("DB not reachable")

        monkeypatch.setattr(pmf, "_get_sync_conn", _boom)

        assert pmf._check_trading_day_or_skip() is True


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

        def _boom():
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
        """交易日路径 → main 返 _run() 的 return code (0 success)."""
        monkeypatch.setattr(pmf, "_check_trading_day_or_skip", lambda: True)
        monkeypatch.setattr(pmf, "_run", lambda: 0)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py"])

        assert pmf.main() == 0


class TestRunReturnContract:
    """_run() 必须返 int (main wrapper 契约依赖)."""

    def test_verify_mode_returns_0(self, monkeypatch):
        """--verify 路径: verify(conn) + close → return 0."""
        mock_conn = MagicMock()
        monkeypatch.setattr(pmf, "_get_sync_conn", lambda: mock_conn)
        monkeypatch.setattr(pmf, "_apply_statement_timeout", lambda c: None)
        monkeypatch.setattr(pmf, "verify", lambda c: None)
        monkeypatch.setattr(sys, "argv", ["pull_moneyflow.py", "--verify"])

        rc = pmf._run()

        assert rc == 0
        mock_conn.close.assert_called_once()
