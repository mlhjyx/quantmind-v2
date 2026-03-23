"""
Batch 4 Factor IC Analysis (4 factors — new dimensions)
========================================================
1. turnover_skewness_20: skewness of 20d turnover_rate
2. return_consistency_20: fraction of positive-return days in 20d
3. gap_frequency_20: fraction of 20d with |open/pre_close - 1| > 2%
4. relative_volume_20: today's volume / mean(volume, 60d)

Factor 1 (shareholder_concentration) skipped: daily_basic has no
shareholders_num column; data not in DB.

DB: postgresql://quantmind:quantmind@localhost:5432/quantmind_v2
"""

import pandas as pd
import numpy as np
import psycopg2
from scipy import stats
from datetime import date as dt_date
import time
import warnings
warnings.filterwarnings('ignore')
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header

DB_URI = 'postgresql://quantmind:quantmind@localhost:5432/quantmind_v2'


# ── IC computation helper (same as batch3) ──
def compute_monthly_ic(factor_wide, excess_fwd, month_ends,
                       direction=1,
                       date_range=(dt_date(2021, 1, 1), dt_date(2025, 12, 31))):
    """Compute monthly Spearman IC between factor and forward excess return."""
    fac = factor_wide.copy()
    fac.index = fac.index.astype(str)
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    ic_records = []
    for d in month_ends:
        d_str = str(d)
        d_date = pd.Timestamp(d_str).date()
        if d_date < date_range[0] or d_date > date_range[1]:
            continue
        if d_str not in fac.index or d_str not in efwd.index:
            continue
        fac_cross = fac.loc[d_str].dropna()
        fwd_cross = efwd.loc[d_str].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        vals = direction * fac_cross[common].values
        ic, pval = stats.spearmanr(vals, fwd_cross[common].values)
        ic_records.append({'date': d_str, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})
    return pd.DataFrame(ic_records)


def print_ic_report(name: str, formula: str, ic_df: pd.DataFrame) -> dict | None:
    """Print standardized IC report for a factor."""
    if len(ic_df) == 0:
        print(f"\n{'='*70}")
        print(f"  {name}: NO DATA (all months filtered)")
        print(f"{'='*70}")
        return None

    ic_df = ic_df.copy()
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    ic_mean = ic_df['ic'].mean()
    ic_std = ic_df['ic'].std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0
    pct_pos = (ic_df['ic'] > 0).mean() * 100

    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"Formula: {formula}")
    print(f"{'='*70}")

    print(f"\n-- Overall ({ic_df['date'].min().strftime('%Y-%m')} ~ {ic_df['date'].max().strftime('%Y-%m')}) --")
    print(f"  IC Mean:     {ic_mean:.4f}  ({abs(ic_mean)*100:.2f}%)")
    print(f"  IC Std:      {ic_std:.4f}")
    print(f"  IC_IR:       {ic_ir:.4f}")
    print(f"  t-stat:      {t_stat:.2f}  {'***' if abs(t_stat)>2.58 else '**' if abs(t_stat)>1.96 else '*' if abs(t_stat)>1.64 else 'ns'}")
    print(f"  IC > 0:      {pct_pos:.1f}%")
    print(f"  Months:      {len(ic_df)}")

    # Annual breakdown
    print(f"\n-- Annual Breakdown --")
    print(f"  {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t-stat':>8} {'IC>0%':>6} {'N':>4}")
    print(f"  {'-'*52}")
    for year, grp in ic_df.groupby('year'):
        ym = grp['ic'].mean()
        ys = grp['ic'].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp['ic'] > 0).mean() * 100
        print(f"  {year:<6} {ym:>8.4f} {ys:>8.4f} {yir:>8.4f} {yt:>8.2f} {yp:>5.1f}% {len(grp):>4}")

    # Monthly IC series (condensed)
    print(f"\n-- Monthly IC (condensed) --")
    print(f"  {'Month':<10} {'IC':>8} {'N':>6}")
    print(f"  {'-'*26}")
    for _, row in ic_df.iterrows():
        marker = ' *' if abs(row['ic']) > 0.05 else ''
        print(f"  {row['date'].strftime('%Y-%m'):<10} {row['ic']:>8.4f} {int(row['n_stocks']):>6}{marker}")

    # Verdict
    print(f"\n  VERDICT: ", end='')
    if abs(t_stat) > 1.96 and abs(ic_mean) > 0.02:
        print(f"PASS (t={t_stat:.2f}, IC={ic_mean:.4f})")
    elif abs(t_stat) > 1.64 and abs(ic_mean) > 0.015:
        print(f"MARGINAL (t={t_stat:.2f}, IC={ic_mean:.4f})")
    else:
        print(f"FAIL (t={t_stat:.2f}, IC={ic_mean:.4f})")

    return {'name': name, 'ic_mean': ic_mean, 'ic_std': ic_std, 'ic_ir': ic_ir,
            't_stat': t_stat, 'pct_pos': pct_pos, 'n_months': len(ic_df)}


