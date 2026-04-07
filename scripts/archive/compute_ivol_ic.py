"""
IVOL (Idiosyncratic Volatility) Factor IC Analysis
====================================================
CAPM residual std over 60-day rolling window.
Direction: -1 (low IVOL outperforms high IVOL)
"""

import time
import warnings

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

warnings.filterwarnings('ignore')
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header

DB_URI = 'postgresql://xin:quantmind@localhost:5432/quantmind_v2'

def main():
    print_config_header()
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # ── 1. Load stock data ──
    print("Loading stock data...")
    stock_df = pd.read_sql("""
        SELECT code, trade_date, pct_change::float/100 as ret
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Stock rows: {len(stock_df):,}, codes: {stock_df['code'].nunique()}")

    # ── 2. Load CSI300 benchmark ──
    print("Loading CSI300 index...")
    bench_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-07-01'
        ORDER BY trade_date
    """, conn)
    bench_df['mkt_ret'] = bench_df['close'].pct_change()
    bench_df = bench_df[['trade_date', 'mkt_ret']].dropna()
    print(f"  Benchmark days: {len(bench_df)}")

    # ── 3. Pivot to wide tables for vectorized rolling calc ──
    print("Pivoting to wide format...")
    ret_wide = stock_df.pivot(index='trade_date', columns='code', values='ret')
    ret_wide = ret_wide.reindex(bench_df['trade_date'].values)
    mkt = bench_df.set_index('trade_date')['mkt_ret']

    n_dates, n_codes = ret_wide.shape
    print(f"  Matrix: {n_dates} dates x {n_codes} codes")

    # ── 4. Vectorized IVOL: rolling 60-day beta then residual std ──
    print("Computing IVOL (vectorized rolling)...")
    t1 = time.time()

    window = 60
    min_obs = 30

    # Convert to numpy for speed
    R = ret_wide.values  # (T, N)
    M = mkt.values.reshape(-1, 1)  # (T, 1)

    # Rolling cov(stock, mkt) and var(mkt)
    # Using cumsum trick for rolling stats
    ivol_matrix = np.full_like(R, np.nan)

    # Process in chunks of dates to manage memory
    for i in range(window - 1, n_dates):
        start = i - window + 1
        r_win = R[start:i+1, :]       # (60, N)
        m_win = M[start:i+1, 0]       # (60,)

        # Count valid obs per stock
        valid = ~np.isnan(r_win) & ~np.isnan(m_win.reshape(-1, 1))
        n_valid = valid.sum(axis=0)    # (N,)

        # Replace NaN with 0 for computation, then mask
        r_clean = np.where(valid, r_win, 0.0)
        m_clean = np.where(valid, m_win.reshape(-1, 1), 0.0)

        # Mean
        r_mean = r_clean.sum(axis=0) / np.maximum(n_valid, 1)  # (N,)
        m_sum = m_clean.sum(axis=0)
        m_mean = m_sum / np.maximum(n_valid, 1)                # (N,)

        # Cov and var
        r_dm = r_clean - r_mean[np.newaxis, :]  # (60, N)
        m_dm = m_clean - m_mean[np.newaxis, :]  # (60, N)
        r_dm = np.where(valid, r_dm, 0.0)
        m_dm = np.where(valid, m_dm, 0.0)

        cov_rm = (r_dm * m_dm).sum(axis=0) / np.maximum(n_valid - 1, 1)
        var_m = (m_dm * m_dm).sum(axis=0) / np.maximum(n_valid - 1, 1)

        # Beta
        beta = np.where(var_m > 1e-12, cov_rm / var_m, 0.0)  # (N,)

        # Residuals: r - beta * m
        resid = r_clean - beta[np.newaxis, :] * m_clean
        resid = np.where(valid, resid, np.nan)

        # Std of residuals
        resid_std = np.nanstd(resid, axis=0, ddof=1)

        # Mask insufficient obs
        resid_std[n_valid < min_obs] = np.nan
        ivol_matrix[i, :] = resid_std

    ivol_df = pd.DataFrame(ivol_matrix, index=ret_wide.index, columns=ret_wide.columns)
    print(f"  IVOL computed in {time.time()-t1:.1f}s")

    # ── 5. Forward 5-day return (excess over CSI300) ──
    print("Computing forward returns...")
    # Use close prices for forward return
    close_df = pd.read_sql("""
        SELECT code, trade_date, close::float * adj_factor::float as adj_close
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    conn.close()

    close_wide = close_df.pivot(index='trade_date', columns='code', values='adj_close')
    close_wide = close_wide.reindex(ret_wide.index)

    # 5-day forward return
    fwd_ret = close_wide.shift(-5) / close_wide - 1

    # CSI300 5-day forward return
    bench_df.set_index('trade_date').reindex(ret_wide.index)
    # Recompute from index close
    bench_close_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-07-01'
        ORDER BY trade_date
    """, psycopg2.connect(DB_URI))
    bench_close_s = bench_close_df.set_index('trade_date')['close'].reindex(ret_wide.index)
    bench_fwd = bench_close_s.shift(-5) / bench_close_s - 1

    # Excess forward return
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # ── 6. Monthly IC calculation ──
    print("Computing monthly IC...")
    # Get month-end dates
    dates = pd.Series(ret_wide.index)
    dates_dt = pd.to_datetime(dates)
    month_ends = dates.groupby(dates_dt.dt.to_period('M')).last().values
    # Filter: need IVOL data (after 2021-01 roughly)
    from datetime import date as dt_date
    d_start = dt_date(2021, 1, 1)
    d_end = dt_date(2025, 12, 31)
    month_ends_clean = []
    for d in month_ends:
        if isinstance(d, str):
            d = pd.Timestamp(d).date()
        elif isinstance(d, pd.Timestamp):
            d = d.date()
        if d >= d_start and d <= d_end:
            month_ends_clean.append(d)
    month_ends = month_ends_clean

    # Normalize all indices to string for consistent lookup
    ivol_df.index = ivol_df.index.astype(str)
    excess_fwd.index = excess_fwd.index.astype(str)
    month_ends = [str(d) for d in month_ends]

    ic_records = []
    for d in month_ends:
        if d not in ivol_df.index or d not in excess_fwd.index:
            continue
        ivol_cross = ivol_df.loc[d].dropna()
        fwd_cross = excess_fwd.loc[d].dropna()
        common = ivol_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        # Direction: -1 (low IVOL = high return), so negate IVOL
        ic, pval = stats.spearmanr(-ivol_cross[common].values, fwd_cross[common].values)
        ic_records.append({
            'date': d,
            'ic': ic,
            'pval': pval,
            'n_stocks': len(common)
        })

    ic_df = pd.DataFrame(ic_records)
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    # ── 7. Results ──
    print("\n" + "="*70)
    print("IVOL Factor IC Analysis (direction: -IVOL, low vol outperforms)")
    print("="*70)

    # Overall
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
    print("\n── Annual Breakdown ──")
    print(f"  {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t-stat':>8} {'IC>0%':>6} {'N':>4}")
    print(f"  {'-'*50}")
    for year, grp in ic_df.groupby('year'):
        ym = grp['ic'].mean()
        ys = grp['ic'].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp['ic'] > 0).mean() * 100
        print(f"  {year:<6} {ym:>8.4f} {ys:>8.4f} {yir:>8.4f} {yt:>8.2f} {yp:>5.1f}% {len(grp):>4}")

    # ── 8. Correlation with existing 5 factors ──
    print("\n── Correlation with Existing Factors (monthly cross-section rank corr) ──")
    conn2 = psycopg2.connect(DB_URI)

    # Pick 5 key factors and 3 sample dates for speed
    key_factors = ['volatility_20', 'ln_market_cap', 'momentum_20', 'turnover_mean_20', 'bp_ratio']
    sample_dates_corr = [month_ends[len(month_ends)//4], month_ends[len(month_ends)//2], month_ends[3*len(month_ends)//4]]
    sample_dates_str = "','".join(str(d) for d in sample_dates_corr)
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
            for d in sample_dates_corr:
                d_str = str(d)
                if d_str not in ivol_df.index or d_str not in fv_wide.index:
                    continue
                ivol_cross = ivol_df.loc[d_str].dropna()
                fv_cross = fv_wide.loc[d_str].dropna()
                common = ivol_cross.index.intersection(fv_cross.index)
                if len(common) < 100:
                    continue
                c, _ = stats.spearmanr(ivol_cross[common].values, fv_cross[common].values)
                corrs.append(c)
            if corrs:
                corr_results[fname] = np.mean(corrs)

        if corr_results:
            print(f"\n  {'Factor':<25} {'Rank Corr':>10}")
            print(f"  {'-'*37}")
            for fname, corr in sorted(corr_results.items(), key=lambda x: abs(x[1]), reverse=True):
                print(f"  {fname:<25} {corr:>10.4f}")
        else:
            print("  No overlapping data for correlation.")
    else:
        print("  No existing factors in DB or no overlap.")

    # ── 9. Monthly IC time series ──
    print("\n── Monthly IC Time Series ──")
    print(f"  {'Month':<10} {'IC':>8} {'N_stocks':>8}")
    print(f"  {'-'*28}")
    for _, row in ic_df.iterrows():
        marker = ' *' if abs(row['ic']) > 0.05 else ''
        print(f"  {row['date'].strftime('%Y-%m'):<10} {row['ic']:>8.4f} {int(row['n_stocks']):>8}{marker}")

    # ── Summary verdict ──
    print(f"\n{'='*70}")
    print("VERDICT:")
    if abs(t_stat) > 1.96 and abs(ic_mean) > 0.02:
        print(f"  IVOL is SIGNIFICANT (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print("  Recommend adding to candidate pool.")
    elif abs(t_stat) > 1.64:
        print(f"  IVOL is MARGINALLY significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print("  Worth monitoring, may add with lower weight.")
    else:
        print(f"  IVOL is NOT significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print("  Not recommended for current factor pool.")
    print(f"{'='*70}")

    print(f"\nTotal time: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
