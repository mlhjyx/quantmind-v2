"""Framework #4 Evaluation Gate — Platform SDK sub-package.

MVP 3.5 batch 1: EvaluationPipeline + EvaluationReport + 7 Gates concrete.
"""
from .gates import (
    G1IcSignificanceGate,
    G2CorrelationFilterGate,
    G3PairedBootstrapGate,
    G4WalkForwardGate,
    G8BhFdrGate,
    G9NoveltyAstGate,
    G10HypothesisGate,
    Gate,
    GateContext,
    GateError,
)
from .interface import (
    EvaluationPipeline,
    GateResult,
    StrategyEvaluator,
)
from .pipeline import (
    EvaluationDecision,
    EvaluationReport,
    PlatformEvaluationPipeline,
)
from .strategy_evaluator import (
    PlatformStrategyEvaluator,
    build_strategy_context,
)
from .strategy_gates import (
    STRATEGY_G1_PVALUE_THRESHOLD,
    STRATEGY_G2_DEFAULT_MAX_DD,
    StrategyG1SharpeGate,
    StrategyG2MaxDrawdownGate,
    StrategyG3RegressionGate,
    default_strategy_pipeline,
)
from .utils import (
    benjamini_hochberg_threshold,
    paired_bootstrap_pvalue,
    t_statistic,
)

__all__ = [
    # Interface (ABC + dataclass)
    "EvaluationPipeline",
    "StrategyEvaluator",
    "GateResult",
    # Pipeline (concrete)
    "PlatformEvaluationPipeline",
    "EvaluationReport",
    "EvaluationDecision",
    # Gate base
    "Gate",
    "GateContext",
    "GateError",
    # Gate concretes (G1-G10, MVP 3.5 batch 1)
    "G1IcSignificanceGate",
    "G2CorrelationFilterGate",
    "G3PairedBootstrapGate",
    "G4WalkForwardGate",
    "G8BhFdrGate",
    "G9NoveltyAstGate",
    "G10HypothesisGate",
    # Strategy Gates (G1' / G2' / G3', MVP 3.5 batch 3)
    "StrategyG1SharpeGate",
    "StrategyG2MaxDrawdownGate",
    "StrategyG3RegressionGate",
    "STRATEGY_G1_PVALUE_THRESHOLD",
    "STRATEGY_G2_DEFAULT_MAX_DD",
    "default_strategy_pipeline",
    # Strategy Evaluator (MVP 3.5 batch 3)
    "PlatformStrategyEvaluator",
    "build_strategy_context",
    # Utils
    "paired_bootstrap_pvalue",
    "t_statistic",
    "benjamini_hochberg_threshold",
]
