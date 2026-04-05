#!/usr/bin/env python3
"""候选3(行业轮动) 可行性评估 — 行业动量/反转因子IC检验。

数据源: index_daily表中的申万行业指数(46,593行)
目标: 在31个申万一级行业截面上计算行业动量/反转因子的IC

因子:
  - ind_momentum_20: 行业指数20日收益率 (动量)
  - ind_momentum_60: 行业指数60日收益率 (中期动量)
  - ind_reversal_60: 行业指数60日收益率取反 (反转)

IC定义: 当日因子值 vs 未来20日行业指数收益率的Spearman相关性
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.services.price_utils import _get_sync_conn


def main():
    conn = _get_sync_conn()

    # 1. 加载申万行业指数日线
    print("加载申万行业指数数据...")
    df = pd.read_sql(
        """SELECT index_code, trade_date, close
           FROM index_daily
           WHERE index_code LIKE '8010%%.SI'
              OR index_code LIKE '8011%%.SI'
              OR index_code LIKE '8012%%.SI'
              OR index_code LIKE '8013%%.SI'
              OR index_code LIKE '8014%%.SI'
              OR index_code LIKE '8015%%.SI'
              OR index_code LIKE '8016%%.SI'
              OR index_code LIKE '8017%%.SI'
              OR index_code LIKE '8018%%.SI'
              OR index_code LIKE '8019%%.SI'
              OR index_code LIKE '8020%%.SI'
           ORDER BY index_code, trade_date""",
        conn,
    )

    if df.empty:
        # Try alternative: check what index_codes exist
        print("申万行业指数查询为空，检查index_daily中有哪些行业指数...")
        sample = pd.read_sql(
            """SELECT DISTINCT index_code, COUNT(*) as cnt
               FROM index_daily
               GROUP BY index_code
               ORDER BY index_code
               LIMIT 50""",
            conn,
        )
        print(sample.to_string())

        # Try loading all SW indices
        df = pd.read_sql(
            """SELECT index_code, trade_date, close
               FROM index_daily
               WHERE index_code NOT IN ('000300.SH', '000905.SH', '000001.SH', '399001.SZ', '399006.SZ')
               ORDER BY index_code, trade_date""",
            conn,
        )

    n_indices = df["index_code"].nunique()
    print(f"行业指数数量: {n_indices}, 总行数: {len(df)}")
    print(f"指数列表: {sorted(df['index_code'].unique())[:10]}...")
    print(f"日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")

    if n_indices < 10:
        print("行业指数数据不足(< 10个行业), 无法做截面IC分析。")
        conn.close()
        return

    # 2. 构建宽表 (trade_date × index_code)
    pivot = df.pivot_table(index="trade_date", columns="index_code", values="close")
    pivot = pivot.sort_index()
    print(f"宽表形状: {pivot.shape}")

    # 3. 计算因子
    pivot.pct_change(1)
    ret_20d = pivot.pct_change(20)
    ret_60d = pivot.pct_change(60)

    # forward return (未来20日)
    fwd_20d = pivot.pct_change(20).shift(-20)

    # 因子
    factors = {
        "ind_momentum_20": ret_20d,       # 过去20日动量
        "ind_momentum_60": ret_60d,       # 过去60日动量
        "ind_reversal_60": -ret_60d,      # 过去60日反转
        "ind_reversal_20": -ret_20d,      # 过去20日反转
    }

    # 4. 计算截面IC (Spearman rank correlation)
    print("\n" + "=" * 70)
    print("行业层面因子IC分析")
    print("=" * 70)
    print(f"截面: {n_indices}个行业, IC = Spearman(因子, 未来20日收益)")
    print()

    for fname, factor_df in factors.items():
        # 对齐
        common_dates = factor_df.dropna(how="all").index.intersection(
            fwd_20d.dropna(how="all").index
        )
        # 过滤: 至少要有15个行业有数据
        valid_dates = []
        ic_values = []

        for d in common_dates:
            f_vals = factor_df.loc[d].dropna()
            r_vals = fwd_20d.loc[d].dropna()
            common_idx = f_vals.index.intersection(r_vals.index)
            if len(common_idx) < 15:
                continue
            rho, _ = stats.spearmanr(f_vals.loc[common_idx], r_vals.loc[common_idx])
            if not np.isnan(rho):
                ic_values.append(rho)
                valid_dates.append(d)

        if not ic_values:
            print(f"  {fname}: 无有效IC数据")
            continue

        ic_series = pd.Series(ic_values, index=valid_dates)
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        hit_rate = (ic_series > 0).mean() if fname.startswith("ind_momentum") else (ic_series > 0).mean()

        print(f"  {fname}:")
        print(f"    IC_mean = {ic_mean:.4f} ({ic_mean*100:.2f}%)")
        print(f"    IC_std  = {ic_std:.4f}")
        print(f"    IC_IR   = {ic_ir:.3f}")
        print(f"    命中率  = {hit_rate:.1%} (IC>0的比例)")
        print(f"    有效月数 = {len(ic_values)}")

        # 分年度IC
        yearly = ic_series.groupby(ic_series.index.map(lambda d: d.year)).mean()
        print("    年度IC: ", end="")
        for yr, v in yearly.items():
            print(f"{yr}:{v*100:+.1f}% ", end="")
        print()
        print()

    # 5. 行业动量/反转策略简单回测 (Long top 5 / Short bottom 5)
    print("\n" + "=" * 70)
    print("简单行业轮动回测: 每月选Top-5行业等权配置")
    print("=" * 70)

    # 使用实际交易日: 每月最后一个有数据的日期
    pivot_dt = pivot.copy()
    pivot_dt.index = pd.to_datetime(pivot_dt.index)
    monthly_dates = pivot_dt.resample("ME").last().index
    monthly_dates_actual = []
    for m in monthly_dates:
        mask = pivot_dt.index <= m
        if mask.any():
            monthly_dates_actual.append(pivot_dt.index[mask][-1])

    # Convert factor_dfs to datetime index too
    factors_dt = {}
    for fname, fdf in factors.items():
        fdf_dt = fdf.copy()
        fdf_dt.index = pd.to_datetime(fdf_dt.index)
        factors_dt[fname] = fdf_dt

    for fname, factor_df in factors_dt.items():
        monthly_returns = []
        for i in range(len(monthly_dates_actual) - 1):
            d = monthly_dates_actual[i]
            d_next = monthly_dates_actual[i + 1]

            if d not in factor_df.index:
                continue

            f_vals = factor_df.loc[d].dropna()
            if len(f_vals) < 15:
                continue

            # 选Top-5行业
            top5 = f_vals.nlargest(5).index

            # 计算下个月这5个行业的等权收益
            if d_next in pivot_dt.index and d in pivot_dt.index:
                rets = (pivot_dt.loc[d_next, top5] / pivot_dt.loc[d, top5] - 1).dropna()
                if len(rets) > 0:
                    monthly_returns.append({
                        "date": d_next,
                        "return": rets.mean(),
                    })

        if not monthly_returns:
            print(f"\n  {fname}: 无回测数据")
            continue

        mr = pd.DataFrame(monthly_returns).set_index("date")["return"]
        ann_r = (1 + mr).prod() ** (12 / len(mr)) - 1
        ann_v = mr.std() * np.sqrt(12)
        sh = ann_r / ann_v if ann_v > 0 else 0

        print(f"\n  {fname} (Top-5行业等权, 月频):")
        print(f"    年化收益 = {ann_r:.2%}")
        print(f"    年化波动 = {ann_v:.2%}")
        print(f"    Sharpe   = {sh:.3f}")
        print(f"    月胜率   = {(mr > 0).mean():.1%}")
        print(f"    有效月数 = {len(mr)}")

    conn.close()
    print("\n完成。")


if __name__ == "__main__":
    main()
