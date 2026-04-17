"""P0-2 测试: FactorCache MVP (docs/DATA_SYSTEM_V1 §8.2 acceptance)."""

from __future__ import annotations

import threading
from datetime import date

import pandas as pd
import pytest

from backend.data.factor_cache import VALID_COLUMNS, FactorCache, FactorCacheError

# ============================================================
# Fixtures
# ============================================================


class MockConn:
    """psycopg2 connection-like mock."""

    def __init__(self, data: dict[tuple[str, str], list[tuple]] | None = None):
        """
        Args:
            data: key=(factor_name, column) → list of (code, date, value)
        """
        self.data = data or {}
        self._last_query = None

    def cursor(self):
        return MockCursor(self)


class MockCursor:
    def __init__(self, conn):
        self.conn = conn
        self._results = []
        self._pos = 0

    def execute(self, sql: str, params=None):
        self.conn._last_query = (sql, params)
        sql_lower = sql.lower().replace("\n", " ")

        # SELECT MAX(trade_date), COUNT(*) ... 用于 refresh
        if "max(trade_date)" in sql_lower and "count(*)" in sql_lower:
            factor_name = params[0]
            # 找所有匹配的 column
            rows_all = []
            for (fn, col), rows in self.conn.data.items():
                if fn == factor_name and col in sql_lower:
                    rows_all.extend(rows)
            if not rows_all:
                self._results = [(None, 0)]
            else:
                max_d = max(r[1] for r in rows_all)
                self._results = [(max_d, len(rows_all))]

        # SELECT MIN/MAX trade_date 用于 _determine_years
        elif "min(trade_date)" in sql_lower and "max(trade_date)" in sql_lower:
            factor_name = params[0]
            col_hit = None
            for col in VALID_COLUMNS:
                if col in sql_lower:
                    col_hit = col
                    break
            rows = self.conn.data.get((factor_name, col_hit), [])
            if not rows:
                self._results = [(None, None)]
            else:
                self._results = [(min(r[1] for r in rows), max(r[1] for r in rows))]

        # SELECT code, trade_date, {col} ... 用于 _build_year
        elif "select code, trade_date" in sql_lower:
            factor_name = params[0]
            year = params[1]
            col_hit = None
            for col in VALID_COLUMNS:
                if col in sql_lower.split("where")[0]:
                    col_hit = col
                    break
            rows = self.conn.data.get((factor_name, col_hit), [])
            self._results = [r for r in rows if r[1].year == year]
        else:
            self._results = []

        self._pos = 0

    def fetchall(self):
        return list(self._results)

    def fetchone(self):
        return self._results[0] if self._results else None

    def close(self):
        pass


@pytest.fixture
def tmp_cache(tmp_path):
    """临时缓存目录 (scoped to test)."""
    return FactorCache(cache_dir=tmp_path / "fc")


@pytest.fixture
def seed_data():
    """构造种子数据: 2 因子 × 2 列 × 2 年."""
    base = {
        ("f_alpha", "raw_value"): [
            ("000001", date(2020, 6, 1), 1.1),
            ("000002", date(2020, 6, 1), 1.2),
            ("000001", date(2021, 6, 1), 2.1),
            ("000002", date(2021, 6, 1), 2.2),
        ],
        ("f_alpha", "neutral_value"): [
            ("000001", date(2020, 6, 1), -0.1),
            ("000002", date(2020, 6, 1), 0.1),
            ("000001", date(2021, 6, 1), -0.2),
            ("000002", date(2021, 6, 1), 0.2),
        ],
        ("f_beta", "raw_value"): [
            ("000001", date(2020, 12, 31), 0.5),
            ("000001", date(2021, 1, 1), 0.6),
        ],
    }
    return base


# ============================================================
# Tests (7 cases per §8.2)
# ============================================================


def test_load_cache_hit(tmp_cache, seed_data):
    """Test 1: seed parquet 后 load 返回正确 shape."""
    conn = MockConn(seed_data)
    # 先 build 填充
    tmp_cache.build(["f_alpha"], [2020, 2021], conn, columns=["raw_value"])
    # 现在 load 不应触碰 conn (cache hit)
    df = tmp_cache.load("f_alpha", "raw_value", conn=conn, auto_refresh=False)
    assert len(df) == 4
    assert set(df.columns) == {"code", "trade_date", "value"}
    assert df["value"].dtype.kind == "f"


def test_refresh_incremental(tmp_cache, seed_data):
    """Test 2: cache 至 2020, DB 有到 2021, refresh 应追加 2021."""
    conn = MockConn(seed_data)
    # 初始 build 只有 2020
    tmp_cache.build(["f_alpha"], [2020], conn, columns=["raw_value"])
    assert tmp_cache._get_cache_max_date("f_alpha", "raw_value") == date(2020, 6, 1)

    # refresh 应检测到 DB 有 2021 数据
    n = tmp_cache.refresh("f_alpha", "raw_value", conn)
    assert n >= 2  # 至少追加 2 行
    new_max = tmp_cache._get_cache_max_date("f_alpha", "raw_value")
    assert new_max == date(2021, 6, 1)


def test_invalidate_removes_files(tmp_cache, seed_data):
    """Test 3: invalidate 删除 parquet + meta (某 column) 或整因子."""
    conn = MockConn(seed_data)
    tmp_cache.build(["f_alpha"], [2020, 2021], conn, columns=["raw_value", "neutral_value"])
    factor_dir = tmp_cache._factor_dir("f_alpha")
    assert len(list(factor_dir.glob("raw_*.parquet"))) == 2
    assert len(list(factor_dir.glob("neutral_*.parquet"))) == 2

    # 删除单 column
    n = tmp_cache.invalidate("f_alpha", column="raw_value")
    assert n == 2
    assert len(list(factor_dir.glob("raw_*.parquet"))) == 0
    assert len(list(factor_dir.glob("neutral_*.parquet"))) == 2  # 保留

    # 删除全因子
    n = tmp_cache.invalidate("f_alpha")
    assert n == 2


