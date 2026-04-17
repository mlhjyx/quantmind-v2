#!/usr/bin/env python3
"""Paired Bootstrap Test: 5+1 factor IC significance for multiple candidates.

对每个候选因子，测试将其加入现有5因子基线后IC是否显著提升。
方法: 月度截面Spearman IC paired bootstrap (1000次)。

Usage:
    python scripts/research/paired_bootstrap_candidates.py
    python scripts/research/paired_bootstrap_candidates.py --factors price_volume_corr_20 vwap_bias_1d
    python scripts/research/paired_bootstrap_candidates.py --n-bootstrap 5000
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import warnings

warnings.filterwarnings("ignore", category=UserWarning, message=".*pandas only supports.*")

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# 基线5因子 (PAPER_TRADING_CONFIG)
BASELINE_5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

# 候选因子列表
CANDIDATES = [
    "price_volume_corr_20",
    "vwap_bias_1d",
    "rsrs_raw_18",
    "price_level_factor",
    "ep_ratio",
]

# 因子方向 (signal_engine.py FACTOR_DIRECTION)
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": +1,
    "amihud_20": +1,
    "bp_ratio": +1,
    "price_volume_corr_20": -1,
    "vwap_bias_1d": -1,
    "rsrs_raw_18": -1,
    "price_level_factor": -1,
    "ep_ratio": +1,
}


def cs_zscore(s: pd.Series) -> pd.Series:
    """截面MAD winsorization + z-score。"""
    median = s.median()
    mad = (s - median).abs().median()
    if mad < 1e-10:
        return s * 0
    upper = median + 5 * 1.4826 * mad
    lower = median - 5 * 1.4826 * mad
    clipped = s.clip(lower, upper)
    mean = clipped.mean()
    std = clipped.std()
    if std < 1e-10:
        return clipped * 0
    return (clipped - mean) / std


def compute_paired_ic(
    factor_pivots: dict[str, pd.DataFrame],
    baseline_factors: list[str],
    candidate_factor: str,
    excess_fwd: pd.DataFrame,
    month_ends: list[str],
) -> pd.DataFrame:
    """计算基线vs基线+候选的paired IC。"""
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    all_6 = baseline_factors + [candidate_factor]
    dirs_5 = [FACTOR_DIRECTIONS[f] for f in baseline_factors]
    dirs_6 = [FACTOR_DIRECTIONS[f] for f in all_6]

    records = []
    for d_str in month_ends:
        if d_str not in efwd.index:
            continue

        # 5因子composite
        series_5 = []
        for f, d in zip(baseline_factors, dirs_5, strict=False):
            fp = factor_pivots.get(f)
            if fp is None:
                break
            fp2 = fp.copy()
            fp2.index = fp2.index.astype(str)
            if d_str not in fp2.index:
                break
            series_5.append(d * fp2.loc[d_str])
        if len(series_5) != len(baseline_factors):
            continue

        # 6因子composite
        series_6 = []
        for f, d in zip(all_6, dirs_6, strict=False):
            fp = factor_pivots.get(f)
            if fp is None:
                break
            fp2 = fp.copy()
            fp2.index = fp2.index.astype(str)
            if d_str not in fp2.index:
                break
            series_6.append(d * fp2.loc[d_str])
        if len(series_6) != len(all_6):
            continue

        fwd_cross = efwd.loc[d_str].dropna()

        df5 = pd.DataFrame({f"f{i}": s for i, s in enumerate(series_5)}).dropna()
        df6 = pd.DataFrame({f"f{i}": s for i, s in enumerate(series_6)}).dropna()
        common = df5.index.intersection(df6.index).intersection(fwd_cross.index)

        if len(common) < 100:
            continue

        z5 = df5.loc[common].apply(cs_zscore, axis=0).mean(axis=1)
        z6 = df6.loc[common].apply(cs_zscore, axis=0).mean(axis=1)

        ic5, _ = stats.spearmanr(z5.values, fwd_cross[common].values)
        ic6, _ = stats.spearmanr(z6.values, fwd_cross[common].values)

        records.append({
            "date": d_str,
            "ic_5": ic5,
            "ic_6": ic6,
            "ic_diff": ic6 - ic5,
            "n_stocks": len(common),
        })

    return pd.DataFrame(records)


def paired_bootstrap_test(
    ic_diff: np.ndarray,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> dict:
    """Paired bootstrap检验。H0: mean(IC_diff) = 0。"""
    rng = np.random.RandomState(seed)
    n = len(ic_diff)
    observed_mean = np.mean(ic_diff)

    boot_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        boot_means[i] = np.mean(ic_diff[idx])

    ci_lo = np.percentile(boot_means, 2.5)
    ci_hi = np.percentile(boot_means, 97.5)

    p_one_sided = np.mean(boot_means <= 0)
    t_stat, t_pval = stats.ttest_1samp(ic_diff, 0)

    return {
        "observed_mean_diff": observed_mean,
        "ci_95": (ci_lo, ci_hi),
        "p_one_sided": p_one_sided,
        "excludes_zero_95": (ci_lo > 0) or (ci_hi < 0),
        "t_stat": t_stat,
        "t_pval": t_pval,
        "n_months": n,
    }


def main():
    parser = argparse.ArgumentParser(description="Paired Bootstrap for Candidate Factors")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--n-bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--factors", nargs="+", default=CANDIDATES)
    args = parser.parse_args()

    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ── 数据加载 ──
    all_factors = list(set(BASELINE_5 + args.factors))
    placeholders = ",".join(f"'{f}'" for f in all_factors)

    print("=" * 75)
    print("  PAIRED BOOTSTRAP: 5+1 Factor IC Significance Test")
    print("=" * 75)
    print(f"\n  Baseline: {BASELINE_5}")
    print(f"  Candidates: {args.factors}")
    print(f"  Period: {args.start} ~ {args.end}")

    print(f"\n[DATA] Loading factor_values for {len(all_factors)} factors...")
    fv = pd.read_sql(
        f"""SELECT code, trade_date, factor_name, zscore::float as value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= '{args.start}'
              AND trade_date <= '{args.end}'
            ORDER BY trade_date, code""",
        conn,
    )
    print(f"  Rows: {len(fv):,}")

    print("[DATA] Loading klines for forward return...")
    klines = pd.read_sql(
        f"""SELECT code, trade_date,
                   close::float * adj_factor::float as adj_close
            FROM klines_daily
            WHERE trade_date >= '2020-06-01' AND trade_date <= '{args.end}'
              AND volume > 0
            ORDER BY trade_date, code""",
        conn,
    )
    print(f"  Rows: {len(klines):,}")

    print("[DATA] Loading CSI300 benchmark...")
    bench = pd.read_sql(
        f"""SELECT trade_date, close::float
            FROM index_daily
            WHERE index_code='000300.SH'
              AND trade_date >= '2020-06-01' AND trade_date <= '{args.end}'
            ORDER BY trade_date""",
        conn,
    )
    conn.close()

    # ── Pivot & forward return ──
    print("[DATA] Computing 5d forward excess return...")
    adj_wide = klines.pivot(index="trade_date", columns="code", values="adj_close")
    bench_s = bench.set_index("trade_date")["close"]
    common_dates = adj_wide.index.sort_values()
    bench_s = bench_s.reindex(common_dates)

    fwd_ret = adj_wide.shift(-5) / adj_wide - 1
    bench_fwd = bench_s.shift(-5) / bench_s - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # Pivot factors
    factor_pivots = {}
    for fname in all_factors:
        sub = fv[fv["factor_name"] == fname]
        if sub.empty:
            print(f"  WARNING: {fname} has no data, skipping")
            continue
        factor_pivots[fname] = sub.pivot(index="trade_date", columns="code", values="value")

    # Month-end dates
    dates_series = pd.Series(common_dates)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period("M")).last().values
    month_ends = [str(d) for d in month_ends]
    month_ends = [d for d in month_ends if args.start <= d <= args.end]
    print(f"  Month-ends: {len(month_ends)}")

    # ── 逐个候选因子测试 ──
    results_summary = []

    for candidate in args.factors:
        if candidate not in factor_pivots:
            print(f"\n  SKIP {candidate}: no data")
            continue

        print(f"\n{'─' * 75}")
        print(f"  Testing: {candidate} (direction={FACTOR_DIRECTIONS.get(candidate, '?')})")
        print(f"{'─' * 75}")

        paired_ic = compute_paired_ic(
            factor_pivots, BASELINE_5, candidate, excess_fwd, month_ends
        )

        if len(paired_ic) < 10:
            print(f"  Only {len(paired_ic)} months. Too few.")
            results_summary.append({
                "factor": candidate, "verdict": "INSUFFICIENT_DATA",
                "ic_diff": None, "p": None, "ci_95": None,
            })
            continue

        ic5_mean = paired_ic["ic_5"].mean()
        ic6_mean = paired_ic["ic_6"].mean()

        print(f"  5-factor IC: {ic5_mean:+.4f}  |  6-factor IC: {ic6_mean:+.4f}  |  diff: {paired_ic['ic_diff'].mean():+.4f}")
        print(f"  Months: {len(paired_ic)}, avg stocks: {paired_ic['n_stocks'].mean():.0f}")

        result = paired_bootstrap_test(
            paired_ic["ic_diff"].values,
            n_bootstrap=args.n_bootstrap,
            seed=args.seed,
        )

        if result["excludes_zero_95"]:
            verdict = "SIGNIFICANT (p<0.05)"
        elif result["p_one_sided"] < 0.10:
            verdict = "MARGINAL (p<0.10)"
        else:
            verdict = "NOT SIGNIFICANT"

        print(f"  Bootstrap 95% CI: [{result['ci_95'][0]:+.5f}, {result['ci_95'][1]:+.5f}]")
        print(f"  p-value (one-sided): {result['p_one_sided']:.4f}")
        print(f"  t-stat: {result['t_stat']:+.3f}, t-pval: {result['t_pval']:.4f}")
        print(f"  >>> {verdict}")

        results_summary.append({
            "factor": candidate,
            "verdict": verdict,
            "ic_diff": result["observed_mean_diff"],
            "p_one_sided": result["p_one_sided"],
            "ci_95": result["ci_95"],
            "t_stat": result["t_stat"],
            "n_months": result["n_months"],
        })

    # ── 汇总 ──
    print(f"\n{'=' * 75}")
    print("  SUMMARY: Candidate Factor Paired Bootstrap Results")
    print(f"{'=' * 75}")
    print(f"\n  {'Factor':<25} {'IC Diff':>8} {'p(1s)':>7} {'t-stat':>7} {'Verdict'}")
    print("  " + "-" * 70)
    for r in results_summary:
        if r.get("ic_diff") is not None:
            print(
                f"  {r['factor']:<25} {r['ic_diff']:>+8.4f} {r['p_one_sided']:>7.4f} "
                f"{r['t_stat']:>+7.3f} {r['verdict']}"
            )
        else:
            print(f"  {r['factor']:<25} {'N/A':>8} {'N/A':>7} {'N/A':>7} {r['verdict']}")

    elapsed = time.time() - t0
    print(f"\n  Total elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
