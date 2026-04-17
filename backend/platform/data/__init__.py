"""Framework #1 Data — Platform SDK sub-package.

MVP 1.1 (2026-04-18): abstract interfaces (DataSource/DataContract/DataAccessLayer/FactorCacheProtocol).
MVP 1.2a (2026-04-18): concrete `PlatformDataAccessLayer` read-only (4 方法).
"""
from .access_layer import (
    DALError,
    PlatformDataAccessLayer,
    UnsupportedColumn,
    UnsupportedField,
)
from .base_source import BaseDataSource, ContractViolation
from .interface import (
    DataAccessLayer,
    DataContract,
    DataSource,
    FactorCacheProtocol,
    ValidationResult,
)
from .sources import (
    DAILY_BASIC_DATA_CONTRACT,
    KLINES_DAILY_DATA_CONTRACT,
    MINUTE_BARS_DATA_CONTRACT,
    MONEYFLOW_DATA_CONTRACT,
    QMT_ASSETS_CONTRACT,
    QMT_POSITIONS_CONTRACT,
    QMT_TICKS_CONTRACT,
    BaostockDataSource,
    QMTDataSource,
    TushareDataSource,
)

__all__ = [
    # Abstract interfaces (MVP 1.1)
    "DataSource",
    "DataContract",
    "DataAccessLayer",
    "FactorCacheProtocol",
    "ValidationResult",
    # Concrete (MVP 1.2a)
    "PlatformDataAccessLayer",
    "DALError",
    "UnsupportedColumn",
    "UnsupportedField",
    # MVP 2.1a (Template base)
    "BaseDataSource",
    "ContractViolation",
    # MVP 2.1b (concrete fetchers, Sub-commit 1)
    "BaostockDataSource",
    "MINUTE_BARS_DATA_CONTRACT",
    # MVP 2.1b (concrete fetchers, Sub-commit 2)
    "QMTDataSource",
    "QMT_POSITIONS_CONTRACT",
    "QMT_ASSETS_CONTRACT",
    "QMT_TICKS_CONTRACT",
    # MVP 2.1b (concrete fetchers, Sub-commit 3)
    "TushareDataSource",
    "KLINES_DAILY_DATA_CONTRACT",
    "DAILY_BASIC_DATA_CONTRACT",
    "MONEYFLOW_DATA_CONTRACT",
]
