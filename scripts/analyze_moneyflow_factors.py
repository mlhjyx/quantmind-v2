#!/usr/bin/env python3
"""第5批因子: 资金流因子IC分析 (moneyflow_daily)

5个候选:
  1. net_mf_amount_20    — 20日净资金流均值 (方向+1)
  2. big_order_ratio      — 大单占比 (方向+1)
  3. net_big_inflow_ratio — 大单净流入占比 (方向+1)
  4. small_order_net_sell — 小单净卖出 (方向+1，散户越卖越好)
  5. mf_momentum_divergence — 资金流动量背离 (方向-1)

所有金额单位: 万元 (moneyflow_daily.buy_*_amount/sell_*_amount/net_mf_amount)

用法:
    python scripts/analyze_moneyflow_factors.py
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
MONEYFLOW_FACTOR_DIRECTION = {
    "net_mf_amount_20": +1,
    "big_order_ratio": +1,
    "net_big_inflow_ratio": +1,
    "small_order_net_sell": +1,
    "mf_momentum_divergence": -1,
}


def load_moneyflow_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载moneyflow_daily全量数据。"""
    df = pd.read_sql(
        """SELECT code, trade_date,
                  buy_sm_amount, sell_sm_amount,
                  buy_md_amount, sell_md_amount,
                  buy_lg_amount, sell_lg_amount,
                  buy_elg_amount, sell_elg_amount,
                  net_mf_amount
           FROM moneyflow_daily
           WHERE trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(start_date, end_date),
    )
    # 所有金额列转float
    amt_cols = [c for c in df.columns if c not in ("code", "trade_date")]
    for c in amt_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载价格数据用于momentum因子。"""
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


def compute_moneyflow_factors(
    mf_df: pd.DataFrame,
    price_df: pd.DataFrame,
    analysis_dates: list[date],
) -> pd.DataFrame:
    """计算5个资金流因子，返回长表(code, trade_date, factor_name, raw_value)。"""

    # 透视moneyflow数据方便rolling
    mf_pivot = {}
    for col in [
        "net_mf_amount",
        "buy_sm_amount", "sell_sm_amount",
        "buy_md_amount", "sell_md_amount",
        "buy_lg_amount", "sell_lg_amount",
        "buy_elg_amount", "sell_elg_amount",
    ]:
        mf_pivot[col] = mf_df.pivot(index="trade_date", columns="code", values=col)

    # 计算total_amount = 所有买卖金额之和
    total_amount = (
        mf_pivot["buy_sm_amount"]
        + mf_pivot["sell_sm_amount"]
        + mf_pivot["buy_md_amount"]
        + mf_pivot["sell_md_amount"]
        + mf_pivot["buy_lg_amount"]
        + mf_pivot["sell_lg_amount"]
        + mf_pivot["buy_elg_amount"]
        + mf_pivot["sell_elg_amount"]
    )

    # 因子1: net_mf_amount_20 = mean(net_mf_amount, 20d)
    net_mf_20 = mf_pivot["net_mf_amount"].rolling(window=20, min_periods=15).mean()

    # 因子2: big_order_ratio = (buy_elg + sell_elg) / total
    big_amount = mf_pivot["buy_elg_amount"] + mf_pivot["sell_elg_amount"]
    big_order_ratio = big_amount / total_amount.replace(0, np.nan)

    # 因子3: net_big_inflow_ratio
    # = (buy_elg - sell_elg + buy_lg - sell_lg) / total
    net_big_inflow = (
        mf_pivot["buy_elg_amount"]
        - mf_pivot["sell_elg_amount"]
        + mf_pivot["buy_lg_amount"]
        - mf_pivot["sell_lg_amount"]
    )
    net_big_inflow_ratio = net_big_inflow / total_amount.replace(0, np.nan)

    # 因子4: small_order_net_sell = sell_sm - buy_sm
    small_net_sell = mf_pivot["sell_sm_amount"] - mf_pivot["buy_sm_amount"]

    # 因子5: mf_momentum_divergence = rank(price_momentum_20) - rank(net_mf_amount_20)
    # 需要价格momentum
    price_pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    price_mom_20 = price_pivot.pct_change(periods=20)

    results = []
    for td in analysis_dates:
        if td not in net_mf_20.index:
            continue

        row_data = {}

        # 因子1
        v1 = net_mf_20.loc[td].dropna()
        if len(v1) > 50:
            row_data["net_mf_amount_20"] = v1

        # 因子2
        v2 = big_order_ratio.loc[td].dropna() if td in big_order_ratio.index else pd.Series()
        if len(v2) > 50:
            row_data["big_order_ratio"] = v2

        # 因子3
        v3 = net_big_inflow_ratio.loc[td].dropna() if td in net_big_inflow_ratio.index else pd.Series()
        if len(v3) > 50:
            row_data["net_big_inflow_ratio"] = v3

        # 因子4
        v4 = small_net_sell.loc[td].dropna() if td in small_net_sell.index else pd.Series()
        if len(v4) > 50:
            row_data["small_order_net_sell"] = v4

        # 因子5: rank差异
        if td in price_mom_20.index and td in net_mf_20.index:
            pm = price_mom_20.loc[td].dropna()
            nm = net_mf_20.loc[td].dropna()
            common5 = pm.index.intersection(nm.index)
            if len(common5) > 50:
                rank_pm = pm[common5].rank(pct=True)
                rank_nm = nm[common5].rank(pct=True)
                divergence = rank_pm - rank_nm
                row_data["mf_momentum_divergence"] = divergence

        for fname, vals in row_data.items():
            df_part = pd.DataFrame(
                {"code": vals.index, "trade_date": td, "factor_name": fname, "raw_value": vals.values}
            )
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
            direction = MONEYFLOW_FACTOR_DIRECTION.get(fname, 1)
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
                "n_dates": 0,
                "ic_mean": 0,
                "ic_std": 0,
                "ic_ir": 0,
                "hit_rate": 0,
            }

    return ic_results


