"""DataFeed多源支持测试 (C2)。

测试:
1. from_parquet roundtrip: 写出 → 读回 → 完全一致
2. from_dataframe 基本功能
3. validate() 缺列报错
4. 属性: df, date_range, codes, get_daily
5. DataFeed传入run_hybrid_backtest正常运行
"""

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.datafeed import REQUIRED_COLUMNS, DataFeed, DataFeedValidationError

# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════

def _make_trading_days(start: date, n_days: int) -> list[date]:
    """生成n个交易日（跳过周末）。"""
    days = []
    d = start
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _make_price_df(
    codes: list[str],
    trading_days: list[date],
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成行情DataFrame，包含所有必需列+推荐列。"""
    rng = np.random.RandomState(seed)
    rows = []
    for code in codes:
        base_price = rng.uniform(10, 50)
        for td in trading_days:
            ret = rng.normal(0.001, 0.02)
            close = base_price * (1 + ret)
            base_price = close
            pre_close = close / (1 + ret)
            volume = int(rng.uniform(50000, 500000))
            amount = close * volume * 100 / 1000  # 千元
            rows.append({
                "code": code,
                "trade_date": td,
                "open": round(close * (1 + rng.normal(0, 0.005)), 2),
                "high": round(close * 1.02, 2),
                "low": round(close * 0.98, 2),
                "close": round(close, 2),
                "volume": volume,
                "amount": round(amount, 2),
                "pre_close": round(pre_close, 2),
                "adj_factor": 1.0,
                "turnover_rate": round(rng.uniform(1, 10), 2),
                "total_mv": round(rng.uniform(100000, 5000000), 2),
                "industry_sw1": f"sw_{int(code[:2]) % 5}",
                "up_limit": round(pre_close * 1.10, 2),
                "down_limit": round(pre_close * 0.90, 2),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_df():
    """标准测试用DataFrame。"""
    codes = [f"{i:06d}.SZ" for i in range(1, 11)]
    days = _make_trading_days(date(2024, 1, 2), 60)
    return _make_price_df(codes, days)


# ═══════════════════════════════════════════════════
# Test: from_dataframe
# ═══════════════════════════════════════════════════

class TestFromDataFrame:
    """DataFeed.from_dataframe 基本功能。"""

    def test_basic_creation(self, sample_df):
        """从DataFrame创建DataFeed成功。"""
        feed = DataFeed.from_dataframe(sample_df)
        assert len(feed.df) == len(sample_df)

    def test_returns_copy(self, sample_df):
        """from_dataframe返回的是副本，修改不影响原始。"""
        feed = DataFeed.from_dataframe(sample_df)
        feed.df.iloc[0, 0] = "MODIFIED"
        assert sample_df.iloc[0, 0] != "MODIFIED"

    def test_properties(self, sample_df):
        """df, date_range, codes属性正确。"""
        feed = DataFeed.from_dataframe(sample_df)

        start, end = feed.date_range
        assert start == min(sample_df["trade_date"])
        assert end == max(sample_df["trade_date"])

        codes = feed.codes
        assert len(codes) == sample_df["code"].nunique()
        assert codes == sorted(codes)

    def test_get_daily(self, sample_df):
        """get_daily返回单日截面。"""
        feed = DataFeed.from_dataframe(sample_df)
        first_date = feed.date_range[0]
        daily = feed.get_daily(first_date)
        assert all(daily["trade_date"] == first_date)
        assert len(daily) == sample_df["code"].nunique()

    def test_empty_dataframe(self):
        """空DataFrame可以创建（validate不报错）。"""
        empty = pd.DataFrame(columns=REQUIRED_COLUMNS)
        feed = DataFeed.from_dataframe(empty)
        assert feed.df.empty
        assert feed.date_range == (None, None)
        assert feed.codes == []


# ═══════════════════════════════════════════════════
# Test: from_parquet roundtrip
# ═══════════════════════════════════════════════════

class TestFromParquet:
    """Parquet读写roundtrip。"""

    def test_roundtrip_identical(self, sample_df):
        """写出Parquet → 读回 → 与原始DataFrame完全一致。"""
        feed_orig = DataFeed.from_dataframe(sample_df)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_snapshot.parquet"
            feed_orig.to_parquet(path)

            assert path.exists()

            feed_loaded = DataFeed.from_parquet(path)

            # 行数一致
            assert len(feed_loaded.df) == len(feed_orig.df)

            # 列一致
            assert set(feed_loaded.df.columns) == set(feed_orig.df.columns)

            # 数值一致（trade_date转换后比较）
            orig_sorted = feed_orig.df.sort_values(
                ["code", "trade_date"]
            ).reset_index(drop=True)
            loaded_sorted = feed_loaded.df.sort_values(
                ["code", "trade_date"]
            ).reset_index(drop=True)

            for col in ["open", "high", "low", "close", "volume", "amount"]:
                pd.testing.assert_series_equal(
                    orig_sorted[col], loaded_sorted[col], check_names=False,
                )

    def test_file_not_found(self):
        """不存在的Parquet文件抛出FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            DataFeed.from_parquet("/nonexistent/path.parquet")

    def test_date_preservation(self, sample_df):
        """Parquet roundtrip后trade_date类型保持date。"""
        feed = DataFeed.from_dataframe(sample_df)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dates.parquet"
            feed.to_parquet(path)
            loaded = DataFeed.from_parquet(path)

            # trade_date应为date类型（非Timestamp）
            sample_val = loaded.df["trade_date"].iloc[0]
            assert isinstance(sample_val, date)


# ═══════════════════════════════════════════════════
# Test: validate
# ═══════════════════════════════════════════════════

class TestValidate:
    """DataFeed.validate() 列检查。"""

    def test_missing_required_columns(self):
        """缺少必需列抛出DataFeedValidationError。"""
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "trade_date": [date(2024, 1, 2)],
            "open": [10.0],
            # 缺少 high, low, close, volume, amount
        })
        with pytest.raises(DataFeedValidationError, match="缺少必需列"):
            DataFeed.from_dataframe(df)

    def test_wrong_dtype(self):
        """数值列为非数值类型抛出错误。"""
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "trade_date": [date(2024, 1, 2)],
            "open": ["not_a_number"],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100000],
            "amount": [1050000.0],
        })
        with pytest.raises(DataFeedValidationError, match="应为数值类型"):
            DataFeed.from_dataframe(df)

    def test_valid_passes(self, sample_df):
        """完整数据验证通过。"""
        feed = DataFeed.from_dataframe(sample_df)
        feed.validate()  # 不抛异常


