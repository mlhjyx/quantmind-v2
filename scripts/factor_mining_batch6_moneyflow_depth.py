"""
Batch 6: 资金流深度因子 — 5个新因子挖掘 + IC验证
=================================================
基于 moneyflow_daily (614万行) + klines_daily 计算
金额单位: moneyflow_daily = 万元, klines_daily.amount = 千元
"""

import pandas as pd
import numpy as np
from scipy import stats
import psycopg2
from sqlalchemy import create_engine
import warnings
warnings.filterwarnings('ignore')

DB_URL = 'postgresql://quantmind:quantmind@localhost:5432/quantmind_v2'
engine = create_engine(DB_URL)

# ============================================================
# 1. 加载数据
# ============================================================
print("=" * 70)
print("Loading data...")

# moneyflow_daily — 金额单位: 万元
mf = pd.read_sql("""
    SELECT code, trade_date,
           buy_lg_amount, sell_lg_amount,
           buy_elg_amount, sell_elg_amount,
           buy_sm_amount, sell_sm_amount,
           buy_md_amount, sell_md_amount,
           net_mf_amount
    FROM moneyflow_daily
    WHERE trade_date >= '2021-01-04'
    ORDER BY code, trade_date
""", engine, parse_dates=['trade_date'])
print(f"  moneyflow_daily: {len(mf):,} rows, {mf['code'].nunique()} stocks")

# klines_daily — amount单位: 千元, volume: 手
kl = pd.read_sql("""
    SELECT code, trade_date, open, close, pre_close, high, low,
           volume, amount, adj_factor, pct_change
    FROM klines_daily
    WHERE trade_date >= '2021-01-04'
      AND is_suspended = false
    ORDER BY code, trade_date
""", engine, parse_dates=['trade_date'])
print(f"  klines_daily: {len(kl):,} rows, {kl['code'].nunique()} stocks")

# CSI300 benchmark
bench = pd.read_sql("""
    SELECT trade_date, close as bench_close, pct_change as bench_pct
    FROM index_daily
    WHERE index_code = '000300.SH' AND trade_date >= '2021-01-04'
    ORDER BY trade_date
""", engine, parse_dates=['trade_date'])
print(f"  CSI300 benchmark: {len(bench)} rows")

# ============================================================
# 2. 预处理
# ============================================================
print("\nPreprocessing...")

# Merge moneyflow with klines
df = mf.merge(kl, on=['code', 'trade_date'], how='inner')
print(f"  Merged: {len(df):,} rows")

# Derived fields on moneyflow
df['net_lg_amount'] = df['buy_lg_amount'] - df['sell_lg_amount']  # 大单净流入(万元)
df['net_elg_amount'] = df['buy_elg_amount'] - df['sell_elg_amount']  # 特大单净流入
df['net_sm_amount'] = df['buy_sm_amount'] - df['sell_sm_amount']  # 小单净流入
df['net_md_amount'] = df['buy_md_amount'] - df['sell_md_amount']  # 中单净流入

# 大单 = 大单 + 特大单 (机构资金)
df['net_big_amount'] = df['net_lg_amount'] + df['net_elg_amount']
# 小单 = 小单 + 中单 (散户资金)
df['net_small_amount'] = df['net_sm_amount'] + df['net_md_amount']

# 总成交额(万元), moneyflow各项买卖之和
df['total_mf_amount'] = (df['buy_sm_amount'] + df['sell_sm_amount'] +
                          df['buy_md_amount'] + df['sell_md_amount'] +
                          df['buy_lg_amount'] + df['sell_lg_amount'] +
                          df['buy_elg_amount'] + df['sell_elg_amount'])

# 特大单占比
df['elg_ratio'] = (df['buy_elg_amount'] + df['sell_elg_amount']) / df['total_mf_amount'].replace(0, np.nan)

df.sort_values(['code', 'trade_date'], inplace=True)

# ============================================================
# 3. 因子计算
# ============================================================
print("\nCalculating factors...")

