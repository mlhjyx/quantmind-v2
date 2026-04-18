"""MVP 2.3 Sub1 PR C1 · 内建 data_loader 参考实现单测.

覆盖 `backend.platform.backtest.loaders`:
  - ParquetBaselineLoader: 3 文件齐 / benchmark 缺失 / factor 或 price 缺失 FileNotFoundError
  - BacktestCacheLoader: is_valid True / is_valid False → ValueError
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.platform.backtest.interface import BacktestConfig
from backend.platform.backtest.loaders import BacktestCacheLoader, ParquetBaselineLoader

# ─── Fixtures ──────────────────────────────────────────────


def _fake_config() -> BacktestConfig:
    return BacktestConfig(
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
        universe="csi300",
        factor_pool=("bp_ratio",),
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.50,
        cost_model="full",
        capital="1000000.0",
        benchmark="csi300",
        extra={},
    )


def _write_parquet(path: Path, rows: int = 3) -> None:
    """写最小 Parquet (3 行, 随便字段, 仅验证 read_parquet 走通)."""
    df = pd.DataFrame({"code": [f"c{i}" for i in range(rows)], "val": list(range(rows))})
    df.to_parquet(path)


# ─── ParquetBaselineLoader (4 tests) ──────────────────────


def test_parquet_baseline_loader_loads_all_three_files(tmp_path: Path):
    """3 文件 (factor/price/benchmark) 齐 → 全加载."""
    years = 5
    _write_parquet(tmp_path / f"factor_data_{years}yr.parquet")
    _write_parquet(tmp_path / f"price_data_{years}yr.parquet")
    _write_parquet(tmp_path / f"benchmark_{years}yr.parquet")

    loader = ParquetBaselineLoader(baseline_dir=tmp_path, years=years)
    factor_df, price_df, bench_df = loader(_fake_config(), date(2020, 1, 1), date(2024, 12, 31))

    assert len(factor_df) == 3
    assert len(price_df) == 3
    assert bench_df is not None
    assert len(bench_df) == 3


def test_parquet_baseline_loader_benchmark_optional(tmp_path: Path):
    """benchmark 缺失 → bench_df=None, 不 raise."""
    years = 5
    _write_parquet(tmp_path / f"factor_data_{years}yr.parquet")
    _write_parquet(tmp_path / f"price_data_{years}yr.parquet")
    # benchmark 文件不创建

    loader = ParquetBaselineLoader(baseline_dir=tmp_path, years=years)
    factor_df, price_df, bench_df = loader(_fake_config(), date(2020, 1, 1), date(2024, 12, 31))

    assert len(factor_df) == 3
    assert len(price_df) == 3
    assert bench_df is None


def test_parquet_baseline_loader_factor_missing_raises(tmp_path: Path):
    """factor_data 缺失 → FileNotFoundError."""
    years = 5
    _write_parquet(tmp_path / f"price_data_{years}yr.parquet")

    loader = ParquetBaselineLoader(baseline_dir=tmp_path, years=years)
    with pytest.raises(FileNotFoundError, match="factor"):
        loader(_fake_config(), date(2020, 1, 1), date(2024, 12, 31))


def test_parquet_baseline_loader_price_missing_raises(tmp_path: Path):
    """price_data 缺失 → FileNotFoundError (factor 在, price 不在)."""
    years = 12
    _write_parquet(tmp_path / f"factor_data_{years}yr.parquet")

    loader = ParquetBaselineLoader(baseline_dir=tmp_path, years=years)
    with pytest.raises(FileNotFoundError, match="price"):
        loader(_fake_config(), date(2014, 1, 1), date(2025, 12, 31))


# ─── BacktestCacheLoader (3 tests) ──────────────────────


def test_backtest_cache_loader_returns_data_when_valid():
    """is_valid=True → cache.load 返 data dict."""
    fake_factor = pd.DataFrame({"code": ["A"], "factor_name": ["bp"], "raw_value": [1.0]})
    fake_price = pd.DataFrame({"code": ["A"], "trade_date": [date(2021, 1, 4)]})
    fake_bench = pd.DataFrame({"trade_date": [date(2021, 1, 4)], "close": [100.0]})

    mock_cache = MagicMock()
    mock_cache.is_valid.return_value = True
    mock_cache.load.return_value = {
        "factor_data": fake_factor,
        "price_data": fake_price,
        "benchmark": fake_bench,
    }

    loader = BacktestCacheLoader()
    # Patch module-level `_BacktestDataCache` alias (PR C1 review P1-a: patch where used).
    with patch("backend.platform.backtest.loaders._BacktestDataCache", return_value=mock_cache):
        factor_df, price_df, bench_df = loader(_fake_config(), date(2021, 1, 1), date(2025, 12, 31))

    assert factor_df is fake_factor
    assert price_df is fake_price
    assert bench_df is fake_bench
    mock_cache.is_valid.assert_called_once_with(date(2021, 1, 1), date(2025, 12, 31))


def test_backtest_cache_loader_raises_when_invalid():
    """is_valid=False → ValueError (提示 build_backtest_cache 重建)."""
    mock_cache = MagicMock()
    mock_cache.is_valid.return_value = False

    loader = BacktestCacheLoader()
    with (
        patch("backend.platform.backtest.loaders._BacktestDataCache", return_value=mock_cache),
        pytest.raises(ValueError, match="BacktestDataCache invalid"),
    ):
        loader(_fake_config(), date(2021, 1, 1), date(2025, 12, 31))


def test_backtest_cache_loader_benchmark_optional():
    """data dict 无 'benchmark' key → bench_df=None (get 默认)."""
    fake_factor = pd.DataFrame({"code": ["A"]})
    fake_price = pd.DataFrame({"code": ["A"]})

    mock_cache = MagicMock()
    mock_cache.is_valid.return_value = True
    mock_cache.load.return_value = {
        "factor_data": fake_factor,
        "price_data": fake_price,
        # 无 'benchmark' key
    }

    loader = BacktestCacheLoader()
    with patch("backend.platform.backtest.loaders._BacktestDataCache", return_value=mock_cache):
        factor_df, price_df, bench_df = loader(_fake_config(), date(2021, 1, 1), date(2025, 12, 31))

    assert bench_df is None
