"""Optuna 200轮超参搜索 -- 5基线特征, F1 fold。

目标: 在F1 fold (train: 2020-07~2022-06, valid: 2022-07~2022-12) 上
搜索LightGBM最优超参，与默认超参 (OOS IC=0.0706, best_iter=47) 对比。

不修改 ml_engine.py，复用其 WalkForwardTrainer API 加载数据和预处理。
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.engines.ml_engine import (
    FeaturePreprocessor,
    MLConfig,
    WalkForwardTrainer,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("optuna_search")

# ============================================================
# 配置
# ============================================================

BASELINE_FEATURES = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

N_TRIALS = 200
SEED = 42

# ============================================================
# 数据加载（只做一次）
# ============================================================


def load_f1_data():
    """加载F1 fold数据，返回 (train_df, valid_df, test_df, feature_cols, preprocessor)。"""
    config = MLConfig(
        feature_names=BASELINE_FEATURES,
        gpu=True,
    )
    trainer = WalkForwardTrainer(config)
    folds = trainer.generate_folds()
    f1 = folds[0]

    logger.info(f"F1 fold: Train[{f1.train_start}~{f1.train_end}] "
                f"Valid[{f1.valid_start}~{f1.valid_end}] "
                f"Test[{f1.test_start}~{f1.test_end}]")

    # 加载全部数据（train + valid + test范围）
    df = trainer.load_features(f1.train_start, f1.test_end)
    logger.info(f"总数据量: {len(df)}行, {df['code'].nunique()}股")

    # 切分
    train_df, valid_df, test_df = trainer._split_fold_data(df, f1)
    logger.info(f"Train: {len(train_df)}, Valid: {len(valid_df)}, Test: {len(test_df)}")

    # 预处理
    feature_cols = [c for c in BASELINE_FEATURES if c in df.columns]
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_df, feature_cols)

    train_processed = preprocessor.transform(train_df)
    valid_processed = preprocessor.transform(valid_df)
    test_processed = preprocessor.transform(test_df)

    trainer.close()

    return train_processed, valid_processed, test_processed, feature_cols


def compute_mean_rank_ic(df, predictions, target_col="excess_return_20"):
    """计算验证集上的平均RankIC。"""
    temp = df[["trade_date", target_col]].copy()
    temp["predicted"] = predictions

    daily_ics = []
    for td, group in temp.groupby("trade_date"):
        if len(group) < 30:
            continue
        ic = group["predicted"].rank().corr(group[target_col].rank())
        if not np.isnan(ic):
            daily_ics.append(ic)

    return float(np.mean(daily_ics)) if daily_ics else 0.0


def compute_mean_ic(df, predictions, target_col="excess_return_20"):
    """计算平均IC (Pearson)。"""
    temp = df[["trade_date", target_col]].copy()
    temp["predicted"] = predictions

    daily_ics = []
    for td, group in temp.groupby("trade_date"):
        if len(group) < 30:
            continue
        ic = group["predicted"].corr(group[target_col])
        if not np.isnan(ic):
            daily_ics.append(ic)

    return float(np.mean(daily_ics)) if daily_ics else 0.0


# ============================================================
# Optuna目标函数
# ============================================================


def create_objective(X_train, y_train, X_valid, y_valid,
                     train_processed, valid_processed, feature_cols):
    """闭包创建objective，避免每次重新加载数据。"""
    import lightgbm as lgb

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    def objective(trial):
        params = {
            "objective": "regression",
            "metric": "mse",
            "boosting_type": "gbdt",
            "verbose": -1,
            "seed": SEED,
            "n_jobs": -1,
            "device_type": "gpu",
            "gpu_platform_id": 0,
            "gpu_device_id": 0,
            "gpu_use_dp": False,
            "max_bin": 63,
            "subsample_freq": 1,
            "feature_pre_filter": False,
            # 搜索空间（9维）
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 50, 500),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        }
        n_estimators = trial.suggest_int("n_estimators", 50, 500)

        # Pruning callback: 报告每轮valid IC给Optuna
        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=0),  # silent
        ]

        # 训练
        model = lgb.train(
            params,
            train_data,
            num_boost_round=n_estimators,
            valid_sets=[valid_data],
            valid_names=["valid"],
            callbacks=callbacks,
        )

        best_iter = model.best_iteration

        # 验证集RankIC
        valid_pred = model.predict(X_valid, num_iteration=best_iter)
        valid_rank_ic = compute_mean_rank_ic(valid_processed, valid_pred)

        # 过拟合检测
        train_pred = model.predict(X_train, num_iteration=best_iter)
        train_ic = compute_mean_ic(train_processed, train_pred)

        if train_ic > 0 and valid_rank_ic > 0:
            overfit_ratio = train_ic / valid_rank_ic
            if overfit_ratio > 3.0:
                logger.warning(f"Trial {trial.number}: overfit_ratio={overfit_ratio:.2f} > 3.0, penalty=-999")
                return -999.0
            elif overfit_ratio > 2.0:
                logger.warning(f"Trial {trial.number}: overfit_ratio={overfit_ratio:.2f} > 2.0, light penalty")
                return -(valid_rank_ic * 0.8)

        # 记录额外信息
        trial.set_user_attr("valid_rank_ic", valid_rank_ic)
        trial.set_user_attr("train_ic", train_ic)
        trial.set_user_attr("best_iteration", best_iter)
        trial.set_user_attr("overfit_ratio",
                            train_ic / valid_rank_ic if valid_rank_ic > 1e-8 else 99.0)

        return -valid_rank_ic  # minimize

    return objective


# ============================================================
# Main
# ============================================================


def main():
    t_start = time.time()

    # 1. 加载数据（一次性）
    logger.info("=" * 60)
    logger.info("Step 1: 加载F1 fold数据")
    logger.info("=" * 60)

    train_processed, valid_processed, test_processed, feature_cols = load_f1_data()

    X_train = train_processed[feature_cols].values.astype(np.float32)
    y_train = train_processed["excess_return_20"].values.astype(np.float32)
    X_valid = valid_processed[feature_cols].values.astype(np.float32)
    y_valid = valid_processed["excess_return_20"].values.astype(np.float32)
    X_test = test_processed[feature_cols].values.astype(np.float32)
    y_test = test_processed["excess_return_20"].values.astype(np.float32)

    logger.info(f"X_train: {X_train.shape}, X_valid: {X_valid.shape}, X_test: {X_test.shape}")

    # 2. Optuna搜索
    logger.info("=" * 60)
    logger.info(f"Step 2: Optuna超参搜索 ({N_TRIALS} trials)")
    logger.info("=" * 60)

    sampler = TPESampler(n_startup_trials=20, seed=SEED)
    pruner = MedianPruner(n_startup_trials=10, n_warmup_steps=30)

    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        pruner=pruner,
        study_name="lgbm_f1_baseline5",
    )

    objective = create_objective(
        X_train, y_train, X_valid, y_valid,
        train_processed, valid_processed, feature_cols,
    )

    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=True,
                   catch=(Exception,))

    # 3. 结果输出
    logger.info("=" * 60)
    logger.info("Step 3: 搜索结果")
    logger.info("=" * 60)

    # Top-5 trials
    trials_sorted = sorted(
        [t for t in study.trials if t.value is not None and t.value > -900],
        key=lambda t: t.value,
    )
    top5 = trials_sorted[:5]

    print("\n" + "=" * 70)
    print("Top-5 Trials (by valid RankIC)")
    print("=" * 70)
    for i, t in enumerate(top5):
        valid_ic = -t.value
        attrs = t.user_attrs
        print(f"  #{i+1} Trial {t.number}: Valid RankIC = {valid_ic:.4f}, "
              f"Train IC = {attrs.get('train_ic', 'N/A'):.4f}, "
              f"best_iter = {attrs.get('best_iteration', 'N/A')}, "
              f"overfit = {attrs.get('overfit_ratio', 'N/A'):.2f}")

    # Best trial完整超参
    best = study.best_trial
    best_valid_ic = -best.value

    print("\n" + "=" * 70)
    print("Best Trial完整超参")
    print("=" * 70)
    for k, v in sorted(best.params.items()):
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: {v}")
    print(f"\n  Valid RankIC: {best_valid_ic:.4f}")
    print(f"  Best iteration: {best.user_attrs.get('best_iteration', 'N/A')}")
    print(f"  Overfit ratio: {best.user_attrs.get('overfit_ratio', 'N/A'):.2f}")

    # 4. 用best params在F1 test set上验证（仅一次）
    logger.info("=" * 60)
    logger.info("Step 4: Best params OOS验证 (F1 test set)")
    logger.info("=" * 60)

    import lightgbm as lgb

    best_params = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "verbose": -1,
        "seed": SEED,
        "n_jobs": -1,
        "device_type": "gpu",
        "gpu_platform_id": 0,
        "gpu_device_id": 0,
        "gpu_use_dp": False,
        "max_bin": 63,
        "subsample_freq": 1,
    }
    # 注入搜索到的超参（排除n_estimators，单独用于num_boost_round）
    n_estimators_best = best.params.pop("n_estimators", 500)
    best_params.update(best.params)

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    model_best = lgb.train(
        best_params,
        train_data,
        num_boost_round=n_estimators_best,
        valid_sets=[valid_data],
        valid_names=["valid"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ],
    )

    # OOS预测
    test_pred = model_best.predict(X_test, num_iteration=model_best.best_iteration)
    oos_rank_ic = compute_mean_rank_ic(test_processed, test_pred)
    oos_ic = compute_mean_ic(test_processed, test_pred)

    # 默认超参对比基线
    print("\n" + "=" * 70)
    print("OOS对比 (F1 test set: 2023-01 ~ 2023-06)")
    print("=" * 70)
    print("  默认超参 OOS IC:     0.0706 (baseline)")
    print(f"  Best超参 OOS IC:     {oos_ic:.4f}")
    print(f"  Best超参 OOS RankIC: {oos_rank_ic:.4f}")
    print(f"  Best iteration:      {model_best.best_iteration}")
    improvement = (oos_ic - 0.0706) / 0.0706 * 100
    print(f"  IC improvement:      {improvement:+.1f}%")

    # 5. 总耗时
    elapsed = time.time() - t_start
    mins = elapsed / 60
    print(f"\n  总运行时间: {mins:.1f}分钟 ({elapsed:.0f}秒)")

    # 统计
    n_complete = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    n_pruned = len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED])
    print(f"  完成trials: {n_complete}, 被剪枝: {n_pruned}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
