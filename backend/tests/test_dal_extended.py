"""MVP 2.1c Sub-commit 1: test PlatformDataAccessLayer 7 新方法.

使用 sqlite :memory: 作 mock DB, 全部单测覆盖:
  - read_calendar (klines_daily DISTINCT trade_date)
  - read_universe (symbols 有效 A 股)
  - read_stock_status (stock_status_daily 日级快照)
  - read_factor_names (factor_values DISTINCT factor_name)
  - read_freshness (MAX(trade_date) + UnsupportedTable 白名单)
  - read_reconcile_counts (COUNT(*) per trade_date + UnsupportedTable)
  - read_pead_announcements (earnings_announcements Q1 窗口)
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from backend.qm_platform.data.access_layer import (
    PlatformDataAccessLayer,
    UnsupportedTable,
)

# ============================================================
# Fixtures — sqlite :memory: with 8 tables + seed
# ============================================================


@pytest.fixture
def seeded_conn():
    """sqlite :memory: conn with Platform 相关 8 表 seed 数据."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    # klines_daily (for read_calendar + freshness)
    cur.execute(
        "CREATE TABLE klines_daily ("
        "code TEXT, trade_date DATE, close REAL)"
    )
    cur.executemany(
        "INSERT INTO klines_daily VALUES (?, ?, ?)",
        [
            ("600519.SH", date(2026, 4, 14), 1800.0),
            ("600519.SH", date(2026, 4, 15), 1810.0),
            ("000001.SZ", date(2026, 4, 14), 12.0),
            ("000001.SZ", date(2026, 4, 15), 12.1),
            ("600519.SH", date(2026, 4, 16), 1820.0),
        ],
    )

    # symbols (for read_universe)
    cur.execute(
        "CREATE TABLE symbols ("
        "code TEXT PRIMARY KEY, market TEXT, list_status TEXT, "
        "list_date DATE, delist_date DATE)"
    )
    cur.executemany(
        "INSERT INTO symbols VALUES (?, ?, ?, ?, ?)",
        [
            ("600519.SH", "astock", "L", date(2001, 8, 27), None),  # 已上市
            ("000001.SZ", "astock", "L", date(1991, 4, 3), None),   # 已上市
            ("999999.SH", "astock", "D", date(2000, 1, 1),
             date(2020, 5, 1)),  # 已退市
            ("688001.SH", "astock", "L", date(2027, 1, 1), None),   # 未上市
            ("AUDUSD", "forex", "L", None, None),  # 非 astock
        ],
    )

    # stock_status_daily
    cur.execute(
        "CREATE TABLE stock_status_daily ("
        "code TEXT, trade_date DATE, is_st INTEGER, is_suspended INTEGER, "
        "is_new_stock INTEGER, board TEXT, list_date DATE, delist_date DATE, "
        "PRIMARY KEY (code, trade_date))"
    )
    cur.executemany(
        "INSERT INTO stock_status_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("600519.SH", date(2026, 4, 15), 0, 0, 0, "main",
             date(2001, 8, 27), None),
            ("000001.SZ", date(2026, 4, 15), 0, 1, 0, "main",
             date(1991, 4, 3), None),  # 停牌
            ("300001.SZ", date(2026, 4, 15), 1, 0, 0, "gem",
             date(2009, 1, 1), None),  # ST
        ],
    )

    # factor_values (for read_factor_names source='values' + freshness)
    cur.execute(
        "CREATE TABLE factor_values ("
        "factor_name TEXT, code TEXT, trade_date DATE, "
        "raw_value REAL, neutral_value REAL)"
    )
    cur.executemany(
        "INSERT INTO factor_values VALUES (?, ?, ?, ?, ?)",
        [
            ("bp_ratio", "600519.SH", date(2026, 4, 15), 0.05, 0.02),
            ("bp_ratio", "000001.SZ", date(2026, 4, 15), 0.08, 0.03),
            ("volatility_20", "600519.SH", date(2026, 4, 15), 0.15, 0.1),
            ("turnover_mean_20", "600519.SH", date(2026, 4, 15), 0.02, 0.01),
        ],
    )

    # factor_registry (for read_factor_names source='registry' 默认快路径)
    cur.execute(
        "CREATE TABLE factor_registry ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT, "
        "direction INTEGER, status TEXT, pool TEXT)"
    )
    cur.executemany(
        "INSERT INTO factor_registry VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("1", "bp_ratio", "fundamental", 1, "active", "CORE"),
            ("2", "volatility_20", "price_volume", -1, "active", "CORE"),
            ("3", "turnover_mean_20", "liquidity", -1, "active", "CORE"),
            # 额外因子: 已注册但 factor_values 暂无数据 (验证 registry vs values 语义差)
            ("4", "reversal_20", "price_volume", 1, "deprecated", "LEGACY"),
        ],
    )

    # earnings_announcements (for read_pead_announcements)
    cur.execute(
        "CREATE TABLE earnings_announcements ("
        "ts_code TEXT, trade_date DATE, report_type TEXT, "
        "eps_surprise_pct REAL, ann_td DATE)"
    )
    cur.executemany(
        "INSERT INTO earnings_announcements VALUES (?, ?, ?, ?, ?)",
        [
            # Q1 窗口内正常
            ("600519.SH", date(2026, 4, 12), "Q1", 0.05, date(2026, 4, 12)),
            ("000001.SZ", date(2026, 4, 13), "Q1", -0.03, date(2026, 4, 13)),
            # Q1 但超出窗口 (> 7 天)
            ("002001.SZ", date(2026, 3, 20), "Q1", 0.10, date(2026, 3, 20)),
            # 非 Q1 (应过滤)
            ("000002.SZ", date(2026, 4, 14), "Q3", 0.05, date(2026, 4, 14)),
            # abs(eps_surprise) >= 10 (应过滤)
            ("002002.SZ", date(2026, 4, 13), "Q1", 15.0, date(2026, 4, 13)),
            # eps_surprise NULL (应过滤)
            ("002003.SZ", date(2026, 4, 13), "Q1", None, date(2026, 4, 13)),
        ],
    )

    # 其他 freshness 白名单表 (仅 schema, 用于验证 freshness/reconcile 通过)
    for tbl in ("daily_basic", "moneyflow_daily", "index_daily",
                "minute_bars"):
        cur.execute(
            f"CREATE TABLE {tbl} (code TEXT, trade_date DATE, val REAL)"
        )
    cur.execute(
        "INSERT INTO daily_basic VALUES (?, ?, ?)",
        ("600519.SH", date(2026, 4, 15), 30.5),
    )
    cur.execute(
        "INSERT INTO index_daily VALUES (?, ?, ?)",
        ("000300.SH", date(2026, 4, 15), 3800.0),
    )
    conn.commit()
    return conn


