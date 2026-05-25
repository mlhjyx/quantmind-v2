"""MVP 4.3 sub-iter 7 (iter 72) — CI phase entry script.

Single CLI entry point for all 5 CIOrchestrator implementations. Used by
.github/workflows/ci.yml jobs to invoke any phase without per-phase yaml
duplication.

Usage:
    python scripts/ci_run_phase.py --phase pre_commit
    python scripts/ci_run_phase.py --phase pre_push --branch main
    python scripts/ci_run_phase.py --phase regression
    python scripts/ci_run_phase.py --phase ci_matrix
    python scripts/ci_run_phase.py --phase review --pr-number 123

Exit code:
    0 — all checks passed
    1 — at least one check failed OR uncaught exception (铁律 33 fail-soft tier-2)

Platform 严格隔离 sustained: imports only backend.qm_platform.ci.*; no app.*.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Ensure repo root on sys.path for `backend.qm_platform.*` imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PHASE_CHOICES = ("pre_commit", "pre_push", "ci_matrix", "regression", "review")


def _build_orchestrator(phase: str, args: argparse.Namespace):
    """Lazy-import + construct the orchestrator for `phase`.

    Lazy imports keep cold start fast + isolate import errors per phase.
    """
    if phase == "pre_commit":
        from backend.qm_platform.ci.precommit import PreCommitOrchestrator

        return PreCommitOrchestrator()
    if phase == "pre_push":
        from backend.qm_platform.ci.prepush import PrePushOrchestrator

        return PrePushOrchestrator(
            branch_name=args.branch or "",
            commit_subjects=args.commit_subjects or [],
        )
    if phase == "ci_matrix":
        from backend.qm_platform.ci.ci_matrix import CIMatrixOrchestrator

        return CIMatrixOrchestrator()
    if phase == "regression":
        from backend.qm_platform.ci.regression import RegressionOrchestrator

        return RegressionOrchestrator()
    if phase == "review":
        from backend.qm_platform.ci.review import ReviewFinding, ReviewOrchestrator

        findings = []
        if args.findings_json:
            findings_path = Path(args.findings_json)
            raw = json.loads(findings_path.read_text(encoding="utf-8"))
            findings = [ReviewFinding(**item) for item in raw]
        return ReviewOrchestrator(findings=findings, pr_number=args.pr_number)
    raise ValueError(f"unknown phase: {phase}")


def _phase_enum(phase: str):
    """Map phase string → CIPhase enum value."""
    from backend.qm_platform.ci.orchestrator import CIPhase

    return CIPhase(phase)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a single CI phase orchestrator.")
    parser.add_argument("--phase", required=True, choices=PHASE_CHOICES)
    parser.add_argument("--branch", default=None, help="Branch name (pre_push X10 scan input)")
    parser.add_argument(
        "--commit-subjects",
        nargs="*",
        default=None,
        dest="commit_subjects",
        help="Recent commit subjects (pre_push X10 scan input)",
    )
    parser.add_argument("--pr-number", type=int, default=None, help="PR number (review phase)")
    parser.add_argument(
        "--findings-json",
        default=None,
        help="Path to JSON file with reviewer findings (review phase)",
    )
    args = parser.parse_args(argv)

    try:
        orch = _build_orchestrator(args.phase, args)
        result = orch.run_phase(_phase_enum(args.phase))
        status = "PASS" if result.passed else "FAIL"
        print(f"[ci_run_phase] phase={args.phase} status={status} duration_ms={result.duration_ms}")
        for k, v in result.details.items():
            print(f"  {k}: {v}")
        return 0 if result.passed else 1
    except Exception:  # noqa: BLE001 — top-level fail-soft (铁律 33 tier-2)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
