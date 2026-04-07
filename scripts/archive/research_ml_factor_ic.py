#!/usr/bin/env python3
"""子任务1: 12个ML因子 + reversal_60孤儿 + 8个Deprecated 批量IC测试。

对每个因子计算:
1. 截面Rank IC (Spearman, vs next-month excess return over CSI300)
2. IC_IR (IC均值/IC标准差)
3. 分年度IC (2021-2025)
4. 与5个Active因子的截面Spearman相关性
5. 推荐动作
"""

import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ACTIVE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

# 12 ML + reversal_60 孤儿 + 8 Deprecated = 21个待测因子
TEST_FACTORS = [
    # 12 ML factors (DB有数据但未独立测试)
    "kbar_kmid", "kbar_ksft", "kbar_kup", "maxret_20", "chmom_60_20",
    "up_days_ratio_20", "stoch_rsv_20", "gain_loss_ratio_20",
    "large_order_ratio", "money_flow_strength", "beta_market_20",
    # 孤儿
    "reversal_60",
    # 8 Deprecated (验证弃用原因)
    "momentum_5", "momentum_10", "momentum_20", "volatility_60",
    "volume_std_20", "turnover_std_20", "high_low_range_20", "turnover_stability_20",
    # FULL池中IC强但未入Active的
    "mf_divergence", "ep_ratio", "price_volume_corr_20", "price_level_factor",
    "relative_volume_20", "dv_ttm", "turnover_surge_ratio", "ln_market_cap",
    "reversal_5", "reversal_10",
    # Reserve
    "vwap_bias_1d", "rsrs_raw_18",
]


def load_factor_monthly_ends(conn, factor_names: list) -> pd.DataFrame:
    """只加载每月最后一个交易日的因子值（大幅减少内存）。"""
    logger.info(f"加载{len(factor_names)}个因子的月末数据...")
    # 先获取每月最后交易日
    month_ends = pd.read_sql(
        """SELECT MAX(trade_date) as trade_date
           FROM klines_daily
           WHERE trade_date >= '2021-01-01' AND trade_date <= '2026-03-31'
             AND volume > 0
           GROUP BY DATE_TRUNC('month', trade_date)
           ORDER BY trade_date""",
        conn,
    )
    dates = month_ends["trade_date"].tolist()
    logger.info(f"月末交易日: {len(dates)}个")

    # 分批加载因子值
    chunks = []
    fn_str = ",".join(f"'{f}'" for f in factor_names)
    for d in dates:
        chunk = pd.read_sql(
            f"""SELECT code, trade_date, factor_name, neutral_value, raw_value
                FROM factor_values
                WHERE trade_date = %s AND factor_name IN ({fn_str})""",
            conn, params=(d,),
        )
        chunks.append(chunk)

    df = pd.concat(chunks, ignore_index=True)
    logger.info(f"加载完成: {len(df):,}行, {df['factor_name'].nunique()}因子, {df['trade_date'].nunique()}月")
    return df


