"""全量7-fold Walk-Forward训练脚本（Optuna最优超参）。

使用5个核心基线因子: turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio
GPU训练，Optuna Trial 199最优超参数。

对比基线（默认超参）:
  OOS IC=0.0823, OOS RankIC=0.0989, ICIR=0.982
"""

import logging
import sys
import time
from pathlib import Path

# 项目根目录加入path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend.engines.ml_engine import MLConfig, WalkForwardTrainer

# 配置日志
log_dir = project_root / "models"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "run_7fold_optuna.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

# ==============================================================
# Optuna最优超参（Trial 199, 200轮搜索结果）
# ==============================================================
OPTUNA_BEST_PARAMS = {
    "num_leaves": 17,
    "max_depth": 5,
    "learning_rate": 0.032766,
    "min_child_samples": 74,
    "subsample": 0.535818,
    "colsample_bytree": 0.572496,
    "reg_alpha": 0.000020,
    "reg_lambda": 0.0000001,
}

# 默认超参基线结果（用于对比）
DEFAULT_BASELINE = {
    "oos_ic": 0.0823,
    "oos_rank_ic": 0.0989,
    "oos_icir": 0.982,
}


def main():
    """运行全量7-fold Walk-Forward（Optuna最优超参）。"""
    t_start = time.time()

    # 5基线特征
    baseline_features = [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ]

    logger.info("=" * 70)
    logger.info("全量 7-Fold Walk-Forward 训练（Optuna最优超参）")
    logger.info(f"特征: {baseline_features}")
    logger.info(f"GPU: True")
    logger.info(f"Optuna超参: {OPTUNA_BEST_PARAMS}")
    logger.info("=" * 70)

    # 创建配置
    config = MLConfig(
        feature_names=baseline_features,
        gpu=True,
    )

    # 确保模型目录存在
    Path(config.model_dir).mkdir(parents=True, exist_ok=True)

    # 创建训练器
    trainer = WalkForwardTrainer(config)

    try:
        # 运行完整Walk-Forward，传入Optuna最优超参
        result = trainer.run_full_walkforward(params=OPTUNA_BEST_PARAMS)

        # 打印详细汇总表格
        total_elapsed = time.time() - t_start

        print("\n")
        print("=" * 100)
        print("全量 7-Fold Walk-Forward 结果汇总（Optuna最优超参 Trial 199）")
        print("=" * 100)

        # Optuna超参一览
        print(f"\n{'Optuna最优超参':=^60}")
        for k, v in OPTUNA_BEST_PARAMS.items():
            print(f"  {k:<25}: {v}")

        # 每个fold的详细结果
        print(f"\n{'逐Fold详细结果':=^60}")
        header = (
            f"{'Fold':>4} | {'Train IC':>9} | {'Valid IC':>9} | {'OOS IC':>9} | "
            f"{'OOS RankIC':>10} | {'ICIR':>7} | {'Overfit':>8} | "
            f"{'BestIter':>8} | {'Samples(Tr/Va/Te)':>20} | {'Time':>6} | {'Status':>8}"
        )
        print(header)
        print("-" * len(header))

        for r in result.fold_results:
            status = "OVERFIT" if r.is_overfit else "OK"
            samples = f"{r.train_samples}/{r.valid_samples}/{r.test_samples}"
            print(
                f"  F{r.fold_id} | {r.train_ic:>9.4f} | {r.valid_ic:>9.4f} | "
                f"{r.oos_ic:>9.4f} | {r.oos_rank_ic:>10.4f} | {r.oos_icir:>7.3f} | "
                f"{r.overfit_ratio:>8.2f} | {r.best_iteration:>8d} | "
                f"{samples:>20} | {r.elapsed_seconds:>5.1f}s | {status:>8}"
            )

        print("-" * len(header))

        # 汇总指标
        print(f"\n{'整体 OOS 指标':=^60}")
        print(f"  Overall OOS IC:     {result.overall_ic:.4f}")
        print(f"  Overall OOS RankIC: {result.overall_rank_ic:.4f}")
        print(f"  Overall OOS ICIR:   {result.overall_icir:.3f}")
        print(f"  有效fold数:         {result.num_folds_used} / {len(result.fold_results)}")
        print(f"  总耗时:             {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")

        # OOS预测覆盖范围
        if result.oos_predictions is not None and not result.oos_predictions.empty:
            oos = result.oos_predictions
            dates = sorted(oos["trade_date"].unique())
            print(f"  OOS预测范围:        {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
            print(f"  OOS预测总行数:      {len(oos)}")

        # 特征重要性汇总
        valid_results = [r for r in result.fold_results if not r.is_overfit and r.feature_importance]
        if valid_results:
            print(f"\n{'特征重要性 (Gain, 有效fold均值)':=^60}")
            avg_imp = {}
            for r in valid_results:
                for feat, imp in r.feature_importance.items():
                    avg_imp[feat] = avg_imp.get(feat, 0) + imp / len(valid_results)
            for feat, imp in sorted(avg_imp.items(), key=lambda x: -x[1]):
                print(f"  {feat:<25}: {imp:>10.1f}")

        # ==============================================================
        # 与默认超参基线对比
        # ==============================================================
        print(f"\n{'Optuna最优超参 vs 默认超参 对比':=^60}")
        print(f"{'指标':<20} | {'默认超参':>12} | {'Optuna最优':>12} | {'差值':>10} | {'变化%':>8}")
        print("-" * 70)

        comparisons = [
            ("OOS IC", DEFAULT_BASELINE["oos_ic"], result.overall_ic),
            ("OOS RankIC", DEFAULT_BASELINE["oos_rank_ic"], result.overall_rank_ic),
            ("ICIR", DEFAULT_BASELINE["oos_icir"], result.overall_icir),
        ]
        for name, default_val, optuna_val in comparisons:
            diff = optuna_val - default_val
            pct = (diff / abs(default_val) * 100) if abs(default_val) > 1e-8 else 0.0
            sign = "+" if diff >= 0 else ""
            print(
                f"  {name:<18} | {default_val:>12.4f} | {optuna_val:>12.4f} | "
                f"{sign}{diff:>9.4f} | {sign}{pct:>6.1f}%"
            )

        print("-" * 70)

        # 判定
        ic_better = result.overall_ic > DEFAULT_BASELINE["oos_ic"]
        icir_better = result.overall_icir > DEFAULT_BASELINE["oos_icir"]
        if ic_better and icir_better:
            verdict = "OPTUNA更优 - IC和ICIR均提升"
        elif ic_better:
            verdict = "OPTUNA IC更优，但ICIR下降 - 需权衡"
        elif icir_better:
            verdict = "OPTUNA ICIR更优，但IC下降 - 需权衡"
        else:
            verdict = "默认超参更优 - Optuna未带来改善"
        print(f"\n  结论: {verdict}")

        # 上线条件检查
        print(f"\n{'上线条件检查':=^60}")
        checks = [
            ("OOS IC > 0.02", result.overall_ic > 0.02, f"{result.overall_ic:.4f}"),
            ("OOS ICIR > 0.3", result.overall_icir > 0.3, f"{result.overall_icir:.3f}"),
            ("有效fold >= 5", result.num_folds_used >= 5, f"{result.num_folds_used}"),
        ]
        all_pass = True
        for name, passed, val in checks:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] {name}: {val}")
        print(f"\n  总结: {'ALL PASS - 可进入SimBroker回测' if all_pass else 'NOT PASS'}")

        print("=" * 100)

    finally:
        trainer.close()


if __name__ == "__main__":
    main()
