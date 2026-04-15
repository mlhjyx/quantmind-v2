"""Phase 3D Diagnostic: Why is ML OOS Sharpe catastrophically negative?

Hypothesis testing:
1. Is OOS prediction IC negative? (model overfits → anti-predictive)
2. Does SN interaction destroy ML signal? (run without SN)
3. Is the z-score normalization causing issues? (compare with/without)
4. Is there a feature contamination from high-NaN features?

Quick test: Train one fold, analyze OOS predictions in detail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = Path("cache/ml")


def main():
    import lightgbm as lgb
    from engines.ml_engine import FeaturePreprocessor
    from engines.vectorized_signal import compute_rebalance_dates
    from engines.walk_forward import WFConfig, build_exclusion_map

    # --- Load data ---
    print("Loading data...")
    from scripts.research.phase3d_ml_synthesis import (
        FEATURES_A,
        PARAMS_REG,
        load_ln_mcap_pivot,
        load_price_benchmark,
        prepare_ml_data,
    )

    price_df, bench_df = load_price_benchmark()
    ln_mcap_pivot = load_ln_mcap_pivot(price_df)
    ml_data = prepare_ml_data(FEATURES_A, price_df, bench_df)

    actual_features = [f for f in FEATURES_A if f in ml_data.columns]
    print(f"Features ({len(actual_features)}): {actual_features}")

    # --- Use Fold 0 for diagnostic ---
    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    all_dates = sorted(ml_data["trade_date"].unique())
    total_days = len(all_dates)

    # Replicate fold 0 split
    test_size = wf_config.test_window
    train_size = wf_config.train_window
    gap = wf_config.gap

    fold_end = total_days - (wf_config.n_splits - 1) * test_size
    test_start_idx = fold_end - test_size
    train_end_idx = test_start_idx - gap
    train_start_idx = train_end_idx - train_size

    train_dates_list = all_dates[train_start_idx:train_end_idx]
    test_dates_list = all_dates[test_start_idx:fold_end]
    print(f"\nFold 0: Train {train_dates_list[0]}..{train_dates_list[-1]} ({len(train_dates_list)}d)")
    print(f"        Test  {test_dates_list[0]}..{test_dates_list[-1]} ({len(test_dates_list)}d)")

    # Split train data
    train_set = set(train_dates_list)
    test_set = set(test_dates_list)

    train_full = ml_data[ml_data["trade_date"].isin(train_set)].copy()

    # Purge last 16 days
    train_unique_dates = sorted(train_full["trade_date"].unique())
    purge_days = 16
    if len(train_unique_dates) > purge_days:
        purge_cutoff = train_unique_dates[-(purge_days)]
        train_full = train_full[train_full["trade_date"] < purge_cutoff]
        train_unique_dates = sorted(train_full["trade_date"].unique())

    # 80/20 split
    split_idx = int(len(train_unique_dates) * 0.8)
    train_inner_dates = set(train_unique_dates[:split_idx])
    valid_dates = set(train_unique_dates[split_idx:])

    train_inner = train_full[train_full["trade_date"].isin(train_inner_dates)]
    valid_data = train_full[train_full["trade_date"].isin(valid_dates)]

    print(f"  Train inner: {len(train_inner):,}, Valid: {len(valid_data):,}")

    # --- Preprocess ---
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_inner, actual_features)

    train_processed = preprocessor.transform(train_inner)
    valid_processed = preprocessor.transform(valid_data)

    X_train = train_processed[actual_features].values.astype(np.float32)
    y_train = train_processed["excess_return_20"].values.astype(np.float32)
    X_valid = valid_processed[actual_features].values.astype(np.float32)
    y_valid = valid_processed["excess_return_20"].values.astype(np.float32)

    # --- Train ---
    print("\nTraining LightGBM...")
    params = PARAMS_REG.copy()
    train_ds = lgb.Dataset(X_train, label=y_train, feature_name=actual_features)
    valid_ds = lgb.Dataset(X_valid, label=y_valid, reference=train_ds)

    callbacks = [
        lgb.early_stopping(50, verbose=True),
        lgb.log_evaluation(50),
    ]
    model = lgb.train(
        params, train_ds, num_boost_round=500,
        valid_sets=[valid_ds], valid_names=["valid"],
        callbacks=callbacks,
    )
    best_iter = model.best_iteration

    # Train/Valid IC
    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)
    train_ic, _ = sp_stats.spearmanr(train_pred, y_train)
    valid_ic, _ = sp_stats.spearmanr(valid_pred, y_valid)
    print(f"\nTrain IC: {train_ic:.4f}, Valid IC: {valid_ic:.4f}, best_iter: {best_iter}")

    # --- OOS Prediction Analysis ---
    print("\n" + "=" * 60)
    print("OOS PREDICTION DIAGNOSTIC")
    print("=" * 60)

    test_data = ml_data[ml_data["trade_date"].isin(test_set)].copy()
    test_processed = preprocessor.transform(test_data)
    X_test = test_processed[actual_features].values.astype(np.float32)
    y_test = test_processed["excess_return_20"].values.astype(np.float32)
    test_pred = model.predict(X_test, num_iteration=best_iter)

    # Overall OOS IC
    valid_mask = ~np.isnan(y_test)
    oos_ic, oos_pval = sp_stats.spearmanr(test_pred[valid_mask], y_test[valid_mask])
    print(f"\n1. Overall OOS IC: {oos_ic:.4f} (p={oos_pval:.4f})")

    # Per-month OOS IC
    test_processed_with_pred = test_processed.copy()
    test_processed_with_pred["pred"] = test_pred
    test_processed_with_pred["month"] = pd.to_datetime(
        test_processed_with_pred["trade_date"].astype(str)
    ).dt.to_period("M")

    print("\n2. Per-month OOS IC:")
    monthly_ics = []
    for month, grp in test_processed_with_pred.groupby("month"):
        valid = ~grp["excess_return_20"].isna()
        if valid.sum() < 50:
            continue
        ic, _ = sp_stats.spearmanr(
            grp.loc[valid, "pred"].values,
            grp.loc[valid, "excess_return_20"].values,
        )
        monthly_ics.append(ic)
        print(f"  {month}: IC={ic:.4f} (n={valid.sum():,})")

    print(f"\n  Mean monthly IC: {np.mean(monthly_ics):.4f}")
    print(f"  IC>0 months: {sum(1 for x in monthly_ics if x > 0)}/{len(monthly_ics)}")

    # --- Diagnostic 3: Prediction distribution ---
    print("\n3. Prediction distribution:")
    print(f"  Mean:  {test_pred.mean():.6f}")
    print(f"  Std:   {test_pred.std():.6f}")
    print(f"  Min:   {test_pred.min():.6f}")
    print(f"  Max:   {test_pred.max():.6f}")
    print(f"  Range: {test_pred.max() - test_pred.min():.6f}")

    # --- Diagnostic 4: Top-20 vs Bottom-20 analysis ---
    print("\n4. Top-20 vs Bottom-20 stock analysis (per rebalance date):")
    all_trading_days = sorted(price_df["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(all_trading_days, "monthly")
    exclusion_map = build_exclusion_map(price_df)

    top20_returns = []
    bot20_returns = []

    for rd in rebal_dates:
        if rd not in test_set:
            continue

        day_data = test_data[test_data["trade_date"] == rd].copy()
        if day_data.empty:
            # Find closest date
            closest = test_data[test_data["trade_date"] <= rd]["trade_date"].max()
            if pd.isna(closest):
                continue
            day_data = test_data[test_data["trade_date"] == closest].copy()

        exclude = exclusion_map.get(day_data["trade_date"].iloc[0], set())
        day_data = day_data[~day_data["code"].isin(exclude)]

        if len(day_data) < 40:
            continue

        day_processed = preprocessor.transform(day_data)
        X_day = day_processed[actual_features].values.astype(np.float32)
        preds = model.predict(X_day, num_iteration=best_iter)

        scores = pd.Series(preds, index=day_processed["code"].values)
        actual_ret = pd.Series(
            day_processed["excess_return_20"].values,
            index=day_processed["code"].values,
        )

        # Without z-score, without SN
        top20_raw = scores.nlargest(20).index
        bot20_raw = scores.nsmallest(20).index
        top_ret = actual_ret.loc[top20_raw].mean()
        bot_ret = actual_ret.loc[bot20_raw].mean()

        # With z-score + SN
        s_std = scores.std()
        if s_std > 1e-8:
            scores_z = (scores - scores.mean()) / s_std
        else:
            scores_z = scores.copy()

        if ln_mcap_pivot is not None and rd in ln_mcap_pivot.index:
            mcap_row = ln_mcap_pivot.loc[rd]
            common = scores_z.index.intersection(mcap_row.dropna().index)
            if len(common) > 0:
                mcap_vals = mcap_row[common]
                mcap_z = (mcap_vals - mcap_vals.mean()) / max(mcap_vals.std(), 1e-8)
                adj_scores = scores_z[common] - 0.50 * mcap_z
                top20_sn = adj_scores.nlargest(20).index
            else:
                top20_sn = scores_z.nlargest(20).index
        else:
            top20_sn = scores_z.nlargest(20).index

        top_ret_sn = actual_ret.reindex(top20_sn).mean()

        top20_returns.append(top_ret)
        bot20_returns.append(bot_ret)

        ic_day, _ = sp_stats.spearmanr(preds, day_processed["excess_return_20"].values)

        # Market cap of selected stocks
        if ln_mcap_pivot is not None and rd in ln_mcap_pivot.index:
            mcap_row = ln_mcap_pivot.loc[rd]
            top20_mcap = np.exp(mcap_row.reindex(top20_raw).dropna()).median() / 1e8
            top20_sn_mcap = np.exp(mcap_row.reindex(top20_sn).dropna()).median() / 1e8
        else:
            top20_mcap = 0
            top20_sn_mcap = 0

        print(f"  {rd}: IC={ic_day:+.4f} | "
              f"Top20_ret={top_ret:+.4f} Bot20_ret={bot_ret:+.4f} | "
              f"Top20+SN_ret={top_ret_sn:+.4f} | "
              f"MCap(raw)={top20_mcap:.0f}亿 MCap(SN)={top20_sn_mcap:.0f}亿")

    if top20_returns:
        print(f"\n  Mean Top20 return (no SN): {np.mean(top20_returns):+.4f}")
        print(f"  Mean Bot20 return (no SN): {np.mean(bot20_returns):+.4f}")
        print(f"  L/S spread: {np.mean(top20_returns) - np.mean(bot20_returns):+.4f}")

    # --- Diagnostic 5: Feature NaN impact ---
    print("\n5. Feature NaN rates in OOS data:")
    for feat in actual_features:
        nan_pct = test_data[feat].isna().mean() * 100
        fill_val = 0.0  # After FeaturePreprocessor fill
        # Check what z-score the fill value maps to
        mean_val, std_val = preprocessor._zscore_params.get(feat, (0.0, 1.0))
        median_val, mad_val = preprocessor._mad_params.get(feat, (0.0, 1.0))
        fill_zscore = (fill_val - mean_val) / std_val
        print(f"  {feat:30s}: NaN={nan_pct:5.1f}% → fill=0 → zscore={fill_zscore:+.3f}")

    # --- Diagnostic 6: Without SN ---
    print("\n6. Model WITHOUT SN (pure ML ranking):")
    # Already computed above as top20_returns (raw predictions, no SN)
    if top20_returns:
        avg_top = np.mean(top20_returns)
        avg_bot = np.mean(bot20_returns)
        print(f"  Avg Top-20 excess return: {avg_top:+.4f}")
        print(f"  Avg Bot-20 excess return: {avg_bot:+.4f}")
        print("  If positive spread → ML has value but SN kills it")
        print("  If negative spread → ML prediction itself is anti-predictive")


if __name__ == "__main__":
    main()