def load_monthly_returns(conn, aligned_universe: bool = True) -> pd.DataFrame:
    """计算月度超额收益(vs CSI300)。

    Args:
        aligned_universe: True=与回测一致(排除ST/新股/市值<10亿), False=全量
    """
    logger.info(f"计算月度超额收益... (aligned_universe={aligned_universe})")
    if aligned_universe:
        prices = pd.read_sql(
            """SELECT k.code, k.trade_date, k.close
               FROM klines_daily k
               JOIN symbols s ON k.code = s.code
               LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
               WHERE k.trade_date >= '2021-01-01' AND k.trade_date <= '2026-03-31'
                 AND k.volume > 0
                 AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'
                 AND (s.list_date IS NULL OR s.list_date <= k.trade_date - INTERVAL '60 days')
                 AND COALESCE(db.total_mv, 0) > 100000
               ORDER BY k.code, k.trade_date""",
            conn,
        )
    else:
        prices = pd.read_sql(
            """SELECT code, trade_date, close
               FROM klines_daily
               WHERE trade_date >= '2021-01-01' AND trade_date <= '2026-03-31'
                 AND volume > 0
               ORDER BY code, trade_date""",
            conn,
        )
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["ym"] = prices["trade_date"].dt.to_period("M")

    # 月末收盘价
    month_end = prices.groupby(["code", "ym"]).last().reset_index()
    month_end["next_close"] = month_end.groupby("code")["close"].shift(-1)
    month_end["fwd_ret"] = month_end["next_close"] / month_end["close"] - 1
    month_end = month_end.dropna(subset=["fwd_ret"])

    # CSI300月度收益
    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= '2021-01-01' AND trade_date <= '2026-03-31'
           ORDER BY trade_date""",
        conn,
    )
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench["ym"] = bench["trade_date"].dt.to_period("M")
    bench_monthly = bench.groupby("ym")["close"].last()
    bench_ret = bench_monthly.pct_change().rename("bench_ret")

    # 合并
    month_end = month_end.merge(bench_ret, left_on="ym", right_index=True, how="left")
    month_end["excess_ret"] = month_end["fwd_ret"] - month_end["bench_ret"].fillna(0)

    return month_end[["code", "ym", "trade_date", "fwd_ret", "excess_ret"]]


def compute_monthly_ic(factor_df: pd.DataFrame, returns_df: pd.DataFrame,
                       factor_name: str, value_col: str = "neutral_value") -> pd.DataFrame:
    """计算单个因子的月度截面IC序列。factor_df已是月末数据。"""
    fv = factor_df[factor_df["factor_name"] == factor_name][["code", "trade_date", value_col]].copy()
    if fv.empty:
        return pd.DataFrame()

    fv["trade_date"] = pd.to_datetime(fv["trade_date"])
    fv["ym"] = fv["trade_date"].dt.to_period("M")

    # 与下月收益合并
    merged = fv.merge(returns_df[["code", "ym", "excess_ret"]], on=["code", "ym"], how="inner")
    merged = merged.dropna(subset=[value_col, "excess_ret"])

    # 按月计算截面Spearman IC
    ic_list = []
    for ym, grp in merged.groupby("ym"):
        if len(grp) < 30:
            continue
        rho, _ = sp_stats.spearmanr(grp[value_col].values, grp["excess_ret"].values)
        if not np.isnan(rho):
            ic_list.append({"ym": ym, "ic": rho, "n_stocks": len(grp)})

    return pd.DataFrame(ic_list)


def compute_factor_correlations(factor_df: pd.DataFrame, factors_a: list, factors_b: list) -> pd.DataFrame:
    """计算因子间截面相关性矩阵。factor_df已是月末数据。"""
    all_factors = list(set(factors_a + factors_b))
    fv = factor_df[factor_df["factor_name"].isin(all_factors)].copy()
    fv["trade_date"] = pd.to_datetime(fv["trade_date"])

    # Pivot: (code, trade_date) × factor_name
    pivot = fv.pivot_table(index=["code", "trade_date"], columns="factor_name",
                           values="neutral_value", aggfunc="first")

    # 每月截面相关性
    corr_accum = {}
    for td in pivot.index.get_level_values("trade_date").unique():
        month_data = pivot.xs(td, level="trade_date")
        if len(month_data) < 30:
            continue
        for fa in factors_a:
            for fb in factors_b:
                if fa not in month_data.columns or fb not in month_data.columns:
                    continue
                valid = month_data[[fa, fb]].dropna()
                if len(valid) < 30:
                    continue
                rho, _ = sp_stats.spearmanr(valid[fa].values, valid[fb].values)
                if not np.isnan(rho):
                    key = (fa, fb)
                    if key not in corr_accum:
                        corr_accum[key] = []
                    corr_accum[key].append(rho)

    results = []
    for (fa, fb), vals in corr_accum.items():
        results.append({"factor_a": fa, "factor_b": fb, "mean_corr": np.mean(vals),
                         "std_corr": np.std(vals), "n_months": len(vals)})
    return pd.DataFrame(results)


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    # 1. 加载数据 (只加载月末数据,避免MemoryError)
    # aligned_universe=True: 与回测一致(排除ST/新股/市值<10亿)
    all_test = list(set(TEST_FACTORS + ACTIVE_FACTORS))
    factor_df = load_factor_monthly_ends(conn, all_test)
    returns_df = load_monthly_returns(conn, aligned_universe=True)
    logger.info(f"月度收益: {len(returns_df):,}行, {returns_df['ym'].nunique()}月")

    # 确认DB中实际有哪些待测因子
    available = set(factor_df["factor_name"].unique())
    test_factors = [f for f in TEST_FACTORS if f in available]
    missing = [f for f in TEST_FACTORS if f not in available]
    if missing:
        logger.warning(f"DB中缺失: {missing}")
    logger.info(f"待测因子: {len(test_factors)}个")

    # 2. 批量IC计算
    results = []
    for fn in test_factors:
        ic_df = compute_monthly_ic(factor_df, returns_df, fn)
        if ic_df.empty:
            results.append({"factor": fn, "ic_mean": np.nan, "ic_ir": np.nan, "n_months": 0})
            continue

        ic_mean = ic_df["ic"].mean()
        ic_std = ic_df["ic"].std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0

        # 分年度
        yearly = {}
        for yr in range(2021, 2027):
            yr_data = ic_df[ic_df["ym"].dt.year == yr]
            if not yr_data.empty:
                yearly[yr] = yr_data["ic"].mean()

        results.append({
            "factor": fn,
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ic_ir": ic_ir,
            "t_stat": t_stat,
            "n_months": len(ic_df),
            **{f"ic_{yr}": yearly.get(yr, np.nan) for yr in range(2021, 2027)},
        })

    results_df = pd.DataFrame(results).sort_values("ic_mean", key=abs, ascending=False)

    # 3. 相关性矩阵
    logger.info("计算因子相关性...")
    corr_df = compute_factor_correlations(factor_df, test_factors, ACTIVE_FACTORS)

    # 每个待测因子与Active的最大绝对相关性
    max_corr = {}
    for fn in test_factors:
        fn_corrs = corr_df[corr_df["factor_a"] == fn].copy()
        fn_corrs = fn_corrs.dropna(subset=["mean_corr"])
        if not fn_corrs.empty and len(fn_corrs) > 0:
            abs_corrs = fn_corrs["mean_corr"].abs()
            if abs_corrs.notna().any():
                idx = abs_corrs.idxmax()
                max_corr[fn] = float(abs_corrs.loc[idx])
                max_corr[fn + "_with"] = str(fn_corrs.loc[idx, "factor_b"])
            else:
                max_corr[fn] = np.nan
                max_corr[fn + "_with"] = ""
        else:
            max_corr[fn] = np.nan
            max_corr[fn + "_with"] = ""

    # 4. 输出报告
    print("\n" + "=" * 120)
    print("因子池扩展 — ML因子 + 孤儿 + Deprecated + FULL/Reserve 批量IC测试")
    print("=" * 120)
    print("数据范围: 2021-01 ~ 2026-03 | IC方法: 截面Spearman(neutral_value, next-month excess return)")
    print(f"测试因子: {len(test_factors)}个 | Active参照: {ACTIVE_FACTORS}")

    # Active参照
    print("\n--- Active因子参照 (factor_lifecycle) ---")
    for fn in ACTIVE_FACTORS:
        ic_df = compute_monthly_ic(factor_df, returns_df, fn)
        if not ic_df.empty:
            ic_m = ic_df["ic"].mean()
            ic_s = ic_df["ic"].std()
            ir = ic_m / ic_s if ic_s > 0 else 0
            t = ic_m / (ic_s / np.sqrt(len(ic_df))) if ic_s > 0 else 0
            print(f"  {fn:25s} IC={ic_m:+.4f}  IR={ir:+.3f}  t={t:+.2f}  n={len(ic_df)}")

    # 主表
    print("\n--- 批量IC测试结果 ---")
    header = f"{'因子':30s} {'IC_mean':>8} {'IC_IR':>7} {'t-stat':>7} {'月数':>5} {'2021':>7} {'2022':>7} {'2023':>7} {'2024':>7} {'2025':>7} {'maxCorr':>8} {'corrWith':>20} {'推荐':<15}"
    print(header)
    print("-" * len(header))

    for _, row in results_df.iterrows():
        fn = row["factor"]
        ic = row["ic_mean"]
        ir = row["ic_ir"]
        t = row.get("t_stat", 0)
        mc = max_corr.get(fn, np.nan)
        mcw = max_corr.get(fn + "_with", "")

        # 推荐动作
        if pd.isna(ic) or row["n_months"] == 0:
            action = "无数据"
        elif abs(ic) >= 0.02 and (pd.isna(mc) or mc < 0.7):
            action = "候选入池"
        elif abs(ic) >= 0.02 and mc >= 0.7:
            action = f"冗余({mcw})"
        elif abs(ic) >= 0.015:
            action = "边界观察"
        else:
            action = "确认弃用"

        yr_vals = " ".join(
            f"{row.get(f'ic_{yr}', np.nan):>+7.4f}" if not pd.isna(row.get(f"ic_{yr}", np.nan)) else f"{'N/A':>7}"
            for yr in range(2021, 2026)
        )
        mc_str = f"{mc:>+8.3f}" if not pd.isna(mc) else f"{'N/A':>8}"

        print(f"{fn:30s} {ic:>+8.4f} {ir:>+7.3f} {t:>+7.2f} {int(row['n_months']):>5} {yr_vals} {mc_str} {mcw:>20} {action:<15}")

    # 汇总
    candidates = results_df[(results_df["ic_mean"].abs() >= 0.02)].copy()
    candidates["max_corr"] = candidates["factor"].map(lambda f: max_corr.get(f, np.nan))
    independent = candidates[candidates["max_corr"].isna() | (candidates["max_corr"] < 0.7)]

    print("\n--- 汇总 ---")
    print(f"  测试因子总数: {len(test_factors)}")
    print(f"  |IC|>=0.02: {len(candidates)}")
    print(f"  |IC|>=0.02 且 max_corr<0.7: {len(independent)} (候选入池)")
    print(f"  |IC|<0.02: {len(results_df) - len(candidates)} (确认弃用/边界)")

    if not independent.empty:
        print("\n--- 候选入池因子 ---")
        for _, r in independent.iterrows():
            print(f"  {r['factor']:30s} IC={r['ic_mean']:+.4f}  IR={r['ic_ir']:+.3f}  maxCorr={r['max_corr']:.3f}" if not pd.isna(r["max_corr"]) else f"  {r['factor']:30s} IC={r['ic_mean']:+.4f}  IR={r['ic_ir']:+.3f}")

    # 写入文件
    Path(__file__).resolve().parent.parent / "FACTOR_IC_BATCH_REPORT.md"
    # Capture output by re-running print to string
    conn.close()
    elapsed = time.time() - t0
    logger.info(f"总耗时: {elapsed:.0f}s ({elapsed / 60:.1f}分钟)")


if __name__ == "__main__":
    main()
