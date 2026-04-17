#!/usr/bin/env python3
"""Step 6-F Part 3: Size-Neutral 回测.

回答: 强制降低 SMB 暴露后, 策略损失多少 alpha?

方案: 对每日因子合成分数 cross-sectional 中性化 ln_market_cap 后排名.
  - 在 SignalComposer 输出 scores 后, 拟合 scores = a + b*ln_mcap + epsilon
  - 用 epsilon (residual) 重新排名替代原始 scores
  - 这样 Top-20 对市值是 ε-中性的

实现:
  - 自定义 build_size_neutral_target_portfolios() 函数
  - 不修改 run_hybrid_backtest 内部 (避免破坏现有回测路径)
  - 用 SimpleBacktester 直接接受 target_portfolios

数据源: cache/backtest/*.parquet (12 年)
基线对照: 12yr in-sample Sharpe=0.5309 (Step 6-D)

输出:
  cache/baseline/size_neutral_result.json
    - base (无约束) 12yr metrics
    - size_neutral 12yr metrics
    - 持仓市值分布对比

用法:
    python scripts/research/size_neutral_backtest.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import pandas as pd  # noqa: E402
from engines.backtest import BacktestConfig, PMSConfig  # noqa: E402
from engines.backtest.engine import SimpleBacktester  # noqa: E402
from engines.backtest.runner import run_hybrid_backtest  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino  # noqa: E402
from engines.signal_engine import (  # noqa: E402
    FACTOR_DIRECTION,
    SignalComposer,
    SignalConfig,
)
from engines.slippage_model import SlippageConfig  # noqa: E402
from engines.vectorized_signal import compute_rebalance_dates  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}


def load_all_data():
    print("[Load] price + benchmark + factors + ln_mcap...")
    t0 = time.time()
    price_parts, bench_parts, factor_parts = [], [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))
        factor_parts.append(pd.read_parquet(yr_dir / "factor_data.parquet"))
    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")
    factor_df = pd.concat(factor_parts, ignore_index=True)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # ln_market_cap from DB (factor_values)
    print("[Load] ln_market_cap from DB...")
    conn = get_sync_conn()
    ln_mcap = pd.read_sql(
        """SELECT code, trade_date, neutral_value AS ln_mcap
           FROM factor_values
           WHERE factor_name = 'ln_market_cap' AND neutral_value IS NOT NULL""",
        conn,
    )
    conn.close()
    print(f"  ln_mcap: {ln_mcap.shape}")
    print(f"  total load: {time.time()-t0:.1f}s")
    return price_df, bench_df, factor_df, ln_mcap


def build_size_neutral_target_portfolios(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    ln_mcap_df: pd.DataFrame,
    directions: dict,
    top_n: int = 20,
    rebalance_freq: str = "monthly",
) -> dict:
    """构造 size-neutral 的 target_portfolios.

    流程:
      1. 用 SignalComposer 算 scores (5因子 z-score 平均)
      2. 在 scores 上做 ln_mcap 中性化: residual = scores - α - β*ln_mcap
      3. 用 residual 排名选 Top-20
      4. PortfolioBuilder 按 residual rank 等权
    """
    se_config = SignalConfig(
        factor_names=list(directions.keys()),
        top_n=top_n,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
    )

    # 注入 directions
    saved = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

    # 构造 per-date exclude 集 (ST/BJ/停牌/新)
    status_by_date = {}
    for col in ("is_st", "is_suspended", "is_new_stock"):
        if col in price_df.columns:
            excluded = price_df.loc[
                price_df[col] == True, ["code", "trade_date"]  # noqa: E712
            ]
            for td, grp in excluded.groupby("trade_date"):
                status_by_date.setdefault(td, set()).update(grp["code"].tolist())
    if "board" in price_df.columns:
        bj = price_df.loc[price_df["board"] == "bse", ["code", "trade_date"]]
        for td, grp in bj.groupby("trade_date"):
            status_by_date.setdefault(td, set()).update(grp["code"].tolist())

    composer = SignalComposer(se_config)

    # 准备 ln_mcap 索引以加速 lookup
    ln_mcap_pivot = ln_mcap_df.pivot_table(
        index="trade_date", columns="code", values="ln_mcap", aggfunc="first"
    ).sort_index()

    trading_days = sorted(price_df["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, rebalance_freq)

    # OOM Fix: 一次性 groupby trade_date 而非每次 boolean filter (avoid 450M row alloc)
    print("[size-neutral] indexing factor_df by trade_date... (avoid OOM)")
    factor_by_date = {td: grp for td, grp in factor_df.groupby("trade_date", sort=False)}
    sorted_dates = sorted(factor_by_date.keys())

    target_portfolios = {}
    try:
        for rd in rebal_dates:
            # Find latest factor date <= rd via binary search
            import bisect
            idx = bisect.bisect_right(sorted_dates, rd) - 1
            if idx < 0:
                continue
            latest_date = sorted_dates[idx]
            day_data = factor_by_date[latest_date]
            exclude = status_by_date.get(latest_date, set())

            scores = composer.compose(day_data, exclude=exclude)
            if scores.empty:
                continue

            # === Size-neutral residualization ===
            if latest_date in ln_mcap_pivot.index:
                ln_mcap_row = ln_mcap_pivot.loc[latest_date]
            else:
                # fallback: 找最近一天
                idx = ln_mcap_pivot.index.searchsorted(latest_date)
                if idx >= len(ln_mcap_pivot):
                    idx = len(ln_mcap_pivot) - 1
                ln_mcap_row = ln_mcap_pivot.iloc[idx]

            df = pd.DataFrame({
                "score": scores,
                "ln_mcap": ln_mcap_row.reindex(scores.index),
            }).dropna()

            if len(df) < top_n + 5:
                continue

            # OLS: score = a + b * ln_mcap → 取 residual
            x = df["ln_mcap"].values
            y = df["score"].values
            x_mean = x.mean()
            y_mean = y.mean()
            x_var = ((x - x_mean) ** 2).sum()
            if x_var > 0:
                beta = ((x - x_mean) * (y - y_mean)).sum() / x_var
                alpha = y_mean - beta * x_mean
                residual = y - (alpha + beta * x)
            else:
                residual = y - y_mean

            df["residual"] = residual
            # Top-N by residual descending
            top = df.nlargest(top_n, "residual")
            weight = 1.0 / len(top)
            target_portfolios[rd] = {code: weight for code in top.index}
    finally:
        FACTOR_DIRECTION.clear()
        FACTOR_DIRECTION.update(saved)

    return target_portfolios


def metrics_from_nav(nav: pd.Series) -> dict:
    returns = nav.pct_change().dropna()
    if len(returns) < 2:
        return {}
    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    n = len(nav)
    years = n / 244
    total_ret = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual = float((1 + total_ret) ** (1 / max(years, 0.01)) - 1)
    return {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 6),
        "sortino": round(sortino, 4),
        "annual": round(annual, 6),
        "total_return": round(total_ret, 6),
        "n_days": n,
    }


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df, factor_df, ln_mcap_df = load_all_data()

    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    # === Base ===
    print("\n[Base] CORE 5 (no size constraint)")
    t0 = time.time()
    base_factor_df = factor_df[factor_df["factor_name"].isin(CORE_DIRECTIONS)].copy()
    base_result = run_hybrid_backtest(
        base_factor_df, CORE_DIRECTIONS, price_df, config, bench_df
    )
    base_metrics = metrics_from_nav(base_result.daily_nav)
    base_metrics["elapsed"] = round(time.time() - t0, 0)
    print(f"  {base_metrics}")

    # === Size-Neutral ===
    print("\n[Size-Neutral] residualize scores by ln_mcap, then Top-20")
    t0 = time.time()
    target_portfolios = build_size_neutral_target_portfolios(
        base_factor_df, price_df, ln_mcap_df, CORE_DIRECTIONS,
        top_n=20, rebalance_freq="monthly",
    )
    print(f"  target_portfolios: {len(target_portfolios)} 个调仓日")

    # 用 SimpleBacktester 跑
    backtester = SimpleBacktester(config)
    sn_result = backtester.run(
        target_portfolios=target_portfolios,
        price_data=price_df,
        benchmark_data=bench_df,
    )
    sn_metrics = metrics_from_nav(sn_result.daily_nav)
    sn_metrics["elapsed"] = round(time.time() - t0, 0)
    print(f"  {sn_metrics}")

    # === 持仓市值分布对比 (从最后一次调仓) ===
    last_signal_date = max(target_portfolios.keys()) if target_portfolios else None
    sn_holdings = list(target_portfolios.get(last_signal_date, {}).keys()) if last_signal_date else []

    # base 的最后调仓持仓 (从 base_result.fills 推算)
    base_fills = base_result.trades if hasattr(base_result, "trades") else []
    base_recent = sorted(set(f.code for f in base_fills[-100:])) if base_fills else []

    # ln_mcap 分布
    if last_signal_date:
        ln_mcap_at_signal = ln_mcap_df[ln_mcap_df["trade_date"] == last_signal_date].set_index("code")["ln_mcap"]
        sn_mcap = ln_mcap_at_signal.reindex(sn_holdings).dropna()
        base_mcap = ln_mcap_at_signal.reindex(base_recent).dropna()
        size_dist = {
            "signal_date": str(last_signal_date),
            "base_mean_ln_mcap": round(float(base_mcap.mean()), 4) if len(base_mcap) > 0 else None,
            "base_median_ln_mcap": round(float(base_mcap.median()), 4) if len(base_mcap) > 0 else None,
            "sn_mean_ln_mcap": round(float(sn_mcap.mean()), 4) if len(sn_mcap) > 0 else None,
            "sn_median_ln_mcap": round(float(sn_mcap.median()), 4) if len(sn_mcap) > 0 else None,
            "base_n": len(base_mcap),
            "sn_n": len(sn_mcap),
        }
    else:
        size_dist = {}

    output = {
        "meta": {
            "config": {
                "top_n": 20,
                "rebalance": "monthly",
                "slippage": "volume_impact",
                "stamp_tax": "historical",
                "pms": True,
            },
            "method": "Size-neutral via OLS residualization of scores on ln_mcap",
        },
        "base": base_metrics,
        "size_neutral": sn_metrics,
        "delta": {
            "sharpe_diff": round(sn_metrics["sharpe"] - base_metrics["sharpe"], 4),
            "mdd_diff": round(sn_metrics["mdd"] - base_metrics["mdd"], 6),
            "annual_diff": round(sn_metrics["annual"] - base_metrics["annual"], 4),
        },
        "holding_size_distribution": size_dist,
    }

    out_path = BASELINE_DIR / "size_neutral_result.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    print("\n" + "=" * 76)
    print("  Size-Neutral Backtest")
    print("=" * 76)
    print(f"  Base:          Sharpe={base_metrics['sharpe']}, MDD={base_metrics['mdd']:.2%}, Annual={base_metrics['annual']:.2%}")
    print(f"  Size-Neutral:  Sharpe={sn_metrics['sharpe']}, MDD={sn_metrics['mdd']:.2%}, Annual={sn_metrics['annual']:.2%}")
    print(f"  Delta:         Sharpe={output['delta']['sharpe_diff']:+.4f}, MDD={output['delta']['mdd_diff']:+.2%}, Annual={output['delta']['annual_diff']:+.4f}")
    if size_dist:
        print(f"  Last signal: {size_dist['signal_date']}")
        print(f"    Base ln_mcap mean: {size_dist['base_mean_ln_mcap']}")
        print(f"    SN ln_mcap mean: {size_dist['sn_mean_ln_mcap']}")
    print("=" * 76)


if __name__ == "__main__":
    main()
