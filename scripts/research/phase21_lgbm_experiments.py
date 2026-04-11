#!/usr/bin/env python
"""Phase 2.1 层1: LightGBM Walk-Forward 三组实验。

Exp-C: CORE 5因子(对照组) — turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio
Exp-A: Tier 1 13因子 — CORE 5 + RSQR_20, QTLU_20, ind_mom_60, high_vol_price_ratio_20,
       nb_change_rate_20d, nb_trend_20d, nb_ratio_change_5d, nb_net_buy_5d_ratio
Exp-B: Tier 1+2 ~20因子 — Exp-A + IMAX_20, IMIN_20, RESI_20, CORD_20, ind_mom_20

串行执行: Exp-C → (诊断 vs G1) → Exp-A → Exp-B
选OOS IC最高 + trainIC/validIC < 2.0的实验组。

配置: train=60月, valid=12月, test=12月, purge=21天, 12年全量, GPU

Usage:
    cd backend && python ../scripts/research/phase21_lgbm_experiments.py
    cd backend && python ../scripts/research/phase21_lgbm_experiments.py --exp C
    cd backend && python ../scripts/research/phase21_lgbm_experiments.py --exp A
    cd backend && python ../scripts/research/phase21_lgbm_experiments.py --exp B
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# ─── 实验组定义 ─────────────────────────────────────────

FEATURES_C = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]

# Exp-A: CORE5 + 可用的Tier1因子(需neutral_value)
# ind_mom_60: 0行(未入库), nb_*: raw only(未中性化), hvp: partial
# 先用可用的7因子运行, 后续补全后可重跑
FEATURES_A = FEATURES_C + [
    "RSQR_20", "QTLU_20",
]

# Exp-A-full: 包含北向+HVP(中性化后可用)
FEATURES_A_FULL = FEATURES_C + [
    "RSQR_20", "QTLU_20",
    "ind_mom_60", "high_vol_price_ratio_20",
    "nb_change_rate_20d", "nb_trend_20d", "nb_ratio_change_5d", "nb_net_buy_5d_ratio",
]

# Exp-B: 所有有neutral_value的因子 (16因子)
# 排除: ind_mom_60/20(0行), nb_change_rate_20d/nb_trend_20d/nb_net_buy_5d_ratio(无neutral)
FEATURES_B = FEATURES_C + [
    "RSQR_20", "QTLU_20",
    "high_vol_price_ratio_20",
    "IMAX_20", "IMIN_20", "RESI_20", "CORD_20",
    "nb_ratio_change_5d", "nb_contrarian", "nb_increase_ratio_20d", "nb_new_entry",
]

EXPERIMENT_MAP = {
    "C": ("Exp-C: CORE 5 (对照组)", FEATURES_C),
    "A": ("Exp-A: CORE5+QTLU+RSQR (7因子)", FEATURES_A),
    "B": ("Exp-B: CORE5+Tier2+NB (16因子)", FEATURES_B),
}


def run_experiment(exp_key: str) -> dict:
    """运行一组LightGBM WF实验。"""
    from engines.ml_engine import MLConfig, WalkForwardTrainer

    name, features = EXPERIMENT_MAP[exp_key]
    model_dir = f"models/lgbm_phase21/exp_{exp_key.lower()}"

    print(f"\n{'='*70}")
    print(f"Running {name}")
    print(f"  Features ({len(features)}): {features}")
    print(f"{'='*70}")

    # Exp-B用Parquet加载(避免DB OOM), 其他走DB
    parquet_path = ""
    if exp_key == "B":
        pq = Path(__file__).resolve().parent.parent.parent / "backend" / "cache" / "phase21" / "features_expb_16.parquet"
        if pq.exists():
            parquet_path = str(pq)
            print(f"  Using Parquet: {parquet_path}")

    config = MLConfig(
        feature_names=features,
        parquet_path=parquet_path,
        target="excess_return_20",
        train_months=60,
        valid_months=12,
        test_months=12,
        step_months=12,
        purge_days=21,
        expanding_folds=0,  # 全部固定窗口(60月)
        data_start=date(2014, 1, 1),
        data_end=date(2026, 4, 10),
        gpu=True,
        model_dir=model_dir,
        seed=42,
    )

    engine = WalkForwardTrainer(config)

    # 显示fold结构
    folds = engine.generate_folds()
    print(f"\n  Generated {len(folds)} folds:")
    for f in folds:
        print(f"    Fold {f.fold_id}: train [{f.train_start}..{f.train_end}] "
              f"valid [{f.valid_start}..{f.valid_end}] "
              f"test [{f.test_start}..{f.test_end}]"
              f"{' [expanding]' if f.is_expanding else ''}")

    # 运行WF
    t0 = time.time()
    result = engine.run_full_walkforward()
    elapsed = time.time() - t0

    # 结果汇总
    print(f"\n  {'='*60}")
    print(f"  {name} Results ({elapsed/60:.1f} min):")
    print(f"  {'='*60}")

    print(f"\n  Overall OOS IC: {result.overall_ic:.4f}")
    print(f"  Overall OOS RankIC: {result.overall_rank_ic:.4f}")
    print(f"  Overall ICIR: {result.overall_icir:.4f}")
    print(f"  Folds used: {result.num_folds_used}/{len(result.fold_results)}")

    # Fold-by-fold
    print(f"\n  {'Fold':<6} {'Train IC':>10} {'Valid IC':>10} {'OOS IC':>10} "
          f"{'OOS RankIC':>12} {'Overfit':>10} {'Flag':>6}")
    print(f"  {'-'*66}")

    fold_data = []
    for fr in result.fold_results:
        overfit_str = f"{fr.overfit_ratio:.2f}" if fr.overfit_ratio else "N/A"
        flag = "⚠️" if fr.is_overfit else "✅"
        print(f"  F{fr.fold_id:<5} {fr.train_ic:>10.4f} {fr.valid_ic:>10.4f} "
              f"{fr.oos_ic:>10.4f} {fr.oos_rank_ic:>12.4f} {overfit_str:>10} {flag:>6}")
        fold_data.append({
            "fold_id": fr.fold_id,
            "train_ic": fr.train_ic,
            "valid_ic": fr.valid_ic,
            "oos_ic": fr.oos_ic,
            "oos_rank_ic": fr.oos_rank_ic,
            "overfit_ratio": fr.overfit_ratio,
            "is_overfit": fr.is_overfit,
        })

    # trainIC/validIC 比率检查
    train_ics = [fr.train_ic for fr in result.fold_results if fr.train_ic > 0]
    valid_ics = [fr.valid_ic for fr in result.fold_results if fr.valid_ic > 0]
    if train_ics and valid_ics:
        mean_ratio = np.mean(train_ics) / np.mean(valid_ics) if np.mean(valid_ics) > 0 else float("inf")
        print(f"\n  Mean trainIC/validIC ratio: {mean_ratio:.2f}")
        if mean_ratio > 3.0:
            print("  ❌ HARD STOP: trainIC/validIC > 3.0 (过拟合)")
        elif mean_ratio > 2.0:
            print("  ⚠️ WARNING: trainIC/validIC > 2.0")
        else:
            print("  ✅ trainIC/validIC < 2.0")

    # Feature importance (averaged across folds)
    all_imp = {}
    for fr in result.fold_results:
        if fr.feature_importance:
            for feat, imp in fr.feature_importance.items():
                all_imp.setdefault(feat, []).append(imp)

    if all_imp:
        avg_imp = {k: np.mean(v) for k, v in all_imp.items()}
        sorted_imp = sorted(avg_imp.items(), key=lambda x: -x[1])[:10]
        print("\n  Top-10 Feature Importance (avg across folds):")
        total_imp = sum(avg_imp.values())
        for feat, imp in sorted_imp:
            pct = imp / total_imp * 100 if total_imp > 0 else 0
            print(f"    {feat:<35} {imp:>10.1f} ({pct:>5.1f}%)")

    # 保存OOS预测
    if result.oos_predictions is not None and not result.oos_predictions.empty:
        out_dir = Path("cache/phase21")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"oos_predictions_exp_{exp_key.lower()}.parquet"
        result.oos_predictions.to_parquet(out_path)
        print(f"\n  OOS predictions saved: {out_path} ({len(result.oos_predictions):,} rows)")

    # 保存结果JSON
    result_dict = {
        "experiment": exp_key,
        "name": name,
        "features": features,
        "n_features": len(features),
        "overall_ic": result.overall_ic,
        "overall_rank_ic": result.overall_rank_ic,
        "overall_icir": result.overall_icir,
        "num_folds_used": result.num_folds_used,
        "elapsed_min": elapsed / 60,
        "folds": fold_data,
        "top10_features": sorted_imp if all_imp else [],
    }

    out_json = Path("cache/phase21") / f"result_exp_{exp_key.lower()}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(result_dict, f, indent=2, default=str)
    print(f"  Result JSON saved: {out_json}")

    return result_dict


def compare_results(results: list[dict]):
    """对比多组实验结果。"""
    print(f"\n{'='*70}")
    print("COMPARISON MATRIX: Layer 1 LightGBM Experiments")
    print(f"{'='*70}")
    print(f"{'Experiment':<35} {'OOS IC':>8} {'ICIR':>8} {'#Features':>10} {'Folds':>7}")
    print("-" * 70)
    for r in results:
        print(f"{r['name']:<35} {r['overall_ic']:>8.4f} {r['overall_icir']:>8.4f} "
              f"{r['n_features']:>10} {r['num_folds_used']:>7}")

    # Select best
    valid = [r for r in results if r["overall_ic"] > 0]
    if valid:
        best = max(valid, key=lambda r: r["overall_ic"])
        print(f"\n  Best: {best['name']} (OOS IC={best['overall_ic']:.4f})")
        print(f"  Selected for Layer 2: Exp-{best['experiment']}")
    else:
        print("\n  ⚠️ No experiment has positive OOS IC!")

    # G1 baseline comparison
    g1_ic = 0.067  # Step 6-H LightGBM 17-factor WF OOS IC
    for r in results:
        diff_pct = (r["overall_ic"] - g1_ic) / abs(g1_ic) * 100 if g1_ic != 0 else 0
        flag = "✅" if abs(diff_pct) < 10 else "⚠️"
        print(f"  {r['name']}: vs G1(IC=0.067) diff={diff_pct:+.1f}% {flag}")


def main():
    parser = argparse.ArgumentParser(description="Phase 2.1 Layer 1 LightGBM Experiments")
    parser.add_argument("--exp", type=str, default="all",
                        help="Experiment to run: C, A, B, or 'all' (default: all)")
    args = parser.parse_args()

    exps_to_run = list(EXPERIMENT_MAP.keys()) if args.exp.lower() == "all" else [args.exp.upper()]

    results = []
    for exp_key in exps_to_run:
        if exp_key not in EXPERIMENT_MAP:
            print(f"Unknown experiment: {exp_key}")
            continue
        r = run_experiment(exp_key)
        results.append(r)

    if len(results) > 1:
        compare_results(results)

    print("\nDone.")


if __name__ == "__main__":
    main()
