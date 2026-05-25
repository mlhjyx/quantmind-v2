"""MVP 4.4 sub-iter 4 (iter 74 batch) — ConfigBackupOrchestrator.

Snapshot .env (secrets-aware) + configs/*.yaml + config/hooks/* + Servy service
definitions. Distinct from filesystem_backup: small files, but semantically
treated separately for drift-detection + faster retention.

铁律 35 (Secrets via env, no fallback) sustained — .env is included in backup
artifact AS-IS (encrypted at rest left to sub-iter 4+ enhancement). For now,
plain tar.gz; user/ops must ensure backup destination has restricted ACL.

Platform 严格隔离 sustained.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from backend.qm_platform.backup.orchestrator import BackupTarget, BackupTargetResult

DEFAULT_CONFIG_TIMEOUT_SECONDS = 60  # Small files; 60s plenty

SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — internal-controlled cmd list
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class ConfigBackupSpec:
    """Config snapshot specification (frozen — 反 silent mutation)."""

    sources: list[str] = field(
        default_factory=lambda: [
            "backend/.env",
            "configs",
            "config/hooks",
        ]
    )
    artifact_dir: Path = Path("backups/config")
    retention_days: int = 30  # configs change rarely → longer retention OK
    timeout_seconds: int = DEFAULT_CONFIG_TIMEOUT_SECONDS


def default_config_spec() -> ConfigBackupSpec:
    """Canonical config backup spec."""
    return ConfigBackupSpec()


def _sweep_old_artifacts(directory: Path, retention_days: int) -> int:
    if not directory.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:  # silent_ok (铁律 33)
            continue
    return deleted


class ConfigBackupOrchestrator:
    """Single-target orchestrator snapshotting config files via tar -czf.

    Args:
        spec: ConfigBackupSpec (default = default_config_spec()).
        runner: SubprocessRunner DI hook.
        sweep_fn: retention sweep DI.
    """

    def __init__(
        self,
        spec: ConfigBackupSpec | None = None,
        runner: SubprocessRunner | None = None,
        sweep_fn: Callable[[Path, int], int] | None = None,
    ) -> None:
        self.spec = spec if spec is not None else default_config_spec()
        self.runner = runner if runner is not None else _default_runner
        self.sweep_fn = sweep_fn if sweep_fn is not None else _sweep_old_artifacts

    def _build_tar_cmd(self, artifact_path: Path) -> list[str]:
        # --ignore-failed-read: missing source file → warning + continue
        # (e.g. .env not present in fresh clone — still archive what exists)
        return [
            "tar",
            "--ignore-failed-read",
            "-czf",
            str(artifact_path),
            *self.spec.sources,
        ]

    def run_target(self, target: BackupTarget) -> BackupTargetResult:
        if target != BackupTarget.CONFIG:
            return BackupTargetResult(
                target=target,
                passed=True,
                duration_ms=0,
                bytes_written=0,
                details={"skipped": target.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {"source_count": str(len(self.spec.sources))}

        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        artifact_path = self.spec.artifact_dir / f"config_{timestamp}.tar.gz"
        details["artifact_path"] = str(artifact_path)

        passed = True
        bytes_written = 0

        try:
            self.spec.artifact_dir.mkdir(parents=True, exist_ok=True)
            result = self.runner(self._build_tar_cmd(artifact_path), self.spec.timeout_seconds)
            details["tar_rc"] = str(result.returncode)
            if result.returncode != 0:
                passed = False
                err_tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
                if err_tail:
                    details["err_tail"] = err_tail[:120]
            elif artifact_path.exists():
                bytes_written = artifact_path.stat().st_size
        except subprocess.TimeoutExpired:
            details["tar"] = f"TIMEOUT after {self.spec.timeout_seconds}s"
            passed = False
        except (OSError, FileNotFoundError) as e:
            details["tar"] = f"OSError: {e}"
            passed = False

        try:
            deleted = self.sweep_fn(self.spec.artifact_dir, self.spec.retention_days)
            details["retention_swept"] = str(deleted)
        except OSError as e:
            details["retention_sweep_err"] = str(e)

        total_ms = int((time.monotonic() - start) * 1000)
        return BackupTargetResult(
            target=BackupTarget.CONFIG,
            passed=passed,
            duration_ms=total_ms,
            bytes_written=bytes_written,
            details=details,
        )

    def run_all(self) -> list[BackupTargetResult]:
        return [self.run_target(BackupTarget.CONFIG)]


__all__ = [
    "ConfigBackupOrchestrator",
    "ConfigBackupSpec",
    "DEFAULT_CONFIG_TIMEOUT_SECONDS",
    "SubprocessRunner",
    "default_config_spec",
]
