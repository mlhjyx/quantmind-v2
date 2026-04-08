"""回测回归测试 — 验证引擎修改后结果不变。

用法:
    python scripts/regression_test.py           # 跑一次对比
    python scripts/regression_test.py --twice   # 跑两次验证确定性
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
logging.disable(logging.DEBUG)

import structlog  # noqa: E402

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.ERROR)

from engines.backtest_engine import BacktestConfig, PMSConfig, run_hybrid_backtest  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe  # noqa: E402
from engines.slippage_model import SlippageConfig  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"


def run_backtest():
    """从baseline Parquet加载数据，跑回测，返回daily_nav Series。"""
    factor_df = pd.read_parquet(BASELINE_DIR / "factor_data_5yr.parquet")
    price_data = pd.read_parquet(BASELINE_DIR / "price_data_5yr.parquet")

    directions = {
        "turnover_mean_20": -1,
        "volatility_20": -1,
        "reversal_20": 1,
        "amihud_20": 1,
        "bp_ratio": 1,
    }
    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    result = run_hybrid_backtest(factor_df, directions, price_data, config)
    return result.daily_nav


def compare_nav(baseline_nav: pd.Series, current_nav: pd.Series) -> dict:
    """逐日对比NAV，返回差异统计。"""
    # 对齐index
    common = baseline_nav.index.intersection(current_nav.index)
    if len(common) == 0:
        return {"error": "no common dates"}

    b = baseline_nav.loc[common].astype(float)
    c = current_nav.loc[common].astype(float)

    diff = (c - b).abs()
    pct_diff = diff / b.replace(0, np.nan) * 100  # 百分比差异

    return {
        "common_days": len(common),
        "baseline_days": len(baseline_nav),
        "current_days": len(current_nav),
        "max_diff": round(float(diff.max()), 4),
        "mean_diff": round(float(diff.mean()), 4),
        "max_pct_diff": round(float(pct_diff.max()), 6),
        "mean_pct_diff": round(float(pct_diff.mean()), 6),
        "days_above_0001pct": int((pct_diff > 0.001).sum()),
        "days_above_001pct": int((pct_diff > 0.01).sum()),
        "sharpe_baseline": round(float(calc_sharpe(b.pct_change().dropna())), 4),
        "sharpe_current": round(float(calc_sharpe(c.pct_change().dropna())), 4),
        "mdd_baseline": round(float(calc_max_drawdown(b) * 100), 2),
        "mdd_current": round(float(calc_max_drawdown(c) * 100), 2),
    }


def main():
    parser = argparse.ArgumentParser(description="回测回归测试")
    parser.add_argument("--twice", action="store_true", help="跑两次验证确定性")
    args = parser.parse_args()

    baseline_path = BASELINE_DIR / "nav_5yr.parquet"
    if not baseline_path.exists():
        print(f"ERROR: baseline NAV not found at {baseline_path}")
        sys.exit(1)

    baseline_nav = pd.read_parquet(baseline_path)["nav"]
    print(f"Baseline NAV: {len(baseline_nav)} days, {float(baseline_nav.iloc[0]):.2f} -> {float(baseline_nav.iloc[-1]):.2f}")

    # Run 1
    print("\n[Run 1] Running backtest...")
    t0 = time.time()
    nav1 = run_backtest()
    elapsed1 = time.time() - t0
    result1 = compare_nav(baseline_nav, nav1)
    print(f"  Elapsed: {elapsed1:.0f}s")
    print(f"  max_diff: {result1['max_diff']}")
    print(f"  max_pct_diff: {result1['max_pct_diff']}%")
    print(f"  days_above_0.001%: {result1['days_above_0001pct']}")
    print(f"  Sharpe: baseline={result1['sharpe_baseline']}, current={result1['sharpe_current']}")

    if args.twice:
        # Run 2
        print("\n[Run 2] Running backtest (determinism check)...")
        t0 = time.time()
        nav2 = run_backtest()
        elapsed2 = time.time() - t0
        result2 = compare_nav(nav1, nav2)
        print(f"  Elapsed: {elapsed2:.0f}s")
        print(f"  Run1 vs Run2 max_diff: {result2['max_diff']}")
        print(f"  Run1 vs Run2 max_pct_diff: {result2['max_pct_diff']}%")

        deterministic = result2["max_diff"] == 0
        print(f"\n  Deterministic: {'YES ✅' if deterministic else 'NO ❌'}")
        result1["deterministic"] = deterministic
        result1["run2_max_diff"] = result2["max_diff"]

    # Save results
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_file": str(baseline_path),
        "run1": result1,
        "elapsed_sec": round(elapsed1, 0),
    }
    output_path = BASELINE_DIR / "regression_result.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
