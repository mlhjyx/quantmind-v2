#!/usr/bin/env python3
"""Step 6-G: Modifier Layer Experiments — Vol-Targeting + Drawdown-Aware + Partial Size-Neutral.

Part 1: Vol-Targeting (A: tiered, B: inverse proportional)
Part 2: Drawdown-Aware sizing (60d / 40d / 20d lookback)
Part 3: Partial Size-Neutral (beta = 0.25, 0.50, 0.75, 1.00)
Part 4: Combined Modifiers (top single × Vol + Drawdown / + Size-neutral)

Modifier approach: **OUTER WRAPPER** — 跑 base backtest 一次, 用 daily returns 叠加信号做
位置缩放 (scaled_ret = position_mult × base_ret + (1-mult) × cash_ret).

优点: 一次 base 跑 + 多配置比较, ~7 分钟
缺点: 不捕捉 modifier 改变实际 rebalance 的交易成本效应 (approximation).

OOS 验证: 2014-2020 训练阈值, 2021-2026 测试.

输出: cache/baseline/modifier_experiments.json

用法:
    python scripts/research/modifier_experiments.py
"""

from __future__ import annotations

import bisect
import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from engines.backtest import BacktestConfig, PMSConfig  # noqa: E402
from engines.backtest.engine import SimpleBacktester  # noqa: E402
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

CASH_DAILY_RATE = 0.025 / 244  # 2.5% 年化 / 244


# ============================================================
# 数据加载
# ============================================================


def load_all_data():
    print("[Load] 12yr price + benchmark + core factors (CORE 5 filtered)...")
    t0 = time.time()
    price_parts, bench_parts, factor_parts = [], [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))
        # OOM fix (Step 6-G): 按 CORE 5 过滤后再 append, 避免 58M 行 concat
        # 之前: 全部 63 因子 concat → 58M 行 → run_hybrid_backtest 内 boolean filter OOM
        # 现在: 只保留 CORE 5 → ~10M 行, peak RAM 从 ~12GB 降到 ~2GB
        fp = pd.read_parquet(yr_dir / "factor_data.parquet")
        factor_parts.append(fp[fp["factor_name"].isin(CORE_DIRECTIONS)].copy())
    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")
    factor_df = pd.concat(factor_parts, ignore_index=True)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    print(f"  price {price_df.shape}, bench {bench_df.shape}, factor {factor_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df, factor_df


def load_ln_mcap():
    print("[Load] ln_market_cap from DB...")
    t0 = time.time()
    conn = get_sync_conn()
    df = pd.read_sql(
        """SELECT code, trade_date, neutral_value AS ln_mcap
           FROM factor_values
           WHERE factor_name = 'ln_market_cap' AND neutral_value IS NOT NULL""",
        conn,
    )
    conn.close()
    print(f"  ln_mcap {df.shape}, {time.time()-t0:.1f}s")
    return df


# ============================================================
# Metrics 工具
# ============================================================


def nav_from_returns(returns: pd.Series, initial: float = 1_000_000) -> pd.Series:
    return (1 + returns).cumprod() * initial


def compute_metrics(nav: pd.Series, returns: pd.Series | None = None) -> dict:
    if returns is None:
        returns = nav.pct_change().dropna()
    if len(returns) < 2:
        return {}
    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    n = len(nav)
    years = n / 244.0
    total = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual = float((1 + total) ** (1 / max(years, 0.01)) - 1)
    calmar = annual / abs(mdd) if mdd < 0 else 0.0
    return {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 6),
        "annual": round(annual, 6),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "total_return": round(total, 6),
        "n_days": int(n),
    }


def yearly_sharpe(returns: pd.Series) -> dict:
    r = returns.copy()
    r.index = pd.to_datetime(r.index)
    yearly = {}
    for year in range(2014, 2027):
        sub = r[r.index.year == year]
        if len(sub) < 20:
            continue
        yearly[year] = round(float(calc_sharpe(sub)), 4)
    return yearly


# ============================================================
# Part 1: Vol-Targeting signals
# ============================================================


