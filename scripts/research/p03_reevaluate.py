"""P0-3: Re-evaluate CORE3+RSQR+dv with fixed RSQR_20 neutral_values.

All factors loaded from DB (not stale Parquet cache).
Compares 4 configurations to measure RSQR_20 marginal increment.
"""
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

sys.path.append("D:/quantmind-v2/backend")
sys.path.insert(0, "D:/quantmind-v2/scripts/research")
os.chdir("D:/quantmind-v2/backend")

from dotenv import load_dotenv

load_dotenv("D:/quantmind-v2/backend/.env")

import numpy as np
import pandas as pd

# Import shared utilities from phase24 exploration
from phase24_research_exploration import (
    get_db_conn,
    load_factors_from_db,
    load_price_data,
    run_standard_experiment,
)

print("=" * 70)
print("P0-3: Re-evaluate with fixed RSQR_20 neutral_values")
print("Data source: DB (COALESCE(neutral_value, raw_value))")
print("=" * 70)

t_start = time.time()

# Step 1: Load price data from Parquet cache (price/benchmark are fine)
print("\n[1/4] Loading price data...")
price, bench = load_price_data(2020, 2026)

# Step 2: Load ALL needed factors from DB
print("\n[2/4] Loading factors from DB...")
conn = get_db_conn()

all_factors = [
    "turnover_mean_20", "volatility_20", "bp_ratio",  # CORE3
    "reversal_20", "amihud_20",  # CORE5 extras
    "RSQR_20", "dv_ttm",  # Phase 2.4 additions
]
factor_df = load_factors_from_db(all_factors, "2020-01-01", "2026-04-01", conn)

# Filter out NaN values (RSQR_20 may have some from neutralization edge cases)
before = len(factor_df)
factor_df["raw_value"] = pd.to_numeric(factor_df["raw_value"], errors="coerce")
factor_df = factor_df.dropna(subset=["raw_value"])
factor_df = factor_df[np.isfinite(factor_df["raw_value"])]
print(f"  Filtered NaN/Inf: {before:,} -> {len(factor_df):,} ({before - len(factor_df):,} removed)")

# Step 3: Run 4 configurations
print("\n[3/4] Running backtests...")
configs = {
    "A_CORE5_SN": {
        "directions": {"turnover_mean_20": -1, "volatility_20": -1, "reversal_20": 1, "amihud_20": 1, "bp_ratio": 1},
        "label": "CORE5+SN (baseline)",
    },
    "B_CORE3_RSQR_dv_SN": {
        "directions": {"turnover_mean_20": -1, "volatility_20": -1, "bp_ratio": 1, "RSQR_20": -1, "dv_ttm": 1},
        "label": "CORE3+RSQR+dv+SN (Phase2.4 best)",
    },
    "C_CORE3_dv_SN": {
        "directions": {"turnover_mean_20": -1, "volatility_20": -1, "bp_ratio": 1, "dv_ttm": 1},
        "label": "CORE3+dv+SN (no RSQR)",
    },
    "D_CORE5_RSQR_dv_SN": {
        "directions": {"turnover_mean_20": -1, "volatility_20": -1, "reversal_20": 1, "amihud_20": 1, "bp_ratio": 1, "RSQR_20": -1, "dv_ttm": 1},
        "label": "CORE5+RSQR+dv+SN (all 7)",
    },
}

results = {}
for key, cfg in configs.items():
    t1 = time.time()
    dirs = cfg["directions"]
    # Filter factor_df to only needed factors
    needed = list(dirs.keys())
    sub_df = factor_df[factor_df["factor_name"].isin(needed)]

    print(f"\n  Running {cfg['label']}...")
    print(f"    Factors: {needed}")
    print(f"    Factor rows: {len(sub_df):,}")

    metrics = run_standard_experiment(
        factor_df=sub_df,
        directions=dirs,
        price_data=price,
        benchmark_data=bench,
        top_n=20,
        rebalance_freq="monthly",
        sn_beta=0.50,
        conn=conn,
        label=cfg["label"],
    )
    metrics["elapsed_s"] = round(time.time() - t1, 1)
    results[key] = metrics
    print(f"    Sharpe={metrics['sharpe']:.4f}  MDD={metrics['mdd']:.4f}  AnnRet={metrics['annual_return']:.4f}  ({metrics['elapsed_s']}s)")

conn.close()

# Step 4: Summary comparison
print("\n" + "=" * 70)
print("P0-3 RESULTS SUMMARY")
print("=" * 70)
print(f"{'Config':<35} {'Sharpe':>8} {'MDD':>8} {'AnnRet':>8} {'TotRet':>8}")
print("-" * 70)
for key, m in results.items():
    print(f"{m['label']:<35} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} {m['annual_return']:>8.4f} {m['total_return']:>8.4f}")

# Marginal increments
base = results["A_CORE5_SN"]["sharpe"]
best = results["B_CORE3_RSQR_dv_SN"]["sharpe"]
no_rsqr = results["C_CORE3_dv_SN"]["sharpe"]
all7 = results["D_CORE5_RSQR_dv_SN"]["sharpe"]

print(f"\nMarginal Analysis (vs CORE5+SN baseline Sharpe={base:.4f}):")
print(f"  CORE3+RSQR+dv:   {best:.4f} ({(best-base)/abs(base)*100:+.1f}%)")
print(f"  CORE3+dv (no RSQR): {no_rsqr:.4f} ({(no_rsqr-base)/abs(base)*100:+.1f}%)")
print(f"  CORE5+RSQR+dv:   {all7:.4f} ({(all7-base)/abs(base)*100:+.1f}%)")
print(f"\n  RSQR_20 marginal increment: {best-no_rsqr:.4f} Sharpe")
print(f"  dv_ttm marginal increment:  {no_rsqr-base:.4f} Sharpe (approx, via CORE3+dv vs CORE5)")

total_time = time.time() - t_start
print(f"\nTotal time: {total_time/60:.1f} minutes")

# Save results
cache_dir = "D:/quantmind-v2/cache/phase24_audit"
os.makedirs(cache_dir, exist_ok=True)
output = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "data_source": "DB (COALESCE(neutral_value, raw_value))",
    "oos_window": "2020-01-01 ~ 2026-04-01",
    "sn_beta": 0.50,
    "top_n": 20,
    "rebalance": "monthly",
    "results": results,
    "rsqr_marginal": round(best - no_rsqr, 4),
    "dv_ttm_marginal": round(no_rsqr - base, 4),
}
with open(f"{cache_dir}/p03_reevaluation.json", "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nSaved: {cache_dir}/p03_reevaluation.json")
