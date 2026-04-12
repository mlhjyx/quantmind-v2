#!/usr/bin/env python
"""Phase 2.4: Research Exploration — universe filtering, factor combinations, parameter sensitivity.

Root cause diagnosis of EW+SN performance, mcap-segmented backtests,
factor combination experiments, and parameter sensitivity analysis.

Usage:
    cd backend && python ../scripts/research/phase24_research_exploration.py --part0
    cd backend && python ../scripts/research/phase24_research_exploration.py --part1
    cd backend && python ../scripts/research/phase24_research_exploration.py --part2
    cd backend && python ../scripts/research/phase24_research_exploration.py --part3
    cd backend && python ../scripts/research/phase24_research_exploration.py --part4
    cd backend && python ../scripts/research/phase24_research_exploration.py --part5
    cd backend && python ../scripts/research/phase24_research_exploration.py --all
    cd backend && python ../scripts/research/phase24_research_exploration.py --exp 1.3
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
PHASE22_CACHE = CACHE_DIR / "phase22"
PHASE24_CACHE = CACHE_DIR / "phase24"
BASELINE_CACHE = CACHE_DIR / "baseline"

# ─── Constants ──────────────────────────────────────────────

CORE5_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
CORE5_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}
CORE4_FACTORS = [f for f in CORE5_FACTORS if f != "amihud_20"]
CORE4_DIRECTIONS = {k: v for k, v in CORE5_DIRECTIONS.items() if k != "amihud_20"}
SN_BETA = 0.50

# daily_basic.total_mv 在DB中是元(DataPipeline Step 3-A已转换: Tushare万元x10000→元)
YUAN_TO_YI = 1e-8  # 元 → 亿元

MCAP_RANGES = {
    "全A+SN": (0, float("inf"), 0.50),
    "微小盘(<100亿)": (0, 100e8, 0.0),
    "小盘(100-300亿)": (100e8, 300e8, 0.0),
    "中盘(100-500亿)": (100e8, 500e8, 0.0),
    "中大盘(>200亿)": (200e8, float("inf"), 0.0),
    "大盘(>500亿)": (500e8, float("inf"), 0.0),
}

OOS_START = date(2020, 1, 1)
OOS_END = date(2026, 4, 1)
BASELINE_SHARPE = 0.6211  # EW CORE5 + SN b=0.50 from Phase 2.2


# ─── Shared Utility Functions ───────────────────────────────


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

    注意: parquet的raw_value列是WLS中性化值, 但run_hybrid_backtest需要raw_value列名。
    此函数不做rename, 保持raw_value列名以兼容回测引擎。
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


def compute_metrics(nav: pd.Series) -> dict:
    """Sharpe/MDD/annual return from NAV series."""
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe

    returns = nav.pct_change().dropna()
    n_days = len(nav)
    total_ret = nav.iloc[-1] / nav.iloc[0] - 1.0
    ann_ret = (1 + total_ret) ** (TRADING_DAYS_PER_YEAR / max(n_days, 1)) - 1.0
    return {
        "sharpe": round(float(calc_sharpe(returns)), 4),
        "mdd": round(float(calc_max_drawdown(nav)), 4),
        "annual_return": round(float(ann_ret), 4),
        "total_return": round(float(total_ret), 4),
        "n_days": n_days,
    }


def load_mcap_data(start_date, end_date, conn) -> pd.DataFrame:
    """Load total_mv from daily_basic for mcap filtering."""
    df = pd.read_sql(
        """SELECT code, trade_date, total_mv FROM daily_basic
           WHERE trade_date >= %(s)s AND trade_date <= %(e)s AND total_mv > 0""",
        conn,
        params={"s": start_date, "e": end_date},
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["total_mv"] = df["total_mv"].astype(float)
    print(f"  Mcap data: {len(df):,} rows ({df['trade_date'].min()} ~ {df['trade_date'].max()})")
    return df


def filter_factor_by_mcap(
    factor_df: pd.DataFrame,
    mcap_df: pd.DataFrame,
    min_yuan: float = 0,
    max_yuan: float = float("inf"),
) -> pd.DataFrame:
    """Filter factor_df to stocks within market cap range on each date."""
    merged = factor_df.merge(
        mcap_df[["code", "trade_date", "total_mv"]],
        on=["code", "trade_date"],
        how="inner",
    )
    mask = (merged["total_mv"] >= min_yuan) & (merged["total_mv"] < max_yuan)
    result = merged.loc[mask].drop(columns=["total_mv"])
    return result


def load_factors_from_db(factor_names, start_date, end_date, conn) -> pd.DataFrame:
    """Load arbitrary factors from factor_values DB table."""
    placeholders = ",".join(["%s"] * len(factor_names))
    query = f"""
        SELECT code, trade_date, factor_name,
               COALESCE(neutral_value, raw_value) AS raw_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date >= %s AND trade_date <= %s
          AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
    """
    params = list(factor_names) + [start_date, end_date]
    df = pd.read_sql(query, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    print(f"  DB factors: {len(df):,} rows, factors: {sorted(df['factor_name'].unique())}")
    return df


def compute_composite_scores(day_factors: pd.DataFrame, directions: dict) -> pd.Series:
    """等权复合分 = sum(raw_value x direction) / n.

    Args:
        day_factors: DataFrame with (code, factor_name, raw_value)
        directions: dict {factor_name: +1/-1}

    Returns:
        Series (code -> score, descending)
    """
    wide = day_factors.pivot_table(index="code", columns="factor_name", values="raw_value")
    avail = [f for f in directions if f in wide.columns]
    if not avail:
        return pd.Series(dtype=float)

    composite = pd.Series(0.0, index=wide.index)
    for f in avail:
        composite += wide[f].fillna(0) * directions[f]
    composite /= len(avail)
    return composite.sort_values(ascending=False, kind="mergesort")


def run_standard_experiment(
    factor_df: pd.DataFrame,
    directions: dict,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    top_n: int = 20,
    rebalance_freq: str = "monthly",
    sn_beta: float = 0.0,
    conn=None,
    label: str = "",
) -> dict:
    """Standard experiment wrapper: factor_df -> run_hybrid_backtest -> metrics."""
    from engines.backtest.config import BacktestConfig
    from engines.backtest.runner import run_hybrid_backtest
    from engines.signal_engine import SignalConfig

    bt_config = BacktestConfig(
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        initial_capital=1_000_000,
    )
    sig_config = SignalConfig(
        factor_names=list(directions.keys()),
        top_n=top_n,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        size_neutral_beta=sn_beta,
    )
    result = run_hybrid_backtest(
        factor_df=factor_df,
        directions=directions,
        price_data=price_data,
        config=bt_config,
        benchmark_data=benchmark_data,
        signal_config=sig_config,
        conn=conn,
    )
    metrics = compute_metrics(result.daily_nav)
    metrics["label"] = label
    metrics["n_rebal"] = len(result.holdings_history) if hasattr(result, "holdings_history") else 0
    return metrics


def compute_universe_size(
    mcap_df: pd.DataFrame, min_yuan: float, max_yuan: float, dates
) -> pd.Series:
    """Count stocks in mcap range per date."""
    filtered = mcap_df[(mcap_df["total_mv"] >= min_yuan) & (mcap_df["total_mv"] < max_yuan)]
    counts = filtered.groupby("trade_date")["code"].nunique()
    result = counts.reindex(dates).fillna(0).astype(int)
    return result


def predictions_to_backtest(
    oos_df: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    top_n: int = 20,
    ln_mcap_pivot: pd.DataFrame | None = None,
    sn_beta: float = 0.0,
    label: str = "",
) -> dict:
    """OOS predictions -> target_portfolios -> SimpleBacktester -> metrics."""
    from engines.backtest import BacktestConfig, SimpleBacktester
    from engines.size_neutral import apply_size_neutral

    all_oos_dates = sorted(oos_df["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_oos_dates)
    monthly_set = set(monthly_dates)

    target_portfolios = {}
    for td, group in oos_df.groupby("trade_date"):
        if td not in monthly_set:
            continue

        scores = group.set_index("code")["predicted"].sort_values(ascending=False)

        if sn_beta > 0 and ln_mcap_pivot is not None and td in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[td], sn_beta)

        top = scores.nlargest(top_n)
        if len(top) == 0:
            continue
        w = 1.0 / len(top)
        target_portfolios[td] = {code: w for code in top.index}

    if not target_portfolios:
        return {"sharpe": 0.0, "mdd": 0.0, "annual_return": 0.0, "n_rebal": 0, "label": label}

    bt_config = BacktestConfig(top_n=top_n, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config)
    result = tester.run(target_portfolios, price_data, benchmark_data)

    metrics = compute_metrics(result.daily_nav)
    metrics["n_rebal"] = len(target_portfolios)
    metrics["label"] = label
    return metrics


def save_result(result, name: str):
    """Save result dict to cache/phase24/{name}.json."""

    def default_serializer(obj):
        if isinstance(obj, (date, pd.Timestamp)):
            return str(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    fp = PHASE24_CACHE / f"{name}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=default_serializer)
    print(f"  Saved: {fp}")


def load_cached(name: str) -> dict | None:
    """Load from cache if exists."""
    fp = PHASE24_CACHE / f"{name}.json"
    if fp.exists():
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    return None


# ═══════════════════════════════════════════════════════════════
# Part 0: Root Cause Diagnosis
# ═══════════════════════════════════════════════════════════════


def part0_1_cost_attribution():
    """Part 0.1: EW+SN vs ML 持仓市值/流动性/重叠度对比。"""
    print("\n" + "=" * 70)
    print("Part 0.1: Cost Attribution — EW+SN vs LambdaRank 持仓对比")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)

    conn = get_db_conn()
    print("  Loading mcap data...")
    mcap_df = load_mcap_data(OOS_START, OOS_END, conn)

    print("  Loading ln_mcap for SN...")
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
    print(f"  ln_mcap pivot: {ln_mcap_pivot.shape}")

    # 2. Load LambdaRank predictions (optional)
    lr_path = PHASE22_CACHE / "oos_predictions_lambdarank.parquet"
    lr_df = None
    if lr_path.exists():
        lr_df = pd.read_parquet(lr_path)
        lr_df["trade_date"] = pd.to_datetime(lr_df["trade_date"]).dt.date
        print(f"  LambdaRank predictions: {len(lr_df):,} rows")
    else:
        print("  WARNING: LambdaRank predictions not found, skipping ML comparison")

    # 3. Build monthly portfolios and compare
    print("\n[2] Building monthly portfolios...")
    all_factor_dates = sorted(factor_df["trade_date"].unique())
    all_price_dates = sorted(price_data["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [
        d
        for d in monthly_dates
        if d >= OOS_START
        and d <= OOS_END
        and d >= all_factor_dates[0]
        and d <= all_factor_dates[-1]
    ]
    print(f"  Rebalance dates: {len(monthly_dates)} months")

    # Build mcap lookup
    mcap_lookup = {}
    for _, row in mcap_df.iterrows():
        mcap_lookup[(row["code"], row["trade_date"])] = row["total_mv"]

    # LambdaRank monthly dates
    lr_monthly_set = set()
    if lr_df is not None:
        lr_dates = sorted(lr_df["trade_date"].unique())
        lr_monthly_dates = get_monthly_rebal_dates(lr_dates)
        lr_monthly_set = set(lr_monthly_dates)

    factor_date_list = sorted(factor_df["trade_date"].unique())
    records = []

    for i, rd in enumerate(monthly_dates):
        # Find closest factor date
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]

        # EW composite scores
        day_data = factor_df[factor_df["trade_date"] == fd]
        if day_data.empty:
            continue

        exclude = build_exclusion_set(price_data, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]

        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if len(scores) < 20:
            continue

        # No-SN Top20
        top_no_sn = scores.nlargest(20).index.tolist()

        # SN Top20
        top_sn = top_no_sn
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
            adj_scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)
            top_sn = adj_scores.nlargest(20).index.tolist()

        # LambdaRank Top20
        top_lr = []
        if lr_df is not None and rd in lr_monthly_set:
            lr_day = lr_df[lr_df["trade_date"] == rd]
            if not lr_day.empty:
                lr_scores = lr_day.set_index("code")["predicted"].sort_values(ascending=False)
                if ln_mcap_pivot is not None and rd in ln_mcap_pivot.index:
                    lr_scores = apply_size_neutral(lr_scores, ln_mcap_pivot.loc[rd], SN_BETA)
                top_lr = lr_scores.nlargest(20).index.tolist()

        # Market cap stats
        def mcap_stats(codes, td):
            mcaps = [mcap_lookup.get((c, td), np.nan) for c in codes]
            mcaps_valid = [m for m in mcaps if not np.isnan(m)]
            if not mcaps_valid:
                return {"avg_mcap_yi": np.nan, "median_mcap_yi": np.nan, "n_valid": 0}
            arr = np.array(mcaps_valid)
            return {
                "avg_mcap_yi": float(np.mean(arr) * YUAN_TO_YI),
                "median_mcap_yi": float(np.median(arr) * YUAN_TO_YI),
                "n_valid": len(mcaps_valid),
            }

        ew_stats = mcap_stats(top_sn, rd)
        lr_stats = (
            mcap_stats(top_lr, rd)
            if top_lr
            else {"avg_mcap_yi": np.nan, "median_mcap_yi": np.nan, "n_valid": 0}
        )

        # Overlap
        overlap_ew_lr = len(set(top_sn) & set(top_lr)) if top_lr else 0

        # Turnover (vs previous month)
        records.append(
            {
                "date": str(rd),
                "ew_sn_avg_mcap_yi": ew_stats["avg_mcap_yi"],
                "ew_sn_median_mcap_yi": ew_stats["median_mcap_yi"],
                "lr_avg_mcap_yi": lr_stats["avg_mcap_yi"],
                "lr_median_mcap_yi": lr_stats["median_mcap_yi"],
                "overlap_ew_lr": overlap_ew_lr,
                "ew_sn_codes": top_sn,
                "lr_codes": top_lr,
            }
        )

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(monthly_dates)} months")

    conn.close()

    # 4. Aggregate
    print(f"\n[3] Aggregating {len(records)} months...")
    rdf = pd.DataFrame(records)

    avg_ew_mcap = rdf["ew_sn_avg_mcap_yi"].mean()
    avg_lr_mcap = rdf["lr_avg_mcap_yi"].mean()
    med_ew_mcap = rdf["ew_sn_median_mcap_yi"].mean()
    med_lr_mcap = rdf["lr_median_mcap_yi"].mean()
    avg_overlap = rdf["overlap_ew_lr"].mean()

    # Turnover: fraction of codes that changed month-to-month
    ew_turnovers = []
    for i in range(1, len(records)):
        prev_codes = set(records[i - 1]["ew_sn_codes"])
        curr_codes = set(records[i]["ew_sn_codes"])
        if prev_codes:
            to = 1.0 - len(prev_codes & curr_codes) / max(len(prev_codes), 1)
            ew_turnovers.append(to)
    avg_ew_turnover = float(np.mean(ew_turnovers)) if ew_turnovers else 0.0

    lr_turnovers = []
    for i in range(1, len(records)):
        prev_codes = set(records[i - 1]["lr_codes"])
        curr_codes = set(records[i]["lr_codes"])
        if prev_codes and curr_codes:
            to = 1.0 - len(prev_codes & curr_codes) / max(len(prev_codes), 1)
            lr_turnovers.append(to)
    avg_lr_turnover = float(np.mean(lr_turnovers)) if lr_turnovers else 0.0

    # Print
    print(f"\n{'Metric':<30} {'EW+SN':>12} {'LambdaRank+SN':>14}")
    print("-" * 60)
    print(f"{'Avg mcap (yi yuan)':<30} {avg_ew_mcap:>12.1f} {avg_lr_mcap:>14.1f}")
    print(f"{'Median mcap (yi yuan)':<30} {med_ew_mcap:>12.1f} {med_lr_mcap:>14.1f}")
    print(f"{'Avg overlap (of 20)':<30} {avg_overlap:>12.1f} {'':>14}")
    print(f"{'Avg monthly turnover':<30} {avg_ew_turnover:>12.2%} {avg_lr_turnover:>14.2%}")

    result = {
        "n_months": len(records),
        "avg_ew_mcap_yi": round(avg_ew_mcap, 1),
        "med_ew_mcap_yi": round(med_ew_mcap, 1),
        "avg_lr_mcap_yi": round(avg_lr_mcap, 1) if not np.isnan(avg_lr_mcap) else None,
        "med_lr_mcap_yi": round(med_lr_mcap, 1) if not np.isnan(med_lr_mcap) else None,
        "avg_overlap_ew_lr": round(avg_overlap, 1),
        "avg_ew_turnover": round(avg_ew_turnover, 4),
        "avg_lr_turnover": round(avg_lr_turnover, 4),
    }
    save_result(result, "part0_1_cost_attribution")
    print(f"\n  Part 0.1 elapsed: {(time.time() - t0) / 60:.1f} min")
    return result


def part0_2_annual_decomposition():
    """Part 0.2: EW+SN vs LambdaRank year-by-year Sharpe comparison."""
    print("\n" + "=" * 70)
    print("Part 0.2: Annual Decomposition — EW+SN vs LambdaRank by Year")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load EW+SN yearly breakdown from baseline cache
    print("\n[1] Loading EW+SN yearly breakdown...")
    yearly_path = BASELINE_CACHE / "yearly_breakdown.json"
    ew_yearly = {}
    if yearly_path.exists():
        with open(yearly_path) as f:
            yb = json.load(f)
        # Extract yearly Sharpe from breakdown (format depends on how it was saved)
        if isinstance(yb, dict):
            for key, val in yb.items():
                # Try parsing year keys
                try:
                    yr = int(key)
                    if isinstance(val, dict) and "sharpe" in val:
                        ew_yearly[yr] = val["sharpe"]
                except (ValueError, TypeError):
                    pass
            # Fallback: check nested structures
            if not ew_yearly and "yearly" in yb:
                for key, val in yb["yearly"].items():
                    try:
                        yr = int(key)
                        if isinstance(val, dict) and "sharpe" in val:
                            ew_yearly[yr] = val["sharpe"]
                    except (ValueError, TypeError):
                        pass
        print(f"  EW+SN yearly: {ew_yearly}")
    else:
        print("  WARNING: yearly_breakdown.json not found")

    # 2. Run LambdaRank backtest by year
    print("\n[2] Loading LambdaRank predictions and running per-year backtest...")
    lr_path = PHASE22_CACHE / "oos_predictions_lambdarank.parquet"
    lr_yearly = {}

    if lr_path.exists():
        lr_df = pd.read_parquet(lr_path)
        lr_df["trade_date"] = pd.to_datetime(lr_df["trade_date"]).dt.date

        price_data, bench = load_price_data(2020, 2026)

        conn = get_db_conn()
        from engines.size_neutral import load_ln_mcap_pivot

        ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
        conn.close()

        # Per-year backtest
        lr_df["year"] = lr_df["trade_date"].apply(lambda d: d.year)
        years = sorted(lr_df["year"].unique())

        for yr in years:
            yr_data = lr_df[lr_df["year"] == yr].copy()
            yr_start = date(yr, 1, 1)
            yr_end = date(yr, 12, 31)

            yr_price = price_data[
                (price_data["trade_date"] >= yr_start) & (price_data["trade_date"] <= yr_end)
            ].copy()
            yr_bench = bench[
                (bench["trade_date"] >= yr_start) & (bench["trade_date"] <= yr_end)
            ].copy()

            if yr_price.empty or yr_data.empty:
                continue

            metrics = predictions_to_backtest(
                yr_data,
                yr_price,
                yr_bench,
                top_n=20,
                ln_mcap_pivot=ln_mcap_pivot,
                sn_beta=SN_BETA,
                label=f"LR+SN {yr}",
            )
            lr_yearly[yr] = metrics["sharpe"]
            print(f"  {yr}: LR+SN Sharpe={metrics['sharpe']:.4f}")
    else:
        print("  WARNING: LambdaRank predictions not found, skipping")

    # 3. If no EW yearly, run EW+SN backtest per year too
    if not ew_yearly:
        print("\n[3] Running EW+SN per-year backtest...")
        factor_df = load_factor_from_parquet(2020, 2026)
        price_data, bench = load_price_data(2020, 2026)
        conn = get_db_conn()

        for yr in range(2020, 2026):
            yr_start = date(yr, 1, 1)
            yr_end = date(yr, 12, 31)

            yr_factor = factor_df[
                (factor_df["trade_date"] >= yr_start) & (factor_df["trade_date"] <= yr_end)
            ].copy()
            yr_price = price_data[
                (price_data["trade_date"] >= yr_start) & (price_data["trade_date"] <= yr_end)
            ].copy()
            yr_bench = bench[
                (bench["trade_date"] >= yr_start) & (bench["trade_date"] <= yr_end)
            ].copy()

            if yr_factor.empty or yr_price.empty:
                continue

            metrics = run_standard_experiment(
                yr_factor,
                CORE5_DIRECTIONS,
                yr_price,
                yr_bench,
                top_n=20,
                sn_beta=SN_BETA,
                conn=conn,
                label=f"EW+SN {yr}",
            )
            ew_yearly[yr] = metrics["sharpe"]
            print(f"  {yr}: EW+SN Sharpe={metrics['sharpe']:.4f}")

        conn.close()

    # 4. Print comparison table
    all_years = sorted(set(list(ew_yearly.keys()) + list(lr_yearly.keys())))
    print(f"\n{'Year':<8} {'EW+SN':>10} {'LR+SN':>10} {'Diff':>10}")
    print("-" * 42)
    for yr in all_years:
        ew_s = ew_yearly.get(yr)
        lr_s = lr_yearly.get(yr)
        ew_str = f"{ew_s:.4f}" if ew_s is not None else "N/A"
        lr_str = f"{lr_s:.4f}" if lr_s is not None else "N/A"
        diff_str = ""
        if ew_s is not None and lr_s is not None:
            diff = lr_s - ew_s
            diff_str = f"{diff:+.4f}"
        print(f"{yr:<8} {ew_str:>10} {lr_str:>10} {diff_str:>10}")

    result = {
        "ew_yearly": {str(k): v for k, v in ew_yearly.items()},
        "lr_yearly": {str(k): v for k, v in lr_yearly.items()},
    }
    save_result(result, "part0_2_annual_decomposition")
    print(f"\n  Part 0.2 elapsed: {(time.time() - t0) / 60:.1f} min")
    return result


def part0_3_rebalance_alpha():
    """Part 0.3: Rebalance alpha = Standard monthly rebal vs buy-and-hold."""
    print("\n" + "=" * 70)
    print("Part 0.3: Rebalance Alpha — Monthly Rebal vs Buy-and-Hold")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    # 2. Backtest A: Standard monthly rebalance (EW+SN)
    print("\n[2] Backtest A: Monthly rebalance EW+SN...")
    t1 = time.time()
    metrics_rebal = run_standard_experiment(
        factor_df,
        CORE5_DIRECTIONS,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="Monthly Rebalance",
    )
    print(
        f"  Sharpe={metrics_rebal['sharpe']}, MDD={metrics_rebal['mdd']}, "
        f"AnnRet={metrics_rebal['annual_return']} ({time.time() - t1:.1f}s)"
    )

    # 3. Backtest B: Buy-and-hold (only first month's portfolio)
    print("\n[3] Backtest B: Buy-and-hold (first month only)...")
    t1 = time.time()

    from engines.backtest.config import BacktestConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    # Build the first month's portfolio manually
    all_factor_dates = sorted(factor_df["trade_date"].unique())
    all_price_dates = sorted(price_data["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [
        d
        for d in monthly_dates
        if d >= OOS_START
        and d <= OOS_END
        and d >= all_factor_dates[0]
        and d <= all_factor_dates[-1]
    ]

    if not monthly_dates:
        print("  ERROR: No rebalance dates found")
        conn.close()
        return None

    first_rd = monthly_dates[0]
    factor_date_list = sorted(factor_df["trade_date"].unique())
    idx = bisect_right(factor_date_list, first_rd)
    fd = factor_date_list[max(idx - 1, 0)]

    day_data = factor_df[factor_df["trade_date"] == fd]
    exclude = build_exclusion_set(price_data, first_rd)
    day_data = day_data[~day_data["code"].isin(exclude)]

    scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)

    # Apply SN
    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
    if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
        scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)

    top20 = scores.nlargest(20)
    w = 1.0 / len(top20)
    target_portfolios = {first_rd: {code: w for code in top20.index}}

    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config)
    result_bh = tester.run(target_portfolios, price_data, bench)

    metrics_bh = compute_metrics(result_bh.daily_nav)
    metrics_bh["label"] = "Buy-and-Hold (1st month)"
    metrics_bh["n_rebal"] = 1

    print(
        f"  Sharpe={metrics_bh['sharpe']}, MDD={metrics_bh['mdd']}, "
        f"AnnRet={metrics_bh['annual_return']} ({time.time() - t1:.1f}s)"
    )

    conn.close()

    # 4. Rebalance alpha
    rebal_alpha = metrics_rebal["sharpe"] - metrics_bh["sharpe"]
    print(f"\n{'Method':<30} {'Sharpe':>10} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 65)
    print(
        f"{'Monthly Rebalance':<30} {metrics_rebal['sharpe']:>10.4f} "
        f"{metrics_rebal['mdd']:>10.4f} {metrics_rebal['annual_return']:>10.4f}"
    )
    print(
        f"{'Buy-and-Hold (1st month)':<30} {metrics_bh['sharpe']:>10.4f} "
        f"{metrics_bh['mdd']:>10.4f} {metrics_bh['annual_return']:>10.4f}"
    )
    print(f"\n  Rebalance Alpha (Sharpe diff): {rebal_alpha:+.4f}")

    result = {
        "rebalance": metrics_rebal,
        "buy_and_hold": metrics_bh,
        "rebalance_alpha_sharpe": round(rebal_alpha, 4),
    }
    save_result(result, "part0_3_rebalance_alpha")
    print(f"\n  Part 0.3 elapsed: {(time.time() - t0) / 60:.1f} min")
    return result


def part0_5_composite_ic():
    """Part 0.5: Composite score IC analysis (Rank IC of equal-weight score)."""
    print("\n" + "=" * 70)
    print("Part 0.5: Composite Score IC Analysis")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)

    # 2. Build composite score wide table
    print("\n[2] Computing composite scores for each date...")
    all_dates = sorted(factor_df["trade_date"].unique())
    composite_records = []

    for td in all_dates:
        day_data = factor_df[factor_df["trade_date"] == td]
        if day_data.empty:
            continue
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        for code, score in scores.items():
            composite_records.append({"trade_date": td, "code": code, "score": score})

    composite_df = pd.DataFrame(composite_records)
    print(f"  Composite scores: {len(composite_df):,} rows, {len(all_dates)} dates")

    # Pivot to wide: (date x code)
    composite_wide = composite_df.pivot_table(index="trade_date", columns="code", values="score")
    print(f"  Composite wide: {composite_wide.shape}")

    # 3. Compute forward excess returns
    print("\n[3] Computing forward excess returns (horizon=20)...")
    from engines.ic_calculator import compute_forward_excess_returns, compute_ic_series

    fwd_ret = compute_forward_excess_returns(
        price_df=price_data,
        benchmark_df=bench,
        horizon=20,
        price_col="adj_close",
        benchmark_price_col="close",
    )
    print(f"  Forward excess returns: {fwd_ret.shape}")

    # 4. Compute IC series
    print("\n[4] Computing IC series...")
    ic_series = compute_ic_series(composite_wide, fwd_ret)
    ic_clean = ic_series.dropna()

    ic_mean = float(ic_clean.mean())
    ic_std = float(ic_clean.std())
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_clean))) if ic_std > 0 else 0.0
    pct_positive = float((ic_clean > 0).mean())

    print("\n  Composite IC Results:")
    print(f"    IC Mean:     {ic_mean:.4f}")
    print(f"    IC Std:      {ic_std:.4f}")
    print(f"    IC IR:       {ic_ir:.4f}")
    print(f"    t-stat:      {t_stat:.2f}")
    print(f"    % positive:  {pct_positive:.1%}")
    print(f"    N dates:     {len(ic_clean)}")

    # Yearly IC
    ic_df = ic_clean.reset_index()
    ic_df.columns = ["trade_date", "ic"]
    ic_df["year"] = ic_df["trade_date"].apply(lambda d: d.year if isinstance(d, date) else d.year)
    yearly_ic = ic_df.groupby("year")["ic"].agg(["mean", "std", "count"])
    print("\n  Yearly IC:")
    print(f"  {'Year':<8} {'Mean':>8} {'Std':>8} {'N':>6}")
    print(f"  {'-' * 34}")
    for yr, row in yearly_ic.iterrows():
        print(f"  {yr:<8} {row['mean']:>8.4f} {row['std']:>8.4f} {int(row['count']):>6}")

    result = {
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4),
        "t_stat": round(t_stat, 2),
        "pct_positive": round(pct_positive, 4),
        "n_dates": len(ic_clean),
        "yearly_ic": {str(yr): round(row["mean"], 4) for yr, row in yearly_ic.iterrows()},
    }
    save_result(result, "part0_5_composite_ic")
    print(f"\n  Part 0.5 elapsed: {(time.time() - t0) / 60:.1f} min")
    return result


# ═══════════════════════════════════════════════════════════════
# Part 1: Universe Filter Experiments
# ═══════════════════════════════════════════════════════════════


def part1_prerequisite():
    """Part 1 Prerequisite: Check universe size for each mcap range."""
    print("\n" + "=" * 70)
    print("Part 1 Prerequisite: Universe Size by Market Cap Range")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    conn = get_db_conn()
    print("\n[1] Loading mcap data...")
    mcap_df = load_mcap_data(OOS_START, OOS_END, conn)
    conn.close()

    # Compute monthly dates from mcap data
    all_dates = sorted(mcap_df["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_dates)
    monthly_dates = [d for d in monthly_dates if d >= OOS_START and d <= OOS_END]

    print(f"\n[2] Computing universe sizes for {len(monthly_dates)} months...")
    results = {}
    flag_warnings = []

    print(f"\n  {'Range':<25} {'Min':>8} {'Mean':>8} {'Max':>8} {'Flag':>6}")
    print(f"  {'-' * 58}")

    for label, (min_y, max_y, _) in MCAP_RANGES.items():
        counts = compute_universe_size(mcap_df, min_y, max_y, monthly_dates)
        min_c = int(counts.min()) if len(counts) > 0 else 0
        mean_c = float(counts.mean()) if len(counts) > 0 else 0
        max_c = int(counts.max()) if len(counts) > 0 else 0

        flag = ""
        if mean_c < 300:
            flag = "WARN"
            flag_warnings.append(label)

        print(f"  {label:<25} {min_c:>8} {mean_c:>8.0f} {max_c:>8} {flag:>6}")
        results[label] = {
            "min_stocks": min_c,
            "mean_stocks": round(mean_c, 0),
            "max_stocks": max_c,
            "warning": mean_c < 300,
        }

    if flag_warnings:
        print(f"\n  WARNING: The following ranges have mean < 300 stocks: {flag_warnings}")
        print(
            "  Small universe may lead to concentrated portfolios or insufficient diversification."
        )

    save_result(results, "part1_prerequisite")
    print(f"\n  Part 1 pre elapsed: {(time.time() - t0) / 60:.1f} min")
    return results


def part1_3_mcap_range_comparison():
    """Part 1.3: CORE5 backtest across different market cap ranges."""
    print("\n" + "=" * 70)
    print("Part 1.3: CORE5 Backtest by Market Cap Range")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)

    conn = get_db_conn()
    mcap_df = load_mcap_data(OOS_START, OOS_END, conn)

    # 2. Run experiments for each range
    print("\n[2] Running experiments...")
    all_results = []

    for label, (min_y, max_y, sn_beta) in MCAP_RANGES.items():
        print(f"\n  --- {label} ---")
        t1 = time.time()

        # Filter factor_df by mcap range
        if min_y == 0 and max_y == float("inf"):
            # Full universe, no filtering needed
            filtered_factor = factor_df.copy()
        else:
            filtered_factor = filter_factor_by_mcap(factor_df, mcap_df, min_y, max_y)

        n_rows = len(filtered_factor)
        n_stocks = filtered_factor["code"].nunique() if n_rows > 0 else 0
        print(f"  Filtered: {n_rows:,} factor rows, {n_stocks} unique stocks")

        if n_rows == 0 or n_stocks < 20:
            print(f"  SKIP: insufficient stocks ({n_stocks} < 20)")
            all_results.append(
                {
                    "label": label,
                    "sharpe": None,
                    "mdd": None,
                    "annual_return": None,
                    "n_stocks": n_stocks,
                    "skipped": True,
                }
            )
            continue

        # Filter price_data to same stocks (for this range)
        range_codes = set(filtered_factor["code"].unique())
        range_price = price_data[price_data["code"].isin(range_codes)].copy()

        metrics = run_standard_experiment(
            filtered_factor,
            CORE5_DIRECTIONS,
            range_price,
            bench,
            top_n=20,
            sn_beta=sn_beta,
            conn=conn,
            label=label,
        )
        metrics["n_stocks"] = n_stocks
        metrics["skipped"] = False
        all_results.append(metrics)

        print(
            f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']}, "
            f"AnnRet={metrics['annual_return']} ({time.time() - t1:.1f}s)"
        )

    conn.close()

    # 3. Print comparison table
    print(f"\n\n{'Range':<25} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10} {'Stocks':>8}")
    print("-" * 65)

    for r in sorted(all_results, key=lambda x: x.get("sharpe") or -999, reverse=True):
        if r.get("skipped"):
            print(f"{r['label']:<25} {'SKIP':>8} {'':>10} {'':>10} {r['n_stocks']:>8}")
        else:
            print(
                f"{r['label']:<25} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} "
                f"{r['annual_return']:>10.4f} {r['n_stocks']:>8}"
            )

    # vs baseline
    print(f"\n  Baseline (EW+SN full A): Sharpe={BASELINE_SHARPE}")

    save_result(all_results, "part1_3_mcap_range_comparison")
    print(f"\n  Part 1.3 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part1_2_core4_midcap():
    """Part 1.2: CORE4 (no amihud) in mid-cap (100-500亿) universe."""
    print("\n" + "=" * 70)
    print("Part 1.2: CORE4 (no amihud) in Mid-Cap (100-500亿)")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    # Load ALL factors from parquet (CORE5) then filter to CORE4
    factor_df = load_factor_from_parquet(2020, 2026)
    factor_df_c4 = factor_df[factor_df["factor_name"].isin(CORE4_FACTORS)].copy()
    print(f"  CORE4 factors: {len(factor_df_c4):,} rows")

    price_data, bench = load_price_data(2020, 2026)

    conn = get_db_conn()
    mcap_df = load_mcap_data(OOS_START, OOS_END, conn)

    # 2. Filter to mid-cap
    min_y, max_y = 100e8, 500e8
    print(f"\n[2] Filtering to mid-cap ({min_y * YUAN_TO_YI:.0f}-{max_y * YUAN_TO_YI:.0f}亿)...")

    filtered_c4 = filter_factor_by_mcap(factor_df_c4, mcap_df, min_y, max_y)
    filtered_c5 = filter_factor_by_mcap(factor_df, mcap_df, min_y, max_y)
    print(f"  CORE4 mid-cap: {len(filtered_c4):,} rows, {filtered_c4['code'].nunique()} stocks")
    print(f"  CORE5 mid-cap: {len(filtered_c5):,} rows, {filtered_c5['code'].nunique()} stocks")

    # Filter price to mid-cap stocks
    midcap_codes = set(filtered_c5["code"].unique()) | set(filtered_c4["code"].unique())
    midcap_price = price_data[price_data["code"].isin(midcap_codes)].copy()

    # 3. Run CORE4 mid-cap
    print("\n[3] Running CORE4 mid-cap backtest...")
    t1 = time.time()
    metrics_c4 = run_standard_experiment(
        filtered_c4,
        CORE4_DIRECTIONS,
        midcap_price,
        bench,
        top_n=20,
        sn_beta=0.0,
        conn=conn,
        label="CORE4 mid-cap (no SN)",
    )
    print(
        f"  CORE4: Sharpe={metrics_c4['sharpe']}, MDD={metrics_c4['mdd']} ({time.time() - t1:.1f}s)"
    )

    # 4. Run CORE5 mid-cap for comparison
    print("\n[4] Running CORE5 mid-cap backtest...")
    t1 = time.time()
    metrics_c5 = run_standard_experiment(
        filtered_c5,
        CORE5_DIRECTIONS,
        midcap_price,
        bench,
        top_n=20,
        sn_beta=0.0,
        conn=conn,
        label="CORE5 mid-cap (no SN)",
    )
    print(
        f"  CORE5: Sharpe={metrics_c5['sharpe']}, MDD={metrics_c5['mdd']} ({time.time() - t1:.1f}s)"
    )

    conn.close()

    # 5. Print comparison
    print(f"\n\n{'Method':<30} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 62)
    print(
        f"{'CORE4 mid-cap (no SN)':<30} {metrics_c4['sharpe']:>8.4f} "
        f"{metrics_c4['mdd']:>10.4f} {metrics_c4['annual_return']:>10.4f}"
    )
    print(
        f"{'CORE5 mid-cap (no SN)':<30} {metrics_c5['sharpe']:>8.4f} "
        f"{metrics_c5['mdd']:>10.4f} {metrics_c5['annual_return']:>10.4f}"
    )
    print(f"\n  Diff (C4-C5): {metrics_c4['sharpe'] - metrics_c5['sharpe']:+.4f} Sharpe")
    print(f"  Baseline (EW+SN full A): Sharpe={BASELINE_SHARPE}")

    result = {
        "core4_midcap": metrics_c4,
        "core5_midcap": metrics_c5,
        "sharpe_diff": round(metrics_c4["sharpe"] - metrics_c5["sharpe"], 4),
    }
    save_result(result, "part1_2_core4_midcap")
    print(f"\n  Part 1.2 elapsed: {(time.time() - t0) / 60:.1f} min")
    return result


def part1_4_midcap_low_sn():
    """Part 1.4: Mid-cap (100-500亿) with low SN beta values."""
    print("\n" + "=" * 70)
    print("Part 1.4: Mid-Cap + Low SN Beta Sensitivity")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)

    conn = get_db_conn()
    mcap_df = load_mcap_data(OOS_START, OOS_END, conn)

    # Filter to mid-cap
    min_y, max_y = 100e8, 500e8
    filtered = filter_factor_by_mcap(factor_df, mcap_df, min_y, max_y)
    midcap_codes = set(filtered["code"].unique())
    midcap_price = price_data[price_data["code"].isin(midcap_codes)].copy()
    print(f"  Mid-cap filtered: {len(filtered):,} rows, {len(midcap_codes)} stocks")

    # 2. Test different SN betas
    sn_betas = [0.0, 0.10, 0.15, 0.20, 0.30, 0.50]
    all_results = []

    for beta in sn_betas:
        print(f"\n  --- SN beta={beta:.2f} ---")
        t1 = time.time()
        metrics = run_standard_experiment(
            filtered,
            CORE5_DIRECTIONS,
            midcap_price,
            bench,
            top_n=20,
            sn_beta=beta,
            conn=conn,
            label=f"Mid-cap SN b={beta:.2f}",
        )
        metrics["sn_beta"] = beta
        all_results.append(metrics)
        print(f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']} ({time.time() - t1:.1f}s)")

    conn.close()

    # 3. Print comparison table
    print(f"\n\n{'SN Beta':<12} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 44)
    for r in all_results:
        print(
            f"{r['sn_beta']:<12.2f} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} {r['annual_return']:>10.4f}"
        )

    best = max(all_results, key=lambda x: x["sharpe"])
    print(f"\n  Best: SN beta={best['sn_beta']:.2f}, Sharpe={best['sharpe']:.4f}")
    print(f"  Baseline (EW+SN full A): Sharpe={BASELINE_SHARPE}")

    save_result(all_results, "part1_4_midcap_low_sn")
    print(f"\n  Part 1.4 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


# ═══════════════════════════════════════════════════════════════
# Part 2: Factor Combination Experiments (Stubs)
# ═══════════════════════════════════════════════════════════════


def part2_0_factor_profiles():
    """Part 2.0: Check factor_profile table + cache/profiler for candidate factor profiles."""
    print("\n" + "=" * 70)
    print("Part 2.0: Factor Profile Availability Check")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Candidate factors for Part 2.2/2.3
    CANDIDATES = [
        "RSQR_20",
        "QTLU_20",
        "dv_ttm",
        "ep_ratio",
        "HVP_20",
        "IMAX_20",
        "IMIN_20",
        "CORD_20",
        "RESI_20",
    ]

    conn = get_db_conn()

    # 1. Check factor_profile table
    print("\n[1] Checking factor_profile table...")
    try:
        profile_df = pd.read_sql(
            "SELECT factor_name, updated_at FROM factor_profile ORDER BY factor_name",
            conn,
        )
        profiled_factors = set(profile_df["factor_name"].tolist())
        print(f"  factor_profile has {len(profiled_factors)} factors")
    except Exception as e:
        print(f"  factor_profile table error: {e}")
        profiled_factors = set()

    # 2. Check cache/profiler directory
    print("\n[2] Checking cache/profiler/ directory...")
    profiler_cache = CACHE_DIR / "profiler"
    cached_profiles = set()
    if profiler_cache.exists():
        for f in profiler_cache.glob("*.json"):
            cached_profiles.add(f.stem.replace("_profile", ""))
        print(f"  cache/profiler has {len(cached_profiles)} files")
    else:
        print("  cache/profiler/ not found")

    # 3. Check DB availability for each candidate
    print("\n[3] Checking DB availability for candidates...")
    print(f"\n  {'Factor':<20} {'DB Rows':>10} {'Profile':>10} {'Cache':>8}")
    print(f"  {'-' * 52}")

    results = {}
    for fname in CANDIDATES:
        try:
            count_df = pd.read_sql(
                "SELECT COUNT(*) as cnt FROM factor_values WHERE factor_name = %s",
                conn,
                params=(fname,),
            )
            db_rows = int(count_df.iloc[0]["cnt"])
        except Exception:
            db_rows = 0

        has_profile = (
            "YES" if fname in profiled_factors or fname.lower() in profiled_factors else "NO"
        )
        has_cache = "YES" if fname in cached_profiles or fname.lower() in cached_profiles else "NO"

        print(f"  {fname:<20} {db_rows:>10,} {has_profile:>10} {has_cache:>8}")
        results[fname] = {
            "db_rows": db_rows,
            "has_profile": has_profile == "YES",
            "has_cache": has_cache == "YES",
            "available": db_rows > 0,
        }

    # 4. Also check CORE5 profile status
    print("\n  CORE5 profile status:")
    for fname in CORE5_FACTORS:
        has_p = "YES" if fname in profiled_factors else "NO"
        print(f"  {fname:<20} {has_p:>10}")

    conn.close()

    save_result(results, "part2_0_factor_profiles")
    print(f"\n  Part 2.0 elapsed: {(time.time() - t0) / 60:.1f} min")
    return results


def part2_1_factor_inventory():
    """Part 2.1: Factor inventory — list all PASS factors from DB with basic IC stats."""
    print("\n" + "=" * 70)
    print("Part 2.1: Factor Inventory from DB")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    conn = get_db_conn()

    # 1. Get all distinct factors in factor_values with row counts
    print("\n[1] Querying factor_values for all factors...")
    factor_counts = pd.read_sql(
        """SELECT factor_name, COUNT(*) as cnt,
                  MIN(trade_date) as min_date, MAX(trade_date) as max_date
           FROM factor_values
           WHERE neutral_value IS NOT NULL
           GROUP BY factor_name
           ORDER BY factor_name""",
        conn,
    )
    print(f"  Found {len(factor_counts)} factors with neutral_value")

    # 2. Get IC from factor_ic_history
    print("\n[2] Querying factor_ic_history for IC stats...")
    try:
        ic_stats = pd.read_sql(
            """SELECT factor_name,
                      AVG(ic_value) as mean_ic,
                      STDDEV(ic_value) as std_ic,
                      COUNT(*) as n_obs
               FROM factor_ic_history
               GROUP BY factor_name
               ORDER BY factor_name""",
            conn,
        )
        ic_lookup = {row["factor_name"]: row for _, row in ic_stats.iterrows()}
        print(f"  IC history for {len(ic_stats)} factors")
    except Exception as e:
        print(f"  IC history error: {e}")
        ic_lookup = {}

    # 3. Cross-sectional correlation with CORE5 (using latest date)
    print("\n[3] Computing cross-sectional correlation with CORE5...")
    latest_date_df = pd.read_sql(
        "SELECT MAX(trade_date) as ld FROM factor_values WHERE factor_name = 'turnover_mean_20'",
        conn,
    )
    latest_date = latest_date_df.iloc[0]["ld"]

    core5_wide = pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s AND factor_name IN %s AND neutral_value IS NOT NULL""",
        conn,
        params=(latest_date, tuple(CORE5_FACTORS)),
    )
    core5_wide.pivot_table(
        index="code", columns="factor_name", values="neutral_value"
    )

    conn.close()

    # 4. Print inventory
    print(
        f"\n  {'Factor':<25} {'Rows':>10} {'IC Mean':>8} {'IC Std':>8} {'t-stat':>8} {'Available':>10}"
    )
    print(f"  {'-' * 74}")

    inventory = []
    for _, row in factor_counts.iterrows():
        fname = row["factor_name"]
        ic_info = ic_lookup.get(fname, {})
        ic_mean = ic_info.get("mean_ic", None)
        ic_std = ic_info.get("std_ic", None)
        n_obs = ic_info.get("n_obs", 0)

        if ic_mean is not None and ic_std is not None and ic_std > 0 and n_obs > 0:
            t_stat = float(ic_mean) / (float(ic_std) / np.sqrt(n_obs))
        else:
            t_stat = None

        in_core5 = fname in CORE5_FACTORS
        ic_str = f"{float(ic_mean):.4f}" if ic_mean is not None else "N/A"
        std_str = f"{float(ic_std):.4f}" if ic_std is not None else "N/A"
        t_str = f"{t_stat:.2f}" if t_stat is not None else "N/A"
        tag = "CORE5" if in_core5 else "CAND"

        print(f"  {fname:<25} {int(row['cnt']):>10,} {ic_str:>8} {std_str:>8} {t_str:>8} {tag:>10}")

        inventory.append(
            {
                "factor_name": fname,
                "db_rows": int(row["cnt"]),
                "ic_mean": round(float(ic_mean), 4) if ic_mean is not None else None,
                "ic_std": round(float(ic_std), 4) if ic_std is not None else None,
                "t_stat": round(t_stat, 2) if t_stat is not None else None,
                "in_core5": in_core5,
                "min_date": str(row["min_date"]),
                "max_date": str(row["max_date"]),
            }
        )

    save_result(inventory, "part2_1_factor_inventory")
    print(f"\n  Part 2.1 elapsed: {(time.time() - t0) / 60:.1f} min")
    return inventory


