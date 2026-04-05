"""通知防洪泛 -- 同类通知在N分钟内不重复发送。

Phase 0用内存dict做简单限流，不需要Redis。
限流key = level + title，不同级别有不同最小间隔。
"""

import time

import structlog

logger = structlog.get_logger(__name__)

# 各级别默认最小间隔(秒)
_DEFAULT_INTERVALS: dict[str, int] = {
    "P0": 60,  # P0: 1分钟（紧急，间隔短）
    "P1": 600,  # P1: 10分钟
    "P2": 1800,  # P2: 30分钟
    "P3": 3600,  # P3: 1小时
}


class NotificationThrottler:
    """通知防洪泛控制器。

    基于内存dict，记录每个(level, title)的最后发送时间戳。
    同类通知在最小间隔内不重复发送。

    线程安全说明: Phase 0单进程使用，不加锁。
    如果后续多worker需要改用Redis TTL。
    """

    def __init__(
        self,
        intervals: dict[str, int] | None = None,
        max_entries: int = 10000,
    ) -> None:
        """初始化限流器。

        Args:
            intervals: 各级别最小间隔(秒)，None则用默认值。
            max_entries: 内存记录上限，超过时清理过期条目。
        """
        self._intervals = intervals or _DEFAULT_INTERVALS.copy()
        self._max_entries = max_entries
        # key: (level, title) -> last_sent_timestamp
        self._last_sent: dict[tuple[str, str], float] = {}

    def throttle(self, level: str, title: str) -> bool:
        """判断是否允许发送。

        Args:
            level: 通知级别 P0/P1/P2/P3。
            title: 通知标题(用于去重)。

        Returns:
            True = 允许发送，False = 被限流(跳过)。
        """
        now = time.monotonic()
        key = (level, title)
        interval = self._intervals.get(level, 600)

        last = self._last_sent.get(key)
        if last is not None and (now - last) < interval:
            logger.debug(
                "[Throttle] 限流: level=%s title='%s' 距上次%.0f秒 < 间隔%d秒",
                level,
                title,
                now - last,
                interval,
            )
            return False

        # 允许发送，记录时间
        self._last_sent[key] = now

        # 条目过多时清理过期记录
        if len(self._last_sent) > self._max_entries:
            self._cleanup(now)

        return True

    def _cleanup(self, now: float) -> None:
        """清理过期条目。

        Args:
            now: 当前 monotonic 时间戳。
        """
        max_interval = max(self._intervals.values(), default=3600)
        expired_keys = [k for k, ts in self._last_sent.items() if (now - ts) > max_interval]
        for k in expired_keys:
            del self._last_sent[k]
        logger.debug("[Throttle] 清理过期条目 %d 个", len(expired_keys))

    def reset(self) -> None:
        """重置所有限流记录(测试用)。"""
        self._last_sent.clear()

    def get_interval(self, level: str) -> int:
        """获取指定级别的最小间隔(秒)。

        Args:
            level: 通知级别。

        Returns:
            最小间隔秒数。
        """
        return self._intervals.get(level, 600)


# 全局单例 -- Phase 0进程内共享
default_throttler = NotificationThrottler()
