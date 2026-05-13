#!/usr/bin/env python
"""V3 §13.2 daily metrics extraction CLI — S10 paper-mode 5d.

Usage:
    python scripts/v3_paper_mode_5d_extract_metrics.py [--date YYYY-MM-DD]

Default: aggregate metrics for yesterday (Asia/Shanghai). Designed to run
daily via Servy / Celery Beat post-market-close (~16:30).

Behavior:
  1. Connect to PG via app.services.db.get_sync_conn (sustained 8b/8c convention)
  2. aggregate_daily_metrics(conn, target_date) — runs all V3 §13.2 queries
  3. upsert_daily_metrics(conn, result) — UPSERT one row per date
  4. conn.commit() (caller transaction boundary per 铁律 32)
  5. Print summary to stdout for log capture

Exit codes:
  0: success
  1: DB error
  2: invalid args

铁律 22: doc 跟随代码 — ADR-062 §3 documents the daily cron contract.
铁律 32: this script owns commit boundary; PURE module does not commit.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _yesterday_shanghai() -> str:
    """Returns yesterday's date in Asia/Shanghai timezone as ISO string."""
    sh_now = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    return (sh_now.date() - timedelta(days=1)).isoformat()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="V3 §13.2 daily metrics extraction (S10 paper-mode 5d)"
    )
    parser.add_argument(
        "--date",
        default=_yesterday_shanghai(),
        help="Target date YYYY-MM-DD (default: yesterday, Asia/Shanghai)",
    )
    args = parser.parse_args()

    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError as e:
        logger.error("Invalid --date arg: %s", e)
        return 2

    # Lazy imports so the script can be argparse-tested without DB setup.
    from app.services.db import get_sync_conn  # type: ignore[import-not-found]
    from backend.qm_platform.risk.metrics import (
        aggregate_daily_metrics,
        upsert_daily_metrics,
    )

    conn = None
    try:
        conn = get_sync_conn()
        result = aggregate_daily_metrics(conn, target_date)
        rowcount = upsert_daily_metrics(conn, result)
        conn.commit()
        logger.info(
            "[extract-metrics] date=%s upserted=%d alerts_p0=%d staged=%d cost=%.4f",
            target_date,
            rowcount,
            result.alerts_p0_count,
            result.staged_plans_count,
            result.llm_cost_total,
        )
        return 0
    except Exception:
        logger.exception("[extract-metrics] failed")
        if conn is not None:
            conn.rollback()
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
