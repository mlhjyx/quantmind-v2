"""Framework #5 Backtest — Platform SDK sub-package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .interface import (
    BacktestConfig,
    BacktestRegistry,
    BacktestResult,
    BacktestRunner,
    BatchBacktestExecutor,
    PMSConfig,
    SlippageConfig,
    UniverseFilter,
)

_LAZY_EXPORTS = {
    "BacktestCacheLoader": "backend.qm_platform.backtest.loaders",
    "ParquetBaselineLoader": "backend.qm_platform.backtest.loaders",
    "InMemoryBacktestRegistry": "backend.qm_platform.backtest.memory_registry",
}

__all__ = [
    "BacktestCacheLoader",
    "BacktestConfig",
    "BacktestRegistry",
    "BacktestResult",
    "BacktestRunner",
    "BatchBacktestExecutor",
    "InMemoryBacktestRegistry",
    "ParquetBaselineLoader",
    "PMSConfig",
    "SlippageConfig",
    "UniverseFilter",
]


def __getattr__(name: str) -> Any:
    """Resolve concrete helpers lazily so interface imports avoid pandas."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
