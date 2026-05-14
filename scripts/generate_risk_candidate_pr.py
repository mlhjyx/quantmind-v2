"""V3 §8.3 RiskReflector approved-candidate → PR generator — TB-4d sprint.

EXPLICIT-TRIGGER tool (human / CC runs it) — NOT a Beat, NOT the webhook hot
path. Per PR #345 plan option B "Webhook sediment + scripts/ PR 生成器": the
DingTalk webhook handler (reflection_candidate_service) only sediments candidate
records to docs/research-kb/risk_findings/; THIS script is the ONLY git-touching
component, behind an explicit trigger.

Flow:
  1. Scan docs/research-kb/risk_findings/*_approved.md with `pr_generated: false`.
  2. RED-LINE SELF-CHECK: verify the proposed change set touches ONLY
     docs/research-kb/risk_findings/ — abort if ANY .env / backend production /
     configs / broker path mutation detected (反 silent .env mutation ADR-022 +
     反 production config mutation). The candidates are PROPOSALS for user review,
     NOT auto-applied — this script only marks records `pr_generated: true` and
     creates a PR branch carrying the candidate records themselves.
  3. git branch + add + commit + push — **NEVER git merge** (user 显式 merge
     sustained — sustained LL-098 X10 + redline discipline).
  4. Print the gh pr create command for the user (this script does NOT create
     the PR via gh — user runs it, keeping the GitHub-visible action user-driven).

Safety properties:
  - 0 .env mutation / 0 broker call / 0 production code change — script only
    touches docs/research-kb/risk_findings/ markdown records.
  - NEVER git merge — push only, user merges.
  - --dry-run flag — full flow except git push (for verification / testing).
  - redline_pretool_block hook + quantmind-redline-guardian subagent still apply
    to any git operation this script triggers.

Usage:
    python scripts/generate_risk_candidate_pr.py [--dry-run] [--repo-root PATH]

关联 V3: §8.3 line 965-967 (参数候选 → user approve → 系统生成 PR → user merge)
关联 ADR: ADR-022 (反 silent .env mutation) / ADR-069 候选 (TB-4 closure)
关联 铁律: 33 (fail-loud) / 35 (secrets — 0 .env touch) / 42 (PR governance) /
  X10 (反 silent forward-progress — script generates PR, user merges)
关联 LL: LL-098 X10 / LL-163 候选 (TB-4 closure)
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("generate_risk_candidate_pr")

# Paths the script is ALLOWED to touch. Any staged change outside this set
# aborts the run (red-line self-check).
_ALLOWED_PATH_PREFIX: str = "docs/research-kb/risk_findings/"

# Forbidden path fragments — defense-in-depth (red-line self-check).
_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    ".env",
    "backend/app/",
    "backend/engines/",
    "configs/",
    "config/litellm_router",
)


def _run_git(args: list[str], *, repo_root: Path, check: bool = True) -> str:
    """Run a git command in repo_root, return stdout. fail-loud on non-zero (铁律 33)."""
    result = subprocess.run(  # noqa: S603 — git args are script-controlled, no user input
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def _scan_pending_approved(risk_findings_dir: Path) -> list[Path]:
    """Find *_approved.md records with `pr_generated: false` frontmatter."""
    if not risk_findings_dir.is_dir():
        return []
    pending: list[Path] = []
    for path in sorted(risk_findings_dir.glob("*_approved.md")):
        content = path.read_text(encoding="utf-8")
        if "pr_generated: false" in content:
            pending.append(path)
    return pending


def _mark_pr_generated(path: Path) -> None:
    """Flip `pr_generated: false` → `pr_generated: true` in a candidate record."""
    content = path.read_text(encoding="utf-8")
    updated = content.replace("pr_generated: false", "pr_generated: true", 1)
    if updated == content:
        raise RuntimeError(
            f"{path.name}: 'pr_generated: false' marker not found — record "
            f"malformed or already PR-generated"
        )
    path.write_text(updated, encoding="utf-8")


def _rollback_marks(pending: list[Path], *, repo_root: Path) -> None:
    """Revert `_mark_pr_generated` flips + unstage — clean abort state.

    Reviewer-fix (PR #346 MEDIUM 1): on red-line abort / any pre-push exception,
    leaving `pr_generated: true` flips + staged files is an unclean failure mode.
    This helper restores the working tree (used by both dry-run path + error path).
    """
    _run_git(["reset", "HEAD"], repo_root=repo_root, check=False)
    for path in pending:
        try:
            content = path.read_text(encoding="utf-8")
            path.write_text(
                content.replace("pr_generated: true", "pr_generated: false", 1),
                encoding="utf-8",
            )
        except OSError:
            # Best-effort rollback — log via caller; do not mask the original error.
            logger.warning("[candidate-pr] rollback: failed to revert %s", path.name)


def _redline_self_check(staged_paths: list[str]) -> None:
    """RED-LINE SELF-CHECK — verify staged changes touch ONLY risk_findings/.

    Aborts (fail-loud per 铁律 33) if ANY staged path is outside
    docs/research-kb/risk_findings/ OR matches a forbidden fragment. This is
    the core safety gate per PR #345 plan option B — the script must NEVER
    mutate .env / production code / configs.

    Raises:
        RuntimeError: staged change set violates the red-line boundary.
    """
    violations: list[str] = []
    for p in staged_paths:
        norm = p.replace("\\", "/")
        if not norm.startswith(_ALLOWED_PATH_PREFIX):
            violations.append(f"{p} (outside {_ALLOWED_PATH_PREFIX})")
            continue
        for frag in _FORBIDDEN_FRAGMENTS:
            if frag in norm:
                violations.append(f"{p} (forbidden fragment {frag!r})")
    if violations:
        raise RuntimeError(
            "RED-LINE SELF-CHECK FAILED — staged changes touch forbidden paths:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nThis script may ONLY touch docs/research-kb/risk_findings/. "
            "Aborting before any git push (反 silent .env / production mutation "
            "per ADR-022 + 铁律 35)."
        )


def generate_pr(*, repo_root: Path, dry_run: bool) -> int:
    """Generate a PR branch carrying pending approved candidate records.

    Returns process exit code (0 = success / 0-pending, 1 = error).
    """
    risk_findings_dir = repo_root / "docs" / "research-kb" / "risk_findings"
    pending = _scan_pending_approved(risk_findings_dir)

    if not pending:
        logger.info("[candidate-pr] 0 pending approved candidates — nothing to do.")
        return 0

    logger.info(
        "[candidate-pr] %d pending approved candidate(s): %s",
        len(pending),
        ", ".join(p.name for p in pending),
    )

    # Verify clean working tree before we start (反 mixing unrelated changes).
    dirty = _run_git(["status", "--porcelain"], repo_root=repo_root)
    if dirty:
        raise RuntimeError(
            "working tree not clean — commit / stash unrelated changes before "
            f"running this script:\n{dirty}"
        )

    # Mark each pending record pr_generated: true.
    for path in pending:
        _mark_pr_generated(path)

    branch_name = f"risk-candidate-pr-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    # From here on, any exception BEFORE git push must roll back the
    # _mark_pr_generated flips + unstage (反 unclean abort state — reviewer-fix
    # PR #346 MEDIUM 1). git push is the point-of-no-return — after push, the
    # branch carries the flipped records intentionally.
    try:
        # Stage ONLY the risk_findings/ records.
        for path in pending:
            rel = path.relative_to(repo_root)
            _run_git(["add", str(rel)], repo_root=repo_root)

        # RED-LINE SELF-CHECK — verify staged set touches ONLY risk_findings/.
        staged = _run_git(
            ["diff", "--cached", "--name-only"], repo_root=repo_root
        ).splitlines()
        _redline_self_check([s for s in staged if s.strip()])
        logger.info(
            "[candidate-pr] red-line self-check PASSED (%d staged paths)", len(staged)
        )

        if dry_run:
            logger.info(
                "[candidate-pr] --dry-run — staged %d record(s), red-line PASS, "
                "NOT creating branch / commit / push. Rolling back.",
                len(staged),
            )
            _rollback_marks(pending, repo_root=repo_root)
            return 0

        # Create branch + commit (NEVER merge — user 显式 merge sustained).
        _run_git(["checkout", "-b", branch_name], repo_root=repo_root)
        commit_msg = (
            f"chore(risk-candidate): sediment {len(pending)} approved RiskReflector "
            f"candidate(s) for user review\n\n"
            f"Auto-generated by scripts/generate_risk_candidate_pr.py (V3 §8.3 闭环).\n"
            f"Candidates are PROPOSALS — user reviews + merges this PR. NOT auto-applied.\n"
            f"Records: {', '.join(p.name for p in pending)}\n"
        )
        _run_git(["commit", "-m", commit_msg], repo_root=repo_root)
    except Exception:
        # Pre-push failure (red-line abort / git error) — restore clean state.
        logger.error(
            "[candidate-pr] pre-push failure — rolling back _mark_pr_generated "
            "flips + unstaging (反 unclean abort state)"
        )
        _rollback_marks(pending, repo_root=repo_root)
        raise

    # git push — point-of-no-return (branch carries the flipped records).
    _run_git(["push", "-u", "origin", branch_name], repo_root=repo_root)

    logger.info(
        "[candidate-pr] branch %s pushed. NEXT (user-driven, NOT this script):\n"
        "  gh pr create --title 'chore(risk-candidate): %d approved candidate(s)' "
        "--body '...'\n"
        "  → user reviews + merges (反 silent merge — script does branch+commit+push only)",
        branch_name,
        len(pending),
    )
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Generate a PR branch carrying approved RiskReflector candidates."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Full flow except git branch/commit/push (verification only).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repo root (default: scripts/.. = repo root).",
    )
    args = parser.parse_args()

    try:
        return generate_pr(repo_root=args.repo_root, dry_run=args.dry_run)
    except (RuntimeError, OSError) as exc:
        logger.error("[candidate-pr] FAILED: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
