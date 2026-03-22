#!/usr/bin/env python3
"""第5批因子补充(batch5b): 资金流深度因子IC分析

3个候选（补充资金流维度深度）:
  1. mf_persistence_20     — 20日内net_mf_amount>0的天数占比 (方向+1)
  2. big_small_divergence_20 — 大小单背离: rank(大单净买均值) - rank(小单净买均值) (方向+1)
  3. mf_volatility_20      — 资金流波动率: std(net_mf) / mean(|net_mf|) (方向-1)

所有金额单位: 万元 (moneyflow_daily.buy_*_amount/sell_*_amount/net_mf_amount)

用法:
    python scripts/compute_moneyflow_batch2_ic.py
"""

import functools
import sys
from datetime import date, timedelta
from pathlib import Path

# 强制flush输出
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn

# 因子方向定义
FACTOR_DIRECTION = {
    "mf_persistence_20": +1,
    "big_small_divergence_20": +1,
    "mf_volatility_20": -1,
}


def load_moneyflow_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载moneyflow_daily全量数据。"""
    df = pd.read_sql(
        """SELECT code, trade_date,
                  buy_sm_amount, sell_sm_amount,
                  buy_elg_amount, sell_elg_amount,
                  net_mf_amount
           FROM moneyflow_daily
           WHERE trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(start_date, end_date),
    )
    amt_cols = [c for c in df.columns if c not in ("code", "trade_date")]
    for c in amt_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载价格数据。"""
    df = pd.read_sql(
        """SELECT code, trade_date,
                  close * COALESCE(adj_factor, 1) AS adj_close,
                  volume
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s
             AND volume > 0""",
        conn,
        params=(start_date, end_date),
    )
    df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
    return df


def compute_factors(
    mf_df: pd.DataFrame,
    analysis_dates: list[date],
) -> pd.DataFrame:
    """计算3个资金流深度因子，返回长表(code, trade_date, factor_name, raw_value)。"""

    # 透视moneyflow数据
    net_mf = mf_df.pivot(index="trade_date", columns="code", values="net_mf_amount")
    buy_elg = mf_df.pivot(index="trade_date", columns="code", values="buy_elg_amount")
    sell_elg = mf_df.pivot(index="trade_date", columns="code", values="sell_elg_amount")
    buy_sm = mf_df.pivot(index="trade_date", columns="code", values="buy_sm_amount")
    sell_sm = mf_df.pivot(index="trade_date", columns="code", values="sell_sm_amount")

    # 大单净买 = buy_elg - sell_elg（用超大单代表机构）
    big_net = buy_elg - sell_elg
    # 小单净买 = buy_sm - sell_sm
    small_net = buy_sm - sell_sm

    # 预计算rolling量
    # 因子1: mf_persistence_20 = 20日内net_mf>0的天数占比
    net_mf_positive = (net_mf > 0).astype(float)
    mf_persistence = net_mf_positive.rolling(window=20, min_periods=15).mean()

    # 因子2的中间量: 20日均值
    big_net_mean_20 = big_net.rolling(window=20, min_periods=15).mean()
    small_net_mean_20 = small_net.rolling(window=20, min_periods=15).mean()

    # 因子3: mf_volatility_20 = std(net_mf, 20d) / mean(|net_mf|, 20d)
    net_mf_std_20 = net_mf.rolling(window=20, min_periods=15).std()
    net_mf_abs_mean_20 = net_mf.abs().rolling(window=20, min_periods=15).mean()
    mf_volatility = net_mf_std_20 / net_mf_abs_mean_20.replace(0, np.nan)

    results = []
    for td in analysis_dates:
        # 因子1: mf_persistence_20
        if td in mf_persistence.index:
            v1 = mf_persistence.loc[td].dropna()
            if len(v1) > 50:
                df_part = pd.DataFrame({
                    "code": v1.index, "trade_date": td,
                    "factor_name": "mf_persistence_20", "raw_value": v1.values,
                })
                results.append(df_part)

        # 因子2: big_small_divergence_20 = rank(big_net_mean_20) - rank(small_net_mean_20)
        if td in big_net_mean_20.index and td in small_net_mean_20.index:
            bn = big_net_mean_20.loc[td].dropna()
            sn = small_net_mean_20.loc[td].dropna()
            common = bn.index.intersection(sn.index)
            if len(common) > 50:
                rank_big = bn[common].rank(pct=True)
                rank_small = sn[common].rank(pct=True)
                divergence = rank_big - rank_small
                df_part = pd.DataFrame({
                    "code": divergence.index, "trade_date": td,
                    "factor_name": "big_small_divergence_20", "raw_value": divergence.values,
                })
                results.append(df_part)

        # 因子3: mf_volatility_20
        if td in mf_volatility.index:
            v3 = mf_volatility.loc[td].dropna()
            # 过滤极端值（inf等）
            v3 = v3[np.isfinite(v3)]
            if len(v3) > 50:
                df_part = pd.DataFrame({
                    "code": v3.index, "trade_date": td,
                    "factor_name": "mf_volatility_20", "raw_value": v3.values,
                })
                results.append(df_part)

    if results:
        return pd.concat(results, ignore_index=True)
    return pd.DataFrame()


def load_forward_returns(trade_dates: list, horizon: int, conn) -> pd.DataFrame:
    """加载forward excess return（超额CSI300）。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 2)

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


