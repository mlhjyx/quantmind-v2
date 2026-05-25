"""MVP 4.4 sub-iter 2+3+4 (iter 74 batch) — concrete backup orchestrator tests.

Covers DBBackupOrchestrator + FilesystemBackupOrchestrator + ConfigBackupOrchestrator
in one batched test module (3 orchestrators × ~9 tests each = 27 tests).

沿用 ci/precommit pattern: SubprocessRunner DI + skip non-matching target +
fail-soft for TimeoutExpired/OSError + retention sweep DI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.backup.config_backup import (
    DEFAULT_CONFIG_TIMEOUT_SECONDS,
    ConfigBackupOrchestrator,
    ConfigBackupSpec,
    default_config_spec,
)
from backend.qm_platform.backup.db_backup import (
    DEFAULT_PG_DUMP_TIMEOUT_SECONDS,
    DBBackupOrchestrator,
    DBBackupSpec,
    default_db_spec,
)
from backend.qm_platform.backup.filesystem_backup import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    FilesystemBackupOrchestrator,
    FilesystemBackupSpec,
    default_filesystem_spec,
)
from backend.qm_platform.backup.orchestrator import BackupTarget


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ────────────────────────────────────────────────────────────
# DBBackupOrchestrator (pg_dump wrapper)
# ────────────────────────────────────────────────────────────


def test_db_default_spec():
    spec = default_db_spec()
    assert spec.database == "quantmind_v2"
    assert spec.host == "127.0.0.1"
    assert spec.port == 5432
    assert spec.retention_days == 14


def test_db_default_pg_dump_timeout():
    assert DEFAULT_PG_DUMP_TIMEOUT_SECONDS == 3600


def test_db_spec_frozen():
    import dataclasses

    s = DBBackupSpec(database="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.database = "y"  # type: ignore[misc]


def test_db_pg_dump_success(tmp_path):
    """pg_dump rc=0 + artifact present → passed=True, bytes_written>0."""
    spec = DBBackupSpec(database="quantmind_v2", artifact_dir=tmp_path)
    fake_runner = MagicMock(
        side_effect=lambda cmd, _t: (
            # Side effect: create artifact file before returning
            Path(cmd[-1]).write_bytes(b"FAKE_PG_DUMP_BYTES" * 100) or _mk_completed(returncode=0)
        )
    )
    fake_checksum = MagicMock(return_value="abc123sha256")
    orch = DBBackupOrchestrator(spec=spec, runner=fake_runner, checksum_fn=fake_checksum)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is True
    assert result.bytes_written > 0
    assert result.details["pg_dump_rc"] == "0"
    assert result.details["checksum"] == "abc123sha256"
    fake_runner.assert_called_once()


def test_db_pg_dump_fail(tmp_path):
    """pg_dump rc != 0 → passed=False, err_tail captured."""
    spec = DBBackupSpec(database="quantmind_v2", artifact_dir=tmp_path)
    runner = MagicMock(
        return_value=_mk_completed(returncode=1, stderr="pg_dump: connection refused")
    )
    orch = DBBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "connection refused" in result.details.get("err_tail", "")


def test_db_pg_dump_timeout(tmp_path):
    spec = DBBackupSpec(database="quantmind_v2", artifact_dir=tmp_path)
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=3600))
    orch = DBBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "TIMEOUT" in result.details["pg_dump"]


def test_db_oserror(tmp_path):
    spec = DBBackupSpec(database="quantmind_v2", artifact_dir=tmp_path)
    runner = MagicMock(side_effect=FileNotFoundError("pg_dump not on PATH"))
    orch = DBBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is False
    assert "OSError" in result.details["pg_dump"]


def test_db_non_db_target_skipped():
    orch = DBBackupOrchestrator(runner=MagicMock())
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is True
    assert result.details == {"skipped": "filesystem"}


def test_db_retention_sweep_invoked(tmp_path):
    spec = DBBackupSpec(database="quantmind_v2", artifact_dir=tmp_path)
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    sweep = MagicMock(return_value=3)
    orch = DBBackupOrchestrator(spec=spec, runner=runner, sweep_fn=sweep)
    result = orch.run_target(BackupTarget.DB)
    sweep.assert_called_once_with(spec.artifact_dir, 14)
    assert result.details["retention_swept"] == "3"


def test_db_run_all_single_element():
    orch = DBBackupOrchestrator(runner=MagicMock(return_value=_mk_completed(returncode=0)))
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].target == BackupTarget.DB


# ────────────────────────────────────────────────────────────
# FilesystemBackupOrchestrator (tar -czf wrapper)
# ────────────────────────────────────────────────────────────


def test_fs_default_spec():
    spec = default_filesystem_spec()
    assert "cache/baseline" in spec.sources
    assert spec.retention_days == 7


def test_fs_default_tar_timeout():
    assert DEFAULT_TAR_TIMEOUT_SECONDS == 1800


def test_fs_spec_frozen():
    import dataclasses

    s = FilesystemBackupSpec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.retention_days = 999  # type: ignore[misc]


def test_fs_tar_success(tmp_path):
    spec = FilesystemBackupSpec(sources=["dummy"], artifact_dir=tmp_path)

    def runner_with_artifact(cmd, _t):
        artifact = Path(cmd[2])
        artifact.write_bytes(b"FAKE_TAR_BYTES" * 200)
        return _mk_completed(returncode=0)

    runner = MagicMock(side_effect=runner_with_artifact)
    orch = FilesystemBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is True
    assert result.bytes_written > 0


def test_fs_tar_fail(tmp_path):
    spec = FilesystemBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(return_value=_mk_completed(returncode=2, stderr="tar: cannot open"))
    orch = FilesystemBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is False


def test_fs_tar_timeout(tmp_path):
    spec = FilesystemBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["tar"], timeout=1800))
    orch = FilesystemBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is False
    assert "TIMEOUT" in result.details["tar"]


def test_fs_oserror(tmp_path):
    spec = FilesystemBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(side_effect=FileNotFoundError("tar not on PATH"))
    orch = FilesystemBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.FILESYSTEM)
    assert result.passed is False


def test_fs_non_fs_target_skipped():
    orch = FilesystemBackupOrchestrator(runner=MagicMock())
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is True
    assert result.details == {"skipped": "db"}


def test_fs_run_all_single_element():
    orch = FilesystemBackupOrchestrator(runner=MagicMock(return_value=_mk_completed(returncode=0)))
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].target == BackupTarget.FILESYSTEM


def test_fs_retention_sweep(tmp_path):
    spec = FilesystemBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    sweep = MagicMock(return_value=2)
    orch = FilesystemBackupOrchestrator(spec=spec, runner=runner, sweep_fn=sweep)
    result = orch.run_target(BackupTarget.FILESYSTEM)
    sweep.assert_called_once()
    assert result.details["retention_swept"] == "2"


# ────────────────────────────────────────────────────────────
# ConfigBackupOrchestrator (tar -czf with --ignore-failed-read)
# ────────────────────────────────────────────────────────────


def test_config_default_spec():
    spec = default_config_spec()
    assert "backend/.env" in spec.sources
    assert "configs" in spec.sources
    assert spec.retention_days == 30


def test_config_default_timeout():
    assert DEFAULT_CONFIG_TIMEOUT_SECONDS == 60


def test_config_spec_frozen():
    import dataclasses

    s = ConfigBackupSpec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.retention_days = 1  # type: ignore[misc]


def test_config_tar_success(tmp_path):
    spec = ConfigBackupSpec(sources=["x"], artifact_dir=tmp_path)

    def runner_with_artifact(cmd, _t):
        # cmd: ["tar", "--ignore-failed-read", "-czf", artifact_path, *sources]
        artifact = Path(cmd[3])
        artifact.write_bytes(b"CFG" * 50)
        return _mk_completed(returncode=0)

    runner = MagicMock(side_effect=runner_with_artifact)
    orch = ConfigBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.CONFIG)
    assert result.passed is True
    assert result.bytes_written > 0


def test_config_tar_includes_ignore_failed_read_flag(tmp_path):
    """tar cmd must include --ignore-failed-read to survive missing .env."""
    spec = ConfigBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = ConfigBackupOrchestrator(spec=spec, runner=runner)
    orch.run_target(BackupTarget.CONFIG)
    cmd_arg = runner.call_args.args[0]
    assert "--ignore-failed-read" in cmd_arg


def test_config_tar_fail(tmp_path):
    spec = ConfigBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(return_value=_mk_completed(returncode=1, stderr="tar: bad"))
    orch = ConfigBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.CONFIG)
    assert result.passed is False


def test_config_oserror(tmp_path):
    spec = ConfigBackupSpec(sources=["x"], artifact_dir=tmp_path)
    runner = MagicMock(side_effect=FileNotFoundError("tar missing"))
    orch = ConfigBackupOrchestrator(spec=spec, runner=runner)
    result = orch.run_target(BackupTarget.CONFIG)
    assert result.passed is False


def test_config_non_config_target_skipped():
    orch = ConfigBackupOrchestrator(runner=MagicMock())
    result = orch.run_target(BackupTarget.DB)
    assert result.passed is True
    assert result.details == {"skipped": "db"}


def test_config_run_all_single_element():
    orch = ConfigBackupOrchestrator(runner=MagicMock(return_value=_mk_completed(returncode=0)))
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].target == BackupTarget.CONFIG
