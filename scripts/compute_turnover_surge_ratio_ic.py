"""
Turnover Surge Ratio Factor IC Analysis
========================================
Formula: mean(turnover_rate, 5d) / mean(turnover_rate, 20d)
Direction: -1 (sudden turnover surge -> subsequent underperformance)

Economic rationale:
- Short-term turnover spike relative to medium-term average indicates abnormal trading activity
- Often driven by retail herding / momentum chasers entering near peaks
- In A-share market, this "hot potato" effect is well-documented
- After surge subsides, mean-reversion of attention leads to price decline

A-share applicability: HIGH
- A-share market is retail-dominated (~70% retail trading volume)
- Retail herding amplifies turnover surge effect
- Similar to "attention" factor in behavioral finance literature (Barber & Odean 2008)
"""

import pandas as pd
import numpy as np
import psycopg2
from scipy import stats
import time
import warnings
warnings.filterwarnings('ignore')
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header

DB_URI = 'postgresql://quantmind:quantmind@localhost:5432/quantmind_v2'

def main():
    print_config_header()
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ── 1. Load turnover data from daily_basic ──
    print("Loading turnover data from daily_basic...")
    df = pd.read_sql("""
        SELECT code, trade_date, turnover_rate::float
        FROM daily_basic
        WHERE trade_date >= '2020-07-01' AND turnover_rate IS NOT NULL AND turnover_rate > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(df):,}, codes: {df['code'].nunique()}")

    # ── 2. Pivot to wide format ──
    print("Pivoting to wide format...")
    turn_wide = df.pivot(index='trade_date', columns='code', values='turnover_rate')
    n_dates, n_codes = turn_wide.shape
    print(f"  Matrix: {n_dates} dates x {n_codes} codes")

    # ── 3. Compute turnover_surge_ratio = MA5 / MA20 ──
    print("Computing turnover_surge_ratio...")
    t1 = time.time()
    ma5 = turn_wide.rolling(window=5, min_periods=3).mean()
    ma20 = turn_wide.rolling(window=20, min_periods=10).mean()
    surge_ratio = ma5 / ma20
    # Replace inf/extreme values
    surge_ratio = surge_ratio.replace([np.inf, -np.inf], np.nan)
    # Clip extreme ratios (>5 or <0.1 are likely data issues)
    surge_ratio = surge_ratio.clip(0.1, 5.0)
    print(f"  Computed in {time.time()-t1:.1f}s")

    # ── 4. Forward 5-day excess return ──
    print("Computing forward returns...")
    close_df = pd.read_sql("""
        SELECT code, trade_date, close::float * adj_factor::float as adj_close
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    close_wide = close_df.pivot(index='trade_date', columns='code', values='adj_close')
    close_wide = close_wide.reindex(turn_wide.index)

    fwd_ret = close_wide.shift(-5) / close_wide - 1

    # CSI300 benchmark
    bench_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-07-01'
        ORDER BY trade_date
    """, conn)
    conn.close()

    bench_close = bench_df.set_index('trade_date')['close'].reindex(turn_wide.index)
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # ── 5. Monthly IC ──
    print("Computing monthly IC...")
    dates = pd.Series(turn_wide.index)
    dates_dt = pd.to_datetime(dates)
    month_ends = dates.groupby(dates_dt.dt.to_period('M')).last().values
    month_ends = [str(d) for d in month_ends]

    surge_ratio.index = surge_ratio.index.astype(str)
    excess_fwd.index = excess_fwd.index.astype(str)

    from datetime import date as dt_date
    ic_records = []
    for d in month_ends:
        d_date = pd.Timestamp(d).date()
        if d_date < dt_date(2021, 1, 1) or d_date > dt_date(2025, 12, 31):
            continue
        if d not in surge_ratio.index or d not in excess_fwd.index:
            continue
        fac_cross = surge_ratio.loc[d].dropna()
        fwd_cross = excess_fwd.loc[d].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        # Direction: -1 (negate factor, high surge = bad)
        ic, pval = stats.spearmanr(-fac_cross[common].values, fwd_cross[common].values)
        ic_records.append({'date': d, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})

    ic_df = pd.DataFrame(ic_records)
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    # ── 6. Results ──
    print("\n" + "="*70)
    print("TURNOVER SURGE RATIO IC Analysis (direction: -surge_ratio)")
    print("Formula: -[mean(turnover_rate, 5d) / mean(turnover_rate, 20d)]")
    print("="*70)

    ic_mean = ic_df['ic'].mean()
    ic_std = ic_df['ic'].std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0
    pct_pos = (ic_df['ic'] > 0).mean() * 100

    print(f"\n── Overall ({ic_df['date'].min().strftime('%Y-%m')} ~ {ic_df['date'].max().strftime('%Y-%m')}) ──")
    print(f"  IC Mean:     {ic_mean:.4f}")
    print(f"  IC Std:      {ic_std:.4f}")
    print(f"  IC_IR:       {ic_ir:.4f}")
    print(f"  t-stat:      {t_stat:.2f}  {'***' if abs(t_stat)>2.58 else '**' if abs(t_stat)>1.96 else '*' if abs(t_stat)>1.64 else 'ns'}")
    print(f"  IC > 0:      {pct_pos:.1f}%")
    print(f"  Months:      {len(ic_df)}")

    # Annual breakdown
    print(f"\n── Annual Breakdown ──")
    print(f"  {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t-stat':>8} {'IC>0%':>6} {'N':>4}")
    print(f"  {'-'*50}")
    for year, grp in ic_df.groupby('year'):
        ym = grp['ic'].mean()
        ys = grp['ic'].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp['ic'] > 0).mean() * 100
        print(f"  {year:<6} {ym:>8.4f} {ys:>8.4f} {yir:>8.4f} {yt:>8.2f} {yp:>5.1f}% {len(grp):>4}")

    # ── 7. Correlation with existing factors ──
    print(f"\n── Correlation with Existing Factors ──")
    conn2 = psycopg2.connect(DB_URI)
    key_factors = ['turnover_mean_20', 'turnover_std_20', 'volatility_20', 'ln_market_cap', 'momentum_20', 'bp_ratio']
    sample_dates = [month_ends[len(month_ends)//4], month_ends[len(month_ends)//2], month_ends[3*len(month_ends)//4]]
    sample_dates_str = "','".join(str(d) for d in sample_dates)
    factor_str = "','".join(key_factors)

    fv_all = pd.read_sql(f"""
        SELECT code, trade_date, factor_name, zscore::float as value
        FROM factor_values
        WHERE factor_name IN ('{factor_str}')
          AND trade_date::text IN ('{sample_dates_str}')
        ORDER BY trade_date, code
    """, conn2)
    conn2.close()

    if len(fv_all) > 0:
        corr_results = {}
        for fname, fgrp in fv_all.groupby('factor_name'):
            fv_wide = fgrp.pivot(index='trade_date', columns='code', values='value')
            fv_wide.index = fv_wide.index.astype(str)
            corrs = []
            for d in sample_dates:
                d_str = str(d)
                if d_str not in surge_ratio.index or d_str not in fv_wide.index:
                    continue
                fac_cross = surge_ratio.loc[d_str].dropna()
                fv_cross = fv_wide.loc[d_str].dropna()
                common = fac_cross.index.intersection(fv_cross.index)
                if len(common) < 100:
                    continue
                c, _ = stats.spearmanr(fac_cross[common].values, fv_cross[common].values)
                corrs.append(c)
            if corrs:
                corr_results[fname] = np.mean(corrs)

        if corr_results:
            print(f"\n  {'Factor':<25} {'Rank Corr':>10}")
            print(f"  {'-'*37}")
            for fname, corr in sorted(corr_results.items(), key=lambda x: abs(x[1]), reverse=True):
                flag = ' *** HIGH' if abs(corr) > 0.7 else ' ** MODERATE' if abs(corr) > 0.5 else ''
                print(f"  {fname:<25} {corr:>10.4f}{flag}")
    else:
        print("  No existing factors for correlation check.")

    # ── 8. Monthly IC time series ──
    print(f"\n── Monthly IC Time Series ──")
    print(f"  {'Month':<10} {'IC':>8} {'N_stocks':>8}")
    print(f"  {'-'*28}")
    for _, row in ic_df.iterrows():
        marker = ' *' if abs(row['ic']) > 0.05 else ''
        print(f"  {row['date'].strftime('%Y-%m'):<10} {row['ic']:>8.4f} {int(row['n_stocks']):>8}{marker}")

    # ── Verdict ──
    print(f"\n{'='*70}")
    print("VERDICT:")
    if abs(t_stat) > 1.96 and abs(ic_mean) > 0.02:
        print(f"  SIGNIFICANT (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Recommend adding to candidate pool.")
    elif abs(t_stat) > 1.64:
        print(f"  MARGINALLY significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Worth monitoring, may add with lower weight.")
    else:
        print(f"  NOT significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Not recommended for current factor pool.")
    print(f"{'='*70}")
    print(f"\nTotal time: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