def calc_ic_series(factor_df: pd.DataFrame, fwd_returns: pd.DataFrame) -> dict:
    """计算因子IC时间序列。"""
    ic_results = {}

    for fname in factor_df["factor_name"].unique():
        ics = []
        for td in fwd_returns.index:
            fv = factor_df[(factor_df["trade_date"] == td) & (factor_df["factor_name"] == fname)]
            if fv.empty:
                continue
            fv = fv.set_index("code")["raw_value"]
            fr = fwd_returns.loc[td].dropna()
            common = fv.index.intersection(fr.index)
            if len(common) < 50:
                continue
            ic, _ = stats.spearmanr(fv[common], fr[common])
            if np.isfinite(ic):
                ics.append({"date": td, "ic": ic})

        if ics:
            ic_df = pd.DataFrame(ics)
            direction = FACTOR_DIRECTION.get(fname, 1)
            ic_vals = ic_df["ic"].values * direction

            ic_results[fname] = {
                "n_dates": len(ics),
                "ic_mean": float(np.mean(ic_vals)),
                "ic_std": float(np.std(ic_vals)),
                "ic_ir": float(np.mean(ic_vals) / np.std(ic_vals)) if np.std(ic_vals) > 0 else 0,
                "hit_rate": float(np.mean(ic_vals > 0)),
                "ic_series": ic_df,
            }
        else:
            ic_results[fname] = {
                "n_dates": 0, "ic_mean": 0, "ic_std": 0, "ic_ir": 0, "hit_rate": 0,
            }

    return ic_results


