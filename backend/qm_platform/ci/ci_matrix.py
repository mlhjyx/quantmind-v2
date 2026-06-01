"""MVP 4.3 sub-iter 4 (iter 69) — CIMatrixOrchestrator.

Third concrete CIOrchestrator encoding the supported environment matrix
(Python version × PostgreSQL version × pytest marker tags) and running the
same test suite across each cell.

Initial matrix (per CLAUDE.md §技术栈):
  - Python 3.11 (production, default)
  - PostgreSQL 16.8 (production, TimescaleDB 2.26.0)

Future cells (deferred to sub-iter ops):
  - Python 3.12 candidate
  - PostgreSQL 17 candidate
  - Multi-pytest-marker stratification

沿用 precommit/prepush 体例: SubprocessRunner DI + frozen check spec + 铁律
33 fail-soft. Cell-level failure does NOT raise — captured in details +
aggregate passed=False.

Platform 严格隔离 sustained: 0 import backend.app.* (subprocess only).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

DEFAULT_CELL_TIMEOUT_SECONDS = 300  # 5min per cell (smoke ~50s + buffer)

SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Default subprocess runner — wraps subprocess.run with capture."""
    return subprocess.run(  # noqa: S603 — internal-controlled cmd list
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class MatrixCell:
    """A single matrix cell (env + test selector) — frozen 反 silent mutation.

    Attributes:
        python_version: e.g. "3.11" (used for cell identifier + docs only;
            runner cmd is responsible for actually targeting interpreter).
        postgres_version: e.g. "16.8" (informational; DB conn comes from env).
        tags: pytest marker expression to select tests in this cell
            (e.g. "smoke and not live_tushare").
        timeout_seconds: per-cell wall-time limit.
    """

    python_version: str
    postgres_version: str
    tags: str = "smoke and not live_tushare"
    timeout_seconds: int = DEFAULT_CELL_TIMEOUT_SECONDS

    @property
    def cell_id(self) -> str:
        """Stable cell identifier — used as key in CIResult.details."""
        # Normalize: dots in versions → underscores for filesystem-safe keys
        py = self.python_version.replace(".", "_")
        pg = self.postgres_version.replace(".", "_")
        return f"py{py}_pg{pg}"


def default_matrix() -> list[MatrixCell]:
    """Canonical matrix — currently 1 cell (py3.11 + pg16.8 production)."""
    return [
        MatrixCell(python_version="3.11", postgres_version="16.8"),
    ]


def _build_pytest_cmd(cell: MatrixCell) -> list[str]:
    """Build pytest invocation cmd for a matrix cell."""
    return [
        "pytest",
        "backend/tests/",
        "-m",
        cell.tags,
        "--tb=line",
        "-q",
        "--timeout=60",
    ]


def _last_nonempty_line(text: str) -> str:
    """Return a bounded one-line tail suitable for CIResult.details."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:160] if lines else ""


class CIMatrixOrchestrator:
    """Iterates supported environment cells; runs pytest per cell.

    Args:
        matrix: cells list (default = default_matrix()).
        runner: SubprocessRunner DI hook.
        cmd_builder: callable mapping MatrixCell → pytest cmd list (default
            uses module-level _build_pytest_cmd; tests can override).
    """

    def __init__(
        self,
        matrix: list[MatrixCell] | None = None,
        runner: SubprocessRunner | None = None,
        cmd_builder: Callable[[MatrixCell], list[str]] | None = None,
    ) -> None:
        self.matrix = matrix if matrix is not None else default_matrix()
        self.runner = runner if runner is not None else _default_runner
        self.cmd_builder = cmd_builder if cmd_builder is not None else _build_pytest_cmd

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Run pytest across all matrix cells; aggregate per-cell results.

        Only CIPhase.CI_MATRIX is processed; other phases return skip result.
        """
        if phase != CIPhase.CI_MATRIX:
            return CIResult(
                phase=phase,
                passed=True,
                duration_ms=0,
                details={"skipped": phase.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {"matrix_size": str(len(self.matrix))}
        all_passed = True

        for cell in self.matrix:
            cell_start = time.monotonic()
            cmd = self.cmd_builder(cell)
            try:
                result = self.runner(cmd, cell.timeout_seconds)
                cell_passed = result.returncode == 0
                summary_parts = [f"rc={result.returncode}"]
                if result.stdout:
                    summary_parts.append(f"stdout_len={len(result.stdout)}")
                    if not cell_passed:
                        stdout_tail = _last_nonempty_line(result.stdout)
                        if stdout_tail:
                            summary_parts.append(f"stdout_tail={stdout_tail}")
                if result.stderr and not cell_passed:
                    err_tail = _last_nonempty_line(result.stderr)
                    if err_tail:
                        summary_parts.append(f"err_tail={err_tail[:80]}")
                details[cell.cell_id] = " ".join(summary_parts)
                if not cell_passed:
                    all_passed = False
            except subprocess.TimeoutExpired:
                details[cell.cell_id] = f"TIMEOUT after {cell.timeout_seconds}s"
                all_passed = False
            except (OSError, FileNotFoundError) as e:
                # silent_ok: cmd not found / IO error captured (铁律 33)
                details[cell.cell_id] = f"OSError: {e}"
                all_passed = False
            cell_elapsed_ms = int((time.monotonic() - cell_start) * 1000)
            details[f"{cell.cell_id}_duration_ms"] = str(cell_elapsed_ms)

        total_ms = int((time.monotonic() - start) * 1000)
        return CIResult(
            phase=CIPhase.CI_MATRIX,
            passed=all_passed,
            duration_ms=total_ms,
            details=details,
        )

    def run_all(self) -> list[CIResult]:
        """Single-phase orchestrator — list of length 1."""
        return [self.run_phase(CIPhase.CI_MATRIX)]


__all__ = [
    "CIMatrixOrchestrator",
    "DEFAULT_CELL_TIMEOUT_SECONDS",
    "MatrixCell",
    "SubprocessRunner",
    "default_matrix",
]
