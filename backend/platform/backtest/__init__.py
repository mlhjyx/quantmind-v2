"""Framework #5 Backtest — Platform SDK sub-package."""

from .interface import (
    BacktestConfig,
    BacktestRegistry,
    BacktestResult,
    BacktestRunner,
    BatchBacktestExecutor,
)
from .loaders import BacktestCacheLoader, ParquetBaselineLoader

__all__ = [
    "BacktestCacheLoader",
    "BacktestConfig",
    "BacktestRegistry",
    "BacktestResult",
    "BacktestRunner",
    "BatchBacktestExecutor",
    "ParquetBaselineLoader",
]
