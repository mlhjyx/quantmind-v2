"""MVP 1.2a test — PlatformDataAccessLayer (read_factor/ohlc/fundamentals/registry).

两组测试:
  - MagicMock 组: 验证依赖注入 + 调用路径 (conn_factory, factor_cache)
  - sqlite in-memory 组: 验证 SQL 语义正确性 (兼容 PG 的最小子集)

不触 live PG / live FactorCache, 测试全独立.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.qm_platform.data.access_layer import (
    PlatformDataAccessLayer,
    UnsupportedColumn,
    UnsupportedField,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_conn_factory() -> MagicMock:
    """返回一个每次调用产生新 MagicMock conn 的 factory."""
    factory = MagicMock()
    factory.return_value = MagicMock()
    return factory


@pytest.fixture
def sqlite_factory():
    """sqlite in-memory, 预建 factor_values / klines_daily / daily_basic / factor_registry."""
    db = sqlite3.connect(":memory:")
    cur = db.cursor()
    cur.executescript(
        """
        CREATE TABLE factor_values (
            code TEXT,
            trade_date TEXT,
            factor_name TEXT,
            raw_value REAL,
            neutral_value REAL,
            zscore REAL,
            PRIMARY KEY (code, trade_date, factor_name)
        );
        CREATE TABLE klines_daily (
            code TEXT,
            trade_date TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, amount REAL,
            adj_factor REAL,
            PRIMARY KEY (code, trade_date)
        );
        CREATE TABLE daily_basic (
            code TEXT,
            trade_date TEXT,
            pe_ttm REAL, pb REAL, ps_ttm REAL,
            dv_ttm REAL, total_mv REAL, circ_mv REAL, turnover_rate REAL,
            PRIMARY KEY (code, trade_date)
        );
        CREATE TABLE factor_registry (
            id TEXT,
            name TEXT PRIMARY KEY,
            category TEXT,
            direction INTEGER,
            expression TEXT,
            code_content TEXT,
            hypothesis TEXT,
            source TEXT,
            lookback_days INTEGER,
            status TEXT,
            pool TEXT,
            gate_ic REAL,
            gate_ir REAL,
            gate_mono REAL,
            gate_t REAL,
            ic_decay_ratio REAL,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    # 种子数据
    cur.executemany(
        "INSERT INTO factor_values(code, trade_date, factor_name, raw_value, neutral_value, zscore) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("600519.SH", "2024-01-02", "turnover_mean_20", 1.5, 0.8, 0.3),
            ("600519.SH", "2024-01-03", "turnover_mean_20", 1.6, 0.9, 0.4),
            ("000001.SZ", "2024-01-02", "turnover_mean_20", 2.0, 1.2, 0.5),
            # NaN neutral → 不应出现
            ("000002.SZ", "2024-01-02", "turnover_mean_20", 1.0, None, 0.1),
            # 其他因子不干扰
            ("600519.SH", "2024-01-02", "volatility_20", 0.02, 0.01, None),
        ],
    )
    cur.executemany(
        "INSERT INTO klines_daily(code, trade_date, open, high, low, close, "
        "volume, amount, adj_factor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("600519.SH", "2024-01-02", 1700.0, 1720.0, 1695.0, 1715.0, 1000000, 1715000000.0, 1.0),
            ("600519.SH", "2024-01-03", 1715.0, 1730.0, 1710.0, 1725.0, 1200000, 2070000000.0, 1.0),
            ("000001.SZ", "2024-01-02", 12.0, 12.5, 11.9, 12.3, 5000000, 61500000.0, 1.1),
            # volume=0 应被过滤
            ("000002.SZ", "2024-01-02", 8.0, 8.1, 7.9, 8.0, 0, 0.0, 1.0),
        ],
    )
    cur.executemany(
        "INSERT INTO daily_basic(code, trade_date, pe_ttm, pb, ps_ttm, dv_ttm, "
        "total_mv, circ_mv, turnover_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # 600519 两天, 应该取 01-03 最新
            ("600519.SH", "2024-01-02", 30.0, 8.5, 12.0, 1.2, 2.1e12, 2.1e12, 0.3),
            ("600519.SH", "2024-01-03", 30.1, 8.6, 12.1, 1.2, 2.12e12, 2.12e12, 0.32),
            ("000001.SZ", "2024-01-02", 6.5, 0.7, 2.0, 3.5, 2.4e11, 2.3e11, 0.5),
        ],
    )
    cur.executemany(
        "INSERT INTO factor_registry(id, name, category, direction, expression, "
        "code_content, hypothesis, source, lookback_days, status, pool, "
        "gate_ic, gate_ir, gate_mono, gate_t, ic_decay_ratio, "
        "created_at, updated_at) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("uuid-1", "turnover_mean_20", "liquidity", -1, "expr_1",
             None, "hypothesis_1", "builtin", 60, "active", "CORE",
             -0.091, -0.9, None, -30.0, 0.85, "2024-01-01", "2024-01-01"),
            ("uuid-2", "bp_ratio", "fundamental", 1, "inv(pb)",
             None, "value_anomaly", "builtin", 60, "active", "CORE",
             0.107, 0.9, None, 28.0, 0.92, "2024-01-01", "2024-01-01"),
            ("uuid-3", "reversal_20", "momentum", -1, "expr_3",
             None, "reversion", "builtin", 60, "warning", "CORE5_baseline",
             -0.05, -0.4, None, -12.0, 0.43, "2024-01-01", "2024-01-01"),
            ("uuid-4", "mf_divergence", "moneyflow", 1, "expr_4",
             None, "bogus", "gp", 60, "deprecated", "INVALIDATED",
             -0.022, -0.2, None, -3.0, 0.0, "2024-01-01", "2024-01-01"),
        ],
    )
    db.commit()

    class _SharedConn:
        def __init__(self, inner: sqlite3.Connection):
            self._inner = inner

        def cursor(self):
            return self._inner.cursor()

        def commit(self):
            self._inner.commit()

        def close(self):
            pass  # keep shared db alive

    def factory():
        return _SharedConn(db)

    yield factory
    db.close()


