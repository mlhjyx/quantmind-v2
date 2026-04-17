"""Phase 3E-II Track 2.4: Noise robustness for microstructure factors.

Reuses in-memory neutralization from phase3e_fast_eval.py.
Tests both 5% and 20% noise levels per 铁律20.

Criteria:
  5% noise retention < 0.95 -> WARNING
  20% noise retention < 0.50 -> FRAGILE, exclude from Active pool
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from engines.factor_engine import preprocess_pipeline
from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

RNG_SEED = 42
HORIZON = 20
OUT_DIR = Path("cache/phase3e")

# 16 PASS factors from ic_neutral_screen.csv (amihud_intraday_20 excluded = FAIL)
PASS_FACTORS = [
    "intraday_skewness_20", "intraday_kurtosis_20", "high_freq_volatility_20",
    "updown_vol_ratio_20", "max_intraday_drawdown_20", "volume_concentration_20",
    "volume_autocorr_20", "smart_money_ratio_20", "volume_return_corr_20",
    "open_drive_20", "close_drive_20", "morning_afternoon_ratio_20",
    "variance_ratio_20", "price_path_efficiency_20", "autocorr_5min_20",
    "weighted_price_contribution_20",
]

CORE4 = ["turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"]


def load_shared_data(conn):
    """Load industry + ln_mcap for neutralization."""
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols")
    sym_df = pd.DataFrame(cur.fetchall(), columns=["code", "industry_sw1"])
    industry = sym_df.set_index("code")["industry_sw1"].fillna("其他")

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
    """Load raw_value from DB."""
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


def neutralize_in_memory(factor_long, industry, mcap_df, sample_step=20):
    """Neutralize factor cross-sectionally, return wide DataFrame (sampled dates)."""
    dates = sorted(factor_long["trade_date"].unique())
    sampled = dates[::sample_step]

    rows = []
    for d in sampled:
        day_data = factor_long[factor_long["trade_date"] == d].set_index("code")["raw_value"]
        if len(day_data) < 200:
            continue
        day_mcap = mcap_df[mcap_df["trade_date"] == d].set_index("code")["ln_mcap"]
        common = day_data.index.intersection(day_mcap.index).intersection(industry.index)
        if len(common) < 200:
            continue
        _, neutral_val = preprocess_pipeline(day_data[common], day_mcap[common], industry[common])
        rows.append(pd.Series(neutral_val, name=d))

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def add_gaussian_noise(factor_wide: pd.DataFrame, noise_pct: float, rng) -> pd.DataFrame:
    """Add cross-sectional Gaussian noise independently per date."""
    result = factor_wide.copy()
    for td in result.index:
        row = result.loc[td].dropna()
        if len(row) < 5:
            continue
        sigma = float(row.std()) * noise_pct
        if sigma <= 0:
            continue
        noise = rng.normal(0, sigma, size=len(row))
        result.loc[td, row.index] = row.values + noise
    return result


def test_noise(neutral_wide, fwd_ret, noise_pct, rng):
    """Compute clean IC, noisy IC, retention."""
    common = neutral_wide.index.intersection(fwd_ret.index)
    if len(common) < 30:
        return None

    fw = neutral_wide.loc[common]
    fr = fwd_ret.loc[common]

    clean_ic = compute_ic_series(fw, fr)
    clean_stats = summarize_ic_stats(clean_ic) if len(clean_ic) >= 20 else None
    if not clean_stats or abs(clean_stats["mean"]) < 0.001:
        return None

    noisy_wide = add_gaussian_noise(fw, noise_pct, rng)
    noisy_ic = compute_ic_series(noisy_wide, fr)
    noisy_stats = summarize_ic_stats(noisy_ic) if len(noisy_ic) >= 20 else None
    if not noisy_stats:
        return None

    retention = abs(noisy_stats["mean"]) / abs(clean_stats["mean"])
    return {
        "clean_ic": round(clean_stats["mean"], 5),
        "noisy_ic": round(noisy_stats["mean"], 5),
        "clean_t": round(clean_stats["t_stat"], 2),
        "noisy_t": round(noisy_stats["t_stat"], 2),
        "retention": round(retention, 4),
    }


def main():
    from app.services.db import get_sync_conn

    print("=" * 70)
    print("Phase 3E-II Track 2.4: Noise Robustness (铁律20)")
    print("=" * 70)

    t0 = time.time()
    conn = get_sync_conn()

    # 1. Load shared data
    print("\n[Step 1] Loading shared data...")
    industry, mcap_df = load_shared_data(conn)

    # 2. Load price for IC
    print("[Step 2] Loading price data...")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from phase3d_ml_synthesis import load_price_benchmark
    price_df, bench_df = load_price_benchmark()
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=HORIZON, price_col="close")
    print(f"  Shared data ready in {time.time() - t0:.0f}s")

    # 3. Test each factor at 5% and 20% noise
    print(f"\n{'=' * 70}")
    print(f"Testing {len(PASS_FACTORS)} PASS factors at 5% and 20% noise")
    print(f"{'=' * 70}")

    rng_5 = np.random.default_rng(RNG_SEED)
    rng_20 = np.random.default_rng(RNG_SEED + 1)

    results = []
    for i, fname in enumerate(PASS_FACTORS, 1):
        t1 = time.time()
        print(f"\n[{i:2d}/16] {fname}...", flush=True)

        factor_long = load_raw_factor(fname, conn)
        if factor_long.empty:
            print("  SKIP: no data")
            continue

        neutral_wide = neutralize_in_memory(factor_long, industry, mcap_df)
        if neutral_wide.empty or len(neutral_wide) < 30:
            print("  SKIP: insufficient neutralized dates")
            continue

        r5 = test_noise(neutral_wide, fwd_ret, 0.05, rng_5)
        r20 = test_noise(neutral_wide, fwd_ret, 0.20, rng_20)

        if r5 is None or r20 is None:
            print("  SKIP: IC computation failed")
            continue

        # Status per 铁律20
        warn_5 = r5["retention"] < 0.95
        fragile_20 = r20["retention"] < 0.50
        status = "FRAGILE" if fragile_20 else ("WARN" if warn_5 else "ROBUST")

        row = {
            "factor": fname,
            "clean_ic": r5["clean_ic"],
            "noise_5pct_ic": r5["noisy_ic"],
            "retention_5pct": r5["retention"],
            "noise_20pct_ic": r20["noisy_ic"],
            "retention_20pct": r20["retention"],
            "status": status,
        }
        results.append(row)

        s5 = f"5%={r5['retention']:.3f}" + (" !" if warn_5 else "")
        s20 = f"20%={r20['retention']:.3f}" + (" FRAGILE" if fragile_20 else "")
        print(f"  clean={r5['clean_ic']:+.4f} | {s5} | {s20} -> {status} ({time.time()-t1:.0f}s)")

    # 4. Save results
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results_df = pd.DataFrame(results)
    results_df.to_csv(OUT_DIR / "noise_robustness.csv", index=False)

    # Also save JSON for downstream
    summary = {
        "noise_levels": [0.05, 0.20],
        "rng_seed": RNG_SEED,
        "horizon": HORIZON,
        "total": len(results),
        "robust": sum(1 for r in results if r["status"] == "ROBUST"),
        "warn": sum(1 for r in results if r["status"] == "WARN"),
        "fragile": sum(1 for r in results if r["status"] == "FRAGILE"),
        "results": results,
    }
    (OUT_DIR / "noise_robustness.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    # 5. Summary table
    print(f"\n{'=' * 70}")
    print("Noise Robustness Summary")
    print(f"{'=' * 70}")
    print(f"  {'Factor':<32} {'Clean IC':>9} {'5% Ret':>8} {'20% Ret':>8} {'Status':>8}")
    print(f"  {'-' * 68}")
    for r in sorted(results, key=lambda x: x["retention_20pct"], reverse=True):
        marker = {"ROBUST": "", "WARN": " !", "FRAGILE": " XX"}[r["status"]]
        print(f"  {r['factor']:<32} {r['clean_ic']:>+9.4f} {r['retention_5pct']:>8.3f} {r['retention_20pct']:>8.3f} {r['status']:>8}{marker}")

    robust = sum(1 for r in results if r["status"] == "ROBUST")
    warn = sum(1 for r in results if r["status"] == "WARN")
    fragile = sum(1 for r in results if r["status"] == "FRAGILE")
    print(f"\n  ROBUST: {robust}, WARN: {warn}, FRAGILE: {fragile}")
    print(f"  Total time: {time.time() - t0:.0f}s")

    conn.close()


if __name__ == "__main__":
    main()
