"""Phase 3E-II Track 2.2+2.3: Neutral IC comparison + CORE4 correlation.

For each of the 17 PASS microstructure factors:
1. Compute raw IC and neutral IC (铁律4: must compare both)
2. Flag factors where neutral IC decays >50% (fake alpha from size/industry)
3. Check correlation with CORE4 factors (|corr|>0.7 = redundant)
4. Check inter-factor correlation (avoid selecting correlated pairs)

Usage:
    python scripts/research/phase3e_neutral_eval.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)
from phase3d_ml_synthesis import load_price_benchmark

MICRO_FACTORS = [
    "intraday_skewness_20", "intraday_kurtosis_20", "high_freq_volatility_20",
    "updown_vol_ratio_20", "max_intraday_drawdown_20", "volume_concentration_20",
    "amihud_intraday_20", "volume_autocorr_20", "smart_money_ratio_20",
    "volume_return_corr_20", "open_drive_20", "close_drive_20",
    "morning_afternoon_ratio_20", "variance_ratio_20", "price_path_efficiency_20",
    "autocorr_5min_20", "weighted_price_contribution_20",
]

CORE4 = ["turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"]


def load_factor(factor_name: str, value_col: str, conn) -> pd.DataFrame:
    """Load factor from DB as wide DataFrame (dates x codes)."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT trade_date, code, {value_col}
        FROM factor_values
        WHERE factor_name = %s AND {value_col} IS NOT NULL
          AND trade_date >= '2019-01-01'
        ORDER BY trade_date, code
    """, (factor_name,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["trade_date", "code", "value"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(np.float64)
    return df.pivot_table(index="trade_date", columns="code", values="value")


def cross_section_corr(fa_wide: pd.DataFrame, fb_wide: pd.DataFrame, n_sample: int = 60) -> float:
    """Average cross-sectional Spearman correlation between two factors.

    Samples n_sample dates for speed.
    """
    common_dates = sorted(set(fa_wide.index) & set(fb_wide.index))
    if len(common_dates) < 30:
        return np.nan

    # Sample dates evenly
    if len(common_dates) > n_sample:
        idx = np.linspace(0, len(common_dates) - 1, n_sample, dtype=int)
        sample_dates = [common_dates[i] for i in idx]
    else:
        sample_dates = common_dates

    corrs = []
    for d in sample_dates:
        a = fa_wide.loc[d].dropna()
        b = fb_wide.loc[d].dropna()
        common = a.index.intersection(b.index)
        if len(common) < 100:
            continue
        r, _ = scipy_stats.spearmanr(a[common], b[common])
        if np.isfinite(r):
            corrs.append(r)

    return np.mean(corrs) if corrs else np.nan


def main():
    from app.services.db import get_sync_conn

    print("=" * 70)
    print("Phase 3E-II: Neutral IC Comparison + CORE4 Correlation")
    print("=" * 70)

    # 1. Load price + benchmark
    print("\nLoading price data...")
    t0 = time.time()
    price_df, bench_df = load_price_benchmark()
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=20, price_col="close")
    print(f"  Forward returns ready: {fwd_ret.shape}, {time.time() - t0:.0f}s")

    conn = get_sync_conn()

    # 2. Load CORE4 neutral values for correlation check
    print("\nLoading CORE4 factors...")
    core4_wide = {}
    for f in CORE4:
        w = load_factor(f, "neutral_value", conn)
        if not w.empty:
            core4_wide[f] = w
            print(f"  {f}: {w.shape}")

    # 3. Screen each microstructure factor
    print("\n" + "=" * 70)
    print("IC Comparison: Raw vs Neutral")
    print("=" * 70)

    ic_results = []
    neutral_wide_cache = {}  # For inter-factor correlation

    for i, fname in enumerate(MICRO_FACTORS, 1):
        t1 = time.time()
        print(f"\n[{i:2d}/17] {fname}")

        try:
            # Load raw and neutral
            raw_wide = load_factor(fname, "raw_value", conn)
            neutral_wide = load_factor(fname, "neutral_value", conn)

            if raw_wide.empty:
                print("  SKIP: no raw data")
                ic_results.append({"factor": fname, "status": "NO_DATA"})
                continue

            # Compute raw IC
            raw_ic = compute_ic_series(raw_wide, fwd_ret)
            raw_stats = summarize_ic_stats(raw_ic) if len(raw_ic) >= 30 else None

            # Compute neutral IC
            if neutral_wide.empty or neutral_wide.shape[0] < 30:
                print("  WARN: neutral_value not available, raw IC only")
                neutral_stats = None
                decay_pct = np.nan
            else:
                neutral_ic = compute_ic_series(neutral_wide, fwd_ret)
                neutral_stats = summarize_ic_stats(neutral_ic) if len(neutral_ic) >= 30 else None
                neutral_wide_cache[fname] = neutral_wide

                if raw_stats and neutral_stats and abs(raw_stats["mean"]) > 0.001:
                    decay_pct = 1 - abs(neutral_stats["mean"]) / abs(raw_stats["mean"])
                else:
                    decay_pct = np.nan

            # Determine status
            if raw_stats is None:
                status = "SKIP"
            elif neutral_stats and abs(neutral_stats["t_stat"]) > 2.5:
                status = "PASS" if decay_pct < 0.5 else "FAKE_ALPHA"
            elif raw_stats and abs(raw_stats["t_stat"]) > 2.5:
                status = "FAKE_ALPHA" if decay_pct >= 0.5 else "MARGINAL"
            else:
                status = "FAIL"

            row = {
                "factor": fname,
                "raw_ic": round(raw_stats["mean"], 5) if raw_stats else np.nan,
                "raw_t": round(raw_stats["t_stat"], 2) if raw_stats else np.nan,
                "neutral_ic": round(neutral_stats["mean"], 5) if neutral_stats else np.nan,
                "neutral_t": round(neutral_stats["t_stat"], 2) if neutral_stats else np.nan,
                "decay_pct": round(decay_pct, 3) if np.isfinite(decay_pct) else np.nan,
                "status": status,
            }
            ic_results.append(row)

            # Print summary
            r_ic = f"raw={raw_stats['mean']:+.4f}(t={raw_stats['t_stat']:.1f})" if raw_stats else "raw=N/A"
            n_ic = f"neu={neutral_stats['mean']:+.4f}(t={neutral_stats['t_stat']:.1f})" if neutral_stats else "neu=N/A"
            d_str = f"decay={decay_pct:.0%}" if np.isfinite(decay_pct) else "decay=N/A"
            print(f"  {r_ic} | {n_ic} | {d_str} → {status} ({time.time() - t1:.0f}s)")

        except Exception as e:
            print(f"  ERROR: {e}")
            ic_results.append({"factor": fname, "status": "ERROR", "error": str(e)})

    # 4. Save IC results
    ic_df = pd.DataFrame(ic_results)
    out_dir = Path("cache/phase3e")
    out_dir.mkdir(parents=True, exist_ok=True)
    ic_df.to_csv(out_dir / "ic_neutral_screen.csv", index=False)
    print("\nIC results saved to cache/phase3e/ic_neutral_screen.csv")

    # Summary
    print("\n" + "=" * 70)
    print("IC Summary")
    print("=" * 70)
    for _, r in ic_df.iterrows():
        s = r.get("status", "?")
        marker = "✅" if s == "PASS" else "❌" if s in ("FAIL", "FAKE_ALPHA") else "⚠️"
        print(f"  {marker} {r['factor']}: {s}")

    pass_factors = [r["factor"] for _, r in ic_df.iterrows() if r.get("status") == "PASS"]
    print(f"\n{len(pass_factors)} factors PASS neutral IC screen")

    if not pass_factors:
        print("\nNo factors survived — skipping correlation check")
        conn.close()
        return

    # 5. Correlation with CORE4
    print("\n" + "=" * 70)
    print("CORE4 Correlation Check (|corr|>0.7 = redundant)")
    print("=" * 70)

    corr_results = []
    for fname in pass_factors:
        if fname not in neutral_wide_cache:
            continue
        fw = neutral_wide_cache[fname]
        for c4 in CORE4:
            if c4 not in core4_wide:
                continue
            corr = cross_section_corr(fw, core4_wide[c4])
            corr_results.append({"factor": fname, "core4": c4, "corr": round(corr, 4)})
            redundant = "⚠️ REDUNDANT" if abs(corr) > 0.7 else ""
            print(f"  {fname} vs {c4}: {corr:+.3f} {redundant}")

    # 6. Inter-factor correlation
    print("\n" + "=" * 70)
    print("Inter-factor Correlation (among PASS factors)")
    print("=" * 70)

    for i, f1 in enumerate(pass_factors):
        for f2 in pass_factors[i + 1:]:
            if f1 in neutral_wide_cache and f2 in neutral_wide_cache:
                corr = cross_section_corr(neutral_wide_cache[f1], neutral_wide_cache[f2])
                corr_results.append({"factor": f1, "core4": f2, "corr": round(corr, 4)})
                tag = "⚠️ HIGH" if abs(corr) > 0.7 else ""
                print(f"  {f1} vs {f2}: {corr:+.3f} {tag}")

    # Save correlation results
    corr_df = pd.DataFrame(corr_results)
    corr_df.to_csv(out_dir / "correlation_matrix.csv", index=False)
    print("\nCorrelation results saved to cache/phase3e/correlation_matrix.csv")

    conn.close()
    print(f"\n=== Done in {time.time() - t0:.0f}s ===")


if __name__ == "__main__":
    main()
