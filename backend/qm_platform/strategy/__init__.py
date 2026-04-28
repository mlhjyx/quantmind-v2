"""Framework #3 Strategy — Platform SDK sub-package."""
from .allocator import EqualWeightAllocator
from .interface import (
    CapitalAllocator,
    RebalanceFreq,
    Strategy,
    StrategyContext,
    StrategyRegistry,
    StrategyStatus,
)
from .registry import (
    DEFAULT_LIVE_EVAL_FRESHNESS_DAYS,
    DBStrategyRegistry,
    EvaluationRequired,
    StrategyNotFound,
    StrategyRegistryIntegrityError,
)

__all__ = [
    "Strategy",
    "StrategyRegistry",
    "CapitalAllocator",
    "RebalanceFreq",
    "StrategyStatus",
    "StrategyContext",
    # MVP 3.2 批 1 concretes:
    "DBStrategyRegistry",
    "EqualWeightAllocator",
    "StrategyNotFound",
    "StrategyRegistryIntegrityError",
    # MVP 3.5.1 LIVE 守门:
    "EvaluationRequired",
    "DEFAULT_LIVE_EVAL_FRESHNESS_DAYS",
]
