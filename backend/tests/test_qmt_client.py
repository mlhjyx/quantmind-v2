"""QMTClient 单元测试。"""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_redis():
    """Mock Redis连接。"""
    with patch("app.core.qmt_client.redis") as mock_mod:
        mock_r = MagicMock()
        mock_mod.from_url.return_value = mock_r
        yield mock_r


class TestQMTClient:
    """QMTClient 读取缓存测试。"""

    def test_is_connected_true(self, mock_redis):
        """连接状态为connected时返回True。"""
        mock_redis.get.return_value = "connected"
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.is_connected() is True

    def test_is_connected_false(self, mock_redis):
        """连接状态为disconnected时返回False。"""
        mock_redis.get.return_value = "disconnected"
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.is_connected() is False

    def test_get_positions(self, mock_redis):
        """持仓缓存正确解析。"""
        mock_redis.hgetall.return_value = {"000001.SZ": "1000", "600519.SH": "200"}
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        pos = client.get_positions()
        assert pos == {"000001.SZ": 1000, "600519.SH": 200}

    def test_get_positions_empty(self, mock_redis):
        """无持仓时返回空dict。"""
        mock_redis.hgetall.return_value = {}
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.get_positions() == {}

    def test_get_nav(self, mock_redis):
        """NAV缓存正确解析。"""
        nav_data = {"cash": 50000.0, "total_value": 1000000.0, "position_count": 15}
        mock_redis.get.return_value = json.dumps(nav_data)
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        nav = client.get_nav()
        assert nav["cash"] == 50000.0
        assert nav["total_value"] == 1000000.0

    def test_get_nav_none(self, mock_redis):
        """无NAV缓存时返回None。"""
        mock_redis.get.return_value = None
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.get_nav() is None

    def test_get_price(self, mock_redis):
        """单只股票价格正确读取。"""
        mock_redis.get.return_value = json.dumps({"price": 35.6, "high": 36.0, "low": 35.0})
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.get_price("000001.SZ") == 35.6

    def test_get_price_missing(self, mock_redis):
        """股票价格缓存不存在时返回None。"""
        mock_redis.get.return_value = None
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.get_price("999999.SZ") is None

    def test_get_prices_batch(self, mock_redis):
        """批量价格读取。"""
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [
            json.dumps({"price": 35.6}),
            None,
            json.dumps({"price": 1800.0}),
        ]
        mock_redis.pipeline.return_value = mock_pipe
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        prices = client.get_prices(["000001.SZ", "999999.SZ", "600519.SH"])
        assert prices == {"000001.SZ": 35.6, "600519.SH": 1800.0}

    def test_redis_failure_graceful(self, mock_redis):
        """Redis断连时不抛异常。"""
        mock_redis.hgetall.side_effect = ConnectionError("Redis down")
        from app.core.qmt_client import QMTClient

        client = QMTClient.__new__(QMTClient)
        client._redis = mock_redis
        assert client.get_positions() == {}
