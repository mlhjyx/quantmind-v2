"""Phase 3E Track B: Multi-model ML exploration.

Reuses phase3d's WF infrastructure (data loading, preprocessing, signal_func pattern)
but swaps in different model architectures: XGBoost, CatBoost, TabNet, LSTM, Stacking.

Usage:
    python scripts/research/phase3e_ml_models.py --model xgboost
    python scripts/research/phase3e_ml_models.py --model catboost
    python scripts/research/phase3e_ml_models.py --model tabnet
    python scripts/research/phase3e_ml_models.py --model lstm
    python scripts/research/phase3e_ml_models.py --model stacking
    python scripts/research/phase3e_ml_models.py --all-trees    # XGB + CatBoost + LightGBM
    python scripts/research/phase3e_ml_models.py --compare       # Print comparison table

Architecture:
    Each model implements a signal_func factory (like make_lgbm_signal_func in phase3d).
    All share: WFConfig 5-fold, SimpleBacktester, T+1, SN b=0.50, Top-20 monthly.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

# Reuse phase3d infrastructure
from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.vectorized_signal import compute_rebalance_dates  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    build_exclusion_map,
)
from phase3d_ml_synthesis import (  # noqa: E402
    FEATURES_A,
    PARAMS_REG,
    FoldDiagnostics,
    _compute_ic,
    load_ln_mcap_pivot,
    load_price_benchmark,
    prepare_ml_data,
)

# ============================================================
# Config
# ============================================================

CACHE_DIR = Path("cache/phase3e_ml")
RESULTS_FILE = CACHE_DIR / "ml_model_comparison.json"

WF_CONFIG = WFConfig(
    n_splits=5,
    train_window=750,
    test_window=250,
    gap=5,
)

BACKTEST_CONFIG = BacktestConfig(
    initial_capital=1_000_000,
    commission_rate=0.0000854,
    stamp_tax_rate=0.0005,
    historical_stamp_tax=True,
    transfer_fee_rate=0.00001,
    slippage_mode="volume_impact",
)

TOP_N = 20
SN_BETA = 0.50
REBALANCE_FREQ = "monthly"
EXTRA_PURGE_DAYS = 16


# ============================================================
# Generic Model Signal Function Factory
# ============================================================

def _make_generic_signal_func(
    ml_data: pd.DataFrame,
    feature_names: list[str],
    price_data: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame | None,
    model_name: str,
    train_predict_fn,
    fold_diagnostics: list[FoldDiagnostics] | None = None,
):
    """Generic signal_func factory — delegates model training/prediction to train_predict_fn.

    train_predict_fn signature:
        (X_train, y_train, X_valid, y_valid, actual_features, fold_idx)
        -> (model_predict_fn, best_iter, extra_info)

    where model_predict_fn(X) -> np.ndarray of predictions
    """
    from engines.signal_engine import PortfolioBuilder, SignalConfig

    exclusion_map = build_exclusion_map(price_data)
    all_trading_days = sorted(price_data["trade_date"].unique())
    all_rebal_dates = compute_rebalance_dates(all_trading_days, REBALANCE_FREQ)

    se_config = SignalConfig(
        factor_names=feature_names[:4],
        top_n=TOP_N,
        weight_method="equal",
        rebalance_freq=REBALANCE_FREQ,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
    )
    builder = PortfolioBuilder(se_config)
    actual_features = [f for f in feature_names if f in ml_data.columns]
    fold_counter = [0]

    def signal_func(
        train_dates: list[date], test_dates: list[date]
    ) -> dict[date, dict[str, float]]:
        fold_counter[0] += 1
        fold_idx = fold_counter[0]
        t0 = time.time()
        print(f"\n  === [{model_name}] Fold {fold_idx} ===")
        print(f"  Train: {train_dates[0]}..{train_dates[-1]} ({len(train_dates)}d)")
        print(f"  Test:  {test_dates[0]}..{test_dates[-1]} ({len(test_dates)}d)")

        train_set = set(train_dates)
        test_set = set(test_dates)

        # 1. Slice + purge
        train_full = ml_data[ml_data["trade_date"].isin(train_set)].copy()
        train_unique_dates = sorted(train_full["trade_date"].unique())
        if len(train_unique_dates) > EXTRA_PURGE_DAYS + 50:
            purge_cutoff = train_unique_dates[-(EXTRA_PURGE_DAYS + 1)]
            train_full = train_full[train_full["trade_date"] <= purge_cutoff]
            train_unique_dates = sorted(train_full["trade_date"].unique())

        # 2. 80/20 train/valid split
        n = len(train_unique_dates)
        split_idx = int(n * 0.8)
        train_inner_dates = set(train_unique_dates[:split_idx])
        valid_dates = set(train_unique_dates[split_idx:])

        train_inner = train_full[train_full["trade_date"].isin(train_inner_dates)]
        valid_data = train_full[train_full["trade_date"].isin(valid_dates)]

        if len(train_inner) < 5000 or len(valid_data) < 1000:
            print(f"  SKIP: insufficient data (train={len(train_inner)}, valid={len(valid_data)})")
            return {}

        # 3. Preprocess (fit on train_inner only)
        from engines.ml_engine import FeaturePreprocessor
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(train_inner, actual_features)

        train_processed = preprocessor.transform(train_inner)
        valid_processed = preprocessor.transform(valid_data)

        X_train = train_processed[actual_features].values.astype(np.float32)
        y_train = train_processed["excess_return_20"].values.astype(np.float32)
        X_valid = valid_processed[actual_features].values.astype(np.float32)
        y_valid = valid_processed["excess_return_20"].values.astype(np.float32)

        print(f"  Train: {len(X_train):,}, Valid: {len(X_valid):,}, Features: {len(actual_features)}")

        # 4. Train model (delegated)
        predict_fn, best_iter, extra = train_predict_fn(
            X_train, y_train, X_valid, y_valid, actual_features, fold_idx
        )

        # 5. Diagnostics
        train_pred = predict_fn(X_train)
        valid_pred = predict_fn(X_valid)
        train_ic = _compute_ic(train_pred, y_train)
        valid_ic = _compute_ic(valid_pred, y_valid)

        elapsed = time.time() - t0
        print(f"  Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f}, "
              f"best_iter={best_iter}, {elapsed:.1f}s")

        if fold_diagnostics is not None:
            fold_diagnostics.append(FoldDiagnostics(
                fold_idx=fold_idx,
                train_samples=len(X_train),
                valid_samples=len(X_valid),
                train_ic=train_ic,
                valid_ic=valid_ic,
                best_iter=best_iter,
                feature_importance=extra.get("feature_importance", {}),
                elapsed_s=elapsed,
            ))

        # 6. Generate signals for test period
        fold_rebal = [rd for rd in all_rebal_dates if rd in test_set]
        if not fold_rebal:
            return {}

        test_factor_data = ml_data[ml_data["trade_date"].isin(test_set)].copy()
        target_portfolios: dict[date, dict[str, float]] = {}

        for rd in fold_rebal:
            day_data = test_factor_data[test_factor_data["trade_date"] <= rd]
            if day_data.empty:
                continue
            latest_date = day_data["trade_date"].max()
            day_data = day_data[day_data["trade_date"] == latest_date].copy()

            exclude = exclusion_map.get(latest_date, set())
            day_data = day_data[~day_data["code"].isin(exclude)]
            if len(day_data) < TOP_N:
                continue

            day_processed = preprocessor.transform(day_data)
            X_day = day_processed[actual_features].values.astype(np.float32)
            preds = predict_fn(X_day)

            # Z-score normalize
            scores = pd.Series(preds, index=day_processed["code"].values)
            s_std = scores.std()
            if s_std > 1e-8:
                scores = (scores - scores.mean()) / s_std
            scores = scores.sort_values(ascending=False)

            # SN adjustment
            if SN_BETA > 0 and ln_mcap_pivot is not None and latest_date in ln_mcap_pivot.index:
                from engines.size_neutral import apply_size_neutral
                scores = apply_size_neutral(scores, ln_mcap_pivot.loc[latest_date], SN_BETA)

            weights = builder.build(scores, pd.Series(dtype=str))
            if weights:
                target_portfolios[rd] = weights

        print(f"  Generated {len(target_portfolios)} signals")
        return target_portfolios

    return signal_func


# ============================================================
# Model-Specific train_predict_fn Implementations
# ============================================================

def _xgboost_train(X_train, y_train, X_valid, y_valid, features, fold_idx):
    """XGBoost regression with GPU acceleration."""
    import xgboost as xgb

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=features)
    dvalid = xgb.DMatrix(X_valid, label=y_valid, feature_names=features)

    params = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "max_depth": 6,
        "learning_rate": 0.05,
        "reg_alpha": 1.0,
        "reg_lambda": 5.0,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "tree_method": "hist",
        "device": "cuda",
        "seed": 42,
        "verbosity": 0,
    }

    model = xgb.train(
        params, dtrain,
        num_boost_round=500,
        evals=[(dvalid, "valid")],
        early_stopping_rounds=50,
        verbose_eval=False,
    )

    best_iter = model.best_iteration
    fi = model.get_score(importance_type="gain")

    def predict(X):
        dm = xgb.DMatrix(X, feature_names=features)
        return model.predict(dm, iteration_range=(0, best_iter))

    return predict, best_iter, {"feature_importance": fi}


def _catboost_train(X_train, y_train, X_valid, y_valid, features, fold_idx):
    """CatBoost regression with Ordered Boosting."""
    from catboost import CatBoostRegressor, Pool

    train_pool = Pool(X_train, y_train, feature_names=features)
    valid_pool = Pool(X_valid, y_valid, feature_names=features)

    model = CatBoostRegressor(
        iterations=500,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=5.0,
        task_type="GPU",
        random_seed=42,
        verbose=0,
        early_stopping_rounds=50,
        eval_metric="RMSE",
    )
    model.fit(train_pool, eval_set=valid_pool, verbose=0)

    best_iter = model.get_best_iteration()
    fi_vals = model.get_feature_importance()
    fi = dict(zip(features, [float(v) for v in fi_vals]))

    def predict(X):
        return model.predict(X)

    return predict, best_iter, {"feature_importance": fi}


def _tabnet_train(X_train, y_train, X_valid, y_valid, features, fold_idx):
    """TabNet with attention-based feature selection."""
    from pytorch_tabnet.tab_model import TabNetRegressor

    # Replace NaN with 0 for TabNet
    X_train = np.nan_to_num(X_train, nan=0.0)
    X_valid = np.nan_to_num(X_valid, nan=0.0)
    y_train = y_train.reshape(-1, 1)
    y_valid = y_valid.reshape(-1, 1)

    model = TabNetRegressor(
        n_d=32, n_a=32, n_steps=5, gamma=1.5,
        n_independent=2, n_shared=2,
        seed=42,
        verbose=0,
        device_name="cuda",
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_valid, y_valid)],
        eval_metric=["rmse"],
        max_epochs=200,
        patience=30,
        batch_size=4096,
        virtual_batch_size=256,
    )

    best_epoch = model.best_epoch if hasattr(model, "best_epoch") else 0
    fi = dict(zip(features, [float(v) for v in model.feature_importances_]))

    def predict(X):
        X = np.nan_to_num(X, nan=0.0)
        return model.predict(X).flatten()

    return predict, best_epoch, {"feature_importance": fi}


def _lstm_train(X_train, y_train, X_valid, y_valid, features, fold_idx):
    """LSTM: treats each sample as a cross-sectional snapshot.

    Note: For true temporal LSTM, we'd need sequential data per stock.
    This version uses a simple MLP-like approach with LSTM layer to capture
    feature interactions, not temporal dynamics.
    For temporal version, we'd need to restructure data as
    (N_stocks, T_lookback, N_features) per day.
    """
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    # Wider MLP to better utilize GPU
    class FactorMLP(nn.Module):
        def __init__(self, n_features: int, hidden: int = 256):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_features, hidden),
                nn.BatchNorm1d(hidden),
                nn.ReLU(),
                nn.Dropout(0.3),
                nn.Linear(hidden, hidden // 2),
                nn.BatchNorm1d(hidden // 2),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(hidden // 2, hidden // 4),
                nn.ReLU(),
                nn.Linear(hidden // 4, 1),
            )

        def forward(self, x):
            return self.net(x).squeeze(-1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    n_features = X_train.shape[1]

    # Replace NaN
    X_tr = np.nan_to_num(X_train, nan=0.0)
    X_va = np.nan_to_num(X_valid, nan=0.0)

    train_ds = TensorDataset(
        torch.FloatTensor(X_tr),
        torch.FloatTensor(y_train),
    )
    valid_ds = TensorDataset(
        torch.FloatTensor(X_va),
        torch.FloatTensor(y_valid),
    )
    train_loader = DataLoader(train_ds, batch_size=32768, shuffle=True,
                              pin_memory=True, num_workers=0)
    valid_loader = DataLoader(valid_ds, batch_size=65536, shuffle=False,
                              pin_memory=True, num_workers=0)

    model = FactorMLP(n_features).to(device)
    # torch.compile requires Triton (Linux only), skip on Windows
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=1e-3)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)

    best_valid_loss = float("inf")
    best_state = None
    patience_counter = 0
    max_patience = 30

    for epoch in range(200):
        # Train
        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
            loss = nn.MSELoss()(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        # Validate
        model.eval()
        val_losses = []
        with torch.no_grad():
            for xb, yb in valid_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                val_losses.append(nn.MSELoss()(pred, yb).item())
        val_loss = np.mean(val_losses)
        scheduler.step(val_loss)

        if val_loss < best_valid_loss:
            best_valid_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= max_patience:
                break

    best_epoch = epoch - max_patience + 1 if patience_counter >= max_patience else epoch

    # Load best state
    model.load_state_dict(best_state)
    model.eval()

    def predict(X):
        X = np.nan_to_num(X, nan=0.0)
        with torch.no_grad():
            t = torch.FloatTensor(X).to(device)
            return model(t).cpu().numpy()

    return predict, best_epoch, {"feature_importance": {}}


def _lightgbm_train(X_train, y_train, X_valid, y_valid, features, fold_idx):
    """LightGBM regression (baseline for comparison)."""
    import lightgbm as lgb

    train_ds = lgb.Dataset(X_train, label=y_train, feature_name=features)
    valid_ds = lgb.Dataset(X_valid, label=y_valid, reference=train_ds)

    params = PARAMS_REG.copy()

    callbacks = [
        lgb.early_stopping(stopping_rounds=50, verbose=False),
        lgb.log_evaluation(period=0),
    ]
    model = lgb.train(
        params, train_ds,
        num_boost_round=500,
        valid_sets=[valid_ds],
        valid_names=["valid"],
        callbacks=callbacks,
    )
    best_iter = model.best_iteration
    importance = model.feature_importance(importance_type="gain")
    fi = dict(zip(features, [float(v) for v in importance]))

    def predict(X):
        return model.predict(X, num_iteration=best_iter)

    return predict, best_iter, {"feature_importance": fi}


MODEL_REGISTRY = {
    "xgboost": ("XGBoost Regression", _xgboost_train),
    "catboost": ("CatBoost Ordered Boosting", _catboost_train),
    "tabnet": ("TabNet Attention", _tabnet_train),
    "lstm": ("Neural Network (MLP)", _lstm_train),
    "lightgbm": ("LightGBM Baseline", _lightgbm_train),
}


# ============================================================
# Stacking Ensemble
# ============================================================

def _make_stacking_signal_func(
    ml_data, feature_names, price_data, ln_mcap_pivot,
    base_models=("lightgbm", "xgboost", "catboost"),
    fold_diagnostics=None,
):
    """Stacking: train multiple base models, average their z-scored predictions."""
    from engines.signal_engine import PortfolioBuilder, SignalConfig

    exclusion_map = build_exclusion_map(price_data)
    all_trading_days = sorted(price_data["trade_date"].unique())
    all_rebal_dates = compute_rebalance_dates(all_trading_days, REBALANCE_FREQ)

    se_config = SignalConfig(
        factor_names=feature_names[:4], top_n=TOP_N,
        weight_method="equal", rebalance_freq=REBALANCE_FREQ,
        industry_cap=1.0, turnover_cap=1.0, cash_buffer=0.0,
    )
    builder = PortfolioBuilder(se_config)
    actual_features = [f for f in feature_names if f in ml_data.columns]
    fold_counter = [0]

    def signal_func(train_dates, test_dates):
        fold_counter[0] += 1
        fold_idx = fold_counter[0]
        t0 = time.time()
        print(f"\n  === [Stacking] Fold {fold_idx} ===")

        train_set, test_set = set(train_dates), set(test_dates)

        # Same data prep as generic
        train_full = ml_data[ml_data["trade_date"].isin(train_set)].copy()
        train_unique = sorted(train_full["trade_date"].unique())
        if len(train_unique) > EXTRA_PURGE_DAYS + 50:
            train_full = train_full[train_full["trade_date"] <= train_unique[-(EXTRA_PURGE_DAYS + 1)]]
            train_unique = sorted(train_full["trade_date"].unique())

        split_idx = int(len(train_unique) * 0.8)
        train_inner = train_full[train_full["trade_date"].isin(set(train_unique[:split_idx]))]
        valid_data = train_full[train_full["trade_date"].isin(set(train_unique[split_idx:]))]

        from engines.ml_engine import FeaturePreprocessor
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(train_inner, actual_features)
        train_p = preprocessor.transform(train_inner)
        valid_p = preprocessor.transform(valid_data)

        X_tr = train_p[actual_features].values.astype(np.float32)
        y_tr = train_p["excess_return_20"].values.astype(np.float32)
        X_va = valid_p[actual_features].values.astype(np.float32)
        y_va = valid_p["excess_return_20"].values.astype(np.float32)

        # Train all base models
        predict_fns = []
        for mname in base_models:
            _, train_fn = MODEL_REGISTRY[mname]
            print(f"  Training {mname}...", end="", flush=True)
            pred_fn, bi, _ = train_fn(X_tr, y_tr, X_va, y_va, actual_features, fold_idx)
            pred_fn_ic = _compute_ic(pred_fn(X_va), y_va)
            print(f" valid_IC={pred_fn_ic:.4f}, iter={bi}")
            predict_fns.append(pred_fn)

        elapsed = time.time() - t0
        print(f"  Stacking trained in {elapsed:.1f}s")

        # Generate signals: average z-scored predictions
        fold_rebal = [rd for rd in all_rebal_dates if rd in test_set]
        test_data = ml_data[ml_data["trade_date"].isin(test_set)].copy()
        target_portfolios = {}

        for rd in fold_rebal:
            day_data = test_data[test_data["trade_date"] <= rd]
            if day_data.empty:
                continue
            latest = day_data["trade_date"].max()
            day_data = day_data[day_data["trade_date"] == latest].copy()
            day_data = day_data[~day_data["code"].isin(exclusion_map.get(latest, set()))]
            if len(day_data) < TOP_N:
                continue

            day_p = preprocessor.transform(day_data)
            X_day = day_p[actual_features].values.astype(np.float32)

            # Average z-scored predictions from all models
            all_preds = []
            for pfn in predict_fns:
                p = pfn(X_day)
                std = np.std(p)
                if std > 1e-8:
                    p = (p - np.mean(p)) / std
                all_preds.append(p)
            avg_pred = np.mean(all_preds, axis=0)

            scores = pd.Series(avg_pred, index=day_p["code"].values)
            s_std = scores.std()
            if s_std > 1e-8:
                scores = (scores - scores.mean()) / s_std
            scores = scores.sort_values(ascending=False)

            if SN_BETA > 0 and ln_mcap_pivot is not None and latest in ln_mcap_pivot.index:
                from engines.size_neutral import apply_size_neutral
                scores = apply_size_neutral(scores, ln_mcap_pivot.loc[latest], SN_BETA)

            weights = builder.build(scores, pd.Series(dtype=str))
            if weights:
                target_portfolios[rd] = weights

        print(f"  Generated {len(target_portfolios)} signals")
        return target_portfolios

    return signal_func


# ============================================================
# Runner
# ============================================================

def run_experiment(
    model_key: str,
    ml_data: pd.DataFrame,
    feature_names: list[str],
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame,
) -> dict:
    """Run a single model experiment through WF engine."""
    print(f"\n{'='*70}")
    print(f"Experiment: {model_key}")
    print(f"{'='*70}")

    fold_diags: list[FoldDiagnostics] = []

    if model_key == "stacking":
        signal_func = _make_stacking_signal_func(
            ml_data, feature_names, price_df, ln_mcap_pivot,
            fold_diagnostics=fold_diags,
        )
    else:
        model_label, train_fn = MODEL_REGISTRY[model_key]
        signal_func = _make_generic_signal_func(
            ml_data, feature_names, price_df, ln_mcap_pivot,
            model_name=model_label,
            train_predict_fn=train_fn,
            fold_diagnostics=fold_diags,
        )

    # Run WF
    wf_engine = WalkForwardEngine(WF_CONFIG, backtest_config=BACKTEST_CONFIG)
    t0 = time.time()
    wf_result = wf_engine.run(
        signal_func=signal_func,
        price_data=price_df,
        benchmark_data=bench_df,
    )
    elapsed = time.time() - t0

    # Extract results
    result = {
        "model": model_key,
        "oos_sharpe": round(wf_result.combined_oos_sharpe, 4),
        "oos_mdd": round(wf_result.combined_oos_mdd, 4),
        "oos_annual_return": round(wf_result.combined_oos_annual_return, 4),
        "per_fold_sharpe": [round(f.oos_sharpe, 4) for f in wf_result.fold_results],
        "neg_folds": sum(1 for f in wf_result.fold_results if f.oos_sharpe < 0),
        "elapsed_s": round(elapsed, 1),
        "fold_diagnostics": [
            {
                "fold": d.fold_idx,
                "train_ic": round(d.train_ic, 4),
                "valid_ic": round(d.valid_ic, 4),
                "best_iter": d.best_iter,
            }
            for d in fold_diags
        ],
    }

    # Print summary
    print(f"\n{'='*70}")
    print(f"Result: {model_key}")
    print(f"  OOS Sharpe: {result['oos_sharpe']}")
    print(f"  OOS MDD: {result['oos_mdd']}")
    print(f"  Per-fold: {result['per_fold_sharpe']}")
    print(f"  Neg folds: {result['neg_folds']}/5")
    print(f"  Time: {elapsed:.0f}s")
    print(f"{'='*70}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Phase 3E: Multi-model ML exploration")
    parser.add_argument("--model", choices=list(MODEL_REGISTRY.keys()) + ["stacking"],
                        help="Model to run")
    parser.add_argument("--all-trees", action="store_true",
                        help="Run all tree models (LightGBM, XGBoost, CatBoost)")
    parser.add_argument("--all", action="store_true", help="Run all models")
    parser.add_argument("--compare", action="store_true", help="Print comparison table")
    args = parser.parse_args()

    if args.compare:
        if RESULTS_FILE.exists():
            with open(RESULTS_FILE) as f:
                results = json.load(f)
            print(f"\n{'Model':<20} {'Sharpe':>8} {'MDD':>8} {'NegFolds':>9} {'Time':>8}")
            print("-" * 55)
            for r in sorted(results, key=lambda x: -x["oos_sharpe"]):
                print(f"{r['model']:<20} {r['oos_sharpe']:>8.4f} {r['oos_mdd']:>8.4f} "
                      f"{r['neg_folds']:>5}/5    {r['elapsed_s']:>6.0f}s")
            print("\nBaseline (equal-weight): Sharpe=0.8659, MDD=-0.1391")
        else:
            print("No results yet. Run experiments first.")
        return

    # Determine which models to run
    if args.all:
        models = list(MODEL_REGISTRY.keys()) + ["stacking"]
    elif args.all_trees:
        models = ["lightgbm", "xgboost", "catboost"]
    elif args.model:
        models = [args.model]
    else:
        parser.print_help()
        return

    # Load shared data
    print("Loading shared data...")
    price_df, bench_df = load_price_benchmark()
    ml_data = prepare_ml_data(FEATURES_A, price_df, bench_df)
    ln_mcap_pivot = load_ln_mcap_pivot(price_df)
    print(f"Data ready: {len(ml_data):,} rows\n")

    # Load existing results
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            all_results = json.load(f)

    # Run experiments
    for model_key in models:
        try:
            result = run_experiment(
                model_key, ml_data, FEATURES_A,
                price_df, bench_df, ln_mcap_pivot,
            )
            # Update or append result
            all_results = [r for r in all_results if r["model"] != model_key]
            all_results.append(result)

            # Save incrementally
            with open(RESULTS_FILE, "w") as f:
                json.dump(all_results, f, indent=2)
            print(f"\nSaved to {RESULTS_FILE}")

        except Exception as e:
            print(f"\n!!! {model_key} FAILED: {e}")
            import traceback
            traceback.print_exc()
            continue

        gc.collect()

    # Final comparison
    print(f"\n{'='*70}")
    print("FINAL COMPARISON")
    print(f"{'='*70}")
    print(f"{'Model':<20} {'Sharpe':>8} {'MDD':>8} {'NegFolds':>9}")
    print("-" * 45)
    for r in sorted(all_results, key=lambda x: -x["oos_sharpe"]):
        print(f"{r['model']:<20} {r['oos_sharpe']:>8.4f} {r['oos_mdd']:>8.4f} {r['neg_folds']:>5}/5")
    print(f"{'equal-weight':<20} {'0.8659':>8} {'-0.1391':>8} {'0':>5}/5")


if __name__ == "__main__":
    main()
