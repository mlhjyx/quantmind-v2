#!/usr/bin/env python3
"""iter 174 MVP 4.7 Chunk 1 — BGE-M3 embedding backfill standalone CLI.

Wraps `app.tasks.embedding_backfill_tasks.backfill_risk_memory_embeddings`
for manual / schtask / one-shot invocation outside the Celery Beat schedule.

Idempotent — safe to re-run; partial completion handled by NULL guards.

Usage:
    python scripts/backfill_risk_memory_embeddings.py
    python scripts/backfill_risk_memory_embeddings.py --batch-size 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# Canonical sys.path order: PROJECT_ROOT first, then BACKEND_DIR (LL-175).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

import structlog  # noqa: E402

from app.tasks.embedding_backfill_tasks import (  # noqa: E402
    backfill_risk_memory_embeddings,
)

logger = structlog.get_logger("backfill_risk_memory_embeddings")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill BGE-M3 embeddings for risk_memory rows where embedding IS NULL"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Max rows per invocation (default 100). Re-run for larger backfills.",
    )
    args = parser.parse_args()

    result = backfill_risk_memory_embeddings(batch_size=args.batch_size)
    logger.info("[backfill-cli] %s", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
