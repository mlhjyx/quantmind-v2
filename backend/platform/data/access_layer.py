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
    from .access_layer import PlatformDataAccessLayer

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

from .interface import DataAccessLayer

# ---------- 错误类型 ----------


class DALError(RuntimeError):
    """Platform DAL 基类异常."""


class UnsupportedColumn(DALError):  # noqa: N818 — DALError 已含 Error 后缀, 子类走语义名
    """column 不在 factor_values 白名单."""


class UnsupportedField(DALError):  # noqa: N818 — 同上
    """fields 含非 daily_basic / factor_registry 白名单字段."""


class UnsupportedTable(DALError):  # noqa: N818 — 同上
    """table 不在 freshness / reconcile 白名单 (MVP 2.1c)."""


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
# MVP 2.1c: read_freshness / read_reconcile_counts 允许查询的表白名单
# 仅 Platform 负责的时间序列事实表, 排除 config / registry / metadata
_FRESHNESS_TABLES = frozenset(
    {
        "klines_daily",
        "daily_basic",
        "moneyflow_daily",
        "factor_values",
        "index_daily",
        "minute_bars",
        "stock_status_daily",
    }
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


def _coerce_date(v: Any) -> date | None:
    """强制转换成 date. 兼容 psycopg2 (已返 date) / sqlite (返 str) / datetime.

    返 None 若 v 是 None. 其他异常 bubble up (静默转换 = 铁律 33 silent failure).
    """
    if v is None:
        return None
    if isinstance(v, date) and not hasattr(v, "hour"):
        # pure date (non-datetime)
        return v
    if hasattr(v, "date") and callable(v.date):
        # datetime-like
        return v.date()
    if isinstance(v, str):
        return date.fromisoformat(v)
    raise TypeError(f"cannot coerce {type(v).__name__} to date: {v!r}")


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
        """读 factor_registry 表 (MVP 1.3a 对齐 live PG 18 字段 schema).

        返 DataFrame 列对齐 DB: id, name, category, direction, expression,
        code_content, hypothesis, source, lookback_days, status, pool, gate_ic,
        gate_ir, gate_mono, gate_t, ic_decay_ratio, created_at, updated_at.
        """
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
            f"SELECT id, name, category, direction, expression, code_content, "
            f"       hypothesis, source, lookback_days, status, pool, "
            f"       gate_ic, gate_ir, gate_mono, gate_t, ic_decay_ratio, "
            f"       created_at, updated_at "
            f"FROM factor_registry {where_sql} "
            f"ORDER BY name"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            columns = [
                "id", "name", "category", "direction", "expression", "code_content",
                "hypothesis", "source", "lookback_days", "status", "pool",
                "gate_ic", "gate_ir", "gate_mono", "gate_t", "ic_decay_ratio",
                "created_at", "updated_at",
            ]
            if not rows:
                return pd.DataFrame(columns=columns)
            return pd.DataFrame(rows, columns=columns)
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # MVP 2.1c 扩展: 7 新方法 (SQL 迁移消费方统一入口)
    # ════════════════════════════════════════════════════════════════

    # ---------- read_calendar ----------

    def read_calendar(
        self,
        start: date | None = None,
        end: date | None = None,
    ) -> list[date]:
        """读交易日历 (distinct trade_date from klines_daily).

        消费方 (MVP 2.1c A/B 级迁移): compute_factor_ic / fetch_base_data /
        services.factor_repository / engines.signal_engine.
        """
        where_clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            where_clauses.append(f"trade_date >= {self._ph}")
            params.append(start)
        if end is not None:
            where_clauses.append(f"trade_date <= {self._ph}")
            params.append(end)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = (
            f"SELECT DISTINCT trade_date FROM klines_daily {where_sql} "
            f"ORDER BY trade_date"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            out: list[date] = []
            for r in rows:
                coerced = _coerce_date(r[0])
                if coerced is not None:
                    out.append(coerced)
            return out
        finally:
            conn.close()

    # ---------- read_universe ----------

    def read_universe(self, as_of: date) -> list[str]:
        """读 as_of 日有效 A 股 universe (未退市 + 已上市).

        排除: list_status='D' (已退市) + list_date > as_of (未上市).
        不排除 BJ / ST / 停牌 (调用方按策略自行过滤).

        消费方: services.data_orchestrator / engines.ml_engine.
        """
        sql = (
            f"SELECT code FROM symbols "
            f"WHERE market = 'astock' "
            f"  AND list_status != 'D' "
            f"  AND (list_date IS NULL OR list_date <= {self._ph}) "
            f"  AND (delist_date IS NULL OR delist_date > {self._ph}) "
            f"ORDER BY code"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, (as_of, as_of))
                rows = cur.fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    # ---------- read_stock_status ----------

    def read_stock_status(
        self,
        codes: list[str],
        as_of: date,
    ) -> pd.DataFrame:
        """读 as_of 日的股票状态快照 (ST/停牌/新股).

        消费方: services.pt_data_service / engines.factor_analyzer.
        """
        columns = [
            "code", "is_st", "is_suspended", "is_new_stock",
            "board", "list_date", "delist_date",
        ]
        if not codes:
            return pd.DataFrame(columns=columns)
        code_list = _as_list(codes)
        placeholders = ", ".join([self._ph] * len(code_list))
        sql = (
            f"SELECT code, is_st, is_suspended, is_new_stock, "
            f"       board, list_date, delist_date "
            f"FROM stock_status_daily "
            f"WHERE code IN ({placeholders}) AND trade_date = {self._ph} "
            f"ORDER BY code"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, (*code_list, as_of))
                rows = cur.fetchall()
            if not rows:
                return pd.DataFrame(columns=columns)
            return pd.DataFrame(rows, columns=columns)
        finally:
            conn.close()

    # ---------- read_factor_names ----------

    def read_factor_names(self, source: str = "registry") -> list[str]:
        """读 factor_name 去重列表 (默认从 factor_registry 快路径).

        Args:
          source: "registry" (默认, 走 factor_registry, 快 <1ms, 287 行全注册表) /
                  "values" (走 factor_values DISTINCT, 慢 ~100s on 816M rows,
                  返实际有数据的因子名).

        消费方: compute_factor_ic / engines.ml_engine / engines.factor_analyzer /
        engines.factor_profiler. 生产 ML 训练 / IC 全量计算默认走 registry 快路径,
        仅需要"确有数据"的场景 (如 factor_profiler 画像) 显式传 source='values'.

        Raises:
          ValueError: source 非 "registry" / "values".
        """
        if source == "registry":
            sql = "SELECT DISTINCT name FROM factor_registry ORDER BY name"
        elif source == "values":
            sql = (
                "SELECT DISTINCT factor_name FROM factor_values "
                "ORDER BY factor_name"
            )
        else:
            raise ValueError(
                f"source must be 'registry' or 'values', got {source!r}"
            )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    # ---------- read_freshness ----------

    def read_freshness(self, tables: list[str]) -> dict[str, date | None]:
        """读多个表的 MAX(trade_date) 作为新鲜度探针.

        消费方: services.data_orchestrator L3 data freshness check.

        Raises:
          UnsupportedTable: tables 含非白名单表.
        """
        if not tables:
            return {}
        bad = [t for t in tables if t not in _FRESHNESS_TABLES]
        if bad:
            raise UnsupportedTable(
                f"tables 含非白名单 {bad}, 允许: {sorted(_FRESHNESS_TABLES)}"
            )
        out: dict[str, date | None] = {}
        conn = self._conn_factory()
        try:
            for t in tables:
                # 表名走白名单非参数, 不注入风险 (已 frozenset 验证)
                sql = f"SELECT MAX(trade_date) FROM {t}"  # noqa: S608
                with _conn_cursor(conn) as cur:
                    cur.execute(sql)
                    row = cur.fetchone()
                raw = row[0] if row else None
                out[t] = _coerce_date(raw)
            return out
        finally:
            conn.close()

    # ---------- read_reconcile_counts ----------

    def read_reconcile_counts(
        self,
        tables: list[str],
        as_of: date,
    ) -> dict[str, int]:
        """读多个表在 as_of 日的 COUNT(*) 用于跨表对齐检查.

        消费方: services.data_orchestrator L3 reconcile check.

        Raises:
          UnsupportedTable: tables 含非白名单表.
        """
        if not tables:
            return {}
        bad = [t for t in tables if t not in _FRESHNESS_TABLES]
        if bad:
            raise UnsupportedTable(
                f"tables 含非白名单 {bad}, 允许: {sorted(_FRESHNESS_TABLES)}"
            )
        out: dict[str, int] = {}
        conn = self._conn_factory()
        try:
            for t in tables:
                sql = f"SELECT COUNT(*) FROM {t} WHERE trade_date = {self._ph}"  # noqa: S608
                with _conn_cursor(conn) as cur:
                    cur.execute(sql, (as_of,))
                    row = cur.fetchone()
                out[t] = int(row[0]) if row and row[0] is not None else 0
            return out
        finally:
            conn.close()

    # ---------- read_pead_announcements ----------

    def read_pead_announcements(
        self,
        trade_date: date,
        lookback_days: int = 7,
    ) -> pd.DataFrame:
        """读 trade_date 附近 lookback_days 天窗口的 Q1 财报公告 (PEAD 因子用).

        消费方 (MVP 2.1c B 级迁移): services.factor_repository.load_pead_announcements
        (原函数将改为 thin wrapper 调本方法).

        Args:
          trade_date: 基准日
          lookback_days: 回看窗口 (默认 7 天, 公告后信号衰减)

        Returns:
          DataFrame with columns ['ts_code', 'eps_surprise_pct', 'ann_td'],
          按 (ts_code, trade_date DESC) 排序. 无数据返回空 DataFrame (列名保留).

        Filters:
          - report_type='Q1'
          - trade_date <= <trade_date> AND trade_date >= <trade_date> - lookback_days
          - eps_surprise_pct IS NOT NULL AND ABS(eps_surprise_pct) < 10
        """
        columns = ["ts_code", "eps_surprise_pct", "ann_td"]
        # 日期窗口在 Python 层计算, 避免 PG-specific INTERVAL (sqlite 兼容)
        from datetime import timedelta as _td
        since = trade_date - _td(days=lookback_days)
        # 对齐 services/factor_repository.load_pead_announcements 原 SQL:
        # 输出列名 ann_td 是 trade_date 的 alias (非 DB 原生字段 ann_date)
        sql = (
            f"SELECT ea.ts_code, ea.eps_surprise_pct, "
            f"       ea.trade_date AS ann_td "
            f"FROM earnings_announcements ea "
            f"WHERE ea.report_type = 'Q1' "
            f"  AND ea.trade_date BETWEEN {self._ph} AND {self._ph} "
            f"  AND ea.eps_surprise_pct IS NOT NULL "
            f"  AND ABS(ea.eps_surprise_pct) < 10 "
            f"ORDER BY ea.ts_code, ea.trade_date DESC"
        )
        conn = self._conn_factory()
        try:
            with _conn_cursor(conn) as cur:
                cur.execute(sql, (since, trade_date))
                rows = cur.fetchall()
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
    "UnsupportedTable",
]
