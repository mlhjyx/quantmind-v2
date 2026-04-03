"""StreamBus — Redis Streams 统一数据总线。

所有模块间的事件通信通过 Redis Streams 实现。
Stream 命名规范: qm:{domain}:{event_type}

设计原则:
- publish 失败不阻塞主流程（只日志不抛异常）
- 同步优先（当前系统 sync 为主）
- maxlen 防止 Stream 无限增长
"""

import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis

from app.config import settings

logger = logging.getLogger("stream_bus")

# ── Stream 名称常量 ──────────────────────────────────────
STREAM_SIGNAL_GENERATED = "qm:signal:generated"
STREAM_EXECUTION_ORDER_FILLED = "qm:execution:order_filled"
STREAM_EXECUTION_ORDER_FAILED = "qm:execution:order_failed"
STREAM_FACTOR_COMPUTED = "qm:factor:computed"
STREAM_HEALTH_CHECK_RESULT = "qm:health:check_result"
STREAM_SCHEDULE_TASK_COMPLETED = "qm:schedule:task_completed"
STREAM_QMT_STATUS = "qm:qmt:status"
STREAM_QMT_REQUEST = "qm:qmt:request"
STREAM_PMS_POSITION_UPDATE = "qm:pms:position_update"
STREAM_PMS_PROTECTION_TRIGGERED = "qm:pms:protection_triggered"

# 所有已注册的 Stream（用于管理端点枚举）
ALL_STREAMS = [
    STREAM_SIGNAL_GENERATED,
    STREAM_EXECUTION_ORDER_FILLED,
    STREAM_EXECUTION_ORDER_FAILED,
    STREAM_FACTOR_COMPUTED,
    STREAM_HEALTH_CHECK_RESULT,
    STREAM_SCHEDULE_TASK_COMPLETED,
    STREAM_QMT_STATUS,
    STREAM_QMT_REQUEST,
    STREAM_PMS_POSITION_UPDATE,
    STREAM_PMS_PROTECTION_TRIGGERED,
]

DEFAULT_MAXLEN = 10_000


class _JSONEncoder(json.JSONEncoder):
    """处理 datetime / Decimal 等非原生 JSON 类型。"""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        from decimal import Decimal

        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


class StreamBus:
    """Redis Streams 统一数据总线。"""

    def __init__(self, redis_url: str | None = None):
        url = redis_url or settings.REDIS_URL
        self._pool = redis.ConnectionPool.from_url(url, decode_responses=True)
        self._redis: redis.Redis | None = None

    @property
    def _r(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis(connection_pool=self._pool)
        return self._redis

    def publish_sync(
        self,
        stream: str,
        data: dict,
        *,
        source: str = "",
        maxlen: int = DEFAULT_MAXLEN,
    ) -> str | None:
        """同步发布消息到 Stream。

        Args:
            stream: Stream 名称，如 qm:signal:generated。
            data: 业务数据 dict。
            source: 发布源标识，如 signal_service。
            maxlen: Stream 最大长度（近似裁剪）。

        Returns:
            message_id 或 None（失败时）。
        """
        message = {
            "published_at": datetime.now(UTC).isoformat(),
            "source": source,
            "payload": json.dumps(data, cls=_JSONEncoder, ensure_ascii=False),
        }
        try:
            msg_id = self._r.xadd(stream, message, maxlen=maxlen, approximate=True)  # type: ignore[arg-type]
            logger.debug("[StreamBus] published to %s: %s", stream, msg_id)
            return str(msg_id) if msg_id else None
        except Exception:
            logger.warning("[StreamBus] publish to %s failed", stream, exc_info=True)
            return None

    def get_history(
        self,
        stream: str,
        count: int = 100,
        start_id: str = "-",
        end_id: str = "+",
    ) -> list[dict]:
        """获取历史消息（同步，调试用）。"""
        try:
            raw = self._r.xrange(stream, start_id, end_id, count=count)
            results = []
            for msg_id, fields in raw:
                entry = {"id": msg_id, **fields}
                if "payload" in entry:
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        entry["payload"] = json.loads(entry["payload"])
                results.append(entry)
            return results
        except Exception:
            logger.warning("[StreamBus] get_history %s failed", stream, exc_info=True)
            return []

    def stream_info(self, stream: str) -> dict | None:
        """获取 Stream 元信息（长度、消费者组等）。"""
        try:
            info = self._r.xinfo_stream(stream)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
                "groups": info.get("groups", 0),
            }
        except redis.ResponseError:
            return None
        except Exception:
            logger.warning("[StreamBus] stream_info %s failed", stream, exc_info=True)
            return None

    def stream_len(self, stream: str) -> int:
        """获取 Stream 消息数量。"""
        try:
            return self._r.xlen(stream)
        except Exception:
            return 0

    def all_streams_status(self) -> list[dict]:
        """获取所有已注册 Stream 的状态摘要。"""
        result = []
        for name in ALL_STREAMS:
            length = self.stream_len(name)
            info = self.stream_info(name) if length > 0 else None
            last_time = None
            if info and info.get("last_entry"):
                last_entry = info["last_entry"]
                if isinstance(last_entry, (list, tuple)) and len(last_entry) >= 2:
                    fields = last_entry[1] if isinstance(last_entry[1], dict) else {}
                    last_time = fields.get("published_at")
            result.append({
                "stream": name,
                "length": length,
                "last_published_at": last_time,
            })
        return result

    def close(self) -> None:
        """关闭连接池。"""
        if self._redis:
            self._redis.close()
            self._redis = None
        self._pool.disconnect()


# ── 全局单例 ─────────────────────────────────────────────
_bus: StreamBus | None = None


def get_stream_bus() -> StreamBus:
    """获取全局 StreamBus 单例。"""
    global _bus
    if _bus is None:
        _bus = StreamBus()
    return _bus


def close_stream_bus() -> None:
    """关闭全局 StreamBus（服务关闭时调用）。"""
    global _bus
    if _bus is not None:
        _bus.close()
        _bus = None
