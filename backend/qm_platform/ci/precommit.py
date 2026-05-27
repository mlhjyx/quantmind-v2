"""MVP 4.3 sub-iter 2 (iter 67) — PreCommitOrchestrator.

Concrete CIOrchestrator merging 4 pre-commit checks into a single subprocess-
wrapped orchestrator:
  1. `ruff check` — lint enforcement
  2. `ruff format --check` — formatting consistency
  3. `pytest --collect-only` — lightweight CI/platform discovery sanity
  4. `scripts/check_llm_imports.sh --staged` — S2/PR-219 LLM import allowlist

Each check runs sequentially via subprocess.run with configurable timeout.
Individual check failure does NOT raise — captured in CIResult.passed=False
+ details dict (铁律 33 fail-soft). Aggregate passed = all individual passes.

Platform 严格隔离 sustained (沿用 MVP 4.1/4.2 体例):
  - 0 import backend.app.* / backend.data.* / backend.engines.*
  - subprocess invocations resolved via SUBPROCESS_RUNNER DI hook
    (default = subprocess.run; tests override with mock)
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

DEFAULT_TIMEOUT_SECONDS = 30
PYTEST_COLLECT_TIMEOUT_SECONDS = 300
PYTEST_COLLECT_TARGETS = [
    "backend/tests/test_qm_platform_ci_orchestrator.py",
    "backend/tests/test_qm_platform_ci_precommit.py",
    "backend/tests/test_qm_platform_ci_prepush.py",
    "backend/tests/test_qm_platform_ci_matrix.py",
    "backend/tests/test_qm_platform_ci_regression.py",
    "backend/tests/test_qm_platform_ci_review.py",
    "backend/tests/test_qm_platform_ci_entry_script.py",
    "backend/tests/test_platform_skeleton.py",
]

# DI hook signature: (cmd_list, timeout_seconds) -> CompletedProcess-like obj
# (returncode + stdout + stderr attributes)
SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Default subprocess runner — wraps subprocess.run with stdout/stderr capture."""
    return subprocess.run(  # noqa: S603 — input cmd is internal-controlled list
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class PreCommitCheck:
    """Spec for a single pre-commit check (frozen — 反 silent mutation)."""

    name: str  # e.g. "ruff_check" / "pytest_collect"
    cmd: list[str] = field(default_factory=list)
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def default_checks() -> list[PreCommitCheck]:
    """Canonical 4 pre-commit checks (per MVP_4_3_cicd.md §1)."""
    return [
        PreCommitCheck(name="ruff_check", cmd=["ruff", "check", "."]),
        PreCommitCheck(name="ruff_format", cmd=["ruff", "format", "--check", "."]),
        PreCommitCheck(
            name="pytest_collect",
            cmd=["pytest", "--collect-only", "-q", *PYTEST_COLLECT_TARGETS],
            timeout_seconds=PYTEST_COLLECT_TIMEOUT_SECONDS,
        ),
        PreCommitCheck(
            name="check_llm_imports",
            cmd=["bash", "scripts/check_llm_imports.sh", "--staged"],
            timeout_seconds=15,
        ),
    ]


class PreCommitOrchestrator:
    """Runs 4 pre-commit checks; returns single CIResult with aggregated outcome.

    Args:
        checks: list of PreCommitCheck specs (default = default_checks()).
        runner: SubprocessRunner DI hook for testability (default = subprocess.run wrapper).
    """

    def __init__(
        self,
        checks: list[PreCommitCheck] | None = None,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self.checks = checks if checks is not None else default_checks()
        self.runner = runner if runner is not None else _default_runner

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Execute pre-commit checks; return aggregated CIResult.

        Only CIPhase.PRE_COMMIT is supported — other phases return immediate
        skip result (passed=True, details={"skipped": phase.value}).
        """
        if phase != CIPhase.PRE_COMMIT:
            return CIResult(
                phase=phase,
                passed=True,
                duration_ms=0,
                details={"skipped": phase.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {}
        all_passed = True

        for check in self.checks:
            check_start = time.monotonic()
            try:
                result = self.runner(check.cmd, check.timeout_seconds)
                check_passed = result.returncode == 0
                summary_parts = [f"rc={result.returncode}"]
                # Truncate stdout/stderr to avoid bloat (沿用 batch 3.x dispatch convention).
                if result.stdout:
                    summary_parts.append(f"stdout_len={len(result.stdout)}")
                if result.stderr and not check_passed:
                    err_tail = (
                        result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
                    )
                    if err_tail:
                        summary_parts.append(f"err_tail={err_tail[:80]}")
                details[check.name] = " ".join(summary_parts)
                if not check_passed:
                    all_passed = False
            except subprocess.TimeoutExpired:
                details[check.name] = f"TIMEOUT after {check.timeout_seconds}s"
                all_passed = False
            except (OSError, FileNotFoundError) as e:
                # silent_ok: command not found / IO error → captured as failure
                # detail, not raised (铁律 33 fail-soft per orchestrator contract).
                details[check.name] = f"OSError: {e}"
                all_passed = False
            check_elapsed_ms = int((time.monotonic() - check_start) * 1000)
            details[f"{check.name}_duration_ms"] = str(check_elapsed_ms)

        total_ms = int((time.monotonic() - start) * 1000)
        return CIResult(
            phase=CIPhase.PRE_COMMIT,
            passed=all_passed,
            duration_ms=total_ms,
            details=details,
        )

    def run_all(self) -> list[CIResult]:
        """Single-phase orchestrator semantics — returns list of length 1."""
        return [self.run_phase(CIPhase.PRE_COMMIT)]


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PYTEST_COLLECT_TIMEOUT_SECONDS",
    "PYTEST_COLLECT_TARGETS",
    "PreCommitCheck",
    "PreCommitOrchestrator",
    "SubprocessRunner",
    "default_checks",
]
