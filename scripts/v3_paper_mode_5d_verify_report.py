#!/usr/bin/env python
"""V3 §15.4 paper-mode 5d acceptance verify CLI — S10.

Usage:
    python scripts/v3_paper_mode_5d_verify_report.py \\
        --window-end YYYY-MM-DD \\
        [--window-days 5] \\
        [--p0-false-positive-count N] \\
        [--meta-alert-p0-count N] \\
        [--out docs/audit/v3_tier_a_paper_mode_5d_<date>.md]

Behavior:
  1. Read risk_metrics_daily over the 5d window (window-end - 4 days .. window-end)
  2. Run V3 §15.4 4 acceptance items:
     a. P0 alert 误报率 < 30% (caller provides classified count)
     b. L1 detection latency P99 < 5s (per-day, max across window)
     c. L4 STAGED 流程闭环 0 失败 (status=FAILED count = 0)
     d. 元监控 0 P0 元告警 (caller provides; defaults 0 until §13.3 lands)
  3. Write markdown report to --out path
  4. Exit code 0 if all_pass else 1

铁律 22: doc 跟随代码 — ADR-062 §4 documents verify report contract.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="V3 §15.4 paper-mode 5d verify report (S10)")
    parser.add_argument(
        "--window-end",
        required=True,
        help="End date of 5d window (inclusive), YYYY-MM-DD",
    )
    parser.add_argument("--window-days", type=int, default=5, help="Window length (default 5)")
    parser.add_argument(
        "--p0-false-positive-count",
        type=int,
        default=0,
        help="Caller-classified P0 false positive count (default 0)",
    )
    parser.add_argument(
        "--meta-alert-p0-count",
        type=int,
        default=0,
        help="P0 元告警 count (default 0 until §13.3 lands)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output markdown path (default: print to stdout)",
    )
    args = parser.parse_args()

    try:
        window_end = datetime.strptime(args.window_end, "%Y-%m-%d").date()
    except ValueError as e:
        logger.error("Invalid --window-end arg: %s", e)
        return 2

    from app.services.db import get_sync_conn  # type: ignore[import-not-found]
    from backend.qm_platform.risk.metrics import generate_verify_report

    conn = None
    try:
        conn = get_sync_conn()
        report = generate_verify_report(
            conn,
            window_end=window_end,
            window_days=args.window_days,
            p0_false_positive_count=args.p0_false_positive_count,
            meta_alert_p0_count=args.meta_alert_p0_count,
        )
        md = report.to_markdown()

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            logger.info("[verify-report] written to %s", out_path)
        else:
            print(md)

        verdict = "PASS" if report.all_pass else "FAIL"
        logger.info(
            "[verify-report] verdict=%s items=%d missing_days=%d",
            verdict,
            len(report.items),
            len(report.missing_days),
        )
        return 0 if report.all_pass else 1
    except Exception:
        logger.exception("[verify-report] failed")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
