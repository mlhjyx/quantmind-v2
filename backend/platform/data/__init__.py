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
from .interface import (
    DataAccessLayer,
    DataContract,
    DataSource,
    FactorCacheProtocol,
    ValidationResult,
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
]
