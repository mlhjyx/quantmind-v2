"""
因子池健康报告生成脚本
Sprint 1.3b: 对factor_values表22个因子做统一评级
IC计算方法: Spearman rank correlation(zscore, 5日超额收益)
超额收益: 相对沪深300
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy import stats
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()

def load_index_returns(conn):
    """加载沪深300日收益率"""
    sql = """
    SELECT trade_date, close
    FROM index_daily
    WHERE index_code='000300.SH'
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    df = df.set_index('trade_date').sort_index()
    df['close'] = df['close'].astype(float)
    df['index_ret'] = df['close'].pct_change()
    return df['index_ret']

def load_stock_returns(conn):
    """加载个股日收益率 (复权)"""
    sql = """
    SELECT code, trade_date, close, adj_factor
    FROM klines_daily
    WHERE trade_date >= '2020-07-01' AND trade_date <= '2026-03-23'
      AND is_suspended = false
    ORDER BY code, trade_date
    """
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    df['close'] = df['close'].astype(float)
    df['adj_factor'] = df['adj_factor'].astype(float)
    # 复权价
    df['adj_close'] = df['close'] * df['adj_factor']
    # 日收益率
    df = df.sort_values(['code', 'trade_date'])
    df['ret'] = df.groupby('code')['adj_close'].pct_change()
    return df[['code', 'trade_date', 'ret']].dropna()

def compute_forward_excess_return(stock_ret_df, index_ret_series, forward_days=5):
    """计算5日前瞻超额收益"""
    # Pivot stock returns to wide format
    ret_wide = stock_ret_df.pivot(index='trade_date', columns='code', values='ret')

    # Align index returns
    index_ret_aligned = index_ret_series.reindex(ret_wide.index)

    # Forward cumulative returns (5 days)
    # For each date t, forward_ret = product of (1+r) from t+1 to t+5 - 1
    stock_fwd = (1 + ret_wide).rolling(forward_days).apply(lambda x: x.prod(), raw=True).shift(-forward_days) - 1
    index_fwd = (1 + index_ret_aligned).rolling(forward_days).apply(lambda x: x.prod(), raw=True).shift(-forward_days) - 1

    # Excess return
    excess_ret = stock_fwd.subtract(index_fwd, axis=0)

    # Back to long format
    excess_long = excess_ret.stack().reset_index()
    excess_long.columns = ['trade_date', 'code', 'fwd_excess_ret']
    return excess_long

def load_factors(conn):
    """加载全部因子zscore"""
    sql = """
    SELECT code, trade_date, factor_name, zscore
    FROM factor_values
    WHERE zscore IS NOT NULL
    """
    df = pd.read_sql(sql, conn, parse_dates=['trade_date'])
    df['zscore'] = df['zscore'].astype(float)
    return df

def compute_ic_by_date(factor_df, excess_ret_df, factor_name):
    """计算某因子每日IC (Spearman rank correlation)"""
    f = factor_df[factor_df['factor_name'] == factor_name][['code', 'trade_date', 'zscore']]
    merged = f.merge(excess_ret_df, on=['code', 'trade_date'], how='inner')
    merged = merged.dropna()

    def daily_ic(group):
        if len(group) < 30:
            return np.nan
        rho, _ = stats.spearmanr(group['zscore'], group['fwd_excess_ret'])
        return rho

    ic_series = merged.groupby('trade_date').apply(daily_ic).dropna()
    return ic_series

