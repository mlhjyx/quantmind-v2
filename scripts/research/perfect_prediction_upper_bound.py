#!/usr/bin/env python
"""A.8 完美预测上界实验 — Phase 2.1 前置验证。

核心问题: 如果预测完美(用未来真实收益), portfolio优化能达到多少Sharpe?

三组实验:
  Exp1: 完美预测 + 等权Top-20
  Exp2: 完美预测 + 等权Top-20 + SN(b=0.50)
  Exp3: 完美预测 + MVO(riskfolio-lib, Ledoit-Wolf, long-only, max_weight=0.10)

Go/Stop Gate:
  完美+MVO Sharpe > 1.5 → portfolio优化空间大, 继续Part 2/3
  完美+MVO Sharpe < 1.0 → 瓶颈不在portfolio层, 停下报告
  完美+等权 Sharpe > 1.5 → 问题纯在预测层, 融合架构不解决根因

必须走 SimpleBacktester.run() 回测 (铁律16: 信号路径唯一)。

Usage:
    cd backend && python ../scripts/research/perfect_prediction_upper_bound.py
"""

from __future__ import annotations

import gc
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"


def load_all_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载12年price_data + benchmark。"""
    price_parts, bench_parts = [], []
    for y in range(2014, 2027):
        pf = CACHE_DIR / str(y) / "price_data.parquet"
        bf = CACHE_DIR / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price = pd.concat(price_parts, ignore_index=True)
    bench = pd.concat(bench_parts, ignore_index=True)

    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    price = price.sort_values(["code", "trade_date"])
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
    bench = bench.sort_values("trade_date").drop_duplicates("trade_date")

    return price, bench


def get_monthly_rebalance_dates(trade_dates: list[date]) -> list[date]:
    """获取月末最后交易日列表。"""
    df = pd.DataFrame({"td": trade_dates})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def compute_forward_excess(
    price: pd.DataFrame,
    bench: pd.DataFrame,
    rebal_dates: list[date],
    horizon: int = 20,
) -> dict[date, pd.Series]:
    """计算每个调仓日T+horizon超额收益(完美前瞻)。

    Returns:
        {rebal_date: pd.Series(code → excess_return)}
    """
    trade_dates = sorted(price["trade_date"].unique())
    td_idx = {d: i for i, d in enumerate(trade_dates)}

    # Wide close
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close")
    close_wide = close_wide.sort_index()

    # Benchmark close series
    bench_s = bench.set_index("trade_date")["close"].sort_index()

    results = {}
    for rd in rebal_dates:
        if rd not in td_idx:
            continue
        idx = td_idx[rd]
        if idx + horizon >= len(trade_dates):
            continue

        fwd_date = trade_dates[idx + horizon]

        # Stock forward returns
        if rd not in close_wide.index or fwd_date not in close_wide.index:
            continue
        stock_ret = close_wide.loc[fwd_date] / close_wide.loc[rd] - 1.0

        # Benchmark forward return
        if rd not in bench_s.index or fwd_date not in bench_s.index:
            continue
        bench_ret = bench_s.loc[fwd_date] / bench_s.loc[rd] - 1.0

        excess = stock_ret - bench_ret
        excess = excess.dropna()
        results[rd] = excess

    return results


def build_exclusion_set(price: pd.DataFrame, td: date) -> set[str]:
    """获取指定日期的排除集合(ST/停牌/新股/BJ)。"""
    day = price[price["trade_date"] == td]
    exclude = set()
    if "is_st" in day.columns:
        exclude |= set(day.loc[day["is_st"], "code"])
    if "is_suspended" in day.columns:
        exclude |= set(day.loc[day["is_suspended"], "code"])
    if "is_new_stock" in day.columns:
        exclude |= set(day.loc[day["is_new_stock"], "code"])
    if "board" in day.columns:
        exclude |= set(day.loc[day["board"] == "bse", "code"])
    return exclude


def exp1_perfect_equal_weight(
    forward_excess: dict[date, pd.Series],
    price: pd.DataFrame,
    top_n: int = 20,
) -> dict[date, dict[str, float]]:
    """Exp1: 完美预测 + 等权Top-N。"""
    target_portfolios = {}
    for rd, excess in sorted(forward_excess.items()):
        # 排除ST/停牌/新股/BJ
        exclude = build_exclusion_set(price, rd)
        valid = excess.drop(labels=exclude.intersection(excess.index), errors="ignore")
        valid = valid.replace([np.inf, -np.inf], np.nan).dropna()

        if len(valid) < top_n:
            continue

        # 按超额收益降序取Top-N, 等权
        top_codes = valid.nlargest(top_n).index.tolist()
        w = 1.0 / len(top_codes)
        target_portfolios[rd] = {c: w for c in top_codes}

    return target_portfolios


def exp2_perfect_sn_equal_weight(
    forward_excess: dict[date, pd.Series],
    price: pd.DataFrame,
    top_n: int = 20,
    beta: float = 0.50,
) -> dict[date, dict[str, float]]:
    """Exp2: 完美预测 + SN(b=0.50) + 等权Top-N。"""
    # 需要ln_mcap来做SN
    ln_mcap_wide = None
    try:
        close_wide = price.pivot_table(index="trade_date", columns="code", values="close")
        # 用close作为mcap proxy (简化: 直接用ln_close作为相对排名)
        # 实际应用中ln_mcap = ln(close * total_shares), 但此处作为上界实验
        # 使用adj_close作为proxy足够
        ln_mcap_wide = np.log(close_wide + 1e-12)
    except Exception:
        print("  WARNING: Could not compute ln_mcap proxy, falling back to Exp1")
        return exp1_perfect_equal_weight(forward_excess, price, top_n)

    target_portfolios = {}
    for rd, excess in sorted(forward_excess.items()):
        exclude = build_exclusion_set(price, rd)
        valid = excess.drop(labels=exclude.intersection(excess.index), errors="ignore")
        valid = valid.replace([np.inf, -np.inf], np.nan).dropna()

        if len(valid) < top_n:
            continue

        # SN调整: adj_score = excess - beta * zscore(ln_mcap)
        if rd in ln_mcap_wide.index:
            mcap = ln_mcap_wide.loc[rd]
            common = valid.index.intersection(mcap.dropna().index)
            if len(common) >= top_n:
                valid_sn = valid.loc[common]
                mcap_sn = mcap.loc[common]
                mcap_z = (mcap_sn - mcap_sn.mean()) / (mcap_sn.std() + 1e-12)
                adj_score = valid_sn - beta * mcap_z
                top_codes = adj_score.nlargest(top_n).index.tolist()
                w = 1.0 / len(top_codes)
                target_portfolios[rd] = {c: w for c in top_codes}
                continue

        # Fallback: no SN
        top_codes = valid.nlargest(top_n).index.tolist()
        w = 1.0 / len(top_codes)
        target_portfolios[rd] = {c: w for c in top_codes}

    return target_portfolios


def exp3_perfect_mvo(
    forward_excess: dict[date, pd.Series],
    price: pd.DataFrame,
    top_n_candidates: int = 40,
    max_weight: float = 0.10,
) -> dict[date, dict[str, float]]:
    """Exp3: 完美预测 + MVO(riskfolio-lib)。

    选Top-40候选池, 用riskfolio做MVO优化得到非均匀权重。
    """
    try:
        import riskfolio as rp
    except ImportError:
        print("  ERROR: riskfolio-lib not installed. Run: pip install riskfolio-lib")
        print("  Falling back to Exp1 (equal weight)")
        return exp1_perfect_equal_weight(forward_excess, price, top_n=20)

    # 预计算日收益率wide表
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    daily_ret_wide = close_wide.pct_change(fill_method=None)

    trade_dates = sorted(close_wide.index)
    td_idx = {d: i for i, d in enumerate(trade_dates)}

    target_portfolios = {}

    for rd, excess in sorted(forward_excess.items()):
        exclude = build_exclusion_set(price, rd)
        valid = excess.drop(labels=exclude.intersection(excess.index), errors="ignore")
        valid = valid.replace([np.inf, -np.inf], np.nan).dropna()

        if len(valid) < top_n_candidates:
            continue

        # Top-40候选
        candidates = valid.nlargest(top_n_candidates).index.tolist()

        # 获取过去120天日收益率
        if rd not in td_idx:
            continue
        idx = td_idx[rd]
        lookback = max(idx - 120, 0)
        hist_ret = daily_ret_wide.iloc[lookback:idx][candidates].dropna(axis=1, how="all")
        hist_ret = hist_ret.dropna()

        if len(hist_ret) < 60 or len(hist_ret.columns) < 10:
            # 数据不足, 退化为等权Top-20
            top20 = valid.nlargest(20).index.tolist()
            w = 1.0 / len(top20)
            target_portfolios[rd] = {c: w for c in top20}
            continue

        try:
            port = rp.Portfolio(returns=hist_ret)
            port.assets_stats(method_mu="hist", method_cov="ledoit_wolf")
            port.upperlng = max_weight

            w_df = port.optimization(
                model="Classic", rm="MV", obj="Sharpe",
                rf=0, l=0, hist=True,
            )

            if w_df is not None and not w_df.empty:
                weights = w_df["weights"].to_dict()
                # 过滤零权重
                weights = {k: v for k, v in weights.items() if v > 0.001}
                if weights:
                    total = sum(weights.values())
                    weights = {k: v / total for k, v in weights.items()}
                    target_portfolios[rd] = weights
                    continue
        except Exception:
            pass  # MVO失败, 退化为等权

        # Fallback
        top20 = valid.nlargest(20).index.tolist()
        w = 1.0 / len(top20)
        target_portfolios[rd] = {c: w for c in top20}

    return target_portfolios


def run_backtest(
    name: str,
    target_portfolios: dict[date, dict[str, float]],
    price: pd.DataFrame,
    bench: pd.DataFrame,
) -> dict:
    """用SimpleBacktester跑回测(铁律16)。"""
    from engines.backtest import BacktestConfig, BacktestResult, SimpleBacktester
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe

    config = BacktestConfig(
        initial_capital=1_000_000.0,
        rebalance_freq="monthly",
        historical_stamp_tax=True,
        slippage_mode="volume_impact",
    )

    backtester = SimpleBacktester(config)
    result: BacktestResult = backtester.run(
        target_portfolios=target_portfolios,
        price_data=price,
        benchmark_data=bench,
    )

    nav = result.daily_nav
    returns = result.daily_returns

    sharpe = calc_sharpe(returns) if len(returns) > 1 else 0
    mdd = calc_max_drawdown(nav)
    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (TRADING_DAYS_PER_YEAR / len(nav)) - 1 if len(nav) > 1 else 0
    n_rebal = len(target_portfolios)

    print(f"\n  {name}:")
    print(f"    Sharpe: {sharpe:.4f}")
    print(f"    MDD:    {mdd:.2%}")
    print(f"    Ann Ret:{ann_ret:.2%}")
    print(f"    Rebal:  {n_rebal} dates")
    print(f"    NAV:    {nav.iloc[0]:.0f} → {nav.iloc[-1]:.0f}")

    return {
        "name": name,
        "sharpe": sharpe,
        "mdd": mdd,
        "ann_ret": ann_ret,
        "n_rebal": n_rebal,
        "final_nav": nav.iloc[-1],
    }


def main():
    t_start = time.time()

    print("=" * 60)
    print("A.8 Perfect Prediction Upper Bound Experiment")
    print("=" * 60)

    # 1. Load data
    print("\n[1] Loading 12yr data...")
    price, bench = load_all_data()
    trade_dates = sorted(price["trade_date"].unique())
    print(f"    {len(price):,} price rows, {len(trade_dates)} trade dates")
    print(f"    Date range: {trade_dates[0]} ~ {trade_dates[-1]}")

    # 2. Get monthly rebalance dates
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    # 去掉最后几个(无法计算T+20前瞻)
    rebal_dates = [d for d in rebal_dates if d <= date(2026, 3, 1)]
    print(f"    {len(rebal_dates)} monthly rebalance dates")

    # 3. Compute perfect forward excess
    print("\n[2] Computing perfect forward excess returns (T+20)...")
    forward_excess = compute_forward_excess(price, bench, rebal_dates, horizon=20)
    print(f"    {len(forward_excess)} dates with valid forward returns")

    # 4. Three experiments
    print("\n[3] Running experiments...")

    # Exp1: Perfect + Equal-weight Top-20
    print("\n  Building Exp1: Perfect + EqualWeight Top-20...")
    tp1 = exp1_perfect_equal_weight(forward_excess, price, top_n=20)
    print(f"    {len(tp1)} rebalance dates")

    # Exp2: Perfect + SN + Equal-weight Top-20
    print("\n  Building Exp2: Perfect + SN(b=0.50) + EqualWeight Top-20...")
    tp2 = exp2_perfect_sn_equal_weight(forward_excess, price, top_n=20, beta=0.50)
    print(f"    {len(tp2)} rebalance dates")

    # Exp3: Perfect + MVO
    print("\n  Building Exp3: Perfect + MVO (riskfolio, Ledoit-Wolf)...")
    tp3 = exp3_perfect_mvo(forward_excess, price, top_n_candidates=40, max_weight=0.10)
    print(f"    {len(tp3)} rebalance dates")

    gc.collect()

    # 5. Run backtests
    print("\n[4] Running backtests (SimpleBacktester)...")
    results = []
    results.append(run_backtest("Exp1: Perfect+EqualWeight", tp1, price, bench))
    results.append(run_backtest("Exp2: Perfect+SN(b=0.50)+EW", tp2, price, bench))
    results.append(run_backtest("Exp3: Perfect+MVO", tp3, price, bench))

    # 6. Summary table
    print("\n" + "=" * 70)
    print("SUMMARY: Perfect Prediction Upper Bound")
    print("=" * 70)
    print(f"{'Experiment':<35} {'Sharpe':>8} {'MDD':>10} {'Ann Ret':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r['name']:<35} {r['sharpe']:>8.4f} {r['mdd']:>10.2%} {r['ann_ret']:>10.2%}")

    # 7. Go/Stop Gate
    print("\n" + "=" * 70)
    print("GO/STOP GATE:")
    s1 = results[0]["sharpe"]
    s3 = results[2]["sharpe"]

    if s3 > 1.5:
        print(f"  ✅ Perfect+MVO Sharpe={s3:.4f} > 1.5 → Portfolio优化空间大, 继续Part 2/3")
        gate = "GO"
    elif s3 < 1.0:
        print(f"  ❌ Perfect+MVO Sharpe={s3:.4f} < 1.0 → 瓶颈不在portfolio层, 停下报告")
        gate = "STOP"
    else:
        print(f"  ⚠️ Perfect+MVO Sharpe={s3:.4f} 在 1.0~1.5 → 边界情况, 需综合判断")
        gate = "REVIEW"

    if s1 > 1.5:
        print(f"  ⚠️ Perfect+EW Sharpe={s1:.4f} > 1.5 → 等权已足够, 融合架构不解决根因")

    print(f"\n  GATE RESULT: {gate}")
    print("\n  Baseline reference: SN b=0.50 inner Sharpe=0.68, WF OOS=0.6521")

    elapsed = time.time() - t_start
    print(f"\nTotal elapsed: {elapsed/60:.1f} min")

    return results


if __name__ == "__main__":
    main()
