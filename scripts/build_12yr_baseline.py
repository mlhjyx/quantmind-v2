#!/usr/bin/env python3
"""构建 12 年 in-sample 基线 (2014-2025).

Step 6-D Fix 6: 提供 WF OOS 对照的全样本基线。
Phase B M2 (2026-04-15): 扩展保存 regression_test 需要的聚合 parquets, 支持 F75.
MVP 2.3 Sub2 (2026-04-19): 迁 Platform SDK (原直调 run_hybrid_backtest).

输出文件 (cache/baseline/):
  - nav_12yr.parquet           — 全样本 NAV 时序 (回测结果)
  - metrics_12yr.json          — 汇总指标 (与 5yr 基线同格式)
  - factor_data_12yr.parquet   — [M2 新增] 聚合因子 DataFrame (regression_test --years 12 用)
  - price_data_12yr.parquet    — [M2 新增] 聚合价格 DataFrame
  - benchmark_12yr.parquet     — [M2 新增] 聚合基准 DataFrame

用法:
    python scripts/build_12yr_baseline.py

说明:
  这是 "一次性 bootstrap" 脚本. 生成的 factor_data_12yr / price_data_12yr 成为
  regression_test 的**冻结输入**, 之后不应被覆盖 (除非有意识重建基线 + git commit 提升版本).
  生成时会 REWRITE nav_12yr.parquet + metrics_12yr.json (确保与输入一致).

迁移说明 (MVP 2.3 Sub2):
  - 走 `PlatformBacktestRunner` + `InMemoryBacktestRegistry` + `LIVE_PT` mode
    (借 ad-hoc 语义: 不 override start/end + 不 cache)
  - `engine_config_builder` 注入完整 Engine BacktestConfig (SlippageConfig/PMS/historical 税)
  - `data_loader` closure 提供已加载的 factor/price/bench (保留 parquet cache 逻辑)
  - 从 `result.engine_artifacts["engine_result"]` 取 daily_nav/trades (铁律 15 锚点不漂)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

logging.disable(logging.DEBUG)

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import pandas as pd  # noqa: E402
from engines.backtest.config import BacktestConfig as EngineBacktestConfig  # noqa: E402
from engines.backtest.config import PMSConfig  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino  # noqa: E402
from engines.slippage_model import SlippageConfig  # noqa: E402

from backend.platform._types import BacktestMode  # noqa: E402
from backend.platform.backtest import BacktestConfig as PlatformBacktestConfig  # noqa: E402
from backend.platform.backtest import InMemoryBacktestRegistry  # noqa: E402
from backend.platform.backtest.runner import PlatformBacktestRunner  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "backtest"

DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}


def load_12yr_parquet_cache():
    """从 cache/backtest/2014..2026 拼接 12 年数据。"""
    print("[Load] 加载 12 年 Parquet 缓存...")
    t0 = time.time()
    fd, pd_, bm = [], [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    print(f"  年份: {years}")

    for year in years:
        yr_dir = CACHE_DIR / str(year)
        pd_.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        fd.append(pd.read_parquet(yr_dir / "factor_data.parquet"))
        bm.append(pd.read_parquet(yr_dir / "benchmark.parquet"))

    price_df = pd.concat(pd_, ignore_index=True).sort_values(["code", "trade_date"])
    factor_df = pd.concat(fd, ignore_index=True)
    bench_df = pd.concat(bm, ignore_index=True).sort_values("trade_date").drop_duplicates("trade_date")

    print(f"  price_df: {price_df.shape} ({price_df['trade_date'].min()}..{price_df['trade_date'].max()})")
    print(f"  factor_df: {factor_df.shape}")
    print(f"  bench_df: {bench_df.shape}")
    print(f"  加载耗时: {time.time() - t0:.1f}s")
    return factor_df, price_df, bench_df


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    factor_df, price_df, bench_df = load_12yr_parquet_cache()

    # Engine BacktestConfig — 与迁前完全对齐 (铁律 15 锚点)
    engine_cfg = EngineBacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    # Platform BacktestConfig — 构 config_hash 稳定 (sorted factor_pool + datetime.date)
    trading_days = sorted(price_df["trade_date"].unique())
    start_date = pd.Timestamp(trading_days[0]).date()
    end_date = pd.Timestamp(trading_days[-1]).date()
    factor_pool = tuple(sorted(DIRECTIONS.keys()))

    platform_cfg = PlatformBacktestConfig(
        start=start_date,
        end=end_date,
        universe="all_a",
        factor_pool=factor_pool,
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.0,
        cost_model="full",  # historical_stamp_tax=True
        capital="1000000",
        benchmark="csi300",
        extra={},
    )

    runner = PlatformBacktestRunner(
        registry=InMemoryBacktestRegistry(),
        data_loader=lambda _c, _s, _e: (factor_df, price_df, bench_df),
        conn=None,  # size_neutral_beta=0, 无需 DB ln_mcap
        direction_provider=lambda pool: {n: DIRECTIONS[n] for n in pool},
        engine_config_builder=lambda _p: engine_cfg,
        signal_config_builder=lambda c: SimpleNamespace(size_neutral_beta=c.size_neutral_beta),
    )

    print("\n[Backtest] 跑 12 年全样本 in-sample...")
    t0 = time.time()
    # LIVE_PT: 不 override start/end + 不 cache (InMem get_by_hash 恒 None 双重真跑)
    platform_result = runner.run(mode=BacktestMode.LIVE_PT, config=platform_cfg)
    if platform_result.engine_artifacts is None:
        raise RuntimeError(
            "engine_artifacts=None — LIVE_PT 应强制真跑, 产出 {engine_result, price_data}"
        )
    result = platform_result.engine_artifacts["engine_result"]
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.0f}s")

    # Metrics
    nav = result.daily_nav
    returns = nav.pct_change().dropna()

    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))

    n_days = len(nav)
    years = n_days / 244.0
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)

    metrics = {
        "sharpe": round(sharpe, 4),
        "mdd_pct": round(mdd * 100, 2),
        "annual_return_pct": round(annual_return * 100, 2),
        "sortino": round(sortino, 4),
        "total_return_pct": round(total_return * 100, 2),
        "total_trades": len(result.trades) if hasattr(result, "trades") else 0,
        "nav_start": float(nav.iloc[0]),
        "nav_end": float(nav.iloc[-1]),
        "trading_days": n_days,
        "years_covered": round(years, 2),
        "date_range": [str(nav.index[0]), str(nav.index[-1])],
        "elapsed_sec": round(elapsed, 0),
        "config": {
            "factors": list(DIRECTIONS.keys()),
            "top_n": 20,
            "rebalance_freq": "monthly",
            "initial_capital": 1_000_000,
            "slippage_mode": "volume_impact",
            "stamp_tax": "historical",
            "pms_enabled": True,
        },
    }

    # Save NAV
    nav_path = BASELINE_DIR / "nav_12yr.parquet"
    nav.to_frame("nav").to_parquet(nav_path)
    print(f"\n[Save] NAV → {nav_path}")

    # Save metrics
    metrics_path = BASELINE_DIR / "metrics_12yr.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"[Save] Metrics → {metrics_path}")

    # [Phase B M2] Save aggregated inputs for regression_test --years 12
    # 这些 parquets 是 regression_test 的冻结输入, 保证铁律 15 (回测可复现)
    factor_data_path = BASELINE_DIR / "factor_data_12yr.parquet"
    price_data_path = BASELINE_DIR / "price_data_12yr.parquet"
    benchmark_path = BASELINE_DIR / "benchmark_12yr.parquet"

    factor_df.to_parquet(factor_data_path)
    price_df.to_parquet(price_data_path)
    bench_df.to_parquet(benchmark_path)

    print(f"[Save] factor_data_12yr → {factor_data_path} ({factor_df.shape})")
    print(f"[Save] price_data_12yr  → {price_data_path} ({price_df.shape})")
    print(f"[Save] benchmark_12yr   → {benchmark_path} ({bench_df.shape})")

    print("\n=== 12yr In-Sample Baseline ===")
    print(f"  Sharpe:        {metrics['sharpe']}")
    print(f"  MDD:           {metrics['mdd_pct']}%")
    print(f"  Annual Return: {metrics['annual_return_pct']}%")
    print(f"  Sortino:       {metrics['sortino']}")
    print(f"  Total Return:  {metrics['total_return_pct']}%")
    print(f"  Trading Days:  {metrics['trading_days']} ({metrics['years_covered']} 年)")
    print(f"  NAV Final:     {metrics['nav_end']:,.0f}")


if __name__ == "__main__":
    main()
