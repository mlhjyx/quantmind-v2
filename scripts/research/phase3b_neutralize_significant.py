#!/usr/bin/env python3
"""Phase 3B Task 1: Neutralize 32 significant factors (|t|>2.5).

Serial processing to respect memory constraints (铁律9).
Pipeline per factor: MAD(5σ) → WLS(industry+mcap) → z-score clip(±3)

After completion:
  1. Run factor_health_check.py for validation
  2. Run build_backtest_cache.py for Parquet rebuild (铁律30)

Usage:
  python scripts/research/phase3b_neutralize_significant.py
  python scripts/research/phase3b_neutralize_significant.py --skip-existing
"""

import gc
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"

# 32 significant factors from IC quick-screen (|t| > 2.5)
SIGNIFICANT_FACTORS = [
    "high_low_range_20", "volatility_60", "turnover_std_20", "maxret_20",
    "CORD5", "turnover_f", "ivol_20", "gap_frequency_20",
    "atr_norm_20", "turnover_stability_20", "large_order_ratio", "RSQR30",
    "IMIN10", "HIGH0", "price_level_factor", "high_vol_price_ratio_20",
    "CORD20", "kbar_kup", "sp_ttm", "momentum_20",
    "gain_loss_ratio_20", "price_volume_corr_20", "reversal_60", "relative_volume_20",
    "rsrs_raw_18", "mf_divergence", "volume_std_20", "reversal_10",
    "momentum_10", "momentum_5", "reversal_5", "turnover_surge_ratio",
]


def check_already_neutralized(conn) -> set[str]:
    """Check which factors already have neutral_value populated."""
    cur = conn.cursor()
    already = set()
    for fname in SIGNIFICANT_FACTORS:
        cur.execute("""
            SELECT COUNT(*) FROM factor_values
            WHERE factor_name = %s
              AND neutral_value IS NOT NULL
              AND trade_date >= '2023-01-01'
            LIMIT 1
        """, (fname,))
        # Use EXISTS for speed
        cur.execute("""
            SELECT EXISTS(
                SELECT 1 FROM factor_values
                WHERE factor_name = %s
                  AND neutral_value IS NOT NULL
                  AND trade_date >= '2023-01-01'
            )
        """, (fname,))
        exists = cur.fetchone()[0]
        if exists:
            already.add(fname)
    return already


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 3B: Neutralize significant factors")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip factors that already have neutral_value")
    parser.add_argument("--start", default="2014-01-01", help="Start date")
    parser.add_argument("--end", default="2026-04-15", help="End date")
    args = parser.parse_args()

    # Import inside main to avoid circular imports at module level
    from engines.fast_neutralize import fast_neutralize_batch

    conn = psycopg2.connect(DB_CONN)
    t_total = time.time()

    print("=" * 70)
    print("  Phase 3B Task 1: Neutralize 32 Significant Factors")
    print(f"  Date range: {args.start} ~ {args.end}")
    print("=" * 70)

    # Check already neutralized
    factors_to_process = list(SIGNIFICANT_FACTORS)
    if args.skip_existing:
        already = check_already_neutralized(conn)
        if already:
            print(f"\n  Already neutralized ({len(already)}): {', '.join(sorted(already))}")
            factors_to_process = [f for f in factors_to_process if f not in already]

    print(f"\n  Factors to neutralize: {len(factors_to_process)}")
    if not factors_to_process:
        print("  Nothing to do!")
        conn.close()
        return

    # Serial neutralization (铁律9: max 2 heavy processes)
    results = {}
    for i, fname in enumerate(factors_to_process):
        t0 = time.time()
        print(f"\n── [{i+1}/{len(factors_to_process)}] {fname} ──")

        try:
            n_updated = fast_neutralize_batch(
                [fname],
                start_date=args.start,
                end_date=args.end,
                conn=conn,
                update_db=True,
                write_parquet=True,
            )
            elapsed = time.time() - t0
            results[fname] = {"status": "OK", "rows": n_updated, "time": elapsed}
            print(f"  {fname}: {n_updated:,} rows neutralized ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            results[fname] = {"status": "FAIL", "error": str(e)[:100], "time": elapsed}
            print(f"  {fname}: FAILED - {e}")

        # Memory cleanup between factors
        gc.collect()

    # Summary
    total_elapsed = time.time() - t_total
    ok_count = sum(1 for r in results.values() if r["status"] == "OK")
    fail_count = sum(1 for r in results.values() if r["status"] == "FAIL")
    total_rows = sum(r.get("rows", 0) for r in results.values())

    print("\n" + "=" * 70)
    print(f"  Neutralization Complete ({total_elapsed:.0f}s)")
    print(f"  OK: {ok_count}, FAIL: {fail_count}, Total rows: {total_rows:,}")
    print("=" * 70)

    for fname, r in results.items():
        status = "OK" if r["status"] == "OK" else "FAIL"
        rows = r.get("rows", 0)
        print(f"  {fname:>25s}: {status} | {rows:>10,} rows | {r['time']:.1f}s")

    if fail_count > 0:
        print(f"\n  WARNING: {fail_count} factors FAILED neutralization!")
        for fname, r in results.items():
            if r["status"] == "FAIL":
                print(f"    {fname}: {r['error']}")

    # NaN check (铁律29)
    print("\n── NaN Validation (铁律29) ──")
    cur = conn.cursor()
    nan_issues = []
    for fname in results:
        if results[fname]["status"] != "OK":
            continue
        cur.execute("""
            SELECT COUNT(*) FROM factor_values
            WHERE factor_name = %s AND neutral_value = 'NaN'
        """, (fname,))
        nan_count = cur.fetchone()[0]
        status = "PASS" if nan_count == 0 else f"FAIL ({nan_count} NaN)"
        print(f"  {fname:>25s}: {status}")
        if nan_count > 0:
            nan_issues.append(fname)

    if nan_issues:
        print(f"\n  CRITICAL: {len(nan_issues)} factors have NaN in neutral_value!")
    else:
        print(f"\n  All {ok_count} factors pass NaN check")

    conn.close()

    # Reminder for next steps
    print("\n" + "=" * 70)
    print("  NEXT STEPS:")
    print("  1. python scripts/factor_health_check.py " + " ".join(list(results.keys())[:5]) + " ...")
    print("  2. python scripts/build_backtest_cache.py  (铁律30)")
    print("=" * 70)


if __name__ == "__main__":
    main()
