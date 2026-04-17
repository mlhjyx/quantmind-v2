#!/usr/bin/env python3
r"""Phase 1.1 Step 1: Profile 12年回测, 识别841s瓶颈。

用法:
    cd D:\quantmind-v2
    python scripts/research/profile_backtest.py
"""

import cProfile
import io
import os
import pstats
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import logging

# 抑制debug日志（滑点计算9000+行），只保留WARNING以上
# structlog用stdlib作后端，设root logger即可
logging.basicConfig(level=logging.WARNING)


from data.parquet_cache import BacktestDataCache
from engines.backtest.runner import run_hybrid_backtest
from engines.metrics import generate_report

from app.services.config_loader import (
    get_data_range,
    get_directions,
    load_config,
    to_backtest_config,
    to_signal_config,
)


def main():
    config_path = "configs/backtest_12yr.yaml"
    cfg = load_config(config_path)
    bt_config = to_backtest_config(cfg)
    sig_config = to_signal_config(cfg)
    directions = get_directions(cfg)
    start_str, end_str = get_data_range(cfg)
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()

    # --- 加载数据 (不计入profile) ---
    cache = BacktestDataCache()
    t0 = time.time()
    data = cache.load(start, end)
    factor_df = data["factor_data"]
    price_data = data["price_data"]
    benchmark = data["benchmark"]
    load_time = time.time() - t0
    print(
        f"数据加载: factor={len(factor_df)}行, price={len(price_data)}行, "
        f"benchmark={len(benchmark)}行 ({load_time:.1f}s)"
    )

    # --- Profile回测主体 ---
    print("\n=== 开始Profile (run_hybrid_backtest + generate_report) ===")
    profiler = cProfile.Profile()

    t1 = time.time()
    profiler.enable()
    result = run_hybrid_backtest(
        factor_df,
        directions,
        price_data,
        bt_config,
        benchmark,
        signal_config=sig_config,
    )
    t_bt = time.time() - t1

    t2 = time.time()
    report = generate_report(result, price_data)
    t_report = time.time() - t2
    profiler.disable()

    total = time.time() - t1
    print("\n=== 耗时分解 ===")
    print(f"run_hybrid_backtest: {t_bt:.1f}s")
    print(f"generate_report:     {t_report:.1f}s")
    print(f"总计:                {total:.1f}s")
    print(f"Sharpe: {report.get('sharpe', 'N/A')}")

    # --- 输出Top-30耗时函数 ---
    print("\n=== Top-30 cumulative time ===")
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(30)
    print(stream.getvalue())

    # --- 输出Top-30 tottime (自身时间, 不含子调用) ---
    print("\n=== Top-30 tottime (self time) ===")
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2)
    stats2.sort_stats("tottime")
    stats2.print_stats(30)
    print(stream2.getvalue())

    # --- 保存完整profile ---
    prof_path = "cache/backtest_profile.prof"
    profiler.dump_stats(prof_path)
    print(f"\n完整profile已保存到 {prof_path}")
    print("可用 snakeviz cache/backtest_profile.prof 可视化")


if __name__ == "__main__":
    main()
