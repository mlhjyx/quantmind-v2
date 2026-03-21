#!/usr/bin/env python3
"""Route C: 财务质量因子IC分析。

对3个候选因子做:
1. 截面IC计算（Spearman rank correlation with forward return）
2. IC时间序列统计（mean, std, IR, hit rate）
3. 与现有5因子的相关性分析
4. 加入组合后的回测对比

用法:
    python scripts/analyze_financial_factors.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn
from engines.financial_factors import (
    compute_financial_factors,
    FINANCIAL_FACTOR_DIRECTION,
)


def load_forward_returns(trade_dates: list, horizon: int, conn) -> pd.DataFrame:
    """加载forward excess return（超额CSI300）。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 2)

    # 加载价格
    prices = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s AND k.volume > 0""",
        conn,
        params=(min_date, max_date),
    )
    prices = prices.pivot(index="trade_date", columns="code", values="adj_close")

    # 基准
    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(min_date, max_date),
    )
    bench = bench.set_index("trade_date")["close"]

    # 计算forward return
    all_dates = sorted(prices.index)
    results = []
    for td in trade_dates:
        if td not in prices.index:
            continue
        # 找horizon天后的日期
        future = [d for d in all_dates if d > td]
        if len(future) < horizon:
            continue
        fwd_date = future[horizon - 1]

        stock_ret = (prices.loc[fwd_date] / prices.loc[td] - 1)
        bench_ret = bench.loc[fwd_date] / bench.loc[td] - 1 if td in bench.index and fwd_date in bench.index else 0

        excess = stock_ret - bench_ret
        excess.name = td
        results.append(excess)

    if results:
        return pd.DataFrame(results)
    return pd.DataFrame()


def calc_ic_series(factor_df: pd.DataFrame, fwd_returns: pd.DataFrame) -> dict:
    """计算因子IC时间序列。"""
    ic_results = {}

    for fname in factor_df["factor_name"].unique():
        ics = []
        for td in fwd_returns.index:
            # 取当日因子值
            fv = factor_df[(factor_df["trade_date"] == td) & (factor_df["factor_name"] == fname)]
            if fv.empty:
                continue
            fv = fv.set_index("code")["raw_value"]

            # 取forward return
            fr = fwd_returns.loc[td].dropna()

            # 交集
            common = fv.index.intersection(fr.index)
            if len(common) < 50:
                continue

            ic, _ = stats.spearmanr(fv[common], fr[common])
            if np.isfinite(ic):
                ics.append({"date": td, "ic": ic})

        if ics:
            ic_df = pd.DataFrame(ics)
            direction = FINANCIAL_FACTOR_DIRECTION.get(fname, 1)
            ic_vals = ic_df["ic"].values * direction  # 方向调整

            ic_results[fname] = {
                "n_dates": len(ics),
                "ic_mean": float(np.mean(ic_vals)),
                "ic_std": float(np.std(ic_vals)),
                "ic_ir": float(np.mean(ic_vals) / np.std(ic_vals)) if np.std(ic_vals) > 0 else 0,
                "hit_rate": float(np.mean(ic_vals > 0)),
                "ic_series": ic_df,
            }
        else:
            ic_results[fname] = {"n_dates": 0, "ic_mean": 0, "ic_std": 0, "ic_ir": 0, "hit_rate": 0}

    return ic_results


def calc_factor_correlations(factor_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """计算新因子与现有5因子的截面相关性。"""
    # 取一个日期做截面相关
    dates = factor_df["trade_date"].unique()
    if len(dates) == 0:
        return pd.DataFrame()

    # 用最近20个日期的平均相关性
    sample_dates = sorted(dates)[-20:]
    all_corrs = []

    for td in sample_dates:
        new_fv = factor_df[factor_df["trade_date"] == td].pivot(
            index="code", columns="factor_name", values="raw_value"
        )
        old_fv = existing_df[existing_df["trade_date"] == td].pivot(
            index="code", columns="factor_name", values="zscore"
        )

        if new_fv.empty or old_fv.empty:
            continue

        common = new_fv.index.intersection(old_fv.index)
        if len(common) < 100:
            continue

        combined = pd.concat([new_fv.loc[common], old_fv.loc[common]], axis=1)
        corr = combined.corr(method="spearman")
        all_corrs.append(corr)

    if all_corrs:
        return sum(all_corrs) / len(all_corrs)
    return pd.DataFrame()


def main():
    conn = _get_sync_conn()

    # 检查数据量
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM financial_indicators")
    n_fina = cur.fetchone()[0]
    print(f"financial_indicators: {n_fina:,}行")

    if n_fina < 10000:
        print("⚠ 数据量不足，请等待pull_financial_data.py完成")
        conn.close()
        return

    # 选取分析日期: 每月最后一个交易日 (2021-2025)
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= '2021-01-01' AND trade_date <= '2025-12-31'
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC"""
    )
    analysis_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"分析日期: {len(analysis_dates)}个月 ({analysis_dates[0]} ~ {analysis_dates[-1]})")

    # 1. 计算因子值
    print("\n[1] 计算财务因子...")
    all_factor_rows = []
    for i, td in enumerate(analysis_dates):
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(analysis_dates)}", flush=True)
        fdf = compute_financial_factors(td, conn)
        if not fdf.empty:
            fdf["trade_date"] = td
            all_factor_rows.append(fdf)

    if not all_factor_rows:
        print("⚠ 无因子数据生成")
        conn.close()
        return

    factor_df = pd.concat(all_factor_rows, ignore_index=True)
    print(f"  因子值: {len(factor_df):,}行, {factor_df['factor_name'].nunique()}个因子")

    for fname in factor_df["factor_name"].unique():
        n = len(factor_df[factor_df["factor_name"] == fname])
        n_dates = factor_df[factor_df["factor_name"] == fname]["trade_date"].nunique()
        print(f"    {fname}: {n:,}条 × {n_dates}日")

    # 2. 计算Forward Returns (20-day excess)
    print("\n[2] 计算Forward Returns (20日超额)...")
    fwd_rets = load_forward_returns(analysis_dates, horizon=20, conn=conn)
    print(f"  Forward returns: {fwd_rets.shape}")

    # 3. IC分析
    print("\n[3] IC分析...")
    ic_results = calc_ic_series(factor_df, fwd_rets)

    print(f"\n{'因子':>20} {'IC均值':>8} {'IC_IR':>7} {'命中率':>6} {'日期数':>5}")
    print("-" * 55)
    for fname, res in ic_results.items():
        direction = FINANCIAL_FACTOR_DIRECTION.get(fname, 1)
        dir_str = "(+)" if direction > 0 else "(-)"
        print(
            f"{fname:>20} {dir_str} "
            f"{res['ic_mean']:>+.4f} "
            f"{res['ic_ir']:>+.3f} "
            f"{res['hit_rate']:>5.1%} "
            f"{res['n_dates']:>5}"
        )

    # 4. 与现有因子的相关性
    print("\n[4] 与现有5因子的截面相关性...")
    existing_factors = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    existing_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s
             AND trade_date IN %s""",
        conn,
        params=(tuple(existing_factors), tuple(analysis_dates[-20:])),
    )

    if not existing_df.empty:
        corr_matrix = calc_factor_correlations(factor_df, existing_df)
        if not corr_matrix.empty:
            new_factors = list(FINANCIAL_FACTOR_DIRECTION.keys())
            print(f"\n{'':>20}", end="")
            for ef in existing_factors:
                print(f" {ef[:12]:>12}", end="")
            print()
            for nf in new_factors:
                if nf in corr_matrix.index:
                    print(f"{nf:>20}", end="")
                    for ef in existing_factors:
                        if ef in corr_matrix.columns:
                            v = corr_matrix.loc[nf, ef]
                            print(f" {v:>+11.3f}", end="")
                        else:
                            print(f" {'N/A':>12}", end="")
                    print()

    # 5. 年度IC分解
    print("\n[5] 年度IC分解:")
    for fname, res in ic_results.items():
        if res["n_dates"] == 0:
            continue
        ic_df = res["ic_series"]
        ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
        direction = FINANCIAL_FACTOR_DIRECTION.get(fname, 1)
        print(f"\n  {fname}:")
        for year, grp in ic_df.groupby("year"):
            vals = grp["ic"].values * direction
            print(f"    {year}: IC={np.mean(vals):+.4f} IR={np.mean(vals)/max(np.std(vals),1e-6):+.3f} "
                  f"hit={np.mean(vals>0):.0%} n={len(vals)}")

    # 6. Gate check
    print("\n\n" + "=" * 55)
    print("Gate Check (IC > 1.5%, corr < 0.5 with existing)")
    print("=" * 55)
    passed = []
    for fname, res in ic_results.items():
        ic_pass = abs(res["ic_mean"]) > 0.015
        # 检查与现有因子最大相关性
        max_corr = 0
        if not corr_matrix.empty and fname in corr_matrix.index:
            for ef in existing_factors:
                if ef in corr_matrix.columns:
                    max_corr = max(max_corr, abs(corr_matrix.loc[fname, ef]))
        corr_pass = max_corr < 0.5

        status = "✅ PASS" if (ic_pass and corr_pass) else "❌ FAIL"
        passed.append(ic_pass and corr_pass)
        print(f"  {fname:>20}: IC={res['ic_mean']:+.4f} (>1.5%={'✓' if ic_pass else '✗'}) "
              f"max_corr={max_corr:.3f} (<0.5={'✓' if corr_pass else '✗'}) → {status}")

    conn.close()

    if any(passed):
        print("\n💡 有因子通过Gate，建议纳入候选池做进一步回测。")
        print("   下一步: 加入组合回测，检查Sharpe是否提升。")
    else:
        print("\n⚠ 无因子通过Gate，建议调整因子定义或寻找新方向。")


if __name__ == "__main__":
    main()
