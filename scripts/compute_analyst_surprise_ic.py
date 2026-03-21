"""
Analyst Surprise Proxy Factor IC Analysis
===========================================
Formula: Cumulative excess return in [ann_date-2, ann_date+2] window (5-day CAR)
Direction: +1 (positive surprise drift = PEAD continues)

Economic rationale (Bernard & Thomas 1989, PEAD):
- Post-Earnings-Announcement Drift is one of the oldest known anomalies
- Market underreacts to earnings news at announcement
- Excess return around announcement proxies for "surprise" magnitude/direction
- Stocks with positive surprise continue to drift up for 60+ days
- Without analyst consensus data, we use price reaction as surprise proxy

A-share applicability: MODERATE-HIGH
- A-share has less analyst coverage -> more room for underreaction
- Quarterly reporting cycle creates clustered announcement dates
- PIT alignment critical: use actual_ann_date, NOT report_date
- Caveat: A-share has T+1, no short selling for retail -> asymmetric PEAD
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

    # ── 1. Load financial announcement dates ──
    print("Loading financial announcement dates...")
    ann_df = pd.read_sql("""
        SELECT code, report_date, actual_ann_date
        FROM financial_indicators
        WHERE actual_ann_date IS NOT NULL
          AND actual_ann_date >= '2020-01-01'
        ORDER BY code, actual_ann_date
    """, conn)
    print(f"  Announcements: {len(ann_df):,}, codes: {ann_df['code'].nunique()}")

    # ── 2. Load daily returns and benchmark ──
    print("Loading daily returns...")
    ret_df = pd.read_sql("""
        SELECT code, trade_date, pct_change::float/100 as ret
        FROM klines_daily
        WHERE trade_date >= '2019-12-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)

    bench_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2019-12-01'
        ORDER BY trade_date
    """, conn)
    bench_df['bench_ret'] = bench_df['close'].pct_change()
    bench_ret = bench_df.set_index('trade_date')['bench_ret']

    # Get sorted trading dates for date lookup
    trading_dates = sorted(ret_df['trade_date'].unique())
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}

    # Pivot returns
    ret_wide = ret_df.pivot(index='trade_date', columns='code', values='ret')
    ret_wide = ret_wide.reindex(trading_dates)

    # Excess return = stock return - benchmark return
    excess_ret_wide = ret_wide.sub(bench_ret, axis=0)

    print(f"  Daily returns matrix: {ret_wide.shape[0]} dates x {ret_wide.shape[1]} codes")

    # ── 3. Compute CAR[-2, +2] around each announcement ──
    print("Computing announcement CAR[-2, +2]...")
    t1 = time.time()

    car_records = []
    n_skip = 0
    for _, row in ann_df.iterrows():
        code = row['code']
        ann_date = row['actual_ann_date']

        if ann_date not in date_to_idx:
            # Find nearest trading date
            idx = np.searchsorted(trading_dates, ann_date)
            if idx >= len(trading_dates):
                n_skip += 1
                continue
            ann_date = trading_dates[idx]

        idx = date_to_idx[ann_date]
        # Window: [idx-2, idx+2]
        start_idx = max(0, idx - 2)
        end_idx = min(len(trading_dates) - 1, idx + 2)

        if end_idx - start_idx < 3:  # Need at least 3 days
            n_skip += 1
            continue

        window_dates = trading_dates[start_idx:end_idx+1]

        if code not in excess_ret_wide.columns:
            n_skip += 1
            continue

        car = excess_ret_wide.loc[window_dates, code].sum()
        if np.isnan(car):
            n_skip += 1
            continue

        car_records.append({
            'code': code,
            'ann_date': ann_date,
            'report_date': row['report_date'],
            'car': car
        })

    car_df = pd.DataFrame(car_records)
    print(f"  Valid CARs: {len(car_df):,}, skipped: {n_skip}")
    print(f"  Computed in {time.time()-t1:.1f}s")

    if len(car_df) < 100:
        print("  INSUFFICIENT DATA for IC analysis. Exiting.")
        conn.close()
        return

    # ── 4. Map CAR to forward-looking factor (PIT: use ann_date) ──
    # For each stock, the most recent CAR as of date D becomes the factor value
    # PIT: factor only available AFTER ann_date
    print("Building PIT factor panel...")

    # For each month-end, find the most recent CAR for each stock
    dates_all = sorted(ret_wide.index)
    dates_dt = pd.to_datetime(pd.Series(dates_all))
    month_ends = pd.Series(dates_all).groupby(dates_dt.dt.to_period('M')).last().values

    from datetime import date as dt_date
    month_ends_clean = [d for d in month_ends
                        if pd.Timestamp(d).date() >= dt_date(2021, 1, 1)
                        and pd.Timestamp(d).date() <= dt_date(2025, 12, 31)]

    # Sort car_df by ann_date for efficient lookup
    car_df = car_df.sort_values('ann_date')

    # Build forward returns for IC
    close_df = pd.read_sql("""
        SELECT code, trade_date, close::float * adj_factor::float as adj_close
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    conn.close()

    close_wide = close_df.pivot(index='trade_date', columns='code', values='adj_close')
    close_wide = close_wide.reindex(dates_all)
    fwd_ret = close_wide.shift(-5) / close_wide - 1

    bench_close = bench_df.set_index('trade_date')['close'].reindex(dates_all)
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)
    excess_fwd.index = excess_fwd.index.astype(str)

    # ── 5. Monthly IC ──
    print("Computing monthly IC...")
    ic_records = []
    for d in month_ends_clean:
        d_str = str(d)
        d_date = pd.Timestamp(d).date()

        # Get most recent CAR for each stock as of this date (PIT)
        recent_car = car_df[car_df['ann_date'] <= d].groupby('code')['car'].last()
        # Only use CARs from last 120 days (stale CARs lose predictive power)
        cutoff = d_date - pd.Timedelta(days=120)
        recent_dates = car_df[car_df['ann_date'] <= d].groupby('code')['ann_date'].last()
        fresh = recent_dates[recent_dates >= cutoff].index
        recent_car = recent_car.reindex(fresh).dropna()

        if d_str not in excess_fwd.index:
            continue
        fwd_cross = excess_fwd.loc[d_str].dropna()
        common = recent_car.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue

        # Direction: +1 (positive surprise -> positive drift, no negation needed)
        ic, pval = stats.spearmanr(recent_car[common].values, fwd_cross[common].values)
        ic_records.append({'date': d, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})

    if len(ic_records) == 0:
        print("  NO VALID IC observations. Factor may not be computable with current data.")
        return

    ic_df = pd.DataFrame(ic_records)
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    # ── 6. Results ──
    print("\n" + "="*70)
    print("ANALYST SURPRISE PROXY (PEAD) IC Analysis (direction: +CAR)")
    print("Formula: CAR[-2,+2] around earnings announcement date")
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
    key_factors = ['momentum_20', 'reversal_20', 'turnover_mean_20', 'volatility_20', 'ln_market_cap', 'bp_ratio']
    sample_dates = [str(month_ends_clean[len(month_ends_clean)//4]),
                    str(month_ends_clean[len(month_ends_clean)//2]),
                    str(month_ends_clean[3*len(month_ends_clean)//4])]
    sample_dates_str = "','".join(sample_dates)
    factor_str = "','".join(key_factors)

    fv_all = pd.read_sql(f"""
        SELECT code, trade_date, factor_name, zscore::float as value
        FROM factor_values
        WHERE factor_name IN ('{factor_str}')
          AND trade_date::text IN ('{sample_dates_str}')
    """, conn2)
    conn2.close()

    if len(fv_all) > 0:
        corr_results = {}
        for fname, fgrp in fv_all.groupby('factor_name'):
            fv_wide = fgrp.pivot(index='trade_date', columns='code', values='value')
            fv_wide.index = fv_wide.index.astype(str)
            corrs = []
            for d_str in sample_dates:
                d_date = pd.Timestamp(d_str).date()
                cutoff = d_date - pd.Timedelta(days=120)
                recent_car_d = car_df[car_df['ann_date'] <= d_date].groupby('code')['car'].last()
                recent_dates_d = car_df[car_df['ann_date'] <= d_date].groupby('code')['ann_date'].last()
                fresh_d = recent_dates_d[recent_dates_d >= cutoff].index
                recent_car_d = recent_car_d.reindex(fresh_d).dropna()

                if d_str not in fv_wide.index:
                    continue
                fv_cross = fv_wide.loc[d_str].dropna()
                common = recent_car_d.index.intersection(fv_cross.index)
                if len(common) < 100:
                    continue
                c, _ = stats.spearmanr(recent_car_d[common].values, fv_cross[common].values)
                corrs.append(c)
            if corrs:
                corr_results[fname] = np.mean(corrs)

        if corr_results:
            print(f"\n  {'Factor':<25} {'Rank Corr':>10}")
            print(f"  {'-'*37}")
            for fname, corr in sorted(corr_results.items(), key=lambda x: abs(x[1]), reverse=True):
                flag = ' *** HIGH' if abs(corr) > 0.7 else ' ** MODERATE' if abs(corr) > 0.5 else ''
                print(f"  {fname:<25} {corr:>10.4f}{flag}")

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
        print(f"  PEAD effect confirmed in A-share. Recommend for candidate pool.")
    elif abs(t_stat) > 1.64:
        print(f"  MARGINALLY significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  PEAD signal present but weak. May improve with longer CAR window.")
    else:
        print(f"  NOT significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  PEAD proxy via CAR not effective. May need analyst consensus data.")
    print(f"{'='*70}")
    print(f"\nTotal time: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
