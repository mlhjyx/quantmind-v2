#!/usr/bin/env python3
"""候选1(质量成长)因子IC快速验证。

计算3个核心财务因子的截面IC:
1. roe (ROE水平值, 方向+1)
2. revenue_yoy (营收同比增速, 方向+1)
3. gross_profit_margin (毛利率, 方向+1)

PIT对齐: 使用actual_ann_date，确保无前视偏差。
Forward return: 20日超额收益(相对沪深300)。
验证标准: IC_mean > 0.02 (STRATEGY_CANDIDATES.md)

用法:
    cd /Users/xin/Documents/quantmind-v2 && python scripts/validate_candidate1_ic.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn

# 候选1因子定义
CANDIDATE1_FACTORS = {
    "roe": {"column": "roe", "direction": 1, "desc": "ROE水平值(%)"},
    "revenue_yoy": {"column": "revenue_yoy", "direction": 1, "desc": "营收同比增速(%)"},
    "gross_profit_margin": {"column": "gross_profit_margin", "direction": 1, "desc": "毛利率(%)"},
}

IC_THRESHOLD = 0.02  # 候选1验证标准


def load_pit_factor(trade_date: date, factor_col: str, conn) -> pd.Series:
    """PIT对齐加载单个财务因子值。

    对每只股票，取截至trade_date已公告的最新一期报告的因子值。
    同一(code, report_date)取actual_ann_date最晚的（修正稿覆盖快报）。
    """
    df = pd.read_sql(
        """WITH ranked AS (
            SELECT code, report_date, actual_ann_date, """ + factor_col + """,
                   ROW_NUMBER() OVER (
                       PARTITION BY code, report_date
                       ORDER BY actual_ann_date DESC
                   ) AS rn
            FROM financial_indicators
            WHERE actual_ann_date <= %s
              AND """ + factor_col + """ IS NOT NULL
        ),
        latest AS (
            SELECT code, """ + factor_col + """,
                   ROW_NUMBER() OVER (
                       PARTITION BY code
                       ORDER BY report_date DESC
                   ) AS rn2
            FROM ranked
            WHERE rn = 1
        )
        SELECT code, """ + factor_col + """ AS value
        FROM latest
        WHERE rn2 = 1""",
        conn,
        params=(trade_date,),
    )
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("code")["value"].astype(float)


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

    # 1. 获取分析日期: 每月最后一个交易日 (2021-2025)
    cur = conn.cursor()
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

    # 2. 计算Forward Returns (20-day excess)
    print("\n[1] 计算Forward Returns (20日超额)...")
    fwd_rets = load_forward_returns(analysis_dates, horizon=20, conn=conn)
    print(f"  Forward returns: {fwd_rets.shape}")

    # 3. 逐因子计算IC
    print("\n[2] 逐因子计算截面IC...")
    all_results = {}

    for fname, fdef in CANDIDATE1_FACTORS.items():
        print(f"\n  --- {fname} ({fdef['desc']}) ---")
        ics = []

        for td in fwd_rets.index:
            # PIT加载因子值
            fv = load_pit_factor(td, fdef["column"], conn)
            if fv.empty:
                continue

            # Forward return
            fr = fwd_rets.loc[td].dropna()

            # 交集
            common = fv.index.intersection(fr.index)
            if len(common) < 100:
                continue

            ic, _ = stats.spearmanr(fv[common], fr[common])
            if np.isfinite(ic):
                ics.append({"date": td, "ic": ic})

        if not ics:
            print(f"    ERROR: 无有效IC")
            all_results[fname] = None
            continue

        ic_df = pd.DataFrame(ics)
        ic_vals = ic_df["ic"].values * fdef["direction"]

        result = {
            "n_dates": len(ics),
            "ic_mean": float(np.mean(ic_vals)),
            "ic_std": float(np.std(ic_vals)),
            "ic_ir": float(np.mean(ic_vals) / np.std(ic_vals)) if np.std(ic_vals) > 0 else 0,
            "hit_rate": float(np.mean(ic_vals > 0)),
            "ic_series": ic_df,
            "direction": fdef["direction"],
        }
        all_results[fname] = result

        print(f"    IC均值:  {result['ic_mean']:+.4f} ({result['ic_mean']*100:+.2f}%)")
        print(f"    IC_IR:   {result['ic_ir']:+.3f}")
        print(f"    命中率:  {result['hit_rate']:.1%}")
        print(f"    有效月数: {result['n_dates']}")

        # 年度分解
        ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
        for year, grp in ic_df.groupby("year"):
            vals = grp["ic"].values * fdef["direction"]
            ir = np.mean(vals) / np.std(vals) if np.std(vals) > 0 else 0
            print(f"      {year}: IC={np.mean(vals):+.4f} IR={ir:+.3f} hit={np.mean(vals>0):.0%} n={len(vals)}")

    # 4. 与现有5因子的截面相关性
    print("\n\n[3] 与现有基线因子的截面相关性 (最近20个月平均)...")
    existing_factors = ["turnover_mean_20", "volatility_20", "reversal_20", "ln_market_cap", "bp_ratio"]
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
        for fname, fdef in CANDIDATE1_FACTORS.items():
            corrs = {}
            for ef in existing_factors:
                ef_corrs = []
                for td in sample_dates:
                    fv = load_pit_factor(td, fdef["column"], conn)
                    ev = existing_df[
                        (existing_df["trade_date"] == td) & (existing_df["factor_name"] == ef)
                    ].set_index("code")["zscore"]
                    common = fv.index.intersection(ev.index)
                    if len(common) >= 100:
                        c, _ = stats.spearmanr(fv[common].astype(float), ev[common].astype(float))
                        if np.isfinite(c):
                            ef_corrs.append(c)
                if ef_corrs:
                    corrs[ef] = np.mean(ef_corrs)

            print(f"\n  {fname}:")
            for ef, c in corrs.items():
                flag = " *** HIGH" if abs(c) > 0.5 else ""
                print(f"    vs {ef:>20}: {c:+.4f}{flag}")

    # 5. Summary & Gate check
    print("\n\n" + "=" * 70)
    print("CANDIDATE 1 IC VALIDATION SUMMARY")
    print("=" * 70)
    print(f"{'因子':>25} {'IC均值':>10} {'>2%?':>6} {'IC_IR':>8} {'命中率':>8} {'月数':>5}")
    print("-" * 70)

    pass_count = 0
    for fname, res in all_results.items():
        if res is None:
            print(f"{fname:>25} {'N/A':>10}")
            continue
        ic_pct = res["ic_mean"] * 100
        passed = abs(res["ic_mean"]) > IC_THRESHOLD
        if passed:
            pass_count += 1
        status = "PASS" if passed else "FAIL"
        print(
            f"{fname:>25} {res['ic_mean']:>+.4f} {status:>6} "
            f"{res['ic_ir']:>+.3f} {res['hit_rate']:>7.1%} {res['n_dates']:>5}"
        )

    print(f"\nGate: {pass_count}/3 因子IC > {IC_THRESHOLD*100:.0f}%")
    if pass_count >= 2:
        print("VERDICT: 候选1因子基础充分，可进入WF-OOS验证")
    elif pass_count == 1:
        print("VERDICT: 仅1个因子通过，需评估是否调整因子组合")
    else:
        print("VERDICT: 因子IC普遍不足，候选1可能需要重新设计")

    conn.close()


if __name__ == "__main__":
    main()
