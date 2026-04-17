"""Framework #1 Data — Platform SDK sub-package.

Re-exports public interfaces. See `interface.py` for contracts.
"""
from backend.platform.data.interface import (
    DataAccessLayer,
    DataContract,
    DataSource,
    FactorCacheProtocol,
    ValidationResult,
)

__all__ = [
    "DataSource",
    "DataContract",
    "DataAccessLayer",
    "FactorCacheProtocol",
    "ValidationResult",
]
