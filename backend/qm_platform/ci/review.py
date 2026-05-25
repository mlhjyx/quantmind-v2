"""MVP 4.3 sub-iter 6 (iter 71) — ReviewOrchestrator.

Fifth concrete CIOrchestrator. Consumes reviewer agent findings (typed as
ReviewFinding list) + posts them as PR comments via `gh pr comment`.

Severity gating: P0 / P1 block (passed=False); P2 / P3 warnings only.
Threshold configurable via constructor (default block_at = "P1").

沿用 precommit/prepush/ci_matrix/regression 体例: SubprocessRunner DI +
frozen check spec + 铁律 33 fail-soft tier-2.

Platform 严格隔离 sustained: 0 import backend.app.* (subprocess + stdlib only).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

# Severity tuple — ordered low → high (P0 most severe).
SEVERITY_LEVELS: tuple[str, ...] = ("P0", "P1", "P2", "P3")
SEVERITY_ORDER: dict[str, int] = {sev: i for i, sev in enumerate(SEVERITY_LEVELS)}

DEFAULT_GH_TIMEOUT_SECONDS = 30

SubprocessRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Default subprocess runner."""
    return subprocess.run(  # noqa: S603 — internal-controlled cmd list
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass(frozen=True)
class ReviewFinding:
    """A single reviewer finding (frozen — 反 silent mutation).

    Attributes:
        severity: one of SEVERITY_LEVELS (P0/P1/P2/P3).
        file_path: source file the finding refers to.
        line: 1-indexed line number; 0 if file-level.
        message: short human-readable description.
    """

    severity: str
    file_path: str
    line: int
    message: str


def format_findings_as_comment(findings: list[ReviewFinding]) -> str:
    """Build a markdown PR comment body grouping findings by severity.

    Returns:
        Markdown string; empty findings → "No findings." sentinel.
    """
    if not findings:
        return "No findings."

    # Group by severity in canonical order (P0 → P3)
    groups: dict[str, list[ReviewFinding]] = {sev: [] for sev in SEVERITY_LEVELS}
    for f in findings:
        if f.severity in groups:
            groups[f.severity].append(f)

    lines: list[str] = ["## CI Review Findings", ""]
    for sev in SEVERITY_LEVELS:
        items = groups[sev]
        if not items:
            continue
        lines.append(f"### {sev} ({len(items)})")
        for f in items:
            loc = f"{f.file_path}:{f.line}" if f.line > 0 else f.file_path
            lines.append(f"- `{loc}` — {f.message}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class ReviewOrchestrator:
    """Posts reviewer findings as PR comments + gates merge via severity.

    Args:
        findings: list of ReviewFinding.
        pr_number: PR number for `gh pr comment <pr> --body`.
        runner: SubprocessRunner DI hook.
        block_at: severity threshold (default "P1" — block on P0/P1).
        gh_timeout_seconds: timeout for gh subprocess.
    """

    def __init__(
        self,
        findings: list[ReviewFinding] | None = None,
        pr_number: int | None = None,
        runner: SubprocessRunner | None = None,
        block_at: str = "P1",
        gh_timeout_seconds: int = DEFAULT_GH_TIMEOUT_SECONDS,
    ) -> None:
        self.findings = findings if findings is not None else []
        self.pr_number = pr_number
        self.runner = runner if runner is not None else _default_runner
        if block_at not in SEVERITY_LEVELS:
            raise ValueError(f"block_at must be one of {SEVERITY_LEVELS}; got {block_at!r}")
        self.block_at = block_at
        self.gh_timeout_seconds = gh_timeout_seconds

    def _has_blocking_finding(self) -> bool:
        """Return True if any finding meets/exceeds block_at threshold."""
        block_order = SEVERITY_ORDER[self.block_at]
        return any(SEVERITY_ORDER.get(f.severity, 99) <= block_order for f in self.findings)

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Group findings, build comment, invoke gh.

        Only CIPhase.REVIEW is processed; other phases return skip result.
        """
        if phase != CIPhase.REVIEW:
            return CIResult(
                phase=phase,
                passed=True,
                duration_ms=0,
                details={"skipped": phase.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {
            "findings_count": str(len(self.findings)),
            "block_at": self.block_at,
        }

        blocking = self._has_blocking_finding()
        passed = not blocking
        details["blocking"] = str(blocking)

        # Build comment + invoke gh (if pr_number provided)
        comment_body = format_findings_as_comment(self.findings)
        details["comment_length"] = str(len(comment_body))

        if self.pr_number is not None and self.findings:
            cmd = ["gh", "pr", "comment", str(self.pr_number), "--body", comment_body]
            try:
                result = self.runner(cmd, self.gh_timeout_seconds)
                gh_passed = result.returncode == 0
                summary_parts = [f"gh_rc={result.returncode}"]
                if result.stderr and not gh_passed:
                    err_tail = (
                        result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
                    )
                    if err_tail:
                        summary_parts.append(f"err_tail={err_tail[:80]}")
                details["gh_post"] = " ".join(summary_parts)
                if not gh_passed:
                    passed = False
            except subprocess.TimeoutExpired:
                details["gh_post"] = f"TIMEOUT after {self.gh_timeout_seconds}s"
                passed = False
            except (OSError, FileNotFoundError) as e:
                # silent_ok: gh not installed / IO error captured (铁律 33)
                details["gh_post"] = f"OSError: {e}"
                passed = False
        else:
            details["gh_post"] = "SKIPPED (no pr_number or no findings)"

        total_ms = int((time.monotonic() - start) * 1000)
        return CIResult(
            phase=CIPhase.REVIEW,
            passed=passed,
            duration_ms=total_ms,
            details=details,
        )

    def run_all(self) -> list[CIResult]:
        """Single-phase orchestrator — list of length 1."""
        return [self.run_phase(CIPhase.REVIEW)]


__all__ = [
    "DEFAULT_GH_TIMEOUT_SECONDS",
    "ReviewFinding",
    "ReviewOrchestrator",
    "SEVERITY_LEVELS",
    "SEVERITY_ORDER",
    "SubprocessRunner",
    "format_findings_as_comment",
]
