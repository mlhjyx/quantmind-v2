"""MVP 2.1a Framework #1 Data — Cache Coherency 协议显式化 (铁律 30).

铁律 30 要求: 源数据 (DB factor_values / klines_daily / 其他) 变更后, 下游所有缓存
(Parquet / Redis / 内存) 必须在下一交易日内生效.

现有 `backend/data/factor_cache.py::_get_cache_max_date` (L180-230) 是隐式实现,
本模块把它升级为**显式契约** (spec), MVP 2.1c 再让 factor_cache 实现此 spec.

关联铁律:
  - 30: 缓存一致性
  - 17: DataPipeline 入库 (本协议的反向对偶 — 写触发 cache invalidate)
  - 31: Engine 纯计算 (cache_coherency 本身无 IO, 纯判定逻辑)
  - 33: 禁 silent failure (is_stale 返 bool + CacheCoherencyError 显式 raise)

使用示例:
    from .cache_coherency import (
        CacheCoherencyPolicy, MaxDateChecker, TTLGuard,
    )

    policy = CacheCoherencyPolicy(
        db_max_date_check=True,
        ttl_seconds=86400,  # 24h
    )
    if MaxDateChecker().is_stale(db_max, cache_max, policy):
        # invalidate + refill
        ...
    elif TTLGuard().is_expired(cache_written_at, policy):
        # 保守策略: DB 查询失败时也失效
        ...
    else:
        # 缓存可用
        ...

MVP 2.1c 集成路径:
  - `backend/data/factor_cache.py::load` 调用 MaxDateChecker/TTLGuard 替代 inline 判定
  - `FactorCache` 实现 Platform `FactorCacheProtocol` (MVP 1.1 ABC)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

# ---------- 错误类型 ----------


class CacheCoherencyError(RuntimeError):
    """Cache coherency 违反 — 缓存与源不一致且调用方要求 fail-loud."""


# ---------- Policy ----------


@dataclass(frozen=True)
class CacheCoherencyPolicy:
    """Cache coherency 显式契约. 组合多种 check 策略.

    Args:
      db_max_date_check: 每次 read 前对比 DB max_date vs cache max_date.
        True (默认): 源数据更新后 1 交易日内失效 (铁律 30 主路径).
        False: 跳过 DB 对比 (离线回测 / 不可访问 DB 时).
      ttl_seconds: TTL 兜底 (默认 86400 = 24h).
        DB 查询失败时的保守策略: 超 TTL 视为 stale.
        0 表示禁用 TTL (不推荐, 会让 DB 失败时永远返 fresh).
      content_hash_check: 优化 — 同 max_date 下用内容 hash 检测漂移 (Wave 2+).
        MVP 2.1a 不实现, 仅预留字段.
      invalidate_on_write: 订阅 DataPipeline write 事件自动失效 (Wave 3 Event Sourcing).
        MVP 2.1a 不实现, 仅预留字段.
    """

    db_max_date_check: bool = True
    ttl_seconds: int = 86400
    content_hash_check: bool = False
    invalidate_on_write: bool = False

    def __post_init__(self) -> None:
        if self.ttl_seconds < 0:
            raise ValueError(f"ttl_seconds 不得为负, 现: {self.ttl_seconds}")


# ---------- MaxDateChecker ----------


class MaxDateChecker:
    """对比 DB max_date vs cache max_date, 决定 cache 是否 stale.

    逻辑:
      - policy.db_max_date_check=False → 永远 fresh (False)
      - cache_max is None → stale (True, cache 从未写过)
      - db_max > cache_max → stale (True, DB 有新数据 cache 没)
      - db_max <= cache_max → fresh (False)

    调用方责任:
      - 提供 DB max_date (通过 `SELECT MAX(trade_date) FROM factor_values WHERE factor_name=%s`)
      - cache_max 从 cache 实现方获取 (如 parquet 文件索引 / redis key)
    """

    def is_stale(
        self,
        db_max: date | None,
        cache_max: date | None,
        policy: CacheCoherencyPolicy,
    ) -> bool:
        """判断 cache 是否 stale.

        Args:
          db_max: DB 中该数据的最新日期, None 表示 DB 无数据 (初始化场景).
          cache_max: cache 中该数据的最新日期, None 表示 cache 空.
          policy: coherency policy.

        Returns:
          True if stale (需 invalidate + refill), False if fresh.
        """
        if not policy.db_max_date_check:
            # 禁用 DB 对比 — 只靠 TTL/其他兜底
            return False
        if db_max is None:
            # DB 无数据, cache 也不该有 — 但若 cache 有则是 stale (安全策略)
            return cache_max is not None
        if cache_max is None:
            return True
        return db_max > cache_max


# ---------- TTLGuard ----------


class TTLGuard:
    """TTL 兜底 — cache 超 ttl_seconds 视为 stale.

    DB 查询失败 (MaxDateChecker 不可用) 时的保守 fallback:
    即便无法验证 DB max_date, TTL 过期也视为 stale 触发 refill.

    用法:
        guard = TTLGuard()
        if guard.is_expired(cache.written_at, policy):
            # 触发 refill
            ...
    """

    def is_expired(
        self,
        cache_written_at: datetime,
        policy: CacheCoherencyPolicy,
        now: datetime | None = None,
    ) -> bool:
        """判断 cache 是否超过 TTL.

        Args:
          cache_written_at: cache 写入时间 (timezone-aware datetime, 铁律 41).
          policy: coherency policy.
          now: 当前时间 (None 时用 datetime.now(UTC), 测试用 freeze_time).

        Returns:
          True if expired (超 TTL), False if still within TTL.

        Raises:
          ValueError: cache_written_at is naive datetime (铁律 41 要求 tz-aware).
        """
        if policy.ttl_seconds == 0:
            # TTL 禁用
            return False
        if cache_written_at.tzinfo is None:
            raise ValueError(
                "cache_written_at 必须 timezone-aware (铁律 41), "
                "传 naive datetime 会导致 UTC/本地时区混用"
            )
        now = now or datetime.now(UTC)
        elapsed = (now - cache_written_at).total_seconds()
        return elapsed > policy.ttl_seconds


# ---------- 组合 check helper ----------


def check_stale(
    *,
    db_max: date | None,
    cache_max: date | None,
    cache_written_at: datetime | None,
    policy: CacheCoherencyPolicy,
    now: datetime | None = None,
) -> str | None:
    """组合 MaxDateChecker + TTLGuard, 返 stale 原因 str 或 None (fresh).

    Args:
      db_max: DB max_date.
      cache_max: cache max_date.
      cache_written_at: cache 写入时间 (None 等同 cache 空).
      policy: policy.
      now: for testing.

    Returns:
      "db_max_ahead" / "cache_empty" / "ttl_expired" / None (fresh).

    用法:
        reason = check_stale(db_max=x, cache_max=y, cache_written_at=z, policy=p)
        if reason:
            logger.info(f"cache stale: {reason}, invalidating")
            cache.invalidate(factor_name)
    """
    max_checker = MaxDateChecker()
    ttl_guard = TTLGuard()

    if cache_max is None and cache_written_at is None:
        return "cache_empty"

    if max_checker.is_stale(db_max, cache_max, policy):
        return "db_max_ahead"

    if cache_written_at is not None and ttl_guard.is_expired(cache_written_at, policy, now):
        return "ttl_expired"

    return None


__all__ = [
    "CacheCoherencyPolicy",
    "CacheCoherencyError",
    "MaxDateChecker",
    "TTLGuard",
    "check_stale",
]
