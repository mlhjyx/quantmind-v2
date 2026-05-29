"""MVP 4.4 sub-iter 2 (iter 74 batch) — DBBackupOrchestrator.

Wraps pg_dump for TimescaleDB (CLAUDE.md §技术栈: PG 16.8 / TimescaleDB 2.26.0 /
db=quantmind_v2 / D:\\pgdata16). Artifact written to artifact_dir; retention
sweep removes files older than retention_days (best-effort fail-soft).

沿用 ci/precommit/prepush 体例: SubprocessRunner DI + frozen check spec +
铁律 33 fail-soft tier-2.

Platform 严格隔离 sustained: 0 import backend.app.* (subprocess + stdlib only).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.qm_platform.backup.orchestrator import BackupTarget, BackupTargetResult
from backend.qm_platform.backup.pg_tools import pg_subprocess_env, resolve_pg_binary

DEFAULT_PG_DUMP_TIMEOUT_SECONDS = 3600  # 1h for 165GB worst case

SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — internal-controlled cmd list
        cmd,
        capture_output=True,
        env=pg_subprocess_env(),
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class DBBackupSpec:
    """pg_dump backup specification (frozen — 反 silent mutation)."""

    database: str
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "xin"
    artifact_dir: Path = Path("backups/db")
    retention_days: int = 14
    timeout_seconds: int = DEFAULT_PG_DUMP_TIMEOUT_SECONDS


def default_db_spec() -> DBBackupSpec:
    """Canonical spec — matches CLAUDE.md §技术栈 production config."""
    return DBBackupSpec(database="quantmind_v2")


def _sha256_of_file(path: Path) -> str:
    """SHA256 checksum (chunked to handle 165GB files without memory blow)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):  # 1MB chunks
            h.update(chunk)
    return h.hexdigest()


def _sweep_old_artifacts(directory: Path, retention_days: int) -> int:
    """Delete artifacts older than retention_days. Returns count deleted.

    Best-effort fail-soft: missing dir + permission errors silently ignored.
    """
    if not directory.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:  # silent_ok: filesystem race / permission (铁律 33)
            continue
    return deleted


class DBBackupOrchestrator:
    """Single-target orchestrator wrapping pg_dump.

    Args:
        spec: DBBackupSpec (default = default_db_spec()).
        runner: SubprocessRunner DI hook.
        sweep_fn: retention sweep function (DI for tests).
        checksum_fn: SHA256 function (DI for tests).
    """

    def __init__(
        self,
        spec: DBBackupSpec | None = None,
        runner: SubprocessRunner | None = None,
        sweep_fn: Callable[[Path, int], int] | None = None,
        checksum_fn: Callable[[Path], str] | None = None,
    ) -> None:
        self.spec = spec if spec is not None else default_db_spec()
        self.runner = runner if runner is not None else _default_runner
        self.sweep_fn = sweep_fn if sweep_fn is not None else _sweep_old_artifacts
        self.checksum_fn = checksum_fn if checksum_fn is not None else _sha256_of_file

    def _build_pg_dump_cmd(self, artifact_path: Path) -> list[str]:
        """Construct pg_dump invocation (custom format -Fc for parallel restore)."""
        return [
            resolve_pg_binary("pg_dump"),
            "-h",
            self.spec.host,
            "-p",
            str(self.spec.port),
            "-U",
            self.spec.user,
            "-d",
            self.spec.database,
            "-Fc",  # custom format
            "-f",
            str(artifact_path),
        ]

    def run_target(self, target: BackupTarget) -> BackupTargetResult:
        """Execute pg_dump for DB target; non-DB targets return skip result."""
        if target != BackupTarget.DB:
            return BackupTargetResult(
                target=target,
                passed=True,
                duration_ms=0,
                bytes_written=0,
                details={"skipped": target.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {"spec_database": self.spec.database}

        # Build artifact path with UTC date stamp
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        artifact_path = self.spec.artifact_dir / f"{self.spec.database}_{timestamp}.dump"
        details["artifact_path"] = str(artifact_path)

        passed = True
        bytes_written = 0

        try:
            self.spec.artifact_dir.mkdir(parents=True, exist_ok=True)
            result = self.runner(self._build_pg_dump_cmd(artifact_path), self.spec.timeout_seconds)
            details["pg_dump_rc"] = str(result.returncode)
            if result.returncode != 0:
                passed = False
                err_tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
                if err_tail:
                    details["err_tail"] = err_tail[:120]
            else:
                if artifact_path.exists():
                    bytes_written = artifact_path.stat().st_size
                    details["checksum"] = self.checksum_fn(artifact_path)
        except subprocess.TimeoutExpired:
            details["pg_dump"] = f"TIMEOUT after {self.spec.timeout_seconds}s"
            passed = False
        except (OSError, FileNotFoundError) as e:
            details["pg_dump"] = f"OSError: {e}"
            passed = False

        # Retention sweep (best-effort)
        try:
            deleted = self.sweep_fn(self.spec.artifact_dir, self.spec.retention_days)
            details["retention_swept"] = str(deleted)
        except OSError as e:  # silent_ok: sweep failure non-fatal (铁律 33)
            details["retention_sweep_err"] = str(e)

        total_ms = int((time.monotonic() - start) * 1000)
        return BackupTargetResult(
            target=BackupTarget.DB,
            passed=passed,
            duration_ms=total_ms,
            bytes_written=bytes_written,
            details=details,
        )

    def run_all(self) -> list[BackupTargetResult]:
        return [self.run_target(BackupTarget.DB)]


# Suppress unused import for stdlib `os` (kept for future env-var resolution path)
_ = os


__all__ = [
    "DBBackupOrchestrator",
    "DBBackupSpec",
    "DEFAULT_PG_DUMP_TIMEOUT_SECONDS",
    "SubprocessRunner",
    "default_db_spec",
]
