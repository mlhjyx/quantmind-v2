"""Step 6-H Part 1.9: Walk-Forward 验证 Partial Size-Neutral beta=0.50。

对比 Step 6-D base WF (Sharpe=0.6336, MDD=-45.7%, UNSTABLE):
  - 5-fold WF: WFConfig(n_splits=5, train=750, gap=5, test=250)
  - 逐年度分解: 12 年 (2014-2025)

输出: cache/baseline/wf_sn050_result.json
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.backtest.engine import SimpleBacktester  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe  # noqa: E402
from engines.size_neutral import load_ln_mcap_pivot  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    make_equal_weight_signal_func,
)

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}
CACHE_DIR = Path("cache/baseline")
OUTPUT = CACHE_DIR / "wf_sn050_result.json"


def load_data():
    """从 Parquet 缓存加载 12 年数据。"""
    cache_root = Path("cache/backtest")
    price_parts, bench_parts, factor_parts = [], [], []
    for year_dir in sorted(cache_root.iterdir()):
        if not year_dir.is_dir():
            continue
        pf = year_dir / "price_data.parquet"
        bf = year_dir / "benchmark.parquet"
        ff = year_dir / "factor_data.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))
        if ff.exists():
            fp = pd.read_parquet(ff)
            factor_parts.append(fp[fp["factor_name"].isin(CORE_DIRECTIONS)].copy())

    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")
    factor_df = pd.concat(factor_parts, ignore_index=True)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    return price_df, bench_df, factor_df


def run_wf_5fold(factor_df, price_df, bench_df, ln_mcap_pivot):
    """标准 5-fold WF。"""
    print("\n=== WF 5-fold (b=0.50) ===")
    t0 = time.time()

    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(
        top_n=20,
        rebalance_freq="monthly",
        initial_capital=1_000_000,
    )

    signal_func = make_equal_weight_signal_func(
        factor_df, CORE_DIRECTIONS, price_df,
        top_n=20, rebalance_freq="monthly",
        size_neutral_beta=0.50,
        ln_mcap_pivot=ln_mcap_pivot,
    )

    all_dates = sorted(price_df["trade_date"].unique())
    engine = WalkForwardEngine(wf_config, bt_config)
    result = engine.run(signal_func, price_df, bench_df, all_dates)

    fold_data = []
    for fr in result.fold_results:
        fold_data.append({
            "fold": fr.fold_idx,
            "test_start": str(fr.test_period[0]),
            "test_end": str(fr.test_period[1]),
            "oos_sharpe": round(fr.oos_sharpe, 4),
            "oos_mdd": round(fr.oos_mdd, 4),
            "oos_annual_return": round(fr.oos_annual_return, 4),
        })

    combined = {
        "combined_sharpe": round(result.combined_oos_sharpe, 4),
        "combined_mdd": round(result.combined_oos_mdd, 4),
        "combined_annual_return": round(result.combined_oos_annual_return, 4),
        "total_oos_days": result.total_oos_days,
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(f"  Combined Sharpe: {combined['combined_sharpe']}")
    print(f"  Combined MDD:    {combined['combined_mdd']}")
    print(f"  Elapsed: {combined['elapsed_s']}s")
    return {"folds": fold_data, "combined": combined}


def run_annual_breakdown(factor_df, price_df, bench_df, ln_mcap_pivot):
    """逐年度回测。"""
    print("\n=== Annual Breakdown (b=0.50) ===")
    from engines.signal_engine import FACTOR_DIRECTION, PortfolioBuilder, SignalComposer
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.size_neutral import apply_size_neutral
    from engines.vectorized_signal import compute_rebalance_dates
    from engines.walk_forward import build_exclusion_map

    se_config = SEConfig(
        factor_names=list(CORE_DIRECTIONS.keys()),
        top_n=20, weight_method="equal", rebalance_freq="monthly",
        industry_cap=1.0, turnover_cap=1.0, cash_buffer=0.0,
    )
    bt_config = BacktestConfig(
        top_n=20, rebalance_freq="monthly", initial_capital=1_000_000,
    )

    exclusion_map = build_exclusion_map(price_df)

    saved = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(CORE_DIRECTIONS)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    all_trading_days = sorted(price_df["trade_date"].unique())
    all_rebal = compute_rebalance_dates(all_trading_days, "monthly")

    target_portfolios = {}
    for rd in all_rebal:
        day_data = factor_df[factor_df["trade_date"] <= rd]
        if day_data.empty:
            continue
        latest_date = day_data["trade_date"].max()
        day_data = day_data[day_data["trade_date"] == latest_date]
        exclude = exclusion_map.get(latest_date, set())
        scores = composer.compose(day_data, exclude=exclude)
        if scores.empty:
            continue
        if latest_date in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[latest_date], 0.50)
        weights = builder.build(scores, pd.Series(dtype=str))
        if weights:
            target_portfolios[rd] = weights

    FACTOR_DIRECTION.clear()
    FACTOR_DIRECTION.update(saved)

    tester = SimpleBacktester(bt_config)
    result = tester.run(target_portfolios, price_df, bench_df)

    # 逐年分解
    nav = result.daily_nav
    annual = {}
    for year in range(2014, 2026):
        y_start = date(year, 1, 1)
        y_end = date(year, 12, 31)
        mask = (nav.index >= y_start) & (nav.index <= y_end)
        y_nav = nav[mask]
        if len(y_nav) < 20:
            continue
        y_returns = y_nav.pct_change().dropna()
        sharpe = float(calc_sharpe(y_returns))
        mdd = float(calc_max_drawdown(y_nav))
        annual_ret = float((y_nav.iloc[-1] / y_nav.iloc[0]) - 1)
        annual[str(year)] = {
            "sharpe": round(sharpe, 4),
            "mdd": round(mdd, 4),
            "annual_return": round(annual_ret, 4),
            "days": len(y_nav),
        }
        print(f"  {year}: Sharpe={sharpe:.3f}, MDD={mdd:.3f}, Return={annual_ret:.3f}")

    return annual


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    price_df, bench_df, factor_df = load_data()
    print(f"Data: price {price_df.shape}, bench {bench_df.shape}, factor {factor_df.shape}")

    # 加载 ln_mcap
    print("[Load] ln_mcap from DB...")
    t0 = time.time()
    trading_days = sorted(price_df["trade_date"].unique())
    ln_mcap_pivot = load_ln_mcap_pivot(min(trading_days), max(trading_days))
    print(f"  ln_mcap pivot {ln_mcap_pivot.shape}, {time.time()-t0:.1f}s")

    # 5-fold WF
    wf_result = run_wf_5fold(factor_df, price_df, bench_df, ln_mcap_pivot)

    # 逐年度
    annual = run_annual_breakdown(factor_df, price_df, bench_df, ln_mcap_pivot)

    # Step 6-D base 对比
    base_wf_path = CACHE_DIR / "wf_oos_result.json"
    comparison = {}
    if base_wf_path.exists():
        base = json.loads(base_wf_path.read_text())
        comparison = {
            "base_combined_sharpe": base.get("combined_oos_sharpe", base.get("combined_sharpe")),
            "base_combined_mdd": base.get("combined_oos_mdd", base.get("combined_mdd")),
            "sn050_combined_sharpe": wf_result["combined"]["combined_sharpe"],
            "sn050_combined_mdd": wf_result["combined"]["combined_mdd"],
            "sharpe_improvement": round(
                wf_result["combined"]["combined_sharpe"]
                - (base.get("combined_oos_sharpe", base.get("combined_sharpe", 0))),
                4,
            ),
        }
        print("\n=== Comparison vs Base WF ===")
        for k, v in comparison.items():
            print(f"  {k}: {v}")

    output = {
        "config": {"size_neutral_beta": 0.50, "top_n": 20, "rebalance_freq": "monthly"},
        "wf_5fold": wf_result,
        "annual_breakdown": annual,
        "comparison_vs_base": comparison,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {OUTPUT}")


if __name__ == "__main__":
    main()