def main():
    conn = get_conn()
    try:
        print("Loading index returns...")
        index_ret = load_index_returns(conn)

        print("Loading stock returns...")
        stock_ret = load_stock_returns(conn)

        print("Computing 5-day forward excess returns...")
        excess_ret = compute_forward_excess_return(stock_ret, index_ret, forward_days=5)
        print(f"  Excess return records: {len(excess_ret):,}")

        print("Loading factors...")
        factor_df = load_factors(conn)
        factor_names = sorted(factor_df['factor_name'].unique())
        print(f"  Factors: {len(factor_names)}")

        # V1.1 baseline factors
        baseline_factors = ['turnover_mean_20', 'volatility_20', 'reversal_20', 'amihud_20', 'bp_ratio']

        # --- IC Calculation ---
        print("\nCalculating IC for each factor...")
        results = []
        ic_series_dict = {}

        # For correlation: collect daily factor cross-section means won't work.
        # Instead, use factor zscore cross-factor correlation per date

        for fname in factor_names:
            ic_series = compute_ic_by_date(factor_df, excess_ret, fname)
            ic_series_dict[fname] = ic_series

            if len(ic_series) < 20:
                results.append({
                    'factor_name': fname,
                    'ic_mean': np.nan,
                    'ic_std': np.nan,
                    'ir': np.nan,
                    'ic_positive_ratio': np.nan,
                    'n_dates': len(ic_series),
                    'yearly_positive': 'N/A',
                    'years_positive': 0,
                    'years_total': 0,
                    'note': '数据不足'
                })
                print(f"  {fname}: 数据不足 ({len(ic_series)} dates)")
                continue

            ic_mean = ic_series.mean()
            ic_std = ic_series.std()
            ir = ic_mean / ic_std if ic_std > 0 else 0
            ic_pos_ratio = (ic_series > 0).mean()

            # Yearly breakdown
            yearly_ic = {}
            years_positive = 0
            years_total = 0
            for year in range(2020, 2027):
                yearly = ic_series[ic_series.index.year == year]
                if len(yearly) >= 20:
                    ymean = yearly.mean()
                    yearly_ic[year] = ymean
                    years_total += 1
                    if ymean > 0:
                        years_positive += 1

            yearly_str = ", ".join([f"{y}:{v:.3f}" for y, v in sorted(yearly_ic.items())])

            results.append({
                'factor_name': fname,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ir': ir,
                'ic_positive_ratio': ic_pos_ratio,
                'n_dates': len(ic_series),
                'yearly_positive': yearly_str,
                'years_positive': years_positive,
                'years_total': years_total,
                'note': ''
            })
            print(f"  {fname}: IC={ic_mean:.4f}, IR={ir:.4f}, pos_ratio={ic_pos_ratio:.2%}, {years_positive}/{years_total} years positive")

        # --- Cross-factor correlation (using daily zscore cross-section correlation) ---
        print("\nCalculating cross-factor correlations with baseline...")

        # For each non-baseline factor, compute correlation with each baseline factor
        # using cross-sectional zscore on overlapping dates
        corr_results = {}

        for fname in factor_names:
            max_corr_with_baseline = 0.0
            max_corr_partner = ''

            for bfname in baseline_factors:
                if fname == bfname:
                    max_corr_with_baseline = 1.0
                    max_corr_partner = bfname
                    break

                # Get overlapping dates
                f1 = factor_df[factor_df['factor_name'] == fname][['code', 'trade_date', 'zscore']].rename(columns={'zscore': 'z1'})
                f2 = factor_df[factor_df['factor_name'] == bfname][['code', 'trade_date', 'zscore']].rename(columns={'zscore': 'z2'})
                merged = f1.merge(f2, on=['code', 'trade_date'], how='inner').dropna()

                if len(merged) < 1000:
                    continue

                # Sample dates to speed up (use ~50 dates spread across the period)
                dates = sorted(merged['trade_date'].unique())
                sample_dates = dates[::max(1, len(dates)//50)]
                sampled = merged[merged['trade_date'].isin(sample_dates)]

                # Cross-sectional correlation per date, then average
                def cs_corr(grp):
                    if len(grp) < 30:
                        return np.nan
                    return grp['z1'].corr(grp['z2'])

                daily_corrs = sampled.groupby('trade_date').apply(cs_corr).dropna()
                avg_corr = abs(daily_corrs.mean())

                if avg_corr > max_corr_with_baseline:
                    max_corr_with_baseline = avg_corr
                    max_corr_partner = bfname

            corr_results[fname] = (max_corr_with_baseline, max_corr_partner)
            if fname not in baseline_factors:
                print(f"  {fname}: max|corr| with baseline = {max_corr_with_baseline:.3f} ({max_corr_partner})")

        # --- Coverage stats ---
        print("\nGathering coverage stats...")
        coverage_sql = """
        SELECT factor_name,
               COUNT(DISTINCT trade_date) as n_days,
               MIN(trade_date) as min_date,
               MAX(trade_date) as max_date,
               ROUND(AVG(CASE WHEN raw_value IS NULL THEN 1 ELSE 0 END)::numeric * 100, 2) as raw_null_pct
        FROM factor_values
        GROUP BY factor_name
        ORDER BY factor_name
        """
        coverage = pd.read_sql(coverage_sql, conn).set_index('factor_name')

        # --- Rating ---
        print("\nAssigning ratings...")
        report_rows = []

        for r in results:
            fname = r['factor_name']
            ic_mean = r['ic_mean']
            ir = r['ir']
            years_pos = r['years_positive']
            years_total = r['years_total']
            max_corr, corr_partner = corr_results.get(fname, (np.nan, ''))

            cov = coverage.loc[fname] if fname in coverage.index else {}
            n_days = cov.get('n_days', 0) if isinstance(cov, dict) == False else 0
            try:
                n_days = int(cov['n_days'])
            except:
                n_days = 0
            null_pct = float(cov.get('raw_null_pct', 0)) if hasattr(cov, 'get') else 0.0
            min_date = cov.get('min_date', '') if hasattr(cov, 'get') else ''
            max_date = cov.get('max_date', '') if hasattr(cov, 'get') else ''

            # Rating logic
            if r['note'] == '数据不足':
                rating = 'Insufficient'
                reason = f"仅{r['n_dates']}天IC数据，无法评估"
            elif fname in baseline_factors:
                rating = 'Active'
                reason = f"v1.1基线因子"
            elif pd.isna(ic_mean):
                rating = 'Insufficient'
                reason = "IC计算失败"
            else:
                abs_ic = abs(ic_mean)
                stable = years_pos >= 4 if years_total >= 5 else (years_pos >= years_total - 1 and years_total >= 3)
                low_corr = max_corr < 0.5

                if abs_ic >= 0.015 and low_corr and stable:
                    rating = 'Reserve'
                    reason = f"IC>{abs_ic:.1%}, corr<0.5, {years_pos}/{years_total}年正IC — 候选升级"
                elif abs_ic < 0.015:
                    rating = 'Deprecated'
                    reason = f"|IC|={abs_ic:.3f}<1.5%"
                elif max_corr >= 0.7:
                    rating = 'Deprecated'
                    reason = f"与{corr_partner} corr={max_corr:.2f}>0.7，信息冗余"
                elif not stable:
                    rating = 'Deprecated'
                    reason = f"{years_pos}/{years_total}年正IC，不稳定"
                else:
                    # IC>=1.5% but corr 0.5-0.7 or borderline stability
                    rating = 'Watch'
                    reason = f"|IC|={abs_ic:.3f}, corr={max_corr:.2f}, {years_pos}/{years_total}年正IC — 需进一步观察"

            report_rows.append({
                'factor_name': fname,
                'ic_mean': ic_mean,
                'ir': ir,
                'years_positive': f"{years_pos}/{years_total}" if years_total > 0 else 'N/A',
                'max_baseline_corr': max_corr,
                'corr_partner': corr_partner,
                'n_days': n_days,
                'null_pct': null_pct,
                'date_range': f"{min_date}~{max_date}",
                'rating': rating,
                'reason': reason,
                'yearly_detail': r.get('yearly_positive', '')
            })

        # --- Output ---
        report_df = pd.DataFrame(report_rows).sort_values('rating')

        # Print summary
        print("\n" + "="*120)
        print("因子池健康报告 — Sprint 1.3b")
        print("="*120)

        rating_counts = report_df['rating'].value_counts()
        print(f"\n评级分布: {dict(rating_counts)}")

        print(f"\n{'因子':<24} {'IC_mean':>8} {'IR':>8} {'年度稳定':>8} {'基线maxCorr':>11} {'Corr伙伴':<20} {'覆盖天数':>8} {'NaN%':>6} {'评级':<12} 理由")
        print("-"*160)

        for _, row in report_df.iterrows():
            ic_str = f"{row['ic_mean']:.4f}" if not pd.isna(row['ic_mean']) else 'N/A'
            ir_str = f"{row['ir']:.4f}" if not pd.isna(row['ir']) else 'N/A'
            corr_str = f"{row['max_baseline_corr']:.3f}" if not pd.isna(row['max_baseline_corr']) else 'N/A'
            print(f"{row['factor_name']:<24} {ic_str:>8} {ir_str:>8} {row['years_positive']:>8} {corr_str:>11} {row['corr_partner']:<20} {row['n_days']:>8} {row['null_pct']:>6} {row['rating']:<12} {row['reason']}")

        # Yearly IC detail
        print(f"\n{'='*120}")
        print("年度IC明细:")
        print(f"{'='*120}")
        for _, row in report_df.iterrows():
            if row['yearly_detail'] and row['yearly_detail'] != 'N/A':
                print(f"  {row['factor_name']:<24} {row['yearly_detail']}")

        # Save to markdown
        md_path = str(Path(__file__).resolve().parent.parent / 'docs' / 'FACTOR_HEALTH_REPORT.md')
        with open(md_path, 'w') as f:
            f.write("# 因子池健康报告 — Sprint 1.3b\n\n")
            f.write(f"> 生成时间: 2026-03-23\n")
            f.write(f"> IC方法: Spearman rank correlation(zscore, 5日超额收益vs沪深300)\n")
            f.write(f"> 数据范围: 2020-07-01 ~ 2026-03-23\n\n")

            f.write(f"## 评级分布\n\n")
            for rating, count in rating_counts.items():
                f.write(f"- **{rating}**: {count}个\n")
            f.write(f"\n## 评级标准\n\n")
            f.write("| 评级 | 条件 | 含义 |\n")
            f.write("|------|------|------|\n")
            f.write("| **Active** | v1.1基线因子 | 当前策略使用中 |\n")
            f.write("| **Reserve** | |IC|>1.5%, 基线corr<0.5, 4/5年正IC | 候选升级因子 |\n")
            f.write("| **Watch** | 部分达标但需观察 | 条件边界因子 |\n")
            f.write("| **Deprecated** | |IC|<1.5% 或 corr>0.7 或 不稳定 | 建议停止日常计算 |\n")
            f.write("| **Insufficient** | 数据覆盖不足 | 无法评估 |\n\n")

            f.write("## 因子评级总表\n\n")
            f.write("| 因子 | IC_mean | IR | 年度稳定 | 基线max\\|Corr\\| | Corr伙伴 | 覆盖天数 | NaN% | 评级 | 理由 |\n")
            f.write("|------|---------|-----|----------|----------------|----------|----------|------|------|------|\n")

            for _, row in report_df.iterrows():
                ic_str = f"{row['ic_mean']:.4f}" if not pd.isna(row['ic_mean']) else 'N/A'
                ir_str = f"{row['ir']:.4f}" if not pd.isna(row['ir']) else 'N/A'
                corr_str = f"{row['max_baseline_corr']:.3f}" if not pd.isna(row['max_baseline_corr']) else 'N/A'
                f.write(f"| {row['factor_name']} | {ic_str} | {ir_str} | {row['years_positive']} | {corr_str} | {row['corr_partner']} | {row['n_days']} | {row['null_pct']} | **{row['rating']}** | {row['reason']} |\n")

            f.write("\n## 年度IC明细\n\n")
            f.write("| 因子 | 年度IC (year:IC_mean) |\n")
            f.write("|------|-----------------------|\n")
            for _, row in report_df.iterrows():
                if row['yearly_detail'] and row['yearly_detail'] != 'N/A':
                    f.write(f"| {row['factor_name']} | {row['yearly_detail']} |\n")

            f.write("\n## 升级建议\n\n")
            reserves = report_df[report_df['rating'] == 'Reserve']
            if len(reserves) > 0:
                f.write("以下因子具备升级至v1.2/v1.3的潜力：\n\n")
                for _, row in reserves.iterrows():
                    f.write(f"- **{row['factor_name']}**: IC={row['ic_mean']:.4f}, IR={row['ir']:.4f}, 与基线max|corr|={row['max_baseline_corr']:.3f}\n")
            else:
                f.write("当前无符合Reserve标准的因子。\n")

            watches = report_df[report_df['rating'] == 'Watch']
            if len(watches) > 0:
                f.write("\n以下因子需进一步观察（Watch）：\n\n")
                for _, row in watches.iterrows():
                    f.write(f"- **{row['factor_name']}**: {row['reason']}\n")

            deprecateds = report_df[report_df['rating'] == 'Deprecated']
            if len(deprecateds) > 0:
                f.write(f"\n以下{len(deprecateds)}个因子建议标记Deprecated，停止日常计算以节省资源：\n\n")
                for _, row in deprecateds.iterrows():
                    f.write(f"- **{row['factor_name']}**: {row['reason']}\n")

        print(f"\n报告已保存到: {md_path}")
    finally:
        conn.close()

if __name__ == '__main__':
    main()
