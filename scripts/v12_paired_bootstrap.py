#!/usr/bin/env python3
"""v1.2 Paired Bootstrap Test: 5-factor vs 6-factor IC significance.

Methodology:
  1. Compute monthly cross-sectional Spearman IC for both 5-factor and 6-factor composites
     on the SAME stock pool and SAME time periods (paired design).
  2. For each month, compute IC_diff = IC_6fac - IC_5fac.
  3. Bootstrap the IC_diff series 1000 times (resample months with replacement).
  4. If 95% CI of mean(IC_diff) excludes 0 => v1.2 increment is statistically significant.

v1.1 baseline: turnover_mean_20(-1), volatility_20(-1), reversal_20(+1), amihud_20(+1), bp_ratio(+1)
v1.2 candidate: baseline + mf_momentum_divergence(-1)

Usage:
    python scripts/v12_paired_bootstrap.py
    python scripts/v12_paired_bootstrap.py --start 2021-01-01 --end 2025-12-31
    python scripts/v12_paired_bootstrap.py --n-bootstrap 5000  # more precision
"""

import argparse
import sys
import time
from datetime import date as dt_date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*pandas only supports.*")

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# v1.1 baseline (must match PAPER_TRADING_CONFIG exactly)
BASELINE_5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

# v1.2 = baseline + mf_momentum_divergence
V12_NEW_FACTOR = "mf_momentum_divergence"

# Factor directions from signal_engine.py FACTOR_DIRECTION dict
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": +1,
    "amihud_20": +1,
    "bp_ratio": +1,
    "mf_momentum_divergence": -1,
}


