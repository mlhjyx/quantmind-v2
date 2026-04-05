#!/usr/bin/env python3
"""Batch 7: v1.2 Factor Validation — close_to_high neutralization + mf_divergence incremental
================================================================================
Tasks:
1. close_to_high_ratio: regress out vol_20, test residual IC (redundancy check)
2. mf_momentum_divergence: 6-factor vs 5-factor incremental IC
3. 7-factor combination IC (if 1 & 2 pass)
4. Alternative: price_to_ma20_ratio (if close_to_high fails)
5. intraday_overnight_split factor test

Baseline 5 factors: volatility_20, ln_market_cap, momentum_20, turnover_mean_20, bp_ratio
"""

import time
import warnings

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

warnings.filterwarnings('ignore')

DB_URI = 'postgresql://xin:quantmind@localhost:5432/quantmind_v2'

BASELINE_5 = ['volatility_20', 'ln_market_cap', 'momentum_20', 'turnover_mean_20', 'bp_ratio']
# Factor directions (positive direction = higher zscore => higher expected return)
FACTOR_DIRECTIONS = {
    'volatility_20': -1,
    'ln_market_cap': -1,
    'momentum_20': +1,
    'turnover_mean_20': -1,
    'bp_ratio': +1,
}


def cs_zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional zscore with MAD winsorization."""
    median = s.median()
    mad = (s - median).abs().median()
    upper = median + 5 * 1.4826 * mad
    lower = median - 5 * 1.4826 * mad
    clipped = s.clip(lower, upper)
    mean = clipped.mean()
    std = clipped.std()
    if std < 1e-10:
        return clipped * 0
    return (clipped - mean) / std


def compute_monthly_ic_series(factor_wide: pd.DataFrame, excess_fwd: pd.DataFrame,
                               month_ends: list, direction: int = 1) -> pd.DataFrame:
    """Cross-sectional Spearman IC, monthly."""
    fac = factor_wide.copy()
    fac.index = fac.index.astype(str)
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    records = []
    for d in month_ends:
        d_str = str(d)
        if d_str not in fac.index or d_str not in efwd.index:
            continue
        fac_cross = fac.loc[d_str].dropna()
        fwd_cross = efwd.loc[d_str].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        vals = direction * fac_cross[common].values
        ic, pval = stats.spearmanr(vals, fwd_cross[common].values)
        records.append({'date': d_str, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})
    return pd.DataFrame(records)


def ic_summary(ic_df: pd.DataFrame) -> dict:
    """Compute IC summary stats."""
    if len(ic_df) == 0:
        return {'ic_mean': np.nan, 'ic_std': np.nan, 'ic_ir': np.nan,
                't_stat': np.nan, 'pct_pos': np.nan, 'n_months': 0}
    ic_mean = ic_df['ic'].mean()
    ic_std = ic_df['ic'].std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0
    pct_pos = (ic_df['ic'] > 0).mean() * 100
    return {'ic_mean': ic_mean, 'ic_std': ic_std, 'ic_ir': ic_ir,
            't_stat': t_stat, 'pct_pos': pct_pos, 'n_months': len(ic_df)}


def print_ic_table(name: str, ic_df: pd.DataFrame, direction: int = 1):
    """Print full IC report with annual breakdown."""
    s = ic_summary(ic_df)
    if s['n_months'] == 0:
        print(f"  {name}: NO DATA")
        return s

    sig = '***' if abs(s['t_stat']) > 2.58 else '**' if abs(s['t_stat']) > 1.96 else '*' if abs(s['t_stat']) > 1.64 else 'ns'

    print(f"\n  {name} (dir={direction:+d}):")
    print(f"    IC Mean: {s['ic_mean']:+.4f} ({abs(s['ic_mean'])*100:.2f}%)")
    print(f"    IC Std:  {s['ic_std']:.4f}")
    print(f"    IC_IR:   {s['ic_ir']:.4f}")
    print(f"    t-stat:  {s['t_stat']:.2f} {sig}")
    print(f"    IC > 0:  {s['pct_pos']:.1f}%")
    print(f"    Months:  {s['n_months']}")

    # Annual breakdown
    ic_df = ic_df.copy()
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year
    print(f"    {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t':>6} {'IC>0%':>6} {'N':>3}")
    for year, grp in ic_df.groupby('year'):
        ym = grp['ic'].mean()
        ys = grp['ic'].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp['ic'] > 0).mean() * 100
        print(f"    {year:<6} {ym:>+8.4f} {ys:>8.4f} {yir:>8.4f} {yt:>6.2f} {yp:>5.1f}% {len(grp):>3}")

    return s


def composite_factor_ic(factor_wides: list[pd.DataFrame], directions: list[int],
                         excess_fwd: pd.DataFrame, month_ends: list) -> pd.DataFrame:
    """Compute equal-weight composite factor IC.
    Each factor_wide is zscore-normalized per cross-section, then averaged.
    """
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    records = []
    for d in month_ends:
        d_str = str(d)
        if d_str not in efwd.index:
            continue

        # Collect zscored factors for this date
        factor_series = []
        for fw, dirn in zip(factor_wides, directions, strict=False):
            fw_idx = fw.index.astype(str) if not isinstance(fw.index[0], str) else fw.index
            if d_str not in fw_idx:
                break
            row = fw.loc[d_str] if d_str in fw.index else None
            if row is None:
                # try with str conversion
                fw2 = fw.copy()
                fw2.index = fw2.index.astype(str)
                if d_str not in fw2.index:
                    break
                row = fw2.loc[d_str]
            factor_series.append(dirn * row)
        else:
            # All factors available
            fwd_cross = efwd.loc[d_str].dropna()

            # Stack and find common stocks
            combined = pd.DataFrame({f'f{i}': fs for i, fs in enumerate(factor_series)})
            combined = combined.dropna()
            common = combined.index.intersection(fwd_cross.index)
            if len(common) < 100:
                continue

            # Cross-sectional zscore each factor, then average
            zscored = combined.loc[common].apply(cs_zscore, axis=0)
            composite = zscored.mean(axis=1)

            ic, pval = stats.spearmanr(composite.values, fwd_cross[common].values)
            records.append({'date': d_str, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})

    return pd.DataFrame(records)


def main():
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ══════════════════════════════════════════════════════════════
    # DATA LOADING
    # ══════════════════════════════════════════════════════════════
    print("=" * 80)
    print("BATCH 7: v1.2 FACTOR VALIDATION")
    print("=" * 80)

    print("\n[DATA] Loading klines_daily...")
    klines = pd.read_sql("""
        SELECT code, trade_date,
               open::float as open_price,
               high::float as high_price,
               close::float as close_raw,
               pre_close::float as pre_close,
               close::float * adj_factor::float as adj_close,
               volume::float as volume
        FROM klines_daily
        WHERE trade_date >= '2020-01-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(klines):,}, codes: {klines['code'].nunique()}")

    print("[DATA] Loading CSI300 benchmark...")
    bench = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-01-01'
        ORDER BY trade_date
    """, conn)

    print("[DATA] Loading baseline 5 factors from factor_values...")
    baseline_factors = pd.read_sql(f"""
        SELECT code, trade_date, factor_name, zscore::float as value
        FROM factor_values
        WHERE factor_name IN ({','.join(f"'{f}'" for f in BASELINE_5)})
          AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
    """, conn)
    print(f"  Baseline factor rows: {len(baseline_factors):,}")

    # Also load volatility_20 raw for regression
    print("[DATA] Loading volatility_20 zscore for regression...")
    vol20_raw = pd.read_sql("""
        SELECT code, trade_date, zscore::float as vol20_zscore
        FROM factor_values
        WHERE factor_name = 'volatility_20' AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
    """, conn)

    # Also load momentum_20 for mf_divergence correlation check
    print("[DATA] Loading momentum_20 zscore...")
    mom20_raw = pd.read_sql("""
        SELECT code, trade_date, zscore::float as mom20_zscore
        FROM factor_values
        WHERE factor_name = 'momentum_20' AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
    """, conn)

    print("[DATA] Loading moneyflow_daily...")
    mf = pd.read_sql("""
        SELECT code, trade_date, net_mf_amount::float as net_mf_amount
        FROM moneyflow_daily
        WHERE trade_date >= '2020-06-01'
        ORDER BY trade_date, code
    """, conn)
    print(f"  Moneyflow rows: {len(mf):,}")

    conn.close()

    # ── Pivot to wide ──
    print("[DATA] Pivoting...")
    adj_close_wide = klines.pivot(index='trade_date', columns='code', values='adj_close')
    open_wide = klines.pivot(index='trade_date', columns='code', values='open_price')
    high_wide = klines.pivot(index='trade_date', columns='code', values='high_price')
    close_raw_wide = klines.pivot(index='trade_date', columns='code', values='close_raw')
    pre_close_wide = klines.pivot(index='trade_date', columns='code', values='pre_close')
    klines.pivot(index='trade_date', columns='code', values='volume')
    mf_wide = mf.pivot(index='trade_date', columns='code', values='net_mf_amount')

    common_dates = adj_close_wide.index.sort_values()
    bench_close = bench.set_index('trade_date')['close'].reindex(common_dates)

    # Forward 5-day excess return
    print("[DATA] Computing 5-day forward excess return...")
    ac = adj_close_wide.reindex(common_dates)
    fwd_ret = ac.shift(-5) / ac - 1
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # Month-end dates
    dates_series = pd.Series(common_dates)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period('M')).last().values
    month_ends = [str(d) for d in month_ends]
    # Filter to 2021-2025
    month_ends = [d for d in month_ends if '2021-01' <= d <= '2025-12-31']

    # Baseline factor pivots
    baseline_pivots = {}
    for fname, fgrp in baseline_factors.groupby('factor_name'):
        fp = fgrp.pivot(index='trade_date', columns='code', values='value')
        fp.index = fp.index.astype(str)
        baseline_pivots[fname] = fp

    vol20_wide = vol20_raw.pivot(index='trade_date', columns='code', values='vol20_zscore')
    vol20_wide.index = vol20_wide.index.astype(str)

    mom20_wide = mom20_raw.pivot(index='trade_date', columns='code', values='mom20_zscore')
    mom20_wide.index = mom20_wide.index.astype(str)

    print(f"[DATA] Ready. {len(common_dates)} days, {len(month_ends)} month-ends (2021-2025)")
    print(f"[DATA] Load time: {time.time()-t0:.1f}s\n")

    # ══════════════════════════════════════════════════════════════
    # TASK 0: Baseline 5-factor composite IC (reference)
    # ══════════════════════════════════════════════════════════════
    print("=" * 80)
    print("TASK 0: BASELINE 5-FACTOR COMPOSITE IC")
    print("=" * 80)

    baseline_wides = [baseline_pivots[f] for f in BASELINE_5]
    baseline_dirs = [FACTOR_DIRECTIONS[f] for f in BASELINE_5]
    ic_5fac = composite_factor_ic(baseline_wides, baseline_dirs, excess_fwd, month_ends)
    s_5fac = print_ic_table("5-Factor Baseline (equal-weight)", ic_5fac)

    # ══════════════════════════════════════════════════════════════
    # TASK 1: close_to_high_ratio — neutralize vol_20
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("TASK 1: CLOSE_TO_HIGH_RATIO — NEUTRALIZE VOL_20")
    print("=" * 80)
    print("Method: cross-sectional OLS residual of close_to_high on vol_20")
    print("If residual IC > 3% => independent signal; < 2% => redundant")

    # Compute close_to_high_ratio_20
    cl = close_raw_wide.reindex(common_dates)
    hi = high_wide.reindex(common_dates)
    close_to_high = cl / hi.replace(0, np.nan)
    close_to_high_20 = close_to_high.rolling(window=20, min_periods=15).mean()
    close_to_high_20.index = close_to_high_20.index.astype(str)

    # 1a. Raw IC (both directions)
    print("\n--- 1a. Raw close_to_high_ratio_20 IC ---")
    ic_c2h_pos = compute_monthly_ic_series(close_to_high_20, excess_fwd, month_ends, direction=+1)
    ic_c2h_neg = compute_monthly_ic_series(close_to_high_20, excess_fwd, month_ends, direction=-1)

    if abs(ic_c2h_neg['ic'].mean()) > abs(ic_c2h_pos['ic'].mean()):
        c2h_dir = -1
        ic_c2h_raw = ic_c2h_neg
        print("  Best direction: -1 (close near high => underperform, reversal)")
    else:
        c2h_dir = +1
        ic_c2h_raw = ic_c2h_pos
        print("  Best direction: +1 (close near high => outperform, buy-side strength)")

    s_c2h_raw = print_ic_table("close_to_high_ratio_20 (RAW)", ic_c2h_raw, c2h_dir)

    # 1b. Cross-sectional correlation with vol_20
    print("\n--- 1b. Cross-sectional correlation with vol_20 ---")
    corr_samples = []
    sample_dates = month_ends[::3]  # every 3rd month
    for d in sample_dates:
        if d in close_to_high_20.index and d in vol20_wide.index:
            c2h = close_to_high_20.loc[d].dropna()
            v20 = vol20_wide.loc[d].dropna()
            common = c2h.index.intersection(v20.index)
            if len(common) > 100:
                c, _ = stats.spearmanr(c2h[common].values, v20[common].values)
                corr_samples.append(c)
    if corr_samples:
        avg_corr = np.mean(corr_samples)
        print(f"  Avg Spearman corr(close_to_high, vol_20): {avg_corr:.4f} (N={len(corr_samples)} dates)")
    else:
        avg_corr = np.nan
        print("  WARNING: Could not compute correlation")

    # 1c. Neutralized IC: regress out vol_20 cross-sectionally each month
    print("\n--- 1c. Neutralized IC (residual after regressing out vol_20) ---")
    residual_wide_rows = {}
    for d in close_to_high_20.index:
        if d not in vol20_wide.index:
            continue
        c2h = close_to_high_20.loc[d].dropna()
        v20 = vol20_wide.loc[d].dropna()
        common = c2h.index.intersection(v20.index)
        if len(common) < 100:
            continue
        # OLS: c2h = alpha + beta * vol20 + residual
        x = v20[common].values
        y = c2h[common].values
        # Add constant
        X = np.column_stack([np.ones(len(x)), x])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            residuals = y - X @ beta
            residual_wide_rows[d] = pd.Series(residuals, index=common)
        except Exception:
            continue

    residual_wide = pd.DataFrame(residual_wide_rows).T
    residual_wide.index.name = 'trade_date'
    print(f"  Residual computed for {len(residual_wide)} dates")

    # IC of residual
    ic_resid_pos = compute_monthly_ic_series(residual_wide, excess_fwd, month_ends, direction=+1)
    ic_resid_neg = compute_monthly_ic_series(residual_wide, excess_fwd, month_ends, direction=-1)

    if abs(ic_resid_neg['ic'].mean()) > abs(ic_resid_pos['ic'].mean()):
        resid_dir = -1
        ic_resid = ic_resid_neg
    else:
        resid_dir = +1
        ic_resid = ic_resid_pos

    s_resid = print_ic_table("close_to_high RESIDUAL (vol_20 removed)", ic_resid, resid_dir)

    # Verdict
    resid_ic = abs(s_resid['ic_mean']) if s_resid['n_months'] > 0 else 0
    print(f"\n  >>> VERDICT: Residual |IC| = {resid_ic*100:.2f}%")
    if resid_ic > 0.03:
        c2h_verdict = "PASS"
        print("      PASS: > 3% => INDEPENDENT signal beyond vol_20")
    elif resid_ic > 0.02:
        c2h_verdict = "MARGINAL"
        print("      MARGINAL: 2-3% => weak independent signal, proceed with caution")
    else:
        c2h_verdict = "FAIL"
        print("      FAIL: < 2% => likely REDUNDANT with vol_20")

    # ══════════════════════════════════════════════════════════════
    # TASK 2: mf_momentum_divergence incremental IC
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("TASK 2: MF_MOMENTUM_DIVERGENCE — INCREMENTAL IC VALIDATION")
    print("=" * 80)
    print("Formula: rank(net_mf_amount rolling 5d sum) - rank(momentum_20)")
    print("Divergence = capital flow direction disagrees with price trend")
    print("Test: 6-factor IC (5 baseline + mf_divergence) vs 5-factor IC")

    # Compute mf_momentum_divergence
    mf_w = mf_wide.reindex(common_dates)
    mf_5d_sum = mf_w.rolling(window=5, min_periods=3).sum()
    mf_5d_sum.index = mf_5d_sum.index.astype(str)

    # For momentum_20: we need raw momentum, not zscore. Use adj_close pct_change(20).
    mom_20_raw = ac.pct_change(periods=20)
    mom_20_raw.index = mom_20_raw.index.astype(str)

    # Divergence: rank(mf) - rank(mom) cross-sectionally
    mf_div_rows = {}
    for d in month_ends:
        if d not in mf_5d_sum.index or d not in mom_20_raw.index:
            continue
        mf_cross = mf_5d_sum.loc[d].dropna()
        mom_cross = mom_20_raw.loc[d].dropna()
        common = mf_cross.index.intersection(mom_cross.index)
        if len(common) < 100:
            continue
        mf_rank = mf_cross[common].rank(pct=True)
        mom_rank = mom_cross[common].rank(pct=True)
        divergence = mf_rank - mom_rank  # >0 means money flowing in but price hasn't moved up yet
        mf_div_rows[d] = divergence

    mf_div_wide = pd.DataFrame(mf_div_rows).T

    # Also compute daily version for composite IC
    print("  Computing daily mf_divergence...")
    mf_div_daily_rows = {}
    all_dates_str = [str(d) for d in common_dates]
    for d in all_dates_str:
        if d < '2021-01-01':
            continue
        if d not in mf_5d_sum.index or d not in mom_20_raw.index:
            continue
        mf_cross = mf_5d_sum.loc[d].dropna()
        mom_cross = mom_20_raw.loc[d].dropna()
        common = mf_cross.index.intersection(mom_cross.index)
        if len(common) < 100:
            continue
        mf_rank = mf_cross[common].rank(pct=True)
        mom_rank = mom_cross[common].rank(pct=True)
        mf_div_daily_rows[d] = mf_rank - mom_rank
    mf_div_daily = pd.DataFrame(mf_div_daily_rows).T
    print(f"  mf_divergence: {len(mf_div_daily)} daily dates, {len(mf_div_wide)} monthly dates")

    # 2a. Single factor IC
    print("\n--- 2a. mf_momentum_divergence single factor IC ---")
    ic_mfd_pos = compute_monthly_ic_series(mf_div_wide, excess_fwd, month_ends, direction=+1)
    ic_mfd_neg = compute_monthly_ic_series(mf_div_wide, excess_fwd, month_ends, direction=-1)

    if abs(ic_mfd_pos['ic'].mean()) >= abs(ic_mfd_neg['ic'].mean()):
        mfd_dir = +1
        ic_mfd = ic_mfd_pos
    else:
        mfd_dir = -1
        ic_mfd = ic_mfd_neg

    s_mfd = print_ic_table("mf_momentum_divergence (single)", ic_mfd, mfd_dir)

    # 2b. Correlation with momentum_20 and vol_20
    print("\n--- 2b. Cross-factor correlations ---")
    for ref_name, ref_wide in [('momentum_20', mom20_wide), ('volatility_20', vol20_wide)]:
        corr_list = []
        for d in sample_dates:
            if d in mf_div_wide.index and d in ref_wide.index:
                f1 = mf_div_wide.loc[d].dropna()
                f2 = ref_wide.loc[d].dropna()
                common = f1.index.intersection(f2.index)
                if len(common) > 100:
                    c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                    corr_list.append(c)
        if corr_list:
            print(f"  corr(mf_divergence, {ref_name}): {np.mean(corr_list):.4f} (N={len(corr_list)})")

    # 2c. Incremental IC: 6-factor vs 5-factor
    print("\n--- 2c. 6-Factor (5 baseline + mf_divergence) vs 5-Factor IC ---")
    factor6_wides = [baseline_pivots[f] for f in BASELINE_5] + [mf_div_daily]
    factor6_dirs = [FACTOR_DIRECTIONS[f] for f in BASELINE_5] + [mfd_dir]
    ic_6fac = composite_factor_ic(factor6_wides, factor6_dirs, excess_fwd, month_ends)
    s_6fac = print_ic_table("6-Factor (5 baseline + mf_divergence)", ic_6fac)

    # Compare
    ic5_mean = s_5fac['ic_mean'] if s_5fac['n_months'] > 0 else np.nan
    ic6_mean = s_6fac['ic_mean'] if s_6fac['n_months'] > 0 else np.nan
    delta_6v5 = ic6_mean - ic5_mean if not (np.isnan(ic5_mean) or np.isnan(ic6_mean)) else np.nan

    print("\n  >>> COMPARISON:")
    print(f"      5-Factor IC: {ic5_mean:+.4f}")
    print(f"      6-Factor IC: {ic6_mean:+.4f}")
    print(f"      Delta:       {delta_6v5:+.4f}" if not np.isnan(delta_6v5) else "      Delta:       N/A")

    if not np.isnan(delta_6v5) and delta_6v5 > 0.005:
        mfd_verdict = "PASS"
        print("      PASS: Delta > 0.5% => mf_divergence has incremental value")
    elif not np.isnan(delta_6v5) and delta_6v5 > 0:
        mfd_verdict = "MARGINAL"
        print("      MARGINAL: Delta positive but < 0.5%")
    else:
        mfd_verdict = "FAIL"
        print("      FAIL: No incremental value")

    # Annual comparison 5-factor vs 6-factor
    print("\n--- 2d. Annual comparison ---")
    ic5_df = ic_5fac.copy()
    ic5_df['date'] = pd.to_datetime(ic5_df['date'])
    ic5_df['year'] = ic5_df['date'].dt.year
    ic6_df = ic_6fac.copy()
    ic6_df['date'] = pd.to_datetime(ic6_df['date'])
    ic6_df['year'] = ic6_df['date'].dt.year

    print(f"  {'Year':<6} {'5-Fac IC':>10} {'6-Fac IC':>10} {'Delta':>8}")
    print(f"  {'-'*38}")
    for year in sorted(set(ic5_df['year'].unique()) | set(ic6_df['year'].unique())):
        ic5y = ic5_df[ic5_df['year'] == year]['ic'].mean() if year in ic5_df['year'].values else np.nan
        ic6y = ic6_df[ic6_df['year'] == year]['ic'].mean() if year in ic6_df['year'].values else np.nan
        dy = ic6y - ic5y if not (np.isnan(ic5y) or np.isnan(ic6y)) else np.nan
        print(f"  {year:<6} {ic5y:>+10.4f} {ic6y:>+10.4f} {dy:>+8.4f}" if not np.isnan(dy)
              else f"  {year:<6} {'N/A':>10} {'N/A':>10} {'N/A':>8}")

    # ══════════════════════════════════════════════════════════════
    # TASK 3: 7-FACTOR COMBINATION IC (conditional)
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("TASK 3: 7-FACTOR COMBINATION IC")
    print("=" * 80)

    # Determine which version of close_to_high to use
    if c2h_verdict in ("PASS", "MARGINAL"):
        if c2h_verdict == "PASS":
            # Use residualized version
            c2h_factor = residual_wide
            c2h_name = "close_to_high_RESIDUAL"
        else:
            # Use raw but note caution
            c2h_factor = close_to_high_20
            c2h_name = "close_to_high_RAW (marginal)"
        c2h_direction = resid_dir if c2h_verdict == "PASS" else c2h_dir

        print(f"Using {c2h_name} (verdict={c2h_verdict})")

        factor7_wides = [baseline_pivots[f] for f in BASELINE_5] + [mf_div_daily, c2h_factor]
        factor7_dirs = [FACTOR_DIRECTIONS[f] for f in BASELINE_5] + [mfd_dir, c2h_direction]

        ic_7fac = composite_factor_ic(factor7_wides, factor7_dirs, excess_fwd, month_ends)
        s_7fac = print_ic_table(f"7-Factor (5 + mf_div + {c2h_name})", ic_7fac)

        ic7_mean = s_7fac['ic_mean'] if s_7fac['n_months'] > 0 else np.nan
        delta_7v5 = ic7_mean - ic5_mean if not np.isnan(ic7_mean) else np.nan
        delta_7v6 = ic7_mean - ic6_mean if not (np.isnan(ic7_mean) or np.isnan(ic6_mean)) else np.nan

        print("\n  >>> 7-Factor vs baseline:")
        print(f"      5-Factor IC: {ic5_mean:+.4f}")
        print(f"      6-Factor IC: {ic6_mean:+.4f}")
        print(f"      7-Factor IC: {ic7_mean:+.4f}")
        print(f"      7 vs 5 Delta: {delta_7v5:+.4f}" if not np.isnan(delta_7v5) else "      7 vs 5: N/A")
        print(f"      7 vs 6 Delta: {delta_7v6:+.4f}" if not np.isnan(delta_7v6) else "      7 vs 6: N/A")

        # Annual breakdown
        ic7_df = ic_7fac.copy()
        ic7_df['date'] = pd.to_datetime(ic7_df['date'])
        ic7_df['year'] = ic7_df['date'].dt.year
        print(f"\n  {'Year':<6} {'5-Fac':>8} {'6-Fac':>8} {'7-Fac':>8} {'7v5':>8}")
        print(f"  {'-'*44}")
        for year in sorted(set(ic5_df['year'].unique()) | set(ic6_df['year'].unique()) | set(ic7_df['year'].unique())):
            i5 = ic5_df[ic5_df['year']==year]['ic'].mean() if year in ic5_df['year'].values else np.nan
            i6 = ic6_df[ic6_df['year']==year]['ic'].mean() if year in ic6_df['year'].values else np.nan
            i7 = ic7_df[ic7_df['year']==year]['ic'].mean() if year in ic7_df['year'].values else np.nan
            d7 = i7 - i5 if not (np.isnan(i7) or np.isnan(i5)) else np.nan
            print(f"  {year:<6} {i5:>+8.4f} {i6:>+8.4f} {i7:>+8.4f} {d7:>+8.4f}")
    else:
        print("  close_to_high FAILED redundancy check. Skipping 7-factor with c2h.")
        print("  Will test alternatives below.")

    # ══════════════════════════════════════════════════════════════
    # TASK 4: ALTERNATIVE — price_to_ma20_ratio
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("TASK 4: ALTERNATIVE — PRICE_TO_MA20_RATIO")
    print("=" * 80)
    print("Formula: close / MA(close, 20) - 1")
    print("Hypothesis: far from MA20 => mean reversion")

    ma20 = close_raw_wide.rolling(window=20, min_periods=15).mean()
    price_to_ma20 = close_raw_wide / ma20.replace(0, np.nan) - 1
    price_to_ma20 = price_to_ma20.replace([np.inf, -np.inf], np.nan)
    price_to_ma20.index = price_to_ma20.index.astype(str)

    # 4a. Raw IC
    ic_pma_pos = compute_monthly_ic_series(price_to_ma20, excess_fwd, month_ends, direction=+1)
    ic_pma_neg = compute_monthly_ic_series(price_to_ma20, excess_fwd, month_ends, direction=-1)

    if abs(ic_pma_neg['ic'].mean()) > abs(ic_pma_pos['ic'].mean()):
        pma_dir = -1
        ic_pma = ic_pma_neg
    else:
        pma_dir = +1
        ic_pma = ic_pma_pos

    s_pma = print_ic_table("price_to_ma20_ratio (RAW)", ic_pma, pma_dir)

    # 4b. Correlation with vol_20 and close_to_high
    print("\n--- 4b. Correlations ---")
    for ref_name, ref_wide in [('volatility_20', vol20_wide), ('close_to_high_20', close_to_high_20)]:
        corr_list = []
        for d in sample_dates:
            if d in price_to_ma20.index and d in ref_wide.index:
                f1 = price_to_ma20.loc[d].dropna()
                f2 = ref_wide.loc[d].dropna()
                common = f1.index.intersection(f2.index)
                if len(common) > 100:
                    c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                    corr_list.append(c)
        if corr_list:
            print(f"  corr(price_to_ma20, {ref_name}): {np.mean(corr_list):.4f} (N={len(corr_list)})")

    # 4c. Neutralize vol_20
    print("\n--- 4c. Neutralized IC (residual after vol_20) ---")
    pma_resid_rows = {}
    for d in price_to_ma20.index:
        if d not in vol20_wide.index:
            continue
        pma = price_to_ma20.loc[d].dropna()
        v20 = vol20_wide.loc[d].dropna()
        common = pma.index.intersection(v20.index)
        if len(common) < 100:
            continue
        x = v20[common].values
        y = pma[common].values
        X = np.column_stack([np.ones(len(x)), x])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            residuals = y - X @ beta
            pma_resid_rows[d] = pd.Series(residuals, index=common)
        except Exception:
            continue

    pma_resid_wide = pd.DataFrame(pma_resid_rows).T
    ic_pma_resid_pos = compute_monthly_ic_series(pma_resid_wide, excess_fwd, month_ends, direction=+1)
    ic_pma_resid_neg = compute_monthly_ic_series(pma_resid_wide, excess_fwd, month_ends, direction=-1)

    if abs(ic_pma_resid_neg['ic'].mean()) > abs(ic_pma_resid_pos['ic'].mean()):
        pma_resid_dir = -1
        ic_pma_resid = ic_pma_resid_neg
    else:
        pma_resid_dir = +1
        ic_pma_resid = ic_pma_resid_pos

    s_pma_resid = print_ic_table("price_to_ma20_RESIDUAL (vol_20 removed)", ic_pma_resid, pma_resid_dir)

    # 4d. If price_to_ma20 residual is better than close_to_high residual, test 7-factor with it
    pma_resid_ic = abs(s_pma_resid['ic_mean']) if s_pma_resid['n_months'] > 0 else 0
    c2h_resid_ic = resid_ic

    print("\n  >>> COMPARISON of alternatives (neutralized IC):")
    print(f"      close_to_high residual |IC|: {c2h_resid_ic*100:.2f}%")
    print(f"      price_to_ma20 residual |IC|: {pma_resid_ic*100:.2f}%")

    better_alt = None
    if pma_resid_ic > c2h_resid_ic and pma_resid_ic > 0.02:
        print("      => price_to_ma20 is a better candidate")
        better_alt = ('price_to_ma20_resid', pma_resid_wide, pma_resid_dir)
    elif c2h_resid_ic > 0.02:
        print("      => close_to_high_resid remains better")
    else:
        print("      => Neither has strong independent signal")

    # If we have a better alternative and c2h failed, test 7-factor
    if better_alt and c2h_verdict == "FAIL":
        alt_name, alt_wide, alt_dir = better_alt
        print(f"\n  Testing 7-factor with {alt_name}...")
        factor7_alt_wides = [baseline_pivots[f] for f in BASELINE_5] + [mf_div_daily, alt_wide]
        factor7_alt_dirs = [FACTOR_DIRECTIONS[f] for f in BASELINE_5] + [mfd_dir, alt_dir]
        ic_7fac_alt = composite_factor_ic(factor7_alt_wides, factor7_alt_dirs, excess_fwd, month_ends)
        print_ic_table(f"7-Factor (5 + mf_div + {alt_name})", ic_7fac_alt)

    # ══════════════════════════════════════════════════════════════
    # TASK 5: INTRADAY_OVERNIGHT_SPLIT
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("TASK 5: INTRADAY_OVERNIGHT_SPLIT")
    print("=" * 80)
    print("Formula: mean((close-open)/close, 20d) - mean((open-pre_close)/pre_close, 20d)")
    print("Difference version (avoids division by zero)")

    op = open_wide.reindex(common_dates)
    cl_raw = close_raw_wide.reindex(common_dates)
    pc = pre_close_wide.reindex(common_dates)

    intraday_ret = (cl_raw - op) / cl_raw.replace(0, np.nan)
    overnight_ret = (op - pc) / pc.replace(0, np.nan)

    intraday_avg_20 = intraday_ret.rolling(window=20, min_periods=15).mean()
    overnight_avg_20 = overnight_ret.rolling(window=20, min_periods=15).mean()

    io_split = intraday_avg_20 - overnight_avg_20
    io_split = io_split.replace([np.inf, -np.inf], np.nan)
    io_split.index = io_split.index.astype(str)

    # IC both directions
    ic_io_pos = compute_monthly_ic_series(io_split, excess_fwd, month_ends, direction=+1)
    ic_io_neg = compute_monthly_ic_series(io_split, excess_fwd, month_ends, direction=-1)

    if abs(ic_io_neg['ic'].mean()) > abs(ic_io_pos['ic'].mean()):
        io_dir = -1
        ic_io = ic_io_neg
    else:
        io_dir = +1
        ic_io = ic_io_pos

    s_io = print_ic_table("intraday_overnight_split", ic_io, io_dir)

    # Correlation with existing factors
    print("\n--- Correlations with baseline factors ---")
    for ref_name, ref_wide in [('volatility_20', vol20_wide), ('momentum_20', mom20_wide),
                                ('close_to_high_20', close_to_high_20)]:
        corr_list = []
        for d in sample_dates:
            if d in io_split.index and d in ref_wide.index:
                f1 = io_split.loc[d].dropna()
                f2 = ref_wide.loc[d].dropna()
                common = f1.index.intersection(f2.index)
                if len(common) > 100:
                    c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                    corr_list.append(c)
        if corr_list:
            print(f"  corr(io_split, {ref_name}): {np.mean(corr_list):.4f}")

    # ══════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("FINAL SUMMARY — BATCH 7 v1.2 FACTOR DECISIONS")
    print("=" * 80)

    print(f"\n  {'Factor':<40} {'|IC|%':>6} {'t-stat':>7} {'Verdict':>10}")
    print(f"  {'-'*65}")
    print(f"  {'5-Factor Baseline (composite)':<40} {abs(s_5fac['ic_mean'])*100:>6.2f} {s_5fac['t_stat']:>7.2f} {'REF':>10}")

    if s_c2h_raw and s_c2h_raw['n_months'] > 0:
        print(f"  {'close_to_high RAW (single)':<40} {abs(s_c2h_raw['ic_mean'])*100:>6.2f} {s_c2h_raw['t_stat']:>7.2f} {'':>10}")
    if s_resid and s_resid['n_months'] > 0:
        print(f"  {'close_to_high RESIDUAL (vol_20 out)':<40} {abs(s_resid['ic_mean'])*100:>6.2f} {s_resid['t_stat']:>7.2f} {c2h_verdict:>10}")

    if s_mfd and s_mfd['n_months'] > 0:
        print(f"  {'mf_momentum_divergence (single)':<40} {abs(s_mfd['ic_mean'])*100:>6.2f} {s_mfd['t_stat']:>7.2f} {'':>10}")
    if s_6fac and s_6fac['n_months'] > 0:
        print(f"  {'6-Factor (5+mf_div) composite':<40} {abs(s_6fac['ic_mean'])*100:>6.2f} {s_6fac['t_stat']:>7.2f} {mfd_verdict:>10}")

    if s_pma and s_pma['n_months'] > 0:
        print(f"  {'price_to_ma20_ratio RAW':<40} {abs(s_pma['ic_mean'])*100:>6.2f} {s_pma['t_stat']:>7.2f} {'':>10}")
    if s_pma_resid and s_pma_resid['n_months'] > 0:
        print(f"  {'price_to_ma20 RESIDUAL (vol_20 out)':<40} {abs(s_pma_resid['ic_mean'])*100:>6.2f} {s_pma_resid['t_stat']:>7.2f} {'':>10}")

    if s_io and s_io['n_months'] > 0:
        print(f"  {'intraday_overnight_split':<40} {abs(s_io['ic_mean'])*100:>6.2f} {s_io['t_stat']:>7.2f} {'':>10}")

    # Recommendation
    print("\n  RECOMMENDATION:")
    if mfd_verdict in ("PASS", "MARGINAL"):
        print("    [1] ADD mf_momentum_divergence to baseline (6-factor)")
    else:
        print("    [1] DO NOT ADD mf_momentum_divergence (no incremental value)")

    if c2h_verdict == "PASS":
        print("    [2] ADD close_to_high RESIDUALIZED version (7-factor)")
    elif c2h_verdict == "MARGINAL":
        print("    [2] close_to_high MARGINAL — monitor, use raw version cautiously")
    elif better_alt and pma_resid_ic > 0.02:
        print("    [2] SUBSTITUTE with price_to_ma20_residual (better independence from vol_20)")
    else:
        print("    [2] NO good 7th factor candidate — stay at 6 factors")

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