@pytest.fixture
def dal(seeded_conn):
    """DAL instance with sqlite paramstyle."""
    return PlatformDataAccessLayer(
        conn_factory=lambda: seeded_conn,
        factor_cache=None,
        paramstyle="?",
    )


# ============================================================
# read_calendar (3 tests)
# ============================================================


def test_read_calendar_no_filter(dal):
    result = dal.read_calendar()
    assert len(result) == 3
    assert result == [
        date(2026, 4, 14), date(2026, 4, 15), date(2026, 4, 16),
    ]


def test_read_calendar_start_end_filter(dal):
    result = dal.read_calendar(
        start=date(2026, 4, 15), end=date(2026, 4, 15),
    )
    assert result == [date(2026, 4, 15)]


def test_read_calendar_empty_range(dal):
    result = dal.read_calendar(
        start=date(2027, 1, 1), end=date(2027, 12, 31),
    )
    assert result == []


# ============================================================
# read_universe (3 tests)
# ============================================================


def test_read_universe_excludes_delisted(dal):
    result = dal.read_universe(as_of=date(2026, 4, 15))
    assert "999999.SH" not in result  # list_status=D


def test_read_universe_excludes_not_listed(dal):
    result = dal.read_universe(as_of=date(2026, 4, 15))
    assert "688001.SH" not in result  # list_date > as_of


def test_read_universe_returns_active_astock_only(dal):
    result = dal.read_universe(as_of=date(2026, 4, 15))
    assert "600519.SH" in result
    assert "000001.SZ" in result
    assert "AUDUSD" not in result  # market=forex
    assert len(result) == 2


# ============================================================
# read_stock_status (3 tests)
# ============================================================


def test_read_stock_status_basic(dal):
    df = dal.read_stock_status(
        codes=["600519.SH", "000001.SZ"], as_of=date(2026, 4, 15),
    )
    assert len(df) == 2
    assert set(df.columns) == {
        "code", "is_st", "is_suspended", "is_new_stock",
        "board", "list_date", "delist_date",
    }


def test_read_stock_status_empty_codes(dal):
    df = dal.read_stock_status(codes=[], as_of=date(2026, 4, 15))
    assert df.empty
    assert list(df.columns) == [
        "code", "is_st", "is_suspended", "is_new_stock",
        "board", "list_date", "delist_date",
    ]


