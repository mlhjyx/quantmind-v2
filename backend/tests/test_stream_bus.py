"""StreamBus 单元测试。"""

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_redis():
    """Mock Redis连接。"""
    with patch("app.core.stream_bus.redis") as mock_mod:
        mock_pool = MagicMock()
        mock_mod.ConnectionPool.from_url.return_value = mock_pool
        mock_r = MagicMock()
        mock_mod.Redis.return_value = mock_r
        yield mock_r, mock_pool


class TestStreamBus:
    """StreamBus核心功能测试。"""

    def test_publish_sync_success(self, mock_redis):
        """消息格式正确（含published_at、source、payload）。"""
        mock_r, _ = mock_redis
        mock_r.xadd.return_value = "1234567890-0"

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        msg_id = bus.publish_sync(
            "qm:signal:generated",
            {"trade_date": "2026-04-04", "stock_count": 15},
            source="signal_service",
        )

        assert msg_id == "1234567890-0"
        mock_r.xadd.assert_called_once()
        call_args = mock_r.xadd.call_args
        fields = call_args[0][1]
        assert "published_at" in fields
        assert fields["source"] == "signal_service"
        assert "trade_date" in fields["payload"]

    def test_publish_sync_failure_graceful(self, mock_redis):
        """Redis断连时不抛异常，返回None。"""
        mock_r, _ = mock_redis
        mock_r.xadd.side_effect = ConnectionError("Redis down")

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        result = bus.publish_sync("qm:test", {"key": "value"})
        assert result is None

    def test_get_history(self, mock_redis):
        """历史消息按时间序返回。"""
        mock_r, _ = mock_redis
        mock_r.xrange.return_value = [
            ("1-0", {"source": "test", "payload": '{"a": 1}', "published_at": "t1"}),
            ("2-0", {"source": "test", "payload": '{"a": 2}', "published_at": "t2"}),
        ]

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        history = bus.get_history("qm:test", count=10)
        assert len(history) == 2
        assert history[0]["id"] == "1-0"
        assert history[0]["payload"] == {"a": 1}
        assert history[1]["payload"] == {"a": 2}

    def test_stream_len(self, mock_redis):
        """XLEN返回正确数值。"""
        mock_r, _ = mock_redis
        mock_r.xlen.return_value = 42

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        assert bus.stream_len("qm:test") == 42

    def test_stream_len_failure(self, mock_redis):
        """XLEN失败时返回0。"""
        mock_r, _ = mock_redis
        mock_r.xlen.side_effect = ConnectionError("down")

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        assert bus.stream_len("qm:test") == 0

    def test_maxlen_passed_to_xadd(self, mock_redis):
        """maxlen参数正确传递给XADD。"""
        mock_r, _ = mock_redis
        mock_r.xadd.return_value = "1-0"

        from app.core.stream_bus import StreamBus

        bus = StreamBus.__new__(StreamBus)
        bus._pool = MagicMock()
        bus._redis = mock_r

        bus.publish_sync("qm:test", {"k": "v"}, maxlen=500)
        call_kwargs = mock_r.xadd.call_args
        assert call_kwargs[1]["maxlen"] == 500
        assert call_kwargs[1]["approximate"] is True

    def test_json_encoder_datetime(self):
        """datetime类型可正确序列化。"""
        import json
        from datetime import datetime

        from app.core.stream_bus import _JSONEncoder

        dt = datetime(2026, 4, 4, 14, 30, 0, tzinfo=UTC)
        result = json.dumps({"ts": dt}, cls=_JSONEncoder)
        assert "2026-04-04" in result

    def test_json_encoder_decimal(self):
        """Decimal类型可正确序列化。"""
        import json
        from decimal import Decimal

        from app.core.stream_bus import _JSONEncoder

        result = json.dumps({"price": Decimal("123.456")}, cls=_JSONEncoder)
        assert "123.456" in result
