#!/usr/bin/env python3
"""bp_ratio因子分年IC评估脚本。

研究目标:
  - bp_ratio全期IC=2.64%，但需检查分年稳定性
  - 每月末截面计算Spearman IC (vs 5日超额收益)
  - 分年输出IC均值/标准差/IR/正IC占比
  - 判断价值因子在A股是否稳定

用法:
    python scripts/analyze_bp_ratio_yearly_ic.py
"""

import sys
from datetime import date
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
FACTOR_NAME = "bp_ratio"
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
    monthly = dates.groupby(dates.dt.to_period("M")).max()
    return [d.date() for d in monthly]


def load_factor(trade_date: date, conn) -> pd.Series:
    """加载bp_ratio的neutral_value（已中性化）。"""
    df = pd.read_sql(
        """SELECT code, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name = %s
             AND neutral_value IS NOT NULL""",
        conn,
        params=(trade_date, FACTOR_NAME),
    )
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("code")["neutral_value"].astype(float)


def load_forward_return(trade_date: date, forward_days: int, conn) -> pd.Series:
    """计算trade_date起forward_days日的超额收益(vs CSI300)。"""
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
    stock_ret["excess_ret"] = stock_ret["ret"].astype(float) - float(bench_ret)
    return stock_ret.set_index("code")["excess_ret"].dropna()


def compute_spearman_ic(factor: pd.Series, forward_ret: pd.Series) -> float | None:
    """计算截面Spearman Rank IC。"""
    common = factor.index.intersection(forward_ret.index)
    if len(common) < 30:
        return None
    f = factor.loc[common].astype(float)
    r = forward_ret.loc[common].astype(float)
    mask = f.notna() & r.notna()
    if mask.sum() < 30:
        return None
    corr, _ = stats.spearmanr(f[mask], r[mask])
    return corr


def main():
    conn = _get_sync_conn()

    print("=" * 70)
    print(f"{FACTOR_NAME} 分年IC稳定性评估")
    print(f"期间: {START_DATE} ~ {END_DATE}")
    print(f"Forward return: {FORWARD_DAYS}日超额收益(vs CSI300)")
    print("=" * 70)

    monthly_dates = load_monthly_trade_dates(conn)
    print(f"\n月度截面日: {len(monthly_dates)}个")

    ic_records = []
    for td in monthly_dates:
        factor = load_factor(td, conn)
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

    # ---- 分年IC统计 ----
    print("\n" + "=" * 70)
    print("分年IC统计")
    print("=" * 70)
    print(f"{'年份':>6s}  {'IC均值':>8s}  {'IC标准差':>8s}  {'IC_IR':>8s}  {'正IC占比':>8s}  {'t值':>8s}  {'月数':>4s}  {'判定':>8s}")
    print("-" * 75)

    yearly = ic_df.groupby("year").agg(
        ic_mean=("ic", "mean"),
        ic_std=("ic", "std"),
        ic_positive=("ic", lambda x: (x > 0).mean()),
        count=("ic", "count"),
    )
    yearly["ic_ir"] = yearly["ic_mean"] / yearly["ic_std"]
    yearly["t_stat"] = yearly["ic_mean"] / (yearly["ic_std"] / np.sqrt(yearly["count"]))

    for year, row in yearly.iterrows():
        # 判定: IC>0.02且正IC>50%为GOOD, IC<0为BAD, 其余WEAK
        if row["ic_mean"] > 0.02 and row["ic_positive"] > 0.5:
            verdict = "GOOD"
        elif row["ic_mean"] < 0:
            verdict = "BAD"
        else:
            verdict = "WEAK"
        print(
            f"{year:>6d}  {row['ic_mean']:>8.4f}  {row['ic_std']:>8.4f}  "
            f"{row['ic_ir']:>8.4f}  {row['ic_positive']:>7.1%}  "
            f"{row['t_stat']:>8.4f}  {int(row['count']):>4d}  {verdict:>8s}"
        )

    # ---- 全期统计 ----
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

    # ---- 半年滚动IC ----
    print("\n" + "=" * 70)
    print("半年滚动IC (6个月窗口)")
    print("=" * 70)
    if len(ic_df) >= 6:
        rolling_ic = ic_df["ic"].rolling(6).mean()
        for i in range(5, len(ic_df)):
            td = ic_df.iloc[i]["trade_date"]
            ric = rolling_ic.iloc[i]
            bar = "+" * max(0, int(ric * 200)) + "-" * max(0, int(-ric * 200))
            print(f"{td}  {ric:>8.4f}  |{bar}")

    # ---- 结论 ----
    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)

    bad_years = [y for y, r in yearly.iterrows() if r["ic_mean"] < 0]
    weak_years = [y for y, r in yearly.iterrows() if 0 <= r["ic_mean"] < 0.02]
    good_years = [y for y, r in yearly.iterrows() if r["ic_mean"] >= 0.02]

    print(f"GOOD年份 (IC>2%): {good_years}")
    print(f"WEAK年份 (0<IC<2%): {weak_years}")
    print(f"BAD年份 (IC<0): {bad_years}")

    if len(bad_years) >= 2:
        print("\n>>> WARNING: 多个年份IC为负，bp_ratio在A股不稳定，建议降权或替换")
    elif len(bad_years) == 1:
        print(f"\n>>> CAUTION: {bad_years[0]}年IC为负，可能与市场风格有关，建议保留但降权")
    else:
        print("\n>>> OK: 所有年份IC均为正，bp_ratio表现稳定")

    conn.close()
    print("\n分析完成。")


if __name__ == "__main__":
    main()
