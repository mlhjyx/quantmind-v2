#!/usr/bin/env python3
"""GPA因子(gross_profit_margin proxy) IC分析脚本。

研究目标:
  - 用financial_indicators.gross_profit_margin作为GPA的proxy
  - PIT对齐(actual_ann_date)，计算每月Spearman IC
  - 排除金融股（银行/保险/证券，毛利率NULL率极高）
  - 与forward 5日超额收益(vs CSI300)计算IC
  - 评估是否通过IC Gate (IC > 0.015)

用法:
    python scripts/analyze_gpa_ic.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.services.price_utils import _get_sync_conn


# ---- 配置 ----
START_DATE = date(2021, 1, 4)
END_DATE = date(2025, 12, 31)
FORWARD_DAYS = 5
IC_GATE = 0.015
EXCLUDE_INDUSTRIES = ("银行", "保险", "证券")
DB_URI = "postgresql://quantmind:quantmind@localhost:5432/quantmind_v2"


def load_monthly_trade_dates(conn) -> list[date]:
    """每月最后一个交易日作为IC计算截面日。"""
    df = pd.read_sql(
        """SELECT trade_date
           FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s
           GROUP BY trade_date
           ORDER BY trade_date""",
        conn,
        params=(START_DATE, END_DATE),
    )
    dates = pd.to_datetime(df["trade_date"])
    # 每月最后一个交易日
    monthly = dates.groupby(dates.dt.to_period("M")).max()
    return [d.date() for d in monthly]


def load_gpa_pit(trade_date: date, conn) -> pd.Series:
    """PIT方式加载截至trade_date的最新gross_profit_margin。

    逻辑:
      1. 只取actual_ann_date <= trade_date的记录
      2. 同一(code, report_date)取actual_ann_date最新
      3. 每个code取report_date最新的那条
      4. 排除金融股
    """
    df = pd.read_sql(
        """WITH ranked AS (
            SELECT fi.code, fi.report_date, fi.actual_ann_date,
                   fi.gross_profit_margin,
                   ROW_NUMBER() OVER (
                       PARTITION BY fi.code, fi.report_date
                       ORDER BY fi.actual_ann_date DESC
                   ) AS rn
            FROM financial_indicators fi
            JOIN symbols s ON fi.code = s.code
            WHERE fi.actual_ann_date <= %s
              AND fi.gross_profit_margin IS NOT NULL
              AND s.industry_sw1 NOT IN %s
              AND s.list_status = 'L'
        ),
        latest AS (
            SELECT code, report_date, gross_profit_margin,
                   ROW_NUMBER() OVER (
                       PARTITION BY code
                       ORDER BY report_date DESC
                   ) AS rn2
            FROM ranked
            WHERE rn = 1
        )
        SELECT code, gross_profit_margin
        FROM latest
        WHERE rn2 = 1""",
        conn,
        params=(trade_date, EXCLUDE_INDUSTRIES),
    )
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("code")["gross_profit_margin"].astype(float)


def load_forward_return(trade_date: date, forward_days: int, conn) -> pd.Series:
    """计算trade_date起forward_days日的超额收益(vs CSI300)。

    超额收益 = 个股收益 - CSI300收益
    使用close价格（已有adj逻辑在klines_daily中）。
    """
    # 获取trade_date之后的交易日
    dates_df = pd.read_sql(
        """SELECT DISTINCT trade_date FROM klines_daily
           WHERE trade_date >= %s
           ORDER BY trade_date
           LIMIT %s""",
        conn,
        params=(trade_date, forward_days + 1),
    )
    if len(dates_df) < forward_days + 1:
        return pd.Series(dtype=float)

    t0 = dates_df.iloc[0]["trade_date"]
    t1 = dates_df.iloc[forward_days]["trade_date"]

    # 个股收益
    stock_ret = pd.read_sql(
        """SELECT a.code,
                  (b.close - a.close) / NULLIF(a.close, 0) AS ret
           FROM klines_daily a
           JOIN klines_daily b ON a.code = b.code AND b.trade_date = %s
           WHERE a.trade_date = %s
             AND a.volume > 0
             AND b.volume > 0""",
        conn,
        params=(t1, t0),
    )

    # CSI300收益
    bench = pd.read_sql(
        """SELECT close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date IN (%s, %s)
           ORDER BY trade_date""",
        conn,
        params=(t0, t1),
    )
    if len(bench) < 2:
        return pd.Series(dtype=float)

    bench_ret = (bench.iloc[1]["close"] - bench.iloc[0]["close"]) / bench.iloc[0]["close"]

    # 超额收益
    stock_ret["excess_ret"] = stock_ret["ret"].astype(float) - float(bench_ret)
    return stock_ret.set_index("code")["excess_ret"].dropna()


def load_existing_factors(trade_date: date, conn) -> pd.DataFrame:
    """加载现有因子的neutral_value，用于相关性分析。"""
    df = pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND neutral_value IS NOT NULL""",
        conn,
        params=(trade_date,),
    )
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="code", columns="factor_name", values="neutral_value")


