"""Framework #6 Signal & Execution — Platform SDK sub-package."""
from .interface import (
    AuditChain,
    ExecutionAuditTrail,
    OrderRouter,
    SignalPipeline,
)
from .pipeline import (
    COMPOSE_STRATEGY_ID,
    FactorStaleError,
    PlatformSignalPipeline,
    UniverseEmpty,
)

__all__ = [
    "SignalPipeline",
    "OrderRouter",
    "ExecutionAuditTrail",
    "AuditChain",
    # MVP 3.3 batch 1
    "PlatformSignalPipeline",
    "FactorStaleError",
    "UniverseEmpty",
    "COMPOSE_STRATEGY_ID",
]