def part2_2_add_factors():
    """Part 2.2: Add candidate factors to CORE5, test on full A + SN b=0.50.

    Given Part 1 finding: alpha is micro-cap only → test on full A+SN (optimal setup).
    """
    print("\n" + "=" * 70)
    print("Part 2.2: Add Factors to CORE5 (Full A + SN b=0.50)")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Candidate factors to add: name -> direction
    CANDIDATES = {
        "RSQR_20": -1,  # IC=0.052, residual volatility (lower=better)
        "QTLU_20": -1,  # IC=-0.082, upper quantile (lower=better)
        "dv_ttm": 1,  # IC=0.031, dividend yield (higher=better)
        "ep_ratio": 1,  # IC=0.034, earnings/price (higher=better)
    }

    # 1. Load CORE5 data
    print("\n[1] Loading CORE5 factors + price data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    # 2. Run baseline: CORE5 + SN (should match ~0.6652)
    print("\n[2] Running baseline CORE5 + SN...")
    t1 = time.time()
    baseline = run_standard_experiment(
        factor_df,
        CORE5_DIRECTIONS,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="CORE5+SN (baseline)",
    )
    print(
        f"  Baseline: Sharpe={baseline['sharpe']}, MDD={baseline['mdd']} ({time.time() - t1:.1f}s)"
    )

    # 3. For each candidate, load from DB and test CORE5+X
    print("\n[3] Testing CORE5 + candidate factors...")
    all_results = [baseline]

    for cand_name, cand_dir in CANDIDATES.items():
        print(f"\n  --- CORE5 + {cand_name} (dir={cand_dir:+d}) ---")
        t1 = time.time()

        # Load candidate from DB
        cand_df = load_factors_from_db([cand_name], OOS_START, OOS_END, conn)
        if cand_df.empty:
            print(f"  SKIP: {cand_name} not found in DB")
            all_results.append(
                {
                    "label": f"CORE5+{cand_name}",
                    "sharpe": None,
                    "skipped": True,
                }
            )
            continue

        # Merge with CORE5
        merged = pd.concat([factor_df, cand_df], ignore_index=True)
        directions = {**CORE5_DIRECTIONS, cand_name: cand_dir}

        metrics = run_standard_experiment(
            merged,
            directions,
            price_data,
            bench,
            top_n=20,
            sn_beta=SN_BETA,
            conn=conn,
            label=f"CORE5+{cand_name}",
        )
        all_results.append(metrics)
        diff = metrics["sharpe"] - baseline["sharpe"]
        print(
            f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']}, "
            f"Diff={diff:+.4f} ({time.time() - t1:.1f}s)"
        )

    conn.close()

    # 4. Print comparison
    print(f"\n\n{'Method':<30} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10} {'vs Base':>10}")
    print("-" * 72)
    for r in sorted(all_results, key=lambda x: x.get("sharpe") or -999, reverse=True):
        if r.get("skipped"):
            print(f"{r['label']:<30} {'SKIP':>8}")
        else:
            diff = r["sharpe"] - baseline["sharpe"]
            print(
                f"{r['label']:<30} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} "
                f"{r['annual_return']:>10.4f} {diff:>+10.4f}"
            )

    save_result(all_results, "part2_2_add_factors")
    print(f"\n  Part 2.2 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part2_3_replace_factors():
    """Part 2.3: Replace weak CORE5 factors (amihud/reversal) with candidates."""
    print("\n" + "=" * 70)
    print("Part 2.3: Replace Weak Factors in CORE5")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Replacement combos to test
    REPLACEMENTS = {
        "CORE4(no amihud)+RSQR_20": {
            "factors": ["turnover_mean_20", "volatility_20", "reversal_20", "bp_ratio", "RSQR_20"],
            "directions": {
                "turnover_mean_20": -1,
                "volatility_20": -1,
                "reversal_20": 1,
                "bp_ratio": 1,
                "RSQR_20": -1,
            },
        },
        "CORE4(no amihud)+dv_ttm": {
            "factors": ["turnover_mean_20", "volatility_20", "reversal_20", "bp_ratio", "dv_ttm"],
            "directions": {
                "turnover_mean_20": -1,
                "volatility_20": -1,
                "reversal_20": 1,
                "bp_ratio": 1,
                "dv_ttm": 1,
            },
        },
        "CORE4+RSQR_20+dv_ttm (6fac)": {
            "factors": [
                "turnover_mean_20",
                "volatility_20",
                "reversal_20",
                "bp_ratio",
                "RSQR_20",
                "dv_ttm",
            ],
            "directions": {
                "turnover_mean_20": -1,
                "volatility_20": -1,
                "reversal_20": 1,
                "bp_ratio": 1,
                "RSQR_20": -1,
                "dv_ttm": 1,
            },
        },
        "CORE3(no amihud,reversal)+RSQR+dv": {
            "factors": ["turnover_mean_20", "volatility_20", "bp_ratio", "RSQR_20", "dv_ttm"],
            "directions": {
                "turnover_mean_20": -1,
                "volatility_20": -1,
                "bp_ratio": 1,
                "RSQR_20": -1,
                "dv_ttm": 1,
            },
        },
    }

    # 1. Load data
    print("\n[1] Loading data...")
    core5_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    # Load replacement factors from DB
    replacement_factors = ["RSQR_20", "dv_ttm"]
    extra_df = load_factors_from_db(replacement_factors, OOS_START, OOS_END, conn)

    # 2. Run baseline
    print("\n[2] Running CORE5+SN baseline...")
    baseline = run_standard_experiment(
        core5_df,
        CORE5_DIRECTIONS,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="CORE5+SN (baseline)",
    )
    print(f"  Baseline: Sharpe={baseline['sharpe']}")

    # 3. Run replacement combos
    print("\n[3] Testing replacement combos...")
    all_results = [baseline]

    for label, combo in REPLACEMENTS.items():
        print(f"\n  --- {label} ---")
        t1 = time.time()

        # Build factor_df for this combo
        core_factors = [f for f in combo["factors"] if f in CORE5_FACTORS]
        new_factors = [f for f in combo["factors"] if f not in CORE5_FACTORS]

        combo_df = core5_df[core5_df["factor_name"].isin(core_factors)].copy()
        if new_factors and not extra_df.empty:
            new_df = extra_df[extra_df["factor_name"].isin(new_factors)].copy()
            combo_df = pd.concat([combo_df, new_df], ignore_index=True)

        metrics = run_standard_experiment(
            combo_df,
            combo["directions"],
            price_data,
            bench,
            top_n=20,
            sn_beta=SN_BETA,
            conn=conn,
            label=label,
        )
        all_results.append(metrics)
        diff = metrics["sharpe"] - baseline["sharpe"]
        print(f"  Sharpe={metrics['sharpe']}, Diff={diff:+.4f} ({time.time() - t1:.1f}s)")

    conn.close()

    # 4. Print comparison
    print(f"\n\n{'Method':<40} {'Sharpe':>8} {'MDD':>10} {'vs Base':>10}")
    print("-" * 72)
    for r in sorted(all_results, key=lambda x: x.get("sharpe") or -999, reverse=True):
        diff = r["sharpe"] - baseline["sharpe"]
        print(f"{r['label']:<40} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} {diff:>+10.4f}")

    save_result(all_results, "part2_3_replace_factors")
    print(f"\n  Part 2.3 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part2_4_negative_screening():
    """Part 2.4: Negative screening — Top-30 → filter worst 10 → hold Top-20."""
    print("\n" + "=" * 70)
    print("Part 2.4: Negative Screening")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load data
    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    from engines.backtest.config import BacktestConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)

    # 2. Build portfolios with negative screening
    all_factor_dates = sorted(factor_df["trade_date"].unique())
    all_price_dates = sorted(price_data["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [
        d
        for d in monthly_dates
        if d >= OOS_START
        and d <= OOS_END
        and d >= all_factor_dates[0]
        and d <= all_factor_dates[-1]
    ]

    factor_date_list = sorted(factor_df["trade_date"].unique())

    strategies = {
        "Top30→screen worst10 by vol": {
            "top_n_initial": 30,
            "screen_by": "volatility_20",
            "screen_n": 10,
            "screen_dir": "high_bad",
        },
        "Top25→screen worst5 by vol": {
            "top_n_initial": 25,
            "screen_by": "volatility_20",
            "screen_n": 5,
            "screen_dir": "high_bad",
        },
    }

    all_results = []

    for strat_name, strat_cfg in strategies.items():
        print(f"\n  --- {strat_name} ---")
        t1 = time.time()

        target_portfolios = {}
        for rd in monthly_dates:
            idx = bisect_right(factor_date_list, rd)
            if idx == 0:
                continue
            fd = factor_date_list[idx - 1]

            day_data = factor_df[factor_df["trade_date"] == fd]
            if day_data.empty:
                continue

            exclude = build_exclusion_set(price_data, rd)
            day_data = day_data[~day_data["code"].isin(exclude)]

            # Composite scores with SN
            scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
            if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
                scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)

            # Top-N initial
            top_initial = scores.nlargest(strat_cfg["top_n_initial"])

            # Get screen factor values for these codes
            screen_factor = strat_cfg["screen_by"]
            screen_vals = day_data[day_data["factor_name"] == screen_factor].set_index("code")[
                "raw_value"
            ]
            screen_vals = screen_vals.reindex(top_initial.index)

            # Remove worst N by screen factor
            if strat_cfg["screen_dir"] == "high_bad":
                # High values are bad (volatility) → remove highest
                worst = screen_vals.nlargest(strat_cfg["screen_n"]).index
            else:
                worst = screen_vals.nsmallest(strat_cfg["screen_n"]).index

            kept = top_initial.drop(worst, errors="ignore")
            if len(kept) < 10:
                continue

            w = 1.0 / len(kept)
            target_portfolios[rd] = {code: w for code in kept.index}

        bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
        tester = SimpleBacktester(bt_config)
        result = tester.run(target_portfolios, price_data, bench)

        metrics = compute_metrics(result.daily_nav)
        metrics["label"] = strat_name
        metrics["n_rebal"] = len(target_portfolios)
        all_results.append(metrics)
        print(f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']} ({time.time() - t1:.1f}s)")

    conn.close()

    # Print comparison
    print(f"\n\n{'Method':<40} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 72)
    for r in sorted(all_results, key=lambda x: x["sharpe"], reverse=True):
        print(f"{r['label']:<40} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} {r['annual_return']:>10.4f}")
    print(f"\n  Baseline (EW+SN): Sharpe={BASELINE_SHARPE}")

    save_result(all_results, "part2_4_negative_screening")
    print(f"\n  Part 2.4 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part2_5_lambdarank_factor():
    """Part 2.5: Use LambdaRank OOS prediction as 6th factor in EW composite."""
    print("\n" + "=" * 70)
    print("Part 2.5: LambdaRank Score as 6th Factor")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load LambdaRank OOS predictions
    lr_path = PHASE22_CACHE / "oos_predictions_lambdarank.parquet"
    if not lr_path.exists():
        print("  LambdaRank OOS predictions not found. Skipping.")
        return None

    print("\n[1] Loading data...")
    lr_df = pd.read_parquet(lr_path)
    lr_df["trade_date"] = pd.to_datetime(lr_df["trade_date"]).dt.date
    print(
        f"  LambdaRank: {len(lr_df):,} rows, dates: {lr_df['trade_date'].min()} ~ {lr_df['trade_date'].max()}"
    )

    # Convert to factor_df format
    lr_factor = lr_df[["code", "trade_date", "predicted"]].copy()
    lr_factor["factor_name"] = "lambdarank_score"
    lr_factor = lr_factor.rename(columns={"predicted": "raw_value"})

    # Z-score normalize per date (so it's on same scale as other factors)
    lr_factor["raw_value"] = lr_factor.groupby("trade_date")["raw_value"].transform(
        lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
    )

    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    # 2. Run baseline
    print("\n[2] Running CORE5+SN baseline...")
    baseline = run_standard_experiment(
        factor_df,
        CORE5_DIRECTIONS,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="CORE5+SN (baseline)",
    )
    print(f"  Baseline: Sharpe={baseline['sharpe']}")

    # 3. Merge LR as 6th factor
    print("\n[3] Running CORE5+LambdaRank+SN...")
    # Limit to overlapping date range
    lr_dates = set(lr_factor["trade_date"].unique())
    core_dates = set(factor_df["trade_date"].unique())
    overlap_dates = lr_dates & core_dates
    print(f"  Overlapping dates: {len(overlap_dates)}")

    merged = pd.concat(
        [
            factor_df[factor_df["trade_date"].isin(overlap_dates)],
            lr_factor[lr_factor["trade_date"].isin(overlap_dates)],
        ],
        ignore_index=True,
    )

    directions_6 = {**CORE5_DIRECTIONS, "lambdarank_score": 1}

    metrics_6 = run_standard_experiment(
        merged,
        directions_6,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="CORE5+LR+SN (6 factors)",
    )

    # 4. Also test CORE5+LR without SN to see if LR provides its own size-neutral effect
    print("\n[4] Running CORE5+LambdaRank (no SN)...")
    metrics_nosn = run_standard_experiment(
        merged,
        directions_6,
        price_data,
        bench,
        top_n=20,
        sn_beta=0.0,
        conn=conn,
        label="CORE5+LR (no SN)",
    )

    conn.close()

    # 5. Print comparison
    all_results = [baseline, metrics_6, metrics_nosn]
    print(f"\n\n{'Method':<35} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10} {'vs Base':>10}")
    print("-" * 77)
    for r in sorted(all_results, key=lambda x: x["sharpe"], reverse=True):
        diff = r["sharpe"] - baseline["sharpe"]
        print(
            f"{r['label']:<35} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} "
            f"{r['annual_return']:>10.4f} {diff:>+10.4f}"
        )

    save_result(all_results, "part2_5_lambdarank_factor")
    print(f"\n  Part 2.5 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


# ═══════════════════════════════════════════════════════════════
# Part 3: Parameter Sensitivity (Stubs)
# ═══════════════════════════════════════════════════════════════


def part3_1_topn_sensitivity():
    """Part 3.1: Top-N sensitivity on full A + SN b=0.50."""
    print("\n" + "=" * 70)
    print("Part 3.1: Top-N Sensitivity (Full A + SN b=0.50)")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    top_ns = [10, 15, 20, 25, 30, 40]
    all_results = []

    for n in top_ns:
        print(f"\n  --- Top-{n} ---")
        t1 = time.time()
        metrics = run_standard_experiment(
            factor_df,
            CORE5_DIRECTIONS,
            price_data,
            bench,
            top_n=n,
            sn_beta=SN_BETA,
            conn=conn,
            label=f"Top-{n}",
        )
        all_results.append(metrics)
        print(f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']} ({time.time() - t1:.1f}s)")

    conn.close()

    print(f"\n\n{'Top-N':<10} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 42)
    for r in all_results:
        print(f"{r['label']:<10} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} {r['annual_return']:>10.4f}")

    best = max(all_results, key=lambda x: x["sharpe"])
    print(f"\n  Best: {best['label']}, Sharpe={best['sharpe']:.4f}")

    save_result(all_results, "part3_1_topn_sensitivity")
    print(f"\n  Part 3.1 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part3_2_rebalance_freq():
    """Part 3.2: Rebalance frequency — monthly vs bimonthly."""
    print("\n" + "=" * 70)
    print("Part 3.2: Rebalance Frequency Sensitivity")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    from engines.backtest.config import BacktestConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)

    all_factor_dates = sorted(factor_df["trade_date"].unique())
    all_price_dates = sorted(price_data["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [
        d
        for d in monthly_dates
        if d >= OOS_START
        and d <= OOS_END
        and d >= all_factor_dates[0]
        and d <= all_factor_dates[-1]
    ]
    factor_date_list = sorted(factor_df["trade_date"].unique())

    # Monthly (standard) via run_standard_experiment
    print("\n[2] Monthly rebalance...")
    t1 = time.time()
    metrics_monthly = run_standard_experiment(
        factor_df,
        CORE5_DIRECTIONS,
        price_data,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        label="Monthly",
    )
    print(f"  Sharpe={metrics_monthly['sharpe']} ({time.time() - t1:.1f}s)")

    # Bimonthly: take every other month
    print("\n[3] Bimonthly rebalance...")
    t1 = time.time()
    bimonthly_dates = monthly_dates[::2]  # Every other month

    target_portfolios_bi = {}
    for rd in bimonthly_dates:
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]
        day_data = factor_df[factor_df["trade_date"] == fd]
        if day_data.empty:
            continue
        exclude = build_exclusion_set(price_data, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)
        top20 = scores.nlargest(20)
        if len(top20) < 5:
            continue
        w = 1.0 / len(top20)
        target_portfolios_bi[rd] = {code: w for code in top20.index}

    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config)
    result_bi = tester.run(target_portfolios_bi, price_data, bench)
    metrics_bi = compute_metrics(result_bi.daily_nav)
    metrics_bi["label"] = "Bimonthly"
    metrics_bi["n_rebal"] = len(target_portfolios_bi)
    print(f"  Sharpe={metrics_bi['sharpe']} ({time.time() - t1:.1f}s)")

    # Quarterly: every 3rd month
    print("\n[4] Quarterly rebalance...")
    t1 = time.time()
    quarterly_dates = monthly_dates[::3]

    target_portfolios_q = {}
    for rd in quarterly_dates:
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]
        day_data = factor_df[factor_df["trade_date"] == fd]
        if day_data.empty:
            continue
        exclude = build_exclusion_set(price_data, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)
        top20 = scores.nlargest(20)
        if len(top20) < 5:
            continue
        w = 1.0 / len(top20)
        target_portfolios_q[rd] = {code: w for code in top20.index}

    result_q = tester.run(target_portfolios_q, price_data, bench)
    metrics_q = compute_metrics(result_q.daily_nav)
    metrics_q["label"] = "Quarterly"
    metrics_q["n_rebal"] = len(target_portfolios_q)
    print(f"  Sharpe={metrics_q['sharpe']} ({time.time() - t1:.1f}s)")

    conn.close()

    all_results = [metrics_monthly, metrics_bi, metrics_q]
    print(f"\n\n{'Frequency':<15} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10} {'Rebal':>8}")
    print("-" * 55)
    for r in all_results:
        print(
            f"{r['label']:<15} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} "
            f"{r['annual_return']:>10.4f} {r['n_rebal']:>8}"
        )

    save_result(all_results, "part3_2_rebalance_freq")
    print(f"\n  Part 3.2 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


def part3_3_sn_beta_sensitivity():
    """Part 3.3: SN beta sensitivity on full universe (0.0 to 1.0)."""
    print("\n" + "=" * 70)
    print("Part 3.3: SN Beta Sensitivity (Full Universe)")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("\n[1] Loading data...")
    factor_df = load_factor_from_parquet(2020, 2026)
    price_data, bench = load_price_data(2020, 2026)
    conn = get_db_conn()

    betas = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.00]
    all_results = []

    for beta in betas:
        print(f"\n  --- SN beta={beta:.2f} ---")
        t1 = time.time()
        metrics = run_standard_experiment(
            factor_df,
            CORE5_DIRECTIONS,
            price_data,
            bench,
            top_n=20,
            sn_beta=beta,
            conn=conn,
            label=f"SN b={beta:.2f}",
        )
        metrics["sn_beta"] = beta
        all_results.append(metrics)
        print(f"  Sharpe={metrics['sharpe']}, MDD={metrics['mdd']} ({time.time() - t1:.1f}s)")

    conn.close()

    print(f"\n\n{'SN Beta':<10} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 42)
    for r in all_results:
        print(
            f"{r['sn_beta']:<10.2f} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} {r['annual_return']:>10.4f}"
        )

    best = max(all_results, key=lambda x: x["sharpe"])
    print(f"\n  Best: SN beta={best['sn_beta']:.2f}, Sharpe={best['sharpe']:.4f}")

    save_result(all_results, "part3_3_sn_beta_sensitivity")
    print(f"\n  Part 3.3 elapsed: {(time.time() - t0) / 60:.1f} min")
    return all_results


# ═══════════════════════════════════════════════════════════════
# Part 4: Advanced Strategies (Stubs)
# ═══════════════════════════════════════════════════════════════


def part4_1_ashare_factors():
    """Part 4.1: Skipped — dv_ttm tested in Part 2.2/2.3."""
    print("\n" + "=" * 70)
    print("Part 4.1: A-Share Specific Factors — Covered by Part 2.2/2.3")
    print("=" * 70)
    print("  dv_ttm and ep_ratio tested in Part 2.2 (add factors).")
    print("  See Part 2.2/2.3 results for A-share factor analysis.")


def part4_2_style_diversification():
    """Part 4.2: Skipped — Part 1 showed alpha is 100% micro-cap.

    Style diversification across mcap ranges is not viable since
    non-micro-cap ranges have near-zero Sharpe.
    """
    print("\n" + "=" * 70)
    print("Part 4.2: Style Diversification — SKIPPED")
    print("=" * 70)
    print("  Part 1.3 showed alpha is 100% micro-cap driven.")
    print("  Non-micro-cap Sharpe: small=0.18, mid=0.07, large=-0.01")
    print("  Style diversification across mcap ranges not viable.")
    print("  Barbell SN structure remains optimal.")


def part4_3_barbell_vs_active():
    """Part 4.3: Skipped — SN barbell proven optimal in Part 1."""
    print("\n" + "=" * 70)
    print("Part 4.3: Barbell vs Active — SKIPPED")
    print("=" * 70)
    print("  Part 1.3 definitively showed SN barbell (0.67) >> all universe filters.")
    print("  No alternative structure can match barbell's risk-return profile.")


# ═══════════════════════════════════════════════════════════════
# Part 5: Summary (Stub)
# ═══════════════════════════════════════════════════════════════


def part5_summary():
    """Part 5: Summary — aggregate all cached results into a comparison matrix."""
    print("\n" + "=" * 70)
    print("Part 5: Summary Report — All Experiments")
    print("=" * 70)

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)

    # Load all cached results
    all_experiments = []

    # Part 0 results
    load_cached("part0_1_cost_attribution")
    load_cached("part0_2_annual_decomposition")
    p0_3 = load_cached("part0_3_rebalance_alpha")
    p0_5 = load_cached("part0_5_composite_ic")

    if p0_3:
        all_experiments.append(
            {
                "part": "0.3",
                "label": "Monthly Rebalance (baseline)",
                **p0_3.get("rebalance", {}),
            }
        )
        all_experiments.append(
            {
                "part": "0.3",
                "label": "Buy-and-Hold",
                **p0_3.get("buy_and_hold", {}),
            }
        )

    # Part 1 results
    p1_3 = load_cached("part1_3_mcap_range_comparison")
    if p1_3:
        for r in p1_3:
            if not r.get("skipped"):
                all_experiments.append({"part": "1.3", **r})

    p1_2 = load_cached("part1_2_core4_midcap")
    if p1_2:
        all_experiments.append({"part": "1.2", **p1_2.get("core4_midcap", {})})
        all_experiments.append({"part": "1.2", **p1_2.get("core5_midcap", {})})

    p1_4 = load_cached("part1_4_midcap_low_sn")
    if p1_4:
        best_14 = max(p1_4, key=lambda x: x.get("sharpe", -999))
        all_experiments.append({"part": "1.4", **best_14})

    # Part 2 results
    p2_2 = load_cached("part2_2_add_factors")
    if p2_2:
        for r in p2_2:
            if not r.get("skipped"):
                all_experiments.append({"part": "2.2", **r})

    p2_3 = load_cached("part2_3_replace_factors")
    if p2_3:
        for r in p2_3:
            all_experiments.append({"part": "2.3", **r})

    p2_4 = load_cached("part2_4_negative_screening")
    if p2_4:
        for r in p2_4:
            all_experiments.append({"part": "2.4", **r})

    p2_5 = load_cached("part2_5_lambdarank_factor")
    if p2_5:
        for r in p2_5:
            all_experiments.append({"part": "2.5", **r})

    # Part 3 results
    p3_1 = load_cached("part3_1_topn_sensitivity")
    if p3_1:
        for r in p3_1:
            all_experiments.append({"part": "3.1", **r})

    p3_2 = load_cached("part3_2_rebalance_freq")
    if p3_2:
        for r in p3_2:
            all_experiments.append({"part": "3.2", **r})

    p3_3 = load_cached("part3_3_sn_beta_sensitivity")
    if p3_3:
        best_33 = max(p3_3, key=lambda x: x.get("sharpe", -999))
        all_experiments.append({"part": "3.3-best", **best_33})

    # Print full comparison matrix sorted by Sharpe
    valid = [e for e in all_experiments if e.get("sharpe") is not None]
    valid.sort(key=lambda x: x.get("sharpe", -999), reverse=True)

    print(f"\n{'Part':<8} {'Label':<40} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("=" * 80)
    for e in valid:
        label = e.get("label", "?")[:38]
        sharpe = e.get("sharpe", 0)
        mdd = e.get("mdd", 0)
        ann = e.get("annual_return", 0)
        marker = " ★" if sharpe > BASELINE_SHARPE else ""
        print(
            f"{e.get('part', '?'):<8} {label:<40} {sharpe:>8.4f} {mdd:>10.4f} {ann:>10.4f}{marker}"
        )

    print(f"\n  Baseline: EW CORE5 + SN b=0.50 = {BASELINE_SHARPE}")
    print(f"  Target: > {BASELINE_SHARPE * 1.1:.4f} (baseline × 1.1) for Phase 4 PT restart")

    above_baseline = [e for e in valid if e.get("sharpe", 0) > BASELINE_SHARPE]
    if above_baseline:
        best = above_baseline[0]
        print(
            f"\n  🏆 Best: [{best.get('part')}] {best.get('label')} Sharpe={best.get('sharpe'):.4f}"
        )
        if best.get("sharpe", 0) > BASELINE_SHARPE * 1.1:
            print("  → EXCEEDS target! Phase 4 PT restart candidate.")
        else:
            print(f"  → Above baseline but below target ({BASELINE_SHARPE * 1.1:.4f}).")
    else:
        print("\n  ❌ No experiment exceeds baseline. EW CORE5 + SN is local optimum.")

    # Composite IC summary
    if p0_5:
        print(
            f"\n  Composite IC: mean={p0_5.get('ic_mean')}, IR={p0_5.get('ic_ir')}, "
            f"t={p0_5.get('t_stat')}, positive={p0_5.get('pct_positive')}"
        )

    # Key findings
    print("\n" + "=" * 80)
    print("KEY FINDINGS:")
    print("=" * 80)
    print("1. Alpha is 100% micro-cap (Part 1.3): non-micro-cap Sharpe ≈ 0")
    print("2. SN barbell is optimal structure, universe filter cannot replace it")
    print("3. Composite IC = 0.113 (IR=1.15) is very strong and stable")
    print("4. Rebalance alpha = +0.05 Sharpe only, high turnover cost")

    summary = {
        "n_experiments": len(valid),
        "baseline_sharpe": BASELINE_SHARPE,
        "above_baseline": len(above_baseline),
        "best_label": above_baseline[0].get("label") if above_baseline else None,
        "best_sharpe": above_baseline[0].get("sharpe") if above_baseline else None,
        "all_results": valid,
    }
    save_result(summary, "part5_summary")
    return summary


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Phase 2.4: Research Exploration")
    parser.add_argument("--part0", action="store_true", help="Root cause diagnosis")
    parser.add_argument("--part1", action="store_true", help="Universe filter experiments")
    parser.add_argument("--part2", action="store_true", help="Factor combination experiments")
    parser.add_argument("--part3", action="store_true", help="Parameter sensitivity")
    parser.add_argument("--part4", action="store_true", help="Advanced strategies")
    parser.add_argument("--part5", action="store_true", help="Summary report")
    parser.add_argument("--all", action="store_true", help="Run all parts")
    parser.add_argument("--exp", type=str, help="Run specific experiment, e.g. '1.3'")
    args = parser.parse_args()

    PHASE24_CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    run_all = args.all

    # Dispatch specific experiment
    if args.exp:
        exp_map = {
            "0.1": part0_1_cost_attribution,
            "0.2": part0_2_annual_decomposition,
            "0.3": part0_3_rebalance_alpha,
            "0.5": part0_5_composite_ic,
            "1.pre": part1_prerequisite,
            "1.2": part1_2_core4_midcap,
            "1.3": part1_3_mcap_range_comparison,
            "1.4": part1_4_midcap_low_sn,
            "2.0": part2_0_factor_profiles,
            "2.1": part2_1_factor_inventory,
            "2.2": part2_2_add_factors,
            "2.3": part2_3_replace_factors,
            "2.4": part2_4_negative_screening,
            "2.5": part2_5_lambdarank_factor,
            "3.1": part3_1_topn_sensitivity,
            "3.2": part3_2_rebalance_freq,
            "3.3": part3_3_sn_beta_sensitivity,
            "4.1": part4_1_ashare_factors,
            "4.2": part4_2_style_diversification,
            "4.3": part4_3_barbell_vs_active,
            "5": part5_summary,
        }
        func = exp_map.get(args.exp)
        if func:
            func()
        else:
            print(f"Unknown experiment: {args.exp}")
            print(f"Available: {sorted(exp_map.keys())}")
        gc.collect()
        print(f"\n  Total elapsed: {(time.time() - t0) / 60:.1f} min")
        return

    if args.part0 or run_all:
        print("\n" + "#" * 70)
        print("# PART 0: ROOT CAUSE DIAGNOSIS")
        print("#" * 70)
        part0_1_cost_attribution()
        gc.collect()
        part0_2_annual_decomposition()
        gc.collect()
        part0_3_rebalance_alpha()
        gc.collect()
        part0_5_composite_ic()
        gc.collect()

    if args.part1 or run_all:
        print("\n" + "#" * 70)
        print("# PART 1: UNIVERSE FILTER EXPERIMENTS")
        print("#" * 70)
        part1_prerequisite()
        gc.collect()
        part1_3_mcap_range_comparison()
        gc.collect()
        part1_2_core4_midcap()
        gc.collect()
        part1_4_midcap_low_sn()
        gc.collect()

    if args.part2 or run_all:
        print("\n" + "#" * 70)
        print("# PART 2: FACTOR COMBINATION EXPERIMENTS (STUBS)")
        print("#" * 70)
        part2_0_factor_profiles()
        part2_1_factor_inventory()
        part2_2_add_factors()
        part2_3_replace_factors()
        part2_4_negative_screening()
        part2_5_lambdarank_factor()

    if args.part3 or run_all:
        print("\n" + "#" * 70)
        print("# PART 3: PARAMETER SENSITIVITY (STUBS)")
        print("#" * 70)
        part3_1_topn_sensitivity()
        part3_2_rebalance_freq()
        part3_3_sn_beta_sensitivity()

    if args.part4 or run_all:
        print("\n" + "#" * 70)
        print("# PART 4: ADVANCED STRATEGIES (STUBS)")
        print("#" * 70)
        part4_1_ashare_factors()
        part4_2_style_diversification()
        part4_3_barbell_vs_active()

    if args.part5 or run_all:
        print("\n" + "#" * 70)
        print("# PART 5: SUMMARY")
        print("#" * 70)
        part5_summary()

    print(f"\n  Total elapsed: {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
