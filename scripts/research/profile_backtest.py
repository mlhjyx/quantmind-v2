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
from engines.metrics import generate_report

from app.services.config_loader import (
    get_data_range,
    get_directions,
    load_config,
    to_backtest_config,
    to_signal_config,
)
from backend.platform._types import BacktestMode
from backend.platform.backtest import BacktestConfig as PlatformCfg
from backend.platform.backtest import InMemoryBacktestRegistry
from backend.platform.backtest.runner import PlatformBacktestRunner


def main():
    """Profile 12 年回测识别瓶颈 (MVP 2.3 Sub1 PR C4 迁 Platform SDK).

    走 `PlatformBacktestRunner.run(mode=LIVE_PT)` + cProfile 包. 原直调
    `run_hybrid_backtest + generate_report` 改为 Runner 调度 + 从
    `result.engine_artifacts` 取 engine_result/price_data 走 generate_report.

    **Profile 粒度**: cProfile 捕获 Runner.run() 整个调用栈 (包含
    _build_engine_config / data_loader / run_hybrid_backtest / perf 聚合 /
    _build_lineage / registry.log_run) + generate_report. Runner 调度 overhead
    应 < 1% (每次 run 固定 ~10 行 Python), 基本不污染瓶颈分析.
    """
    config_path = "configs/backtest_12yr.yaml"
    cfg = load_config(config_path)
    bt_config_engine = to_backtest_config(cfg)
    sig_config = to_signal_config(cfg)
    directions = get_directions(cfg)
    start_str, end_str = get_data_range(cfg)
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()

    # --- 加载数据 (不计入profile, 与迁前对齐) ---
    cache = BacktestDataCache()
    t0 = time.time()
    data = cache.load(start, end)
    factor_df = data["factor_data"]
    price_data = data["price_data"]
    benchmark = data.get("benchmark")
    load_time = time.time() - t0
    print(
        f"数据加载: factor={len(factor_df)}行, price={len(price_data)}行, "
        f"benchmark={len(benchmark) if benchmark is not None else 0}行 ({load_time:.1f}s)"
    )

    # --- 构造 Platform SDK 组件 ---
    # closure data_loader 返已加载 parquets (与迁前 cache.load 同源)
    def _preloaded_loader(_platform_cfg, _start, _end):
        return factor_df, price_data, benchmark

    platform_cfg = PlatformCfg(
        start=start,
        end=end,
        universe="all_a",
        factor_pool=tuple(directions.keys()),
        rebalance_freq=cfg["strategy"].get("rebalance_freq", "monthly"),
        top_n=int(cfg["strategy"].get("top_n", 20)),
        industry_cap=float(cfg["strategy"].get("industry_cap", 1.0)),
        size_neutral_beta=float(cfg["strategy"].get("size_neutral_beta", 0.0)),
        cost_model="full",
        capital=str(cfg["backtest"].get("initial_capital", 1_000_000)),
        benchmark="csi300" if cfg["backtest"].get("benchmark") == "000300.SH" else "none",
        extra={},
    )
    runner = PlatformBacktestRunner(
        registry=InMemoryBacktestRegistry(),
        data_loader=_preloaded_loader,
        conn=None,  # profile 场景无 SN (12yr YAML SN=0) 或容忍 SN 分支 (engine 内 skip)
        direction_provider=lambda pool: {n: directions[n] for n in pool},
        engine_config_builder=lambda _p: bt_config_engine,
        signal_config_builder=lambda _p: sig_config,
    )

    # --- Profile 回测主体 ---
    print("\n=== 开始 Profile (PlatformBacktestRunner.run + generate_report) ===")
    profiler = cProfile.Profile()

    t1 = time.time()
    profiler.enable()
    # TODO(mvp-2.3-sub3): BacktestMode.AD_HOC 目前未实现, 借 LIVE_PT 语义 (不 override +
    # 不 cache) 匹配 profile 场景 (每次真跑). Sub3 评估新 AD_HOC mode 替代借用.
    result = runner.run(mode=BacktestMode.LIVE_PT, config=platform_cfg)
    t_bt = time.time() - t1

    # PR C2 契约: LIVE_PT always re-run → engine_artifacts 必塞
    if result.engine_artifacts is None:
        raise RuntimeError(
            "engine_artifacts=None — 违反 PR C2 契约 (LIVE_PT always re-run)"
        )
    engine_result = result.engine_artifacts["engine_result"]
    price_data_from_artifacts = result.engine_artifacts["price_data"]

    t2 = time.time()
    report = generate_report(engine_result, price_data_from_artifacts)
    t_report = time.time() - t2
    profiler.disable()

    total = time.time() - t1
    print("\n=== 耗时分解 ===")
    print(f"runner.run (含 run_hybrid_backtest): {t_bt:.1f}s")
    print(f"generate_report:                    {t_report:.1f}s")
    print(f"总计:                               {total:.1f}s")
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
