#!/usr/bin/env python3
"""Phase 1.1: 验证runner.py优化后结果一致性。

比较优化后的3yr/12yr回测结果与基线。
输出写入cache/optimization_validation.txt。
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import logging

# 完全抑制所有structlog输出(它们走stdout)
logging.basicConfig(level=logging.CRITICAL)
# 猴子补丁structlog: 所有logger的msg方法变为no-op
import structlog

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL),
    cache_logger_on_first_use=False,
)

from data.parquet_cache import BacktestDataCache
from engines.backtest.runner import run_hybrid_backtest
from engines.metrics import generate_report

from app.services.config_loader import (
    get_directions,
    load_config,
    to_backtest_config,
    to_signal_config,
)

OUTPUT_FILE = "cache/optimization_validation.txt"


def run_validation(start_date, end_date, label):
    """跑一次回测并返回metrics。"""
    cfg = load_config("configs/backtest_12yr.yaml")
    bt_config = to_backtest_config(cfg)
    sig_config = to_signal_config(cfg)
    directions = get_directions(cfg)

    cache = BacktestDataCache()
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    data = cache.load(start, end)

    t0 = time.time()
    result = run_hybrid_backtest(
        data["factor_data"],
        directions,
        data["price_data"],
        bt_config,
        data["benchmark"],
        signal_config=sig_config,
    )
    elapsed = time.time() - t0

    report = generate_report(result, data["price_data"])
    return {
        "label": label,
        "elapsed": elapsed,
        "sharpe": report.sharpe_ratio,
        "annual_return": report.annual_return,
        "max_drawdown": report.max_drawdown,
        "total_return": report.total_return,
        "nav_final": float(result.daily_nav.iloc[-1]),
        "nav_count": len(result.daily_nav),
        "trades": len(result.trades),
    }


def main():
    lines = []
    lines.append("=" * 60)
    lines.append("Phase 1.1 Optimization Validation")
    lines.append(f"Time: {datetime.now().isoformat()}")
    lines.append("=" * 60)

    # 3yr验证
    r3 = run_validation("2022-01-01", "2024-12-31", "3yr")
    lines.append(f"\n--- {r3['label']} ---")
    lines.append(f"Time:     {r3['elapsed']:.1f}s")
    lines.append(f"Sharpe:   {r3['sharpe']:.4f}")
    lines.append(f"Annual:   {r3['annual_return']:.4f}")
    lines.append(f"MDD:      {r3['max_drawdown']:.4f}")
    lines.append(f"Total:    {r3['total_return']:.4f}")
    lines.append(f"NAV:      {r3['nav_final']:.2f}")
    lines.append(f"Days:     {r3['nav_count']}")
    lines.append(f"Trades:   {r3['trades']}")

    # 5yr基线比对
    r5 = run_validation("2021-01-01", "2025-12-31", "5yr")
    lines.append(f"\n--- {r5['label']} ---")
    lines.append(f"Time:     {r5['elapsed']:.1f}s")
    lines.append(f"Sharpe:   {r5['sharpe']:.4f}")
    lines.append(f"Annual:   {r5['annual_return']:.4f}")
    lines.append(f"MDD:      {r5['max_drawdown']:.4f}")
    lines.append(f"Total:    {r5['total_return']:.4f}")
    lines.append(f"NAV:      {r5['nav_final']:.2f}")
    lines.append(f"Days:     {r5['nav_count']}")
    lines.append(f"Trades:   {r5['trades']}")

    # 5yr基线: Sharpe=0.6095 (regression_test.py)
    lines.append("\n--- 5yr Baseline (regression_test.py) ---")
    lines.append("Sharpe:   0.6095")
    sharpe_diff = abs(r5["sharpe"] - 0.6095)
    lines.append(f"Diff:     {sharpe_diff:.6f}")
    lines.append(f"PASS:     {'✅' if sharpe_diff < 0.001 else '❌'} (threshold: <0.001)")

    output = "\n".join(lines)
    print(output)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(output + "\n")
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
