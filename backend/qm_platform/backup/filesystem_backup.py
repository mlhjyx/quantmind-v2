"""MVP 4.4 sub-iter 3 (iter 74 batch) — FilesystemBackupOrchestrator.

Snapshot factor parquet cache (43GB) + cache/baseline/* + reports/* via
tar/gzip archive. Stateless compute; subprocess wrapper preserved for tar
invocation (sustained MVP 4.3 体例).

Platform 严格隔离 sustained.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from backend.qm_platform.backup.orchestrator import BackupTarget, BackupTargetResult

DEFAULT_TAR_TIMEOUT_SECONDS = 1800  # 30min for ~50GB tar+gzip

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
class FilesystemBackupSpec:
    """Filesystem backup paths (frozen — 反 silent mutation).

    sources: list of root paths to include (relative or absolute).
    artifact_dir: where the tar.gz archive lands.
    retention_days: archives older than this are swept best-effort.
    """

    sources: list[str] = field(
        default_factory=lambda: ["cache/baseline", "backend/data/parquet_cache", "reports"]
    )
    artifact_dir: Path = Path("backups/fs")
    retention_days: int = 7
    timeout_seconds: int = DEFAULT_TAR_TIMEOUT_SECONDS


def default_filesystem_spec() -> FilesystemBackupSpec:
    """Canonical spec — parquet cache + baseline + reports."""
    return FilesystemBackupSpec()


def _sweep_old_artifacts(directory: Path, retention_days: int) -> int:
    """Delete archives older than retention_days. Best-effort fail-soft."""
    if not directory.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:  # silent_ok: filesystem race (铁律 33)
            continue
    return deleted


class FilesystemBackupOrchestrator:
    """Single-target orchestrator wrapping tar -czf snapshot.

    Args:
        spec: FilesystemBackupSpec (default = default_filesystem_spec()).
        runner: SubprocessRunner DI hook.
        sweep_fn: retention sweep DI.
    """

    def __init__(
        self,
        spec: FilesystemBackupSpec | None = None,
        runner: SubprocessRunner | None = None,
        sweep_fn: Callable[[Path, int], int] | None = None,
    ) -> None:
        self.spec = spec if spec is not None else default_filesystem_spec()
        self.runner = runner if runner is not None else _default_runner
        self.sweep_fn = sweep_fn if sweep_fn is not None else _sweep_old_artifacts

    def _build_tar_cmd(self, artifact_path: Path) -> list[str]:
        return ["tar", "-czf", str(artifact_path), *self.spec.sources]

    def run_target(self, target: BackupTarget) -> BackupTargetResult:
        if target != BackupTarget.FILESYSTEM:
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
        artifact_path = self.spec.artifact_dir / f"fs_{timestamp}.tar.gz"
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
            target=BackupTarget.FILESYSTEM,
            passed=passed,
            duration_ms=total_ms,
            bytes_written=bytes_written,
            details=details,
        )

    def run_all(self) -> list[BackupTargetResult]:
        return [self.run_target(BackupTarget.FILESYSTEM)]


__all__ = [
    "DEFAULT_TAR_TIMEOUT_SECONDS",
    "FilesystemBackupOrchestrator",
    "FilesystemBackupSpec",
    "SubprocessRunner",
    "default_filesystem_spec",
]
