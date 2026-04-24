"""MVP 3.2 Strategy Framework — DBStrategyRegistry concrete.

**批 1 (Session 33 Part 1, 2026-04-24)**: 提供 Strategy 注册表的 DB-backed 实现.
与 `strategy_registry` + `strategy_status_log` 2 DB 表配对 (backend/migrations/strategy_registry.sql).

## 架构决策

- **In-memory instance cache + DB metadata**: `_instances: dict[UUID, Strategy]` 启动时注入,
  DB 只存 metadata (name / status / factor_pool / config). `get_live()` 返 DB live UUIDs ∩
  cache 的 instances. 若 DB 有 UUID 但 cache 未 register → fail-loud StrategyNotFound
  (铁律 33 silent fail 禁).

- **铁律 32 事务边界**: 本类所有 DB 方法**不 commit**, 调用方 (daily_pipeline / FastAPI) 管事务.
  上层 Exception 必须 rollback.

- **铁律 39 显式声明**: DBStrategyRegistry 走 sync psycopg2 (对齐 DBFactorRegistry +
  DBFeatureFlag + DBExperimentRegistry 等既有 Platform concrete 模式).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from .interface import Strategy, StrategyRegistry, StrategyStatus

if TYPE_CHECKING:
    import psycopg2.extensions

_logger = logging.getLogger(__name__)


class StrategyNotFound(KeyError):  # noqa: N818 — 语义优先 (对齐 FactorNotFound)
    """策略 ID 在 DB 或 in-memory cache 中找不到."""


class StrategyRegistryIntegrityError(RuntimeError):
    """DB 与 in-memory cache 不一致 (e.g. DB live 但 cache 未 register)."""


class DBStrategyRegistry(StrategyRegistry):
    """DB-backed StrategyRegistry 实现.

    Args:
      conn_factory: 返回 psycopg2 connection 的 callable (DI, 对齐 MVP 1.3b DBFactorRegistry).

    Usage:
      >>> registry = DBStrategyRegistry(conn_factory=get_sync_conn)
      >>> registry.register(S1MonthlyRanking())  # 在 boot 时 (FastAPI lifespan) 注册
      >>> live = registry.get_live()  # daily_pipeline 16:30 signal_phase 遍历
    """

    def __init__(
        self, conn_factory: Callable[[], psycopg2.extensions.connection]
    ) -> None:
        self._conn_factory = conn_factory
        # In-memory instance cache (boot-time populated via register())
        self._instances: dict[UUID, Strategy] = {}

    # ─── CRUD: register ───────────────────────────────────────────────

    def register(self, strategy: Strategy) -> None:
        """注册策略 — instance 入 cache + metadata upsert 到 DB.

        幂等: 同 strategy_id 重复 register 不报错, 更新 metadata (name/factor_pool/config)
        但保留 status (status 变更走 update_status() 带审计).

        Raises:
          ValueError: strategy.strategy_id 非有效 UUID, 或 factor_pool 空
          psycopg2 errors: DB 连接失败 / CHECK 约束违反 (fail-loud, 铁律 33)
        """
        sid = self._parse_uuid(strategy.strategy_id, "strategy_id")
        name = getattr(strategy, "name", None) or strategy.__class__.__name__
        factor_pool = list(strategy.factor_pool)
        if not factor_pool:
            raise ValueError(
                f"Strategy {name} factor_pool is empty — "
                "铁律 13/14 要求策略必依赖显式因子清单"
            )

        # 序列化 Enum -> text
        rebalance_freq = strategy.rebalance_freq.value
        status = getattr(strategy, "status", StrategyStatus.DRAFT)
        status_text = status.value if isinstance(status, StrategyStatus) else str(status)
        config = getattr(strategy, "config", {})
        description = getattr(strategy, "description", "")

        conn = self._conn_factory()
        cur = conn.cursor()

        # 查是否首次 register (决定 strategy_status_log 是否写首行)
        cur.execute(
            "SELECT status FROM strategy_registry WHERE strategy_id = %s",
            (str(sid),),
        )
        existing_row = cur.fetchone()
        existing_status = existing_row[0] if existing_row else None

        # Upsert (幂等, 保 status 不动, 交给 update_status 管状态迁移)
        cur.execute(
            """
            INSERT INTO strategy_registry
                (strategy_id, name, rebalance_freq, status, factor_pool, config, description)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (strategy_id) DO UPDATE SET
                name = EXCLUDED.name,
                rebalance_freq = EXCLUDED.rebalance_freq,
                factor_pool = EXCLUDED.factor_pool,
                config = EXCLUDED.config,
                description = EXCLUDED.description
            """,
            (
                str(sid),
                name,
                rebalance_freq,
                status_text,
                json.dumps(factor_pool),
                json.dumps(config),
                description,
            ),
        )

        # 审计日志: 首次 register 插 log (old_status=NULL)
        if existing_status is None:
            cur.execute(
                """
                INSERT INTO strategy_status_log
                    (strategy_id, old_status, new_status, reason)
                VALUES (%s, NULL, %s, %s)
                """,
                (str(sid), status_text, f"initial register via {self.__class__.__name__}"),
            )

        # In-memory cache (无论首次 or 重注)
        self._instances[sid] = strategy

        _logger.info(
            "strategy registered: id=%s name=%s status=%s rebalance=%s factors=%d",
            sid,
            name,
            status_text,
            rebalance_freq,
            len(factor_pool),
        )

    # ─── Query: get_live / get_by_id ──────────────────────────────────

    def get_live(self) -> list[Strategy]:
        """返回所有 DB status=LIVE 的策略 instance.

        Raises:
          StrategyRegistryIntegrityError: DB live UUID 但 in-memory cache 未 register
            (fail-loud 防 production 静默跳过策略, 铁律 33)
        """
        conn = self._conn_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT strategy_id, name FROM strategy_registry WHERE status = 'live' ORDER BY name"
        )
        rows = cur.fetchall()

        instances: list[Strategy] = []
        for sid_str, name in rows:
            sid = UUID(sid_str) if isinstance(sid_str, str) else sid_str
            instance = self._instances.get(sid)
            if instance is None:
                raise StrategyRegistryIntegrityError(
                    f"DB 有 live strategy {name} (id={sid}) 但 in-memory cache 未 register. "
                    "可能原因: (1) boot 时未调 register() (2) 进程重启后 instance 未重新注入. "
                    "铁律 33 fail-loud: production 跳过 live 策略是安全事故."
                )
            instances.append(instance)
        return instances

    def get_by_id(self, strategy_id: str) -> Strategy:
        """按 ID 取策略 instance. 若 DB 无或 cache 未 register 则 raise."""
        sid = self._parse_uuid(strategy_id, "strategy_id")
        conn = self._conn_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM strategy_registry WHERE strategy_id = %s", (str(sid),)
        )
        if cur.fetchone() is None:
            raise StrategyNotFound(f"strategy_id {sid} 不在 strategy_registry DB 表中")
        instance = self._instances.get(sid)
        if instance is None:
            raise StrategyNotFound(
                f"strategy_id {sid} in DB 但 in-memory cache 未 register (需 boot 时调 register())"
            )
        return instance

    # ─── Mutate: update_status ────────────────────────────────────────

    def update_status(
        self,
        strategy_id: str,
        new_status: StrategyStatus,
        reason: str,
    ) -> None:
        """变更策略状态 + 写 strategy_status_log 审计行.

        Raises:
          StrategyNotFound: strategy_id 不在 DB
          ValueError: reason 空 (审计必附原因)
        """
        if not reason or not reason.strip():
            raise ValueError("update_status 必须附 reason (审计要求)")
        sid = self._parse_uuid(strategy_id, "strategy_id")
        new_status_text = (
            new_status.value
            if isinstance(new_status, StrategyStatus)
            else str(new_status)
        )

        conn = self._conn_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM strategy_registry WHERE strategy_id = %s",
            (str(sid),),
        )
        row = cur.fetchone()
        if row is None:
            raise StrategyNotFound(
                f"update_status 失败: strategy_id {sid} 不在 DB. 先调 register()."
            )
        old_status_text = row[0]
        if old_status_text == new_status_text:
            _logger.info(
                "update_status no-op: id=%s already at status=%s",
                sid,
                new_status_text,
            )
            return

        cur.execute(
            "UPDATE strategy_registry SET status = %s WHERE strategy_id = %s",
            (new_status_text, str(sid)),
        )
        cur.execute(
            """
            INSERT INTO strategy_status_log
                (strategy_id, old_status, new_status, reason)
            VALUES (%s, %s, %s, %s)
            """,
            (str(sid), old_status_text, new_status_text, reason.strip()),
        )
        _logger.info(
            "strategy status changed: id=%s %s → %s reason=%r",
            sid,
            old_status_text,
            new_status_text,
            reason,
        )

    # ─── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_uuid(val: str | UUID, field_name: str) -> UUID:
        if isinstance(val, UUID):
            return val
        try:
            return UUID(val)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"{field_name} 必须是 UUID, 实测 {type(val).__name__}: {val!r}"
            ) from e
