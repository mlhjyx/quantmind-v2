"""MVP 4.4 sub-iter 1 (iter 73) — Backup orchestration entry skeleton.

Extends Framework #12 (Backup & Disaster Recovery) with multi-target
orchestrator dataclass + Protocol mirroring MVP 4.3 ci/ 体例.

Coordinates 3 backup targets:
  - DB: pg_dump of TimescaleDB (165GB) + WAL archive
  - FILESYSTEM: parquet cache (43GB) + cache/baseline/* + reports/*
  - CONFIG: .env (encrypted at rest) + configs/*.yaml + config/hooks/*

Platform 严格隔离 sustained (沿用 MVP 4.1/4.2/4.3 体例):
  - 0 import backend.app.* / backend.data.* / backend.engines.*
  - DI via subprocess/shell wrappers (sub-iter 2+ wiring)

Distinct from legacy `backup/interface.py` `BackupResult` — that dataclass
carries `backup_id` + `checksum` + `started_at` for cross-run audit. This
orchestrator-level `BackupTargetResult` mirrors `CIResult` shape (target /
passed / duration_ms / details + numeric bytes_written).

铁律对齐:
  - 24 (MVP ≤ 2 页 spec ✅)
  - 29 (NaN 校验 in restore — sub-iter 5 wiring)
  - 30 (cache consistency in restore — sub-iter 5 wiring)
  - 31 (Engine 纯计算 — orchestrator skeleton stateless)
  - 33 fail-safe (BackupTargetResult.passed=False + details capture vs raise)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class BackupTarget(str, Enum):
    """3 backup targets per MVP_4_4_backup_dr.md §2."""

    DB = "db"
    FILESYSTEM = "filesystem"
    CONFIG = "config"


@dataclass(frozen=True)
class BackupTargetResult:
    """Per-target backup execution result (frozen — 反 silent mutation).

    Attributes:
        target: which BackupTarget executed.
        passed: True iff all checks within target succeeded.
        duration_ms: target wall-time in milliseconds (int).
        bytes_written: total bytes written for this target (informational).
        details: target-specific output dict
            (e.g. {"artifact_path": "...", "checksum": "..."}).
    """

    target: BackupTarget
    passed: bool
    duration_ms: int
    bytes_written: int
    details: dict[str, str] = field(default_factory=dict)


class BackupOrchestrator(Protocol):
    """MVP 4.4 backup orchestration interface (iter 73 stub).

    Implementations (iter 74+):
      - DBBackupOrchestrator (pg_dump wrapper + retention policy)
      - FilesystemBackupOrchestrator (parquet cache + cache/baseline snapshot)
      - ConfigBackupOrchestrator (.env encrypted + configs/*.yaml + hooks)
      - RestoreVerificationOrchestrator (sample restore + integrity check)
    """

    def run_target(self, target: BackupTarget) -> BackupTargetResult:
        """Execute a single backup target and return its BackupTargetResult."""
        ...

    def run_all(self) -> list[BackupTargetResult]:
        """Execute all 3 targets in canonical order; return results list."""
        ...


def all_targets_passed(results: list[BackupTargetResult]) -> bool:
    """Return True iff every BackupTargetResult.passed is True (铁律 31 pure compute).

    Empty list → True (vacuous; caller handles 0-result edge separately).
    """
    return all(r.passed for r in results)


def total_bytes_written(results: list[BackupTargetResult]) -> int:
    """Sum of bytes_written across all results (informational)."""
    return sum(r.bytes_written for r in results)


def total_duration_ms(results: list[BackupTargetResult]) -> int:
    """Sum of duration_ms across all results."""
    return sum(r.duration_ms for r in results)


def targets_in_canonical_order() -> list[BackupTarget]:
    """Canonical execution order: db → filesystem → config.

    DB first (largest + most operationally critical); filesystem second
    (factor cache could be recomputed but slow); config last (smallest, but
    semantically distinct — drift detection target).
    """
    return [BackupTarget.DB, BackupTarget.FILESYSTEM, BackupTarget.CONFIG]


__all__ = [
    "BackupOrchestrator",
    "BackupTarget",
    "BackupTargetResult",
    "all_targets_passed",
    "targets_in_canonical_order",
    "total_bytes_written",
    "total_duration_ms",
]
