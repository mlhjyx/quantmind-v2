"""Framework #5 Backtest — Platform SDK sub-package."""

from .interface import (
    BacktestConfig,
    BacktestRegistry,
    BacktestResult,
    BacktestRunner,
    BatchBacktestExecutor,
)
from .loaders import BacktestCacheLoader, ParquetBaselineLoader
from .memory_registry import InMemoryBacktestRegistry

__all__ = [
    "BacktestCacheLoader",
    "BacktestConfig",
    "BacktestRegistry",
    "BacktestResult",
    "BacktestRunner",
    "BatchBacktestExecutor",
    "InMemoryBacktestRegistry",
    "ParquetBaselineLoader",
]
