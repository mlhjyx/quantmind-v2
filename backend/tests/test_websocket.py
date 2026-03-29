"""WebSocket基础设施单元测试。

测试范围:
- 事件payload构造函数（events.py）
- BacktestWebSocketManager emit方法（manager.py）
- Room加入/离开逻辑（通过mock sio）
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.websocket.events import (
    EVENT_LOG,
    EVENT_PROGRESS,
    EVENT_REALTIME_NAV,
    EVENT_STATUS,
    make_log,
    make_progress,
    make_realtime_nav,
    make_status,
)
from app.websocket.manager import BacktestWebSocketManager, _room_name

# ─────────────────────────────────────────────────────────
# events.py 测试
# ─────────────────────────────────────────────────────────


class TestMakeProgress:
    """测试make_progress事件构造。"""

    def test_基本字段完整(self):
        payload = make_progress("run1", 50.0, date(2024, 1, 15), 10.5)
        assert payload["run_id"] == "run1"
        assert payload["progress_pct"] == 50.0
        assert payload["current_date"] == "2024-01-15"
        assert payload["elapsed_sec"] == 10.5

    def test_date字符串输入(self):
        payload = make_progress("run1", 100.0, "2024-06-01", 99.9)
        assert payload["current_date"] == "2024-06-01"

    def test_progress_pct精度(self):
        payload = make_progress("run1", 33.3333, date(2024, 1, 1), 0.0)
        assert payload["progress_pct"] == 33.33

    def test_elapsed_sec精度(self):
        payload = make_progress("run1", 0.0, date(2024, 1, 1), 12.3456)
        assert payload["elapsed_sec"] == 12.3


class TestMakeStatus:
    """测试make_status事件构造。"""

    def test_running状态(self):
        payload = make_status("run1", "running")
        assert payload["run_id"] == "run1"
        assert payload["status"] == "running"
        assert payload["message"] == ""

    def test_completed状态带消息(self):
        payload = make_status("run1", "completed", "回测完成")
        assert payload["status"] == "completed"
        assert payload["message"] == "回测完成"

    def test_failed状态(self):
        payload = make_status("run1", "failed", "内存不足")
        assert payload["status"] == "failed"


class TestMakeRealtimeNav:
    """测试make_realtime_nav事件构造。"""

    def test_基本字段(self):
        payload = make_realtime_nav("run1", date(2024, 3, 1), 1050000.0, 1020000.0)
        assert payload["run_id"] == "run1"
        assert payload["date"] == "2024-03-01"
        assert payload["nav"] == 1050000.0
        assert payload["benchmark_nav"] == 1020000.0

    def test_nav精度(self):
        payload = make_realtime_nav("run1", date(2024, 1, 1), 1000001.23456, 999999.0)
        assert payload["nav"] == 1000001.2346


class TestMakeLog:
    """测试make_log事件构造。"""

    def test_info级别(self):
        payload = make_log("run1", "info", "开始回测")
        assert payload["level"] == "INFO"
        assert payload["message"] == "开始回测"

    def test_error级别大写规范化(self):
        payload = make_log("run1", "error", "回测失败")
        assert payload["level"] == "ERROR"

    def test_warning级别(self):
        payload = make_log("run1", "warning", "数据不足")
        assert payload["level"] == "WARNING"


# ─────────────────────────────────────────────────────────
# manager.py 测试
# ─────────────────────────────────────────────────────────


class TestRoomName:
    """测试room命名规则。"""

    def test_room名称格式(self):
        assert _room_name("abc123") == "backtest:abc123"

    def test_特殊字符run_id(self):
        assert _room_name("run-2024-01") == "backtest:run-2024-01"


class TestBacktestWebSocketManager:
    """测试BacktestWebSocketManager推送方法。"""

    @pytest.fixture
    def manager(self):
        return BacktestWebSocketManager()

    @pytest.mark.asyncio
    async def test_emit_progress调用sio_emit(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_progress("run1", 50.0, date(2024, 1, 1), 5.0)
            mock_sio.emit.assert_called_once()
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == EVENT_PROGRESS
            assert call_args[1]["room"] == "backtest:run1"

    @pytest.mark.asyncio
    async def test_emit_status调用sio_emit(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_status("run1", "running")
            mock_sio.emit.assert_called_once()
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == EVENT_STATUS

    @pytest.mark.asyncio
    async def test_emit_realtime_nav调用sio_emit(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_realtime_nav("run1", date(2024, 1, 1), 1000000.0, 1000000.0)
            mock_sio.emit.assert_called_once()
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == EVENT_REALTIME_NAV

    @pytest.mark.asyncio
    async def test_emit_log调用sio_emit(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_log("run1", "INFO", "测试日志")
            mock_sio.emit.assert_called_once()
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == EVENT_LOG

    @pytest.mark.asyncio
    async def test_emit_completed发送completed状态(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_completed("run1", "回测完成")
            # 只发送status事件
            assert mock_sio.emit.call_count == 1
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == EVENT_STATUS
            assert call_args[0][1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_emit_failed发送failed状态和日志(self, manager):
        with patch("app.websocket.manager.sio") as mock_sio:
            mock_sio.emit = AsyncMock()
            await manager.emit_failed("run1", "数据库连接失败")
            # emit_failed发送2次: status + log
            assert mock_sio.emit.call_count == 2
            events = [call[0][0] for call in mock_sio.emit.call_args_list]
            assert EVENT_STATUS in events
            assert EVENT_LOG in events
