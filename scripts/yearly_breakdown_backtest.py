#!/usr/bin/env python3
"""Step 6-D Part 1: 2014-2026 逐年度回测 (填补 WF 盲区).

每个自然年度单独跑 run_hybrid_backtest, 配置跟 WF 一致:
  5 因子等权 / Top-20 / monthly / volume_impact / historical stamp tax / PMS v1.0
  Universe: exclude BJ/ST/suspended/new_stock

数据源: cache/backtest/*/*.parquet (2014-2026 各年份)
2026 是 partial year (到 2026-04-09 为止)

输出: cache/baseline/yearly_breakdown.json

用法:
    python scripts/yearly_breakdown_backtest.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from engines.backtest import BacktestConfig, PMSConfig  # noqa: E402
from engines.backtest.runner import run_hybrid_backtest  # noqa: E402
from engines.metrics import (  # noqa: E402
    calc_calmar,
    calc_max_drawdown,
    calc_sharpe,
    calc_sortino,
)
from engines.slippage_model import SlippageConfig  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "backtest"

DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}

FACTOR_LOOKBACK_DAYS = 60  # 因子 warmup, 避免年初调仓日因子 NaN


def load_year_data(year: int):
    """加载某一年的回测数据 + 前 60 天因子 lookback。"""
    yr_dir = CACHE_DIR / str(year)
    prev_yr_dir = CACHE_DIR / str(year - 1)

    price_df = pd.read_parquet(yr_dir / "price_data.parquet")
    factor_df = pd.read_parquet(yr_dir / "factor_data.parquet")
    bench_df = pd.read_parquet(yr_dir / "benchmark.parquet")

    # 因子 lookback: 从前一年 12 月拼接约 60 天
    if prev_yr_dir.exists():
        prev_factor = pd.read_parquet(prev_yr_dir / "factor_data.parquet")
        prev_factor = prev_factor[
            prev_factor["trade_date"] >= (date(year, 1, 1) - timedelta(days=FACTOR_LOOKBACK_DAYS))
        ]
        factor_df = pd.concat([prev_factor, factor_df], ignore_index=True)

    # 列名兼容
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    return factor_df, price_df, bench_df


def monthly_win_rate(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    nav = nav.copy()
    nav.index = pd.to_datetime(nav.index)
    monthly = nav.resample("ME").last().pct_change().dropna()
    if len(monthly) == 0:
        return 0.0
    return float((monthly > 0).sum() / len(monthly))


def run_year(year: int, config: BacktestConfig) -> dict:
    """跑一个自然年度。"""
    print(f"[Year {year}] loading...")
    factor_df, price_df, bench_df = load_year_data(year)

    # price/bench 限制在该年度 (factor 已含 lookback)
    price_df = price_df[
        (price_df["trade_date"] >= date(year, 1, 1))
        & (price_df["trade_date"] <= date(year, 12, 31))
    ].copy()
    bench_df = bench_df[
        (bench_df["trade_date"] >= date(year, 1, 1))
        & (bench_df["trade_date"] <= date(year, 12, 31))
    ].copy()

    if price_df.empty:
        print(f"  WARNING: no price data for {year}")
        return None

    t0 = time.time()
    result = run_hybrid_backtest(factor_df, DIRECTIONS, price_df, config, bench_df)
    elapsed = time.time() - t0

    nav = result.daily_nav
    returns = nav.pct_change().dropna()

    if len(returns) < 2:
        return None

    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    days = len(nav)
    years_covered = days / 244.0
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years_covered, 0.01)) - 1)
    calmar = float(calc_calmar(annual_return, mdd)) if mdd < 0 else 0.0
    win_rate = monthly_win_rate(nav)

    # partial year 标记
    is_partial = days < 200

    return {
        "year": year,
        "is_partial": is_partial,
        "trading_days": days,
        "date_start": str(nav.index[0]),
        "date_end": str(nav.index[-1]),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 6),
        "annual_return": round(annual_return, 6),
        "total_return": round(total_return, 6),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "monthly_win_rate": round(win_rate, 4),
        "total_trades": len(result.trades) if hasattr(result, "trades") else 0,
        "nav_start": float(nav.iloc[0]),
        "nav_end": float(nav.iloc[-1]),
        "elapsed_sec": round(elapsed, 1),
        "nav_series": nav,  # 用于后续 chain-link
    }


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    years = list(range(2014, 2027))
    print(f"\n[Backtest] 逐年度 {years[0]}..{years[-1]} (13 年)")

    results = []
    total_t0 = time.time()
    for year in years:
        r = run_year(year, config)
        if r is None:
            continue
        results.append(r)
        partial_flag = " (partial)" if r["is_partial"] else ""
        print(
            f"  {year}{partial_flag}: "
            f"Sharpe={r['sharpe']:+.4f}  "
            f"MDD={r['mdd']:+.2%}  "
            f"Annual={r['annual_return']:+.2%}  "
            f"Calmar={r['calmar']:+.3f}  "
            f"WinRate={r['monthly_win_rate']:.2%}  "
            f"Trades={r['total_trades']:>4}  "
            f"({r['elapsed_sec']:.0f}s)"
        )

    total_elapsed = time.time() - total_t0
    print(f"\n总耗时: {total_elapsed:.0f}s")

    # 统计 (排除 partial year)
    full_years = [r for r in results if not r["is_partial"]]
    sharpes = np.array([r["sharpe"] for r in full_years])
    mdds = np.array([r["mdd"] for r in full_years])
    annuals = np.array([r["annual_return"] for r in full_years])

    # 异常年度定位
    neg_years = [r["year"] for r in full_years if r["sharpe"] < 0]
    deep_dd_years = [r["year"] for r in full_years if r["mdd"] < -0.30]

    stats = {
        "sharpe_mean": round(float(sharpes.mean()), 4),
        "sharpe_median": round(float(np.median(sharpes)), 4),
        "sharpe_std": round(float(sharpes.std(ddof=1)) if len(sharpes) > 1 else 0.0, 4),
        "sharpe_min": round(float(sharpes.min()), 4),
        "sharpe_max": round(float(sharpes.max()), 4),
        "mdd_mean": round(float(mdds.mean()), 6),
        "mdd_worst": round(float(mdds.min()), 6),
        "annual_mean": round(float(annuals.mean()), 6),
        "negative_sharpe_years": neg_years,
        "deep_drawdown_years": deep_dd_years,
        "total_full_years": len(full_years),
    }

    # 12年 chain-link NAV (用于后续 FF3 归因)
    print("\n[Chain-Link] 拼接 12 年 NAV (收益率链接)...")
    all_returns = pd.concat(
        [r["nav_series"].pct_change().dropna() for r in results]
    ).sort_index()
    all_returns = all_returns[~all_returns.index.duplicated(keep="first")]
    chain_nav = (1.0 + all_returns).cumprod() * 1_000_000
    print(f"  Chain NAV: {len(chain_nav)} 天 ({chain_nav.index[0]}..{chain_nav.index[-1]})")
    print(f"  Chain NAV end: {chain_nav.iloc[-1]:,.0f}")

    # 保存
    output = {
        "config": {
            "factors": list(DIRECTIONS.keys()),
            "directions": DIRECTIONS,
            "top_n": 20,
            "rebalance_freq": "monthly",
            "initial_capital": 1_000_000,
            "slippage": "volume_impact",
            "stamp_tax": "historical",
            "pms_enabled": True,
            "universe": "exclude BJ/ST/suspended/new_stock",
        },
        "years": [
            {k: v for k, v in r.items() if k != "nav_series"} for r in results
        ],
        "stats": stats,
        "total_elapsed_sec": round(total_elapsed, 0),
    }

    json_path = BASELINE_DIR / "yearly_breakdown.json"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n[Save] {json_path}")

    # 保存 chain NAV (给 FF3 用)
    nav_df = chain_nav.to_frame("nav").copy()
    nav_df.index.name = "trade_date"
    nav_path = BASELINE_DIR / "yearly_chain_nav.parquet"
    nav_df.reset_index().to_parquet(nav_path, index=False)
    print(f"[Save] {nav_path}")

    # 最终报告
    print("\n" + "=" * 88)
    print("  QuantMind V2 — 2014-2026 逐年度回测")
    print("=" * 88)
    print(
        f"\n  {'Year':>6}  {'Sharpe':>8}  {'MDD':>8}  {'Annual':>8}  "
        f"{'Calmar':>8}  {'WinRate':>8}  {'Trades':>7}  {'Regime Hint'}"
    )
    print(
        f"  {'----':>6}  {'-'*8:>8}  {'-'*8:>8}  {'-'*8:>8}  "
        f"{'-'*8:>8}  {'-'*8:>8}  {'-'*7:>7}  {'-'*30}"
    )

    regime_hints = {
        2014: "大牛市 (融资+杠杆)",
        2015: "大牛+股灾+熔断前夜",
        2016: "熔断+反弹",
        2017: "蓝筹行情 (茅指数)",
        2018: "大熊市 (贸易战)",
        2019: "修复性反弹",
        2020: "疫情+核心资产",
        2021: "小盘牛 (抱团瓦解)",
        2022: "熊+反复 (俄乌)",
        2023: "AI主题牛+其他杀",
        2024: "政策密集期",
        2025: "小盘/北交所回暖",
        2026: "当前 (partial)",
    }
    for r in results:
        partial = " *" if r["is_partial"] else "  "
        hint = regime_hints.get(r["year"], "")
        print(
            f"  {r['year']:>4}{partial} "
            f"{r['sharpe']:>8.4f}  {r['mdd']:>+8.2%}  {r['annual_return']:>+8.2%}  "
            f"{r['calmar']:>8.3f}  {r['monthly_win_rate']:>8.2%}  "
            f"{r['total_trades']:>7}  {hint}"
        )
    print("\n  * = partial year")

    print(f"\n  Full years ({len(full_years)}): "
          f"Sharpe mean={stats['sharpe_mean']}, median={stats['sharpe_median']}, "
          f"std={stats['sharpe_std']}")
    print(f"  Sharpe range: [{stats['sharpe_min']}, {stats['sharpe_max']}]")
    print(f"  MDD mean / worst: {stats['mdd_mean']:.2%} / {stats['mdd_worst']:.2%}")
    print(f"  Annual mean: {stats['annual_mean']:.2%}")
    print(f"  Negative-Sharpe years: {neg_years}")
    print(f"  Deep DD years (<-30%): {deep_dd_years}")
    print("=" * 88)


if __name__ == "__main__":
    main()
