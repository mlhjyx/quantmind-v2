"""Framework #4 Evaluation Gate — Platform SDK sub-package."""
from backend.platform.eval.interface import (
    EvaluationPipeline,
    GateResult,
    StrategyEvaluator,
)

__all__ = [
    "EvaluationPipeline",
    "StrategyEvaluator",
    "GateResult",
]
