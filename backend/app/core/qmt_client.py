"""QMTClient — Redis缓存读取接口。

其他模块通过本客户端读取QMT Data Service同步到Redis的数据，
不直接import xtquant。

用法:
    from app.core.qmt_client import get_qmt_client
    client = get_qmt_client()
    positions = client.get_positions()
    nav = client.get_nav()
    price = client.get_price("000001.SZ")
"""

import json
import logging
from typing import Any

import redis

from app.config import settings

logger = logging.getLogger("qmt_client")

# 与 qmt_data_service.py 保持一致
CACHE_PORTFOLIO_CURRENT = "portfolio:current"
CACHE_PORTFOLIO_NAV = "portfolio:nav"
CACHE_MARKET_PREFIX = "market:latest:"
CACHE_QMT_STATUS = "qmt:connection_status"


class QMTClient:
    """QMT数据读取客户端（从Redis缓存读取）。"""

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or settings.REDIS_URL
        self._redis = redis.from_url(url, decode_responses=True)

    def is_connected(self) -> bool:
        """QMT Data Service是否连接正常。"""
        try:
            status = self._redis.get(CACHE_QMT_STATUS)
            return status == "connected"
        except Exception:
            return False

    def get_positions(self) -> dict[str, int]:
        """获取当前持仓 {code: shares}。"""
        try:
            raw = self._redis.hgetall(CACHE_PORTFOLIO_CURRENT)
            return {k: int(float(v)) for k, v in raw.items()}
        except Exception:
            logger.warning("读取持仓缓存失败", exc_info=True)
            return {}

    def get_nav(self) -> dict[str, Any] | None:
        """获取资产概览 {cash, total_value, updated_at, position_count}。"""
        try:
            raw = self._redis.get(CACHE_PORTFOLIO_NAV)
            if raw:
                return json.loads(raw)
            return None
        except Exception:
            logger.warning("读取NAV缓存失败", exc_info=True)
            return None

    def get_price(self, code: str) -> float | None:
        """获取单只股票最新价格。"""
        try:
            raw = self._redis.get(f"{CACHE_MARKET_PREFIX}{code}")
            if raw:
                data = json.loads(raw)
                return data.get("price")
            return None
        except Exception:
            return None

    def get_prices(self, codes: list[str]) -> dict[str, float]:
        """批量获取股票最新价格。"""
        result = {}
        try:
            pipe = self._redis.pipeline()
            for code in codes:
                pipe.get(f"{CACHE_MARKET_PREFIX}{code}")
            values = pipe.execute()
            for code, raw in zip(codes, values, strict=False):
                if raw:
                    data = json.loads(raw)
                    price = data.get("price")
                    if price and price > 0:
                        result[code] = price
        except Exception:
            logger.warning("批量读取价格缓存失败", exc_info=True)
        return result


# ── 全局单例 ─────────────────────────────────────────────
_client: QMTClient | None = None


def get_qmt_client() -> QMTClient:
    """获取全局 QMTClient 单例。"""
    global _client
    if _client is None:
        _client = QMTClient()
    return _client
