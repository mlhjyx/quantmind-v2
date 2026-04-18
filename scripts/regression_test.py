"""回测回归测试 — 验证引擎修改后结果不变 (铁律 15 可复现)。

用法:
    python scripts/regression_test.py                    # 默认 5yr 对比
    python scripts/regression_test.py --years 5          # 显式 5yr
    python scripts/regression_test.py --years 12         # 12yr 全样本 (需先跑 build_12yr_baseline)
    python scripts/regression_test.py --years 12 --twice # 12yr 跑两次验证确定性

基线文件 (cache/baseline/):
    5yr:  factor_data_5yr.parquet  + price_data_5yr.parquet  + nav_5yr.parquet
    12yr: factor_data_12yr.parquet + price_data_12yr.parquet + benchmark_12yr.parquet + nav_12yr.parquet

如果 12yr 文件不存在, 运行 `python scripts/build_12yr_baseline.py` 一次性生成 (Phase B M2 铁律 15 扩展)。
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))
logging.disable(logging.DEBUG)

import structlog  # noqa: E402

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.ERROR)

from datetime import date  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from engines.backtest.config import BacktestConfig as EngineBacktestConfig  # noqa: E402
from engines.backtest.config import PMSConfig  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe  # noqa: E402
from engines.slippage_model import SlippageConfig  # noqa: E402

from backend.platform._types import BacktestMode  # noqa: E402
from backend.platform.backtest import BacktestConfig as PlatformCfg  # noqa: E402
from backend.platform.backtest import InMemoryBacktestRegistry  # noqa: E402
from backend.platform.backtest.runner import PlatformBacktestRunner  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"

# CORE5 factors (与 nav_5yr.parquet / nav_12yr.parquet 基线生成时一致)
CORE5_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}


def run_backtest(years: int = 5):
    """从 baseline Parquet 加载数据, 跑回测, 返回 daily_nav Series.

    MVP 2.3 Sub1 PR C4 迁 Platform SDK (原直调 run_hybrid_backtest):
      - `PlatformBacktestRunner` + `InMemoryBacktestRegistry` (恒 cache miss 强制真跑)
      - `BacktestMode.LIVE_PT` 借 ad-hoc 语义 (不 override start/end + 不 cache)
      - `direction_provider=lambda pool: CORE5_DIRECTIONS` 固定 direction (CI 锚点)
      - `engine_config_builder` 注入完整 Engine BacktestConfig (SlippageConfig/PMS/historical 税)
      - `signal_config_builder` 注入 SN=0 (CORE5 基线无 SN modifier)
      - closure data_loader 从 `cache/baseline/*.parquet` 加载 (CI 冻结锚点, 不走 DB)
      - 从 `result.engine_artifacts["engine_result"].daily_nav` 取 NAV 做 max_diff=0 比对

    **铁律 15 硬门**: 迁移必保 `max_diff=0 Sharpe=0.6095` (5yr) + `Sharpe=0.3594` (12yr)
    与老直调 `run_hybrid_backtest` 路径 bit-identical, CI regression 锚点不得漂移.

    Args:
        years: 5 或 12, 决定加载 factor_data_{years}yr.parquet 等基线文件。
    """
    suffix = f"{years}yr"
    factor_df = pd.read_parquet(BASELINE_DIR / f"factor_data_{suffix}.parquet")
    price_data = pd.read_parquet(BASELINE_DIR / f"price_data_{suffix}.parquet")

    # 12yr 基线额外需要 benchmark (build_12yr_baseline.py 用 bench_df 计算 excess return)
    bench_df = None
    bench_path = BASELINE_DIR / f"benchmark_{suffix}.parquet"
    if bench_path.exists():
        bench_df = pd.read_parquet(bench_path)

    # Engine BacktestConfig — 保持与迁前 CORE5 regression 锚点完全一致字段
    engine_cfg = EngineBacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    # Platform BacktestConfig — 核心字段; Engine config 走 builder 注入保全 14 字段
    # (size_neutral_beta=0.0 CORE5 基线无 SN, 关联铁律 15 + Phase B M2 baseline 冻结参数)
    trading_days = sorted(price_data["trade_date"].unique())
    start_date, end_date = trading_days[0], trading_days[-1]
    # 若 parquet 回读 trade_date 是 pd.Timestamp, 转 datetime.date 对齐 Platform dataclass 签名
    if not isinstance(start_date, date):
        start_date = pd.Timestamp(start_date).date()
        end_date = pd.Timestamp(end_date).date()

    platform_cfg = PlatformCfg(
        start=start_date,
        end=end_date,
        universe="all_a",
        factor_pool=tuple(CORE5_DIRECTIONS.keys()),
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.0,
        cost_model="full",  # historical_stamp_tax=True
        capital="1000000",
        benchmark="csi300" if bench_df is not None else "none",
        extra={},
    )

    # closure data_loader: 从 baseline parquet (已加载) 返回, 对齐原直调路径
    def _baseline_loader(_platform_cfg, _start, _end):
        return factor_df, price_data, bench_df

    runner = PlatformBacktestRunner(
        registry=InMemoryBacktestRegistry(),
        data_loader=_baseline_loader,
        conn=None,  # CORE5 基线 size_neutral_beta=0, 无需 DB ln_mcap
        direction_provider=lambda pool: {n: CORE5_DIRECTIONS[n] for n in pool},
        engine_config_builder=lambda _p: engine_cfg,  # 完整 Engine config 14 字段
        signal_config_builder=lambda c: SimpleNamespace(size_neutral_beta=c.size_neutral_beta),
    )

    # LIVE_PT mode: 不 override start/end + 不 cache, 配 InMem get_by_hash 恒 None 双重真跑
    # (TODO mvp-2.3-sub3: 评估 AD_HOC mode 替代 LIVE_PT 借用)
    result = runner.run(mode=BacktestMode.LIVE_PT, config=platform_cfg)

    # PR C2 契约: cache-miss 真跑 → engine_artifacts 必塞 {engine_result, price_data}
    if result.engine_artifacts is None:
        raise RuntimeError(
            "engine_artifacts=None — 违反 PR C2 契约 (LIVE_PT always re-run), "
            "regression_test 依赖 daily_nav 做 max_diff=0 比对"
        )
    engine_result = result.engine_artifacts["engine_result"]
    return engine_result.daily_nav


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
    parser = argparse.ArgumentParser(description="回测回归测试 (铁律 15 验证)")
    parser.add_argument(
        "--years",
        type=int,
        choices=[5, 12],
        default=5,
        help="基线年数 (5yr CORE5 / 12yr 全样本, Phase B M2 扩展)",
    )
    parser.add_argument("--twice", action="store_true", help="跑两次验证确定性")
    args = parser.parse_args()

    suffix = f"{args.years}yr"
    baseline_path = BASELINE_DIR / f"nav_{suffix}.parquet"
    factor_path = BASELINE_DIR / f"factor_data_{suffix}.parquet"
    price_path = BASELINE_DIR / f"price_data_{suffix}.parquet"

    missing = [p for p in (baseline_path, factor_path, price_path) if not p.exists()]
    if missing:
        print(f"ERROR: {args.years}yr baseline files not found:")
        for p in missing:
            print(f"  - {p}")
        if args.years == 12:
            print("\n请先运行: python scripts/build_12yr_baseline.py")
        else:
            print("\n请确认 cache/baseline/ 目录完整")
        sys.exit(1)

    baseline_nav = pd.read_parquet(baseline_path)["nav"]
    print(
        f"[{suffix}] Baseline NAV: {len(baseline_nav)} days, "
        f"{float(baseline_nav.iloc[0]):.2f} -> {float(baseline_nav.iloc[-1]):.2f}"
    )

    # Run 1
    print(f"\n[Run 1] Running {suffix} backtest...")
    t0 = time.time()
    nav1 = run_backtest(years=args.years)
    elapsed1 = time.time() - t0
    result1 = compare_nav(baseline_nav, nav1)
    print(f"  Elapsed: {elapsed1:.0f}s")
    print(f"  max_diff: {result1['max_diff']}")
    print(f"  max_pct_diff: {result1['max_pct_diff']}%")
    print(f"  days_above_0.001%: {result1['days_above_0001pct']}")
    print(f"  Sharpe: baseline={result1['sharpe_baseline']}, current={result1['sharpe_current']}")

    if args.twice:
        # Run 2
        print(f"\n[Run 2] Running {suffix} backtest (determinism check)...")
        t0 = time.time()
        nav2 = run_backtest(years=args.years)
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
        "years": args.years,
        "baseline_file": str(baseline_path),
        "run1": result1,
        "elapsed_sec": round(elapsed1, 0),
    }
    output_path = BASELINE_DIR / f"regression_result_{suffix}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
