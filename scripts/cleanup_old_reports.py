#!/usr/bin/env python3
"""Reports artifact retention CLI (iter 31 — closes iter 30 P2-8 reviewer note).

Walks `reports/` and applies a 2-rule retention policy per (strategy_id,
execution_mode) tuple inferred from filename `{sid}_{date}_{mode}.json`:

  Rule 1 (count): keep latest N per (sid, mode); delete oldest beyond N.
  Rule 2 (age):   delete any file older than `--max-age-days` regardless of count.

A file is deleted only if it matches BOTH rules' delete predicates (i.e.,
count-policy decides "older than position N" AND age-policy says ">N days old")?
NO — per design, EITHER trigger qualifies for deletion (union, not intersection).
This is the safer retention semantic: keep-recent OR keep-within-age, drop only
the union of "beyond count" + "beyond age".

Defaults sustained from iter 30 P2-8 reviewer note:
  - `--max-age-days 90`  (drop > 90 days regardless of count)
  - `--keep-per-tuple 20` (keep latest 20 per (sid, mode))

Files that don't match the `{sid}_{date_iso}_{mode}.json` pattern are IGNORED
(reports/ has pre-existing unrelated artifacts from earlier sprints — see
`ls reports/` for examples like DATA_SYSTEM_V1_COMPLETION.md, p0_*.json, etc.
Those are not iter-30 report artifacts and must not be touched.

铁律 33: silent failure ban — any unrecognized file logged as INFO + skipped, NOT
silently ignored. Errors during delete logged + re-raised (反 silent dataloss).
铁律 43-c: stderr boot probe + top-level try/except.
铁律 43-d: exit code 0 = success / 1 = no-op (nothing to delete) / 2 = fatal.

Trigger source: iter 30 PR #459 reviewer P2-8 ("reports/ dir will grow unbounded
~36k files/year @ 100 strategies daily cadence; flag for future Beat cleanup task").

Usage:
    # Dry-run (default --no-delete behavior is `delete=False`)
    python scripts/cleanup_old_reports.py --dry-run

    # Real delete
    python scripts/cleanup_old_reports.py

    # Custom thresholds
    python scripts/cleanup_old_reports.py --max-age-days 60 --keep-per-tuple 10

    # Override reports dir (for testing / non-standard install)
    python scripts/cleanup_old_reports.py --reports-dir D:\\path\\to\\reports
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import traceback
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"

# Pattern: {strategy_id}_{YYYY-MM-DD}_{mode}.json
# strategy_id can contain hyphens (UUID style); mode is paper or live.
# Anchored to filename only (NOT path) — caller passes filename to .match().
ARTIFACT_PATTERN = re.compile(
    r"^(?P<sid>[A-Za-z0-9_-]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<mode>paper|live)\.json$"
)

logger = logging.getLogger(__name__)


def _classify(path: Path) -> tuple[str, str, datetime] | None:
    """Parse a filename into (sid, mode, date) or None if not an artifact.

    Returns None for files NOT matching the iter-30 artifact pattern; caller
    treats those as untouchable (sustained pre-existing reports/ residents).
    """
    m = ARTIFACT_PATTERN.match(path.name)
    if not m:
        return None
    try:
        d = datetime.strptime(m.group("date"), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None  # malformed date string → treat as non-artifact
    return m.group("sid"), m.group("mode"), d


def compute_deletes(
    reports_dir: Path,
    *,
    max_age_days: int,
    keep_per_tuple: int,
    now: datetime | None = None,
) -> tuple[list[Path], list[Path]]:
    """Compute (deletes, skipped_non_artifacts) without touching the filesystem.

    Args:
        reports_dir: directory to scan.
        max_age_days: drop files older than this many days (UTC).
        keep_per_tuple: per (sid, mode) keep latest N; oldest beyond N → drop.
        now: injection point for tests; defaults to datetime.now(UTC).

    Returns:
        (deletes, skipped_non_artifacts) — both lists of Paths.
        deletes = union of age-rule + count-rule predicates.
        skipped_non_artifacts = files in reports/ that don't match pattern.
    """
    if max_age_days < 1:
        raise ValueError(f"max_age_days must be >= 1, got {max_age_days}")
    if keep_per_tuple < 1:
        raise ValueError(f"keep_per_tuple must be >= 1, got {keep_per_tuple}")

    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(days=max_age_days)

    skipped_non_artifacts: list[Path] = []
    # group artifact paths by (sid, mode), each with parsed datetime
    grouped: dict[tuple[str, str], list[tuple[Path, datetime]]] = defaultdict(list)

    for path in reports_dir.iterdir():
        if not path.is_file():
            continue
        classified = _classify(path)
        if classified is None:
            skipped_non_artifacts.append(path)
            continue
        sid, mode, file_date = classified
        grouped[(sid, mode)].append((path, file_date))

    deletes_set: set[Path] = set()
    # Age rule: drop everything < cutoff (regardless of group / count).
    # Count rule: per (sid, mode), sort DESC, drop oldest beyond keep_per_tuple.
    for (sid, mode), entries in grouped.items():
        entries.sort(key=lambda x: x[1], reverse=True)  # newest first
        for idx, (path, file_date) in enumerate(entries):
            # Union semantic: age-rule (file_date < cutoff) OR count-rule
            # (idx >= keep_per_tuple position from newest-first). Either trigger
            # qualifies the file for deletion.
            if file_date < cutoff or idx >= keep_per_tuple:
                deletes_set.add(path)

    # Stable order (alpha) for deterministic test + log output
    deletes = sorted(deletes_set, key=lambda p: p.name)
    return deletes, skipped_non_artifacts


def execute_deletes(paths: list[Path]) -> tuple[int, list[tuple[Path, str]]]:
    """Apply deletes, returning (success_count, failures).

    failures = [(path, error_msg), ...] — each delete error captured but
    iteration continues (反 partial-cleanup half-state).
    """
    success = 0
    failures: list[tuple[Path, str]] = []
    for path in paths:
        try:
            os.unlink(path)
            success += 1
        except OSError as e:
            failures.append((path, f"{type(e).__name__}: {e}"))
            logger.error("delete failed: %s -> %s", path, e)
    return success, failures


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Reports artifact retention cleanup (iter 31, closes iter 30 P2-8)"
    )
    p.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"reports dir to scan (default: {DEFAULT_REPORTS_DIR})",
    )
    p.add_argument(
        "--max-age-days",
        type=int,
        default=90,
        help="drop files older than N days (default: 90)",
    )
    p.add_argument(
        "--keep-per-tuple",
        type=int,
        default=20,
        help="keep latest N per (sid, mode) tuple (default: 20)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned deletes without executing (alias for legacy callers)",
    )
    return p


def main() -> int:
    """Entry point — exit 0 success / 1 nothing-to-delete / 2 fatal."""
    print(
        f"[reports-cleanup] boot {datetime.now(UTC).isoformat()} pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    args = _arg_parser().parse_args()

    try:
        reports_dir = args.reports_dir
        if not reports_dir.exists():
            logger.info("reports dir does not exist: %s (nothing to clean)", reports_dir)
            return 1

        deletes, skipped = compute_deletes(
            reports_dir,
            max_age_days=args.max_age_days,
            keep_per_tuple=args.keep_per_tuple,
        )

        logger.info(
            "scan complete: reports_dir=%s artifact_deletes=%d skipped_non_artifacts=%d",
            reports_dir,
            len(deletes),
            len(skipped),
        )
        for path in deletes:
            logger.info("  DELETE candidate: %s", path.name)
        if skipped:
            logger.info("  skipped (non-artifact pattern): %d files", len(skipped))

        if args.dry_run:
            logger.info("--dry-run: NOT executing deletes")
            return 0 if deletes else 1

        if not deletes:
            logger.info("nothing to delete")
            return 1

        success, failures = execute_deletes(deletes)
        logger.info("delete result: success=%d failures=%d", success, len(failures))

        if failures:
            # 反 silent partial cleanup — return fatal if ANY delete failed.
            print(
                f"[reports-cleanup] FATAL: {len(failures)} delete(s) failed",
                file=sys.stderr,
                flush=True,
            )
            return 2

        return 0

    except Exception as e:
        print(
            f"[reports-cleanup] FATAL: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