# =========================================================================
# 组 1: 构造 + 依赖注入 (MagicMock)
# =========================================================================


def test_dal_constructs_without_cache(mock_conn_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=mock_conn_factory)
    assert dal._cache is None
    assert dal._ph == "%s"


def test_dal_constructs_with_cache_and_paramstyle(mock_conn_factory) -> None:
    cache = MagicMock()
    dal = PlatformDataAccessLayer(
        conn_factory=mock_conn_factory, factor_cache=cache, paramstyle="?"
    )
    assert dal._cache is cache
    assert dal._ph == "?"


def test_dal_concrete_implements_all_abstracts(mock_conn_factory) -> None:
    """PlatformDataAccessLayer 可实例化 (abstract 方法全部实现)."""
    dal = PlatformDataAccessLayer(conn_factory=mock_conn_factory)
    assert hasattr(dal, "read_factor")
    assert hasattr(dal, "read_ohlc")
    assert hasattr(dal, "read_fundamentals")
    assert hasattr(dal, "read_registry")


def test_dal_conn_released_after_read(sqlite_factory) -> None:
    """每次 read 走 conn_factory + 释放."""
    call_count = [0]

    def counting_factory():
        call_count[0] += 1
        return sqlite_factory()

    dal = PlatformDataAccessLayer(conn_factory=counting_factory, paramstyle="?")
    dal.read_factor("turnover_mean_20", date(2024, 1, 1), date(2024, 1, 10))
    dal.read_factor("turnover_mean_20", date(2024, 1, 1), date(2024, 1, 10))
    assert call_count[0] == 2  # 两次调用, 两次 factory


# =========================================================================
# 组 2: SQL 路径 (sqlite)
# =========================================================================