def main():
    conn = _get_sync_conn()

    # 检查数据量
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM moneyflow_daily")
    n_mf, min_d, max_d = cur.fetchone()
    print(f"moneyflow_daily: {n_mf:,}行 ({min_d} ~ {max_d})")

    if n_mf < 100_000:
        print("数据量不足，退出")
        conn.close()
        return

    # 分析日期: 每月最后一个交易日
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= '2021-06-01' AND trade_date <= '2025-12-31'
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC"""
    )
    analysis_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"分析日期: {len(analysis_dates)}月 ({analysis_dates[0]} ~ {analysis_dates[-1]})")

    # 1. 加载数据（从2021-01开始，给rolling留buffer）
    print("\n[1] 加载moneyflow数据...")
    mf_df = load_moneyflow_data(date(2021, 1, 1), date(2026, 3, 19), conn)
    print(f"  moneyflow: {len(mf_df):,}行, {mf_df['code'].nunique()}只股票")

    # 2. 计算因子
    print("\n[2] 计算3个资金流深度因子...")
    factor_df = compute_factors(mf_df, analysis_dates)
    if factor_df.empty:
        print("无因子数据生成，退出")
        conn.close()
        return

    print(f"  因子值总量: {len(factor_df):,}行")
    for fname in sorted(factor_df["factor_name"].unique()):
        sub = factor_df[factor_df["factor_name"] == fname]
        n_stocks = sub["code"].nunique()
        n_dates = sub["trade_date"].nunique()
        print(f"    {fname}: {len(sub):,}条, {n_stocks}只股票 x {n_dates}日")

    # 3. Forward Returns + IC分析 (5日 + 20日)
    for horizon in [5, 20]:
        print(f"\n{'='*65}")
        print(f"[3] Forward Returns: {horizon}日超额收益")
        print(f"{'='*65}")
        fwd_rets = load_forward_returns(analysis_dates, horizon=horizon, conn=conn)
        print(f"  Forward returns: {fwd_rets.shape}")

        # IC分析
        print(f"\n[4] IC分析 (horizon={horizon}d):")
        ic_results = calc_ic_series(factor_df, fwd_rets)

        print(f"\n{'因子':>25} {'方向':>4} {'IC均值':>8} {'IC_std':>8} {'IC_IR':>7} {'命中率':>6} {'日期数':>5}")
        print("-" * 75)
        for fname in FACTOR_DIRECTION:
            if fname not in ic_results:
                continue
            res = ic_results[fname]
            direction = FACTOR_DIRECTION[fname]
            dir_str = "(+)" if direction > 0 else "(-)"
            print(
                f"{fname:>25} {dir_str} "
                f"{res['ic_mean']:>+.4f} "
                f"{res['ic_std']:>.4f} "
                f"{res['ic_ir']:>+.3f} "
                f"{res['hit_rate']:>5.1%} "
                f"{res['n_dates']:>5}"
            )

        # 年度IC分解
        print(f"\n[5] 年度IC分解 (horizon={horizon}d):")
        for fname in FACTOR_DIRECTION:
            if fname not in ic_results or ic_results[fname]["n_dates"] == 0:
                continue
            ic_df = ic_results[fname]["ic_series"]
            ic_df = ic_df.copy()
            ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
            direction = FACTOR_DIRECTION[fname]
            print(f"\n  {fname} ({'+'if direction>0 else '-'}):")
            for year, grp in ic_df.groupby("year"):
                vals = grp["ic"].values * direction
                yr_ir = np.mean(vals) / max(np.std(vals), 1e-6)
                print(
                    f"    {year}: IC={np.mean(vals):+.4f}  IR={yr_ir:+.3f}  "
                    f"hit={np.mean(vals > 0):.0%}  n={len(vals)}"
                )

    # 6. 新因子间截面相关性
    print(f"\n{'='*65}")
    print("[6] 新因子间截面相关性（最近20日平均）:")
    print(f"{'='*65}")
    sample_dates = sorted(factor_df["trade_date"].unique())[-20:]
    cross_corrs = []
    for td in sample_dates:
        fv = factor_df[factor_df["trade_date"] == td].pivot(
            index="code", columns="factor_name", values="raw_value"
        )
        if len(fv) > 100:
            cross_corrs.append(fv.corr(method="spearman"))
    if cross_corrs:
        avg_cross = sum(cross_corrs) / len(cross_corrs)
        fnames = [f for f in FACTOR_DIRECTION if f in avg_cross.columns]
        print(f"\n{'':>25}", end="")
        for f in fnames:
            print(f" {f[:12]:>12}", end="")
        print()
        for f1 in fnames:
            print(f"{f1:>25}", end="")
            for f2 in fnames:
                if f1 in avg_cross.index and f2 in avg_cross.columns:
                    v = avg_cross.loc[f1, f2]
                    print(f" {v:>+11.3f}", end="")
                else:
                    print(f" {'N/A':>12}", end="")
            print()

    # 7. 与现有因子池+batch5因子的相关性
    print(f"\n{'='*65}")
    print("[7] 与现有因子池的截面相关性:")
    print(f"{'='*65}")
    existing_factors = [
        "turnover_mean_20", "volatility_20", "reversal_20",
        "amihud_20", "bp_ratio", "momentum_20",
        # batch5因子（如果已入库）
        "net_mf_amount_20", "mf_momentum_divergence",
    ]
    existing_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s
             AND trade_date IN %s""",
        conn,
        params=(tuple(existing_factors), tuple(sample_dates)),
    )

    if not existing_df.empty:
        corr_results = []
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
            corr_results.append(combined.corr(method="spearman"))

        if corr_results:
            corr_matrix = sum(corr_results) / len(corr_results)
            actual_existing = [f for f in existing_factors if f in corr_matrix.columns]
            new_factors = list(FACTOR_DIRECTION.keys())
            print(f"\n{'':>25}", end="")
            for ef in actual_existing:
                print(f" {ef[:12]:>12}", end="")
            print()
            for nf in new_factors:
                if nf in corr_matrix.index:
                    print(f"{nf:>25}", end="")
                    for ef in actual_existing:
                        v = corr_matrix.loc[nf, ef]
                        print(f" {v:>+11.3f}", end="")
                    print()
        else:
            corr_matrix = pd.DataFrame()
            actual_existing = []
            print("  (截面相关性计算失败)")
    else:
        corr_matrix = pd.DataFrame()
        actual_existing = []
        print("  (无现有因子数据)")

    # 8. Gate Check
    print(f"\n\n{'='*65}")
    print("GATE CHECK: IC > 1.5% AND max_corr_with_existing < 0.5")
    print(f"{'='*65}")

    fwd_rets_20 = load_forward_returns(analysis_dates, horizon=20, conn=conn)
    ic_results_20 = calc_ic_series(factor_df, fwd_rets_20)

    for fname in FACTOR_DIRECTION:
        if fname not in ic_results_20:
            print(f"  {fname:>25}: NO DATA")
            continue
        res = ic_results_20[fname]
        ic_pass = abs(res["ic_mean"]) > 0.015

        max_corr = 0.0
        if not corr_matrix.empty and fname in corr_matrix.index:
            for ef in actual_existing:
                if ef in corr_matrix.columns:
                    max_corr = max(max_corr, abs(corr_matrix.loc[fname, ef]))
        corr_pass = max_corr < 0.5

        ic_sym = "Y" if ic_pass else "N"
        corr_sym = "Y" if corr_pass else "N"
        status = "PASS" if (ic_pass and corr_pass) else "FAIL"
        print(
            f"  {fname:>25}: IC={res['ic_mean']:+.4f} (>1.5%={ic_sym})  "
            f"max_corr={max_corr:.3f} (<0.5={corr_sym})  IR={res['ic_ir']:+.3f}  "
            f"-> {status}"
        )

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
