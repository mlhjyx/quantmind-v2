"""Session 21 Fix B regression: config_guard.assert_execution_mode_integrity.

F17 背景: .env EXECUTION_MODE=paper 17 天未切 live, config_guard triple-source
不覆盖此单源字段, PR-A 合入后无启动守门, 直到 Stage 4.1 首日 17:35 pt_audit
才逆向定位 cb_state live 0 行.

本 fix 在 PT 启动前 Step 0.5 + assert_execution_mode_integrity:
- 非法 mode → RAISE ConfigDriftError
- mode='paper' + 近 7 天有 live trade_log → WARN (不 raise, avoid blast radius)
- mode='live' → INFO (真金模式提示)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engines import config_guard as cg_module
from backend.engines.config_guard import (
    ConfigDriftError,
    assert_execution_mode_integrity,
)


class TestModeValidation:
    """Mode 合法性校验 (非法值 RAISE)."""

    def test_invalid_mode_raises(self):
        """mode='test' → ConfigDriftError."""
        with pytest.raises(ConfigDriftError):
            assert_execution_mode_integrity(mode="test", conn=None)

    def test_empty_string_raises(self):
        """mode='' → ConfigDriftError."""
        with pytest.raises(ConfigDriftError):
            assert_execution_mode_integrity(mode="", conn=None)

    def test_uppercase_mode_raises(self):
        """mode='LIVE' (大写) → ConfigDriftError (case-sensitive)."""
        with pytest.raises(ConfigDriftError):
            assert_execution_mode_integrity(mode="LIVE", conn=None)

    def test_paper_mode_with_mock_conn_no_raise(self):
        """mode='paper' + mock conn → 不 raise (正常路径)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, None)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        assert_execution_mode_integrity(mode="paper", conn=mock_conn)

    def test_live_mode_no_db_touch(self):
        """mode='live' 不触 DB (conn=None 也 OK)."""
        assert_execution_mode_integrity(mode="live", conn=None)

    def test_mode_none_reads_settings_live(self, monkeypatch):
        """mode=None → settings.EXECUTION_MODE='live' (review MEDIUM 采纳: 生产默认路径覆盖)."""
        from app import config as app_config
        monkeypatch.setattr(app_config.settings, "EXECUTION_MODE", "live")
        mock_conn = MagicMock()
        # live 路径不碰 DB → cursor 不应被调用
        assert_execution_mode_integrity(mode=None, conn=mock_conn)
        mock_conn.cursor.assert_not_called()

    def test_mode_none_reads_settings_paper(self, monkeypatch):
        """mode=None → settings.EXECUTION_MODE='paper' + 无 live trade_log."""
        from app import config as app_config
        monkeypatch.setattr(app_config.settings, "EXECUTION_MODE", "paper")
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, None)
        # psycopg2 cursor as context manager
        mock_conn.cursor.return_value.__enter__ = lambda self: mock_cur
        mock_conn.cursor.return_value.__exit__ = lambda *args: None
        assert_execution_mode_integrity(mode=None, conn=mock_conn)
        mock_conn.cursor.assert_called()


class TestPaperLiveTradeDetection:
    """mode='paper' 时 live trade_log 交叉检测 (F17 防重演)."""

    def test_paper_with_recent_live_trades_emits_warning(self, monkeypatch):
        """mode='paper' + 近 7 天有 live trade → logger.warning 被调用含 F17."""
        # Patch logger.warning 直接捕获 (structlog caplog 不可靠, monkeypatch 稳)
        warnings_captured = []
        real_warning = cg_module.logger.warning

        def capture_warning(msg, *args, **kwargs):
            warnings_captured.append(msg % args if args else msg)
            return real_warning(msg, *args, **kwargs)

        monkeypatch.setattr(cg_module.logger, "warning", capture_warning)

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (36, "2026-04-17")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        assert_execution_mode_integrity(mode="paper", conn=mock_conn)

        assert any(
            "F17" in msg or "live trade_log" in msg for msg in warnings_captured
        ), f"预期 warning 含 F17/live trade_log, 实际: {warnings_captured}"

    def test_paper_with_no_recent_live_trades_emits_info(self, monkeypatch):
        """mode='paper' + 无 live trade → logger.info 校验通过."""
        infos_captured = []
        real_info = cg_module.logger.info

        def capture_info(msg, *args, **kwargs):
            infos_captured.append(msg % args if args else msg)
            return real_info(msg, *args, **kwargs)

        monkeypatch.setattr(cg_module.logger, "info", capture_info)

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, None)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        assert_execution_mode_integrity(mode="paper", conn=mock_conn)

        assert any(
            "校验通过" in msg for msg in infos_captured
        ), f"预期 info 含 '校验通过', 实际: {infos_captured}"

    def test_paper_with_db_cursor_error_non_blocking(self, monkeypatch):
        """mode='paper' + DB cursor 异常 → 不 raise (非阻塞降级)."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB connection reset")

        # 应正常返回 (不 raise)
        assert_execution_mode_integrity(mode="paper", conn=mock_conn)


class TestSqlQueryShape:
    """regression: SQL 查询正确过滤 live + 时间窗口."""

    def test_sql_uses_execution_mode_live(self):
        """SQL 必须过滤 execution_mode = 'live'."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, None)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        assert_execution_mode_integrity(mode="paper", conn=mock_conn, recent_days=7)

        # 验证 execute 被调用 + SQL 含关键过滤
        mock_cur.execute.assert_called_once()
        sql_arg = mock_cur.execute.call_args[0][0]
        assert "execution_mode = 'live'" in sql_arg
        assert "trade_date >= %s" in sql_arg

    def test_recent_days_parameter_passed(self):
        """recent_days=30 → cutoff 参数对应 30 天前."""
        from datetime import date, timedelta
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, None)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        assert_execution_mode_integrity(mode="paper", conn=mock_conn, recent_days=30)

        params = mock_cur.execute.call_args[0][1]
        cutoff = params[0]
        expected = date.today() - timedelta(days=30)
        assert cutoff == expected
