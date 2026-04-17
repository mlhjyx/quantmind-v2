"""QuantMind Core Platform (QCP) SDK — 12 Frameworks 统一导出.

Applications (PT / GP / Research / AI 闭环 / Forex) 必须通过本 SDK 消费 Platform 能力.
禁止 Application 跨 Framework import / 裸访问 Infrastructure.

组织:
  - Framework #1 Data         → backend.platform.data
  - Framework #2 Factor       → backend.platform.factor
  - Framework #3 Strategy     → backend.platform.strategy
  - Framework #4 Eval         → backend.platform.eval
  - Framework #5 Backtest     → backend.platform.backtest
  - Framework #6 Signal/Exec  → backend.platform.signal
  - Framework #7 Observability→ backend.platform.observability
  - Framework #8 Config       → backend.platform.config
  - Framework #9 CI/Test      → backend.platform.ci
  - Framework #10 Knowledge   → backend.platform.knowledge
  - Framework #11 Resource    → backend.platform.resource
  - Framework #12 Backup & DR → backend.platform.backup

详见 docs/QUANTMIND_PLATFORM_BLUEPRINT.md Part 2.

实施状态: v1.0 骨架 (MVP 1.1, 2026-04-18), 所有 interface 抛 NotImplementedError.
"""
from ._types import (
    BacktestMode,
    Order,
    Priority,
    ResourceProfile,
    Severity,
    Signal,
    Verdict,
)
from .backtest.interface import (
    BacktestConfig,
    BacktestRegistry,
    BacktestResult,
    BacktestRunner,
    BatchBacktestExecutor,
)
from .backup.interface import (
    BackupManager,
    BackupResult,
    DisasterRecoveryRunner,
    RestoreResult,
)
from .ci.interface import (
    CoverageGate,
    SmokeTestSuite,
    TestRunner,
    TestSummary,
)
from .config.interface import (
    ConfigAuditor,
    ConfigLoader,
    ConfigSchema,
    FeatureFlag,
)
from .data.interface import (
    DataAccessLayer,
    DataContract,
    DataSource,
    FactorCacheProtocol,
    ValidationResult,
)
from .eval.interface import (
    EvaluationPipeline,
    GateResult,
    StrategyEvaluator,
)
from .factor.interface import (
    FactorLifecycleMonitor,
    FactorMeta,
    FactorOnboardingPipeline,
    FactorRegistry,
    FactorSpec,
    FactorStatus,
    OnboardResult,
    TransitionDecision,
)
from .knowledge.interface import (
    ADRRecord,
    ADRRegistry,
    ExperimentRecord,
    ExperimentRegistry,
    FailedDirectionDB,
    FailedDirectionRecord,
)
from .observability.interface import (
    Alert,
    AlertRouter,
    EventBus,
    Metric,
    MetricExporter,
)
from .resource.interface import (
    AdmissionController,
    AdmissionResult,
    BudgetGuard,
    ResourceManager,
    ResourceSnapshot,
    requires_resources,
)
from .signal.interface import (
    AuditChain,
    ExecutionAuditTrail,
    OrderRouter,
    SignalPipeline,
)
from .strategy.interface import (
    CapitalAllocator,
    RebalanceFreq,
    Strategy,
    StrategyContext,
    StrategyRegistry,
    StrategyStatus,
)

__all__ = [
    # _types (shared)
    "Signal",
    "Order",
    "Verdict",
    "BacktestMode",
    "Severity",
    "ResourceProfile",
    "Priority",
    # Framework #1 Data
    "DataSource",
    "DataContract",
    "DataAccessLayer",
    "FactorCacheProtocol",
    "ValidationResult",
    # Framework #2 Factor
    "FactorRegistry",
    "FactorOnboardingPipeline",
    "FactorLifecycleMonitor",
    "FactorSpec",
    "FactorMeta",
    "FactorStatus",
    "OnboardResult",
    "TransitionDecision",
    # Framework #3 Strategy
    "Strategy",
    "StrategyRegistry",
    "CapitalAllocator",
    "RebalanceFreq",
    "StrategyStatus",
    "StrategyContext",
    # Framework #4 Eval
    "EvaluationPipeline",
    "StrategyEvaluator",
    "GateResult",
    # Framework #5 Backtest
    "BacktestRunner",
    "BacktestRegistry",
    "BatchBacktestExecutor",
    "BacktestConfig",
    "BacktestResult",
    # Framework #6 Signal/Exec
    "SignalPipeline",
    "OrderRouter",
    "ExecutionAuditTrail",
    "AuditChain",
    # Framework #7 Observability
    "MetricExporter",
    "AlertRouter",
    "EventBus",
    "Metric",
    "Alert",
    # Framework #8 Config
    "ConfigSchema",
    "ConfigLoader",
    "ConfigAuditor",
    "FeatureFlag",
    # Framework #9 CI/Test
    "TestRunner",
    "CoverageGate",
    "SmokeTestSuite",
    "TestSummary",
    # Framework #10 Knowledge
    "ExperimentRegistry",
    "FailedDirectionDB",
    "ADRRegistry",
    "ExperimentRecord",
    "FailedDirectionRecord",
    "ADRRecord",
    # Framework #11 Resource
    "ResourceManager",
    "AdmissionController",
    "BudgetGuard",
    "AdmissionResult",
    "ResourceSnapshot",
    "requires_resources",
    # Framework #12 Backup & DR
    "BackupManager",
    "DisasterRecoveryRunner",
    "BackupResult",
    "RestoreResult",
]
