"""Framework #12 Backup & Disaster Recovery — Platform SDK sub-package.

MVP 4.4 (iter 73+) extends the existing interface (BackupManager / BackupResult /
RestoreResult / DisasterRecoveryRunner) with multi-target orchestration
(BackupTarget / BackupTargetResult / BackupOrchestrator) per
docs/mvp/MVP_4_4_backup_dr.md.
"""

from .interface import (
    BackupManager,
    BackupResult,
    DisasterRecoveryRunner,
    RestoreResult,
)
from .orchestrator import (
    BackupOrchestrator,
    BackupTarget,
    BackupTargetResult,
    all_targets_passed,
    targets_in_canonical_order,
    total_bytes_written,
    total_duration_ms,
)

__all__ = [
    "BackupManager",
    "BackupOrchestrator",
    "BackupResult",
    "BackupTarget",
    "BackupTargetResult",
    "DisasterRecoveryRunner",
    "RestoreResult",
    "all_targets_passed",
    "targets_in_canonical_order",
    "total_bytes_written",
    "total_duration_ms",
]
