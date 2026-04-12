#!/usr/bin/env python
"""Phase 2.3前置: 策略市值暴露诊断。

搞清楚CORE5+SN策略到底选了什么市值区间的股票，CSI300作基准是否合理，
因子IC有多少来自真alpha vs 风格溢价。

Usage:
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --step1
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --step2
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --step3
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --step4
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --step6
    cd backend && python ../scripts/research/phase23_mcap_diagnostic.py --all
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from bisect import bisect_right
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

CACHE_DIR = PROJECT_ROOT / "cache"
PHASE23_CACHE = CACHE_DIR / "phase23"

# CORE 5 因子 + 方向 (from signal_engine.py FACTOR_DIRECTION)
CORE5_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
CORE5_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}
SN_BETA = 0.50

# daily_basic.total_mv 在DB中是元(DataPipeline Step 3-A已转换: Tushare万元×10000→元)
# 验证: 600519.SH 2025-01-02 = 1,869,222,326,400元 ≈ 18692亿元 ✓
# 注意: models/astock.py:322注释"万元"是过时的, 实际是元
YUAN_TO_YI = 1e-8  # 元 → 亿元

# 市值分组阈值(元)
MCAP_GROUPS = {
    "微盘(<100亿)": (0, 100e8),
    "小盘(100-300亿)": (100e8, 300e8),
    "中盘(300-500亿)": (300e8, 500e8),
    "大盘(>500亿)": (500e8, float("inf")),
}


# ─── 共享工具函数 ──────────────────────────────────────────


def get_db_conn():
    """获取psycopg2同步连接。"""
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
    return psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )


def load_price_data(start_year: int = 2020, end_year: int = 2026):
    """从Parquet缓存加载price_data + benchmark。"""
    price_parts, bench_parts = [], []
    for y in range(start_year, end_year + 1):
        pf = CACHE_DIR / "backtest" / str(y) / "price_data.parquet"
        bf = CACHE_DIR / "backtest" / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price = pd.concat(price_parts, ignore_index=True)
    bench = pd.concat(bench_parts, ignore_index=True)
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
    bench = bench.sort_values("trade_date").drop_duplicates("trade_date")
    print(f"  Price: {len(price):,} rows, Benchmark: {len(bench):,} rows")
    return price, bench


def load_factor_from_parquet(start_year: int = 2020, end_year: int = 2026):
    """从Parquet缓存加载CORE5因子数据。

    注意: parquet的raw_value列实际是WLS中性化值(SCHEMA.md警告), rename为neutral_value。
    """
    parts = []
    for y in range(start_year, end_year + 1):
        fp = CACHE_DIR / "backtest" / str(y) / "factor_data.parquet"
        if fp.exists():
            df = pd.read_parquet(fp)
            df = df[df["factor_name"].isin(CORE5_FACTORS)]
            parts.append(df)

    factor_df = pd.concat(parts, ignore_index=True)
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
    # raw_value实际是中性化值(SCHEMA.md documented)
    factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    print(
        f"  Factors from parquet: {len(factor_df):,} rows, "
        f"factors: {sorted(factor_df['factor_name'].unique())}"
    )
    return factor_df


def get_monthly_rebal_dates(trade_dates) -> list:
    """月末最后交易日。"""
    df = pd.DataFrame({"td": sorted(set(trade_dates))})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def compute_composite_scores(day_factors: pd.DataFrame) -> pd.Series:
    """等权复合分 = Σ(neutral_value × direction) / n。

    Args:
        day_factors: 当日因子截面 (code, factor_name, neutral_value)

    Returns:
        Series (code → composite_score, 降序)
    """
    wide = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

    avail_factors = [f for f in CORE5_FACTORS if f in wide.columns]
    if not avail_factors:
        return pd.Series(dtype=float)

    composite = pd.Series(0.0, index=wide.index)
    for factor in avail_factors:
        direction = CORE5_DIRECTIONS[factor]
        composite += wide[factor].fillna(0) * direction

    composite /= len(avail_factors)
    return composite.sort_values(ascending=False, kind="mergesort")


def build_exclusion_set(price_data: pd.DataFrame, td) -> set:
    """构建排除集: ST + 停牌 + 新股 + 北交所。"""
    day = price_data[price_data["trade_date"] == td]
    exclude = set()
    if "is_st" in day.columns:
        exclude |= set(day[day["is_st"]]["code"])
    if "is_suspended" in day.columns:
        exclude |= set(day[day["is_suspended"]]["code"])
    if "is_new_stock" in day.columns:
        exclude |= set(day[day["is_new_stock"]]["code"])
    if "board" in day.columns:
        exclude |= set(day[day["board"] == "bse"]["code"])
    return exclude


# ─── Step 1: 策略持仓市值分布 ─────────────────────────────


def step1_portfolio_mcap_distribution(args):
    """Step 1: 统计Top-20持仓的市值分布(无SN vs SN)。"""
    print("\n" + "=" * 70)
    print("Step 1: 策略持仓市值分布")
    print("=" * 70)

    PHASE23_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    conn = get_db_conn()

    # 1. 加载数据
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, _ = load_price_data(2020, 2026)

    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(date(2020, 1, 1), date(2026, 4, 1), conn)

    # 获取交易日和调仓日
    all_factor_dates = sorted(factor_df["trade_date"].unique())
    all_price_dates = sorted(price_data["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    # 只取有因子数据的月份
    monthly_dates = [
        d for d in monthly_dates if d >= all_factor_dates[0] and d <= all_factor_dates[-1]
    ]
    print(
        f"  Rebalance dates: {len(monthly_dates)} months ({monthly_dates[0]} ~ {monthly_dates[-1]})"
    )

    # 2. 对每月构建持仓并查market cap
    print("\n[2] Building portfolios and querying market caps...")
    records_no_sn = []
    records_sn = []

    # 预建因子日期索引 (bisect用)
    factor_date_list = sorted(factor_df["trade_date"].unique())

    for i, rd in enumerate(monthly_dates):
        # 找最近的因子日期
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]

        # 当日因子
        day_data = factor_df[factor_df["trade_date"] == fd]
        if day_data.empty:
            continue

        # 排除集
        exclude = build_exclusion_set(price_data, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]

        # 复合分
        scores = compute_composite_scores(day_data)
        if len(scores) < 20:
            continue

        # 无SN Top-20
        top_no_sn = scores.nlargest(20).index.tolist()

        # SN Top-20
        top_sn = top_no_sn  # fallback
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
            adj_scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)
            top_sn = adj_scores.nlargest(20).index.tolist()

        # 查market cap (daily_basic, 元)
        all_codes = list(set(top_no_sn + top_sn))
        placeholders = ",".join(["%s"] * len(all_codes))
        cur = conn.cursor()
        cur.execute(
            f"SELECT code, total_mv FROM daily_basic "
            f"WHERE trade_date = %s AND code IN ({placeholders}) AND total_mv > 0",
            [rd] + all_codes,
        )
        mcap_dict = {r[0]: float(r[1]) for r in cur.fetchall()}  # code → 元
        cur.close()

        # 查amount (从price_data)
        day_price = price_data[
            (price_data["trade_date"] == rd) & (price_data["code"].isin(all_codes))
        ].set_index("code")
        amount_dict = (
            {k: float(v) for k, v in day_price["amount"].to_dict().items()}
            if "amount" in day_price.columns
            else {}
        )

        # 统计
        for label, top_codes, record_list in [
            ("no_sn", top_no_sn, records_no_sn),
            ("sn", top_sn, records_sn),
        ]:
            mcaps = [mcap_dict.get(c, np.nan) for c in top_codes]
            amounts = [amount_dict.get(c, np.nan) for c in top_codes]
            mcaps_valid = [m for m in mcaps if not np.isnan(m)]
            amounts_valid = [a for a in amounts if not np.isnan(a)]

            if not mcaps_valid:
                continue

            mcap_arr = np.array(mcaps_valid)
            # 分组计数
            group_counts = {}
            for gname, (lo, hi) in MCAP_GROUPS.items():
                group_counts[gname] = int(np.sum((mcap_arr >= lo) & (mcap_arr < hi)))

            record_list.append(
                {
                    "rebal_date": str(rd),
                    "year": rd.year,
                    "avg_mcap_yuan": float(np.mean(mcap_arr)),
                    "median_mcap_yuan": float(np.median(mcap_arr)),
                    "min_mcap_yuan": float(np.min(mcap_arr)),
                    "max_mcap_yuan": float(np.max(mcap_arr)),
                    "n_stocks": len(mcaps_valid),
                    **group_counts,
                    "avg_amount": float(np.mean(amounts_valid)) if amounts_valid else 0,
                    "min_amount": float(np.min(amounts_valid)) if amounts_valid else 0,
                    "codes": top_codes,
                }
            )

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(monthly_dates)} months")

    conn.close()

    # 3. 汇总
    print(f"\n[3] Summary ({len(records_no_sn)} months no_sn, {len(records_sn)} months sn)")

    # 单位验证: 茅台市值应约1.8-2万亿元(18000-20000亿)
    if records_sn:
        sample = records_sn[0]
        print(
            f"  Sample date: {sample['rebal_date']}, avg_mcap={sample['avg_mcap_yuan']:.0f}元 "
            f"= {sample['avg_mcap_yuan'] * YUAN_TO_YI:.1f}亿元"
        )

    def summarize(records, label):
        df = pd.DataFrame(records)
        avg_mcap = df["avg_mcap_yuan"].mean() * YUAN_TO_YI
        med_mcap = df["median_mcap_yuan"].mean() * YUAN_TO_YI
        min_mcap = df["min_mcap_yuan"].mean() * YUAN_TO_YI

        # 分组占比
        n_total = df["n_stocks"].sum()
        group_pcts = {}
        for gname in MCAP_GROUPS:
            cnt = df[gname].sum()
            group_pcts[gname] = cnt / n_total * 100 if n_total > 0 else 0

        avg_amt = df["avg_amount"].mean()
        min_amt = df["min_amount"].mean()

        print(f"\n  === {label} ===")
        print(f"  Top-20 平均市值: {avg_mcap:.1f} 亿元")
        print(f"  Top-20 中位数市值: {med_mcap:.1f} 亿元")
        print(f"  Top-20 最小市值(均值): {min_mcap:.1f} 亿元")
        for gname, pct in group_pcts.items():
            print(f"  {gname}: {pct:.1f}%")
        print(f"  平均日均成交额: {avg_amt / 1e4:.0f} 万元")
        print(f"  最低日均成交额(均值): {min_amt / 1e4:.0f} 万元")

        # 年度趋势
        yearly = df.groupby("year").agg(
            avg_mcap_yi=("avg_mcap_yuan", lambda x: x.mean() * YUAN_TO_YI),
            median_mcap_yi=("median_mcap_yuan", lambda x: x.mean() * YUAN_TO_YI),
        )
        print("\n  年度趋势:")
        for yr, row in yearly.iterrows():
            print(f"    {yr}: avg={row['avg_mcap_yi']:.1f}亿, median={row['median_mcap_yi']:.1f}亿")

        return {
            "avg_mcap_yi": round(avg_mcap, 1),
            "median_mcap_yi": round(med_mcap, 1),
            "min_mcap_yi": round(min_mcap, 1),
            "group_pcts": {k: round(v, 1) for k, v in group_pcts.items()},
            "avg_amount_wan": round(avg_amt / 1e4, 0),
            "min_amount_wan": round(min_amt / 1e4, 0),
            "yearly": yearly.round(1).to_dict(),
        }

    summary_no_sn = summarize(records_no_sn, "无SN")
    summary_sn = summarize(records_sn, "SN b=0.50")

    # 对比表
    print(f"\n\n{'指标':<25} {'无SN':>12} {'SN b=0.50':>12}")
    print("-" * 52)
    print(
        f"{'Top-20平均市值(亿)':<25} {summary_no_sn['avg_mcap_yi']:>12.1f} {summary_sn['avg_mcap_yi']:>12.1f}"
    )
    print(
        f"{'Top-20中位数市值(亿)':<25} {summary_no_sn['median_mcap_yi']:>12.1f} {summary_sn['median_mcap_yi']:>12.1f}"
    )
    for gname in MCAP_GROUPS:
        pct1 = summary_no_sn["group_pcts"][gname]
        pct2 = summary_sn["group_pcts"][gname]
        print(f"{gname:<25} {pct1:>11.1f}% {pct2:>11.1f}%")
    print(
        f"{'平均日均成交额(万)':<25} {summary_no_sn['avg_amount_wan']:>12.0f} {summary_sn['avg_amount_wan']:>12.0f}"
    )
    print(
        f"{'最低日均成交额(万)':<25} {summary_no_sn['min_amount_wan']:>12.0f} {summary_sn['min_amount_wan']:>12.0f}"
    )

    # 保存
    result = {
        "no_sn": summary_no_sn,
        "sn": summary_sn,
        "n_months": len(records_no_sn),
        "records_no_sn": records_no_sn,
        "records_sn": records_sn,
    }
    out = PHASE23_CACHE / "step1_mcap_distribution.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Saved: {out}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Step 1 elapsed: {elapsed:.1f} min")
    return result


# ─── Step 2: 基准匹配度检验 ───────────────────────────────


def step2_benchmark_matching(args):
    """Step 2: 计算策略日收益与5个基准的相关性。"""
    print("\n" + "=" * 70)
    print("Step 2: 基准匹配度检验")
    print("=" * 70)

    PHASE23_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. 加载Step 1持仓
    step1_path = PHASE23_CACHE / "step1_mcap_distribution.json"
    if not step1_path.exists():
        print("  ERROR: Step 1 results not found. Run --step1 first.")
        return None
    with open(step1_path) as f:
        step1 = json.load(f)

    records_sn = step1["records_sn"]
    # 构建持仓时间表: date → list[code]
    holdings = {}
    for rec in records_sn:
        d = date.fromisoformat(rec["rebal_date"])
        holdings[d] = rec["codes"]

    rebal_dates = sorted(holdings.keys())
    print(f"  Holdings: {len(rebal_dates)} rebalance dates")

    # 2. 加载price_data
    print("\n[1] Loading price data...")
    price_data, _ = load_price_data(2020, 2026)

    # 构建日收益宽表
    print("  Building daily return matrix...")
    price_wide = price_data.pivot_table(
        index="trade_date", columns="code", values="adj_close", aggfunc="last"
    ).sort_index()
    daily_ret = price_wide.pct_change()

    # 3. 计算策略日收益
    print("\n[2] Computing strategy daily returns...")
    trade_dates = sorted(daily_ret.index)
    strat_returns = {}

    for td in trade_dates:
        # 找当前有效持仓(最近的调仓日)
        idx = bisect_right(rebal_dates, td)
        if idx == 0:
            continue
        current_holding = holdings[rebal_dates[idx - 1]]

        # 该日等权收益
        day_rets = daily_ret.loc[td, :].reindex(current_holding).dropna()
        if len(day_rets) > 0:
            strat_returns[td] = day_rets.mean()

    strat_ret_series = pd.Series(strat_returns).sort_index()
    strat_ret_series = strat_ret_series.dropna()
    print(
        f"  Strategy returns: {len(strat_ret_series)} days, "
        f"{strat_ret_series.index[0]} ~ {strat_ret_series.index[-1]}"
    )

    # 4. 加载指数基准
    print("\n[3] Loading benchmark indices...")
    conn = get_db_conn()
    cur = conn.cursor()

    benchmarks = {}

    # CSI300/500/1000 from index_daily
    for code, name in [
        ("000300.SH", "CSI300"),
        ("000905.SH", "CSI500"),
        ("000852.SH", "CSI1000"),
    ]:
        cur.execute(
            "SELECT trade_date, close FROM index_daily WHERE index_code = %s ORDER BY trade_date",
            (code,),
        )
        rows = cur.fetchall()
        if rows:
            s = pd.Series({r[0]: float(r[1]) for r in rows}, dtype=float).sort_index()
            benchmarks[name] = s.pct_change().dropna()
            print(f"  {name}: {len(benchmarks[name])} days")

    # CSI2000: 尝试DB → Tushare → proxy
    print("\n  Trying CSI2000...")
    cur.execute(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '932000.CSI' ORDER BY trade_date"
    )
    rows = cur.fetchall()
    if rows and len(rows) > 100:
        s = pd.Series({r[0]: float(r[1]) for r in rows}, dtype=float).sort_index()
        benchmarks["CSI2000"] = s.pct_change().dropna()
        print(f"  CSI2000 from DB: {len(benchmarks['CSI2000'])} days")
    else:
        print("  CSI2000 not in DB, trying Tushare...")
        try:
            from app.data_fetcher.tushare_api import TushareAPI

            api = TushareAPI()
            csi2000_raw = api.fetch_index_daily("932000.CSI", "20200101", "20260410")
            if csi2000_raw is not None and len(csi2000_raw) > 100:
                csi2000_raw = csi2000_raw.sort_values("trade_date")
                s = pd.Series(
                    csi2000_raw["close"].values,
                    index=pd.to_datetime(csi2000_raw["trade_date"]).dt.date,
                    dtype=float,
                ).sort_index()
                benchmarks["CSI2000"] = s.pct_change().dropna()
                print(f"  CSI2000 from Tushare: {len(benchmarks['CSI2000'])} days")
            else:
                raise ValueError("Tushare returned empty")
        except Exception as e:
            print(f"  CSI2000 Tushare failed: {e}")
            print("  Computing CSI2000 proxy (rank 1001-2000 equal-weight)...")
            # 代理计算: 每月按total_mv排名，rank 1001-2000的等权日收益
            proxy_ret = _compute_csi2000_proxy(conn, price_data, daily_ret)
            if proxy_ret is not None and len(proxy_ret) > 100:
                benchmarks["CSI2000(proxy)"] = proxy_ret
                print(f"  CSI2000 proxy: {len(proxy_ret)} days")

    cur.close()

    # 全A等权
    print("\n  Computing 全A等权...")
    valid = price_data[
        (~price_data.get("is_st", pd.Series(False)).fillna(False).astype(bool))
        & (~price_data.get("is_suspended", pd.Series(False)).fillna(False).astype(bool))
        & (~price_data.get("is_new_stock", pd.Series(False)).fillna(False).astype(bool))
        & (price_data.get("board", pd.Series("main")) != "bse")
    ].copy()
    valid = valid.sort_values(["code", "trade_date"])
    valid["prev_adj"] = valid.groupby("code")["adj_close"].shift(1)
    valid["daily_ret"] = valid["adj_close"] / valid["prev_adj"] - 1
    # 去极端值
    valid = valid[(valid["daily_ret"] > -0.5) & (valid["daily_ret"] < 0.5)]
    all_a_ew = valid.groupby("trade_date")["daily_ret"].mean()
    benchmarks["全A等权"] = all_a_ew.sort_index()
    print(f"  全A等权: {len(all_a_ew)} days")

    conn.close()
    del price_data, price_wide, daily_ret, valid
    gc.collect()

    # 5. 相关性分析
    print("\n[4] Correlation analysis...")
    results = []
    for bname, bench_ret in benchmarks.items():
        # 对齐
        common = strat_ret_series.index.intersection(bench_ret.index)
        if len(common) < 100:
            print(f"  {bname}: insufficient overlap ({len(common)} days)")
            continue

        s = strat_ret_series.reindex(common)
        b = bench_ret.reindex(common)

        corr = s.corr(b)
        excess = s - b
        excess_mean = excess.mean()
        excess_std = excess.std()
        excess_sharpe = (excess_mean / excess_std * np.sqrt(244)) if excess_std > 0 else 0
        ann_bench_ret = (1 + b.mean()) ** 244 - 1
        ann_strat_ret = (1 + s.mean()) ** 244 - 1
        ann_excess = ann_strat_ret - ann_bench_ret

        results.append(
            {
                "benchmark": bname,
                "correlation": round(float(corr), 4),
                "excess_sharpe": round(float(excess_sharpe), 4),
                "ann_bench_ret": round(float(ann_bench_ret), 4),
                "ann_strat_ret": round(float(ann_strat_ret), 4),
                "ann_excess": round(float(ann_excess), 4),
                "n_days": len(common),
            }
        )

    # 排序
    results.sort(key=lambda x: -x["correlation"])

    print(
        f"\n{'基准':<15} {'相关性':>8} {'基准年化':>10} {'策略年化':>10} {'超额年化':>10} {'超额Sharpe':>12}"
    )
    print("-" * 68)
    for r in results:
        print(
            f"{r['benchmark']:<15} {r['correlation']:>8.4f} "
            f"{r['ann_bench_ret']:>9.1%} {r['ann_strat_ret']:>9.1%} "
            f"{r['ann_excess']:>9.1%} {r['excess_sharpe']:>12.4f}"
        )

    best = results[0] if results else None
    if best:
        print(f"\n  最匹配基准: {best['benchmark']} (corr={best['correlation']:.4f})")

    # 保存
    out = PHASE23_CACHE / "step2_benchmark_matching.json"
    with open(out, "w") as f:
        json.dump({"results": results, "best_match": best}, f, indent=2, default=str)
    print(f"\n  Saved: {out}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Step 2 elapsed: {elapsed:.1f} min")
    return {"results": results, "best_match": best}


def _compute_csi2000_proxy(conn, price_data, daily_ret):
    """CSI2000代理: 每月按total_mv排名1001-2000的等权日收益。"""
    cur = conn.cursor()

    # 获取每月月末日期
    all_dates = sorted(price_data["trade_date"].unique())
    monthly = get_monthly_rebal_dates(all_dates)

    proxy_rets = {}
    for i, rd in enumerate(monthly):
        # 查全A市值
        cur.execute(
            "SELECT code, total_mv FROM daily_basic "
            "WHERE trade_date = %s AND total_mv > 0 ORDER BY total_mv DESC",
            (rd,),
        )
        rows = cur.fetchall()
        if len(rows) < 2000:
            continue

        # rank 1001-2000
        proxy_codes = [r[0] for r in rows[1000:2000]]

        # 下一个调仓日前的所有交易日
        next_rd = monthly[i + 1] if i + 1 < len(monthly) else all_dates[-1]
        period_dates = [d for d in all_dates if d > rd and d <= next_rd]

        for td in period_dates:
            if td in daily_ret.index:
                day_rets = daily_ret.loc[td, :].reindex(proxy_codes).dropna()
                if len(day_rets) > 500:
                    proxy_rets[td] = day_rets.mean()

    cur.close()

    if proxy_rets:
        return pd.Series(proxy_rets).sort_index()
    return None


# ─── Step 3: 用匹配基准重算因子IC ────────────────────────


def step3_ic_recomputation(args):
    """Step 3: 用匹配基准替代CSI300重算CORE5因子IC。"""
    print("\n" + "=" * 70)
    print("Step 3: 用匹配基准重算 CORE5 因子 IC")
    print("=" * 70)

    PHASE23_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 加载Step 2结果
    step2_path = PHASE23_CACHE / "step2_benchmark_matching.json"
    if not step2_path.exists():
        print("  ERROR: Step 2 results not found. Run --step2 first.")
        return None
    with open(step2_path) as f:
        step2 = json.load(f)

    best_match = step2["best_match"]
    matched_name = best_match["benchmark"]
    print(f"  Matched benchmark: {matched_name}")

    # 基准代码映射
    bench_code_map = {
        "CSI300": "000300.SH",
        "CSI500": "000905.SH",
        "CSI1000": "000852.SH",
        "CSI2000": "932000.CSI",
    }

    conn = get_db_conn()
    cur = conn.cursor()

    # 加载CSI300 benchmark
    cur.execute(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '000300.SH' ORDER BY trade_date"
    )
    csi300_bench = pd.DataFrame(cur.fetchall(), columns=["trade_date", "close"])
    csi300_bench["close"] = csi300_bench["close"].astype(float)
    print(f"  CSI300: {len(csi300_bench)} days")

    # 加载匹配基准
    matched_code = bench_code_map.get(matched_name)
    if matched_code:
        cur.execute(
            "SELECT trade_date, close FROM index_daily WHERE index_code = %s ORDER BY trade_date",
            (matched_code,),
        )
        rows = cur.fetchall()
        if rows and len(rows) > 100:
            matched_bench = pd.DataFrame(rows, columns=["trade_date", "close"])
            matched_bench["close"] = matched_bench["close"].astype(float)
        else:
            matched_bench = None
    elif "CSI2000" in matched_name:
        # 用proxy
        proxy_path = PHASE23_CACHE / "csi2000_proxy.parquet"
        if proxy_path.exists():
            pd.read_parquet(proxy_path)["daily_ret"]
        else:
            # 需要从step2重算
            print("  CSI2000 proxy not cached, using Tushare fallback...")
            matched_bench = None
            # fallback to CSI1000
            cur.execute(
                "SELECT trade_date, close FROM index_daily "
                "WHERE index_code = '000852.SH' ORDER BY trade_date"
            )
            rows = cur.fetchall()
            matched_bench = pd.DataFrame(rows, columns=["trade_date", "close"])
            matched_bench["close"] = matched_bench["close"].astype(float)
            matched_name = "CSI1000(fallback)"
    elif matched_name == "全A等权":
        # 需要从价格数据构建synthetic close
        print("  Building synthetic close for 全A等权...")
        price_data, _ = load_price_data(2020, 2026)
        valid = price_data[
            (~price_data.get("is_st", pd.Series(False)).fillna(False).astype(bool))
            & (~price_data.get("is_suspended", pd.Series(False)).fillna(False).astype(bool))
            & (price_data.get("board", pd.Series("main")) != "bse")
        ].copy()
        valid = valid.sort_values(["code", "trade_date"])
        valid["prev_adj"] = valid.groupby("code")["adj_close"].shift(1)
        valid["daily_ret"] = valid["adj_close"] / valid["prev_adj"] - 1
        valid = valid[(valid["daily_ret"] > -0.5) & (valid["daily_ret"] < 0.5)]
        all_a_ret = valid.groupby("trade_date")["daily_ret"].mean().sort_index()
        synthetic_close = (1 + all_a_ret).cumprod() * 1000
        matched_bench = pd.DataFrame(
            {
                "trade_date": synthetic_close.index,
                "close": synthetic_close.values,
            }
        )
        del price_data, valid
        gc.collect()
    else:
        matched_bench = None

    if matched_bench is None:
        print("  ERROR: Cannot load matched benchmark. Aborting.")
        conn.close()
        return None

    print(f"  Matched benchmark ({matched_name}): {len(matched_bench)} days")
    cur.close()

    # 加载price_data
    print("\n[1] Loading price data...")
    price_data, _ = load_price_data(2020, 2026)

    # 对每个因子计算IC
    print("\n[2] Computing IC per factor...")
    from engines.ic_calculator import compute_factor_ic_full

    ic_results = []
    for factor in CORE5_FACTORS:
        print(f"\n  --- {factor} ---")
        # 加载单因子
        fdf = pd.read_sql(
            "SELECT code, trade_date, factor_name, neutral_value "
            "FROM factor_values "
            "WHERE factor_name = %s AND trade_date >= %s AND trade_date <= %s "
            "AND neutral_value IS NOT NULL",
            conn,
            params=(factor, date(2020, 1, 1), date(2026, 4, 1)),
        )
        fdf["trade_date"] = pd.to_datetime(fdf["trade_date"]).dt.date
        print(f"    Factor rows: {len(fdf):,}")

        # IC vs CSI300
        result_300 = compute_factor_ic_full(fdf, price_data, csi300_bench, horizon=20)
        stats_300 = result_300["stats"]

        # IC vs matched benchmark
        result_match = compute_factor_ic_full(fdf, price_data, matched_bench, horizon=20)
        stats_match = result_match["stats"]

        ic_300 = stats_300["mean"]
        ic_match = stats_match["mean"]
        delta = ic_match - ic_300

        print(f"    IC(CSI300): {ic_300:.6f}, t={stats_300['t_stat']:.2f}")
        print(f"    IC({matched_name}): {ic_match:.6f}, t={stats_match['t_stat']:.2f}")
        print(f"    Delta: {delta:+.6f}")

        ic_results.append(
            {
                "factor": factor,
                "ic_csi300": round(ic_300, 6),
                "t_csi300": round(stats_300["t_stat"], 2),
                "ic_matched": round(ic_match, 6),
                "t_matched": round(stats_match["t_stat"], 2),
                "delta": round(delta, 6),
                "matched_benchmark": matched_name,
            }
        )

        del fdf, result_300, result_match
        gc.collect()

    conn.close()

    # 汇总表
    print(
        f"\n\n{'因子':<22} {'IC(CSI300)':>12} {'t(300)':>8} {'IC(' + matched_name + ')':>16} {'t(match)':>10} {'Δ':>10}"
    )
    print("-" * 80)
    for r in ic_results:
        print(
            f"{r['factor']:<22} {r['ic_csi300']:>12.6f} {r['t_csi300']:>8.2f} "
            f"{r['ic_matched']:>16.6f} {r['t_matched']:>10.2f} {r['delta']:>+10.6f}"
        )

    # 保存
    out = PHASE23_CACHE / "step3_ic_recomputation.json"
    with open(out, "w") as f:
        json.dump(ic_results, f, indent=2, default=str)
    print(f"\n  Saved: {out}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Step 3 elapsed: {elapsed:.1f} min")
    return ic_results


# ─── Step 4: 市值分位数时间序列 ──────────────────────────


def step4_mcap_percentile_timeseries(args):
    """Step 4: 全A市值分位数时间序列 + 策略定位。"""
    print("\n" + "=" * 70)
    print("Step 4: 市值分位数时间序列")
    print("=" * 70)

    PHASE23_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    conn = get_db_conn()
    cur = conn.cursor()

    # 加载Step 1结果(如果有)
    step1_path = PHASE23_CACHE / "step1_mcap_distribution.json"
    step1_data = None
    if step1_path.exists():
        with open(step1_path) as f:
            step1_data = json.load(f)

    # 目标年份
    target_years = [2014, 2016, 2018, 2020, 2022, 2024]
    results = []

    for year in target_years:
        # 找最近交易日
        target_date = f"{year}-12-31"
        cur.execute(
            "SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= %s",
            (target_date,),
        )
        actual_date = cur.fetchone()[0]
        if actual_date is None:
            print(f"  {year}: no data")
            continue

        # 全A市值
        cur.execute(
            "SELECT code, total_mv FROM daily_basic WHERE trade_date = %s AND total_mv > 0",
            (actual_date,),
        )
        rows = cur.fetchall()
        if not rows:
            continue

        mcaps = np.array([float(r[1]) for r in rows])  # 元
        n_stocks = len(mcaps)
        p25 = np.percentile(mcaps, 25) * YUAN_TO_YI
        p50 = np.percentile(mcaps, 50) * YUAN_TO_YI
        p75 = np.percentile(mcaps, 75) * YUAN_TO_YI

        # 策略定位 (2020+ from Step 1)
        strat_avg = None
        strat_pct = None
        if step1_data and year >= 2020:
            # 找最近的调仓月
            sn_records = step1_data.get("records_sn", [])
            year_recs = [r for r in sn_records if r["rebal_date"].startswith(str(year))]
            if year_recs:
                # 取最后一个月
                last_rec = year_recs[-1]
                strat_avg_yuan = last_rec["avg_mcap_yuan"]
                strat_avg = strat_avg_yuan * YUAN_TO_YI
                strat_pct = float(np.sum(mcaps < strat_avg_yuan) / n_stocks * 100)

        results.append(
            {
                "year": year,
                "actual_date": str(actual_date),
                "n_stocks": n_stocks,
                "p25_yi": round(p25, 1),
                "p50_yi": round(p50, 1),
                "p75_yi": round(p75, 1),
                "strat_avg_yi": round(strat_avg, 1) if strat_avg else None,
                "strat_percentile": round(strat_pct, 1) if strat_pct else None,
            }
        )

    cur.close()
    conn.close()

    # 输出表
    print(
        f"\n{'年份':<6} {'全A股数':>7} {'p25(亿)':>9} {'p50(亿)':>9} {'p75(亿)':>9} {'策略avg(亿)':>12} {'策略分位':>10}"
    )
    print("-" * 68)
    for r in results:
        strat = f"{r['strat_avg_yi']}" if r["strat_avg_yi"] else "-"
        pct = f"{r['strat_percentile']:.1f}%" if r["strat_percentile"] else "-"
        print(
            f"{r['year']:<6} {r['n_stocks']:>7} {r['p25_yi']:>9.1f} {r['p50_yi']:>9.1f} "
            f"{r['p75_yi']:>9.1f} {strat:>12} {pct:>10}"
        )

    # 保存
    out = PHASE23_CACHE / "step4_mcap_percentile.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Saved: {out}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Step 4 elapsed: {elapsed:.1f} min")
    return results


# ─── Step 6: 因子在不同市值分组内的IC ──────────────────────


def step6_ic_by_mcap_group(args):
    """Step 6: 按市值分3组独立计算CORE5因子IC。"""
    print("\n" + "=" * 70)
    print("Step 6: 因子在不同市值分组内的 IC")
    print("=" * 70)

    PHASE23_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 加载匹配基准
    step2_path = PHASE23_CACHE / "step2_benchmark_matching.json"
    matched_bench_name = "CSI300"  # default
    if step2_path.exists():
        with open(step2_path) as f:
            step2 = json.load(f)
        matched_bench_name = step2["best_match"]["benchmark"]

    conn = get_db_conn()
    cur = conn.cursor()

    # 加载基准close
    bench_code_map = {
        "CSI300": "000300.SH",
        "CSI500": "000905.SH",
        "CSI1000": "000852.SH",
    }
    bench_code = bench_code_map.get(matched_bench_name, "000300.SH")
    cur.execute(
        "SELECT trade_date, close FROM index_daily WHERE index_code = %s ORDER BY trade_date",
        (bench_code,),
    )
    bench_df = pd.DataFrame(cur.fetchall(), columns=["trade_date", "close"])
    bench_df["close"] = bench_df["close"].astype(float)
    cur.close()

    print(f"  Benchmark: {matched_bench_name} ({bench_code}), {len(bench_df)} days")

    # 加载price_data
    print("\n[1] Loading price data...")
    price_data, _ = load_price_data(2020, 2026)

    # 一次性计算forward excess returns (最耗内存)
    print("\n[2] Computing forward excess returns...")
    from engines.ic_calculator import (
        compute_forward_excess_returns,
        compute_ic_series,
        summarize_ic_stats,
    )

    fwd_ret = compute_forward_excess_returns(price_data, bench_df, horizon=20)
    print(f"  Forward excess returns: {fwd_ret.shape}")

    # 分组阈值(元, 与MCAP_GROUPS一致)
    groups = {
        "微小盘(<100亿)": (0, 100e8),
        "中盘(100-500亿)": (100e8, 500e8),
        "大盘(>500亿)": (500e8, float("inf")),
    }

    # 对每个因子
    print("\n[3] Computing IC by factor × size group...")
    all_results = []

    for factor in CORE5_FACTORS:
        print(f"\n  --- {factor} ---")

        # JOIN factor_values + daily_basic
        fdf = pd.read_sql(
            "SELECT f.code, f.trade_date, f.neutral_value, db.total_mv "
            "FROM factor_values f "
            "JOIN daily_basic db ON f.code = db.code AND f.trade_date = db.trade_date "
            "WHERE f.factor_name = %s AND f.trade_date >= %s AND f.trade_date <= %s "
            "AND f.neutral_value IS NOT NULL AND db.total_mv > 0",
            conn,
            params=(factor, date(2020, 1, 1), date(2026, 4, 1)),
        )
        fdf["trade_date"] = pd.to_datetime(fdf["trade_date"]).dt.date
        print(f"    Factor+mcap rows: {len(fdf):,}")

        factor_result = {"factor": factor}

        # 全截面IC
        factor_wide_all = fdf.pivot_table(
            index="trade_date", columns="code", values="neutral_value", aggfunc="first"
        ).sort_index()
        ic_all = compute_ic_series(factor_wide_all, fwd_ret)
        stats_all = summarize_ic_stats(ic_all)
        factor_result["full_ic"] = round(stats_all["mean"], 6)
        factor_result["full_t"] = round(stats_all["t_stat"], 2)
        print(f"    全截面: IC={stats_all['mean']:.6f}, t={stats_all['t_stat']:.2f}")
        del factor_wide_all

        # 分组IC
        for gname, (lo, hi) in groups.items():
            group_data = fdf[(fdf["total_mv"] >= lo) & (fdf["total_mv"] < hi)]
            if group_data.empty:
                factor_result[f"{gname}_ic"] = None
                factor_result[f"{gname}_t"] = None
                continue

            grp_wide = group_data.pivot_table(
                index="trade_date", columns="code", values="neutral_value", aggfunc="first"
            ).sort_index()

            ic_grp = compute_ic_series(grp_wide, fwd_ret)
            stats_grp = summarize_ic_stats(ic_grp)
            factor_result[f"{gname}_ic"] = round(stats_grp["mean"], 6)
            factor_result[f"{gname}_t"] = round(stats_grp["t_stat"], 2)
            n_codes = len(group_data["code"].unique())
            print(
                f"    {gname}: IC={stats_grp['mean']:.6f}, t={stats_grp['t_stat']:.2f}, "
                f"n_codes={n_codes}"
            )
            del grp_wide

        all_results.append(factor_result)
        del fdf
        gc.collect()

    conn.close()

    # 汇总表
    g_names = list(groups.keys())
    header = f"{'因子':<22} {'全截面IC':>10} {'t':>6}"
    for gn in g_names:
        header += f" {gn[:6] + 'IC':>10} {'t':>6}"
    header += f" {'中盘t>2.5':>10}"
    print(f"\n{header}")
    print("-" * len(header))

    for r in all_results:
        line = f"{r['factor']:<22} {r['full_ic']:>10.6f} {r['full_t']:>6.2f}"
        for gn in g_names:
            ic = r.get(f"{gn}_ic")
            t = r.get(f"{gn}_t")
            if ic is not None:
                line += f" {ic:>10.6f} {t:>6.2f}"
            else:
                line += f" {'N/A':>10} {'N/A':>6}"
        # 中盘显著性判断
        mid_t = r.get(f"{g_names[1]}_t")
        sig = "✅" if mid_t and abs(mid_t) > 2.5 else "❌"
        line += f" {sig:>10}"
        print(line)

    # 保存
    out = PHASE23_CACHE / "step6_ic_by_mcap_group.json"
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Saved: {out}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Step 6 elapsed: {elapsed:.1f} min")
    return all_results


# ─── Step 5: 综合结论 ────────────────────────────────────


def step5_conclusions(args):
    """Step 5: 综合所有结果回答6个核心问题。"""
    print("\n" + "=" * 70)
    print("Step 5: 综合结论")
    print("=" * 70)

    # 加载所有缓存
    data = {}
    for fname, key in [
        ("step1_mcap_distribution.json", "step1"),
        ("step2_benchmark_matching.json", "step2"),
        ("step3_ic_recomputation.json", "step3"),
        ("step4_mcap_percentile.json", "step4"),
        ("step6_ic_by_mcap_group.json", "step6"),
    ]:
        path = PHASE23_CACHE / fname
        if path.exists():
            with open(path) as f:
                data[key] = json.load(f)
            print(f"  Loaded: {fname}")
        else:
            print(f"  Missing: {fname}")

    print("\n" + "=" * 70)
    print("综合诊断结论")
    print("=" * 70)

    # Q1: 策略是什么策略?
    if "step1" in data:
        s = data["step1"]["sn"]
        print("\n1. 策略市值定位:")
        print(f"   Top-20 平均市值: {s['avg_mcap_yi']} 亿元")
        print(f"   Top-20 中位数市值: {s['median_mcap_yi']} 亿元")
        for gname, pct in s["group_pcts"].items():
            if pct > 5:
                print(f"   {gname}: {pct}%")

        no_sn = data["step1"]["no_sn"]
        print(
            f"\n   SN效果: 平均市值 {no_sn['avg_mcap_yi']}亿 → {s['avg_mcap_yi']}亿 "
            f"({(s['avg_mcap_yi'] / no_sn['avg_mcap_yi'] - 1) * 100:+.0f}%)"
        )

    # Q2: 基准
    if "step2" in data:
        best = data["step2"]["best_match"]
        print("\n2. 基准匹配度:")
        print(f"   最匹配基准: {best['benchmark']} (corr={best['correlation']})")
        for r in data["step2"]["results"]:
            print(f"   {r['benchmark']}: corr={r['correlation']}, 超额Sharpe={r['excess_sharpe']}")

    # Q3: IC来源
    if "step3" in data:
        print("\n3. IC来源分析(CSI300 vs 匹配基准):")
        for r in data["step3"]:
            sign_change = (r["ic_csi300"] > 0) != (r["ic_matched"] > 0)
            pct_change = (r["delta"] / abs(r["ic_csi300"])) * 100 if r["ic_csi300"] != 0 else 0
            status = "⚠️方向反转" if sign_change else f"Δ{pct_change:+.0f}%"
            print(f"   {r['factor']}: {r['ic_csi300']:.4f} → {r['ic_matched']:.4f} ({status})")

    # Q4: 分位数
    if "step4" in data:
        print("\n4. 市值分位数定位:")
        for r in data["step4"]:
            if r["strat_percentile"]:
                print(
                    f"   {r['year']}: 策略avg={r['strat_avg_yi']}亿, "
                    f"处于全A {r['strat_percentile']:.0f}%分位"
                )

    # Q5: 流动性
    if "step1" in data:
        s = data["step1"]["sn"]
        print("\n5. 流动性评估:")
        print(f"   平均日均成交额: {s['avg_amount_wan']:.0f} 万元")
        print(f"   最低日均成交额: {s['min_amount_wan']:.0f} 万元")
        if s["min_amount_wan"] < 500:
            print("   ⚠️ 存在日均成交额<500万的持仓, 100万资金可能面临流动性风险")
        else:
            print("   ✅ 日均成交额>500万, 100万资金规模基本可执行")

    # Q6: 分组IC
    if "step6" in data:
        print("\n6. 因子跨市值有效性:")
        for r in data["step6"]:
            list(MCAP_GROUPS.keys())
            # 简化的3组名
            micro_t = r.get("微小盘(<100亿)_t", 0) or 0
            mid_t = r.get("中盘(100-500亿)_t", 0) or 0
            large_t = r.get("大盘(>500亿)_t", 0) or 0
            if abs(mid_t) > 2.5:
                verdict = "✅ 中盘有效"
            elif abs(micro_t) > 2.5:
                verdict = "⚠️ 仅微盘有效"
            else:
                verdict = "❌ 各组均不显著"
            print(
                f"   {r['factor']}: 微盘t={micro_t:.1f}, 中盘t={mid_t:.1f}, 大盘t={large_t:.1f} → {verdict}"
            )


# ─── Main ────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Phase 2.3前置: 策略市值暴露诊断")
    parser.add_argument("--step1", action="store_true", help="Step 1: 持仓市值分布")
    parser.add_argument("--step2", action="store_true", help="Step 2: 基准匹配度检验")
    parser.add_argument("--step3", action="store_true", help="Step 3: IC重算(匹配基准)")
    parser.add_argument("--step4", action="store_true", help="Step 4: 市值分位数时间序列")
    parser.add_argument("--step5", action="store_true", help="Step 5: 综合结论")
    parser.add_argument("--step6", action="store_true", help="Step 6: 分组IC")
    parser.add_argument("--all", action="store_true", help="运行全部(按依赖顺序)")
    args = parser.parse_args()

    if not any([args.step1, args.step2, args.step3, args.step4, args.step5, args.step6, args.all]):
        parser.print_help()
        return

    t_total = time.time()

    if args.step1 or args.all:
        step1_portfolio_mcap_distribution(args)
        gc.collect()

    if args.step2 or args.all:
        step2_benchmark_matching(args)
        gc.collect()

    if args.step3 or args.all:
        step3_ic_recomputation(args)
        gc.collect()

    if args.step4 or args.all:
        step4_mcap_percentile_timeseries(args)
        gc.collect()

    if args.step6 or args.all:
        step6_ic_by_mcap_group(args)
        gc.collect()

    if args.step5 or args.all:
        step5_conclusions(args)

    elapsed = (time.time() - t_total) / 60
    print(f"\n  Total elapsed: {elapsed:.1f} min")


if __name__ == "__main__":
    main()
