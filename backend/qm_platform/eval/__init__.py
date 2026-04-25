"""Framework #4 Evaluation Gate — Platform SDK sub-package."""
from .interface import (
    EvaluationPipeline,
    GateResult,
    StrategyEvaluator,
)

__all__ = [
    "EvaluationPipeline",
    "StrategyEvaluator",
    "GateResult",
]
