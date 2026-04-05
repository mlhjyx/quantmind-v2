"""F1 Fold SHAP特征重要性分析 + 特征子集OOS IC测试。

Sprint 1.4b: 理解为什么17特征(+12ML)的OOS IC=0.0455 < 5基线的OOS IC=0.0701。
用SHAP TreeExplainer分析特征贡献，找最优特征子集。
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根目录加入path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.engines.ml_engine import (
    FeaturePreprocessor,
    MLConfig,
    WalkForwardTrainer,
    compute_icir,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

BASELINE_FEATURES = [
    "turnover_mean_20", "volatility_20", "reversal_20",
    "amihud_20", "bp_ratio",
]

ML_FEATURES = [
    "kbar_kmid", "kbar_ksft", "kbar_kup",
    "mf_divergence", "large_order_ratio", "money_flow_strength",
    "maxret_20", "chmom_60_20", "up_days_ratio_20",
    "beta_market_20", "stoch_rsv_20", "gain_loss_ratio_20",
]

ALL_17_FEATURES = BASELINE_FEATURES + ML_FEATURES


def train_and_evaluate_fold(
    trainer: WalkForwardTrainer,
    fold,
    df: pd.DataFrame,
    feature_subset: list[str],
    label: str,
) -> dict:
    """用指定特征子集训练F1 fold并返回IC指标。

    直接调用底层训练逻辑，避免修改ml_engine.py。
    """
    import lightgbm as lgb

    t0 = time.time()

    # 切分数据
    train_df, valid_df, test_df = trainer._split_fold_data(df, fold)

    # 检查特征可用性
    available = [f for f in feature_subset if f in df.columns]
    missing = [f for f in feature_subset if f not in df.columns]
    if missing:
        logger.warning(f"[{label}] 缺失特征: {missing}")
    feature_cols = available

    if len(train_df) < 1000:
        logger.error(f"[{label}] 训练数据不足: {len(train_df)}")
        return {"label": label, "features": len(feature_cols),
                "train_ic": 0, "valid_ic": 0, "oos_ic": 0, "overfit_ratio": 0}

    # 预处理（在训练集上fit）
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_df, feature_cols)
    train_p = preprocessor.transform(train_df)
    valid_p = preprocessor.transform(valid_df)
    test_p = preprocessor.transform(test_df)

    X_train = train_p[feature_cols].values.astype(np.float32)
    y_train = train_p["excess_return_20"].values.astype(np.float32)
    X_valid = valid_p[feature_cols].values.astype(np.float32)
    y_valid = valid_p["excess_return_20"].values.astype(np.float32)
    X_test = test_p[feature_cols].values.astype(np.float32)
    test_p["excess_return_20"].values.astype(np.float32)

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    # 训练（使用trainer的默认参数）
    lgb_params = {**trainer._default_lgb_params}
    callbacks = [
        lgb.early_stopping(stopping_rounds=50, verbose=False),
        lgb.log_evaluation(period=100),
    ]

    model = lgb.train(
        lgb_params,
        train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        valid_names=["valid"],
        callbacks=callbacks,
    )

    best_iter = model.best_iteration

    # 计算IC
    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)
    test_pred = model.predict(X_test, num_iteration=best_iter)

    train_ic_s = trainer._compute_daily_ic(train_p, train_pred, "excess_return_20")
    valid_ic_s = trainer._compute_daily_ic(valid_p, valid_pred, "excess_return_20")
    test_ic_s = trainer._compute_daily_ic(test_p, test_pred, "excess_return_20")

    train_ic = float(train_ic_s.mean()) if len(train_ic_s) > 0 else 0.0
    valid_ic = float(valid_ic_s.mean()) if len(valid_ic_s) > 0 else 0.0
    oos_ic = float(test_ic_s.mean()) if len(test_ic_s) > 0 else 0.0
    oos_icir = compute_icir(test_ic_s)

    overfit = train_ic / valid_ic if valid_ic > 1e-8 else 99.0

    elapsed = time.time() - t0
    logger.info(
        f"[{label}] {len(feature_cols)}特征, best_iter={best_iter}, "
        f"Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f}, "
        f"OOS IC={oos_ic:.4f}, Overfit={overfit:.2f}, {elapsed:.1f}s"
    )

    return {
        "label": label,
        "features": len(feature_cols),
        "feature_names": feature_cols,
        "train_ic": train_ic,
        "valid_ic": valid_ic,
        "oos_ic": oos_ic,
        "oos_icir": oos_icir,
        "overfit_ratio": overfit,
        "best_iteration": best_iter,
        "elapsed": elapsed,
        "model": model,
        "preprocessor": preprocessor,
        "valid_processed": valid_p,
        "feature_cols": feature_cols,
    }


def compute_shap_importance(model, X_valid: np.ndarray, feature_cols: list[str]) -> pd.DataFrame:
    """用TreeExplainer计算SHAP特征重要性。

    Args:
        model: 训练好的LightGBM模型
        X_valid: 验证集特征矩阵
        feature_cols: 特征名列表

    Returns:
        DataFrame with columns [feature, shap_importance, rank]
    """
    import shap

    t0 = time.time()
    explainer = shap.TreeExplainer(model)

    # 采样验证集（如果太大）以加速SHAP计算
    n_samples = min(len(X_valid), 50000)
    if n_samples < len(X_valid):
        rng = np.random.RandomState(42)
        idx = rng.choice(len(X_valid), n_samples, replace=False)
        X_sample = X_valid[idx]
        logger.info(f"SHAP采样 {n_samples}/{len(X_valid)} 样本")
    else:
        X_sample = X_valid

    shap_values = explainer.shap_values(X_sample)

    # 每个特征的平均绝对SHAP值
    mean_abs_shap = np.abs(shap_values).mean(axis=0)

    df_imp = pd.DataFrame({
        "feature": feature_cols,
        "shap_importance": mean_abs_shap,
    })
    df_imp = df_imp.sort_values("shap_importance", ascending=False).reset_index(drop=True)
    df_imp["rank"] = range(1, len(df_imp) + 1)

    elapsed = time.time() - t0
    logger.info(f"SHAP计算完成: {n_samples}样本, {len(feature_cols)}特征, {elapsed:.1f}s")

    return df_imp


def main():
    print("=" * 80)
    print("  F1 Fold SHAP特征重要性分析 + 特征子集OOS IC测试")
    print("  Sprint 1.4b: 17特征 vs 5基线 诊断")
    print("=" * 80)

    # ============================================================
    # Step 1: 用全部17特征训练F1 fold
    # ============================================================
    print("\n[Step 1] 训练F1 fold (全部17特征)...")

    config_17 = MLConfig(
        feature_names=ALL_17_FEATURES,
        gpu=True,
        model_dir="models/shap_analysis",
    )

    trainer = WalkForwardTrainer(config_17)
    folds = trainer.generate_folds()
    f1 = folds[0]

    print("\nF1 fold时间窗口:")
    print(f"  Train: {f1.train_start} ~ {f1.train_end}")
    print(f"  Valid: {f1.valid_start} ~ {f1.valid_end}")
    print(f"  Test:  {f1.test_start} ~ {f1.test_end}")

    # 加载完整数据（一次加载，多次使用）
    print("\n加载特征数据...")
    df_all = trainer.load_features(f1.train_start, f1.test_end)
    print(f"数据加载完成: {len(df_all)}行, {df_all['code'].nunique()}股, "
          f"{df_all['trade_date'].nunique()}天")

    # 检查每个特征的可用性和非空率
    print("\n特征可用性检查:")
    for feat in ALL_17_FEATURES:
        if feat in df_all.columns:
            non_null = df_all[feat].notna().sum()
            pct = non_null / len(df_all) * 100
            tag = "[BASELINE]" if feat in BASELINE_FEATURES else "[ML]"
            print(f"  {tag} {feat:25s}: {non_null:>10,} 非空 ({pct:.1f}%)")
        else:
            print(f"  [MISSING] {feat}")

    # 训练全17特征模型
    result_17 = train_and_evaluate_fold(trainer, f1, df_all, ALL_17_FEATURES, "17-ALL")

    # ============================================================
    # Step 2: SHAP分析
    # ============================================================
    print("\n" + "=" * 80)
    print("[Step 2] SHAP TreeExplainer 特征重要性分析...")

    model_17 = result_17["model"]
    valid_p = result_17["valid_processed"]
    feature_cols_17 = result_17["feature_cols"]

    X_valid = valid_p[feature_cols_17].values.astype(np.float32)

    df_shap = compute_shap_importance(model_17, X_valid, feature_cols_17)

    print("\n" + "-" * 60)
    print("  SHAP Feature Importance (F1 Fold, 验证集)")
    print("-" * 60)
    print(f"  {'Rank':<5} {'Feature':<25} {'SHAP Importance':>15} {'Type':<10}")
    print("-" * 60)
    for _, row in df_shap.iterrows():
        feat = row["feature"]
        tag = "BASELINE" if feat in BASELINE_FEATURES else "ML"
        print(f"  {int(row['rank']):<5} {feat:<25} {row['shap_importance']:>15.6f} {tag:<10}")
    print("-" * 60)

    # 同时展示LightGBM gain importance对比
    gain_imp = model_17.feature_importance(importance_type="gain")
    gain_df = pd.DataFrame({
        "feature": feature_cols_17,
        "gain_importance": gain_imp,
    }).sort_values("gain_importance", ascending=False).reset_index(drop=True)
    gain_df["gain_rank"] = range(1, len(gain_df) + 1)

    # 合并SHAP和Gain排名
    merged_imp = df_shap.merge(gain_df[["feature", "gain_rank"]], on="feature")

    print("\n" + "-" * 60)
    print("  SHAP Rank vs Gain Rank 对比")
    print("-" * 60)
    print(f"  {'Feature':<25} {'SHAP Rank':>10} {'Gain Rank':>10} {'Type':<10}")
    print("-" * 60)
    for _, row in merged_imp.iterrows():
        feat = row["feature"]
        tag = "BASELINE" if feat in BASELINE_FEATURES else "ML"
        print(f"  {feat:<25} {int(row['rank']):>10} {int(row['gain_rank']):>10} {tag:<10}")
    print("-" * 60)

    # ============================================================
    # Step 3: 特征子集OOS IC测试
    # ============================================================
    print("\n" + "=" * 80)
    print("[Step 3] 特征子集OOS IC对比测试...")

    # 根据SHAP排名确定子集
    shap_ranked = df_shap["feature"].tolist()
    top5_shap = shap_ranked[:5]
    top8_shap = shap_ranked[:8]
    top10_shap = shap_ranked[:10]

    # 基线 + top-3 ML特征
    ml_ranked = [f for f in shap_ranked if f in ML_FEATURES]
    top3_ml = ml_ranked[:3]
    baseline_plus_top3 = BASELINE_FEATURES + top3_ml

    subsets = [
        ("5-BASELINE", BASELINE_FEATURES),
        ("Top5-SHAP", top5_shap),
        ("Top8-SHAP", top8_shap),
        ("Top10-SHAP", top10_shap),
        ("5BL+Top3ML", baseline_plus_top3),
        ("17-ALL", ALL_17_FEATURES),  # 重用已有结果
    ]

    results = []

    for label, features in subsets:
        if label == "17-ALL":
            # 重用Step 1的结果
            results.append({
                "label": result_17["label"],
                "features": result_17["features"],
                "feature_list": ", ".join(result_17["feature_cols"]),
                "train_ic": result_17["train_ic"],
                "valid_ic": result_17["valid_ic"],
                "oos_ic": result_17["oos_ic"],
                "oos_icir": result_17["oos_icir"],
                "overfit_ratio": result_17["overfit_ratio"],
                "best_iteration": result_17["best_iteration"],
            })
            continue

        print(f"\n  训练 [{label}]: {features}")
        res = train_and_evaluate_fold(trainer, f1, df_all, features, label)
        results.append({
            "label": res["label"],
            "features": res["features"],
            "feature_list": ", ".join(res["feature_cols"]),
            "train_ic": res["train_ic"],
            "valid_ic": res["valid_ic"],
            "oos_ic": res["oos_ic"],
            "oos_icir": res["oos_icir"],
            "overfit_ratio": res["overfit_ratio"],
            "best_iteration": res["best_iteration"],
        })

    # ============================================================
    # Step 4: 输出对比表格
    # ============================================================
    print("\n" + "=" * 80)
    print("  F1 Fold 特征子集 OOS IC 对比表")
    print("=" * 80)
    header = (f"  {'Subset':<14} {'#Feat':>5} {'Train IC':>10} {'Valid IC':>10} "
              f"{'OOS IC':>10} {'OOS ICIR':>10} {'Overfit':>8} {'BestIter':>8}")
    print(header)
    print("-" * 80)

    # 按OOS IC降序排列
    results_sorted = sorted(results, key=lambda x: x["oos_ic"], reverse=True)
    for r in results_sorted:
        marker = " ***" if r["label"] == "5-BASELINE" else ""
        overfit_flag = " !" if r["overfit_ratio"] > 3.0 else ""
        print(f"  {r['label']:<14} {r['features']:>5} {r['train_ic']:>10.4f} "
              f"{r['valid_ic']:>10.4f} {r['oos_ic']:>10.4f} {r['oos_icir']:>10.3f} "
              f"{r['overfit_ratio']:>8.2f}{overfit_flag} {r['best_iteration']:>8}{marker}")
    print("-" * 80)

    # 子集中的特征列表
    print("\n各子集包含的特征:")
    for label, features in subsets:
        avail = [f for f in features if f in df_all.columns]
        print(f"  [{label}] ({len(avail)}): {', '.join(avail)}")

    # SHAP Top特征摘要
    print(f"\nSHAP Top-5: {', '.join(top5_shap)}")
    print(f"SHAP Top-3 ML: {', '.join(top3_ml)}")

    # ============================================================
    # Step 5: 诊断总结
    # ============================================================
    print("\n" + "=" * 80)
    print("  诊断总结")
    print("=" * 80)

    best = max(results, key=lambda x: x["oos_ic"])
    worst = min(results, key=lambda x: x["oos_ic"])

    print(f"  最优子集: {best['label']} (OOS IC={best['oos_ic']:.4f})")
    print(f"  最差子集: {worst['label']} (OOS IC={worst['oos_ic']:.4f})")

    bl_result = next(r for r in results if r["label"] == "5-BASELINE")
    all_result = next(r for r in results if r["label"] == "17-ALL")

    print(f"\n  5基线 OOS IC:  {bl_result['oos_ic']:.4f} (overfit={bl_result['overfit_ratio']:.2f})")
    print(f"  17全部 OOS IC: {all_result['oos_ic']:.4f} (overfit={all_result['overfit_ratio']:.2f})")

    if all_result["overfit_ratio"] > bl_result["overfit_ratio"] * 1.5:
        print("\n  [诊断] 17特征过拟合比率显著高于5基线 -> ML特征引入噪声，模型在训练集上过拟合")
    if all_result["oos_ic"] < bl_result["oos_ic"]:
        print("  [诊断] 更多特征反而OOS更差 -> 维度灾难/噪声特征稀释信号")

    # 分析哪些ML特征可能有害
    print("\n  ML特征SHAP贡献分析:")
    baseline_shap_total = df_shap[df_shap["feature"].isin(BASELINE_FEATURES)]["shap_importance"].sum()
    ml_shap_total = df_shap[~df_shap["feature"].isin(BASELINE_FEATURES)]["shap_importance"].sum()
    print(f"    基线5因子SHAP总和: {baseline_shap_total:.6f}")
    print(f"    ML12特征SHAP总和:  {ml_shap_total:.6f}")
    print(f"    ML/Baseline比值:   {ml_shap_total/baseline_shap_total:.2f}")

    print("\n  建议:")
    if best["label"] != "17-ALL" and best["oos_ic"] > all_result["oos_ic"]:
        print(f"  -> 使用 [{best['label']}] 子集替代全部17特征")
        print(f"     OOS IC提升: {all_result['oos_ic']:.4f} -> {best['oos_ic']:.4f}")
    print("  -> 下一步: 在全部7个fold上验证最优子集的稳定性")

    print("\n" + "=" * 80)
    print("  分析完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