def calc_factor_correlations(factor_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """计算新因子与现有因子的截面Spearman相关性（最近20日平均）。"""
    dates = factor_df["trade_date"].unique()
    if len(dates) == 0:
        return pd.DataFrame()

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
    cur.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM moneyflow_daily")
    n_mf, min_d, max_d = cur.fetchone()
    print(f"moneyflow_daily: {n_mf:,}行 ({min_d} ~ {max_d})", flush=True)

    if n_mf < 100_000:
        print("数据量不足，退出")
        conn.close()
        return

    # 分析日期: 每月最后一个交易日 (2021-06 ~ 2025-12, 给20日rolling留buffer)
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= '2021-06-01' AND trade_date <= '2025-12-31'
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC"""
    )
    analysis_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"分析日期: {len(analysis_dates)}月 ({analysis_dates[0]} ~ {analysis_dates[-1]})", flush=True)

    # 1. 加载数据（从2021-01开始，给rolling留buffer）
    print("\n[1] 加载moneyflow数据...")
    mf_df = load_moneyflow_data(date(2021, 1, 1), date(2026, 3, 19), conn)
    print(f"  moneyflow: {len(mf_df):,}行, {mf_df['code'].nunique()}只股票")

    print("  加载价格数据...")
    price_df = load_price_data(date(2021, 1, 1), date(2026, 3, 19), conn)
    print(f"  price: {len(price_df):,}行")

    # 2. 计算因子
    print("\n[2] 计算5个资金流因子...")
    factor_df = compute_moneyflow_factors(mf_df, price_df, analysis_dates)
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

    # 3. Forward Returns (5日 + 20日)
    for horizon in [5, 20]:
        print(f"\n{'='*65}")
        print(f"[3] Forward Returns: {horizon}日超额收益")
        print(f"{'='*65}")
        fwd_rets = load_forward_returns(analysis_dates, horizon=horizon, conn=conn)
        print(f"  Forward returns: {fwd_rets.shape}")

        # 4. IC分析
        print(f"\n[4] IC分析 (horizon={horizon}d):")
        ic_results = calc_ic_series(factor_df, fwd_rets)

        print(f"\n{'因子':>25} {'方向':>4} {'IC均值':>8} {'IC_std':>8} {'IC_IR':>7} {'命中率':>6} {'日期数':>5}")
        print("-" * 75)
        for fname in MONEYFLOW_FACTOR_DIRECTION:
            if fname not in ic_results:
                continue
            res = ic_results[fname]
            direction = MONEYFLOW_FACTOR_DIRECTION[fname]
            dir_str = "(+)" if direction > 0 else "(-)"
            print(
                f"{fname:>25} {dir_str} "
                f"{res['ic_mean']:>+.4f} "
                f"{res['ic_std']:>.4f} "
                f"{res['ic_ir']:>+.3f} "
                f"{res['hit_rate']:>5.1%} "
                f"{res['n_dates']:>5}"
            )

        # 5. 年度IC分解
        print(f"\n[5] 年度IC分解 (horizon={horizon}d):")
        for fname in MONEYFLOW_FACTOR_DIRECTION:
            if fname not in ic_results or ic_results[fname]["n_dates"] == 0:
                continue
            ic_df = ic_results[fname]["ic_series"]
            ic_df = ic_df.copy()
            ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
            direction = MONEYFLOW_FACTOR_DIRECTION[fname]
            print(f"\n  {fname} ({'+'if direction>0 else '-'}):")
            for year, grp in ic_df.groupby("year"):
                vals = grp["ic"].values * direction
                yr_ir = np.mean(vals) / max(np.std(vals), 1e-6)
                print(
                    f"    {year}: IC={np.mean(vals):+.4f}  IR={yr_ir:+.3f}  "
                    f"hit={np.mean(vals > 0):.0%}  n={len(vals)}"
                )

    # 6. 新因子之间的互相关性
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
        fnames = list(MONEYFLOW_FACTOR_DIRECTION.keys())
        fnames = [f for f in fnames if f in avg_cross.columns]
        print(f"\n{'':>25}", end="")
        for f in fnames:
            print(f" {f[:10]:>10}", end="")
        print()
        for f1 in fnames:
            print(f"{f1:>25}", end="")
            for f2 in fnames:
                if f1 in avg_cross.index and f2 in avg_cross.columns:
                    v = avg_cross.loc[f1, f2]
                    print(f" {v:>+9.3f}", end="")
                else:
                    print(f" {'N/A':>10}", end="")
            print()

    # 7. 与现有18因子的相关性
    print(f"\n{'='*65}")
    print("[7] 与现有因子池的截面相关性:")
    print(f"{'='*65}")
    existing_factors = [
        "turnover_mean_20", "volatility_20", "reversal_20",
        "amihud_20", "bp_ratio", "momentum_20",
    ]
    existing_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s
             AND trade_date IN %s""",
        conn,
        params=(tuple(existing_factors), tuple(sample_dates)),
    )

    corr_matrix = pd.DataFrame()
    if not existing_df.empty:
        corr_matrix = calc_factor_correlations(factor_df, existing_df)
        if not corr_matrix.empty:
            new_factors = list(MONEYFLOW_FACTOR_DIRECTION.keys())
            print(f"\n{'':>25}", end="")
            for ef in existing_factors:
                print(f" {ef[:12]:>12}", end="")
            print()
            for nf in new_factors:
                if nf in corr_matrix.index:
                    print(f"{nf:>25}", end="")
                    for ef in existing_factors:
                        if ef in corr_matrix.columns:
                            v = corr_matrix.loc[nf, ef]
                            print(f" {v:>+11.3f}", end="")
                        else:
                            print(f" {'N/A':>12}", end="")
                    print()
        else:
            print("  (截面相关性计算失败)")
    else:
        print("  (无现有因子数据)")

    # 8. Gate Check
    print(f"\n\n{'='*65}")
    print("GATE CHECK: IC > 1.5% AND max_corr_with_existing < 0.5")
    print(f"{'='*65}")

    # 用20日horizon的IC结果做gate
    fwd_rets_20 = load_forward_returns(analysis_dates, horizon=20, conn=conn)
    ic_results_20 = calc_ic_series(factor_df, fwd_rets_20)

    for fname in MONEYFLOW_FACTOR_DIRECTION:
        if fname not in ic_results_20:
            print(f"  {fname:>25}: NO DATA")
            continue
        res = ic_results_20[fname]
        ic_pass = abs(res["ic_mean"]) > 0.015

        max_corr = 0.0
        if not corr_matrix.empty and fname in corr_matrix.index:
            for ef in existing_factors:
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
