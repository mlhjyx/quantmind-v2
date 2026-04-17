"""MVP 1.3b Framework #2 Factor — DBFactorRegistry concrete 实现.

只实现 `get_direction(name)` (MVP 1.3b 核心): 依赖 DAL read_registry + in-memory
cache (TTL 默认 60min). 其他 abstract 方法 (register / get_active / update_status /
novelty_check) 留 NotImplementedError (MVP 1.3c 实现).

依赖注入保 MVP 1.1 Platform 隔离:
  - `dal`: Platform DataAccessLayer 实例
  - `cache_ttl_minutes`: TTL, 默认 60

关联铁律:
  - 30: 缓存一致性 (TTL + manual invalidate)
  - 33: 禁 silent failure (refresh 异常向上 raise, 调用方决定 fallback)
  - 34: 配置 SSOT (direction 以 DB 为权威)

Usage:
    from backend.data.factor_cache import FactorCache
    from backend.app.services.db import get_sync_conn
    from backend.platform.data.access_layer import PlatformDataAccessLayer
    from backend.platform.factor.registry import DBFactorRegistry

    dal = PlatformDataAccessLayer(conn_factory=get_sync_conn)
    registry = DBFactorRegistry(dal)
    direction = registry.get_direction("turnover_mean_20")  # = -1
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from backend.platform.factor.interface import (
    FactorLifecycleMonitor,
    FactorRegistry,
    FactorSpec,
    FactorStatus,
    TransitionDecision,
)

if TYPE_CHECKING:
    # 跨 Framework: data → TYPE_CHECKING guard (runtime 鸭子类型, 只用 .read_registry()).
    # 保 MVP 1.1 test_frameworks_do_not_cross_import 严格隔离规则.
    from backend.platform.data.interface import DataAccessLayer


class DBFactorRegistry(FactorRegistry):
    """MVP 1.3b concrete 实现 — get_direction + cache.

    Thread-safe (RLock) 保 Celery Beat 多 worker 并发调. Cache 一次 load 全表
    (287 行约 3KB 内存, 可忽略). TTL 过期自动 refresh.

    未实现 (MVP 1.3c):
      - register / update_status (onboarding 强制化)
      - get_active (返 FactorMeta list)
      - novelty_check (G9 Gate)
    """

    def __init__(
        self,
        dal: DataAccessLayer,
        cache_ttl_minutes: int = 60,
    ) -> None:
        self._dal = dal
        self._ttl = timedelta(minutes=cache_ttl_minutes)
        self._cache: dict[str, int] = {}
        self._last_refresh: datetime | None = None
        self._lock = threading.RLock()

    # ---------- get_direction (MVP 1.3b 核心) ----------

    def get_direction(self, name: str) -> int:
        """读 direction. Cache miss 或 TTL 过期 → 一次性 load 全表.

        Args:
          name: 因子名

        Returns:
          direction (+1 / -1). 未注册因子返回默认 +1 (对齐 signal_engine fallback).

        Raises:
          不主动 raise; DB 异常由 _refresh 向上传播, 调用方决定 fallback.
        """
        with self._lock:
            if self._should_refresh():
                self._refresh()
            return self._cache.get(name, 1)  # fallback=1

    def invalidate(self) -> None:
        """手动失效 cache — 用于 MVP 1.3c factor_lifecycle 状态变更时触发."""
        with self._lock:
            self._cache = {}
            self._last_refresh = None

    def cache_size(self) -> int:
        """返 cache 当前条目数 (debug / test 用)."""
        with self._lock:
            return len(self._cache)

    def _should_refresh(self) -> bool:
        if self._last_refresh is None:
            return True
        return (datetime.now(UTC) - self._last_refresh) > self._ttl

    def _refresh(self) -> None:
        """一次性 load 全部 direction 到 cache. 不吃异常, 调用方决定 fallback."""
        df = self._dal.read_registry()
        self._cache = dict(
            zip(df["name"].tolist(), df["direction"].astype(int).tolist(), strict=True)
        )
        self._last_refresh = datetime.now(UTC)

    # ---------- 其他 abstract 方法留 MVP 1.3c ----------

    def register(self, spec: FactorSpec) -> UUID:
        raise NotImplementedError("MVP 1.3c to implement (factor onboarding 强制化)")

    def get_active(self) -> list[Any]:
        raise NotImplementedError("MVP 1.3c to implement (FactorMeta list)")

    def update_status(self, name: str, new_status: FactorStatus, reason: str) -> None:
        raise NotImplementedError("MVP 1.3c to implement (lifecycle 迁移)")

    def novelty_check(self, spec: FactorSpec) -> bool:
        raise NotImplementedError("MVP 1.3c to implement (G9 Gate)")


class StubLifecycleMonitor(FactorLifecycleMonitor):
    """MVP 1.3b 占位 (未实施). MVP 1.3c factor_lifecycle 迁移时实现 evaluate_all."""

    def evaluate_all(self) -> list[TransitionDecision]:
        raise NotImplementedError(
            "MVP 1.3c: 迁 backend/engines/factor_lifecycle.py 到 Platform 时实现"
        )


__all__ = ["DBFactorRegistry", "StubLifecycleMonitor"]
