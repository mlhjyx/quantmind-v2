"""MVP 4.4 sub-iter 5+6 (iter 75 batch) — RestoreVerification + RpoRto tests.

Batched test module covering both restore verification orchestrator and
RPO/RTO measurement + alert (sustained MVP 4.2 fire_residual_alert pattern).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.qm_platform.backup.orchestrator import BackupTarget
from backend.qm_platform.backup.restore_verification import (
    DEFAULT_RESTORE_TIMEOUT_SECONDS,
    RestoreVerificationOrchestrator,
    RestoreVerificationSpec,
    default_restore_spec,
)
from backend.qm_platform.backup.rpo_rto import (
    DEFAULT_RPO_HOURS,
    DEFAULT_RTO_HOURS,
    DEFAULT_SUPPRESS_MINUTES,
    RpoRtoSnapshot,
    compute_rpo_rto_snapshot,
    fire_rpo_rto_alert,
    measure_rpo_hours,
)


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ────────────────────────────────────────────────────────────
# RestoreVerificationOrchestrator
# ────────────────────────────────────────────────────────────


def test_restore_default_spec():
    spec = default_restore_spec()
    assert spec.sample_database == "quantmind_restore_check"
    assert len(spec.integrity_checks) >= 1


def test_restore_default_timeout():
    assert DEFAULT_RESTORE_TIMEOUT_SECONDS == 1800


def test_restore_spec_frozen():
    import dataclasses

    s = RestoreVerificationSpec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.sample_database = "x"  # type: ignore[misc]


def test_restore_no_artifact_found():
    """No artifact returned by finder → passed=False with NO_ARTIFACT_FOUND."""
    finder = MagicMock(return_value=None)
    orch = RestoreVerificationOrchestrator(runner=MagicMock(), artifact_finder=finder)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert result.details["error"] == "NO_ARTIFACT_FOUND"


def test_restore_pg_restore_list_success(tmp_path):
    """pg_restore --list rc=0 → passed=True + toc_entries captured."""
    artifact = tmp_path / "x.dump"
    artifact.write_bytes(b"DUMP")
    runner = MagicMock(return_value=_mk_completed(returncode=0, stdout="entry1\nentry2\nentry3\n"))
    orch = RestoreVerificationOrchestrator(runner=runner, artifact_finder=lambda _d: artifact)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is True
    assert result.details["toc_entries"] == "3"


def test_restore_pg_restore_list_fail(tmp_path):
    artifact = tmp_path / "bad.dump"
    artifact.write_bytes(b"BAD")
    runner = MagicMock(return_value=_mk_completed(returncode=1, stderr="pg_restore: corrupted"))
    orch = RestoreVerificationOrchestrator(runner=runner, artifact_finder=lambda _d: artifact)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "corrupted" in result.details.get("err_tail", "")


def test_restore_timeout(tmp_path):
    artifact = tmp_path / "x.dump"
    artifact.write_bytes(b"DUMP")
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["pg_restore"], timeout=1800))
    orch = RestoreVerificationOrchestrator(runner=runner, artifact_finder=lambda _d: artifact)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "TIMEOUT" in result.details["pg_restore"]


def test_restore_oserror(tmp_path):
    artifact = tmp_path / "x.dump"
    artifact.write_bytes(b"DUMP")
    runner = MagicMock(side_effect=FileNotFoundError("pg_restore"))
    orch = RestoreVerificationOrchestrator(runner=runner, artifact_finder=lambda _d: artifact)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "OSError" in result.details["pg_restore"]


def test_restore_non_db_target_skipped():
    orch = RestoreVerificationOrchestrator(runner=MagicMock())
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is True
    assert result.details == {"skipped": "filesystem"}


def test_restore_run_all_single_element(tmp_path):
    artifact = tmp_path / "x.dump"
    artifact.write_bytes(b"DUMP")
    orch = RestoreVerificationOrchestrator(
        runner=MagicMock(return_value=_mk_completed(returncode=0)),
        artifact_finder=lambda _d: artifact,
    )
    results = orch.run_all()
    assert len(results) == 1


# ────────────────────────────────────────────────────────────
# RpoRto measurement + alert
# ────────────────────────────────────────────────────────────


def test_rpo_rto_default_thresholds():
    assert DEFAULT_RPO_HOURS == 24.0
    assert DEFAULT_RTO_HOURS == 4.0
    assert DEFAULT_SUPPRESS_MINUTES == 60


def test_rpo_rto_snapshot_frozen():
    import dataclasses

    s = RpoRtoSnapshot(
        rpo_hours_actual=1.0,
        rto_hours_actual=0.5,
        rpo_breached=False,
        rto_breached=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.rpo_breached = True  # type: ignore[misc]


def test_measure_rpo_missing_dir_returns_inf():
    """Non-existent directory → INF."""
    assert measure_rpo_hours(Path("/nonexistent-xyz-123")) == float("inf")


def test_measure_rpo_empty_dir_returns_inf(tmp_path):
    """Empty directory → INF."""
    assert measure_rpo_hours(tmp_path) == float("inf")


def test_measure_rpo_recent_artifact_returns_small_hours(tmp_path):
    """Recent artifact (just-created) → near-zero hours."""
    artifact = tmp_path / "recent.dump"
    artifact.write_bytes(b"x")
    hours = measure_rpo_hours(tmp_path)
    assert 0.0 <= hours < 1.0


def test_measure_rpo_old_artifact_returns_large_hours(tmp_path):
    """Old artifact (mtime 48h ago) → ~48 hours."""
    artifact = tmp_path / "old.dump"
    artifact.write_bytes(b"x")
    old_ts = time.time() - 48 * 3600
    import os

    os.utime(artifact, (old_ts, old_ts))
    hours = measure_rpo_hours(tmp_path)
    assert 47.0 < hours < 49.0


def test_compute_snapshot_no_breach(tmp_path):
    """Fresh artifact + fast restore → no breach."""
    (tmp_path / "x.dump").write_bytes(b"x")
    snapshot = compute_rpo_rto_snapshot(
        artifact_dir=tmp_path,
        last_restore_duration_seconds=600,  # 10min
    )
    assert snapshot.rpo_breached is False
    assert snapshot.rto_breached is False


def test_compute_snapshot_rpo_breach(tmp_path):
    """No artifacts → rpo=INF → breach."""
    snapshot = compute_rpo_rto_snapshot(
        artifact_dir=tmp_path / "empty",
        last_restore_duration_seconds=60,
    )
    assert snapshot.rpo_breached is True
    assert snapshot.rpo_hours_actual == float("inf")


def test_compute_snapshot_rto_breach(tmp_path):
    """Restore took 5h → exceeds 4h RTO."""
    (tmp_path / "x.dump").write_bytes(b"x")
    snapshot = compute_rpo_rto_snapshot(
        artifact_dir=tmp_path,
        last_restore_duration_seconds=5 * 3600,
    )
    assert snapshot.rto_breached is True
    assert snapshot.rto_hours_actual == pytest.approx(5.0)


def test_fire_alert_no_breach_no_dispatch():
    snapshot = RpoRtoSnapshot(
        rpo_hours_actual=1.0,
        rto_hours_actual=0.5,
        rpo_breached=False,
        rto_breached=False,
    )
    with patch("backend.qm_platform.backup.rpo_rto._fire_via_platform_sdk") as mock_sdk:
        fired = fire_rpo_rto_alert(snapshot)
    assert fired is False
    mock_sdk.assert_not_called()


def test_fire_alert_rpo_breach_dispatches():
    snapshot = RpoRtoSnapshot(
        rpo_hours_actual=48.0,
        rto_hours_actual=0.5,
        rpo_breached=True,
        rto_breached=False,
    )
    with patch("backend.qm_platform.backup.rpo_rto._fire_via_platform_sdk") as mock_sdk:
        fired = fire_rpo_rto_alert(snapshot)
    assert fired is True
    mock_sdk.assert_called_once()


def test_fire_alert_swallows_generic_exception():
    """Generic exception → fail-soft tier-2."""
    snapshot = RpoRtoSnapshot(
        rpo_hours_actual=48.0,
        rto_hours_actual=0.5,
        rpo_breached=True,
        rto_breached=False,
    )
    with patch(
        "backend.qm_platform.backup.rpo_rto._fire_via_platform_sdk",
        side_effect=RuntimeError("boom"),
    ):
        fired = fire_rpo_rto_alert(snapshot)
    assert fired is False


def test_fire_alert_swallows_alert_dispatch_error():
    """AlertDispatchError → fail-soft tier-1."""
    fake_err = type("AlertDispatchError", (Exception,), {})

    snapshot = RpoRtoSnapshot(
        rpo_hours_actual=48.0,
        rto_hours_actual=0.5,
        rpo_breached=True,
        rto_breached=False,
    )
    import sys

    with (
        patch.dict(
            sys.modules,
            {"qm_platform.observability": MagicMock(AlertDispatchError=fake_err)},
        ),
        patch(
            "backend.qm_platform.backup.rpo_rto._fire_via_platform_sdk",
            side_effect=fake_err("sink fail"),
        ),
    ):
        fired = fire_rpo_rto_alert(snapshot)
    assert fired is False
