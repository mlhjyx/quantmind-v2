"""Framework #8 Config Management — Platform SDK sub-package.

MVP 1.1 (2026-04-18): abstract interfaces (ConfigSchema/Loader/Auditor/FeatureFlag).
MVP 1.2 (2026-04-18): concrete 实现 (Pydantic Schema / YAML+env Loader / Auditor / DB FeatureFlag).
"""
from .auditor import (
    ConfigDriftError,
    ConfigDriftReport,
    PlatformConfigAuditor,
)
from .feature_flag import (
    DBFeatureFlag,
    FlagExpired,
    FlagNotFound,
)
from .interface import (
    ConfigAuditor,
    ConfigLoader,
    ConfigSchema,
    FeatureFlag,
)
from .loader import PlatformConfigLoader
from .schema import (
    BacktestConfigSchema,
    CostConfigSchema,
    DatabaseConfigSchema,
    ExecutionConfigSchema,
    PaperTradingConfigSchema,
    PlatformConfigSchema,
    PMSConfigSchema,
    PMSTier,
    RootConfigSchema,
    SlippageConfigSchema,
    StrategyConfigSchema,
    UniverseConfigSchema,
)

__all__ = [
    # Abstract interfaces (MVP 1.1)
    "ConfigSchema",
    "ConfigLoader",
    "ConfigAuditor",
    "FeatureFlag",
    # Concrete classes (MVP 1.2)
    "PlatformConfigSchema",
    "PlatformConfigLoader",
    "PlatformConfigAuditor",
    "DBFeatureFlag",
    # Pydantic sub-schemas (re-exported for composition)
    "RootConfigSchema",
    "StrategyConfigSchema",
    "ExecutionConfigSchema",
    "SlippageConfigSchema",
    "CostConfigSchema",
    "PMSConfigSchema",
    "PMSTier",
    "UniverseConfigSchema",
    "BacktestConfigSchema",
    "DatabaseConfigSchema",
    "PaperTradingConfigSchema",
    # Errors / data classes
    "ConfigDriftError",
    "ConfigDriftReport",
    "FlagNotFound",
    "FlagExpired",
]
