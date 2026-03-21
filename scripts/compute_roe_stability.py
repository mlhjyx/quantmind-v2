#!/usr/bin/env python3
"""roe_stability因子: 近4个季度ROE的标准差（越小=盈利越稳定）。

PIT (Point-in-Time) 对齐逻辑:
- 使用actual_ann_date确保在每个交易日只用当时已公告的财报
- 对每只股票，取截至该交易日已公告的最近4个季度ROE，计算std
- 方向: -1（低std跑赢高std）

用法:
    python scripts/compute_roe_stability.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn

FACTOR_NAME = "roe_stability"
FACTOR_DIRECTION = -1  # 低std跑赢高std
MIN_QUARTERS = 4
IC_HORIZON = 5  # 5日forward excess return


def load_roe_data(conn) -> pd.DataFrame:
    """加载全量ROE财务数据（含actual_ann_date做PIT对齐）。"""
    df = pd.read_sql(
        """SELECT code, report_date, actual_ann_date, roe
           FROM financial_indicators
           WHERE roe IS NOT NULL AND actual_ann_date IS NOT NULL
           ORDER BY code, report_date""",
        conn,
    )
    df["roe"] = df["roe"].astype(float)
    df["report_date"] = pd.to_datetime(df["report_date"])
    df["actual_ann_date"] = pd.to_datetime(df["actual_ann_date"]).dt.date
    print(f"  加载ROE数据: {len(df):,}行, {df['code'].nunique():,}只股票")
    return df


def compute_roe_stability_pit(roe_data: pd.DataFrame, eval_date: date) -> pd.Series:
    """PIT对齐: 在eval_date这天，每只股票用已公告的最近4季ROE算std。

    Args:
        roe_data: 全量ROE数据
        eval_date: 评估日期（交易日）

    Returns:
        pd.Series indexed by code, values = roe_std (NaN if <4期)
    """
    # 只用eval_date之前已公告的数据（PIT严格对齐）
    available = roe_data[roe_data["actual_ann_date"] <= eval_date].copy()

    if available.empty:
        return pd.Series(dtype=float)

    # 每只股票取最近4个report_date的ROE（去重：同一report_date取最新公告的）
    # 先按actual_ann_date降序排，同一report_date取最晚公告的值
    available = available.sort_values(["code", "report_date", "actual_ann_date"])
    available = available.drop_duplicates(subset=["code", "report_date"], keep="last")

    results = {}
    for code, grp in available.groupby("code"):
        # 取最近4个季度
        recent = grp.nlargest(MIN_QUARTERS, "report_date")
        if len(recent) < MIN_QUARTERS:
            continue  # 不足4期设为NaN（跳过）
        roe_std = recent["roe"].std(ddof=1)
        if np.isfinite(roe_std):
            results[code] = roe_std

    return pd.Series(results, name=FACTOR_NAME)


def get_month_end_trade_dates(conn, start: str = "2021-01-01", end: str = "2025-12-31") -> list:
    """获取每月最后一个交易日列表。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= %s AND trade_date <= %s
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC""",
        (start, end),
    )
    dates = sorted([r[0] for r in cur.fetchall()])
    return dates


def load_forward_returns(trade_dates: list, horizon: int, conn) -> pd.DataFrame:
    """加载forward excess return（超额CSI300）。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 3)

    prices = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s AND k.volume > 0""",
        conn,
        params=(min_date, max_date),
    )
    prices = prices.pivot(index="trade_date", columns="code", values="adj_close")

    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(min_date, max_date),
    )
    bench = bench.set_index("trade_date")["close"]

    all_dates = sorted(prices.index)
    results = []
    for td in trade_dates:
        if td not in prices.index:
            continue
        future = [d for d in all_dates if d > td]
        if len(future) < horizon:
            continue
        fwd_date = future[horizon - 1]

        stock_ret = prices.loc[fwd_date] / prices.loc[td] - 1
        bench_ret = (
            bench.loc[fwd_date] / bench.loc[td] - 1
            if td in bench.index and fwd_date in bench.index
            else 0
        )
        excess = stock_ret - bench_ret
        excess.name = td
        results.append(excess)

    if results:
        return pd.DataFrame(results)
    return pd.DataFrame()


def main():
    conn = _get_sync_conn()

    # 1. 加载ROE数据
    print("[1] 加载ROE数据...")
    roe_data = load_roe_data(conn)

    # 2. 获取分析日期
    analysis_dates = get_month_end_trade_dates(conn)
    print(f"[2] 分析日期: {len(analysis_dates)}个月 ({analysis_dates[0]} ~ {analysis_dates[-1]})")

    # 3. 逐月计算roe_stability因子
    print(f"\n[3] 计算{FACTOR_NAME}因子 (PIT对齐, 滚动{MIN_QUARTERS}期std)...")
    all_factor = []
    for i, td in enumerate(analysis_dates):
        if (i + 1) % 12 == 0 or i == 0:
            print(f"  {i+1}/{len(analysis_dates)} ({td})", flush=True)
        factor_vals = compute_roe_stability_pit(roe_data, td)
        if not factor_vals.empty:
            df = factor_vals.reset_index()
            df.columns = ["code", "raw_value"]
            df["trade_date"] = td
            df["factor_name"] = FACTOR_NAME
            all_factor.append(df)

    if not all_factor:
        print("ERROR: 无因子数据生成")
        conn.close()
        return

    factor_df = pd.concat(all_factor, ignore_index=True)
    print(f"  因子值: {len(factor_df):,}行, {factor_df['trade_date'].nunique()}个月, "
          f"{factor_df['code'].nunique():,}只股票")

    # 因子分布统计
    print(f"\n  因子分布: mean={factor_df['raw_value'].mean():.4f}, "
          f"median={factor_df['raw_value'].median():.4f}, "
          f"std={factor_df['raw_value'].std():.4f}, "
          f"p5={factor_df['raw_value'].quantile(0.05):.4f}, "
          f"p95={factor_df['raw_value'].quantile(0.95):.4f}")

    # 4. 计算IC
    print(f"\n[4] 计算IC ({IC_HORIZON}日forward excess return)...")
    fwd_rets = load_forward_returns(analysis_dates, horizon=IC_HORIZON, conn=conn)
    print(f"  Forward returns: {fwd_rets.shape}")

    ics = []
    for td in fwd_rets.index:
        fv = factor_df[factor_df["trade_date"] == td].set_index("code")["raw_value"]
        fr = fwd_rets.loc[td].dropna()
        common = fv.index.intersection(fr.index)
        if len(common) < 50:
            continue
        ic, _ = stats.spearmanr(fv[common], fr[common])
        if np.isfinite(ic):
            ics.append({"date": td, "ic": ic})

    if not ics:
        print("ERROR: 无有效IC")
        conn.close()
        return

    ic_df = pd.DataFrame(ics)
    # 方向调整: direction=-1表示原始IC应为负（低std跑赢），调整后为正
    ic_vals = ic_df["ic"].values * FACTOR_DIRECTION

    print(f"\n{'='*60}")
    print(f"  {FACTOR_NAME} IC统计 (方向={FACTOR_DIRECTION}, {IC_HORIZON}日超额)")
    print(f"{'='*60}")
    print(f"  IC均值:  {np.mean(ic_vals):+.4f}")
    print(f"  IC标准差: {np.std(ic_vals):.4f}")
    print(f"  IC_IR:   {np.mean(ic_vals)/np.std(ic_vals):+.3f}" if np.std(ic_vals) > 0 else "  IC_IR:   N/A")
    print(f"  命中率:  {np.mean(ic_vals > 0):.1%}")
    print(f"  有效月数: {len(ics)}")

    # 5. 年度IC分解
    print(f"\n[5] 年度IC分解:")
    ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
    print(f"  {'年份':>6} {'IC均值':>8} {'IC_IR':>7} {'命中率':>6} {'月数':>4}")
    print(f"  {'-'*35}")
    for year, grp in ic_df.groupby("year"):
        vals = grp["ic"].values * FACTOR_DIRECTION
        ir = np.mean(vals) / np.std(vals) if np.std(vals) > 0 else 0
        print(f"  {year:>6} {np.mean(vals):>+.4f} {ir:>+.3f} {np.mean(vals>0):>5.0%} {len(vals):>4}")

    # 6. 与现有因子的截面相关性
    print(f"\n[6] 与现有因子的截面相关性 (最近20个月平均)...")
    existing_factors = [
        "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"
    ]
    sample_dates = sorted(analysis_dates)[-20:]
    existing_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s
             AND trade_date IN %s""",
        conn,
        params=(tuple(existing_factors), tuple(sample_dates)),
    )

    if not existing_df.empty:
        corrs_by_factor = {ef: [] for ef in existing_factors}
        for td in sample_dates:
            fv = factor_df[factor_df["trade_date"] == td].set_index("code")["raw_value"]
            for ef in existing_factors:
                ev = existing_df[
                    (existing_df["trade_date"] == td) & (existing_df["factor_name"] == ef)
                ].set_index("code")["zscore"]
                common = fv.index.intersection(ev.index)
                if len(common) >= 100:
                    c, _ = stats.spearmanr(fv[common].astype(float), ev[common].astype(float))
                    if np.isfinite(c):
                        corrs_by_factor[ef].append(c)

        print(f"  {'因子':>20} {'平均相关性':>10} {'样本月数':>8}")
        print(f"  {'-'*40}")
        for ef in existing_factors:
            if corrs_by_factor[ef]:
                avg_corr = np.mean(corrs_by_factor[ef])
                flag = " *** HIGH" if abs(avg_corr) > 0.5 else ""
                print(f"  {ef:>20} {avg_corr:>+.4f} {len(corrs_by_factor[ef]):>8}{flag}")
            else:
                print(f"  {ef:>20} {'N/A':>10}")

    # 7. Gate check
    ic_mean = np.mean(ic_vals)
    print(f"\n{'='*60}")
    print(f"Gate Check: IC > 1.5%  =>  |{ic_mean:.4f}| > 0.015 = {'PASS' if abs(ic_mean) > 0.015 else 'FAIL'}")
    print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