def rolling_skewness(df: pd.DataFrame, window: int = 20, min_periods: int = 15) -> pd.DataFrame:
    """Compute rolling skewness for each column efficiently."""
    return df.rolling(window=window, min_periods=min_periods).skew()


def main():
    print_config_header()
    t0 = time.time()

    # ════════════════════════════════════════════════════════════════
    # SHARED DATA LOADING
    # ════════════════════════════════════════════════════════════════
    conn = psycopg2.connect(DB_URI)

    # 1. klines_daily: adj_close, open, pre_close, close, volume, pct_change
    print("[DATA] Loading klines_daily...")
    klines = pd.read_sql("""
        SELECT code, trade_date,
               open::float as open_price,
               close::float as close_raw,
               pre_close::float as pre_close,
               close::float * adj_factor::float as adj_close,
               volume::float as volume,
               pct_change::float / 100 as ret
        FROM klines_daily
        WHERE trade_date >= '2020-01-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(klines):,}, codes: {klines['code'].nunique()}")

    # 2. daily_basic: turnover_rate, total_mv (for neutralization check)
    print("[DATA] Loading daily_basic...")
    basic = pd.read_sql("""
        SELECT code, trade_date,
               total_mv::float as total_mv,
               turnover_rate::float as turnover_rate
        FROM daily_basic
        WHERE trade_date >= '2020-01-01'
          AND total_mv IS NOT NULL AND total_mv > 0
          AND turnover_rate IS NOT NULL AND turnover_rate > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(basic):,}")

    # 3. CSI300 benchmark
    print("[DATA] Loading CSI300 index...")
    bench = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-01-01'
        ORDER BY trade_date
    """, conn)

    # 4. Existing factors for correlation check
    print("[DATA] Loading existing factors for correlation...")
    existing_factors = pd.read_sql("""
        SELECT code, trade_date, factor_name, zscore::float as value
        FROM factor_values
        WHERE factor_name IN ('volatility_20', 'ln_market_cap', 'momentum_20',
                              'turnover_mean_20', 'bp_ratio', 'reversal_20',
                              'idiosyncratic_volatility', 'dv_ttm')
          AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
    """, conn)
    conn.close()
    print(f"  Existing factor rows: {len(existing_factors):,}")

    # ── Pivot to wide ──
    print("[DATA] Pivoting to wide format...")
    adj_close_wide = klines.pivot(index='trade_date', columns='code', values='adj_close')
    open_wide = klines.pivot(index='trade_date', columns='code', values='open_price')
    pre_close_wide = klines.pivot(index='trade_date', columns='code', values='pre_close')
    volume_wide = klines.pivot(index='trade_date', columns='code', values='volume')
    ret_wide = klines.pivot(index='trade_date', columns='code', values='ret')

    turnover_wide = basic.pivot(index='trade_date', columns='code', values='turnover_rate')
    total_mv_wide = basic.pivot(index='trade_date', columns='code', values='total_mv')

    # Align to common dates
    common_dates = adj_close_wide.index.intersection(turnover_wide.index).sort_values()

    bench_close = bench.set_index('trade_date')['close'].reindex(common_dates)

    # ── Forward 5-day excess return (shared) ──
    print("[DATA] Computing 5-day forward excess return...")
    ac = adj_close_wide.reindex(common_dates)
    fwd_ret = ac.shift(-5) / ac - 1
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # ── Month-end dates ──
    dates_series = pd.Series(common_dates)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period('M')).last().values
    month_ends = [str(d) for d in month_ends]

    print(f"[DATA] Data ready. {len(common_dates)} trading days, month-ends: {len(month_ends)}")
    print(f"[DATA] Total load time: {time.time()-t0:.1f}s")

    results = []

    # ════════════════════════════════════════════════════════════════
    # FACTOR 1: shareholder_concentration — SKIPPED (no data)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 1: shareholder_concentration — SKIPPED")
    print("# daily_basic has no shareholders_num column.")
    print("# Would need to pull from Tushare stk_holdernumber API.")
    print("#"*70)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 2: turnover_skewness_20
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 2: turnover_skewness_20")
    print("#"*70)

    turn = turnover_wide.reindex(common_dates)
    turn_skew_20 = rolling_skewness(turn, window=20, min_periods=15)

    # Hypothesis: positive skew (a few days of abnormal high turnover = retail chasing)
    # => underperform. Direction: -1
    ic2_neg = compute_monthly_ic(turn_skew_20, excess_fwd, month_ends, direction=-1)
    ic2_pos = compute_monthly_ic(turn_skew_20, excess_fwd, month_ends, direction=+1)

    mean_neg = ic2_neg['ic'].mean() if len(ic2_neg) > 0 else 0
    mean_pos = ic2_pos['ic'].mean() if len(ic2_pos) > 0 else 0

    if abs(mean_neg) >= abs(mean_pos):
        ic2 = ic2_neg
        dir2_label = "-1 (high skew => underperform)"
    else:
        ic2 = ic2_pos
        dir2_label = "+1 (high skew => outperform)"

    r2 = print_ic_report(
        "TURNOVER_SKEWNESS_20",
        f"skewness(turnover_rate, 20d), direction={dir2_label}",
        ic2
    )
    if r2:
        results.append(r2)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 3: return_consistency_20
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 3: return_consistency_20")
    print("#"*70)

    ret = ret_wide.reindex(common_dates)
    # Fraction of positive-return days in 20d
    positive_days = (ret > 0).astype(float)
    return_consistency_20 = positive_days.rolling(window=20, min_periods=15).mean()

    # Test both directions
    ic3_pos = compute_monthly_ic(return_consistency_20, excess_fwd, month_ends, direction=+1)
    ic3_neg = compute_monthly_ic(return_consistency_20, excess_fwd, month_ends, direction=-1)

    mean3_pos = ic3_pos['ic'].mean() if len(ic3_pos) > 0 else 0
    mean3_neg = ic3_neg['ic'].mean() if len(ic3_neg) > 0 else 0

    if abs(mean3_pos) >= abs(mean3_neg):
        ic3 = ic3_pos
        dir3_label = "+1 (high consistency => outperform)"
    else:
        ic3 = ic3_neg
        dir3_label = "-1 (high consistency => underperform, i.e., reversal)"

    r3 = print_ic_report(
        "RETURN_CONSISTENCY_20",
        f"frac(ret > 0, 20d), direction={dir3_label}",
        ic3
    )
    if r3:
        results.append(r3)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 4: gap_frequency_20
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 4: gap_frequency_20")
    print("#"*70)

    op = open_wide.reindex(common_dates)
    pc = pre_close_wide.reindex(common_dates)

    # |open / pre_close - 1| > 2%
    gap_pct = (op / pc - 1).abs()
    big_gap = (gap_pct > 0.02).astype(float)
    gap_freq_20 = big_gap.rolling(window=20, min_periods=15).mean()

    # Hypothesis: frequent large gaps = info asymmetry / emotional trading => underperform
    # Direction: -1
    ic4_neg = compute_monthly_ic(gap_freq_20, excess_fwd, month_ends, direction=-1)
    ic4_pos = compute_monthly_ic(gap_freq_20, excess_fwd, month_ends, direction=+1)

    mean4_neg = ic4_neg['ic'].mean() if len(ic4_neg) > 0 else 0
    mean4_pos = ic4_pos['ic'].mean() if len(ic4_pos) > 0 else 0

    if abs(mean4_neg) >= abs(mean4_pos):
        ic4 = ic4_neg
        dir4_label = "-1 (frequent gaps => underperform)"
    else:
        ic4 = ic4_pos
        dir4_label = "+1 (frequent gaps => outperform)"

    r4 = print_ic_report(
        "GAP_FREQUENCY_20",
        f"frac(|open/pre_close - 1| > 2%, 20d), direction={dir4_label}",
        ic4
    )
    if r4:
        results.append(r4)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 5: relative_volume_20
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 5: relative_volume_20")
    print("#"*70)

    vol = volume_wide.reindex(common_dates)
    vol_mean_60 = vol.rolling(window=60, min_periods=30).mean()
    rel_vol = vol / vol_mean_60
    rel_vol = rel_vol.replace([np.inf, -np.inf], np.nan)

    # Hypothesis: abnormal high volume => overreaction => underperform
    # Direction: -1
    ic5_neg = compute_monthly_ic(rel_vol, excess_fwd, month_ends, direction=-1)
    ic5_pos = compute_monthly_ic(rel_vol, excess_fwd, month_ends, direction=+1)

    mean5_neg = ic5_neg['ic'].mean() if len(ic5_neg) > 0 else 0
    mean5_pos = ic5_pos['ic'].mean() if len(ic5_pos) > 0 else 0

    if abs(mean5_neg) >= abs(mean5_pos):
        ic5 = ic5_neg
        dir5_label = "-1 (high relative vol => underperform)"
    else:
        ic5 = ic5_pos
        dir5_label = "+1 (high relative vol => outperform)"

    r5 = print_ic_report(
        "RELATIVE_VOLUME_20",
        f"volume / mean(volume, 60d), direction={dir5_label}",
        ic5
    )
    if r5:
        results.append(r5)

    # ════════════════════════════════════════════════════════════════
    # CROSS-FACTOR CORRELATION CHECK
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# CROSS-FACTOR CORRELATION CHECK")
    print("#"*70)

    new_factors = {
        'turn_skew_20': turn_skew_20,
        'ret_consist_20': return_consistency_20,
        'gap_freq_20': gap_freq_20,
        'rel_volume_20': rel_vol,
    }

    # Normalize index to str
    for k in new_factors:
        new_factors[k] = new_factors[k].copy()
        new_factors[k].index = new_factors[k].index.astype(str)

    # Sample dates for correlation (every 6th month-end)
    sample_dates_corr = [month_ends[i] for i in range(0, len(month_ends), 6)][:10]

    # 1. New factors pairwise
    print("\n-- New Factors Pairwise Correlation (Spearman, avg over sample dates) --")
    new_names = list(new_factors.keys())
    print(f"  {'':>16}", end='')
    for n in new_names:
        print(f" {n[:14]:>14}", end='')
    print()

    for i, n1 in enumerate(new_names):
        print(f"  {n1:>16}", end='')
        for j, n2 in enumerate(new_names):
            if j <= i:
                if i == j:
                    print(f" {'1.000':>14}", end='')
                else:
                    print(f" {'':>14}", end='')
                continue
            corrs = []
            for d in sample_dates_corr:
                d_str = str(d)
                if d_str in new_factors[n1].index and d_str in new_factors[n2].index:
                    f1 = new_factors[n1].loc[d_str].dropna()
                    f2 = new_factors[n2].loc[d_str].dropna()
                    common_codes = f1.index.intersection(f2.index)
                    if len(common_codes) > 100:
                        c, _ = stats.spearmanr(f1[common_codes].values, f2[common_codes].values)
                        corrs.append(c)
            avg_c = np.mean(corrs) if corrs else np.nan
            flag = ' !' if abs(avg_c) > 0.5 else ''
            print(f" {avg_c:>13.4f}{flag}", end='')
        print()

    # 2. New factors vs existing passed factors
    if len(existing_factors) > 0:
        print("\n-- New Factors vs Existing Passed Factors --")
        existing_pivots = {}
        for fname, fgrp in existing_factors.groupby('factor_name'):
            fp = fgrp.pivot(index='trade_date', columns='code', values='value')
            fp.index = fp.index.astype(str)
            existing_pivots[fname] = fp

        ex_names = sorted(existing_pivots.keys())
        print(f"  {'New \\ Existing':>16}", end='')
        for en in ex_names:
            print(f" {en[:14]:>14}", end='')
        print()

        for nn in new_names:
            print(f"  {nn:>16}", end='')
            for en in ex_names:
                corrs = []
                for d in sample_dates_corr:
                    d_str = str(d)
                    if d_str in new_factors[nn].index and d_str in existing_pivots[en].index:
                        f1 = new_factors[nn].loc[d_str].dropna()
                        f2 = existing_pivots[en].loc[d_str].dropna()
                        common_codes = f1.index.intersection(f2.index)
                        if len(common_codes) > 100:
                            c, _ = stats.spearmanr(f1[common_codes].values, f2[common_codes].values)
                            corrs.append(c)
                avg_c = np.mean(corrs) if corrs else np.nan
                flag = ' !' if abs(avg_c) > 0.5 else ''
                print(f" {avg_c:>13.4f}{flag}", end='')
            print()

    # ════════════════════════════════════════════════════════════════
    # SUMMARY TABLE
    # ════════════════════════════════════════════════════════════════
    print("\n" + "="*80)
    print("BATCH 4 SUMMARY")
    print("="*80)
    print(f"  {'Factor':<35} {'IC_Mean':>8} {'t-stat':>8} {'IC_IR':>8} {'IC>0%':>6} {'Verdict':>10}")
    print(f"  {'-'*77}")

    for r in results:
        verdict = ("PASS" if abs(r['t_stat']) > 1.96 and abs(r['ic_mean']) > 0.02 else
                   "MARGINAL" if abs(r['t_stat']) > 1.64 and abs(r['ic_mean']) > 0.015 else
                   "FAIL")
        print(f"  {r['name']:<35} {r['ic_mean']:>8.4f} {r['t_stat']:>8.2f} {r['ic_ir']:>8.4f} {r['pct_pos']:>5.1f}% {verdict:>10}")

    print(f"\n  NOTE: shareholder_concentration skipped (no data in DB).")
    print(f"        Need Tushare stk_holdernumber API to pull shareholder count data.")
    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
