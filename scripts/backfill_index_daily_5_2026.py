"""One-shot backfill: index_daily 000300.SH for 2026-05-08 + 5-11~5-14.

Root cause (P0-4 真根因 surface 2026-05-17):
  signal_phase 5-11 ~ 5-15 连续 5 day fail (config_drift_ok sys.path drift) leave
  pt_data_service.fetch_daily_data._fetch_index() never running for those dates.
  index_daily for 5-08 + 5-11~5-14 missing → compute_daily_ic fwd_rets via CSI300
  benchmark → NaN → all CORE4 IC NaN for these dates.

  signal_phase fixed 2026-05-17 (PR #378), but historical index_daily 仍 gap.
  This one-shot backfills the gap from Tushare.

Usage:
    python scripts/backfill_index_daily_5_2026.py --dry-run
    python scripts/backfill_index_daily_5_2026.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")


from app.data_fetcher.data_loader import get_sync_conn  # noqa: E402
from app.data_fetcher.tushare_api import TushareAPI  # noqa: E402

# Gap dates (surfaced via P0-4 DB query 2026-05-17):
# trading_calendar shows these as trading days but index_daily 000300.SH missing.
GAP_DATES = [
    date(2026, 5, 8),
    date(2026, 5, 11),
    date(2026, 5, 12),
    date(2026, 5, 13),
    date(2026, 5, 14),
]

INDEX_CODE = "000300.SH"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="不写 DB, 仅报告")
    parser.add_argument("--apply", action="store_true", help="实际入库")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        parser.error("必须指定 --dry-run 或 --apply")

    api = TushareAPI()
    conn = get_sync_conn()

    print(f"=== index_daily {INDEX_CODE} backfill ({len(GAP_DATES)} dates) ===")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    total_pulled = 0
    total_upserted = 0
    for td in GAP_DATES:
        td_str = td.strftime("%Y%m%d")
        df = api.fetch_index_daily(INDEX_CODE, td_str, td_str)
        if df is None or df.empty:
            print(f"  {td}: Tushare 返空, SKIP")
            continue
        total_pulled += len(df)
        # 兼容 Tushare 返回字段
        for _, row in df.iterrows():
            row_td = row.get("trade_date")
            if isinstance(row_td, str) and len(row_td) == 8:
                # YYYYMMDD
                row_td_d = date(int(row_td[:4]), int(row_td[4:6]), int(row_td[6:8]))
            else:
                row_td_d = row_td
            print(f"  {row_td_d} close={row.get('close')} vol={row.get('vol')}")
            if args.apply:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO index_daily
                           (index_code, trade_date, open, high, low, close, pre_close,
                            pct_change, volume, amount)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (index_code, trade_date) DO UPDATE SET
                              open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                              close=EXCLUDED.close, pre_close=EXCLUDED.pre_close,
                              pct_change=EXCLUDED.pct_change,
                              volume=EXCLUDED.volume, amount=EXCLUDED.amount""",
                        (
                            INDEX_CODE,
                            row_td_d,
                            row.get("open"),
                            row.get("high"),
                            row.get("low"),
                            row.get("close"),
                            row.get("pre_close"),
                            row.get("pct_chg"),
                            row.get("vol"),
                            row.get("amount"),
                        ),
                    )
                total_upserted += 1
    if args.apply:
        conn.commit()
    conn.close()

    print(f"\n=== Summary: pulled={total_pulled}, upserted={total_upserted} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
