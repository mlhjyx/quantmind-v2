"""QuantMind Core Platform (QCP) SDK — lightweight public exports.

Applications (PT / GP / Research / AI closure / Forex) consume Platform
capabilities through this SDK. The package initializer must stay lightweight:
CI imports `backend.qm_platform.ci.*` on minimal runners that do not install
data-science dependencies, so public SDK symbols are resolved lazily.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    # _types (shared)
    "Signal": "backend.qm_platform._types",
    "Order": "backend.qm_platform._types",
    "Verdict": "backend.qm_platform._types",
    "BacktestMode": "backend.qm_platform._types",
    "Severity": "backend.qm_platform._types",
    "ResourceProfile": "backend.qm_platform._types",
    "Priority": "backend.qm_platform._types",
    # Framework #1 Data
    "DataSource": "backend.qm_platform.data.interface",
    "DataContract": "backend.qm_platform.data.interface",
    "DataAccessLayer": "backend.qm_platform.data.interface",
    "FactorCacheProtocol": "backend.qm_platform.data.interface",
    "ValidationResult": "backend.qm_platform.data.interface",
    # Framework #2 Factor
    "FactorRegistry": "backend.qm_platform.factor.interface",
    "FactorOnboardingPipeline": "backend.qm_platform.factor.interface",
    "FactorLifecycleMonitor": "backend.qm_platform.factor.interface",
    "FactorSpec": "backend.qm_platform.factor.interface",
    "FactorMeta": "backend.qm_platform.factor.interface",
    "FactorStatus": "backend.qm_platform.factor.interface",
    "OnboardResult": "backend.qm_platform.factor.interface",
    "TransitionDecision": "backend.qm_platform.factor.interface",
    # Framework #3 Strategy
    "Strategy": "backend.qm_platform.strategy.interface",
    "StrategyRegistry": "backend.qm_platform.strategy.interface",
    "CapitalAllocator": "backend.qm_platform.strategy.interface",
    "RebalanceFreq": "backend.qm_platform.strategy.interface",
    "StrategyStatus": "backend.qm_platform.strategy.interface",
    "StrategyContext": "backend.qm_platform.strategy.interface",
    "DBStrategyRegistry": "backend.qm_platform.strategy.registry",
    "EqualWeightAllocator": "backend.qm_platform.strategy.allocator",
    "StrategyNotFound": "backend.qm_platform.strategy.registry",
    "StrategyRegistryIntegrityError": "backend.qm_platform.strategy.registry",
    # Framework #4 Eval
    "EvaluationPipeline": "backend.qm_platform.eval.interface",
    "StrategyEvaluator": "backend.qm_platform.eval.interface",
    "GateResult": "backend.qm_platform.eval.interface",
    # Framework #5 Backtest
    "BacktestRunner": "backend.qm_platform.backtest.interface",
    "BacktestRegistry": "backend.qm_platform.backtest.interface",
    "BatchBacktestExecutor": "backend.qm_platform.backtest.interface",
    "BacktestConfig": "backend.qm_platform.backtest.interface",
    "BacktestResult": "backend.qm_platform.backtest.interface",
    # Framework #6 Signal/Exec
    "SignalPipeline": "backend.qm_platform.signal.interface",
    "OrderRouter": "backend.qm_platform.signal.interface",
    "ExecutionAuditTrail": "backend.qm_platform.signal.interface",
    "AuditChain": "backend.qm_platform.signal.interface",
    # Framework #7 Observability
    "MetricExporter": "backend.qm_platform.observability.interface",
    "AlertRouter": "backend.qm_platform.observability.interface",
    "EventBus": "backend.qm_platform.observability.interface",
    "Metric": "backend.qm_platform.observability.interface",
    "Alert": "backend.qm_platform.observability.interface",
    # Framework #8 Config
    "ConfigSchema": "backend.qm_platform.config.interface",
    "ConfigLoader": "backend.qm_platform.config.interface",
    "ConfigAuditor": "backend.qm_platform.config.interface",
    "FeatureFlag": "backend.qm_platform.config.interface",
    # Framework #9 CI/Test
    "TestRunner": "backend.qm_platform.ci.interface",
    "CoverageGate": "backend.qm_platform.ci.interface",
    "SmokeTestSuite": "backend.qm_platform.ci.interface",
    "TestSummary": "backend.qm_platform.ci.interface",
    # Framework #10 Knowledge
    "ExperimentRegistry": "backend.qm_platform.knowledge.interface",
    "FailedDirectionDB": "backend.qm_platform.knowledge.interface",
    "ADRRegistry": "backend.qm_platform.knowledge.interface",
    "ExperimentRecord": "backend.qm_platform.knowledge.interface",
    "FailedDirectionRecord": "backend.qm_platform.knowledge.interface",
    "ADRRecord": "backend.qm_platform.knowledge.interface",
    # Framework #11 Resource
    "ResourceManager": "backend.qm_platform.resource.interface",
    "AdmissionController": "backend.qm_platform.resource.interface",
    "BudgetGuard": "backend.qm_platform.resource.interface",
    "AdmissionResult": "backend.qm_platform.resource.interface",
    "ResourceSnapshot": "backend.qm_platform.resource.interface",
    "requires_resources": "backend.qm_platform.resource.interface",
    # Framework #12 Backup & DR
    "BackupManager": "backend.qm_platform.backup.interface",
    "DisasterRecoveryRunner": "backend.qm_platform.backup.interface",
    "BackupResult": "backend.qm_platform.backup.interface",
    "RestoreResult": "backend.qm_platform.backup.interface",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public SDK exports lazily to keep package import dependency-light."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
