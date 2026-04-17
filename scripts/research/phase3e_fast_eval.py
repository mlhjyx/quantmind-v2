"""Phase 3E-II: Fast in-memory neutral IC evaluation.

Skips DB UPDATE — loads raw_value, neutralizes in-memory, computes IC directly.
Much faster than waiting for fast_neutralize_batch DB writes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from engines.factor_engine import preprocess_pipeline
from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

MICRO_FACTORS = [
    "intraday_skewness_20", "intraday_kurtosis_20", "high_freq_volatility_20",
    "updown_vol_ratio_20", "max_intraday_drawdown_20", "volume_concentration_20",
    "amihud_intraday_20", "volume_autocorr_20", "smart_money_ratio_20",
    "volume_return_corr_20", "open_drive_20", "close_drive_20",
    "morning_afternoon_ratio_20", "variance_ratio_20", "price_path_efficiency_20",
    "autocorr_5min_20", "weighted_price_contribution_20",
]

CORE4 = ["turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"]


def load_shared_data(conn):
    """Load industry + ln_mcap for all dates (shared across factors)."""
    print("  Loading symbols (industry)...")
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols")
    sym_df = pd.DataFrame(cur.fetchall(), columns=["code", "industry_sw1"])
    industry = sym_df.set_index("code")["industry_sw1"].fillna("其他")

    print("  Loading daily_basic (market cap)...")
    cur.execute("""
        SELECT code, trade_date, total_mv FROM daily_basic
        WHERE trade_date >= '2019-01-01' AND total_mv > 0
    """)
    mcap_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "total_mv"])
    mcap_df["trade_date"] = pd.to_datetime(mcap_df["trade_date"]).dt.date
    mcap_df["ln_mcap"] = np.log(mcap_df["total_mv"].astype(float) + 1e-12)
    cur.close()
    return industry, mcap_df


def load_raw_factor(factor_name: str, conn) -> pd.DataFrame:
    """Load raw_value as long DataFrame."""
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, code, raw_value FROM factor_values
        WHERE factor_name = %s AND raw_value IS NOT NULL
          AND trade_date >= '2019-01-01'
        ORDER BY trade_date, code
    """, (factor_name,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["trade_date", "code", "raw_value"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["raw_value"] = pd.to_numeric(df["raw_value"], errors="coerce").astype(np.float64)
    return df


def neutralize_in_memory(factor_long: pd.DataFrame, industry: pd.Series, mcap_df: pd.DataFrame) -> pd.DataFrame:
    """Neutralize factor cross-sectionally per date, returning wide DataFrame."""
    # Sample dates for speed (monthly)
    dates = sorted(factor_long["trade_date"].unique())
    # Use every 20th date (~monthly) for IC evaluation
    sampled = dates[::20]

    raw_wide_rows = []
    neutral_wide_rows = []

    for d in sampled:
        day_data = factor_long[factor_long["trade_date"] == d].set_index("code")["raw_value"]
        if len(day_data) < 200:
            continue

        # Get industry and ln_mcap for this date
        day_mcap = mcap_df[mcap_df["trade_date"] == d].set_index("code")["ln_mcap"]
        common = day_data.index.intersection(day_mcap.index).intersection(industry.index)
        if len(common) < 200:
            continue

        raw_val, neutral_val = preprocess_pipeline(
            day_data[common], day_mcap[common], industry[common]
        )

        raw_wide_rows.append(pd.Series(raw_val, name=d))
        neutral_wide_rows.append(pd.Series(neutral_val, name=d))

    raw_wide = pd.DataFrame(raw_wide_rows) if raw_wide_rows else pd.DataFrame()
    neutral_wide = pd.DataFrame(neutral_wide_rows) if neutral_wide_rows else pd.DataFrame()
    return raw_wide, neutral_wide


def cross_section_corr(fa_wide: pd.DataFrame, fb_wide: pd.DataFrame, n_sample: int = 40) -> float:
    """Average cross-sectional Spearman correlation."""
    common_dates = sorted(set(fa_wide.index) & set(fb_wide.index))
    if len(common_dates) < 20:
        return np.nan
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
    print("Phase 3E-II: Fast In-Memory Neutral IC Evaluation")
    print("=" * 70)

    t0 = time.time()
    conn = get_sync_conn()

    # 1. Load shared data
    print("\n[Step 1] Loading shared data...")
    industry, mcap_df = load_shared_data(conn)
    print(f"  Industry: {len(industry)} codes, MCap: {len(mcap_df):,} rows")

    # 2. Load price + benchmark for IC
    print("\n[Step 2] Loading price data for IC...")
    from phase3d_ml_synthesis import load_price_benchmark
    price_df, bench_df = load_price_benchmark()
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=20, price_col="close")
    print(f"  Forward returns: {fwd_ret.shape}")
    print(f"  Shared data loaded in {time.time() - t0:.0f}s")

    # 3. Evaluate each factor
    print("\n" + "=" * 70)
    print("[Step 3] IC Comparison: Raw vs Neutral (sampled monthly)")
    print("=" * 70)

    ic_results = []
    neutral_cache = {}  # For correlation check

    for i, fname in enumerate(MICRO_FACTORS, 1):
        t1 = time.time()
        print(f"\n[{i:2d}/17] {fname}...", flush=True)

        factor_long = load_raw_factor(fname, conn)
        if factor_long.empty or len(factor_long) < 10000:
            print(f"  SKIP: insufficient data ({len(factor_long)} rows)")
            ic_results.append({"factor": fname, "status": "NO_DATA"})
            continue

        # Neutralize in memory
        raw_wide, neutral_wide = neutralize_in_memory(factor_long, industry, mcap_df)
        if raw_wide.empty or neutral_wide.empty or len(raw_wide) < 30:
            print("  SKIP: insufficient dates after neutralization")
            ic_results.append({"factor": fname, "status": "INSUFFICIENT"})
            continue

        # Compute IC for both
        raw_ic = compute_ic_series(raw_wide, fwd_ret)
        neutral_ic = compute_ic_series(neutral_wide, fwd_ret)

        raw_stats = summarize_ic_stats(raw_ic) if len(raw_ic) >= 20 else None
        neutral_stats = summarize_ic_stats(neutral_ic) if len(neutral_ic) >= 20 else None

        # Decay calculation
        decay_pct = np.nan
        if raw_stats and neutral_stats and abs(raw_stats["mean"]) > 0.001:
            decay_pct = 1 - abs(neutral_stats["mean"]) / abs(raw_stats["mean"])

        # Status
        if neutral_stats and abs(neutral_stats["t_stat"]) > 2.5:
            status = "PASS" if (np.isnan(decay_pct) or decay_pct < 0.5) else "FAKE_ALPHA"
        elif raw_stats and abs(raw_stats["t_stat"]) > 2.5:
            status = "FAKE_ALPHA" if (not np.isnan(decay_pct) and decay_pct >= 0.5) else "MARGINAL"
        else:
            status = "FAIL"

        row = {
            "factor": fname,
            "raw_ic": round(raw_stats["mean"], 5) if raw_stats else np.nan,
            "raw_t": round(raw_stats["t_stat"], 2) if raw_stats else np.nan,
            "neutral_ic": round(neutral_stats["mean"], 5) if neutral_stats else np.nan,
            "neutral_t": round(neutral_stats["t_stat"], 2) if neutral_stats else np.nan,
            "decay_pct": round(decay_pct, 3) if np.isfinite(decay_pct) else np.nan,
            "n_dates": len(raw_ic),
            "status": status,
        }
        ic_results.append(row)
        if status in ("PASS", "MARGINAL"):
            neutral_cache[fname] = neutral_wide

        r_str = f"raw={raw_stats['mean']:+.4f}(t={raw_stats['t_stat']:.1f})" if raw_stats else "raw=N/A"
        n_str = f"neu={neutral_stats['mean']:+.4f}(t={neutral_stats['t_stat']:.1f})" if neutral_stats else "neu=N/A"
        d_str = f"decay={decay_pct:.0%}" if np.isfinite(decay_pct) else ""
        print(f"  {r_str} | {n_str} | {d_str} → {status} ({time.time()-t1:.0f}s)")

    # 4. Save IC results
    ic_df = pd.DataFrame(ic_results)
    out_dir = Path("cache/phase3e")
    out_dir.mkdir(parents=True, exist_ok=True)
    ic_df.to_csv(out_dir / "ic_neutral_screen.csv", index=False)

    print("\n" + "=" * 70)
    print("IC Summary")
    print("=" * 70)
    for _, r in ic_df.iterrows():
        s = r.get("status", "?")
        marker = {"PASS": "✅", "FAIL": "❌", "FAKE_ALPHA": "❌", "MARGINAL": "⚠️"}.get(s, "?")
        raw_str = f"raw={r.get('raw_ic', 'N/A')}" if pd.notna(r.get("raw_ic")) else ""
        neu_str = f"neu={r.get('neutral_ic', 'N/A')}" if pd.notna(r.get("neutral_ic")) else ""
        print(f"  {marker} {r['factor']}: {s} {raw_str} {neu_str}")

    pass_factors = [r["factor"] for _, r in ic_df.iterrows() if r.get("status") == "PASS"]
    marginal = [r["factor"] for _, r in ic_df.iterrows() if r.get("status") == "MARGINAL"]
    print(f"\n{len(pass_factors)} PASS, {len(marginal)} MARGINAL")

    # 5. Correlation with CORE4
    check_factors = pass_factors + marginal
    if not check_factors:
        print("\nNo factors survived — skipping correlation check")
        conn.close()
        return

    print("\n" + "=" * 70)
    print("[Step 4] CORE4 Correlation (|corr|>0.7 = redundant)")
    print("=" * 70)

    # Load CORE4 neutral values
    core4_wide = {}
    for f in CORE4:
        fl = load_raw_factor(f, conn)  # Will use raw for CORE4 too
        if not fl.empty:
            _, nw = neutralize_in_memory(fl, industry, mcap_df)
            if not nw.empty:
                core4_wide[f] = nw

    corr_results = []
    redundant_factors = set()
    for fname in check_factors:
        if fname not in neutral_cache:
            continue
        for c4 in CORE4:
            if c4 not in core4_wide:
                continue
            corr = cross_section_corr(neutral_cache[fname], core4_wide[c4])
            corr_results.append({"factor": fname, "vs": c4, "corr": round(corr, 4)})
            tag = "⚠️ REDUNDANT" if abs(corr) > 0.7 else ""
            if abs(corr) > 0.7:
                redundant_factors.add(fname)
            print(f"  {fname} vs {c4}: {corr:+.3f} {tag}")

    # Inter-factor correlation
    print("\n" + "=" * 70)
    print("[Step 5] Inter-factor Correlation")
    print("=" * 70)
    for i, f1 in enumerate(check_factors):
        for f2 in check_factors[i + 1:]:
            if f1 in neutral_cache and f2 in neutral_cache:
                corr = cross_section_corr(neutral_cache[f1], neutral_cache[f2])
                corr_results.append({"factor": f1, "vs": f2, "corr": round(corr, 4)})
                tag = "⚠️ HIGH" if abs(corr) > 0.7 else ""
                print(f"  {f1} vs {f2}: {corr:+.3f} {tag}")

    corr_df = pd.DataFrame(corr_results)
    corr_df.to_csv(out_dir / "correlation_matrix.csv", index=False)

    # Final summary
    survivors = [f for f in check_factors if f not in redundant_factors]
    print(f"\n{'=' * 70}")
    print(f"Final: {len(survivors)} independent factors survive")
    print(f"  Redundant (corr>0.7 with CORE4): {redundant_factors or 'none'}")
    print(f"  Survivors: {survivors or 'none'}")
    print(f"Total time: {time.time() - t0:.0f}s")

    conn.close()


if __name__ == "__main__":
    main()
