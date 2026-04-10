"""Step 6-H Part 2: LightGBM 17因子 Walk-Forward 实验 (GPU)。

使用 ml_engine.WalkForwardTrainer + batch_gate_v2 的 17 个 PASS 因子。
对比: 等权 5 因子 WF (Sharpe=0.6336) / 等权 5 因子 SN b=0.50。

输出: cache/baseline/lgbm_17factor_wf_result.json
"""

from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.backtest.engine import SimpleBacktester  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe  # noqa: E402
from engines.ml_engine import MLConfig, WalkForwardTrainer  # noqa: E402

PASS_17_FACTORS = [
    "a158_cord30", "a158_vsump60", "amihud_20", "bp_ratio", "dv_ttm",
    "ep_ratio", "gap_frequency_20", "large_order_ratio", "price_volume_corr_20",
    "relative_volume_20", "reversal_20", "reversal_60", "rsrs_raw_18",
    "turnover_mean_20", "up_days_ratio_20", "volatility_20", "volume_std_20",
]

CACHE_DIR = Path("cache/baseline")
OUTPUT = CACHE_DIR / "lgbm_17factor_wf_result.json"


def predictions_to_backtest(
    oos_df: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None = None,
    top_n: int = 20,
) -> dict:
    """将 OOS 预测转为 target_portfolios 并回测。"""
    target_portfolios = {}
    for td, group in oos_df.groupby("trade_date"):
        top = group.nlargest(top_n, "predicted")
        if len(top) == 0:
            continue
        w = 1.0 / len(top)
        target_portfolios[td] = {row["code"]: w for _, row in top.iterrows()}

    if not target_portfolios:
        return {"sharpe": 0.0, "mdd": 0.0, "annual_return": 0.0, "n_rebal": 0}

    bt_config = BacktestConfig(top_n=top_n, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config)
    result = tester.run(target_portfolios, price_data, benchmark_data)

    nav = result.daily_nav
    returns = nav.pct_change().dropna()
    return {
        "sharpe": round(float(calc_sharpe(returns)), 4),
        "mdd": round(float(calc_max_drawdown(nav)), 4),
        "annual_return": round(float((nav.iloc[-1] / nav.iloc[0]) ** (244 / len(nav)) - 1), 4),
        "n_rebal": len(target_portfolios),
        "total_return": round(float(nav.iloc[-1] / nav.iloc[0] - 1), 4),
    }


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LightGBM 17-Factor Walk-Forward Experiment")
    print("=" * 60)

    # 配置
    config = MLConfig(
        feature_names=PASS_17_FACTORS,
        target="excess_return_20",
        gpu=True,
        train_months=24,
        valid_months=6,
        test_months=6,
        step_months=6,
        expanding_folds=3,
        purge_days=21,
    )

    print(f"\nFeatures: {len(config.feature_names)} factors")
    print(f"Target: {config.target}")
    print(f"GPU: {config.gpu}")

    # 训练
    t0 = time.time()
    trainer = WalkForwardTrainer(config)

    print("\n[1/3] Generating folds...")
    folds = trainer.generate_folds()
    print(f"  {len(folds)} folds generated")
    for f in folds:
        print(f"  F{f.fold_id}: train {f.train_start}..{f.train_end} | "
              f"test {f.test_start}..{f.test_end} "
              f"{'(expanding)' if f.is_expanding else '(fixed)'}")

    print("\n[2/3] Loading features from DB...")
    df = trainer.load_features(folds[0].train_start, folds[-1].test_end)
    print(f"  Features: {df.shape}")

    print("\n[3/3] Running walk-forward training...")
    fold_results = []
    all_oos = []

    for fold in folds:
        print(f"\n--- Fold {fold.fold_id} ---")
        try:
            fr, preprocessor = trainer.train_fold(fold, df)
            oos_df = trainer.predict_oos(fold, df, preprocessor, fr.model)

            fold_results.append({
                "fold_id": fold.fold_id,
                "train_period": f"{fold.train_start}..{fold.train_end}",
                "test_period": f"{fold.test_start}..{fold.test_end}",
                "train_ic": round(float(fr.train_ic), 4),
                "valid_ic": round(float(fr.valid_ic), 4),
                "oos_ic": round(float(fr.oos_ic), 4),
                "feature_importance_top5": dict(
                    sorted(fr.feature_importance.items(), key=lambda x: -x[1])[:5]
                ) if fr.feature_importance else {},
            })
            all_oos.append(oos_df)

            print(f"  Train IC: {fr.train_ic:.4f}, Valid IC: {fr.valid_ic:.4f}, "
                  f"OOS IC: {fr.oos_ic:.4f}")
        except Exception as e:
            print(f"  FAILED: {e}")
            fold_results.append({
                "fold_id": fold.fold_id,
                "error": str(e),
            })

    elapsed = time.time() - t0
    print(f"\nTotal training time: {elapsed:.0f}s")

    # 释放特征内存（训练已完成）
    del df
    gc.collect()
    print("  Freed feature DataFrame memory")

    # OOS 回测
    backtest_result = {}
    if all_oos:
        print("\n[Backtest] Converting OOS predictions to portfolio...")
        combined_oos = pd.concat(all_oos, ignore_index=True)
        print(f"  OOS predictions: {combined_oos.shape}")

        # 只加载OOS覆盖年份的 price_data 和 benchmark（节省内存）
        oos_dates = pd.to_datetime(combined_oos["trade_date"])
        oos_start_year = oos_dates.min().year
        oos_end_year = oos_dates.max().year
        print(f"  OOS period: {oos_start_year}-{oos_end_year}")

        cache_root = Path("cache/backtest")
        price_parts, bench_parts = [], []
        for year_dir in sorted(cache_root.iterdir()):
            if not year_dir.is_dir():
                continue
            try:
                year = int(year_dir.name)
            except ValueError:
                continue
            if year < oos_start_year or year > oos_end_year:
                continue
            pf = year_dir / "price_data.parquet"
            bf = year_dir / "benchmark.parquet"
            if pf.exists():
                price_parts.append(pd.read_parquet(pf))
            if bf.exists():
                bench_parts.append(pd.read_parquet(bf))

        if price_parts:
            price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
            bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date") if bench_parts else None
            backtest_result = predictions_to_backtest(combined_oos, price_df, bench_df)
            print(f"  Sharpe: {backtest_result['sharpe']}")
            print(f"  MDD: {backtest_result['mdd']}")
            print(f"  Annual Return: {backtest_result['annual_return']}")

    # 对比
    print("\n=== Comparison ===")
    print(f"  LightGBM 17-factor: Sharpe={backtest_result.get('sharpe', 'N/A')}")
    print("  Equal-weight base WF (Step 6-D): Sharpe=0.6336")
    print("  Equal-weight 12yr (Step 6-D): Sharpe=0.5309")

    output = {
        "config": {
            "features": PASS_17_FACTORS,
            "target": config.target,
            "gpu": config.gpu,
            "train_months": config.train_months,
            "n_folds": len(folds),
        },
        "fold_results": fold_results,
        "backtest": backtest_result,
        "elapsed_s": round(elapsed, 1),
        "comparison": {
            "lgbm_17factor_sharpe": backtest_result.get("sharpe"),
            "equal_weight_base_wf_sharpe": 0.6336,
            "equal_weight_12yr_sharpe": 0.5309,
        },
    }
    OUTPUT.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {OUTPUT}")


if __name__ == "__main__":
    main()
