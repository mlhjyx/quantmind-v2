#!/usr/bin/env python3
"""Batch 6 Factor IC Analysis — 5 new-dimension candidates
==========================================================
1. industry_momentum_spread  — market-level timing signal (std of 31 SW industry 20d momentum)
2. intraday_return_ratio     — (close-open)/open 20d avg / (open-pre_close)/pre_close 20d avg
3. volume_concentration_20   — max(volume, 20d) / sum(volume, 20d)
4. close_to_high_ratio_20    — mean(close/high, 20d)
5. net_mf_reversal           — -rank(net_mf_amount 5d rolling sum)

Factor 1 is market-level: IC is time-series (does spread predict next-month market alpha dispersion?).
Factors 2-5 are stock-level: standard cross-sectional Spearman IC.

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

DB_URI = 'postgresql://quantmind:quantmind@localhost:5432/quantmind_v2'


# ══════════════════════════════════════════════════════════════════
# IC HELPERS (reused from batch 3/4)
# ══════════════════════════════════════════════════════════════════

def compute_monthly_ic(factor_wide: pd.DataFrame, excess_fwd: pd.DataFrame,
                       month_ends: list, direction: int = 1,
                       date_range=(dt_date(2021, 1, 1), dt_date(2025, 12, 31))):
    """Cross-sectional Spearman IC between factor and forward excess return, monthly."""
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


def main():
    t0 = time.time()

    # ══════════════════════════════════════════════════════════════
    # SHARED DATA LOADING
    # ══════════════════════════════════════════════════════════════
    conn = psycopg2.connect(DB_URI)

    # 1. klines_daily
    print("[DATA] Loading klines_daily...")
    klines = pd.read_sql("""
        SELECT code, trade_date,
               open::float as open_price,
               high::float as high_price,
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

    # 2. CSI300 benchmark
    print("[DATA] Loading CSI300 index...")
    bench = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2020-01-01'
        ORDER BY trade_date
    """, conn)

    # 3. SW industry indices (31 industries)
    print("[DATA] Loading SW industry indices...")
    sw_idx = pd.read_sql("""
        SELECT index_code, trade_date, close::float as close_price
        FROM index_daily
        WHERE index_code LIKE '%%.SI' AND trade_date >= '2020-01-01'
        ORDER BY trade_date, index_code
    """, conn)
    print(f"  Rows: {len(sw_idx):,}, industries: {sw_idx['index_code'].nunique()}")

    # 4. moneyflow_daily (net_mf_amount for factor 5)
    print("[DATA] Loading moneyflow net_mf_amount...")
    mf = pd.read_sql("""
        SELECT code, trade_date, net_mf_amount::float as net_mf_amount
        FROM moneyflow_daily
        WHERE trade_date >= '2020-06-01'
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(mf):,}, codes: {mf['code'].nunique()}")

    # 5. Existing factors for correlation check
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
    high_wide = klines.pivot(index='trade_date', columns='code', values='high_price')
    close_raw_wide = klines.pivot(index='trade_date', columns='code', values='close_raw')
    pre_close_wide = klines.pivot(index='trade_date', columns='code', values='pre_close')
    volume_wide = klines.pivot(index='trade_date', columns='code', values='volume')

    # SW industry: pivot to wide (index_code as columns, close as values)
    sw_wide = sw_idx.pivot(index='trade_date', columns='index_code', values='close_price')

    # moneyflow pivot
    mf_wide = mf.pivot(index='trade_date', columns='code', values='net_mf_amount')

    # Common dates for stock factors
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

    print(f"[DATA] Data ready. {len(common_dates)} trading days, month-ends: {len(month_ends)}")
    print(f"[DATA] Total load time: {time.time()-t0:.1f}s\n")

    results = []

    # ══════════════════════════════════════════════════════════════
    # FACTOR 1: industry_momentum_spread (MARKET-LEVEL)
    # ══════════════════════════════════════════════════════════════
    print("#"*70)
    print("# FACTOR 1: industry_momentum_spread (MARKET-LEVEL timing signal)")
    print("#"*70)
    print("# std(20d_momentum across 31 SW industries)")
    print("# This is NOT a stock-level cross-sectional factor.")
    print("# IC is time-series: does high spread predict higher cross-sectional")
    print("# alpha dispersion (i.e., better stock-picking environment)?")
    print()

    # 20d momentum for each industry
    sw_mom_20 = sw_wide.pct_change(periods=20)
    # Cross-industry std of 20d momentum each day
    ind_spread = sw_mom_20.std(axis=1)
    ind_spread = ind_spread.dropna()

    # Alpha dispersion: cross-sectional std of 5-day forward excess returns
    # (Higher dispersion = better stock-picking environment)
    alpha_disp = excess_fwd.std(axis=1).dropna()

    # Ensure string index for alignment
    ind_spread.index = ind_spread.index.astype(str)
    alpha_disp.index = alpha_disp.index.astype(str)

    # Align dates
    common_ts = ind_spread.index.intersection(alpha_disp.index)
    print(f"  Industry spread dates: {len(ind_spread)}, Alpha disp dates: {len(alpha_disp)}, Common: {len(common_ts)}")

    # Monthly sampling for time-series IC
    spread_monthly = []
    for d in month_ends:
        if d in ind_spread.index and d in alpha_disp.index:
            spread_monthly.append({
                'date': d,
                'spread': ind_spread[d],
                'alpha_disp': alpha_disp[d]
            })

    ts_df = pd.DataFrame(spread_monthly)

    if len(ts_df) > 10:
        ts_df['date_dt'] = pd.to_datetime(ts_df['date'])
        ts_df['year'] = ts_df['date_dt'].dt.year

        # Time-series rank correlation
        ts_corr, ts_pval = stats.spearmanr(ts_df['spread'].values, ts_df['alpha_disp'].values)

        print(f"  Time-series Spearman correlation (spread vs alpha_dispersion):")
        print(f"    rho = {ts_corr:.4f}, p-value = {ts_pval:.4f}")
        print(f"    N months = {len(ts_df)}")
        print()

        # Also test: does high spread predict higher TOP-BOTTOM spread next month?
        # Quintile long-short return as proxy for "alpha opportunity"
        # We'll use a simpler metric: mean absolute excess return
        mean_abs_excess = excess_fwd.abs().mean(axis=1).dropna()
        mean_abs_excess.index = mean_abs_excess.index.astype(str)
        spread_vs_abs = []
        for d in month_ends:
            if d in ind_spread.index and d in mean_abs_excess.index:
                spread_vs_abs.append({
                    'date': d,
                    'spread': ind_spread[d],
                    'mean_abs_alpha': mean_abs_excess[d]
                })
        sva_df = pd.DataFrame(spread_vs_abs)

        if len(sva_df) > 10:
            corr2, pval2 = stats.spearmanr(sva_df['spread'], sva_df['mean_abs_alpha'])
            print(f"  Spread vs mean|alpha| (stock-picking opportunity):")
            print(f"    rho = {corr2:.4f}, p-value = {pval2:.4f}")

        # Annual breakdown
        sva_df['date_dt'] = pd.to_datetime(sva_df['date'])
        sva_df['year'] = sva_df['date_dt'].dt.year
        print(f"\n  -- Annual Breakdown --")
        print(f"  {'Year':<6} {'rho_disp':>10} {'rho_abs':>10} {'N':>4}")
        print(f"  {'-'*32}")
        for year, grp in ts_df.groupby('year'):
            if len(grp) > 3:
                yr_corr, _ = stats.spearmanr(grp['spread'], grp['alpha_disp'])
                # mean_abs for same year
                sva_yr = sva_df[sva_df['year'] == year]
                yr_corr2 = np.nan
                if len(sva_yr) > 3:
                    yr_corr2, _ = stats.spearmanr(sva_yr['spread'], sva_yr['mean_abs_alpha'])
                print(f"  {year:<6} {yr_corr:>10.4f} {yr_corr2:>10.4f} {len(grp):>4}")

        # Monthly detail
        print(f"\n  -- Monthly Values --")
        print(f"  {'Month':<10} {'Spread':>10} {'AlphaDisp':>10}")
        print(f"  {'-'*32}")
        for _, row in ts_df.iterrows():
            print(f"  {row['date']:<10} {row['spread']:>10.4f} {row['alpha_disp']:>10.4f}")

        # Verdict for market-level factor
        print(f"\n  VERDICT (market-level): ", end='')
        if abs(ts_corr) > 0.3 and ts_pval < 0.05:
            print(f"USEFUL as timing signal (rho={ts_corr:.3f}, p={ts_pval:.3f})")
        elif abs(ts_corr) > 0.15 and ts_pval < 0.1:
            print(f"MARGINAL timing signal (rho={ts_corr:.3f}, p={ts_pval:.3f})")
        else:
            print(f"WEAK/NO timing signal (rho={ts_corr:.3f}, p={ts_pval:.3f})")
    else:
        print("  NOT ENOUGH DATA for time-series analysis")

    # ══════════════════════════════════════════════════════════════
    # FACTOR 2: intraday_return_ratio
    # ══════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 2: intraday_return_ratio")
    print("# mean((close-open)/open, 20d) / mean((open-pre_close)/pre_close, 20d)")
    print("#"*70)

    op = open_wide.reindex(common_dates)
    cl = close_raw_wide.reindex(common_dates)
    pc = pre_close_wide.reindex(common_dates)

    # Intraday return: (close - open) / open
    intraday_ret = (cl - op) / op.replace(0, np.nan)
    # Overnight return: (open - pre_close) / pre_close
    overnight_ret = (op - pc) / pc.replace(0, np.nan)

    # 20d rolling means
    intraday_avg_20 = intraday_ret.rolling(window=20, min_periods=15).mean()
    overnight_avg_20 = overnight_ret.rolling(window=20, min_periods=15).mean()

    # Ratio: avoid division by zero
    # When overnight is near zero, ratio is unstable. Use signed ratio.
    eps = 1e-6
    sign_overnight = np.sign(overnight_avg_20).replace(0, 1)
    intraday_ratio = intraday_avg_20 / (overnight_avg_20.abs() + eps) * sign_overnight

    # The ratio can be extreme. Clip at [-10, 10]
    intraday_ratio = intraday_ratio.clip(-10, 10)
    intraday_ratio = intraday_ratio.replace([np.inf, -np.inf], np.nan)

    # Also test simpler version: just intraday_avg_20 - overnight_avg_20
    intraday_diff = intraday_avg_20 - overnight_avg_20

    # Test both versions, both directions
    print("\n  Testing ratio version...")
    ic2r_pos = compute_monthly_ic(intraday_ratio, excess_fwd, month_ends, direction=+1)
    ic2r_neg = compute_monthly_ic(intraday_ratio, excess_fwd, month_ends, direction=-1)

    print("  Testing difference version (intraday_avg - overnight_avg)...")
    ic2d_pos = compute_monthly_ic(intraday_diff, excess_fwd, month_ends, direction=+1)
    ic2d_neg = compute_monthly_ic(intraday_diff, excess_fwd, month_ends, direction=-1)

    # Pick best version
    candidates_2 = [
        ('ratio_+1', ic2r_pos, intraday_ratio),
        ('ratio_-1', ic2r_neg, intraday_ratio),
        ('diff_+1', ic2d_pos, intraday_diff),
        ('diff_-1', ic2d_neg, intraday_diff),
    ]
    best_2 = max(candidates_2, key=lambda x: abs(x[1]['ic'].mean()) if len(x[1]) > 0 else 0)
    best_2_label = best_2[0]
    best_2_ic = best_2[1]

    print(f"\n  Best version: {best_2_label} (IC mean = {best_2_ic['ic'].mean():.4f})")

    r2 = print_ic_report(
        "INTRADAY_RETURN_RATIO",
        f"version={best_2_label}, 20d window",
        best_2_ic
    )
    if r2:
        results.append(r2)

    # ══════════════════════════════════════════════════════════════
    # FACTOR 3: volume_concentration_20
    # ══════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 3: volume_concentration_20")
    print("# max(volume, 20d) / sum(volume, 20d)")
    print("#"*70)

    vol = volume_wide.reindex(common_dates)
    vol_max_20 = vol.rolling(window=20, min_periods=15).max()
    vol_sum_20 = vol.rolling(window=20, min_periods=15).sum()
    vol_concentration = vol_max_20 / vol_sum_20.replace(0, np.nan)
    vol_concentration = vol_concentration.replace([np.inf, -np.inf], np.nan)

    # Test both directions
    ic3_neg = compute_monthly_ic(vol_concentration, excess_fwd, month_ends, direction=-1)
    ic3_pos = compute_monthly_ic(vol_concentration, excess_fwd, month_ends, direction=+1)

    mean3_neg = ic3_neg['ic'].mean() if len(ic3_neg) > 0 else 0
    mean3_pos = ic3_pos['ic'].mean() if len(ic3_pos) > 0 else 0

    if abs(mean3_neg) >= abs(mean3_pos):
        ic3 = ic3_neg
        dir3_label = "-1 (concentrated volume => underperform)"
    else:
        ic3 = ic3_pos
        dir3_label = "+1 (concentrated volume => outperform)"

    r3 = print_ic_report(
        "VOLUME_CONCENTRATION_20",
        f"max(vol,20d)/sum(vol,20d), direction={dir3_label}",
        ic3
    )
    if r3:
        results.append(r3)

    # ══════════════════════════════════════════════════════════════
    # FACTOR 4: close_to_high_ratio_20
    # ══════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 4: close_to_high_ratio_20")
    print("# mean(close/high, 20d)")
    print("#"*70)

    hi = high_wide.reindex(common_dates)
    close_to_high = cl / hi.replace(0, np.nan)
    close_to_high_20 = close_to_high.rolling(window=20, min_periods=15).mean()

    # Test both directions
    ic4_pos = compute_monthly_ic(close_to_high_20, excess_fwd, month_ends, direction=+1)
    ic4_neg = compute_monthly_ic(close_to_high_20, excess_fwd, month_ends, direction=-1)

    mean4_pos = ic4_pos['ic'].mean() if len(ic4_pos) > 0 else 0
    mean4_neg = ic4_neg['ic'].mean() if len(ic4_neg) > 0 else 0

    if abs(mean4_pos) >= abs(mean4_neg):
        ic4 = ic4_pos
        dir4_label = "+1 (close near high => outperform, buy-side strength)"
    else:
        ic4 = ic4_neg
        dir4_label = "-1 (close near high => underperform, reversal)"

    r4 = print_ic_report(
        "CLOSE_TO_HIGH_RATIO_20",
        f"mean(close/high, 20d), direction={dir4_label}",
        ic4
    )
    if r4:
        results.append(r4)

    # ══════════════════════════════════════════════════════════════
    # FACTOR 5: net_mf_reversal
    # ══════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 5: net_mf_reversal")
    print("# -rank(sum(net_mf_amount, 5d))")
    print("# Short-term capital inflow reversal")
    print("#"*70)

    mf_w = mf_wide.reindex(common_dates)
    # 5-day rolling sum of net money flow
    mf_5d_sum = mf_w.rolling(window=5, min_periods=3).sum()
    # Negate: stocks with recent net outflow (low mf) should outperform
    # The "reversal" is: -rank(mf_5d_sum), but since IC computes rank correlation
    # we can just use -mf_5d_sum and let direction handle it
    net_mf_reversal = -mf_5d_sum

    # Test both directions
    ic5_pos = compute_monthly_ic(net_mf_reversal, excess_fwd, month_ends, direction=+1)
    ic5_neg = compute_monthly_ic(net_mf_reversal, excess_fwd, month_ends, direction=-1)

    mean5_pos = ic5_pos['ic'].mean() if len(ic5_pos) > 0 else 0
    mean5_neg = ic5_neg['ic'].mean() if len(ic5_neg) > 0 else 0

    if abs(mean5_pos) >= abs(mean5_neg):
        ic5 = ic5_pos
        dir5_label = "+1 (recent net outflow => outperform, capital flow reversal)"
    else:
        ic5 = ic5_neg
        dir5_label = "-1 (recent net inflow => outperform, momentum)"

    r5 = print_ic_report(
        "NET_MF_REVERSAL",
        f"-sum(net_mf_amount, 5d), direction={dir5_label}",
        ic5
    )
    if r5:
        results.append(r5)

    # ══════════════════════════════════════════════════════════════
    # CROSS-FACTOR CORRELATION CHECK
    # ══════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# CROSS-FACTOR CORRELATION CHECK")
    print("#"*70)

    new_factors = {
        'intraday_ratio': best_2[2],       # whichever version won
        'vol_conc_20': vol_concentration,
        'c2h_ratio_20': close_to_high_20,
        'net_mf_rev': net_mf_reversal,
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

    # ══════════════════════════════════════════════════════════════
    # SUMMARY TABLE
    # ══════════════════════════════════════════════════════════════
    print("\n" + "="*80)
    print("BATCH 6 SUMMARY")
    print("="*80)
    print(f"\n  Factor 1 (industry_momentum_spread) is market-level — see above for time-series analysis.")
    print()
    print(f"  {'Factor':<35} {'IC_Mean':>8} {'t-stat':>8} {'IC_IR':>8} {'IC>0%':>6} {'Verdict':>10}")
    print(f"  {'-'*77}")

    for r in results:
        verdict = ("PASS" if abs(r['t_stat']) > 1.96 and abs(r['ic_mean']) > 0.02 else
                   "MARGINAL" if abs(r['t_stat']) > 1.64 and abs(r['ic_mean']) > 0.015 else
                   "FAIL")
        print(f"  {r['name']:<35} {r['ic_mean']:>8.4f} {r['t_stat']:>8.2f} {r['ic_ir']:>8.4f} {r['pct_pos']:>5.1f}% {verdict:>10}")

    # Gate check
    print(f"\n  GATE CHECK (stock-level factors): IC > 1.5% AND t > 1.64")
    print(f"  {'-'*60}")
    for r in results:
        ic_pass = abs(r['ic_mean']) > 0.015
        t_pass = abs(r['t_stat']) > 1.64
        status = "PASS" if (ic_pass and t_pass) else "FAIL"
        print(f"  {r['name']:<35} IC={r['ic_mean']:+.4f}({'+' if ic_pass else '-'})  t={r['t_stat']:.2f}({'+' if t_pass else '-'})  => {status}")

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
