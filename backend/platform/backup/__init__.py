"""Framework #12 Backup & Disaster Recovery — Platform SDK sub-package."""
from .interface import (
    BackupManager,
    BackupResult,
    DisasterRecoveryRunner,
    RestoreResult,
)

__all__ = [
    "BackupManager",
    "DisasterRecoveryRunner",
    "BackupResult",
    "RestoreResult",
]
