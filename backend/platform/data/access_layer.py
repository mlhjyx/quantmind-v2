"""Framework #1 Data — MVP 1.2a DAL Minimal concrete 实现.

Platform 唯一 read 入口. 所有 Application / Engine / MVP 1.3+ Factor Framework
必须通过本类读 `factor_values` / `klines_daily` / `daily_basic` / `factor_registry`.
禁止裸 SQL (铁律 17 的 read 对偶).

依赖注入原则 (保 MVP 1.1 Platform 严格隔离老代码):
  - `conn_factory`: 由调用方提供 (典型 `backend.app.services.db.get_sync_conn`)
  - `factor_cache`: 由调用方提供 (典型 `backend.data.factor_cache.FactorCache()`)
  - Platform 内部绝不 import `backend.app.*` / `backend.data.*` / `backend.engines.*`

Usage (生产):
    from backend.data.factor_cache import FactorCache
    from backend.app.services.db import get_sync_conn
    from backend.platform.data.access_layer import PlatformDataAccessLayer

    dal = PlatformDataAccessLayer(
        conn_factory=get_sync_conn,
        factor_cache=FactorCache(),
    )
    df = dal.read_factor("turnover_mean_20", date(2021,1,1), date(2025,12,31))

关联铁律:
  - 17: DataPipeline 入库 (本模块是 Read 对偶)
  - 30: 缓存一致性 (委托给 FactorCache)
  - 31: Engine 纯计算 (DAL 承担 IO)

范围 (MVP 1.2a minimal, Blueprint Part 4):
  - read_factor / read_ohlc / read_fundamentals / read_registry
  - 不含 DataSource / DataContract (留 MVP 2.1)
  - 不含 Write 路径 (Write 继续走 DataPipeline)
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import date
from typing import Any, Protocol

import pandas as pd

from backend.platform.data.interface import DataAccessLayer

# ---------- 错误类型 ----------


class DALError(RuntimeError):
    """Platform DAL 基类异常."""


class UnsupportedColumn(DALError):  # noqa: N818 — DALError 已含 Error 后缀, 子类走语义名
    """column 不在 factor_values 白名单."""


class UnsupportedField(DALError):  # noqa: N818 — 同上
    """fields 含非 daily_basic / factor_registry 白名单字段."""


# ---------- DB / Cache 鸭子类型 (不强制 Protocol, 减耦合) ----------


class _DBConnection(Protocol):
    """psycopg2 / sqlite3 connection 鸭子类型."""

    def cursor(self) -> Any: ...
    def close(self) -> None: ...


# ---------- 白名单 ----------

_FACTOR_VALUE_COLUMNS = frozenset({"raw_value", "neutral_value", "zscore"})
_DAILY_BASIC_FIELDS = frozenset(
    {"pe_ttm", "pb", "ps_ttm", "dv_ttm", "total_mv", "circ_mv", "turnover_rate"}
)


# ---------- helper ----------


@contextmanager
def _conn_cursor(conn: _DBConnection) -> Any:
    """兼容 psycopg2 / sqlite3 的 cursor context manager."""
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def _as_list(values: tuple | list) -> list:
    return list(values) if not isinstance(values, list) else values


# ---------- PlatformDataAccessLayer ----------


class PlatformDataAccessLayer(DataAccessLayer):
    """Platform 唯一数据读入口 (MVP 1.2a minimal concrete).

    Args:
      conn_factory: 每次调用返回新 DB 连接的 callable.
      factor_cache: 可选 FactorCache-like 实例, 鸭子类型:
        必须有 `.load(factor_name, column, start, end, conn, auto_refresh) -> DataFrame`.
        None 时所有 read_factor 走 fallback SQL.
      paramstyle: "%s" (psycopg2 生产) 或 "?" (sqlite 测试).
    """

    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection],
        *,
        factor_cache: Any | None = None,
        paramstyle: str = "%s",
    ) -> None:
        self._conn_factory = conn_factory
        self._cache = factor_cache
        self._ph = paramstyle

    # ---------- read_factor ----------

    def read_factor(
        self,
        factor: str,
        start: date,
        end: date,
        column: str = "neutral_value",
    ) -> pd.DataFrame:
        """读单因子时间序列 (优先 cache → fallback SQL)."""
        if column not in _FACTOR_VALUE_COLUMNS:
            raise UnsupportedColumn(
                f"column {column!r} 不在白名单 {sorted(_FACTOR_VALUE_COLUMNS)}"
            )

        if self._cache is not None:
            conn = self._conn_factory()
            try:
                return self._cache.load(
                    factor,
                    column=column,
                    start=start,
                    end=end,
                    conn=conn,
                    auto_refresh=True,
                )
            finally:
                conn.close()

        # fallback SQL (无 cache, 测试或 minimal 场景)
        sql = (
            f"SELECT code, trade_date, {column} AS value "
            f"FROM factor_values "
            f"WHERE factor_name = {self._ph} "
            f"  AND trade_date BETWEEN {self._ph} AND {self._ph} "
            f"  AND {column} IS NOT NULL "
            f"ORDER BY code, trade_date"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, (factor, start, end))
                rows = cur.fetchall()
            if not rows:
                return pd.DataFrame(columns=["code", "trade_date", "value"])
            df = pd.DataFrame(rows, columns=["code", "trade_date", "value"])
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["value"] = df["value"].astype("float64")
            return df
        finally:
            conn.close()

    # ---------- read_ohlc ----------

    def read_ohlc(
        self,
        codes: list[str],
        start: date,
        end: date,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        """读价量 OHLCV (MVP 1.2a minimal: 不做 lookback, 不做复权).

        `adjusted` 参数预留给 MVP 2.1 扩展, 本 MVP 总是返回 raw + adj_factor.
        """
        del adjusted  # MVP 2.1 实现, 本 MVP 签名稳定
        if not codes:
            return pd.DataFrame(
                columns=[
                    "code", "trade_date", "open", "high", "low", "close",
                    "volume", "amount", "adj_factor",
                ]
            )
        code_list = _as_list(codes)
        placeholders = ", ".join([self._ph] * len(code_list))
        sql = (
            f"SELECT code, trade_date, open, high, low, close, "
            f"       volume, amount, adj_factor "
            f"FROM klines_daily "
            f"WHERE code IN ({placeholders}) "
            f"  AND trade_date BETWEEN {self._ph} AND {self._ph} "
            f"  AND volume > 0 "
            f"ORDER BY code, trade_date"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, (*code_list, start, end))
                rows = cur.fetchall()
            columns = [
                "code", "trade_date", "open", "high", "low", "close",
                "volume", "amount", "adj_factor",
            ]
            if not rows:
                return pd.DataFrame(columns=columns)
            df = pd.DataFrame(rows, columns=columns)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            for col in ("open", "high", "low", "close", "adj_factor"):
                df[col] = df[col].astype("float64")
            for col in ("volume", "amount"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        finally:
            conn.close()

    # ---------- read_fundamentals ----------

    def read_fundamentals(
        self,
        codes: list[str],
        fields: list[str],
        as_of: date,
    ) -> pd.DataFrame:
        """读 daily_basic PIT 快照 (每 code 最新 trade_date <= as_of).

        MVP 1.2a minimal: 仅读 daily_basic (日频快照, 非财报). MVP 2.1 扩展真 PIT.
        """
        if not fields:
            raise UnsupportedField("fields 不能为空")
        bad = [f for f in fields if f not in _DAILY_BASIC_FIELDS]
        if bad:
            raise UnsupportedField(
                f"fields 含非白名单字段 {bad}, 允许: {sorted(_DAILY_BASIC_FIELDS)}"
            )
        if not codes:
            return pd.DataFrame(columns=["code", "trade_date", *fields])
        code_list = _as_list(codes)
        placeholders = ", ".join([self._ph] * len(code_list))
        fields_sql = ", ".join(fields)

        # sqlite 不支持 DISTINCT ON, 用 group-by 子查询兼容两路径
        sql = (
            f"SELECT db.code, db.trade_date, {fields_sql} "
            f"FROM daily_basic db "
            f"JOIN (SELECT code, MAX(trade_date) AS max_td "
            f"      FROM daily_basic "
            f"      WHERE code IN ({placeholders}) AND trade_date <= {self._ph} "
            f"      GROUP BY code) latest "
            f"  ON db.code = latest.code AND db.trade_date = latest.max_td "
            f"WHERE db.code IN ({placeholders}) "
            f"ORDER BY db.code"
        )
        params = (*code_list, as_of, *code_list)
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            columns = ["code", "trade_date", *fields]
            if not rows:
                return pd.DataFrame(columns=columns)
            df = pd.DataFrame(rows, columns=columns)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            for f in fields:
                df[f] = pd.to_numeric(df[f], errors="coerce")
            return df
        finally:
            conn.close()

    # ---------- read_registry ----------

    def read_registry(
        self,
        status_filter: str | None = None,
        pool_filter: str | None = None,
    ) -> pd.DataFrame:
        """读 factor_registry 表 (供 MVP 1.3 FactorRegistry 使用)."""
        where_clauses: list[str] = []
        params: list[Any] = []
        if status_filter is not None:
            where_clauses.append(f"status = {self._ph}")
            params.append(status_filter)
        if pool_filter is not None:
            where_clauses.append(f"pool = {self._ph}")
            params.append(pool_filter)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = (
            f"SELECT name, direction, pool, status, category, hypothesis, "
            f"       ic_mean, ic_decay_ratio, registered_at, updated_at "
            f"FROM factor_registry {where_sql} "
            f"ORDER BY name"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            columns = [
                "name", "direction", "pool", "status", "category", "hypothesis",
                "ic_mean", "ic_decay_ratio", "registered_at", "updated_at",
            ]
            if not rows:
                return pd.DataFrame(columns=columns)
            return pd.DataFrame(rows, columns=columns)
        finally:
            conn.close()


__all__ = [
    "PlatformDataAccessLayer",
    "DALError",
    "UnsupportedColumn",
    "UnsupportedField",
]