def rolling_by_group(group_df, col, window, func):
    """Apply rolling function within group."""
    return group_df[col].rolling(window, min_periods=max(window // 2, 3)).apply(func, raw=True)

factors = {}
grouped = df.groupby('code')

# ----------------------------------------------------------
# Factor 1: 大单净流入动量 (net_big_momentum_5)
# 经济学假设: 机构资金的方向变化领先价格。5日大单净流入变化率
#            反映机构短期增减仓的加速/减速。
# 公式: (sum_5d(net_big) - sum_5d_lag5(net_big)) / abs(sum_5d_lag5(net_big))
# ----------------------------------------------------------
print("  Factor 1: net_big_momentum_5 (大单净流入动量)")
def calc_f1(g):
    s5 = g['net_big_amount'].rolling(5, min_periods=3).sum()
    s5_lag = s5.shift(5)
    result = (s5 - s5_lag) / s5_lag.abs().replace(0, np.nan)
    return result.clip(-5, 5)  # cap extreme values

factors['net_big_momentum_5'] = grouped.apply(calc_f1).droplevel(0)

# ----------------------------------------------------------
# Factor 2: 资金流集中度 (mf_concentration_10)
# 经济学假设: 短时间内资金集中涌入的股票，往往是有信息驱动的。
#            均匀流入更可能是噪音交易。用净流入的Herfindahl指数衡量。
# 公式: HHI = sum( (|net_mf_i| / sum_10d(|net_mf|))^2 ), i=1..10
#        HHI越大 => 资金越集中在某几天
# ----------------------------------------------------------
print("  Factor 2: mf_concentration_10 (资金流集中度)")
def calc_f2(g):
    abs_net = g['net_mf_amount'].abs()
    results = []
    vals = abs_net.values
    for i in range(len(vals)):
        if i < 9:
            results.append(np.nan)
            continue
        window = vals[i-9:i+1]
        total = np.nansum(window)
        if total == 0:
            results.append(np.nan)
        else:
            shares = window / total
            hhi = np.nansum(shares ** 2)
            results.append(hhi)
    return pd.Series(results, index=g.index)

factors['mf_concentration_10'] = grouped.apply(calc_f2).droplevel(0)

# ----------------------------------------------------------
# Factor 3: 特大单占比变化率 (elg_ratio_change_20)
# 经济学假设: 特大单(>100万元)代表游资/机构大额交易。
#            特大单占比的20日变化率反映游资活跃度趋势。
#            上升 => 大资金正在进场。
# 公式: mean_5d(elg_ratio) - mean_5d_lag20(elg_ratio)
# ----------------------------------------------------------
print("  Factor 3: elg_ratio_change_20 (特大单占比变化率)")
def calc_f3(g):
    ma5 = g['elg_ratio'].rolling(5, min_periods=3).mean()
    ma5_lag = ma5.shift(20)
    return ma5 - ma5_lag

factors['elg_ratio_change_20'] = grouped.apply(calc_f3).droplevel(0)

# ----------------------------------------------------------
# Factor 4: 大小单方向一致性 (big_small_consensus_20)
# 经济学假设: 当大单和小单同方向(都买或都卖)时，市场形成共识，
#            趋势更可能延续。方向分歧时信号不明确。
# 公式: corr(net_big_amount, net_small_amount, 20日滚动)
# ----------------------------------------------------------
print("  Factor 4: big_small_consensus_20 (大小单方向一致性)")
def calc_f4(g):
    return g['net_big_amount'].rolling(20, min_periods=12).corr(g['net_small_amount'])

factors['big_small_consensus_20'] = grouped.apply(calc_f4).droplevel(0)

# ----------------------------------------------------------
# Factor 5: 资金流波动率/价格波动率比值 (mf_price_vol_ratio_20)
# 经济学假设: 资金流波动大但价格波动小 => 知情交易者在暗中建仓/出货
#            (信息交易强度)。价格尚未反映资金动向。
# 公式: std_20(net_mf_amount / total_mf_amount) / std_20(pct_change)
#        用归一化的净流入比率避免市值偏差
# ----------------------------------------------------------
print("  Factor 5: mf_price_vol_ratio_20 (资金流波动/价格波动比)")
def calc_f5(g):
    # 归一化净流入
    mf_norm = g['net_mf_amount'] / g['total_mf_amount'].replace(0, np.nan)
    mf_vol = mf_norm.rolling(20, min_periods=12).std()
    price_vol = g['pct_change'].rolling(20, min_periods=12).std()
    ratio = mf_vol / price_vol.replace(0, np.nan)
    return ratio.clip(0, 10)  # cap

factors['mf_price_vol_ratio_20'] = grouped.apply(calc_f5).droplevel(0)

# ============================================================
# 4. 组装因子DataFrame
# ============================================================
print("\nAssembling factor DataFrame...")
factor_df = df[['code', 'trade_date']].copy()
for fname, fvals in factors.items():
    factor_df[fname] = fvals.values

# Drop rows where all factors are NaN
factor_cols = list(factors.keys())
factor_df.dropna(subset=factor_cols, how='all', inplace=True)
print(f"  Factor DataFrame: {len(factor_df):,} rows")

# ============================================================
# 5. 计算20日超额收益 (forward return)
# ============================================================
print("\nCalculating 20-day forward excess returns...")

# 复权价格
kl_ret = kl.copy()
kl_ret['adj_close'] = kl_ret['close'] * kl_ret['adj_factor']
kl_ret.sort_values(['code', 'trade_date'], inplace=True)

# 20日前瞻收益
kl_ret['fwd_ret_20'] = kl_ret.groupby('code')['adj_close'].transform(
    lambda x: x.shift(-20) / x - 1
)

# Merge benchmark 20d return
bench.sort_values('trade_date', inplace=True)
bench['bench_fwd_20'] = bench['bench_close'].shift(-20) / bench['bench_close'] - 1

fwd = kl_ret[['code', 'trade_date', 'fwd_ret_20']].merge(
    bench[['trade_date', 'bench_fwd_20']], on='trade_date', how='left'
)
fwd['excess_ret_20'] = fwd['fwd_ret_20'] - fwd['bench_fwd_20']

# Merge with factors
factor_df = factor_df.merge(fwd[['code', 'trade_date', 'excess_ret_20']],
                             on=['code', 'trade_date'], how='left')

print(f"  With forward returns: {factor_df['excess_ret_20'].notna().sum():,} valid rows")

# ============================================================
# 6. 月度截面IC (Spearman)
# ============================================================
print("\nCalculating monthly cross-sectional IC (Spearman)...")
print("=" * 70)

# Take month-end dates
factor_df['year_month'] = factor_df['trade_date'].dt.to_period('M')
month_end = factor_df.groupby('year_month')['trade_date'].transform('max')
monthly = factor_df[factor_df['trade_date'] == month_end].copy()
monthly = monthly.dropna(subset=['excess_ret_20'])
print(f"Monthly rebalance dates: {monthly['trade_date'].nunique()}")

ic_results = {}
for fname in factor_cols:
    monthly_ic = []
    for dt, grp in monthly.groupby('trade_date'):
        valid = grp[[fname, 'excess_ret_20']].dropna()
        if len(valid) < 50:
            continue
        ic, _ = stats.spearmanr(valid[fname], valid['excess_ret_20'])
        monthly_ic.append({'date': dt, 'ic': ic})
    
    if not monthly_ic:
        continue
    
    ic_series = pd.DataFrame(monthly_ic)
    mean_ic = ic_series['ic'].mean()
    std_ic = ic_series['ic'].std()
    ir = mean_ic / std_ic if std_ic > 0 else 0
    ic_pos_rate = (ic_series['ic'] > 0).mean()
    n = len(ic_series)
    t_stat = mean_ic / (std_ic / np.sqrt(n)) if std_ic > 0 and n > 1 else 0
    
    ic_results[fname] = {
        'mean_ic': mean_ic,
        'std_ic': std_ic,
        'ir': ir,
        'ic_positive_rate': ic_pos_rate,
        't_stat': t_stat,
        'n_months': n,
        'ic_series': ic_series
    }
    
    print(f"\n{'─' * 50}")
    print(f"Factor: {fname}")
    print(f"  Mean IC:       {mean_ic:+.4f}")
    print(f"  Std IC:        {std_ic:.4f}")
    print(f"  ICIR:          {ir:+.4f}")
    print(f"  IC > 0 rate:   {ic_pos_rate:.1%}")
    print(f"  t-stat:        {t_stat:+.3f}")
    print(f"  N months:      {n}")
    sig = "***" if abs(t_stat) > 2.58 else "**" if abs(t_stat) > 1.96 else "*" if abs(t_stat) > 1.64 else ""
    print(f"  Significance:  {sig if sig else 'not significant'}")

# ============================================================
# 7. 因子间相关性
# ============================================================
print(f"\n{'=' * 70}")
print("Factor cross-correlation (截面均值, Pearson):")

# Use a single large cross-section snapshot (latest month-end with data)
latest_snap = monthly[monthly['trade_date'] == monthly['trade_date'].max()]
if len(latest_snap) > 100:
    corr_matrix = latest_snap[factor_cols].corr(method='spearman')
    print(corr_matrix.round(3).to_string())
else:
    # Average cross-sectional correlation
    corrs = []
    for dt, grp in monthly.groupby('trade_date'):
        if len(grp) < 200:
            continue
        c = grp[factor_cols].corr(method='spearman')
        corrs.append(c)
    if corrs:
        avg_corr = sum(corrs) / len(corrs)
        print(avg_corr.round(3).to_string())

# ============================================================
# 8. 与现有因子的相关性
# ============================================================
print(f"\n{'=' * 70}")
print("Correlation with existing factors (using latest month-end cross-section)...")

existing_factors = ['turnover_mean_20', 'volatility_20', 'reversal_20', 'amihud_20', 'bp_ratio',
                    'price_volume_corr_20', 'momentum_20', 'turnover_surge_ratio']

# Load existing factor values for a recent date
exist_fv = pd.read_sql(f"""
    SELECT code, trade_date, factor_name, zscore
    FROM factor_values
    WHERE factor_name IN ({','.join(["'"+f+"'" for f in existing_factors])})
      AND trade_date = (SELECT max(trade_date) FROM factor_values WHERE factor_name='turnover_mean_20')
""", engine, parse_dates=['trade_date'])

if len(exist_fv) > 0:
    ref_date = exist_fv['trade_date'].iloc[0]
    print(f"  Reference date: {ref_date}")
    exist_pivot = exist_fv.pivot_table(index='code', columns='factor_name', values='zscore')
    
    # Get new factors for same date or nearest
    new_snap = factor_df[factor_df['trade_date'] == ref_date][['code'] + factor_cols].set_index('code')
    
    if len(new_snap) < 50:
        # Try nearest date
        close_dates = factor_df['trade_date'].unique()
        close_dates.sort()
        idx = np.searchsorted(close_dates, ref_date)
        if idx > 0:
            near_date = close_dates[min(idx, len(close_dates)-1)]
            new_snap = factor_df[factor_df['trade_date'] == near_date][['code'] + factor_cols].set_index('code')
            print(f"  Using nearest date: {near_date}")
    
    merged = new_snap.join(exist_pivot, how='inner')
    print(f"  Matched stocks: {len(merged)}")
    
    if len(merged) > 100:
        print("\n  Cross-correlation (new factors vs existing):")
        cross_corr = merged[factor_cols + existing_factors].corr(method='spearman')
        # Show only new vs existing block
        display = cross_corr.loc[factor_cols, existing_factors]
        print(display.round(3).to_string())
else:
    print("  No existing factor data found for correlation check.")

# ============================================================
# 9. 汇总
# ============================================================
print(f"\n{'=' * 70}")
print("SUMMARY TABLE")
print(f"{'=' * 70}")
print(f"{'Factor':<30} {'Mean IC':>8} {'ICIR':>8} {'IC>0%':>8} {'t-stat':>8} {'Sig':>5}")
print(f"{'─' * 30} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 5}")

for fname in factor_cols:
    if fname in ic_results:
        r = ic_results[fname]
        sig = "***" if abs(r['t_stat']) > 2.58 else "**" if abs(r['t_stat']) > 1.96 else "*" if abs(r['t_stat']) > 1.64 else ""
        print(f"{fname:<30} {r['mean_ic']:>+8.4f} {r['ir']:>+8.4f} {r['ic_positive_rate']:>7.1%} {r['t_stat']:>+8.3f} {sig:>5}")

print(f"\n入池门槛: |IC| > 0.015, |t-stat| > 1.64")
print("正交性门槛: 与现有因子相关性 < 0.5")

# Recommendations
print(f"\n{'=' * 70}")
print("RECOMMENDATIONS")
print(f"{'=' * 70}")
for fname in factor_cols:
    if fname in ic_results:
        r = ic_results[fname]
        passed_ic = abs(r['mean_ic']) > 0.015
        passed_t = abs(r['t_stat']) > 1.64
        if passed_ic and passed_t:
            print(f"  PASS  {fname}: IC={r['mean_ic']:+.4f}, t={r['t_stat']:+.3f}")
        elif passed_ic:
            print(f"  WEAK  {fname}: IC={r['mean_ic']:+.4f}, t={r['t_stat']:+.3f} (t-stat too low)")
        else:
            print(f"  FAIL  {fname}: IC={r['mean_ic']:+.4f}, t={r['t_stat']:+.3f}")

print("\nDone.")