def test_read_stock_status_detects_suspended_and_st(dal):
    df = dal.read_stock_status(
        codes=["600519.SH", "000001.SZ", "300001.SZ"],
        as_of=date(2026, 4, 15),
    )
    row = df[df["code"] == "000001.SZ"].iloc[0]
    assert row["is_suspended"] == 1
    assert row["is_st"] == 0
    row = df[df["code"] == "300001.SZ"].iloc[0]
    assert row["is_st"] == 1
    assert row["board"] == "gem"


# ============================================================
# read_factor_names (3 tests, 双 source)
# ============================================================


def test_read_factor_names_registry_default(dal):
    """默认 source='registry' 走 factor_registry 表, 含未入库的因子."""
    names = dal.read_factor_names()
    # registry 有 4 因子 (bp_ratio / volatility_20 / turnover_mean_20 / reversal_20),
    # 最后一个 reversal_20 在 factor_values 无数据但注册了, 仍返.
    assert names == [
        "bp_ratio", "reversal_20", "turnover_mean_20", "volatility_20",
    ]


def test_read_factor_names_values_source(dal):
    """显式 source='values' 走 factor_values DISTINCT, 仅返有数据的因子."""
    names = dal.read_factor_names(source="values")
    # factor_values 只有 3 个 factor_name (无 reversal_20)
    assert names == ["bp_ratio", "turnover_mean_20", "volatility_20"]


def test_read_factor_names_invalid_source_raises(dal):
    with pytest.raises(ValueError, match="source must be"):
        dal.read_factor_names(source="bogus")


def test_read_factor_names_empty_registry(seeded_conn):
    # 清空 factor_registry 后 default source 返 []
    seeded_conn.execute("DELETE FROM factor_registry")
    seeded_conn.commit()
    dal = PlatformDataAccessLayer(
        conn_factory=lambda: seeded_conn,
        factor_cache=None,
        paramstyle="?",
    )
    assert dal.read_factor_names() == []


# ============================================================
# read_freshness (3 tests)
# ============================================================


def test_read_freshness_basic(dal):
    result = dal.read_freshness(
        tables=["klines_daily", "factor_values", "daily_basic"],
    )
    assert result["klines_daily"] == date(2026, 4, 16)
    assert result["factor_values"] == date(2026, 4, 15)
    assert result["daily_basic"] == date(2026, 4, 15)


def test_read_freshness_unsupported_table_raises(dal):
    with pytest.raises(UnsupportedTable, match="非白名单"):
        dal.read_freshness(tables=["klines_daily", "user_accounts"])


def test_read_freshness_empty_tables(dal):
    assert dal.read_freshness(tables=[]) == {}


# ============================================================
# read_reconcile_counts (2 tests)
# ============================================================


def test_read_reconcile_counts_basic(dal):
    result = dal.read_reconcile_counts(
        tables=["klines_daily", "factor_values"],
        as_of=date(2026, 4, 15),
    )
    assert result["klines_daily"] == 2  # 2 stocks on 2026-04-15
    assert result["factor_values"] == 4  # 4 factor values on 2026-04-15


def test_read_reconcile_counts_unsupported_raises(dal):
    with pytest.raises(UnsupportedTable):
        dal.read_reconcile_counts(
            tables=["factor_registry"],  # 非白名单
            as_of=date(2026, 4, 15),
        )


# ============================================================
# read_pead_announcements (3 tests)
# ============================================================


def test_read_pead_basic(dal):
    df = dal.read_pead_announcements(
        trade_date=date(2026, 4, 15), lookback_days=7,
    )
    # 期望: 2 行 (600519.SH + 000001.SZ 在窗口内 Q1 且 eps 合法)
    assert len(df) == 2
    assert set(df["ts_code"]) == {"600519.SH", "000001.SZ"}


def test_read_pead_excludes_non_q1_and_large_eps(dal):
    df = dal.read_pead_announcements(
        trade_date=date(2026, 4, 15), lookback_days=30,
    )
    # 应排除: Q3 (000002.SZ) + abs eps>=10 (002002.SZ) + eps NULL (002003.SZ)
    tscodes = set(df["ts_code"])
    assert "000002.SZ" not in tscodes
    assert "002002.SZ" not in tscodes
    assert "002003.SZ" not in tscodes
    # 在 30 天窗口内 002001.SZ 也应入 (Q1 0.10 合法)
    assert "002001.SZ" in tscodes


def test_read_pead_empty_window_returns_empty_df(dal):
    df = dal.read_pead_announcements(
        trade_date=date(2025, 1, 1), lookback_days=7,
    )
    assert df.empty
    assert list(df.columns) == ["ts_code", "eps_surprise_pct", "ann_td"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
