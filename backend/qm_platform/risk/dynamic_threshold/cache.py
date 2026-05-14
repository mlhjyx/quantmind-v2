"""ThresholdCache — Redis-backed with in-memory fallback (S7, V3 §6.4 + §14 #4).

Redis: low-latency reads for L1 per-tick threshold queries.
  Key: risk:thresholds:{symbol_id}:{rule_id} (Hash)
  TTL: 5min (与 Beat 同步, fallback 静态 .env)

InMemoryThresholdCache: dict-backed for testing / Redis-unavailable fallback.

Protocol interface allows swapping implementations.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Redis key prefix
_REDIS_PREFIX = "risk:thresholds"

# HC-2b2 G8 (V3 §14 mode 4): Redis auto-reconnect cooldown. After a failed
# connect attempt, the next attempt is gated for this many seconds — long
# enough to avoid per-tick reconnect storms (the original `_connected`
# anti-pattern was 2s-blocking every tick), short enough that a recovered
# Redis is picked up within minutes WITHOUT a process restart.
_RECONNECT_COOLDOWN_S: float = 60.0


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
        # HC-2b2 G8: injected client (DI / test) → caller owns lifecycle, this
        # class never auto-(re)creates one. Lazy / self-managed client →
        # auto-reconnect after a cooldown window.
        self._injected: bool = redis_client is not None
        # monotonic ts of the last self-managed connect attempt (None = never
        # tried). Gates auto-reconnect retries to _RECONNECT_COOLDOWN_S.
        self._last_connect_attempt: float | None = None

    def _ensure_redis(self) -> bool:
        """懒初始化 + auto-reconnect Redis client (HC-2b2 G8, V3 §14 mode 4).

        失败后 **不再永久阻断** — 隔 _RECONNECT_COOLDOWN_S 秒自动重连 (替代原
        `_connect_attempted` 永久阻断体例). Redis 恢复无需进程重启. cooldown
        窗口防 per-tick 2s 重连风暴 (sustained 原 anti-per-tick-blocking 意图).

        Injected client (`_injected=True`, DI / test): caller owns lifecycle —
        本类永不 auto-create 真 redis.Redis(). 若 injected client 被 get/set 失败
        reset 为 None, `_ensure_redis` 返 False (caller 须自行 re-inject).
        """
        if self._redis is not None:
            return True
        if self._injected:
            # injected client reset to None by a get/set failure — caller owns
            # the lifecycle, do NOT auto-create a real redis.Redis() here.
            return False

        now = time.monotonic()
        if (
            self._last_connect_attempt is not None
            and now - self._last_connect_attempt < _RECONNECT_COOLDOWN_S
        ):
            return False  # 仍在 cooldown 窗口内, 不重试 (反 per-tick 2s blocking)
        self._last_connect_attempt = now

        try:
            import redis  # noqa: PLC0415

            self._redis = redis.Redis(host="localhost", port=6379, socket_connect_timeout=2)
            self._redis.ping()
            logger.info("[threshold-cache:redis] connected")
            return True
        except Exception as e:
            logger.warning(
                "[threshold-cache:redis] connection failed: %s, fallback to "
                "in-memory (auto-reconnect after %.0fs cooldown — no process "
                "restart needed)",
                e,
                _RECONNECT_COOLDOWN_S,
            )
            self._redis = None
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
            # HC-2b2 G8: drop the (now-suspect) client → next _ensure_redis
            # auto-reconnects after cooldown. Caller transparently falls back
            # to in-memory for this call (returns None).
            self._redis = None
            return None

    def set_batch(self, thresholds: dict[str, dict[str, float]], ttl: int = 300) -> None:
        """Pipeline-write all thresholds with TTL.

        Failure semantics (S7 audit-fix P1-2, post-reviewer):
        - Redis unavailable (lazy `_ensure_redis` returned False) → silent no-op,
          intentional fallback path documented in `_ensure_redis` (反 per-tick
          2s blocking). Operator visibility for this path is the caller's
          responsibility (e.g. monitoring cache miss rate).
        - Redis available but `pipe.execute()` raises (network blip / OOM /
          OOM-killed connection) → re-raise after logging. Caller (e.g. Celery
          task) decides retry policy (反 silent fail-loud violation 铁律 33).
        """
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
            # HC-2b2 G8: drop the suspect client before re-raising → next
            # _ensure_redis auto-reconnects after cooldown (caller decides retry).
            self._redis = None
            raise

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
            # HC-2b2 G8: drop the suspect client → next _ensure_redis auto-reconnects.
            self._redis = None
