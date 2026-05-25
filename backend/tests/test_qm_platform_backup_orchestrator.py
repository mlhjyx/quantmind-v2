"""MVP 4.4 sub-iter 1 (iter 73) — qm_platform.backup.orchestrator shape tests.

Covers BackupTarget enum + BackupTargetResult frozen dataclass +
BackupOrchestrator Protocol + 4 helper functions (all_targets_passed /
total_bytes_written / total_duration_ms / targets_in_canonical_order).

Sub-iter 2+ adds implementation tests (DBBackupOrchestrator etc).
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.qm_platform.backup.orchestrator import (
    BackupOrchestrator,
    BackupTarget,
    BackupTargetResult,
    all_targets_passed,
    targets_in_canonical_order,
    total_bytes_written,
    total_duration_ms,
)


def test_backup_target_enum_has_three_targets():
    """BackupTarget enum exposes exactly 3 targets per spec §2."""
    values = {t.value for t in BackupTarget}
    assert values == {"db", "filesystem", "config"}


def test_backup_target_str_inheritance():
    """BackupTarget inherits from str for ergonomic comparison + serialization."""
    assert BackupTarget.DB == "db"
    assert BackupTarget.FILESYSTEM == "filesystem"
    assert BackupTarget.CONFIG == "config"


def test_backup_target_result_minimal_construction():
    """BackupTargetResult constructs with required fields + details default empty."""
    r = BackupTargetResult(
        target=BackupTarget.DB, passed=True, duration_ms=12345, bytes_written=1024
    )
    assert r.target == BackupTarget.DB
    assert r.passed is True
    assert r.duration_ms == 12345
    assert r.bytes_written == 1024
    assert r.details == {}


def test_backup_target_result_with_details():
    """BackupTargetResult details dict captures target-specific output."""
    r = BackupTargetResult(
        target=BackupTarget.FILESYSTEM,
        passed=False,
        duration_ms=60000,
        bytes_written=0,
        details={"err": "disk full", "artifact_path": "/tmp/x"},
    )
    assert r.details["err"] == "disk full"
    assert r.passed is False


def test_backup_target_result_frozen():
    """BackupTargetResult frozen — 反 silent mutation."""
    r = BackupTargetResult(target=BackupTarget.CONFIG, passed=True, duration_ms=0, bytes_written=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.passed = False  # type: ignore[misc]


def test_backup_target_result_details_independent_per_instance():
    """default_factory=dict ensures details dict not shared across instances."""
    r1 = BackupTargetResult(target=BackupTarget.DB, passed=True, duration_ms=0, bytes_written=0)
    r2 = BackupTargetResult(target=BackupTarget.DB, passed=True, duration_ms=0, bytes_written=0)
    assert r1.details is not r2.details


def test_all_targets_passed_all_true():
    results = [
        BackupTargetResult(
            target=BackupTarget.DB, passed=True, duration_ms=100, bytes_written=1000
        ),
        BackupTargetResult(
            target=BackupTarget.FILESYSTEM,
            passed=True,
            duration_ms=200,
            bytes_written=2000,
        ),
    ]
    assert all_targets_passed(results) is True


def test_all_targets_passed_one_false():
    results = [
        BackupTargetResult(
            target=BackupTarget.DB, passed=True, duration_ms=100, bytes_written=1000
        ),
        BackupTargetResult(
            target=BackupTarget.FILESYSTEM,
            passed=False,
            duration_ms=200,
            bytes_written=0,
        ),
        BackupTargetResult(
            target=BackupTarget.CONFIG, passed=True, duration_ms=50, bytes_written=500
        ),
    ]
    assert all_targets_passed(results) is False


def test_all_targets_passed_empty_list_vacuous_true():
    assert all_targets_passed([]) is True


def test_total_bytes_written_sum():
    results = [
        BackupTargetResult(target=BackupTarget.DB, passed=True, duration_ms=0, bytes_written=1000),
        BackupTargetResult(
            target=BackupTarget.FILESYSTEM,
            passed=True,
            duration_ms=0,
            bytes_written=2500,
        ),
        BackupTargetResult(
            target=BackupTarget.CONFIG, passed=False, duration_ms=0, bytes_written=0
        ),
    ]
    assert total_bytes_written(results) == 3500


def test_total_bytes_written_empty_zero():
    assert total_bytes_written([]) == 0


def test_total_duration_ms_sum():
    results = [
        BackupTargetResult(target=BackupTarget.DB, passed=True, duration_ms=100, bytes_written=0),
        BackupTargetResult(
            target=BackupTarget.FILESYSTEM,
            passed=True,
            duration_ms=250,
            bytes_written=0,
        ),
    ]
    assert total_duration_ms(results) == 350


def test_total_duration_ms_empty_zero():
    assert total_duration_ms([]) == 0


def test_targets_in_canonical_order():
    """Canonical order: db → filesystem → config."""
    assert targets_in_canonical_order() == [
        BackupTarget.DB,
        BackupTarget.FILESYSTEM,
        BackupTarget.CONFIG,
    ]


def test_backup_orchestrator_protocol_structural_typing():
    """Any class with run_target + run_all matches BackupOrchestrator structurally."""

    class StubBackup:
        def run_target(self, target: BackupTarget) -> BackupTargetResult:
            return BackupTargetResult(target=target, passed=True, duration_ms=0, bytes_written=42)

        def run_all(self) -> list[BackupTargetResult]:
            return [self.run_target(t) for t in targets_in_canonical_order()]

    o: BackupOrchestrator = StubBackup()
    result = o.run_target(BackupTarget.DB)
    assert isinstance(result, BackupTargetResult)
    assert result.bytes_written == 42

    results = o.run_all()
    assert len(results) == 3
    assert all_targets_passed(results) is True
    assert total_bytes_written(results) == 126  # 3 × 42