def test_read_factor_sql_path_no_cache(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_factor("turnover_mean_20", date(2024, 1, 1), date(2024, 1, 10))
    assert list(df.columns) == ["code", "trade_date", "value"]
    # NaN neutral_value (000002.SZ) 应被 IS NOT NULL 过滤
    assert len(df) == 3
    assert "000002.SZ" not in df["code"].values
    assert set(df["code"]) == {"600519.SH", "000001.SZ"}


def test_read_factor_column_whitelist_raw(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_factor(
        "turnover_mean_20", date(2024, 1, 1), date(2024, 1, 10), column="raw_value"
    )
    # raw_value 有 4 行 (含 000002.SZ, 因 raw 不 NaN)
    assert len(df) == 4


def test_read_factor_invalid_column_raises(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    with pytest.raises(UnsupportedColumn, match="bogus_col"):
        dal.read_factor("x", date(2024, 1, 1), date(2024, 1, 10), column="bogus_col")


def test_read_factor_empty_range_returns_empty_df(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_factor("turnover_mean_20", date(2030, 1, 1), date(2030, 12, 31))
    assert df.empty
    assert list(df.columns) == ["code", "trade_date", "value"]


def test_read_ohlc_returns_expected_columns(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_ohlc(
        codes=["600519.SH", "000001.SZ"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
    )
    assert list(df.columns) == [
        "code", "trade_date", "open", "high", "low", "close",
        "volume", "amount", "adj_factor",
    ]
    # 3 行 (600519 两天 + 000001 一天, 000002 volume=0 过滤)
    assert len(df) == 3
    assert set(df["code"]) == {"600519.SH", "000001.SZ"}


def test_read_ohlc_empty_codes_returns_empty(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_ohlc(codes=[], start=date(2024, 1, 1), end=date(2024, 1, 10))
    assert df.empty


def test_read_fundamentals_latest_per_code(sqlite_factory) -> None:
    """每 code 返回最新 trade_date 的 PIT 快照."""
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_fundamentals(
        codes=["600519.SH", "000001.SZ"],
        fields=["pe_ttm", "pb", "dv_ttm"],
        as_of=date(2024, 1, 10),
    )
    assert list(df.columns) == ["code", "trade_date", "pe_ttm", "pb", "dv_ttm"]
    assert len(df) == 2
    # 600519 应返回 01-03 (最新)
    row = df[df["code"] == "600519.SH"].iloc[0]
    assert row["pe_ttm"] == pytest.approx(30.1)


def test_read_fundamentals_as_of_excludes_future(sqlite_factory) -> None:
    """as_of 之后的数据不返回."""
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_fundamentals(
        codes=["600519.SH"],
        fields=["pe_ttm"],
        as_of=date(2024, 1, 2),  # 只到 01-02
    )
    assert len(df) == 1
    assert df.iloc[0]["pe_ttm"] == pytest.approx(30.0)  # 01-02 的值


def test_read_fundamentals_field_whitelist(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    with pytest.raises(UnsupportedField, match="forbidden"):
        dal.read_fundamentals(
            codes=["600519.SH"],
            fields=["pe_ttm", "forbidden_field"],
            as_of=date(2024, 1, 10),
        )


def test_read_fundamentals_empty_fields_raises(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    with pytest.raises(UnsupportedField, match="不能为空"):
        dal.read_fundamentals(
            codes=["600519.SH"], fields=[], as_of=date(2024, 1, 10)
        )


def test_read_registry_all(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_registry()
    assert len(df) == 4
    # MVP 1.3a: 对齐 live PG 18 字段
    assert list(df.columns) == [
        "id", "name", "category", "direction", "expression", "code_content",
        "hypothesis", "source", "lookback_days", "status", "pool",
        "gate_ic", "gate_ir", "gate_mono", "gate_t", "ic_decay_ratio",
        "created_at", "updated_at",
    ]


def test_read_registry_status_filter(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_registry(status_filter="active")
    assert len(df) == 2
    assert set(df["name"]) == {"turnover_mean_20", "bp_ratio"}


def test_read_registry_pool_filter(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_registry(pool_filter="CORE")
    assert len(df) == 2
    assert set(df["name"]) == {"turnover_mean_20", "bp_ratio"}


def test_read_registry_combined_filters(sqlite_factory) -> None:
    dal = PlatformDataAccessLayer(conn_factory=sqlite_factory, paramstyle="?")
    df = dal.read_registry(status_filter="active", pool_filter="CORE")
    assert len(df) == 2
    df2 = dal.read_registry(status_filter="deprecated", pool_filter="CORE")
    assert len(df2) == 0  # CORE 无 deprecated


# =========================================================================
# 组 3: cache 路径 (MagicMock)
# =========================================================================


def test_read_factor_with_cache_calls_load() -> None:
    """有 factor_cache 时 read_factor 走 cache.load(), 不走 SQL."""
    mock_conn = MagicMock()
    conn_factory = MagicMock(return_value=mock_conn)
    cache = MagicMock()
    cache.load.return_value = pd.DataFrame(
        {"code": ["x"], "trade_date": [pd.Timestamp("2024-01-02")], "value": [1.23]}
    )

    dal = PlatformDataAccessLayer(conn_factory=conn_factory, factor_cache=cache)
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    df = dal.read_factor("f1", start, end, column="neutral_value")

    # cache.load 被调用, 参数正确
    cache.load.assert_called_once_with(
        "f1",
        column="neutral_value",
        start=start,
        end=end,
        conn=mock_conn,
        auto_refresh=True,
    )
    # SQL execute 不被调用
    mock_conn.cursor.assert_not_called()
    assert list(df.columns) == ["code", "trade_date", "value"]
    assert df.iloc[0]["value"] == 1.23


def test_read_factor_cache_exception_propagates() -> None:
    """cache.load 抛异常时不 silent fallback, 直接传给上层 (铁律 33)."""
    cache = MagicMock()
    cache.load.side_effect = RuntimeError("cache corruption")
    conn_factory = MagicMock(return_value=MagicMock())

    dal = PlatformDataAccessLayer(conn_factory=conn_factory, factor_cache=cache)
    with pytest.raises(RuntimeError, match="cache corruption"):
        dal.read_factor("f1", date(2024, 1, 1), date(2024, 1, 31))


def test_read_factor_cache_invalid_column_raises_before_load() -> None:
    """column 白名单校验在 cache.load 之前发生."""
    cache = MagicMock()
    dal = PlatformDataAccessLayer(
        conn_factory=MagicMock(), factor_cache=cache
    )
    with pytest.raises(UnsupportedColumn):
        dal.read_factor("f1", date(2024, 1, 1), date(2024, 1, 31), column="bogus")
    cache.load.assert_not_called()
