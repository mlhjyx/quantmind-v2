"""Framework #5 Backtest — Platform SDK sub-package."""
from backend.platform.backtest.interface import (
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
