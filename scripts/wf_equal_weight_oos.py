#!/usr/bin/env python3
"""Step 6-D Part 2: 5 因子等权策略 Walk-Forward OOS 稳定性测试.

参数 (来自任务规格):
  数据范围: 2014-01-01 ~ 2026-04-09 (cache/backtest/2014-2026/*.parquet)
  训练窗口: 750 交易日 (3 年) — 等权策略会**忽略** train_dates,
            仅用于 split 分布 (这不是过拟合测试, 是稳定性测试)
  测试窗口: 250 交易日 (1 年)
  Gap:     5 交易日 (防前瞻)
  Fold:    5
  因子:    CORE 5 (turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)
  Top-N:   20, 月度调仓, industry_cap=1.0, volume_impact 滑点, PMS v1.0
  Universe: exclude BJ/ST/suspended/new_stock (通过 build_exclusion_map)

MVP 2.3 Sub2 (2026-04-19): 迁 Platform SDK, 每 fold 走 PlatformBacktestRunner.

输出:
  cache/baseline/wf_oos_result.json   — 每折指标 + 汇总
  cache/baseline/wf_oos_nav.parquet   — 每折 NAV + chain-link NAV 曲线

用法:
    python scripts/wf_equal_weight_oos.py
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from engines.backtest.config import BacktestConfig as EngineBacktestConfig  # noqa: E402
from engines.backtest.config import PMSConfig  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino  # noqa: E402
from engines.slippage_model import SlippageConfig  # noqa: E402
from engines.walk_forward import WalkForwardEngine, WFConfig  # noqa: E402

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

# Factor lookback: 最大因子窗口是 20 天 (turnover_mean_20), 预留 60 天 warmup
FACTOR_LOOKBACK_DAYS = 60


def load_12yr_parquet_cache():
    """从 cache/backtest/2014..2026 拼接 12 年数据。"""
    print("[Load] 加载 12 年 Parquet 缓存...")
    t0 = time.time()
    fd, pd_, bm = [], [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])

    for year in years:
        yr_dir = CACHE_DIR / str(year)
        pd_.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        fd.append(pd.read_parquet(yr_dir / "factor_data.parquet"))
        bm.append(pd.read_parquet(yr_dir / "benchmark.parquet"))

    price_df = pd.concat(pd_, ignore_index=True).sort_values(["code", "trade_date"])
    factor_df = pd.concat(fd, ignore_index=True)
    bench_df = pd.concat(bm, ignore_index=True).sort_values("trade_date").drop_duplicates("trade_date")

    # cache/backtest/*.parquet 的 "raw_value" 实际是中性化值, rename 对齐 run_hybrid_backtest 约定
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    print(f"  price_df:  {price_df.shape}  {price_df['trade_date'].min()}..{price_df['trade_date'].max()}")
    print(f"  factor_df: {factor_df.shape}")
    print(f"  bench_df:  {bench_df.shape}")
    print(f"  加载耗时: {time.time() - t0:.1f}s")
    return factor_df, price_df, bench_df


def monthly_win_rate(nav: pd.Series) -> float:
    """月胜率 = 月收益为正的月数 / 总月数。"""
    if len(nav) < 2:
        return 0.0
    nav = nav.copy()
    nav.index = pd.to_datetime(nav.index)
    monthly = nav.resample("ME").last().pct_change().dropna()
    if len(monthly) == 0:
        return 0.0
    return float((monthly > 0).sum() / len(monthly))


def run_fold(
    fold_idx: int,
    train_dates: list,
    test_dates: list,
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    engine_cfg: EngineBacktestConfig,
) -> dict:
    """在单折 test 期上走 PlatformBacktestRunner (MVP 2.3 Sub2 迁).

    等权策略忽略 train_dates. 为了避免因子 lookback 溢出, 我们给 factor_df 多
    留 FACTOR_LOOKBACK_DAYS 天历史 (仅因子, 不影响 price/bench)。
    price_df 和 bench_df 切到 test_dates 范围。
    """
    from datetime import timedelta

    test_start = min(test_dates)
    test_end = max(test_dates)

    # price/bench 切 test 期
    fold_price = price_df[
        (price_df["trade_date"] >= test_start)
        & (price_df["trade_date"] <= test_end)
    ].copy()
    fold_bench = bench_df[
        (bench_df["trade_date"] >= test_start)
        & (bench_df["trade_date"] <= test_end)
    ].copy()

    # factor_df 留 lookback, 从 test_start - N 天开始
    # 因子是 rolling 20 天的, 60 天 lookback 足够让因子在 test_start 当天可用
    factor_start = test_start - timedelta(days=FACTOR_LOOKBACK_DAYS)
    fold_factor = factor_df[
        (factor_df["trade_date"] >= factor_start)
        & (factor_df["trade_date"] <= test_end)
    ].copy()

    print(
        f"  Fold {fold_idx}: test [{test_start}..{test_end}] "
        f"price={len(fold_price):,} factor={len(fold_factor):,}"
    )

    # Platform BacktestConfig — per-fold start/end, factor_pool sorted
    platform_cfg = PlatformBacktestConfig(
        start=pd.Timestamp(test_start).date(),
        end=pd.Timestamp(test_end).date(),
        universe="all_a",
        factor_pool=tuple(sorted(DIRECTIONS.keys())),
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.0,
        cost_model="full",
        capital="1000000",
        benchmark="csi300",
        extra={"fold_idx": fold_idx},  # config_hash 含 fold_idx 防折间 cache 冲突
    )

    runner = PlatformBacktestRunner(
        registry=InMemoryBacktestRegistry(),
        data_loader=lambda _c, _s, _e: (fold_factor, fold_price, fold_bench),
        conn=None,
        direction_provider=lambda pool: {n: DIRECTIONS[n] for n in pool},
        engine_config_builder=lambda _p: engine_cfg,
        signal_config_builder=lambda c: SimpleNamespace(size_neutral_beta=c.size_neutral_beta),
    )

    t0 = time.time()
    platform_result = runner.run(mode=BacktestMode.LIVE_PT, config=platform_cfg)
    if platform_result.engine_artifacts is None:
        raise RuntimeError(
            f"engine_artifacts=None (fold={fold_idx}) — LIVE_PT 应强制真跑"
        )
    result = platform_result.engine_artifacts["engine_result"]
    elapsed = time.time() - t0

    # 只保留 test 期内 NAV (run_hybrid_backtest 会产出 test 期的完整 NAV,
    # 但如果 factor_df 扩展到 pre-test, 它仍然只在 test 期开始交易)
    nav = result.daily_nav
    returns = nav.pct_change().dropna()

    if len(returns) < 2:
        return {
            "fold_idx": fold_idx,
            "test_start": str(test_start),
            "test_end": str(test_end),
            "oos_sharpe": 0.0,
            "oos_mdd": 0.0,
            "oos_annual_return": 0.0,
            "oos_sortino": 0.0,
            "oos_total_return": 0.0,
            "monthly_win_rate": 0.0,
            "test_days": len(nav),
            "total_trades": 0,
            "elapsed_sec": round(elapsed, 1),
            "nav": nav,
            "returns": returns,
        }

    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    years = len(returns) / 244.0
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)
    win_rate = monthly_win_rate(nav)

    return {
        "fold_idx": fold_idx,
        "test_start": str(test_start),
        "test_end": str(test_end),
        "oos_sharpe": round(sharpe, 4),
        "oos_mdd": round(mdd, 6),
        "oos_annual_return": round(annual_return, 6),
        "oos_sortino": round(sortino, 4),
        "oos_total_return": round(total_return, 6),
        "monthly_win_rate": round(win_rate, 4),
        "test_days": len(nav),
        "total_trades": len(result.trades) if hasattr(result, "trades") else 0,
        "elapsed_sec": round(elapsed, 1),
        "nav": nav,
        "returns": returns,
    }


def chain_link_nav(fold_returns: list) -> pd.Series:
    """用各折日收益率链接成连续 NAV 曲线 (initial=1.0, chain-link)。

    每折独立重置 NAV → 1M (SimpleBacktester 行为), 但收益率序列可用于链接。
    拼接顺序按 fold 时间顺序, 时间索引从第一折第一天。
    """
    if not fold_returns:
        return pd.Series(dtype=float)
    parts = []
    for fr in fold_returns:
        ret = fr.copy()
        parts.append(ret)
    combined_returns = pd.concat(parts).sort_index()
    # 去除重复日期 (fold 间可能有 1 天重叠, 保留第一次出现)
    combined_returns = combined_returns[~combined_returns.index.duplicated(keep="first")]
    nav = (1.0 + combined_returns).cumprod() * 1_000_000
    return nav


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 加载 12 年数据
    factor_df, price_df, bench_df = load_12yr_parquet_cache()

    # 2. 生成 fold 分割
    print("\n[Split] 生成 5 fold 分割...")
    all_dates = sorted(price_df["trade_date"].unique())
    print(f"  总交易日: {len(all_dates)} ({all_dates[0]}..{all_dates[-1]})")

    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    print(f"  配置: n_splits={wf_config.n_splits}, train={wf_config.train_window}, gap={wf_config.gap}, test={wf_config.test_window}")
    print(f"  最少需要: {wf_config.train_window + wf_config.gap + wf_config.n_splits * wf_config.test_window} 交易日")

    splits = WalkForwardEngine(wf_config).generate_splits(all_dates)
    print(f"  生成了 {len(splits)} 折")
    for i, (tr, te) in enumerate(splits):
        print(f"    Fold {i}: train[{tr[0]}..{tr[-1]}] ({len(tr)}d) → test[{te[0]}..{te[-1]}] ({len(te)}d)")

    # 3. 逐折跑回测 (Platform Runner 注入 engine_cfg)
    engine_cfg = EngineBacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    print("\n[Backtest] 逐折执行...")
    t_total = time.time()
    fold_results = []
    for fold_idx, (train_dates, test_dates) in enumerate(splits):
        r = run_fold(
            fold_idx=fold_idx,
            train_dates=train_dates,
            test_dates=test_dates,
            factor_df=factor_df,
            price_df=price_df,
            bench_df=bench_df,
            engine_cfg=engine_cfg,
        )
        fold_results.append(r)
        print(
            f"    Fold {fold_idx}: Sharpe={r['oos_sharpe']}, MDD={r['oos_mdd']:.2%}, "
            f"Annual={r['oos_annual_return']:.2%}, WinRate={r['monthly_win_rate']:.2%}, "
            f"elapsed={r['elapsed_sec']:.0f}s"
        )

    elapsed_total = time.time() - t_total
    print(f"  总耗时: {elapsed_total:.0f}s")

    # 4. 链接 OOS NAV
    print("\n[Chain-Link] 拼接各折收益率...")
    fold_returns_list = [r["returns"] for r in fold_results]
    chain_nav = chain_link_nav(fold_returns_list)
    chain_returns = chain_nav.pct_change().dropna()

    chain_sharpe = float(calc_sharpe(chain_returns))
    chain_mdd = float(calc_max_drawdown(chain_nav))
    chain_sortino = float(calc_sortino(chain_returns))
    chain_years = len(chain_returns) / 244.0
    chain_total_ret = float(chain_nav.iloc[-1] / chain_nav.iloc[0] - 1)
    chain_annual = float((1 + chain_total_ret) ** (1 / max(chain_years, 0.01)) - 1)
    chain_win_rate = monthly_win_rate(chain_nav)

    # 5. 汇总指标
    sharpes = np.array([r["oos_sharpe"] for r in fold_results])
    mdds = np.array([r["oos_mdd"] for r in fold_results])
    annuals = np.array([r["oos_annual_return"] for r in fold_results])

    # 12yr 全样本基线 (从 Fix 6 metrics_12yr.json 读)
    metrics_12yr_path = BASELINE_DIR / "metrics_12yr.json"
    if metrics_12yr_path.exists():
        m12 = json.loads(metrics_12yr_path.read_text())
        in_sample_sharpe = m12["sharpe"]
        in_sample_mdd = m12["mdd_pct"] / 100
        in_sample_annual = m12["annual_return_pct"] / 100
    else:
        in_sample_sharpe = None
        in_sample_mdd = None
        in_sample_annual = None

    summary = {
        "config": {
            "n_splits": wf_config.n_splits,
            "train_window": wf_config.train_window,
            "gap": wf_config.gap,
            "test_window": wf_config.test_window,
            "factors": list(DIRECTIONS.keys()),
            "top_n": 20,
            "rebalance_freq": "monthly",
            "exclude_bj_st_new_suspended": True,
            "slippage": "volume_impact",
            "pms_enabled": True,
        },
        "folds": [
            {k: v for k, v in r.items() if k not in ("nav", "returns")}
            for r in fold_results
        ],
        "fold_stats": {
            "sharpe_mean": round(float(sharpes.mean()), 4),
            "sharpe_std": round(float(sharpes.std(ddof=1)) if len(sharpes) > 1 else 0.0, 4),
            "sharpe_min": round(float(sharpes.min()), 4),
            "sharpe_max": round(float(sharpes.max()), 4),
            "mdd_mean": round(float(mdds.mean()), 6),
            "mdd_worst": round(float(mdds.min()), 6),
            "annual_mean": round(float(annuals.mean()), 6),
            "folds_with_negative_sharpe": int((sharpes < 0).sum()),
        },
        "chain_link": {
            "sharpe": round(chain_sharpe, 4),
            "mdd": round(chain_mdd, 6),
            "annual_return": round(chain_annual, 6),
            "sortino": round(chain_sortino, 4),
            "total_return": round(chain_total_ret, 6),
            "monthly_win_rate": round(chain_win_rate, 4),
            "total_days": int(len(chain_nav)),
            "date_range": [str(chain_nav.index[0]), str(chain_nav.index[-1])],
        },
        "in_sample_12yr": {
            "sharpe": in_sample_sharpe,
            "mdd": in_sample_mdd,
            "annual_return": in_sample_annual,
        },
        "overfit_ratio": round(chain_sharpe / in_sample_sharpe, 4)
        if in_sample_sharpe
        else None,
        "elapsed_sec": round(elapsed_total, 0),
    }

    # 稳定性判定
    std = summary["fold_stats"]["sharpe_std"]
    neg_folds = summary["fold_stats"]["folds_with_negative_sharpe"]
    if std < 0.15 and neg_folds == 0:
        verdict = "STABLE — 折间 Sharpe std < 0.15 且无负 fold"
    elif std < 0.4 and neg_folds == 0:
        verdict = "REGIME_DEPENDENT — std 中等, 需要分年度归因"
    elif neg_folds > 0:
        verdict = "UNSTABLE — 存在负 Sharpe fold, 策略在某时期失效"
    else:
        verdict = "HIGH_VARIANCE — 折间差异大"
    summary["stability_verdict"] = verdict

    # 6. 保存
    # JSON summary
    summary_path = BASELINE_DIR / "wf_oos_result.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[Save] Summary → {summary_path}")

    # NAV parquet (每折 NAV + chain-link)
    nav_frames = []
    for r in fold_results:
        df = r["nav"].to_frame("nav").copy()
        df["fold"] = r["fold_idx"]
        df["kind"] = "fold"
        df.index.name = "trade_date"
        nav_frames.append(df.reset_index())

    chain_df = chain_nav.to_frame("nav").copy()
    chain_df["fold"] = -1
    chain_df["kind"] = "chain_link"
    chain_df.index.name = "trade_date"
    nav_frames.append(chain_df.reset_index())

    combined_nav = pd.concat(nav_frames, ignore_index=True)
    nav_path = BASELINE_DIR / "wf_oos_nav.parquet"
    combined_nav.to_parquet(nav_path, index=False)
    print(f"[Save] NAV → {nav_path}")

    # 7. 打印报告
    print("\n" + "=" * 72)
    print("  Walk-Forward 5-Fold OOS 稳定性测试 — 结果")
    print("=" * 72)
    print("\n每折 OOS 指标:")
    print(f"  {'Fold':>4}  {'Test Period':^23}  {'Sharpe':>7}  {'MDD':>8}  {'Annual':>8}  {'WinRate':>8}  {'Trades':>7}")
    print(f"  {'-'*4}  {'-'*23}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*7}")
    for r in fold_results:
        period = f"{r['test_start']}~{r['test_end']}"
        print(
            f"  {r['fold_idx']:>4}  {period:^23}  {r['oos_sharpe']:>7.4f}  "
            f"{r['oos_mdd']:>8.2%}  {r['oos_annual_return']:>8.2%}  "
            f"{r['monthly_win_rate']:>8.2%}  {r['total_trades']:>7}"
        )

    print("\n折间分布:")
    fs = summary["fold_stats"]
    print(f"  Sharpe mean ± std: {fs['sharpe_mean']} ± {fs['sharpe_std']}")
    print(f"  Sharpe range:      [{fs['sharpe_min']}, {fs['sharpe_max']}]")
    print(f"  MDD mean / worst:  {fs['mdd_mean']:.2%} / {fs['mdd_worst']:.2%}")
    print(f"  Annual mean:       {fs['annual_mean']:.2%}")
    print(f"  Neg-Sharpe folds:  {fs['folds_with_negative_sharpe']}")

    print("\nChain-link OOS:")
    cl = summary["chain_link"]
    print(f"  Sharpe:            {cl['sharpe']}")
    print(f"  MDD:               {cl['mdd']:.2%}")
    print(f"  Annual:            {cl['annual_return']:.2%}")
    print(f"  Total Return:      {cl['total_return']:.2%}")
    print(f"  Monthly WinRate:   {cl['monthly_win_rate']:.2%}")
    print(f"  Total Days:        {cl['total_days']}")

    if in_sample_sharpe is not None:
        print("\n12 年 In-Sample 对照:")
        print(f"  In-Sample Sharpe:  {in_sample_sharpe}")
        print(f"  OOS Chain-Link:    {cl['sharpe']}")
        print(f"  过拟合比率:        {summary['overfit_ratio']} (>0.7 好, <0.5 严重过拟合)")

    print(f"\n稳定性判断: {verdict}")
    print(f"总耗时: {elapsed_total:.0f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