def compute_bench_vol_20d(bench_df: pd.DataFrame) -> pd.Series:
    """CSI300 20日 realized volatility (年化)."""
    df = bench_df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").set_index("trade_date")
    df["ret"] = df["close"].pct_change()
    vol = df["ret"].rolling(20).std() * np.sqrt(244)
    return vol.dropna()


def vol_tiered_signal(vol_20d: pd.Series) -> pd.Series:
    """方案 A: 阶梯式仓位."""
    def _tier(v):
        if np.isnan(v):
            return 1.0
        if v < 0.15:
            return 1.0
        if v < 0.25:
            return 0.7
        if v < 0.35:
            return 0.5
        return 0.3
    return vol_20d.apply(_tier)


def vol_targeted_signal(vol_20d: pd.Series, target_vol: float = 0.15) -> pd.Series:
    """方案 B: 目标波动率 (inverse proportional)."""
    mult = (target_vol / vol_20d).clip(upper=1.0, lower=0.2)
    return mult.fillna(1.0)


# ============================================================
# Part 2: Drawdown-Aware signals
# ============================================================


def drawdown_aware_signal(nav: pd.Series, lookback: int = 60) -> pd.Series:
    """60 日回看计算 drawdown, 根据深度缩放仓位."""
    nav_copy = nav.copy()
    nav_copy.index = pd.to_datetime(nav_copy.index)
    rolling_max = nav_copy.rolling(lookback, min_periods=1).max()
    dd = nav_copy / rolling_max - 1  # 负值

    def _tier(d):
        if d > -0.10:
            return 1.0
        if d > -0.20:
            return 0.5
        return 0.2

    return dd.apply(_tier)


# ============================================================
# Modifier wrapper (outer)
# ============================================================


def apply_modifier(
    base_returns: pd.Series, mult_signal: pd.Series, cash_rate: float = CASH_DAILY_RATE
) -> pd.Series:
    """叠加 modifier 信号缩放日收益, 缺信号部分按现金算."""
    r = base_returns.copy()
    r.index = pd.to_datetime(r.index)
    s = mult_signal.copy()
    s.index = pd.to_datetime(s.index)
    # shift 1 日避免前视偏差 (T 日看信号, T+1 日执行)
    s_lagged = s.shift(1).reindex(r.index, method="ffill").fillna(1.0)
    # 对齐 cash + 持仓
    scaled = s_lagged * r + (1 - s_lagged) * cash_rate
    return scaled


# ============================================================
# Part 3: Partial Size-Neutral
# ============================================================


