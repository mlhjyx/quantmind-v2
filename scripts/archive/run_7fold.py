"""全量7-fold Walk-Forward训练脚本（5基线特征，默认超参）。

使用5个核心基线因子: turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio
GPU训练，默认LightGBM超参数。
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "models" / "run_7fold.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)


def main():
    """运行全量7-fold Walk-Forward。"""
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
    logger.info("全量 7-Fold Walk-Forward 训练")
    logger.info(f"特征: {baseline_features}")
    logger.info("GPU: True")
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
        # 运行完整Walk-Forward
        result = trainer.run_full_walkforward()

        # 打印详细汇总表格
        total_elapsed = time.time() - t_start

        print("\n")
        print("=" * 90)
        print("全量 7-Fold Walk-Forward 结果汇总")
        print("=" * 90)

        # 每个fold的详细结果
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
        print(f"\n{'整体 OOS 指标':=^50}")
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

        # 特征重要性汇总（取所有有效fold的平均）
        valid_results = [r for r in result.fold_results if not r.is_overfit and r.feature_importance]
        if valid_results:
            print(f"\n{'特征重要性 (Gain, 有效fold均值)':=^50}")
            avg_imp = {}
            for r in valid_results:
                for feat, imp in r.feature_importance.items():
                    avg_imp[feat] = avg_imp.get(feat, 0) + imp / len(valid_results)
            for feat, imp in sorted(avg_imp.items(), key=lambda x: -x[1]):
                print(f"  {feat:<25}: {imp:>10.1f}")

        # 上线条件检查
        print(f"\n{'上线条件检查':=^50}")
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

        print("=" * 90)

    finally:
        trainer.close()


if __name__ == "__main__":
    main()
