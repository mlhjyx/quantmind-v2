"""MVP 4.3 sub-iter 3 (iter 68) — PrePushOrchestrator.

Second concrete CIOrchestrator merging 3 pre-push checks 沿用 config/hooks/pre-push
现有 logic:
  1. 铁律 10b smoke test (pytest backend/tests/ -m "smoke and not live_tushare")
  2. 铁律 X10 cutover-bias scan (branch + last 5 commits pattern match)
  3. 铁律 17 DataPipeline guard (check_llm_imports --full + DataPipeline naked
     INSERT scan over backend/**.py)

沿用 precommit.py 体例: SubprocessRunner DI + frozen check spec + 铁律 33 fail-soft.
铁律 X10 X10 pattern match is pure Python (no subprocess) — branch name + commit
subjects passed in as constructor arg or fetched via git subprocess.

Platform 严格隔离 sustained: 0 import backend.app.* (subprocess only).
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

# Cutover-bias hard patterns (per 铁律 X10 + LL-098, config/hooks/pre-push 现有)
X10_HARD_PATTERNS: tuple[str, ...] = (
    r"/schedule\s+agent",
    r"paper-mode\s+5d",
    r"paper-mode\s+dry-run",
    r"paper.*->\s*live",
    r"paper→live",
    r"auto\s+cutover",
    r"自动\s*cutover",
)

DEFAULT_SMOKE_TIMEOUT_SECONDS = 90
DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS = 30
SMOKE_COLLECT_ONLY_ENV = "QM_CI_SMOKE_COLLECT_ONLY"

SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Default subprocess runner — wraps subprocess.run with stdout/stderr capture."""
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
class PrePushCheck:
    """Spec for a single pre-push check (frozen — 反 silent mutation)."""

    name: str
    cmd: list[str] = field(default_factory=list)
    timeout_seconds: int = DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS


def default_subprocess_checks() -> list[PrePushCheck]:
    """Canonical 2 subprocess-based pre-push checks (smoke + datapipeline guard).

    X10 cutover-bias scan is pure-Python and not in this list — handled
    separately in run_phase via x10_scan().
    """
    smoke_cmd = [
        "pytest",
        "backend/tests/",
        "-m",
        "smoke and not live_tushare",
        "--tb=line",
        "-q",
        "--timeout=60",
    ]
    if os.environ.get(SMOKE_COLLECT_ONLY_ENV) == "1":
        smoke_cmd = [
            "pytest",
            "backend/tests/",
            "--collect-only",
            "-q",
            "-m",
            "smoke and not live_tushare",
        ]

    return [
        PrePushCheck(
            name="smoke_test",
            cmd=smoke_cmd,
            timeout_seconds=DEFAULT_SMOKE_TIMEOUT_SECONDS,
        ),
        PrePushCheck(
            name="datapipeline_guard",
            cmd=["bash", "scripts/check_llm_imports.sh", "--full"],
            timeout_seconds=DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS,
        ),
    ]


def x10_scan(branch_name: str, commit_subjects: list[str]) -> tuple[bool, str | None]:
    """Scan branch name + recent commit subjects for cutover-bias patterns.

    Per 铁律 X10 + LL-098: branch / commit msg containing forward-progress
    cutover phrases (e.g. "/schedule agent", "paper→live", "auto cutover")
    → block push.

    Args:
        branch_name: e.g. "main" or "feat/paper-live-cutover".
        commit_subjects: list of recent commit messages (subject line only).

    Returns:
        (passed, offending_excerpt). passed=True iff no patterns match.
    """
    haystack = [branch_name] + commit_subjects
    for text in haystack:
        for pattern in X10_HARD_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return False, f"X10 hit '{pattern}' in: {text[:80]}"
    return True, None


class PrePushOrchestrator:
    """Runs 3 pre-push checks (X10 scan + smoke test + DataPipeline guard).

    Args:
        checks: subprocess-based PrePushCheck list (default = default_subprocess_checks()).
        runner: SubprocessRunner DI hook.
        branch_name: current git branch (default empty; tests inject).
        commit_subjects: recent commit subjects list for X10 scan.
    """

    def __init__(
        self,
        checks: list[PrePushCheck] | None = None,
        runner: SubprocessRunner | None = None,
        branch_name: str = "",
        commit_subjects: list[str] | None = None,
    ) -> None:
        self.checks = checks if checks is not None else default_subprocess_checks()
        self.runner = runner if runner is not None else _default_runner
        self.branch_name = branch_name
        self.commit_subjects = commit_subjects if commit_subjects is not None else []

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Execute pre-push checks; return aggregated CIResult.

        Only CIPhase.PRE_PUSH is processed; others return skip result.
        """
        if phase != CIPhase.PRE_PUSH:
            return CIResult(
                phase=phase,
                passed=True,
                duration_ms=0,
                details={"skipped": phase.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {}
        all_passed = True

        # ── X10 cutover-bias scan (pure Python, no subprocess) ──
        x10_passed, x10_evidence = x10_scan(self.branch_name, self.commit_subjects)
        details["x10_scan"] = "PASS" if x10_passed else (x10_evidence or "FAIL")
        if not x10_passed:
            all_passed = False

        # ── Subprocess-based checks (smoke + datapipeline_guard) ──
        for check in self.checks:
            check_start = time.monotonic()
            try:
                result = self.runner(check.cmd, check.timeout_seconds)
                check_passed = result.returncode == 0
                summary_parts = [f"rc={result.returncode}"]
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
                # silent_ok: cmd not found / IO error → captured as fail detail (铁律 33)
                details[check.name] = f"OSError: {e}"
                all_passed = False
            check_elapsed_ms = int((time.monotonic() - check_start) * 1000)
            details[f"{check.name}_duration_ms"] = str(check_elapsed_ms)

        total_ms = int((time.monotonic() - start) * 1000)
        return CIResult(
            phase=CIPhase.PRE_PUSH,
            passed=all_passed,
            duration_ms=total_ms,
            details=details,
        )

    def run_all(self) -> list[CIResult]:
        """Single-phase orchestrator — returns list of length 1."""
        return [self.run_phase(CIPhase.PRE_PUSH)]


__all__ = [
    "DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS",
    "DEFAULT_SMOKE_TIMEOUT_SECONDS",
    "PrePushCheck",
    "PrePushOrchestrator",
    "SMOKE_COLLECT_ONLY_ENV",
    "SubprocessRunner",
    "X10_HARD_PATTERNS",
    "default_subprocess_checks",
    "x10_scan",
]
