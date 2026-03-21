"""
K-Bar Body Ratio Factor IC Analysis
=====================================
Formula: mean(abs(close-open)/(high-low), 20d), excluding days where high==low
Direction: -1 (high body ratio = decisive candles = overreaction = subsequent reversal)

Economic rationale:
- High body ratio = large percentage of daily range is "real" movement (close-to-open)
- Sustained high body ratios indicate one-directional pressure, often overshooting fair value
- Low body ratio = indecision / high wick, balanced buying & selling
- After period of decisive candles, mean-reversion kicks in as overreaction corrects
- Related to "price efficiency" literature: efficient prices show more noise (wicks)

A-share applicability: MODERATE-HIGH
- A-share has no intraday short selling for most investors, so momentum overshoots are common
- T+1 settlement creates forced holding, amplifying intraday momentum
- Daily limit-up/down creates distinct candlestick patterns
"""

import pandas as pd
import numpy as np
import psycopg2
from scipy import stats
import time
import warnings
warnings.filterwarnings('ignore')

DB_URI = 'postgresql://quantmind:quantmind@localhost:5432/quantmind_v2'

def main():
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ── 1. Load OHLC data ──
    print("Loading OHLC data from klines_daily...")
    df = pd.read_sql("""
        SELECT code, trade_date,
               open::float, high::float, low::float, close::float,
               adj_factor::float, volume
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(df):,}, codes: {df['code'].nunique()}")

    # ── 2. Compute daily body ratio ──
    print("Computing daily body ratio...")
    hl_range = df['high'] - df['low']
    body = (df['close'] - df['open']).abs()
    # Exclude days where high == low (zero range, typically suspended or limit-locked)
    valid = hl_range > 1e-6
    df['body_ratio'] = np.where(valid, body / hl_range, np.nan)

    # ── 3. Pivot and rolling mean ──
    print("Pivoting and computing 20d rolling mean...")
    br_wide = df.pivot(index='trade_date', columns='code', values='body_ratio')
    n_dates, n_codes = br_wide.shape
    print(f"  Matrix: {n_dates} dates x {n_codes} codes")

    kbar_body_20 = br_wide.rolling(window=20, min_periods=10).mean()
    print(f"  Non-NaN factor values: {kbar_body_20.count().sum():,}")

    # ── 4. Forward 5-day excess return ──
    print("Computing forward returns...")
    df['adj_close'] = df['close'] * df['adj_factor']
    close_wide = df.pivot(index='trade_date', columns='code', values='adj_close')
    close_wide = close_wide.reindex(br_wide.index)
    fwd_ret = close_wide.shift(-5) / close_wide - 1

    bench_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-07-01'
        ORDER BY trade_date
    """, conn)
    conn.close()

    bench_close = bench_df.set_index('trade_date')['close'].reindex(br_wide.index)
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # ── 5. Monthly IC ──
    print("Computing monthly IC...")
    dates = pd.Series(br_wide.index)
    dates_dt = pd.to_datetime(dates)
    month_ends = dates.groupby(dates_dt.dt.to_period('M')).last().values
    month_ends = [str(d) for d in month_ends]

    kbar_body_20.index = kbar_body_20.index.astype(str)
    excess_fwd.index = excess_fwd.index.astype(str)

    from datetime import date as dt_date
    ic_records = []
    for d in month_ends:
        d_date = pd.Timestamp(d).date()
        if d_date < dt_date(2021, 1, 1) or d_date > dt_date(2025, 12, 31):
            continue
        if d not in kbar_body_20.index or d not in excess_fwd.index:
            continue
        fac_cross = kbar_body_20.loc[d].dropna()
        fwd_cross = excess_fwd.loc[d].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        # Direction: -1 (negate factor)
        ic, pval = stats.spearmanr(-fac_cross[common].values, fwd_cross[common].values)
        ic_records.append({'date': d, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})

    ic_df = pd.DataFrame(ic_records)
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    # ── 6. Results ──
    print("\n" + "="*70)
    print("KBAR BODY RATIO 20 IC Analysis (direction: -kbar_body_ratio)")
    print("Formula: -mean(abs(close-open)/(high-low), 20d)")
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
    key_factors = ['volatility_20', 'high_low_range_20', 'turnover_mean_20', 'ln_market_cap', 'momentum_20', 'bp_ratio']
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
                if d_str not in kbar_body_20.index or d_str not in fv_wide.index:
                    continue
                fac_cross = kbar_body_20.loc[d_str].dropna()
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