def cs_zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional zscore with MAD winsorization."""
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


def compute_composite_ic_paired(
    factor_wides_5: list[pd.DataFrame],
    directions_5: list[int],
    factor_wides_6: list[pd.DataFrame],
    directions_6: list[int],
    excess_fwd: pd.DataFrame,
    month_ends: list[str],
) -> pd.DataFrame:
    """Compute paired IC for 5-factor and 6-factor composites.

    Returns DataFrame with columns: date, ic_5, ic_6, ic_diff, n_stocks
    Only includes months where BOTH composites can be computed on the same stocks.
    """
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    records = []
    for d_str in month_ends:
        if d_str not in efwd.index:
            continue

        # Collect zscored factors for 5-factor composite
        series_5 = []
        for fw, dirn in zip(factor_wides_5, directions_5):
            fw2 = fw.copy()
            fw2.index = fw2.index.astype(str)
            if d_str not in fw2.index:
                break
            series_5.append(dirn * fw2.loc[d_str])
        else:
            pass  # all 5 factors available
        if len(series_5) != len(factor_wides_5):
            continue

        # Collect zscored factors for 6-factor composite
        series_6 = []
        for fw, dirn in zip(factor_wides_6, directions_6):
            fw2 = fw.copy()
            fw2.index = fw2.index.astype(str)
            if d_str not in fw2.index:
                break
            series_6.append(dirn * fw2.loc[d_str])
        else:
            pass  # all 6 factors available
        if len(series_6) != len(factor_wides_6):
            continue

        fwd_cross = efwd.loc[d_str].dropna()

        # Build DataFrames, find COMMON stocks across both composites AND forward return
        df5 = pd.DataFrame({f"f{i}": s for i, s in enumerate(series_5)}).dropna()
        df6 = pd.DataFrame({f"f{i}": s for i, s in enumerate(series_6)}).dropna()
        common = df5.index.intersection(df6.index).intersection(fwd_cross.index)

        if len(common) < 100:
            continue

        # Cross-sectional zscore each factor, then equal-weight average
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
    """Paired bootstrap test on IC differences.

    H0: mean(IC_diff) = 0 (no improvement from adding factor)
    H1: mean(IC_diff) > 0 (6-factor is better)

    Returns dict with bootstrap statistics.
    """
    rng = np.random.RandomState(seed)
    n = len(ic_diff)
    observed_mean = np.mean(ic_diff)

    boot_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        boot_means[i] = np.mean(ic_diff[idx])

    ci_lo = np.percentile(boot_means, 2.5)
    ci_hi = np.percentile(boot_means, 97.5)
    ci_90_lo = np.percentile(boot_means, 5.0)
    ci_90_hi = np.percentile(boot_means, 95.0)

    # p-value: fraction of bootstrap samples where mean <= 0 (one-sided)
    p_one_sided = np.mean(boot_means <= 0)
    # Two-sided: fraction where |mean| >= |observed|
    p_two_sided = np.mean(np.abs(boot_means - np.mean(boot_means)) >= abs(observed_mean - np.mean(boot_means)))

    # Standard t-test for comparison
    t_stat, t_pval = stats.ttest_1samp(ic_diff, 0)

    return {
        "observed_mean_diff": observed_mean,
        "observed_std_diff": np.std(ic_diff, ddof=1),
        "boot_mean": np.mean(boot_means),
        "boot_std": np.std(boot_means),
        "ci_95": (ci_lo, ci_hi),
        "ci_90": (ci_90_lo, ci_90_hi),
        "p_one_sided": p_one_sided,
        "p_two_sided": p_two_sided,
        "excludes_zero_95": (ci_lo > 0) or (ci_hi < 0),
        "excludes_zero_90": (ci_90_lo > 0) or (ci_90_hi < 0),
        "t_stat": t_stat,
        "t_pval": t_pval,
        "n_months": len(ic_diff),
        "n_bootstrap": n_bootstrap,
    }


def main():
    parser = argparse.ArgumentParser(description="v1.2 Paired Bootstrap IC Test")
    parser.add_argument("--start", default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--n-bootstrap", type=int, default=1000, help="Bootstrap iterations")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ══════════════════════════════════════════════════════════════
    # DATA LOADING
    # ══════════════════════════════════════════════════════════════
    print("=" * 75)
    print("  v1.2 PAIRED BOOTSTRAP TEST: 6-factor vs 5-factor IC")
    print("=" * 75)

    all_factors = BASELINE_5 + [V12_NEW_FACTOR]
    placeholders = ",".join(f"'{f}'" for f in all_factors)

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

    # Check which factors are available
    available = fv["factor_name"].unique()
    missing = [f for f in all_factors if f not in available]
    if missing:
        print(f"\n  WARNING: Missing factors in factor_values: {missing}")
        if V12_NEW_FACTOR in missing:
            print(f"  {V12_NEW_FACTOR} not in DB. Need to compute it from moneyflow_daily.")
            print("  Attempting to compute mf_momentum_divergence on the fly...")
            fv_new = compute_mf_divergence(conn, args.start, args.end)
            if fv_new is not None and not fv_new.empty:
                fv = pd.concat([fv, fv_new], ignore_index=True)
                print(f"  Added {len(fv_new):,} mf_momentum_divergence rows")
            else:
                print("  FAILED to compute mf_momentum_divergence. Cannot proceed.")
                conn.close()
                sys.exit(1)

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

    # ── Pivot & compute forward returns ──
    print("[DATA] Pivoting and computing 5d forward excess return...")
    adj_wide = klines.pivot(index="trade_date", columns="code", values="adj_close")
    bench_s = bench.set_index("trade_date")["close"]
    common_dates = adj_wide.index.sort_values()
    bench_s = bench_s.reindex(common_dates)

    fwd_ret = adj_wide.shift(-5) / adj_wide - 1
    bench_fwd = bench_s.shift(-5) / bench_s - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # Pivot factor values to wide format
    factor_pivots = {}
    for fname in all_factors:
        sub = fv[fv["factor_name"] == fname]
        if sub.empty:
            continue
        pivot = sub.pivot(index="trade_date", columns="code", values="value")
        factor_pivots[fname] = pivot

    # Month-end dates
    dates_series = pd.Series(common_dates)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period("M")).last().values
    month_ends = [str(d) for d in month_ends]
    month_ends = [d for d in month_ends if args.start <= d <= args.end]
    print(f"  Month-end dates: {len(month_ends)} (from {month_ends[0]} to {month_ends[-1]})")

    # Check all factors available
    for f in all_factors:
        if f not in factor_pivots:
            print(f"  FATAL: factor {f} not available after pivot")
            sys.exit(1)

    # ══════════════════════════════════════════════════════════════
    # PAIRED IC COMPUTATION
    # ══════════════════════════════════════════════════════════════
    print("\n[IC] Computing paired IC for 5-factor and 6-factor composites...")

    wides_5 = [factor_pivots[f] for f in BASELINE_5]
    dirs_5 = [FACTOR_DIRECTIONS[f] for f in BASELINE_5]

    all_6 = BASELINE_5 + [V12_NEW_FACTOR]
    wides_6 = [factor_pivots[f] for f in all_6]
    dirs_6 = [FACTOR_DIRECTIONS[f] for f in all_6]

    paired_ic = compute_composite_ic_paired(
        wides_5, dirs_5, wides_6, dirs_6, excess_fwd, month_ends
    )

    if len(paired_ic) < 5:
        print(f"  Only {len(paired_ic)} paired observations. Too few for bootstrap.")
        sys.exit(1)

    print(f"  Paired months: {len(paired_ic)}")
    print(f"  Avg stocks per month: {paired_ic['n_stocks'].mean():.0f}")

    # Summary stats
    ic5_mean = paired_ic["ic_5"].mean()
    ic6_mean = paired_ic["ic_6"].mean()
    ic5_ir = paired_ic["ic_5"].mean() / paired_ic["ic_5"].std() if paired_ic["ic_5"].std() > 0 else 0
    ic6_ir = paired_ic["ic_6"].mean() / paired_ic["ic_6"].std() if paired_ic["ic_6"].std() > 0 else 0

    print(f"\n  {'':20s} {'IC Mean':>10} {'IC Std':>10} {'IC_IR':>10} {'IC>0%':>8}")
    print("  " + "-" * 60)
    print(f"  {'5-factor (v1.1)':20s} {ic5_mean:>+10.4f} {paired_ic['ic_5'].std():>10.4f} {ic5_ir:>10.4f} {(paired_ic['ic_5']>0).mean()*100:>7.1f}%")
    print(f"  {'6-factor (v1.2)':20s} {ic6_mean:>+10.4f} {paired_ic['ic_6'].std():>10.4f} {ic6_ir:>10.4f} {(paired_ic['ic_6']>0).mean()*100:>7.1f}%")
    print(f"  {'Difference':20s} {paired_ic['ic_diff'].mean():>+10.4f} {paired_ic['ic_diff'].std():>10.4f}")

    # ══════════════════════════════════════════════════════════════
    # BOOTSTRAP TEST
    # ══════════════════════════════════════════════════════════════
    print(f"\n[BOOTSTRAP] Running {args.n_bootstrap} iterations (seed={args.seed})...")

    result = paired_bootstrap_test(
        paired_ic["ic_diff"].values,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
    )

    print(f"\n  --- Paired Bootstrap Results ---")
    print(f"  {'Observed mean(IC_diff):':35s} {result['observed_mean_diff']:+.5f}")
    print(f"  {'Observed std(IC_diff):':35s} {result['observed_std_diff']:.5f}")
    print(f"  {'Bootstrap mean:':35s} {result['boot_mean']:+.5f}")
    print(f"  {'Bootstrap std:':35s} {result['boot_std']:.5f}")
    print(f"  {'95% CI:':35s} [{result['ci_95'][0]:+.5f}, {result['ci_95'][1]:+.5f}]")
    print(f"  {'90% CI:':35s} [{result['ci_90'][0]:+.5f}, {result['ci_90'][1]:+.5f}]")
    print(f"  {'p-value (one-sided, H1: diff>0):':35s} {result['p_one_sided']:.4f}")
    print(f"  {'t-test t-stat:':35s} {result['t_stat']:+.3f}")
    print(f"  {'t-test p-value (two-sided):':35s} {result['t_pval']:.4f}")
    print(f"  {'N months:':35s} {result['n_months']}")

    # ══════════════════════════════════════════════════════════════
    # VERDICT
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 75)
    print("  VERDICT")
    print("=" * 75)

    if result["excludes_zero_95"]:
        sig_level = "95%"
        verdict = "SIGNIFICANT"
    elif result["excludes_zero_90"]:
        sig_level = "90%"
        verdict = "MARGINALLY SIGNIFICANT"
    else:
        sig_level = "not significant"
        verdict = "NOT SIGNIFICANT"

    print(f"\n  IC increment (6-fac minus 5-fac): {result['observed_mean_diff']:+.4f} ({result['observed_mean_diff']*100:+.2f}%)")
    print(f"  Bootstrap 95% CI: [{result['ci_95'][0]:+.5f}, {result['ci_95'][1]:+.5f}]")
    print(f"  Statistical significance: {verdict} ({sig_level})")

    if verdict == "SIGNIFICANT":
        print(f"\n  RECOMMENDATION: v1.2 upgrade is justified.")
        print(f"  The +{result['observed_mean_diff']*100:.2f}% IC increment from mf_momentum_divergence")
        print(f"  is statistically significant at 95% confidence.")
        print(f"  However, Paper Trading v1.1 must complete 60 days first.")
        print(f"  After graduation, run v1.2 backtest + new 60-day Paper Trading.")
    elif verdict == "MARGINALLY SIGNIFICANT":
        print(f"\n  RECOMMENDATION: Borderline. Consider waiting for more data.")
        print(f"  The increment is significant at 90% but not 95%.")
        print(f"  May be worth testing with longer OOS period or different rebalance freq.")
    else:
        print(f"\n  RECOMMENDATION: v1.2 upgrade NOT justified by current evidence.")
        print(f"  The IC increment does not reliably exclude zero.")
        print(f"  Keep v1.1 and look for stronger candidate factors.")

    # ── Annual breakdown of IC diff ──
    print(f"\n  --- Annual IC Diff Breakdown ---")
    paired_ic["year"] = pd.to_datetime(paired_ic["date"]).dt.year
    print(f"  {'Year':<6} {'IC_5':>8} {'IC_6':>8} {'Diff':>8} {'Diff>0':>6} {'N':>4}")
    for year, grp in paired_ic.groupby("year"):
        print(
            f"  {year:<6} {grp['ic_5'].mean():>+8.4f} {grp['ic_6'].mean():>+8.4f} "
            f"{grp['ic_diff'].mean():>+8.4f} "
            f"{(grp['ic_diff']>0).mean()*100:>5.1f}% "
            f"{len(grp):>4}"
        )

    # ── Monthly detail ──
    print(f"\n  --- Monthly Detail (IC_5, IC_6, Diff) ---")
    print(f"  {'Month':>10} {'IC_5':>8} {'IC_6':>8} {'Diff':>8} {'N':>6}")
    for _, r in paired_ic.iterrows():
        d = r["date"][:7]  # YYYY-MM
        marker = " *" if r["ic_diff"] > 0 else ""
        print(f"  {d:>10} {r['ic_5']:>+8.4f} {r['ic_6']:>+8.4f} {r['ic_diff']:>+8.4f} {int(r['n_stocks']):>6}{marker}")

    elapsed = time.time() - t0
    print(f"\n  Elapsed: {elapsed:.1f}s")


def compute_mf_divergence(conn, start: str, end: str) -> pd.DataFrame | None:
    """Compute mf_momentum_divergence on the fly if not in factor_values.

    mf_momentum_divergence = rank(20d momentum) - rank(20d net money flow momentum)
    When price goes up but money flows out (or vice versa), there's divergence.
    """
    try:
        print("  Loading klines for momentum...")
        kl = pd.read_sql(
            f"""SELECT code, trade_date,
                       close::float * adj_factor::float as adj_close
                FROM klines_daily
                WHERE trade_date >= '{start}'::date - INTERVAL '30 days'
                  AND trade_date <= '{end}'
                  AND volume > 0
                ORDER BY trade_date, code""",
            conn,
        )

        print("  Loading moneyflow...")
        mf = pd.read_sql(
            f"""SELECT code, trade_date, net_mf_amount::float
                FROM moneyflow_daily
                WHERE trade_date >= '{start}'::date - INTERVAL '30 days'
                  AND trade_date <= '{end}'
                ORDER BY trade_date, code""",
            conn,
        )

        if kl.empty or mf.empty:
            return None

        adj_wide = kl.pivot(index="trade_date", columns="code", values="adj_close")
        mf_wide = mf.pivot(index="trade_date", columns="code", values="net_mf_amount")

        # 20-day price momentum
        price_mom = adj_wide.pct_change(20)
        # 20-day cumulative net money flow (rolling sum)
        mf_cum = mf_wide.rolling(20, min_periods=15).sum()

        # Cross-sectional rank divergence
        records = []
        common_dates = price_mom.index.intersection(mf_cum.index)
        for td in common_dates:
            if str(td) < start:
                continue
            pm = price_mom.loc[td].dropna()
            mc = mf_cum.loc[td].dropna()
            common = pm.index.intersection(mc.index)
            if len(common) < 200:
                continue

            # Rank (0-1 scale)
            pm_rank = pm[common].rank(pct=True)
            mf_rank = mc[common].rank(pct=True)

            # Divergence = price rank - money flow rank
            # Large positive = price up but money out (bearish divergence)
            div = pm_rank - mf_rank

            # Zscore for storage
            div_z = (div - div.mean()) / div.std() if div.std() > 0 else div * 0

            for code in common:
                records.append({
                    "code": code,
                    "trade_date": td,
                    "factor_name": "mf_momentum_divergence",
                    "value": div_z[code],
                })

        if not records:
            return None

        return pd.DataFrame(records)

    except Exception as e:
        print(f"  Error computing mf_divergence: {e}")
        return None


if __name__ == "__main__":
    main()
