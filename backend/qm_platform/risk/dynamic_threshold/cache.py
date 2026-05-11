"""ThresholdCache — Redis-backed with in-memory fallback (S7, V3 §6.4 + §14 #4).

Redis: low-latency reads for L1 per-tick threshold queries.
  Key: risk:thresholds:{symbol_id}:{rule_id} (Hash)
  TTL: 5min (与 Beat 同步, fallback 静态 .env)

InMemoryThresholdCache: dict-backed for testing / Redis-unavailable fallback.

Protocol interface allows swapping implementations.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Redis key prefix
_REDIS_PREFIX = "risk:thresholds"


class ThresholdCache(Protocol):
    """阈值缓存协议 — get/set/flush."""

    def get(self, rule_id: str, code: str) -> float | None:
        """读取单股单规则 effective threshold. 未缓存返 None."""
        ...

    def set_batch(self, thresholds: dict[str, dict[str, float]], ttl: int = 300) -> None:
        """批量写入全量阈值. ttl 默认 5min."""
        ...

    def flush(self) -> None:
        """清空缓存."""
        ...


class InMemoryThresholdCache:
    """内存阈值缓存 — dict-backed, 测试用 / Redis 不可用 fallback."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, float]] = {}

    def get(self, rule_id: str, code: str) -> float | None:
        rule_store = self._store.get(rule_id)
        if rule_store is None:
            return None
        return rule_store.get(code)

    def set_batch(self, thresholds: dict[str, dict[str, float]], ttl: int = 300) -> None:
        """全量替换 (反增量 merge, 保持跟 Beat 同步)."""
        # deep copy to avoid external mutation
        self._store = {rule_id: dict(stocks) for rule_id, stocks in thresholds.items()}
        logger.debug(
            "[threshold-cache:memory] set_batch rules=%d stocks=%d",
            len(thresholds),
            sum(len(s) for s in thresholds.values()),
        )

    def flush(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return sum(len(s) for s in self._store.values())


class RedisThresholdCache:
    """Redis 阈值缓存 — 生产用 (V3 §6.4).

    Key: risk:thresholds:{rule_id}:{code} → float
    TTL: 5min default (300s)
    """

    def __init__(self, redis_client: Any = None, prefix: str = _REDIS_PREFIX) -> None:
        self._redis = redis_client
        self._prefix = prefix
        self._connected: bool = False

    def _ensure_redis(self) -> bool:
        """懒初始化 Redis client (避免 import 时连 Redis).

        首次失败后停止重试 (set _connected=True), 反 per-tick 2s 阻塞.
        Redis 恢复需进程重启 (或 L3 5min Beat 重新创建 RedisThresholdCache).
        """
        if self._redis is not None:
            return True
        if self._connected:
            return False  # 已尝试过, 不再重试 (反 per-tick 2s blocking)

        try:
            import redis  # noqa: PLC0415

            self._redis = redis.Redis(host="localhost", port=6379, socket_connect_timeout=2)
            self._redis.ping()
            self._connected = True
            logger.info("[threshold-cache:redis] connected")
            return True
        except Exception as e:
            logger.warning(
                "[threshold-cache:redis] connection failed: %s, "
                "fallback to in-memory (no further retries this process)",
                e,
            )
            self._connected = True  # 停止重试 (反 per-tick 2s blocking)
            return False

    def get(self, rule_id: str, code: str) -> float | None:
        if not self._ensure_redis():
            return None
        try:
            key = f"{self._prefix}:{rule_id}:{code}"
            val = self._redis.get(key)
            return float(val) if val is not None else None
        except Exception as e:
            logger.error("[threshold-cache:redis] get failed: %s", e)
            return None

    def set_batch(self, thresholds: dict[str, dict[str, float]], ttl: int = 300) -> None:
        if not self._ensure_redis():
            return

        pipe = self._redis.pipeline()
        try:
            for rule_id, stocks in thresholds.items():
                for code, value in stocks.items():
                    key = f"{self._prefix}:{rule_id}:{code}"
                    pipe.setex(key, ttl, str(value))
            pipe.execute()
            logger.debug(
                "[threshold-cache:redis] set_batch rules=%d stocks=%d ttl=%d",
                len(thresholds),
                sum(len(s) for s in thresholds.values()),
                ttl,
            )
        except Exception as e:
            logger.error("[threshold-cache:redis] set_batch failed: %s", e)

    def flush(self) -> None:
        if not self._ensure_redis():
            return
        try:
            keys = self._redis.keys(f"{self._prefix}:*")
            if keys:
                self._redis.delete(*keys)
            logger.debug("[threshold-cache:redis] flushed %d keys", len(keys))
        except Exception as e:
            logger.error("[threshold-cache:redis] flush failed: %s", e)
