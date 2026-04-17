"""Step 6-H Part 3: Regime Flag + Partial Size-Neutral 组合实验。

用 CSI300 stoch_rsv_20 作 regime signal，动态调整 beta:
  - rsv > 0.8 (overbought): beta=0.75
  - rsv < 0.2 (oversold):   beta=0.25
  - 其余:                    beta=0.50

对比 static beta=0.50 (Step 6-G 验证最优)。

输出: cache/baseline/regime_flag_results.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.backtest.engine import SimpleBacktester  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino  # noqa: E402
from engines.signal_engine import (  # noqa: E402
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
)
from engines.signal_engine import SignalConfig as SEConfig  # noqa: E402
from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot  # noqa: E402
from engines.vectorized_signal import compute_rebalance_dates  # noqa: E402
from engines.walk_forward import build_exclusion_map  # noqa: E402

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}
CACHE_DIR = Path("cache/baseline")
OUTPUT = CACHE_DIR / "regime_flag_results.json"


def load_data():
    """从 Parquet 缓存加载。"""
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
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date").sort_values("trade_date")
    factor_df = pd.concat(factor_parts, ignore_index=True)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    return price_df, bench_df, factor_df


def compute_rsv_schedule(bench_df: pd.DataFrame, window: int = 20) -> pd.Series:
    """计算 CSI300 stoch_rsv → 动态 beta schedule。"""
    close = bench_df.set_index("trade_date")["close"].sort_index()
    high_roll = close.rolling(window).max()
    low_roll = close.rolling(window).min()
    rsv = (close - low_roll) / (high_roll - low_roll + 1e-12)

    beta = pd.Series(0.50, index=rsv.index, name="dynamic_beta")
    beta[rsv > 0.8] = 0.75
    beta[rsv < 0.2] = 0.25
    return beta


def run_variant(name, factor_df, price_df, bench_df, ln_mcap_pivot, beta_schedule=None, static_beta=0.50):
    """跑一个 variant 的 12 年回测。"""
    print(f"\n[{name}]")
    t0 = time.time()

    se_config = SEConfig(
        factor_names=list(CORE_DIRECTIONS.keys()),
        top_n=20, weight_method="equal", rebalance_freq="monthly",
        industry_cap=1.0, turnover_cap=1.0, cash_buffer=0.0,
    )
    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)

    exclusion_map = build_exclusion_map(price_df)
    saved = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(CORE_DIRECTIONS)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    trading_days = sorted(price_df["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, "monthly")

    target_portfolios = {}
    try:
        for rd in rebal_dates:
            day_data = factor_df[factor_df["trade_date"] <= rd]
            if day_data.empty:
                continue
            latest_date = day_data["trade_date"].max()
            day_data = day_data[day_data["trade_date"] == latest_date]
            exclude = exclusion_map.get(latest_date, set())
            scores = composer.compose(day_data, exclude=exclude)
            if scores.empty:
                continue

            # 动态 or 静态 beta
            if beta_schedule is not None and latest_date in beta_schedule.index:
                beta = float(beta_schedule.loc[latest_date])
            else:
                beta = static_beta

            if beta > 0 and latest_date in ln_mcap_pivot.index:
                scores = apply_size_neutral(scores, ln_mcap_pivot.loc[latest_date], beta)

            weights = builder.build(scores, pd.Series(dtype=str))
            if weights:
                target_portfolios[rd] = weights
    finally:
        FACTOR_DIRECTION.clear()
        FACTOR_DIRECTION.update(saved)

    tester = SimpleBacktester(bt_config)
    result = tester.run(target_portfolios, price_df, bench_df)

    nav = result.daily_nav
    returns = nav.pct_change().dropna()
    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    total = float(nav.iloc[-1] / nav.iloc[0] - 1)
    years = len(nav) / 244.0
    annual = float((1 + total) ** (1 / max(years, 0.01)) - 1)

    # Train/Test split
    r = returns.copy()
    r.index = pd.to_datetime(r.index)
    train_r = r[r.index < pd.Timestamp("2021-01-01")]
    test_r = r[r.index >= pd.Timestamp("2021-01-01")]

    def _m(ret):
        if len(ret) < 2:
            return {}
        n = (1 + ret).cumprod()
        return {"sharpe": round(float(calc_sharpe(ret)), 4), "mdd": round(float(calc_max_drawdown(n * 1e6)), 4)}

    metrics = {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "sortino": round(sortino, 4),
        "annual_return": round(annual, 4),
        "total_return": round(total, 4),
        "days": len(nav),
        "train_2014_2020": _m(train_r),
        "test_2021_2026": _m(test_r),
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(f"  Sharpe={sharpe:.4f}, MDD={mdd:.4f}, Annual={annual:.4f}")
    print(f"  Train: {metrics['train_2014_2020']}")
    print(f"  Test:  {metrics['test_2021_2026']}")
    return metrics


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    price_df, bench_df, factor_df = load_data()
    print(f"Data: price {price_df.shape}, bench {bench_df.shape}, factor {factor_df.shape}")

    trading_days = sorted(price_df["trade_date"].unique())
    ln_mcap_pivot = load_ln_mcap_pivot(min(trading_days), max(trading_days))
    print(f"ln_mcap pivot: {ln_mcap_pivot.shape}")

    # Dynamic beta schedule
    beta_schedule = compute_rsv_schedule(bench_df, window=20)
    n_high = (beta_schedule == 0.75).sum()
    n_low = (beta_schedule == 0.25).sum()
    n_mid = (beta_schedule == 0.50).sum()
    print(f"\nBeta schedule: {n_low} oversold(0.25), {n_mid} neutral(0.50), {n_high} overbought(0.75)")

    # Binary variant schedule
    beta_binary = pd.Series(0.50, index=beta_schedule.index)
    beta_binary[beta_schedule == 0.75] = 0.75

    results = {}

    # Variant 1: static b=0.50 (control)
    results["static_b050"] = run_variant(
        "Static b=0.50", factor_df, price_df, bench_df, ln_mcap_pivot, static_beta=0.50)

    # Variant 2: dynamic beta (0.25/0.50/0.75)
    results["dynamic_rsv"] = run_variant(
        "Dynamic RSV (0.25/0.50/0.75)", factor_df, price_df, bench_df, ln_mcap_pivot,
        beta_schedule=beta_schedule)

    # Variant 3: binary (0.50/0.75)
    results["binary_rsv"] = run_variant(
        "Binary RSV (0.50/0.75)", factor_df, price_df, bench_df, ln_mcap_pivot,
        beta_schedule=beta_binary)

    # Variant 4: base (no size-neutral)
    results["base_no_sn"] = run_variant(
        "Base (no SN)", factor_df, price_df, bench_df, ln_mcap_pivot, static_beta=0.0)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'Variant':<30} {'Sharpe':>8} {'MDD':>10} {'Annual':>10} {'OOS Sharpe':>12}")
    for name, m in results.items():
        oos = m.get("test_2021_2026", {}).get("sharpe", "N/A")
        print(f"{name:<30} {m['sharpe']:>8.4f} {m['mdd']:>10.4f} {m['annual_return']:>10.4f} {str(oos):>12}")

    output = {
        "regime_signal": "stoch_rsv_20 on CSI300",
        "beta_distribution": {"oversold_025": int(n_low), "neutral_050": int(n_mid), "overbought_075": int(n_high)},
        "results": results,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {OUTPUT}")


if __name__ == "__main__":
    main()
