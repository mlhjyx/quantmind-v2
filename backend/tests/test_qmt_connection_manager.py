"""QMT连接管理器测试。

验证:
1. paper模式下状态为disabled
2. live模式缺配置时状态为error
3. health_check返回正确结构
4. ensure_connected在paper模式下抛异常
5. Singleton模式
"""

from unittest.mock import patch

from app.services.qmt_connection_manager import QMTConnectionManager


class TestQMTConnectionManagerPaperMode:
    """Paper模式（默认）下的连接管理器测试。"""

    def setup_method(self) -> None:
        """每个测试前重置Singleton。"""
        QMTConnectionManager._instance = None

    def test_paper_mode_disabled(self) -> None:
        """paper模式下startup后状态为disabled。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mock_settings.QMT_PATH = ""
            mock_settings.QMT_ACCOUNT_ID = ""
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
        assert mgr.state == "disabled"
        assert mgr.broker is None

    def test_paper_mode_health_check(self) -> None:
        """paper模式health_check返回disabled且is_healthy=True。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mock_settings.QMT_PATH = ""
            mock_settings.QMT_ACCOUNT_ID = ""
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
            health = mgr.health_check()
        assert health["state"] == "disabled"
        assert health["is_healthy"] is True
        assert health["execution_mode"] == "paper"

    def test_ensure_connected_raises_in_paper_mode(self) -> None:
        """paper模式下ensure_connected抛出RuntimeError。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
            try:
                mgr.ensure_connected()
                raise AssertionError("应该抛出RuntimeError")
            except RuntimeError as e:
                assert "paper" in str(e).lower()

    def test_singleton(self) -> None:
        """QMTConnectionManager是Singleton。"""
        a = QMTConnectionManager()
        b = QMTConnectionManager()
        assert a is b


class TestQMTConnectionManagerLiveMode:
    """Live模式下的连接管理器测试（Mock broker）。"""

    def setup_method(self) -> None:
        """每个测试前重置Singleton。"""
        QMTConnectionManager._instance = None

    def test_live_mode_missing_config(self) -> None:
        """live模式缺QMT_PATH时状态为error。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "live"
            mock_settings.QMT_PATH = ""
            mock_settings.QMT_ACCOUNT_ID = ""
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
        assert mgr.state == "error"
        assert "未配置" in (mgr._last_error or "")

    def test_shutdown_from_disabled(self) -> None:
        """disabled状态下shutdown不报错。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
            mgr.shutdown()
        assert mgr.state == "disconnected"

    def test_health_check_structure(self) -> None:
        """health_check返回正确的字段结构。"""
        mgr = QMTConnectionManager()
        with patch("app.services.qmt_connection_manager.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mock_settings.QMT_PATH = ""
            mock_settings.QMT_ACCOUNT_ID = ""
            mgr._initialized = False
            mgr.__init__()  # type: ignore[misc]
            mgr.startup()
            health = mgr.health_check()

        required_keys = {
            "execution_mode",
            "state",
            "account_id",
            "qmt_path",
            "connected_at",
            "last_error",
            "is_healthy",
        }
        assert required_keys.issubset(health.keys())
