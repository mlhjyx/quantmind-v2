"""
Net Profit YoY (PIT) Factor IC Analysis
=========================================
Formula: net_profit_yoy from financial_indicators, PIT-aligned via actual_ann_date
Direction: +1 (high profit growth -> positive future returns)

Economic rationale:
- Earnings growth is one of the most fundamental drivers of equity returns
- Companies with accelerating profit growth attract investor attention and buying pressure
- Complementary to revenue_yoy: revenue growth shows top-line momentum,
  net profit growth shows bottom-line execution (margin expansion, cost control)
- PIT alignment critical: only use data available as of actual_ann_date to avoid lookahead bias

A-share applicability: HIGH
- A-share earnings growth is a primary driver of institutional allocation
- Quarterly reporting creates natural factor refresh cycle
- Retail investors heavily chase earnings stories, creating momentum
- Caveat: extreme growth (>300%) often from low base, need winsorization
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

    # ── 1. Load financial data with PIT dates ──
    print("Loading net_profit_yoy from financial_indicators (PIT)...")
    fi = pd.read_sql("""
        SELECT code, report_date, actual_ann_date, net_profit_yoy::float
        FROM financial_indicators
        WHERE actual_ann_date IS NOT NULL
          AND net_profit_yoy IS NOT NULL
          AND actual_ann_date >= '2020-01-01'
        ORDER BY code, actual_ann_date
    """, conn)
    print(f"  Rows: {len(fi):,}, codes: {fi['code'].nunique()}")

    # Winsorize extreme growth values (common in A-share)
    # net_profit_yoy is in percentage (e.g., 50.0 means 50%)
    p1, p99 = fi['net_profit_yoy'].quantile([0.01, 0.99])
    fi['net_profit_yoy_w'] = fi['net_profit_yoy'].clip(p1, p99)
    print(f"  Winsorized range: [{p1:.1f}%, {p99:.1f}%]")

    # ── 2. Load price data for forward returns ──
    print("Loading price data...")
    close_df = pd.read_sql("""
        SELECT code, trade_date, close::float * adj_factor::float as adj_close
        FROM klines_daily
        WHERE trade_date >= '2020-07-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)

    trading_dates = sorted(close_df['trade_date'].unique())
    close_wide = close_df.pivot(index='trade_date', columns='code', values='adj_close')
    close_wide = close_wide.reindex(trading_dates)
    fwd_ret = close_wide.shift(-5) / close_wide - 1

    # Benchmark
    bench_df = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-07-01'
        ORDER BY trade_date
    """, conn)
    conn.close()

    bench_close = bench_df.set_index('trade_date')['close'].reindex(trading_dates)
    bench_fwd = bench_close.shift(-5) / bench_close - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)
    excess_fwd.index = excess_fwd.index.astype(str)

    # ── 3. Build PIT factor panel ──
    print("Building PIT factor panel...")
    # For each month-end, use the most recent net_profit_yoy available via actual_ann_date
    dates_dt = pd.to_datetime(pd.Series(trading_dates))
    month_ends = pd.Series(trading_dates).groupby(dates_dt.dt.to_period('M')).last().values

    from datetime import date as dt_date
    month_ends_clean = [d for d in month_ends
                        if pd.Timestamp(d).date() >= dt_date(2021, 1, 1)
                        and pd.Timestamp(d).date() <= dt_date(2025, 12, 31)]

    # ── 4. Monthly IC ──
    print("Computing monthly IC...")
    ic_records = []
    for d in month_ends_clean:
        d_str = str(d)
        d_date = pd.Timestamp(d).date()

        # PIT: only use announcements made on or before d_date
        avail = fi[fi['actual_ann_date'] <= d_date]
        # Get most recent announcement per stock
        latest = avail.groupby('code').tail(1).set_index('code')['net_profit_yoy_w']

        # Freshness filter: only use data from announcements within last 180 days
        latest_dates = avail.groupby('code')['actual_ann_date'].last()
        cutoff = d_date - pd.Timedelta(days=180)
        fresh_codes = latest_dates[latest_dates >= cutoff].index
        latest = latest.reindex(fresh_codes).dropna()

        if d_str not in excess_fwd.index:
            continue
        fwd_cross = excess_fwd.loc[d_str].dropna()
        common = latest.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue

        # Direction: +1 (high growth = good, no negation)
        ic, pval = stats.spearmanr(latest[common].values, fwd_cross[common].values)
        ic_records.append({'date': d, 'ic': ic, 'pval': pval, 'n_stocks': len(common)})

    if len(ic_records) == 0:
        print("  NO VALID IC observations. Check data coverage.")
        return

    ic_df = pd.DataFrame(ic_records)
    ic_df['date'] = pd.to_datetime(ic_df['date'])
    ic_df['year'] = ic_df['date'].dt.year

    # ── 5. Results ──
    print("\n" + "="*70)
    print("NET PROFIT YOY (PIT) IC Analysis (direction: +net_profit_yoy)")
    print("Formula: net_profit_yoy, PIT-aligned via actual_ann_date")
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

    # ── 6. Correlation with existing factors ──
    print(f"\n── Correlation with Existing Factors ──")
    conn2 = psycopg2.connect(DB_URI)
    key_factors = ['momentum_20', 'ep_ratio', 'bp_ratio', 'ln_market_cap', 'turnover_mean_20', 'volatility_20']
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
                avail = fi[fi['actual_ann_date'] <= d_date]
                latest = avail.groupby('code').tail(1).set_index('code')['net_profit_yoy_w']
                latest_dates = avail.groupby('code')['actual_ann_date'].last()
                cutoff = d_date - pd.Timedelta(days=180)
                fresh_codes = latest_dates[latest_dates >= cutoff].index
                latest = latest.reindex(fresh_codes).dropna()

                if d_str not in fv_wide.index:
                    continue
                fv_cross = fv_wide.loc[d_str].dropna()
                common = latest.index.intersection(fv_cross.index)
                if len(common) < 100:
                    continue
                c, _ = stats.spearmanr(latest[common].values, fv_cross[common].values)
                corrs.append(c)
            if corrs:
                corr_results[fname] = np.mean(corrs)

        if corr_results:
            print(f"\n  {'Factor':<25} {'Rank Corr':>10}")
            print(f"  {'-'*37}")
            for fname, corr in sorted(corr_results.items(), key=lambda x: abs(x[1]), reverse=True):
                flag = ' *** HIGH' if abs(corr) > 0.7 else ' ** MODERATE' if abs(corr) > 0.5 else ''
                print(f"  {fname:<25} {corr:>10.4f}{flag}")

    # ── 7. Monthly IC time series ──
    print(f"\n── Monthly IC Time Series ──")
    print(f"  {'Month':<10} {'IC':>8} {'N_stocks':>8}")
    print(f"  {'-'*28}")
    for _, row in ic_df.iterrows():
        marker = ' *' if abs(row['ic']) > 0.05 else ''
        print(f"  {row['date'].strftime('%Y-%m'):<10} {row['ic']:>8.4f} {int(row['n_stocks']):>8}{marker}")

    # ── 8. Compare with revenue_yoy if possible ──
    print(f"\n── Comparison note ──")
    print(f"  This factor (net_profit_yoy) complements revenue_yoy:")
    print(f"  - revenue_yoy = top-line growth momentum")
    print(f"  - net_profit_yoy = bottom-line execution (margins + cost control)")
    print(f"  - Low corr between them = good diversification value")

    # ── Verdict ──
    print(f"\n{'='*70}")
    print("VERDICT:")
    if abs(t_stat) > 1.96 and abs(ic_mean) > 0.02:
        print(f"  SIGNIFICANT (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Recommend adding to candidate pool.")
    elif abs(t_stat) > 1.64:
        print(f"  MARGINALLY significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Worth monitoring, may improve with sector neutralization.")
    else:
        print(f"  NOT significant (t={t_stat:.2f}, IC={ic_mean:.4f})")
        print(f"  Earnings growth may be too well-known / priced in.")
    print(f"{'='*70}")
    print(f"\nTotal time: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
