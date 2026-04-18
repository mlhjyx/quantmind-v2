"""Framework #5 Backtest — Platform SDK sub-package."""

from .interface import (
    BacktestConfig,
    BacktestRegistry,
    BacktestResult,
    BacktestRunner,
    BatchBacktestExecutor,
)

__all__ = [
    "BacktestRunner",
    "BacktestRegistry",
    "BatchBacktestExecutor",
    "BacktestConfig",
    "BacktestResult",
]
