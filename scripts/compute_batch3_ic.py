"""
Batch 3 Factor IC Analysis (5 factors)
========================================
1. large_cap_low_vol: -volatility_20 * ln_market_cap (interaction)
2. turnover_volatility_ratio: turnover_mean_20 / volatility_20
3. price_level_factor: ln(close_price)
4. momentum_60_120: -(close[t-5]/close[t-125] - 1) (120d reversal, skip recent 5d)
5. volume_momentum_divergence: rank(price_mom_20) - rank(vol_mom_20)

All share the same data load + forward return computation.
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

# ── IC computation helper ──
def compute_monthly_ic(factor_wide, excess_fwd, month_ends, direction=1, date_range=(dt_date(2021, 1, 1), dt_date(2025, 12, 31))):
    """Compute monthly Spearman IC between factor and forward excess return.
    direction: +1 means high factor = high return, -1 means negate factor.
    """
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


def print_ic_report(name, formula, ic_df):
    """Print standardized IC report for a factor."""
    if len(ic_df) == 0:
        print(f"\n{'='*70}")
        print(f"  {name}: NO DATA (all months filtered)")
        print(f"{'='*70}")
        return

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

    # ════════════════════════════════════════════════════════════════
    # SHARED DATA LOADING
    # ════════════════════════════════════════════════════════════════
    conn = psycopg2.connect(DB_URI)

    # 1. klines_daily: adj_close, close, volume, pct_change
    print("[DATA] Loading klines_daily...")
    klines = pd.read_sql("""
        SELECT code, trade_date,
               close::float as close_raw,
               close::float * adj_factor::float as adj_close,
               volume::float as volume,
               pct_change::float / 100 as ret
        FROM klines_daily
        WHERE trade_date >= '2020-01-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn)
    print(f"  Rows: {len(klines):,}, codes: {klines['code'].nunique()}")

    # 2. daily_basic: total_mv, turnover_rate
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

    # 4. Existing factor_values for correlation check
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
    close_raw_wide = klines.pivot(index='trade_date', columns='code', values='close_raw')
    volume_wide = klines.pivot(index='trade_date', columns='code', values='volume')
    ret_wide = klines.pivot(index='trade_date', columns='code', values='ret')

    total_mv_wide = basic.pivot(index='trade_date', columns='code', values='total_mv')
    turnover_wide = basic.pivot(index='trade_date', columns='code', values='turnover_rate')

    # Align all to common date index
    common_dates = adj_close_wide.index.intersection(total_mv_wide.index)
    common_dates = common_dates.sort_values()

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
    # FACTOR 1: large_cap_low_vol (interaction term)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 1: large_cap_low_vol")
    print("#"*70)

    # ln_market_cap (total_mv is in 万元)
    ln_mv = np.log(total_mv_wide.reindex(common_dates).replace(0, np.nan))

    # volatility_20: rolling 20-day std of daily returns
    vol_20 = ret_wide.reindex(common_dates).rolling(window=20, min_periods=10).std()

    # Interaction: -vol_20 * ln_mv
    # High market cap + low volatility => high factor value
    large_low_vol = (-vol_20) * ln_mv

    # Also test the components separately for comparison
    # Test direction: +1 (high interaction = good)
    ic1 = compute_monthly_ic(large_low_vol, excess_fwd, month_ends, direction=1)
    r1 = print_ic_report(
        "LARGE_CAP_LOW_VOL (interaction)",
        "-volatility_20 * ln(total_mv), direction=+1",
        ic1
    )
    if r1:
        results.append(r1)

    # Compare: just -vol_20
    ic1b = compute_monthly_ic(-vol_20, excess_fwd, month_ends, direction=1)
    r1b = print_ic_report(
        "  [comparison] -VOLATILITY_20 alone",
        "-volatility_20, direction=+1",
        ic1b
    )
    if r1b:
        results.append(r1b)

    # Compare: just ln_mv
    ic1c = compute_monthly_ic(ln_mv, excess_fwd, month_ends, direction=1)
    r1c = print_ic_report(
        "  [comparison] LN_MARKET_CAP alone",
        "ln(total_mv), direction=+1",
        ic1c
    )
    if r1c:
        results.append(r1c)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 2: turnover_volatility_ratio
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 2: turnover_volatility_ratio")
    print("#"*70)

    turn_20 = turnover_wide.reindex(common_dates).rolling(window=20, min_periods=10).mean()
    vol_20_aligned = vol_20.reindex(common_dates)

    # Ratio: turnover / volatility (both 20-day)
    turn_vol_ratio = turn_20 / vol_20_aligned
    turn_vol_ratio = turn_vol_ratio.replace([np.inf, -np.inf], np.nan)
    turn_vol_ratio = turn_vol_ratio.clip(
        turn_vol_ratio.quantile(0.01, axis=1).values.reshape(-1, 1),
        turn_vol_ratio.quantile(0.99, axis=1).values.reshape(-1, 1)
    )

    # Test both directions
    ic2_pos = compute_monthly_ic(turn_vol_ratio, excess_fwd, month_ends, direction=1)
    ic2_neg = compute_monthly_ic(turn_vol_ratio, excess_fwd, month_ends, direction=-1)

    # Pick better direction
    mean_pos = ic2_pos['ic'].mean() if len(ic2_pos) > 0 else 0
    mean_neg = ic2_neg['ic'].mean() if len(ic2_neg) > 0 else 0
    if abs(mean_pos) >= abs(mean_neg):
        ic2 = ic2_pos
        dir2 = "+1"
    else:
        ic2 = ic2_neg
        dir2 = "-1"

    r2 = print_ic_report(
        "TURNOVER_VOLATILITY_RATIO",
        f"turnover_mean_20 / volatility_20, direction={dir2}",
        ic2
    )
    if r2:
        results.append(r2)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 3: price_level_factor
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 3: price_level_factor")
    print("#"*70)

    ln_price = np.log(close_raw_wide.reindex(common_dates).replace(0, np.nan))

    # Test both directions
    ic3_pos = compute_monthly_ic(ln_price, excess_fwd, month_ends, direction=1)
    ic3_neg = compute_monthly_ic(ln_price, excess_fwd, month_ends, direction=-1)

    mean3_pos = ic3_pos['ic'].mean() if len(ic3_pos) > 0 else 0
    mean3_neg = ic3_neg['ic'].mean() if len(ic3_neg) > 0 else 0
    if abs(mean3_pos) >= abs(mean3_neg):
        ic3 = ic3_pos
        dir3 = "+1"
    else:
        ic3 = ic3_neg
        dir3 = "-1"

    r3 = print_ic_report(
        "PRICE_LEVEL_FACTOR",
        f"ln(close_price), direction={dir3}",
        ic3
    )
    if r3:
        results.append(r3)

    # Correlation with ln_market_cap
    print("\n  [Corr check] price_level vs ln_market_cap:")
    sample_months = [month_ends[len(month_ends)//4], month_ends[len(month_ends)//2], month_ends[3*len(month_ends)//4]]
    ln_price_str = ln_price.copy()
    ln_price_str.index = ln_price_str.index.astype(str)
    ln_mv_str = ln_mv.copy()
    ln_mv_str.index = ln_mv_str.index.astype(str)
    corrs_pm = []
    for d in sample_months:
        d_str = str(d)
        if d_str in ln_price_str.index and d_str in ln_mv_str.index:
            p = ln_price_str.loc[d_str].dropna()
            m = ln_mv_str.loc[d_str].dropna()
            common = p.index.intersection(m.index)
            if len(common) > 100:
                c, _ = stats.spearmanr(p[common].values, m[common].values)
                corrs_pm.append(c)
    if corrs_pm:
        print(f"    Avg rank corr(ln_price, ln_mv): {np.mean(corrs_pm):.4f}")
    else:
        print(f"    No overlap for corr check.")

    # ════════════════════════════════════════════════════════════════
    # FACTOR 4: momentum_60_120 (120d reversal, skip recent 5d)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 4: momentum_60_120")
    print("#"*70)

    ac_aligned = adj_close_wide.reindex(common_dates)

    # 120d reversal: -(close[t-5] / close[t-125] - 1)
    # Skip recent 5 days to avoid short-term reversal contamination
    mom_120 = ac_aligned.shift(5) / ac_aligned.shift(125) - 1
    reversal_120 = -mom_120  # negate for reversal

    # Also test 60d reversal
    mom_60 = ac_aligned.shift(5) / ac_aligned.shift(65) - 1
    reversal_60 = -mom_60

    # Test 120d reversal (direction already negated)
    ic4_120 = compute_monthly_ic(reversal_120, excess_fwd, month_ends, direction=1)
    r4_120 = print_ic_report(
        "REVERSAL_120 (120d, skip 5d)",
        "-(adj_close[t-5] / adj_close[t-125] - 1), direction=+1",
        ic4_120
    )
    if r4_120:
        results.append(r4_120)

    # Test 60d reversal
    ic4_60 = compute_monthly_ic(reversal_60, excess_fwd, month_ends, direction=1)
    r4_60 = print_ic_report(
        "  [comparison] REVERSAL_60 (60d, skip 5d)",
        "-(adj_close[t-5] / adj_close[t-65] - 1), direction=+1",
        ic4_60
    )
    if r4_60:
        results.append(r4_60)

    # Also test raw momentum (not reversal) to see direction
    ic4_mom = compute_monthly_ic(mom_120, excess_fwd, month_ends, direction=1)
    r4_mom = print_ic_report(
        "  [comparison] MOMENTUM_120 (raw, not reversed)",
        "(adj_close[t-5] / adj_close[t-125] - 1), direction=+1",
        ic4_mom
    )
    if r4_mom:
        results.append(r4_mom)

    # ════════════════════════════════════════════════════════════════
    # FACTOR 5: volume_momentum_divergence
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# FACTOR 5: volume_momentum_divergence")
    print("#"*70)

    # Price momentum 20d
    price_mom_20 = ac_aligned / ac_aligned.shift(20) - 1

    # Volume momentum: vol_mean_5 / vol_mean_20 - 1
    vol_aligned = volume_wide.reindex(common_dates)
    vol_mean_5 = vol_aligned.rolling(window=5, min_periods=3).mean()
    vol_mean_20 = vol_aligned.rolling(window=20, min_periods=10).mean()
    vol_mom_20 = vol_mean_5 / vol_mean_20 - 1
    vol_mom_20 = vol_mom_20.replace([np.inf, -np.inf], np.nan)

    # Cross-sectional rank for each day, then difference
    # rank(price_mom) - rank(vol_mom) => positive = price up but volume down
    price_rank = price_mom_20.rank(axis=1, pct=True)
    vol_rank = vol_mom_20.rank(axis=1, pct=True)
    divergence = price_rank - vol_rank

    # Direction: -1 (high divergence = price up vol down = unsustainable = will drop)
    ic5 = compute_monthly_ic(divergence, excess_fwd, month_ends, direction=-1)
    r5 = print_ic_report(
        "VOLUME_MOMENTUM_DIVERGENCE",
        "-[rank(price_mom_20) - rank(vol_mom_20)], direction=-1",
        ic5
    )
    if r5:
        results.append(r5)

    # Also test +1 direction
    ic5_pos = compute_monthly_ic(divergence, excess_fwd, month_ends, direction=1)
    r5_pos = print_ic_report(
        "  [comparison] VOL_MOM_DIVERGENCE direction=+1",
        "[rank(price_mom_20) - rank(vol_mom_20)], direction=+1",
        ic5_pos
    )
    if r5_pos:
        results.append(r5_pos)

    # ════════════════════════════════════════════════════════════════
    # CORRELATION MATRIX (all 5 new factors vs existing)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#"*70)
    print("# CROSS-FACTOR CORRELATION CHECK")
    print("#"*70)

    # Build new factor dict
    new_factors = {
        'large_cap_low_vol': large_low_vol,
        'turn_vol_ratio': turn_vol_ratio,
        'ln_price': ln_price,
        'reversal_120': reversal_120,
        'vol_mom_diverge': divergence,
    }

    # Normalize index to str
    for k in new_factors:
        new_factors[k].index = new_factors[k].index.astype(str)

    # Sample dates for correlation
    sample_dates_corr = [month_ends[i] for i in range(0, len(month_ends), 6)][:10]

    # 1. New factors pairwise
    print("\n-- New Factors Pairwise Correlation --")
    new_names = list(new_factors.keys())
    print(f"  {'':>22}", end='')
    for n in new_names:
        print(f" {n[:12]:>12}", end='')
    print()

    for i, n1 in enumerate(new_names):
        print(f"  {n1:>22}", end='')
        for j, n2 in enumerate(new_names):
            if j <= i:
                if i == j:
                    print(f" {'1.000':>12}", end='')
                else:
                    print(f" {'':>12}", end='')
                continue
            corrs = []
            for d in sample_dates_corr:
                d_str = str(d)
                if d_str in new_factors[n1].index and d_str in new_factors[n2].index:
                    f1 = new_factors[n1].loc[d_str].dropna()
                    f2 = new_factors[n2].loc[d_str].dropna()
                    common = f1.index.intersection(f2.index)
                    if len(common) > 100:
                        c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                        corrs.append(c)
            avg_c = np.mean(corrs) if corrs else np.nan
            flag = '!' if abs(avg_c) > 0.5 else ''
            print(f" {avg_c:>11.4f}{flag}", end='')
        print()

    # 2. New factors vs existing
    if len(existing_factors) > 0:
        print("\n-- New Factors vs Existing Factors --")
        existing_pivots = {}
        for fname, fgrp in existing_factors.groupby('factor_name'):
            fp = fgrp.pivot(index='trade_date', columns='code', values='value')
            fp.index = fp.index.astype(str)
            existing_pivots[fname] = fp

        ex_names = sorted(existing_pivots.keys())
        print(f"  {'New \\ Existing':>22}", end='')
        for en in ex_names:
            print(f" {en[:12]:>12}", end='')
        print()

        for nn in new_names:
            print(f"  {nn:>22}", end='')
            for en in ex_names:
                corrs = []
                for d in sample_dates_corr:
                    d_str = str(d)
                    if d_str in new_factors[nn].index and d_str in existing_pivots[en].index:
                        f1 = new_factors[nn].loc[d_str].dropna()
                        f2 = existing_pivots[en].loc[d_str].dropna()
                        common = f1.index.intersection(f2.index)
                        if len(common) > 100:
                            c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                            corrs.append(c)
                avg_c = np.mean(corrs) if corrs else np.nan
                flag = '!' if abs(avg_c) > 0.5 else ''
                print(f" {avg_c:>11.4f}{flag}", end='')
            print()

    # ════════════════════════════════════════════════════════════════
    # SUMMARY TABLE
    # ════════════════════════════════════════════════════════════════
    print("\n" + "="*80)
    print("BATCH 3 SUMMARY")
    print("="*80)
    print(f"  {'Factor':<40} {'IC_Mean':>8} {'t-stat':>8} {'IC_IR':>8} {'IC>0%':>6} {'Verdict':>10}")
    print(f"  {'-'*82}")

    for r in results:
        verdict = "PASS" if abs(r['t_stat']) > 1.96 and abs(r['ic_mean']) > 0.02 else \
                  "MARGINAL" if abs(r['t_stat']) > 1.64 and abs(r['ic_mean']) > 0.015 else "FAIL"
        print(f"  {r['name']:<40} {r['ic_mean']:>8.4f} {r['t_stat']:>8.2f} {r['ic_ir']:>8.4f} {r['pct_pos']:>5.1f}% {verdict:>10}")

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