def compute_spearman_ic(factor: pd.Series, forward_ret: pd.Series) -> float | None:
    """计算截面Spearman Rank IC。"""
    common = factor.index.intersection(forward_ret.index)
    if len(common) < 30:  # 最少30只股票
        return None
    f = factor.loc[common].astype(float)
    r = forward_ret.loc[common].astype(float)
    # 去NaN
    mask = f.notna() & r.notna()
    if mask.sum() < 30:
        return None
    corr, _ = stats.spearmanr(f[mask], r[mask])
    return corr


def main():
    conn = _get_sync_conn()

    print("=" * 70)
    print("GPA因子(gross_profit_margin proxy) IC分析")
    print(f"期间: {START_DATE} ~ {END_DATE}")
    print(f"Forward return: {FORWARD_DAYS}日超额收益(vs CSI300)")
    print(f"排除行业: {EXCLUDE_INDUSTRIES}")
    print(f"IC Gate阈值: {IC_GATE}")
    print("=" * 70)

    # 1. 获取月度截面日
    monthly_dates = load_monthly_trade_dates(conn)
    print(f"\n月度截面日: {len(monthly_dates)}个")

    # 2. 逐月计算IC
    ic_records = []
    for td in monthly_dates:
        factor = load_gpa_pit(td, conn)
        if factor.empty:
            continue

        fwd_ret = load_forward_return(td, FORWARD_DAYS, conn)
        if fwd_ret.empty:
            continue

        ic = compute_spearman_ic(factor, fwd_ret)
        if ic is not None:
            ic_records.append({
                "trade_date": td,
                "year": td.year,
                "month": td.month,
                "ic": ic,
                "n_stocks": len(factor.index.intersection(fwd_ret.index)),
            })

    if not ic_records:
        print("ERROR: 无有效IC记录!")
        conn.close()
        return

    ic_df = pd.DataFrame(ic_records)
    print(f"有效IC月份: {len(ic_df)}个")
    print(f"平均截面股票数: {ic_df['n_stocks'].mean():.0f}")

    # 3. 年度IC统计
    print("\n" + "=" * 70)
    print("年度IC统计")
    print("=" * 70)
    print(f"{'年份':>6s}  {'IC均值':>8s}  {'IC标准差':>8s}  {'IC_IR':>8s}  {'正IC占比':>8s}  {'月数':>4s}")
    print("-" * 50)

    yearly = ic_df.groupby("year").agg(
        ic_mean=("ic", "mean"),
        ic_std=("ic", "std"),
        ic_positive=("ic", lambda x: (x > 0).mean()),
        count=("ic", "count"),
    )
    yearly["ic_ir"] = yearly["ic_mean"] / yearly["ic_std"]

    for year, row in yearly.iterrows():
        print(
            f"{year:>6d}  {row['ic_mean']:>8.4f}  {row['ic_std']:>8.4f}  "
            f"{row['ic_ir']:>8.4f}  {row['ic_positive']:>7.1%}  {int(row['count']):>4d}"
        )

    # 4. 全期统计
    print("\n" + "=" * 70)
    print("全期IC统计")
    print("=" * 70)
    ic_values = ic_df["ic"].values
    ic_mean = np.mean(ic_values)
    ic_std = np.std(ic_values, ddof=1)
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_values)))
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(ic_values) - 1))
    positive_ratio = (ic_values > 0).mean()

    print(f"IC均值:       {ic_mean:.4f}")
    print(f"IC标准差:     {ic_std:.4f}")
    print(f"IC_IR:        {ic_ir:.4f}")
    print(f"t统计量:      {t_stat:.4f}")
    print(f"p值:          {p_value:.4f}")
    print(f"正IC占比:     {positive_ratio:.1%}")
    print(f"样本量:       {len(ic_values)}个月")

    # 5. IC Gate判定
    print("\n" + "=" * 70)
    gate_pass = abs(ic_mean) > IC_GATE
    significance = p_value < 0.05
    print(f"IC Gate (|IC| > {IC_GATE}):  {'PASS' if gate_pass else 'FAIL'}  (IC={ic_mean:.4f})")
    print(f"统计显著性 (p < 0.05):       {'PASS' if significance else 'FAIL'}  (p={p_value:.4f})")
    print(f"综合判定:                    {'PASS - 建议纳入候选因子池' if (gate_pass and significance) else 'FAIL - 不建议纳入' if not gate_pass else 'MARGINAL - IC通过但显著性不足'}")

    # 6. 与现有因子的相关性
    print("\n" + "=" * 70)
    print("与现有因子的相关性分析")
    print("=" * 70)

    # 选取一个中间日期的截面做相关性
    mid_dates = [d for d in monthly_dates if d.year in (2022, 2023)]
    if len(mid_dates) >= 6:
        sample_dates = mid_dates[::len(mid_dates) // 6][:6]
    else:
        sample_dates = mid_dates[:6]

    corr_records = []
    for td in sample_dates:
        gpa = load_gpa_pit(td, conn)
        existing = load_existing_factors(td, conn)
        if gpa.empty or existing.empty:
            continue

        common = gpa.index.intersection(existing.index)
        if len(common) < 50:
            continue

        for col in existing.columns:
            vals = existing.loc[common, col].astype(float)
            mask = gpa.loc[common].notna() & vals.notna()
            if mask.sum() < 30:
                continue
            corr, _ = stats.spearmanr(gpa.loc[common][mask], vals[mask])
            corr_records.append({"factor": col, "corr": corr})

    if corr_records:
        corr_df = pd.DataFrame(corr_records)
        avg_corr = corr_df.groupby("factor")["corr"].mean().sort_values(ascending=False)

        # 只展示主要因子（选5个代表性的）
        key_factors = ["ep_ratio", "bp_ratio", "ln_market_cap", "momentum_20", "volatility_20",
                       "turnover_mean_20", "reversal_20", "amihud_20"]
        print(f"{'因子':>20s}  {'平均Spearman相关':>15s}  {'正交性判定':>10s}")
        print("-" * 55)
        for factor in key_factors:
            if factor in avg_corr.index:
                c = avg_corr[factor]
                orth = "OK" if abs(c) < 0.5 else "HIGH"
                print(f"{factor:>20s}  {c:>15.4f}  {orth:>10s}")

        max_corr_factor = avg_corr.abs().idxmax()
        max_corr_val = avg_corr.abs().max()
        print(f"\n最大相关性: |corr({max_corr_factor})| = {max_corr_val:.4f}")
        if max_corr_val < 0.5:
            print("正交性判定: PASS (与所有现有因子相关性 < 0.5)")
        else:
            print(f"正交性判定: WARNING (与{max_corr_factor}相关性 >= 0.5)")
    else:
        print("(无法计算相关性，现有因子数据不足)")

    # 7. 月度IC明细
    print("\n" + "=" * 70)
    print("月度IC明细")
    print("=" * 70)
    print(f"{'日期':>12s}  {'IC':>8s}  {'股票数':>6s}")
    print("-" * 30)
    for _, row in ic_df.iterrows():
        marker = " *" if abs(row["ic"]) > 0.05 else ""
        print(f"{row['trade_date']}  {row['ic']:>8.4f}  {int(row['n_stocks']):>6d}{marker}")

    conn.close()
    print("\n分析完成。")


if __name__ == "__main__":
    main()