# ═══════════════════════════════════════════════════
# Test: DataFeed与回测引擎集成
# ═══════════════════════════════════════════════════

class TestDataFeedIntegration:
    """DataFeed传入run_hybrid_backtest。"""

    def test_datafeed_in_hybrid_backtest(self, sample_df):
        """DataFeed对象传入run_hybrid_backtest正常运行。"""
        from engines.backtest_engine import BacktestConfig, run_hybrid_backtest

        codes = sample_df["code"].unique().tolist()
        days = sorted(sample_df["trade_date"].unique())
        factors = ["f1", "f2"]
        directions = {"f1": 1, "f2": -1}

        rng = np.random.RandomState(99)
        factor_rows = []
        for td in days:
            for code in codes:
                for f in factors:
                    factor_rows.append({
                        "code": code,
                        "trade_date": td,
                        "factor_name": f,
                        "raw_value": round(rng.normal(0, 1), 4),
                    })
        factor_df = pd.DataFrame(factor_rows)

        feed = DataFeed.from_dataframe(sample_df)

        config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=5,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=10.0,
        )

        result = run_hybrid_backtest(
            factor_df=factor_df,
            directions=directions,
            price_data=sample_df,  # 兼容：即使传了price_data，datafeed优先
            config=config,
            datafeed=feed,
        )

        assert len(result.daily_nav) > 0
        assert result.daily_nav.iloc[-1] > 0

    def test_datafeed_vs_direct_df_identical(self, sample_df):
        """DataFeed路径 vs 直接传DataFrame路径结果一致。"""
        from engines.backtest_engine import BacktestConfig, run_hybrid_backtest

        codes = sample_df["code"].unique().tolist()
        days = sorted(sample_df["trade_date"].unique())
        rng = np.random.RandomState(99)
        factor_rows = []
        for td in days:
            for code in codes:
                for f in ["f1", "f2"]:
                    factor_rows.append({
                        "code": code,
                        "trade_date": td,
                        "factor_name": f,
                        "raw_value": round(rng.normal(0, 1), 4),
                    })
        factor_df = pd.DataFrame(factor_rows)

        config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=5,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=10.0,
        )

        # 直接传DataFrame
        r1 = run_hybrid_backtest(
            factor_df=factor_df,
            directions={"f1": 1, "f2": -1},
            price_data=sample_df,
            config=config,
        )

        # 通过DataFeed传
        feed = DataFeed.from_dataframe(sample_df)
        r2 = run_hybrid_backtest(
            factor_df=factor_df,
            directions={"f1": 1, "f2": -1},
            price_data=sample_df,
            config=config,
            datafeed=feed,
        )

        pd.testing.assert_series_equal(r1.daily_nav, r2.daily_nav)
