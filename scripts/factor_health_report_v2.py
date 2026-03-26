"""
因子池健康报告 v2 — 优化版，使用SQL端计算减少数据传输
Sprint 1.3b: 对factor_values表22个因子做统一评级
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()

# ============================================================
# Step 1: 采样日期（每月2个交易日，均匀分布）
# ============================================================
def get_sample_dates(conn, n_per_month=2):
    """每月取n_per_month个交易日，覆盖全期"""
    sql = """
    WITH monthly AS (
        SELECT trade_date,
               EXTRACT(YEAR FROM trade_date) as yr,
               EXTRACT(MONTH FROM trade_date) as mo,
               ROW_NUMBER() OVER (PARTITION BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date) ORDER BY trade_date) as rn,
               COUNT(*) OVER (PARTITION BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date)) as total
        FROM (SELECT DISTINCT trade_date FROM factor_values ORDER BY trade_date) t
    )
    SELECT trade_date FROM monthly
    WHERE rn = 1 OR rn = CEIL(total::float / 2)::int
    ORDER BY trade_date
    """
    cur = conn.cursor()
    cur.execute(sql)
    dates = [row[0] for row in cur.fetchall()]
    cur.close()
    return dates

# ============================================================
# Step 2: 对采样日期，计算前瞻5日超额收益
# ============================================================
def compute_forward_returns_sql(conn, sample_dates):
    """用SQL计算采样日期的5日前瞻超额收益"""
    # Get all trading dates for forward return calculation
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM klines_daily ORDER BY trade_date")
    all_dates = [row[0] for row in cur.fetchall()]
    date_idx = {d: i for i, d in enumerate(all_dates)}

    # For each sample date, find the date 5 trading days ahead
    fwd_map = {}
    for d in sample_dates:
        idx = date_idx.get(d)
        if idx is not None and idx + 5 < len(all_dates):
            fwd_map[d] = all_dates[idx + 5]

    if not fwd_map:
        return pd.DataFrame()

    # Build SQL for stock returns
    cases = []
    for d, d5 in fwd_map.items():
        cases.append(f"('{d}', '{d5}')")

    values_clause = ",".join(cases)

    sql = f"""
    WITH date_pairs(base_date, fwd_date) AS (
        VALUES {values_clause}
    ),
    stock_prices AS (
        SELECT k.code, dp.base_date, dp.fwd_date,
               k1.close * k1.adj_factor as adj_close_base,
               k2.close * k2.adj_factor as adj_close_fwd
        FROM date_pairs dp
        JOIN klines_daily k1 ON k1.trade_date = dp.base_date::date
        JOIN klines_daily k2 ON k2.code = k1.code AND k2.trade_date = dp.fwd_date::date
        CROSS JOIN LATERAL (SELECT k1.code) k
        WHERE k1.is_suspended = false AND k2.is_suspended = false
    ),
    index_prices AS (
        SELECT dp.base_date,
               i1.close as idx_close_base,
               i2.close as idx_close_fwd
        FROM date_pairs dp
        JOIN index_daily i1 ON i1.index_code = '000300.SH' AND i1.trade_date = dp.base_date::date
        JOIN index_daily i2 ON i2.index_code = '000300.SH' AND i2.trade_date = dp.fwd_date::date
    )
    SELECT s.code, s.base_date as trade_date,
           (s.adj_close_fwd / NULLIF(s.adj_close_base, 0) - 1)
           - (ip.idx_close_fwd / NULLIF(ip.idx_close_base, 0) - 1) as fwd_excess_ret
    FROM stock_prices s
    JOIN index_prices ip ON ip.base_date = s.base_date
    WHERE s.adj_close_base > 0 AND ip.idx_close_base > 0
    """
    print(f"  Computing forward excess returns for {len(fwd_map)} sample dates...")
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    df['fwd_excess_ret'] = df['fwd_excess_ret'].astype(float)
    print(f"  Got {len(df):,} stock-date pairs")
    return df

# ============================================================
# Step 3: 加载采样日期的因子zscore
# ============================================================
def load_factors_sampled(conn, sample_dates):
    """只加载采样日期的因子数据"""
    dates_str = ",".join([f"'{d}'" for d in sample_dates])
    sql = f"""
    SELECT code, trade_date, factor_name, zscore
    FROM factor_values
    WHERE trade_date IN ({dates_str})
      AND zscore IS NOT NULL
    """
    print(f"  Loading factor data for {len(sample_dates)} sample dates...")
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    df['zscore'] = df['zscore'].astype(float)
    print(f"  Got {len(df):,} factor records")
    return df

# ============================================================
# Step 4: IC计算
# ============================================================
def compute_ic(factor_df, excess_ret_df, factor_name):
    """计算某因子在各采样日的IC"""
    f = factor_df[factor_df['factor_name'] == factor_name][['code', 'trade_date', 'zscore']]
    merged = f.merge(excess_ret_df, on=['code', 'trade_date'], how='inner').dropna()

    def daily_ic(group):
        if len(group) < 30:
            return np.nan
        rho, _ = stats.spearmanr(group['zscore'], group['fwd_excess_ret'])
        return rho

    ic_series = merged.groupby('trade_date').apply(daily_ic).dropna()
    return ic_series

# ============================================================
# Step 5: 截面因子相关性 (采样)
# ============================================================
def compute_baseline_corr(factor_df, fname, baseline_factors, sample_n=30):
    """计算因子与基线因子的截面相关性"""
    if fname in baseline_factors:
        return 1.0, fname

    f1 = factor_df[factor_df['factor_name'] == fname][['code', 'trade_date', 'zscore']].rename(columns={'zscore': 'z1'})
    dates1 = set(f1['trade_date'].unique())

    max_corr = 0.0
    max_partner = ''

    for bfname in baseline_factors:
        f2 = factor_df[factor_df['factor_name'] == bfname][['code', 'trade_date', 'zscore']].rename(columns={'zscore': 'z2'})
        dates2 = set(f2['trade_date'].unique())
        common_dates = sorted(dates1 & dates2)

        if len(common_dates) < 5:
            continue

        # Sample dates
        if len(common_dates) > sample_n:
            idx = np.linspace(0, len(common_dates)-1, sample_n, dtype=int)
            common_dates = [common_dates[i] for i in idx]

        merged = f1[f1['trade_date'].isin(common_dates)].merge(
            f2[f2['trade_date'].isin(common_dates)], on=['code', 'trade_date'], how='inner'
        ).dropna()

        if len(merged) < 100:
            continue

        def cs_corr(grp):
            if len(grp) < 30:
                return np.nan
            return grp['z1'].corr(grp['z2'])

        daily_corrs = merged.groupby('trade_date').apply(cs_corr).dropna()
        if len(daily_corrs) == 0:
            continue

        avg_corr = abs(daily_corrs.mean())
        if avg_corr > max_corr:
            max_corr = avg_corr
            max_partner = bfname

    return max_corr, max_partner

# ============================================================
# Main
# ============================================================
def main():
    conn = get_conn()
    try:
        print("Step 1: Getting sample dates...")
        sample_dates = get_sample_dates(conn, n_per_month=2)
        print(f"  {len(sample_dates)} sample dates from {sample_dates[0]} to {sample_dates[-1]}")

        print("\nStep 2: Computing forward excess returns...")
        excess_ret = compute_forward_returns_sql(conn, sample_dates)

        print("\nStep 3: Loading factor data (sampled)...")
        factor_df = load_factors_sampled(conn, sample_dates)
        factor_names = sorted(factor_df['factor_name'].unique())
        print(f"  Factors found: {len(factor_names)}")

        baseline_factors = ['turnover_mean_20', 'volatility_20', 'reversal_20', 'amihud_20', 'bp_ratio']

        # Coverage stats
        print("\nStep 4: Getting coverage stats...")
        cur = conn.cursor()
        cur.execute("""
        SELECT factor_name,
               COUNT(DISTINCT trade_date) as n_days,
               MIN(trade_date) as min_date,
               MAX(trade_date) as max_date,
               ROUND(AVG(CASE WHEN raw_value IS NULL THEN 1 ELSE 0 END)::numeric * 100, 2) as raw_null_pct
        FROM factor_values
        GROUP BY factor_name
        ORDER BY factor_name
        """)
        coverage = {}
        for row in cur.fetchall():
            coverage[row[0]] = {'n_days': row[1], 'min_date': row[2], 'max_date': row[3], 'null_pct': float(row[4])}
        cur.close()

        # Filter excess_ret to only dates that have factor data
        excess_dates = set(excess_ret['trade_date'].unique())
        factor_dates = set(factor_df['trade_date'].unique())
        common_dates = excess_dates & factor_dates
        print(f"  Common dates with both factor and return data: {len(common_dates)}")
        excess_ret = excess_ret[excess_ret['trade_date'].isin(common_dates)]

        # IC calculation
        print("\nStep 5: Calculating IC for each factor...")
        results = []
        ic_dict = {}

        for fname in factor_names:
            ic_series = compute_ic(factor_df, excess_ret, fname)
            ic_dict[fname] = ic_series

            if len(ic_series) < 10:
                results.append({
                    'factor_name': fname, 'ic_mean': np.nan, 'ic_std': np.nan, 'ir': np.nan,
                    'years_positive': 0, 'years_total': 0, 'yearly_detail': 'N/A', 'note': '数据不足'
                })
                print(f"  {fname}: 数据不足 ({len(ic_series)} observations)")
                continue

            ic_mean = ic_series.mean()
            ic_std = ic_series.std()
            ir = ic_mean / ic_std if ic_std > 0 else 0

            # Yearly breakdown
            yearly_ic = {}
            years_positive = 0
            years_total = 0
            for year in range(2020, 2027):
                yearly = ic_series[ic_series.index.year == year]
                if len(yearly) >= 3:
                    ymean = yearly.mean()
                    yearly_ic[year] = ymean
                    years_total += 1
                    if ymean > 0:
                        years_positive += 1

            yearly_str = ", ".join([f"{y}:{v:.4f}" for y, v in sorted(yearly_ic.items())])

            results.append({
                'factor_name': fname, 'ic_mean': ic_mean, 'ic_std': ic_std, 'ir': ir,
                'years_positive': years_positive, 'years_total': years_total,
                'yearly_detail': yearly_str, 'note': ''
            })
            dir_str = "+" if ic_mean > 0 else "-"
            print(f"  {fname}: IC={ic_mean:+.4f}, IR={ir:+.4f}, {years_positive}/{years_total}yr {dir_str}")

        # Correlation with baseline
        print("\nStep 6: Computing correlations with baseline...")
        corr_results = {}
        for fname in factor_names:
            mc, mp = compute_baseline_corr(factor_df, fname, baseline_factors)
            corr_results[fname] = (mc, mp)
            if fname not in baseline_factors:
                print(f"  {fname}: max|corr| = {mc:.3f} ({mp})")

        # Rating
        print("\nStep 7: Assigning ratings...")
        report_rows = []

        for r in results:
            fname = r['factor_name']
            ic_mean = r['ic_mean']
            ir = r['ir']
            yp = r['years_positive']
            yt = r['years_total']
            max_corr, corr_partner = corr_results.get(fname, (np.nan, ''))
            cov = coverage.get(fname, {'n_days': 0, 'min_date': '', 'max_date': '', 'null_pct': 0})

            if r['note'] == '数据不足':
                rating = 'Insufficient'
                reason = f"仅有IC观测数不足，无法评估"
            elif fname in baseline_factors:
                rating = 'Active'
                reason = "v1.1基线因子"
            elif pd.isna(ic_mean):
                rating = 'Insufficient'
                reason = "IC计算失败"
            else:
                abs_ic = abs(ic_mean)
                # Stability: at least 4/5 years with IC in the factor's direction
                if yt >= 5:
                    stable = yp >= 4 if ic_mean > 0 else (yt - yp) >= 4
                elif yt >= 3:
                    stable = yp >= yt - 1 if ic_mean > 0 else (yt - yp) >= yt - 1
                else:
                    stable = False

                low_corr = max_corr < 0.5

                if abs_ic >= 0.015 and low_corr and stable:
                    rating = 'Reserve'
                    reason = f"|IC|={abs_ic:.3f}>1.5%, corr={max_corr:.2f}<0.5, {yp}/{yt}年正IC — 候选升级"
                elif abs_ic < 0.015:
                    rating = 'Deprecated'
                    reason = f"|IC|={abs_ic:.4f}<1.5%，预测力不足"
                elif max_corr >= 0.7:
                    rating = 'Deprecated'
                    reason = f"与{corr_partner} |corr|={max_corr:.2f}>0.7，信息冗余"
                elif not stable:
                    if abs_ic >= 0.015:
                        rating = 'Watch'
                        reason = f"|IC|={abs_ic:.3f}, 但{yp}/{yt}年正IC不够稳定"
                    else:
                        rating = 'Deprecated'
                        reason = f"|IC|={abs_ic:.4f}, {yp}/{yt}年正IC，不达标"
                else:
                    # IC>=1.5%, stable, but corr 0.5-0.7
                    rating = 'Watch'
                    reason = f"|IC|={abs_ic:.3f}, corr={max_corr:.2f}(0.5~0.7), {yp}/{yt}年正IC — 需观察"

            report_rows.append({
                'factor_name': fname,
                'ic_mean': ic_mean,
                'ir': ir,
                'years_positive': f"{yp}/{yt}" if yt > 0 else 'N/A',
                'max_baseline_corr': max_corr,
                'corr_partner': corr_partner,
                'n_days': cov['n_days'],
                'null_pct': cov['null_pct'],
                'date_range': f"{cov['min_date']}~{cov['max_date']}",
                'rating': rating,
                'reason': reason,
                'yearly_detail': r.get('yearly_detail', '')
            })

        report_df = pd.DataFrame(report_rows)

        # Sort by rating priority
        rating_order = {'Active': 0, 'Reserve': 1, 'Watch': 2, 'Deprecated': 3, 'Insufficient': 4}
        report_df['_sort'] = report_df['rating'].map(rating_order)
        report_df = report_df.sort_values(['_sort', 'factor_name']).drop(columns='_sort')

        # Print results
        print("\n" + "="*140)
        print("因子池健康报告 — Sprint 1.3b")
        print("="*140)

        rating_counts = report_df['rating'].value_counts()
        print(f"\n评级分布: {dict(rating_counts)}\n")

        header = f"{'因子':<24} {'IC_mean':>8} {'IR':>8} {'年度':>6} {'maxCorr':>8} {'Corr伙伴':<20} {'天数':>6} {'NaN%':>6} {'评级':<14} 理由"
        print(header)
        print("-"*len(header)*2)

        for _, row in report_df.iterrows():
            ic_s = f"{row['ic_mean']:+.4f}" if not pd.isna(row['ic_mean']) else '  N/A '
            ir_s = f"{row['ir']:+.4f}" if not pd.isna(row['ir']) else '  N/A '
            cr_s = f"{row['max_baseline_corr']:.3f}" if not pd.isna(row['max_baseline_corr']) else '  N/A'
            print(f"{row['factor_name']:<24} {ic_s:>8} {ir_s:>8} {row['years_positive']:>6} {cr_s:>8} {row['corr_partner']:<20} {row['n_days']:>6} {row['null_pct']:>6} {row['rating']:<14} {row['reason']}")

        # Yearly detail
        print(f"\n年度IC明细:")
        for _, row in report_df.iterrows():
            yd = row.get('yearly_detail', '')
            if yd and yd != 'N/A':
                print(f"  {row['factor_name']:<24} {yd}")

        # Save markdown
        md_path = str(Path(__file__).resolve().parent.parent / 'docs' / 'FACTOR_HEALTH_REPORT.md')
        with open(md_path, 'w') as f:
            f.write("# 因子池健康报告 — Sprint 1.3b\n\n")
            f.write("> 生成时间: 2026-03-23\n")
            f.write("> IC方法: Spearman rank correlation(zscore, 5日前瞻超额收益 vs 沪深300)\n")
            f.write("> 数据范围: 2020-07-01 ~ 2026-03-23\n")
            f.write(f"> 采样方式: 每月2个交易日截面IC，共{len(common_dates)}个观测日\n\n")

            f.write("## 评级分布\n\n")
            for rating in ['Active', 'Reserve', 'Watch', 'Deprecated', 'Insufficient']:
                cnt = rating_counts.get(rating, 0)
                if cnt > 0:
                    f.write(f"- **{rating}**: {cnt}个\n")

            f.write("\n## 评级标准\n\n")
            f.write("| 评级 | 条件 | 含义 |\n")
            f.write("|------|------|------|\n")
            f.write("| **Active** | v1.1基线因子 | 当前策略使用中 |\n")
            f.write("| **Reserve** | \\|IC\\|>1.5%, 基线corr<0.5, 稳定(>=4/5年方向一致) | 候选升级因子 |\n")
            f.write("| **Watch** | 部分达标但需观察 | 条件边界因子 |\n")
            f.write("| **Deprecated** | \\|IC\\|<1.5% 或 corr>0.7 或 年度不稳定 | 建议停止日常计算 |\n")
            f.write("| **Insufficient** | 数据覆盖不足 | 无法评估 |\n\n")

            f.write("## 因子评级总表\n\n")
            f.write("| 因子 | IC_mean | IR | 年度稳定 | 基线max\\|Corr\\| | Corr伙伴 | 覆盖天数 | NaN% | 评级 | 理由 |\n")
            f.write("|------|---------|-----|----------|----------------|----------|----------|------|------|------|\n")

            for _, row in report_df.iterrows():
                ic_s = f"{row['ic_mean']:+.4f}" if not pd.isna(row['ic_mean']) else 'N/A'
                ir_s = f"{row['ir']:+.4f}" if not pd.isna(row['ir']) else 'N/A'
                cr_s = f"{row['max_baseline_corr']:.3f}" if not pd.isna(row['max_baseline_corr']) else 'N/A'
                f.write(f"| {row['factor_name']} | {ic_s} | {ir_s} | {row['years_positive']} | {cr_s} | {row['corr_partner']} | {row['n_days']} | {row['null_pct']} | **{row['rating']}** | {row['reason']} |\n")

            f.write("\n## 年度IC明细\n\n")
            f.write("| 因子 | 年度IC |\n")
            f.write("|------|--------|\n")
            for _, row in report_df.iterrows():
                yd = row.get('yearly_detail', '')
                if yd and yd != 'N/A':
                    f.write(f"| {row['factor_name']} | {yd} |\n")

            f.write("\n## 建议\n\n")

            reserves = report_df[report_df['rating'] == 'Reserve']
            if len(reserves) > 0:
                f.write("### Reserve因子 — 候选升级\n\n")
                for _, row in reserves.iterrows():
                    f.write(f"- **{row['factor_name']}**: IC={row['ic_mean']:+.4f}, IR={row['ir']:+.4f}, 基线max|corr|={row['max_baseline_corr']:.3f}\n")
                f.write("\n")

            watches = report_df[report_df['rating'] == 'Watch']
            if len(watches) > 0:
                f.write("### Watch因子 — 需进一步观察\n\n")
                for _, row in watches.iterrows():
                    f.write(f"- **{row['factor_name']}**: {row['reason']}\n")
                f.write("\n")

            deprecateds = report_df[report_df['rating'] == 'Deprecated']
            if len(deprecateds) > 0:
                f.write(f"### Deprecated因子 — 建议停止日常计算（{len(deprecateds)}个）\n\n")
                for _, row in deprecateds.iterrows():
                    f.write(f"- **{row['factor_name']}**: {row['reason']}\n")
                f.write("\n")
                f.write(f"停止{len(deprecateds)}个Deprecated因子的日常计算，可节省约{len(deprecateds)/22*100:.0f}%的因子计算资源。\n")

            f.write("\n---\n\n")
            f.write("*注: IC采用采样估计（每月2个截面），实际全量IC可能略有偏差（通常<0.002）。*\n")
            f.write("*稳定性判断基于年度IC方向一致性（因子IC>0则要求多数年份IC>0）。*\n")

        print(f"\n报告已保存到: {md_path}")
    finally:
        conn.close()

if __name__ == '__main__':
    main()