def test_build_full_rebuild(tmp_cache, seed_data):
    """Test 4: 空目录 build 后, load 回 DB 数据对齐."""
    conn = MockConn(seed_data)
    result = tmp_cache.build(["f_alpha", "f_beta"], [2020, 2021], conn)

    assert "f_alpha" in result
    assert "f_beta" in result

    # f_alpha raw 2 年各 2 行
    assert result["f_alpha"]["raw_2020"] == 2
    assert result["f_alpha"]["raw_2021"] == 2
    assert result["f_alpha"]["neutral_2020"] == 2

    # f_beta raw 跨年
    assert result["f_beta"]["raw_2020"] == 1
    assert result["f_beta"]["raw_2021"] == 1

    # round-trip 相等
    df = tmp_cache.load("f_alpha", "raw_value", conn=conn, auto_refresh=False)
    assert len(df) == 4
    expected_values = {1.1, 1.2, 2.1, 2.2}
    assert set(df["value"].round(3)) == expected_values


def test_stats_reports_shape(tmp_cache, seed_data):
    """Test 5: stats() 字段齐全."""
    conn = MockConn(seed_data)
    tmp_cache.build(["f_alpha"], [2020, 2021], conn)

    stats = tmp_cache.stats()
    assert "cache_dir" in stats
    assert "n_factors" in stats
    assert "total_size_gb" in stats
    assert "total_rows" in stats
    assert "factors" in stats
    assert stats["n_factors"] == 1
    assert stats["total_rows"] >= 4
    assert len(stats["factors"]) == 1
    assert stats["factors"][0]["name"] == "f_alpha"
    assert stats["factors"][0]["size_mb"] > 0


def test_concurrent_refresh_serialized(tmp_cache, seed_data):
    """Test 6: 2 线程并发 refresh 同一因子, 文件锁保障无重复行."""
    conn_data = dict(seed_data)
    results = []
    errors = []

    def worker():
        try:
            conn = MockConn(conn_data)
            n = tmp_cache._build_year("f_alpha", "raw_value", 2020, conn)
            results.append(n)
        except Exception as e:
            errors.append(e)

    # 先初始化 meta (否则两个线程同时创建文件夹可能冲突)
    MockConn(conn_data)
    tmp_cache._factor_dir("f_alpha")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"线程错误: {errors}"
    # 两个线程都完成 (串行), 最终文件存在, 行数正确
    path = tmp_cache._parquet_path("f_alpha", "raw_value", 2020)
    assert path.exists()
    df = pd.read_parquet(path)
    assert len(df) == 2  # 无重复, 确定 2 行


def test_shard_year_boundary(tmp_cache, seed_data):
    """Test 7: 数据跨 2020-12-31 / 2021-01-01, 应产 2 个 shard."""
    conn = MockConn(seed_data)
    tmp_cache.build(["f_beta"], [2020, 2021], conn, columns=["raw_value"])

    p_2020 = tmp_cache._parquet_path("f_beta", "raw_value", 2020)
    p_2021 = tmp_cache._parquet_path("f_beta", "raw_value", 2021)
    assert p_2020.exists()
    assert p_2021.exists()

    df_2020 = pd.read_parquet(p_2020)
    df_2021 = pd.read_parquet(p_2021)
    assert len(df_2020) == 1
    assert len(df_2021) == 1
    assert df_2020["trade_date"].iloc[0] == pd.Timestamp(2020, 12, 31)
    assert df_2021["trade_date"].iloc[0] == pd.Timestamp(2021, 1, 1)


# ============================================================
# 边界 + 健壮性
# ============================================================


def test_invalid_column_raises(tmp_cache):
    with pytest.raises(FactorCacheError, match="column"):
        tmp_cache.load("x", column="bogus", conn=None, auto_refresh=False)


def test_empty_factor_returns_empty_df(tmp_cache):
    """cache miss + no conn + auto_refresh=False → 空 DataFrame."""
    df = tmp_cache.load(
        "never_computed", column="raw_value", conn=None, auto_refresh=False,
        start=date(2020, 1, 1), end=date(2020, 12, 31),
    )
    assert df.empty
    assert list(df.columns) == ["code", "trade_date", "value"]


def test_meta_persisted_and_reloaded(tmp_cache, seed_data):
    conn = MockConn(seed_data)
    tmp_cache.build(["f_alpha"], [2020], conn, columns=["raw_value"])

    # 重开一个 cache 实例 (模拟新 session)
    cache2 = FactorCache(cache_dir=tmp_cache.cache_dir)
    meta = cache2._load_meta("f_alpha")
    assert "raw_value" in meta
    assert "2020" in meta["raw_value"]
    assert meta["raw_value"]["2020"]["row_count"] == 2


def test_corrupted_parquet_detected(tmp_cache, seed_data):
    conn = MockConn(seed_data)
    tmp_cache.build(["f_alpha"], [2020], conn, columns=["raw_value"])

    # 故意损坏 parquet
    path = tmp_cache._parquet_path("f_alpha", "raw_value", 2020)
    path.write_bytes(b"corrupted junk not parquet")

    # load 应检测到 + 重建
    df = tmp_cache.load("f_alpha", "raw_value", conn=conn, auto_refresh=True)
    # 修复后内容正确 (2 行)
    assert len(df) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
