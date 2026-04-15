"""Phase 3E: IC quick-screen for 20 microstructure factors.

Reads raw_value from factor_values, computes Spearman Rank IC vs forward
excess return (20d horizon), using ic_calculator shared module (铁律19).

Usage:
    python scripts/research/phase3e_ic_screen.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.ic_calculator import (  # noqa: E402
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)
from phase3d_ml_synthesis import load_price_benchmark  # noqa: E402

ALL_FACTORS = [
    "intraday_skewness_20",
    "intraday_kurtosis_20",
    "high_freq_volatility_20",
    "updown_vol_ratio_20",
    "max_intraday_drawdown_20",
    "volume_concentration_20",
    "amihud_intraday_20",
    "volume_autocorr_20",
    "smart_money_ratio_20",
    "volume_return_corr_20",
    "open_drive_20",
    "close_drive_20",
    "morning_afternoon_ratio_20",
    "lunch_break_gap_20",
    "last_bar_volume_share_20",
    "variance_ratio_20",
    "price_path_efficiency_20",
    "autocorr_5min_20",
    "weighted_price_contribution_20",
    "intraday_reversal_strength_20",
]


def load_factor_from_db(factor_name: str, conn) -> pd.DataFrame:
    """Load a single factor's raw_value from factor_values."""
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, code, raw_value
        FROM factor_values
        WHERE factor_name = %s
          AND raw_value IS NOT NULL
          AND trade_date >= '2019-01-01'
        ORDER BY trade_date, code
    """, (factor_name,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return pd.DataFrame(columns=["trade_date", "code", "raw_value"])
    df = pd.DataFrame(rows, columns=["trade_date", "code", "raw_value"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["raw_value"] = pd.to_numeric(df["raw_value"], errors="coerce").astype(np.float64)
    return df


def main():
    from app.services.db import get_sync_conn

    print("=" * 70)
    print("Phase 3E: Microstructure Factor IC Quick-Screen")
    print("=" * 70)

    # 1. Load price + benchmark
    print("\nLoading price data...")
    t0 = time.time()
    price_df, bench_df = load_price_benchmark()

    # 2. Compute forward excess returns (20d horizon)
    print("Computing forward excess returns (horizon=20)...")
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=20, price_col="close")
    print(f"  Forward returns: {fwd_ret.shape} (dates x stocks)")
    print(f"  Data loaded in {time.time() - t0:.1f}s")

    # 3. Screen each factor
    conn = get_sync_conn()
    results = []

    for i, factor_name in enumerate(ALL_FACTORS, 1):
        t1 = time.time()
        print(f"\n[{i:2d}/20] {factor_name}...", end="", flush=True)

        try:
            factor_df = load_factor_from_db(factor_name, conn)
            if len(factor_df) < 10000:
                print(f" SKIP (only {len(factor_df):,} rows)")
                results.append({
                    "factor": factor_name,
                    "ic_mean": np.nan,
                    "ic_std": np.nan,
                    "ir": np.nan,
                    "t_stat": np.nan,
                    "hit_rate": np.nan,
                    "n_days": 0,
                    "status": "SKIP",
                })
                continue

            # Pivot to wide format
            factor_wide = factor_df.pivot_table(
                index="trade_date", columns="code", values="raw_value"
            )

            # Compute IC series
            ic_series = compute_ic_series(factor_wide, fwd_ret)

            if len(ic_series) < 30:
                print(f" SKIP (only {len(ic_series)} IC days)")
                results.append({
                    "factor": factor_name,
                    "ic_mean": np.nan,
                    "ic_std": np.nan,
                    "ir": np.nan,
                    "t_stat": np.nan,
                    "hit_rate": np.nan,
                    "n_days": len(ic_series),
                    "status": "SKIP",
                })
                continue

            stats = summarize_ic_stats(ic_series)
            elapsed = time.time() - t1

            status = "PASS" if abs(stats["t_stat"]) > 2.5 else "WEAK" if abs(stats["t_stat"]) > 1.5 else "FAIL"
            print(f" IC={stats['mean']:+.4f}, IR={stats['ir']:.3f}, "
                  f"t={stats['t_stat']:.2f}, hit={stats['hit_rate']:.1%}, "
                  f"n={stats['n_days']}, {elapsed:.1f}s → {status}")

            results.append({
                "factor": factor_name,
                "ic_mean": round(stats["mean"], 5),
                "ic_std": round(stats["std"], 5),
                "ir": round(stats["ir"], 4),
                "t_stat": round(stats["t_stat"], 2),
                "hit_rate": round(stats["hit_rate"], 4),
                "n_days": stats["n_days"],
                "status": status,
            })

        except Exception as e:
            print(f" ERROR: {e}")
            results.append({
                "factor": factor_name,
                "ic_mean": np.nan,
                "ic_std": np.nan,
                "ir": np.nan,
                "t_stat": np.nan,
                "hit_rate": np.nan,
                "n_days": 0,
                "status": "ERROR",
            })

    conn.close()

    # 4. Summary table
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("t_stat", key=abs, ascending=False)

    print(f"\n{'=' * 70}")
    print("IC QUICK-SCREEN SUMMARY (raw_value, 20d excess return)")
    print(f"{'=' * 70}")
    print(f"{'Factor':<35} {'IC':>8} {'IR':>7} {'t-stat':>7} {'Hit%':>6} {'Days':>5} {'Status':>6}")
    print("-" * 75)
    for _, r in results_df.iterrows():
        if pd.isna(r["ic_mean"]):
            print(f"{r['factor']:<35} {'—':>8} {'—':>7} {'—':>7} {'—':>6} {r['n_days']:>5} {r['status']:>6}")
        else:
            print(f"{r['factor']:<35} {r['ic_mean']:>+8.4f} {r['ir']:>7.3f} "
                  f"{r['t_stat']:>7.2f} {r['hit_rate']:>5.1%} {r['n_days']:>5} {r['status']:>6}")

    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_weak = sum(1 for r in results if r["status"] == "WEAK")
    print(f"\nPASS (|t|>2.5): {n_pass}/20, WEAK (|t|>1.5): {n_weak}/20")
    print("Note: This is raw IC. PASS factors need neutralized IC confirmation (铁律4).")

    # Save results
    out_path = Path("cache/phase3e/ic_screen_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