def partial_size_neutral_targets(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    ln_mcap_df: pd.DataFrame,
    directions: dict,
    beta: float,
    top_n: int = 20,
    rebalance_freq: str = "monthly",
) -> dict:
    """对 scores 做部分中性化: score_final = score - beta * zscore(ln_mcap).

    beta=0 → 无中性化 (base)
    beta=1 → 完全中性化 (Step 6-F)
    beta=0.5 → 部分
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
    saved = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

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

    ln_mcap_pivot = ln_mcap_df.pivot_table(
        index="trade_date", columns="code", values="ln_mcap", aggfunc="first"
    ).sort_index()

    trading_days = sorted(price_df["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, rebalance_freq)

    # Date-indexed (OOM fix from Part 3 Step 6-F)
    factor_by_date = {td: grp for td, grp in factor_df.groupby("trade_date", sort=False)}
    sorted_fdates = sorted(factor_by_date.keys())

    target_portfolios = {}
    try:
        for rd in rebal_dates:
            idx = bisect.bisect_right(sorted_fdates, rd) - 1
            if idx < 0:
                continue
            latest_date = sorted_fdates[idx]
            day_data = factor_by_date[latest_date]
            exclude = status_by_date.get(latest_date, set())

            scores = composer.compose(day_data, exclude=exclude)
            if scores.empty:
                continue

            if latest_date in ln_mcap_pivot.index:
                ln_mcap_row = ln_mcap_pivot.loc[latest_date]
            else:
                idx2 = ln_mcap_pivot.index.searchsorted(latest_date)
                if idx2 >= len(ln_mcap_pivot):
                    idx2 = len(ln_mcap_pivot) - 1
                ln_mcap_row = ln_mcap_pivot.iloc[idx2]

            df = pd.DataFrame({
                "score": scores,
                "ln_mcap": ln_mcap_row.reindex(scores.index),
            }).dropna()
            if len(df) < top_n + 5:
                continue

            # Z-score ln_mcap
            mv_mean = df["ln_mcap"].mean()
            mv_std = df["ln_mcap"].std()
            if mv_std > 0:
                df["ln_mcap_z"] = (df["ln_mcap"] - mv_mean) / mv_std
            else:
                df["ln_mcap_z"] = 0.0

            # Partial neutralization
            df["adj_score"] = df["score"] - beta * df["ln_mcap_z"]

            top = df.nlargest(top_n, "adj_score")
            weight = 1.0 / len(top)
            target_portfolios[rd] = {code: weight for code in top.index}
    finally:
        FACTOR_DIRECTION.clear()
        FACTOR_DIRECTION.update(saved)

    return target_portfolios


# ============================================================
# OOS evaluator
# ============================================================


def split_metrics(returns: pd.Series) -> dict:
    """Train 2014-2020 vs Test 2021-2026."""
    r = returns.copy()
    r.index = pd.to_datetime(r.index)
    train = r[r.index < pd.Timestamp("2021-01-01")]
    test = r[r.index >= pd.Timestamp("2021-01-01")]
    return {
        "train_2014_2020": compute_metrics(nav_from_returns(train), train),
        "test_2021_2026": compute_metrics(nav_from_returns(test), test),
    }


# ============================================================
# Main
# ============================================================


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df, factor_df = load_all_data()
    # 提前加载 ln_mcap_df 供 base case + Part 3 共享 (避免后期重新加载)
    ln_mcap_df = load_ln_mcap()

    # Base CORE 5 — 使用 SignalComposer 路径 (内存友好, 避免 run_hybrid_backtest 内部 O(n) 循环)
    # 之前 OOM 根因: run_hybrid_backtest 内 factor_df[factor_df["trade_date"] <= rd] 对 14.7M 行
    # 每调仓日分配 ~337 MiB 瞬态 DataFrame, 148 个 rebal 日累计 peak 撑爆内存。
    # 新路径: 复用 partial_size_neutral_targets(beta=0.0) — 同样 Top-20 等权但走 date-indexed 字典,
    # 内存峰值 <3GB (已被 Step 6-F size_neutral_backtest 验证)。
    print("\n[Base] CORE 5 — SignalComposer 路径 (内存安全, beta=0.0 ≡ 无 size-neutral)")
    t0 = time.time()
    base_factor_df = factor_df[factor_df["factor_name"].isin(CORE_DIRECTIONS)].copy()
    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )
    base_targets = partial_size_neutral_targets(
        base_factor_df, price_df, ln_mcap_df, CORE_DIRECTIONS,
        beta=0.0, top_n=20, rebalance_freq="monthly",
    )
    base_backtester = SimpleBacktester(config)
    base_result = base_backtester.run(
        target_portfolios=base_targets,
        price_data=price_df,
        benchmark_data=bench_df,
    )
    base_nav = base_result.daily_nav
    base_ret = base_nav.pct_change().dropna()
    base_metrics = compute_metrics(base_nav, base_ret)
    base_yearly = yearly_sharpe(base_ret)
    print(f"  Base: {base_metrics} ({time.time()-t0:.0f}s)")

    results = {
        "base": {
            "metrics": base_metrics,
            "yearly": base_yearly,
            "oos_split": split_metrics(base_ret),
        }
    }

    # ========== Part 1: Vol-Targeting ==========
    print("\n[Part 1] Vol-Targeting")
    vol_20d = compute_bench_vol_20d(bench_df)
    print(f"  CSI300 vol_20d: mean={float(vol_20d.mean()):.3f}, max={float(vol_20d.max()):.3f}, min={float(vol_20d.min()):.3f}")

    vol_signals = {
        "vol_tiered": vol_tiered_signal(vol_20d),
        "vol_target_015": vol_targeted_signal(vol_20d, target_vol=0.15),
        "vol_target_020": vol_targeted_signal(vol_20d, target_vol=0.20),
    }

    for name, sig in vol_signals.items():
        scaled_ret = apply_modifier(base_ret, sig)
        scaled_nav = nav_from_returns(scaled_ret)
        m = compute_metrics(scaled_nav, scaled_ret)
        y = yearly_sharpe(scaled_ret)
        oos = split_metrics(scaled_ret)
        print(f"  [{name}] Sharpe={m.get('sharpe')}, MDD={m.get('mdd'):.2%}, Annual={m.get('annual'):.2%}")
        print(f"    OOS train Sharpe={oos['train_2014_2020'].get('sharpe')}, test Sharpe={oos['test_2021_2026'].get('sharpe')}")
        # Average position over time
        s_lagged = sig.shift(1).reindex(base_ret.index, method="ffill").fillna(1.0)
        avg_pos = float(s_lagged.mean())
        results[name] = {
            "metrics": m,
            "yearly": y,
            "oos_split": oos,
            "avg_position": round(avg_pos, 4),
            "vs_base": {
                "sharpe_diff": round(m.get("sharpe", 0) - base_metrics.get("sharpe", 0), 4),
                "mdd_diff": round(m.get("mdd", 0) - base_metrics.get("mdd", 0), 6),
                "annual_diff": round(m.get("annual", 0) - base_metrics.get("annual", 0), 4),
            },
        }

    # ========== Part 2: Drawdown-Aware ==========
    print("\n[Part 2] Drawdown-Aware")
    for lookback in [20, 40, 60]:
        name = f"dd_aware_{lookback}d"
        sig = drawdown_aware_signal(base_nav, lookback=lookback)
        scaled_ret = apply_modifier(base_ret, sig)
        scaled_nav = nav_from_returns(scaled_ret)
        m = compute_metrics(scaled_nav, scaled_ret)
        y = yearly_sharpe(scaled_ret)
        oos = split_metrics(scaled_ret)
        print(f"  [{name}] Sharpe={m.get('sharpe')}, MDD={m.get('mdd'):.2%}, Annual={m.get('annual'):.2%}")
        s_lagged = sig.shift(1).reindex(base_ret.index, method="ffill").fillna(1.0)
        avg_pos = float(s_lagged.mean())
        results[name] = {
            "metrics": m,
            "yearly": y,
            "oos_split": oos,
            "avg_position": round(avg_pos, 4),
            "vs_base": {
                "sharpe_diff": round(m.get("sharpe", 0) - base_metrics.get("sharpe", 0), 4),
                "mdd_diff": round(m.get("mdd", 0) - base_metrics.get("mdd", 0), 6),
                "annual_diff": round(m.get("annual", 0) - base_metrics.get("annual", 0), 4),
            },
        }

    # ========== Part 3: Partial Size-Neutral ==========
    # ln_mcap_df 已在 main() 开头加载, 直接复用
    print("\n[Part 3] Partial Size-Neutral")

    for beta in [0.25, 0.50, 0.75]:
        name = f"size_neutral_b{int(beta*100):03d}"
        print(f"  [{name}] building target_portfolios with beta={beta}...")
        t0 = time.time()
        targets = partial_size_neutral_targets(
            base_factor_df, price_df, ln_mcap_df, CORE_DIRECTIONS,
            beta=beta, top_n=20, rebalance_freq="monthly",
        )
        backtester = SimpleBacktester(config)
        sn_result = backtester.run(
            target_portfolios=targets,
            price_data=price_df,
            benchmark_data=bench_df,
        )
        sn_nav = sn_result.daily_nav
        sn_ret = sn_nav.pct_change().dropna()
        m = compute_metrics(sn_nav, sn_ret)
        y = yearly_sharpe(sn_ret)
        oos = split_metrics(sn_ret)
        print(f"    Sharpe={m.get('sharpe')}, MDD={m.get('mdd'):.2%}, Annual={m.get('annual'):.2%}, {time.time()-t0:.0f}s")
        results[name] = {
            "metrics": m,
            "yearly": y,
            "oos_split": oos,
            "beta": beta,
            "vs_base": {
                "sharpe_diff": round(m.get("sharpe", 0) - base_metrics.get("sharpe", 0), 4),
                "mdd_diff": round(m.get("mdd", 0) - base_metrics.get("mdd", 0), 6),
                "annual_diff": round(m.get("annual", 0) - base_metrics.get("annual", 0), 4),
            },
        }

    # ========== Part 4: Combined ==========
    print("\n[Part 4] Combined Modifiers (base × best single)")

    # 选最好的 vol 和 dd (by Sharpe)
    best_vol = max(vol_signals.keys(), key=lambda k: results[k]["metrics"].get("sharpe", -99))
    best_dd = max(
        [f"dd_aware_{l}d" for l in (20, 40, 60)],
        key=lambda k: results[k]["metrics"].get("sharpe", -99),
    )
    print(f"  best vol: {best_vol}, best dd: {best_dd}")

    # Combined: vol × dd
    vol_sig = vol_signals[best_vol]
    dd_sig = drawdown_aware_signal(base_nav, lookback=int(best_dd.split("_")[-1].rstrip("d")))
    # 合并: 取乘积 (最保守)
    r = base_ret.copy()
    r.index = pd.to_datetime(r.index)
    vs = vol_sig.shift(1).reindex(r.index, method="ffill").fillna(1.0)
    ds = dd_sig.shift(1).reindex(r.index, method="ffill").fillna(1.0)
    combined_sig = vs * ds  # product
    scaled_ret = combined_sig * r + (1 - combined_sig) * CASH_DAILY_RATE
    scaled_nav = nav_from_returns(scaled_ret)
    m_c = compute_metrics(scaled_nav, scaled_ret)
    y_c = yearly_sharpe(scaled_ret)
    oos_c = split_metrics(scaled_ret)
    print(f"  [combined_vol_dd] Sharpe={m_c.get('sharpe')}, MDD={m_c.get('mdd'):.2%}, Annual={m_c.get('annual'):.2%}")
    results["combined_vol_dd"] = {
        "metrics": m_c,
        "yearly": y_c,
        "oos_split": oos_c,
        "combo": [best_vol, best_dd],
        "avg_position": round(float(combined_sig.mean()), 4),
        "vs_base": {
            "sharpe_diff": round(m_c.get("sharpe", 0) - base_metrics.get("sharpe", 0), 4),
            "mdd_diff": round(m_c.get("mdd", 0) - base_metrics.get("mdd", 0), 6),
            "annual_diff": round(m_c.get("annual", 0) - base_metrics.get("annual", 0), 4),
        },
    }

    # Save
    out_path = BASELINE_DIR / "modifier_experiments.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    # 报告
    print("\n" + "=" * 100)
    print("  Modifier Experiments 汇总")
    print("=" * 100)
    print(
        f"  {'Experiment':<28} {'Sharpe':>7} {'Δ':>7} {'MDD':>8} {'Δ':>8} "
        f"{'Annual':>8} {'Δ':>8} {'TrainS':>7} {'TestS':>7} {'AvgPos':>7}"
    )
    print("  " + "-" * 98)
    for name, r in results.items():
        m = r["metrics"]
        vb = r.get("vs_base", {})
        oos = r.get("oos_split", {})
        train_s = oos.get("train_2014_2020", {}).get("sharpe", "-")
        test_s = oos.get("test_2021_2026", {}).get("sharpe", "-")
        ap = r.get("avg_position", "-")
        sd = vb.get("sharpe_diff", 0) if vb else 0
        md = vb.get("mdd_diff", 0) if vb else 0
        ad = vb.get("annual_diff", 0) if vb else 0
        print(
            f"  {name:<28} {m.get('sharpe', 0):>7.4f} {sd:>+7.4f} "
            f"{m.get('mdd', 0):>+8.2%} {md:>+8.2%} "
            f"{m.get('annual', 0):>+8.2%} {ad:>+8.4f} "
            f"{str(train_s):>7} {str(test_s):>7} {str(ap):>7}"
        )
    print("=" * 100)


if __name__ == "__main__":
    main()
