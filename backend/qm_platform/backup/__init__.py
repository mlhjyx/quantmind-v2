"""Framework #12 Backup & Disaster Recovery — Platform SDK sub-package.

MVP 4.4 (iter 73+) extends the existing interface (BackupManager / BackupResult /
RestoreResult / DisasterRecoveryRunner) with multi-target orchestration
(BackupTarget / BackupTargetResult / BackupOrchestrator) per
docs/mvp/MVP_4_4_backup_dr.md.
"""

from .config_backup import (
    DEFAULT_CONFIG_TIMEOUT_SECONDS,
    ConfigBackupOrchestrator,
    ConfigBackupSpec,
    default_config_spec,
)
from .db_backup import (
    DEFAULT_PG_DUMP_TIMEOUT_SECONDS,
    DBBackupOrchestrator,
    DBBackupSpec,
    default_db_spec,
)
from .filesystem_backup import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    FilesystemBackupOrchestrator,
    FilesystemBackupSpec,
    default_filesystem_spec,
)
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
from .restore_verification import (
    DEFAULT_RESTORE_TIMEOUT_SECONDS,
    RestoreVerificationOrchestrator,
    RestoreVerificationSpec,
    default_restore_spec,
)
from .rpo_rto import (
    DEFAULT_RPO_HOURS,
    DEFAULT_RTO_HOURS,
    DEFAULT_SUPPRESS_MINUTES,
    RpoRtoSnapshot,
    compute_rpo_rto_snapshot,
    fire_rpo_rto_alert,
    measure_rpo_hours,
)

__all__ = [
    "BackupManager",
    "BackupOrchestrator",
    "BackupResult",
    "BackupTarget",
    "BackupTargetResult",
    "ConfigBackupOrchestrator",
    "ConfigBackupSpec",
    "DBBackupOrchestrator",
    "DBBackupSpec",
    "DEFAULT_CONFIG_TIMEOUT_SECONDS",
    "DEFAULT_PG_DUMP_TIMEOUT_SECONDS",
    "DEFAULT_TAR_TIMEOUT_SECONDS",
    # iter 236 — sediment F401 unused-import fix per MVP 4.4 restore_verification + rpo_rto module additions
    "DEFAULT_RESTORE_TIMEOUT_SECONDS",
    "DEFAULT_RPO_HOURS",
    "DEFAULT_RTO_HOURS",
    "DEFAULT_SUPPRESS_MINUTES",
    "DisasterRecoveryRunner",
    "FilesystemBackupOrchestrator",
    "FilesystemBackupSpec",
    "RestoreResult",
    "RestoreVerificationOrchestrator",
    "RestoreVerificationSpec",
    "RpoRtoSnapshot",
    "all_targets_passed",
    "compute_rpo_rto_snapshot",
    "default_config_spec",
    "default_db_spec",
    "default_filesystem_spec",
    "default_restore_spec",
    "fire_rpo_rto_alert",
    "measure_rpo_hours",
    "targets_in_canonical_order",
    "total_bytes_written",
    "total_duration_ms",
]
