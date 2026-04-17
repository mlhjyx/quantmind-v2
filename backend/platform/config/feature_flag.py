"""Framework #8 Config Management — FeatureFlag concrete 实现 (DB-backed).

MVP 1.2 minimum viable:
  - `is_enabled(name)`: binary on/off, 命中查询 removal_date, 过期 raise FlagExpired
  - `register(name, default, removal_date, description)`: UPSERT
  - 不含 percentage rollout / user bucketing (单人系统不需要)

依赖注入: 构造时传入 `conn_factory: Callable[[], Connection]`, 调用方 (App 层) 决定
具体 DSN / pool. 本模块不 import `backend.app.services.db` — 保 MVP 1.1 Platform 隔离.

关联铁律:
  - 32: Service 不 commit — 本模块 register() 会 commit 自身事务 (作为 Platform 原子
    操作), 但调用方可通过传入自带 conn + 手动 commit 实现跨 Service 事务.
  - 33: 禁 silent failure — FlagNotFound / FlagExpired 全部 raise.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import date
from typing import Any, Protocol

from backend.platform.config.interface import FeatureFlag


class _DBConnection(Protocol):
    """鸭子类型 — 实际传入 psycopg2 connection 或 sqlite3 connection (测试用)."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class FlagNotFound(KeyError):  # noqa: N818 — KeyError 子类按 stdlib 惯例不加 Error 后缀
    """flag_name 未在 feature_flags 表中注册."""


class FlagExpired(RuntimeError):  # noqa: N818 — 消费方靠语义名匹配, 保 MVP 1.2 plan API
    """flag 已超过 removal_date, 必须清理 (不得永久化)."""


@contextmanager
def _conn_cursor(conn: _DBConnection):
    """兼容 psycopg2 / sqlite3 的 cursor context manager."""
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


class DBFeatureFlag(FeatureFlag):
    """DB-backed FeatureFlag.

    Args:
      conn_factory: 返回 `_DBConnection` 的 callable, 每次调用产生新连接
        (或从池借). 典型值: `backend.app.services.db.get_sync_conn`.
      paramstyle: "%s" (psycopg2) 或 "?" (sqlite3). 测试用 sqlite 内存数据库需传 "?".

    Usage (生产):
        from backend.app.services.db import get_sync_conn
        from backend.platform.config.feature_flag import DBFeatureFlag
        flag = DBFeatureFlag(get_sync_conn)
        if flag.is_enabled("new_pt_logic"):
            ...
    """

    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection],
        *,
        paramstyle: str = "%s",
    ) -> None:
        self._conn_factory = conn_factory
        self._ph = paramstyle  # placeholder

    def is_enabled(self, flag_name: str, context: dict[str, Any] | None = None) -> bool:
        """查询 flag 是否开启.

        Args:
          flag_name: flag 名.
          context: MVP 1.2 忽略 (预留给 Wave 3+ bucketing 扩展).

        Returns:
          True 若 enabled=True 且未过 removal_date.

        Raises:
          FlagNotFound: flag_name 未注册.
          FlagExpired: 已超 removal_date (强制清理提示).
        """
        del context  # binary on/off MVP, 暂不使用
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(
                    f"SELECT enabled, removal_date FROM feature_flags WHERE name = {self._ph}",
                    (flag_name,),
                )
                row = cur.fetchone()
            if row is None:
                raise FlagNotFound(f"feature flag not registered: {flag_name!r}")
            enabled, removal_date = row
            # sqlite 返回 str, psycopg2 返回 date — 兼容
            if isinstance(removal_date, str):
                removal_date = date.fromisoformat(removal_date)
            if removal_date < date.today():
                raise FlagExpired(
                    f"flag {flag_name!r} removal_date {removal_date} 已过期, 必须从代码和 DB 清理"
                )
            return bool(enabled)
        finally:
            conn.close()

    def register(
        self,
        name: str,
        default: bool,
        removal_date: str | date,
        description: str,
    ) -> None:
        """注册或更新 flag (UPSERT).

        Args:
          name: flag 名 (PK).
          default: 初始 enabled 值.
          removal_date: "YYYY-MM-DD" 或 date.
          description: 作用说明 (给后人看).

        Raises:
          ValueError: removal_date 格式非法或已过期.
        """
        if isinstance(removal_date, str):
            removal_date_d = date.fromisoformat(removal_date)
        else:
            removal_date_d = removal_date
        if removal_date_d < date.today():
            raise ValueError(
                f"removal_date {removal_date_d} 不得早于今天 — 新 flag 必须有未来退休日"
            )

        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                # UPSERT: INSERT ... ON CONFLICT DO UPDATE (psycopg2) /
                #         INSERT OR REPLACE (sqlite 简化变体, 但丢 created_at)
                # 用 ON CONFLICT 语法 (PG 9.5+ / sqlite 3.24+ 都支持)
                cur.execute(
                    f"""
                    INSERT INTO feature_flags (name, enabled, removal_date, description)
                    VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph})
                    ON CONFLICT(name) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        removal_date = EXCLUDED.removal_date,
                        description = EXCLUDED.description
                    """,
                    (name, default, removal_date_d, description),
                )
            conn.commit()
        finally:
            conn.close()

    def list_all(self) -> list[dict[str, Any]]:
        """列所有 flag (debug / 清理用)."""
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(
                    "SELECT name, enabled, removal_date, description FROM feature_flags ORDER BY name"
                )
                rows = cur.fetchall()
            result = []
            for row in rows:
                name, enabled, removal_date, desc = row
                if isinstance(removal_date, str):
                    removal_date = date.fromisoformat(removal_date)
                result.append(
                    {
                        "name": name,
                        "enabled": bool(enabled),
                        "removal_date": removal_date,
                        "description": desc,
                    }
                )
            return result
        finally:
            conn.close()


__all__ = ["DBFeatureFlag", "FlagNotFound", "FlagExpired"]
