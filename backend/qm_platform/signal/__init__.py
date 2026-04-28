"""Framework #6 Signal & Execution — Platform SDK sub-package."""
from .audit import (
    AuditMissing,
    OutboxBackedAuditTrail,
    StubExecutionAuditTrail,
)
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
from .router import (
    DEFAULT_LOT_SIZE,
    IdempotencyViolation,
    InsufficientCapital,
    PlatformOrderRouter,
    TurnoverCapExceeded,
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
    # MVP 3.3 batch 2 Step 1
    "PlatformOrderRouter",
    "IdempotencyViolation",
    "InsufficientCapital",
    "TurnoverCapExceeded",
    "DEFAULT_LOT_SIZE",
    # MVP 3.3 batch 3
    "StubExecutionAuditTrail",
    "AuditMissing",
    # MVP 3.4 batch 3
    "OutboxBackedAuditTrail",
]
