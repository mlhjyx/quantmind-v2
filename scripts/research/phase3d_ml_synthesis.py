"""Phase 3D: ML Synthesis — LightGBM Walk-Forward experiments.

Goal: Break equal-weight alpha ceiling (OOS Sharpe=0.8659) using LightGBM
with progressively larger feature sets.

Architecture: Train LightGBM inside a signal_func callback that plugs into
the SAME WalkForwardEngine used for the equal-weight baseline. This ensures
identical folds, identical backtest engine, identical NAV chain-linking.

Usage:
    python scripts/research/phase3d_ml_synthesis.py --feature-set A --mode regression
    python scripts/research/phase3d_ml_synthesis.py --feature-set B --mode lambdarank
    python scripts/research/phase3d_ml_synthesis.py --all
    python scripts/research/phase3d_ml_synthesis.py --verify  # Check factor availability only
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.vectorized_signal import compute_rebalance_dates  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    build_exclusion_map,
)

# ============================================================
# Feature Set Definitions
# ============================================================

# Feature-A: CORE4 + 7 independent factors (low corr with CORE4)
FEATURES_A = [
    "turnover_mean_20",   # CORE4, direction=-1
    "volatility_20",      # CORE4, direction=-1
    "bp_ratio",           # CORE4, direction=+1
    "dv_ttm",             # CORE4, direction=+1
    "CORD5",              # Alpha158 CORD5, corr=0.13
    "RSQR_20",            # Alpha158, corr=0.15
    "IMIN_20",            # Alpha158, corr=0.13
    "a158_cord30",        # Alpha158 CORD20, corr=0.23
    "reversal_60",        # Reserve, corr=0.30
    "price_level_factor", # Reserve Tier1, corr=0.30
    "price_volume_corr_20",  # Reserve, corr=0.28, perfect monotonicity
]

# Feature-B: All significant factors (deduplicated)
# Removed: momentum_5 (mirror reversal_5), momentum_10 (mirror reversal_10),
#   mf_divergence (INVALIDATED), ivol_20 (corr=0.967 with volatility_20)
FEATURES_B = [
    # CORE4
    "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",
    # Reserve Tier 1
    "reversal_20", "reversal_60", "reversal_5",
    "price_level_factor", "price_volume_corr_20",
    "ep_ratio", "ln_market_cap", "amihud_20",
    # Microstructure + Liquidity
    "turnover_surge_ratio", "relative_volume_20",
    "gap_frequency_20", "vwap_bias_1d", "rsrs_raw_18",
    "large_order_ratio",
    # Volatility
    "atr_norm_20",
    # Alpha158 Six
    "RSQR_20", "QTLU_20", "IMAX_20", "IMIN_20", "CORD_20", "RESI_20",
    # a158 computed
    "a158_cord30", "a158_corr5", "a158_vsump60", "a158_std60",
    # Phase 3B extras
    "kbar_kup", "gain_loss_ratio_20", "up_days_ratio_20", "volume_std_20",
]
# Removed (not in factor_values DB):
#   net_mf_amount, big_small_divergence — moneyflow micro not stored as factors
#   RSI_14, MACD_hist, KDJ_K, CCI_14 — TA-Lib factors not computed/stored
#   sue_q3, sue_all — PEAD factors not stored
#   ind_mom_20, ind_mom_60 — industry momentum not stored

# LightGBM parameters (from ml_engine.py defaults, GPU-optimized)
PARAMS_REG = {
    "objective": "regression",
    "metric": "mse",
    "boosting_type": "gbdt",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": 6,
    "min_child_samples": 50,
    "reg_alpha": 1.0,
    "reg_lambda": 5.0,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "subsample_freq": 1,
    "device_type": "gpu",
    "gpu_platform_id": 0,
    "gpu_device_id": 0,
    "gpu_use_dp": False,
    "max_bin": 63,
    "n_jobs": -1,
    "seed": 42,
    "bagging_seed": 42,
    "feature_fraction_seed": 42,
    "data_random_seed": 42,
    "deterministic": True,
    "verbose": -1,
}

PARAMS_LR = {
    **PARAMS_REG,
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_eval_at": [20],
}

CACHE_DIR = Path("cache/ml")
RESULTS_FILE = CACHE_DIR / "phase3d_results.json"

# ============================================================
# Data Preparation
# ============================================================


_PRICE_COLS = [
    "code", "trade_date", "open", "close", "pre_close", "volume", "amount",
    "up_limit", "down_limit", "turnover_rate",
    "is_st", "is_suspended", "is_new_stock", "board",
]
_FLOAT32_COLS = [
    "open", "close", "pre_close", "up_limit", "down_limit",
    "turnover_rate", "amount",
]

# WF needs ~750 train + 5×250 test = 2005 trading days from end
# 2017 start gives ~2250 days buffer (2018 too tight at ~2005)
MIN_YEAR = 2017


def _downcast_floats(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast float64 columns to float32 in-place."""
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].astype(np.float32)
    return df


def load_price_benchmark() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load price and benchmark data from Parquet cache (memory-optimized)."""
    cache_root = Path("cache/backtest")
    price_parts, bench_parts = [], []
    for year_dir in sorted(cache_root.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            yr = int(year_dir.name)
        except ValueError:
            continue
        if yr < MIN_YEAR:
            continue
        pf = year_dir / "price_data.parquet"
        bf = year_dir / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf, columns=_PRICE_COLS))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    del price_parts
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date").sort_values("trade_date")
    del bench_parts

    # Ensure date types
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.date
    bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"]).dt.date

    # Downcast floats to float32
    for col in _FLOAT32_COLS:
        if col in price_df.columns:
            price_df[col] = price_df[col].astype(np.float32)
    _downcast_floats(bench_df)

    gc.collect()
    mem_mb = price_df.memory_usage(deep=True).sum() / 1024**2
    print(f"  Price data: {len(price_df):,} rows, {price_df['code'].nunique()} stocks, "
          f"{price_df['trade_date'].nunique()} days, {mem_mb:.0f}MB")
    print(f"  Benchmark: {len(bench_df):,} rows")
    return price_df, bench_df


def compute_target_labels(price_df: pd.DataFrame, bench_df: pd.DataFrame) -> pd.DataFrame:
    """Compute T+20 log excess return labels (memory-optimized).

    Uses groupby+shift instead of pivot to avoid wide matrix explosion.
    Returns long-format DataFrame: (trade_date, code, excess_return_20)
    """
    cache_path = CACHE_DIR / "target_excess_return_20.parquet"
    if cache_path.exists():
        print(f"  Loading cached target labels from {cache_path}")
        df = pd.read_parquet(cache_path)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        _downcast_floats(df)
        print(f"  Target labels: {len(df):,} rows")
        return df

    print("  Computing target labels (T+20 log excess return)...")
    t0 = time.time()

    # Stock forward return via groupby+shift (no wide matrix)
    slim = price_df[["code", "trade_date", "close"]].copy()
    slim = slim.sort_values(["code", "trade_date"])
    slim["fwd_close"] = slim.groupby("code")["close"].shift(-20)
    slim["stock_fwd"] = np.log1p(
        (slim["fwd_close"] / slim["close"] - 1).astype(np.float32)
    )
    slim.drop(columns=["fwd_close"], inplace=True)

    # Benchmark forward return
    bench = bench_df[["trade_date", "close"]].copy().sort_values("trade_date")
    bench["bench_fwd"] = np.log1p(
        (bench["close"].shift(-20) / bench["close"] - 1).astype(np.float32)
    )
    bench_map = bench.set_index("trade_date")["bench_fwd"]

    # Excess return
    slim["bench_fwd"] = slim["trade_date"].map(bench_map)
    slim["excess_return_20"] = (slim["stock_fwd"] - slim["bench_fwd"]).astype(np.float32)
    del bench, bench_map
    gc.collect()

    # Filter
    result = slim[["trade_date", "code", "excess_return_20"]].dropna(subset=["excess_return_20"])
    result = result[result["excess_return_20"].abs() < 5.0].copy()
    del slim
    gc.collect()

    # Save cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache_path, index=False)

    print(f"  Target labels: {len(result):,} rows, {time.time() - t0:.1f}s")
    return result


def verify_factors(feature_names: list[str]) -> list[str]:
    """Verify which factors exist in DB with neutral_value. Returns valid names.

    Uses EXISTS + LIMIT 1 queries for speed on 590M row table.
    """
    from app.services.db import get_sync_conn
    conn = get_sync_conn()
    cur = conn.cursor()

    # Check each factor — use EXISTS (fast, stops at first match)
    valid = []
    missing = []
    no_neutral = []

    for fname in feature_names:
        # Check existence (fast)
        cur.execute(
            "SELECT 1 FROM factor_values "
            "WHERE factor_name = %s AND trade_date >= '2020-01-01' LIMIT 1",
            (fname,),
        )
        exists = cur.fetchone() is not None
        if not exists:
            missing.append(fname)
            continue

        # Check neutral_value existence (fast)
        cur.execute(
            "SELECT 1 FROM factor_values "
            "WHERE factor_name = %s AND trade_date >= '2020-01-01' "
            "AND neutral_value IS NOT NULL LIMIT 1",
            (fname,),
        )
        has_neutral = cur.fetchone() is not None
        if not has_neutral:
            no_neutral.append(fname)
        valid.append(fname)

    conn.close()

    if missing:
        print(f"  ⚠ Missing factors (not in DB): {missing}")
    if no_neutral:
        print(f"  ℹ Factors without neutral_value (will use raw_value): {no_neutral}")
    print(f"  ✓ Valid factors: {len(valid)}/{len(feature_names)}")
    return valid


def load_factor_matrix(
    feature_names: list[str],
    start_date: date = date(2017, 1, 1),
    end_date: date = date(2026, 4, 30),
) -> pd.DataFrame:
    """Load factor matrix from DB per-factor to control memory.

    Loads one factor at a time, merges incrementally, uses float32.
    """
    from app.services.db import get_sync_conn

    cache_key = f"features_{len(feature_names)}f_{start_date.year}"
    cache_path = CACHE_DIR / f"{cache_key}.parquet"
    if cache_path.exists():
        print(f"  Loading cached feature matrix from {cache_path}")
        df = pd.read_parquet(cache_path)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        _downcast_floats(df)
        print(f"  Feature matrix: {df.shape}")
        return df

    print(f"  Loading {len(feature_names)} factors from DB (per-factor)...")
    t0 = time.time()

    result_df = None
    for i, fname in enumerate(feature_names):
        conn = get_sync_conn()
        sql = """
        SELECT code, trade_date,
               COALESCE(neutral_value, raw_value) as value
        FROM factor_values
        WHERE factor_name = %s
          AND trade_date BETWEEN %s AND %s
          AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """
        chunk = pd.read_sql(sql, conn, params=(fname, start_date, end_date))
        conn.close()

        chunk["trade_date"] = pd.to_datetime(chunk["trade_date"]).dt.date
        chunk["value"] = chunk["value"].astype(np.float32)
        chunk = chunk.rename(columns={"value": fname})

        null_pct = chunk[fname].isna().mean() * 100
        status = f"  [{i+1}/{len(feature_names)}] {fname}: {len(chunk):,} rows"
        if null_pct > 30:
            status += f" (WARNING: {null_pct:.0f}% NaN)"
        print(status)

        if result_df is None:
            result_df = chunk
        else:
            result_df = result_df.merge(chunk, on=["code", "trade_date"], how="outer")

        del chunk
        gc.collect()

    # Save cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_parquet(cache_path, index=False)
    print(f"  Feature matrix: {result_df.shape}, {time.time() - t0:.1f}s total")
    return result_df


def prepare_ml_data(
    feature_names: list[str],
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare combined feature + target DataFrame for ML training."""
    target_df = compute_target_labels(price_df, bench_df)
    factor_df = load_factor_matrix(feature_names)

    merged = factor_df.merge(
        target_df[["trade_date", "code", "excess_return_20"]],
        on=["trade_date", "code"],
        how="inner",
    )
    del target_df, factor_df
    gc.collect()

    merged = merged.dropna(subset=["excess_return_20"])
    _downcast_floats(merged)

    # Coverage report (1.5): per-factor NaN rate after merge
    print(f"  Merged data: {len(merged):,} rows, {merged['code'].nunique()} stocks, "
          f"{merged['trade_date'].nunique()} days")
    print("  Feature coverage after merge:")
    for f in feature_names:
        if f in merged.columns:
            n_valid = merged[f].notna().sum()
            nan_pct = merged[f].isna().mean() * 100
            flag = " ⚠ LOW" if nan_pct > 50 else (" △" if nan_pct > 30 else "")
            print(f"    {f:30s} valid={n_valid:>10,}  NaN={nan_pct:5.1f}%{flag}")
    return merged


# ============================================================
# ML Signal Function Factory
# ============================================================


def _compute_ic(pred: np.ndarray, actual: np.ndarray) -> float:
    """Spearman rank IC between predictions and actuals."""
    if len(pred) < 30:
        return 0.0
    ic, _ = sp_stats.spearmanr(pred, actual)
    return float(ic) if not np.isnan(ic) else 0.0


def _build_rank_groups(df: pd.DataFrame) -> list[int]:
    """Build LightGBM rank group sizes (one group per trade_date)."""
    groups = df.groupby("trade_date").size().tolist()
    return groups


def _to_rank_label(y: np.ndarray, n_bins: int = 5) -> np.ndarray:
    """Convert continuous returns to non-negative integer labels for lambdarank.

    NOTE: This is the global-quantile fallback. Prefer _to_rank_label_per_group
    for LambdaRank training, which computes per-date quantiles so that each
    group has a full label spread even when cross-date return levels differ.
    """
    labels = np.zeros(len(y), dtype=np.int32)
    valid_mask = ~np.isnan(y)
    if valid_mask.sum() < n_bins:
        return labels
    quantiles = np.nanquantile(y, np.linspace(0, 1, n_bins + 1))
    quantiles[-1] += 1e-8
    for i in range(n_bins):
        mask = valid_mask & (y >= quantiles[i]) & (y < quantiles[i + 1])
        labels[mask] = i
    return labels


def _to_rank_label_per_group(
    df: pd.DataFrame, y_col: str = "excess_return_20", n_bins: int = 5
) -> np.ndarray:
    """Per-date quantile labels for LambdaRank.

    Global quantiles cause entire days (when market-wide returns are low)
    to collapse to a single label bin, giving LambdaRank zero gradient for
    that group. Per-date quantiles ensure every group has a full 0..(n_bins-1)
    label spread.
    """
    # Reset index to contiguous 0..N-1 so we can safely index into labels array
    df_reset = df[[y_col, "trade_date"]].reset_index(drop=True)
    labels = np.zeros(len(df_reset), dtype=np.int32)
    for _, grp in df_reset.groupby("trade_date"):
        y = grp[y_col].values
        valid = ~np.isnan(y)
        if valid.sum() < n_bins:
            continue
        try:
            bins = pd.qcut(y[valid], n_bins, labels=False, duplicates="drop")
            result = np.zeros(len(grp), dtype=np.int32)
            result[valid] = bins.astype(np.int32)
            labels[grp.index.values] = result
        except ValueError:
            continue
    return labels


@dataclass
class FoldDiagnostics:
    """Diagnostics for a single fold's ML training."""
    fold_idx: int
    train_samples: int = 0
    valid_samples: int = 0
    train_ic: float = 0.0
    valid_ic: float = 0.0
    best_iter: int = 0
    feature_importance: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0


def make_lgbm_signal_func(
    ml_data: pd.DataFrame,
    feature_names: list[str],
    price_data: pd.DataFrame,
    top_n: int = 20,
    rebalance_freq: str = "monthly",
    size_neutral_beta: float = 0.50,
    ln_mcap_pivot: pd.DataFrame | None = None,
    lgb_params: dict | None = None,
    mode: str = "regression",
    extra_purge_days: int = 16,
    fold_diagnostics: list[FoldDiagnostics] | None = None,
):
    """Create a WF-compatible signal_func that trains LightGBM per fold.

    Analogous to make_equal_weight_signal_func() in walk_forward.py:92.
    Trains LightGBM on train_dates, predicts on test_dates, returns
    Top-N equal-weight portfolios with SN adjustment.

    Args:
        ml_data: Wide DataFrame (trade_date, code, f1..fN, excess_return_20)
        feature_names: Column names to use as features
        price_data: For universe filtering (ST/BJ/suspended/new_stock)
        top_n: Top-N stocks per rebalance
        rebalance_freq: "monthly" / "weekly"
        size_neutral_beta: SN adjustment strength (0.50 = baseline)
        ln_mcap_pivot: Market cap data for SN (required if beta > 0)
        lgb_params: LightGBM parameters (defaults to PARAMS_REG)
        mode: "regression" or "lambdarank"
        extra_purge_days: Extra purge beyond WF gap (16 = 21 total - 5 gap)
        fold_diagnostics: Mutable list to collect per-fold diagnostics
    """
    import lightgbm as lgb
    from engines.ml_engine import FeaturePreprocessor
    from engines.signal_engine import PortfolioBuilder, SignalConfig

    if lgb_params is None:
        lgb_params = PARAMS_LR.copy() if mode == "lambdarank" else PARAMS_REG.copy()

    # Build exclusion map (one-time)
    exclusion_map = build_exclusion_map(price_data)

    # Pre-compute rebalance dates
    all_trading_days = sorted(price_data["trade_date"].unique())
    all_rebal_dates = compute_rebalance_dates(all_trading_days, rebalance_freq)

    # Portfolio builder config
    se_config = SignalConfig(
        factor_names=feature_names[:4],  # dummy, not used for composition
        top_n=top_n,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
    )
    builder = PortfolioBuilder(se_config)

    # Actual feature columns present in ml_data
    actual_features = [f for f in feature_names if f in ml_data.columns]
    fold_counter = [0]  # mutable counter

    def signal_func(
        train_dates: list[date], test_dates: list[date]
    ) -> dict[date, dict[str, float]]:
        fold_counter[0] += 1
        fold_idx = fold_counter[0]
        t0 = time.time()
        print(f"\n  === Fold {fold_idx} ===")
        print(f"  Train: {train_dates[0]}..{train_dates[-1]} ({len(train_dates)}d)")
        print(f"  Test:  {test_dates[0]}..{test_dates[-1]} ({len(test_dates)}d)")

        train_set = set(train_dates)
        test_set = set(test_dates)

        # 1. Slice data
        train_full = ml_data[ml_data["trade_date"].isin(train_set)].copy()

        # 2. Purge last extra_purge_days from training data
        # (prevents T+20 label leakage through WF gap)
        train_unique_dates = sorted(train_full["trade_date"].unique())
        if len(train_unique_dates) > extra_purge_days + 50:
            purge_cutoff = train_unique_dates[-(extra_purge_days + 1)]
            train_full = train_full[train_full["trade_date"] <= purge_cutoff]
            train_unique_dates = sorted(train_full["trade_date"].unique())

        # 3. Split 80/20 train_inner/valid (time-ordered)
        n_train_dates = len(train_unique_dates)
        split_idx = int(n_train_dates * 0.8)
        train_inner_dates = set(train_unique_dates[:split_idx])
        valid_dates = set(train_unique_dates[split_idx:])

        train_inner = train_full[train_full["trade_date"].isin(train_inner_dates)]
        valid_data = train_full[train_full["trade_date"].isin(valid_dates)]

        if len(train_inner) < 5000 or len(valid_data) < 1000:
            print(f"  SKIP: insufficient data (train={len(train_inner)}, valid={len(valid_data)})")
            return {}

        # 4. Fit preprocessor on train_inner only
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(train_inner, actual_features)

        train_processed = preprocessor.transform(train_inner)
        valid_processed = preprocessor.transform(valid_data)

        X_train = train_processed[actual_features].values.astype(np.float32)
        y_train = train_processed["excess_return_20"].values.astype(np.float32)
        X_valid = valid_processed[actual_features].values.astype(np.float32)
        y_valid = valid_processed["excess_return_20"].values.astype(np.float32)

        print(f"  Train: {len(X_train):,} samples, Valid: {len(X_valid):,} samples")

        # 5. Build LightGBM datasets
        if mode == "lambdarank":
            train_groups = _build_rank_groups(train_processed)
            valid_groups = _build_rank_groups(valid_processed)
            y_train_rank = _to_rank_label_per_group(train_processed)
            y_valid_rank = _to_rank_label_per_group(valid_processed)
            train_ds = lgb.Dataset(
                X_train, label=y_train_rank,
                group=train_groups, feature_name=actual_features,
            )
            valid_ds = lgb.Dataset(
                X_valid, label=y_valid_rank,
                group=valid_groups, reference=train_ds,
            )
        else:
            train_ds = lgb.Dataset(X_train, label=y_train, feature_name=actual_features)
            valid_ds = lgb.Dataset(X_valid, label=y_valid, reference=train_ds)

        # 6. Train
        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=100),
        ]
        model = lgb.train(
            lgb_params,
            train_ds,
            num_boost_round=500,
            valid_sets=[valid_ds],
            valid_names=["valid"],
            callbacks=callbacks,
        )
        best_iter = model.best_iteration

        # 7. Compute train/valid IC for diagnostics
        train_pred = model.predict(X_train, num_iteration=best_iter)
        valid_pred = model.predict(X_valid, num_iteration=best_iter)
        train_ic = _compute_ic(train_pred, y_train)
        valid_ic = _compute_ic(valid_pred, y_valid)

        # Feature importance
        importance = model.feature_importance(importance_type="gain")
        feat_imp = dict(zip(actual_features, [float(v) for v in importance]))

        elapsed = time.time() - t0
        print(f"  Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f}, "
              f"best_iter={best_iter}, {elapsed:.1f}s")

        # Record diagnostics
        if fold_diagnostics is not None:
            fold_diagnostics.append(FoldDiagnostics(
                fold_idx=fold_idx,
                train_samples=len(X_train),
                valid_samples=len(X_valid),
                train_ic=train_ic,
                valid_ic=valid_ic,
                best_iter=best_iter,
                feature_importance=feat_imp,
                elapsed_s=elapsed,
            ))

        # 8. Generate signals for test period rebalance dates
        fold_rebal = [rd for rd in all_rebal_dates if rd in test_set]
        if not fold_rebal:
            print("  WARNING: No rebalance dates in test period")
            return {}

        # Load test period factor data for prediction
        test_factor_data = ml_data[ml_data["trade_date"].isin(test_set)].copy()

        target_portfolios: dict[date, dict[str, float]] = {}
        for rd in fold_rebal:
            # Get latest factor data <= rebalance date
            day_data = test_factor_data[test_factor_data["trade_date"] <= rd]
            if day_data.empty:
                continue
            latest_date = day_data["trade_date"].max()
            day_data = day_data[day_data["trade_date"] == latest_date].copy()

            # Filter universe
            exclude = exclusion_map.get(latest_date, set())
            day_data = day_data[~day_data["code"].isin(exclude)]

            if len(day_data) < top_n:
                continue

            # Preprocess and predict
            day_processed = preprocessor.transform(day_data)
            X_day = day_processed[actual_features].values.astype(np.float32)
            preds = model.predict(X_day, num_iteration=best_iter)

            # Build scores Series — z-score normalize so ML predictions
            # are on same scale as equal-weight composite (~N(0,1)).
            # Without this, SN adjustment (beta * zscore(ln_mcap) ~ ±1.5)
            # completely overwhelms raw predictions (~±0.05).
            scores = pd.Series(preds, index=day_processed["code"].values)
            s_std = scores.std()
            if s_std > 1e-8:
                scores = (scores - scores.mean()) / s_std
            scores = scores.sort_values(ascending=False)

            # Apply size-neutral adjustment
            if size_neutral_beta > 0 and ln_mcap_pivot is not None:
                if latest_date in ln_mcap_pivot.index:
                    from engines.size_neutral import apply_size_neutral
                    scores = apply_size_neutral(
                        scores, ln_mcap_pivot.loc[latest_date], size_neutral_beta
                    )

            # --- OOS diagnostic: prediction IC and Top-20 analysis ---
            actual_ret = day_processed["excess_return_20"].values
            valid_mask = ~np.isnan(actual_ret)
            if valid_mask.sum() > 50:
                oos_ic, _ = sp_stats.spearmanr(preds[valid_mask], actual_ret[valid_mask])
                top20_codes = scores.head(20).index.tolist()
                top20_ret_map = pd.Series(actual_ret, index=day_processed["code"].values)
                top20_avg = top20_ret_map.reindex(top20_codes).mean()
                bot20_codes = scores.tail(20).index.tolist()
                bot20_avg = top20_ret_map.reindex(bot20_codes).mean()
                # Check code format alignment with price_data
                price_codes = set(price_data["code"].unique())
                n_in_price = sum(1 for c in top20_codes if c in price_codes)
                print(f"    {rd}: IC={oos_ic:+.4f}, Top20_exret={top20_avg:+.4f}, "
                      f"Bot20_exret={bot20_avg:+.4f}, n={valid_mask.sum()}, "
                      f"codes_in_price={n_in_price}/20, "
                      f"sample_codes={top20_codes[:3]}")

            # Top-N equal-weight via PortfolioBuilder
            weights = builder.build(scores, pd.Series(dtype=str))
            if weights:
                target_portfolios[rd] = weights
                wt_sum = sum(weights.values())
                print(f"    → Portfolio: {len(weights)} stocks, wt_sum={wt_sum:.4f}, "
                      f"top3={list(weights.keys())[:3]}")

        print(f"  Generated {len(target_portfolios)} rebalance signals")
        return target_portfolios

    return signal_func


# ============================================================
# Experiment Runner
# ============================================================


def load_ln_mcap_pivot(price_df: pd.DataFrame) -> pd.DataFrame:
    """Load ln_market_cap pivot for SN adjustment (memory-optimized)."""
    cache_path = CACHE_DIR / "ln_mcap_pivot.parquet"
    if cache_path.exists():
        print(f"  Loading cached ln_mcap pivot from {cache_path}")
        pivot = pd.read_parquet(cache_path)
        pivot.index = pd.to_datetime(pivot.index).date
        _downcast_floats(pivot)
        print(f"  ln_mcap pivot: {pivot.shape}")
        return pivot

    from app.services.db import get_sync_conn
    conn = get_sync_conn()

    min_date = price_df["trade_date"].min()
    max_date = price_df["trade_date"].max()

    df = pd.read_sql(
        """SELECT code, trade_date,
                  CAST(neutral_value AS REAL) as ln_mcap
           FROM factor_values
           WHERE factor_name = 'ln_market_cap'
             AND trade_date BETWEEN %s AND %s
             AND neutral_value IS NOT NULL""",
        conn, params=(min_date, max_date),
    )
    conn.close()

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["ln_mcap"] = df["ln_mcap"].astype(np.float32)
    pivot = df.pivot_table(index="trade_date", columns="code", values="ln_mcap", aggfunc="first")
    del df
    gc.collect()

    pivot.to_parquet(cache_path)
    print(f"  ln_mcap pivot: {pivot.shape}")
    return pivot


def run_experiment(
    exp_id: str,
    feature_names: list[str],
    mode: str,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame,
    ml_data: pd.DataFrame,
    sn_beta: float = 0.50,
) -> dict[str, Any]:
    """Run a single ML WF experiment."""
    print(f"\n{'='*60}")
    print(f"Experiment: {exp_id} ({len(feature_names)} features, {mode}, SN_beta={sn_beta})")
    print(f"{'='*60}")

    # Collect per-fold diagnostics
    fold_diagnostics: list[FoldDiagnostics] = []

    # Build signal function
    lgb_params = PARAMS_LR.copy() if mode == "lambdarank" else PARAMS_REG.copy()

    signal_func = make_lgbm_signal_func(
        ml_data=ml_data,
        feature_names=feature_names,
        price_data=price_df,
        top_n=20,
        rebalance_freq="monthly",
        size_neutral_beta=sn_beta,
        ln_mcap_pivot=ln_mcap_pivot,
        lgb_params=lgb_params,
        mode=mode,
        extra_purge_days=16,
        fold_diagnostics=fold_diagnostics,
    )

    # WF config — SAME as equal-weight baseline
    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(
        top_n=20,
        rebalance_freq="monthly",
        initial_capital=1_000_000,
    )

    # Run WF
    engine = WalkForwardEngine(wf_config, bt_config)
    all_dates = sorted(price_df["trade_date"].unique())

    t0 = time.time()
    result = engine.run(signal_func, price_df, bench_df, all_dates)
    total_elapsed = time.time() - t0

    # Compile results
    fold_results = []
    for fr in result.fold_results:
        diag = fold_diagnostics[fr.fold_idx] if fr.fold_idx < len(fold_diagnostics) else None
        fold_results.append({
            "fold_idx": fr.fold_idx,
            "train_period": f"{fr.train_period[0]}..{fr.train_period[1]}",
            "test_period": f"{fr.test_period[0]}..{fr.test_period[1]}",
            "oos_sharpe": round(fr.oos_sharpe, 4),
            "oos_mdd": round(fr.oos_mdd, 4),
            "oos_annual_return": round(fr.oos_annual_return, 4),
            "train_ic": round(diag.train_ic, 4) if diag else None,
            "valid_ic": round(diag.valid_ic, 4) if diag else None,
            "best_iter": diag.best_iter if diag else None,
            "top5_features": dict(
                sorted(diag.feature_importance.items(), key=lambda x: -x[1])[:5]
            ) if diag and diag.feature_importance else {},
        })

    # Feature importance stability across folds
    all_importances = [d.feature_importance for d in fold_diagnostics if d.feature_importance]
    fi_stability = 0.0
    if len(all_importances) >= 2:
        # Pairwise Spearman correlation of feature importance rankings
        all_features_set = set()
        for imp in all_importances:
            all_features_set.update(imp.keys())
        all_features_list = sorted(all_features_set)

        correlations = []
        for i in range(len(all_importances)):
            for j in range(i + 1, len(all_importances)):
                ranks_i = [all_importances[i].get(f, 0) for f in all_features_list]
                ranks_j = [all_importances[j].get(f, 0) for f in all_features_list]
                corr, _ = sp_stats.spearmanr(ranks_i, ranks_j)
                if not np.isnan(corr):
                    correlations.append(corr)
        fi_stability = float(np.mean(correlations)) if correlations else 0.0

    # Averaged feature importance
    avg_importance = {}
    if all_importances:
        all_keys = set()
        for imp in all_importances:
            all_keys.update(imp.keys())
        for k in all_keys:
            vals = [imp.get(k, 0) for imp in all_importances]
            avg_importance[k] = float(np.mean(vals))

    top20_features = dict(sorted(avg_importance.items(), key=lambda x: -x[1])[:20])

    n_negative_folds = sum(1 for fr in result.fold_results if fr.oos_sharpe < 0)

    output = {
        "exp_id": exp_id,
        "n_features": len(feature_names),
        "mode": mode,
        "combined_oos_sharpe": round(result.combined_oos_sharpe, 4),
        "combined_oos_mdd": round(result.combined_oos_mdd, 4),
        "combined_oos_annual_return": round(result.combined_oos_annual_return, 4),
        "combined_oos_total_return": round(result.combined_oos_total_return, 4),
        "total_oos_days": result.total_oos_days,
        "n_negative_folds": n_negative_folds,
        "all_folds_positive": n_negative_folds == 0,
        "fi_stability": round(fi_stability, 4),
        "top20_features": top20_features,
        "fold_results": fold_results,
        "elapsed_s": round(total_elapsed, 1),
        "baseline_sharpe": 0.8659,
        "vs_baseline": round(result.combined_oos_sharpe - 0.8659, 4),
        "vs_baseline_pct": round((result.combined_oos_sharpe / 0.8659 - 1) * 100, 1),
    }

    print(f"\n  === {exp_id} Result ===")
    print(f"  OOS Sharpe: {output['combined_oos_sharpe']}")
    print(f"  OOS MDD:    {output['combined_oos_mdd']}")
    print(f"  vs baseline: {output['vs_baseline']:+.4f} ({output['vs_baseline_pct']:+.1f}%)")
    print(f"  Negative folds: {n_negative_folds}/5")
    print(f"  FI stability: {fi_stability:.3f}")
    print(f"  Top 5 features: {list(top20_features.keys())[:5]}")
    print(f"  Total time: {total_elapsed:.0f}s")

    return output


# ============================================================
# Main
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="Phase 3D: ML Synthesis Experiments")
    parser.add_argument("--feature-set", choices=["A", "B", "C"], help="Feature set to use")
    parser.add_argument("--mode", choices=["regression", "lambdarank"], default="regression")
    parser.add_argument("--all", action="store_true", help="Run all experiments")
    parser.add_argument("--beta", type=float, default=0.50, help="SN beta (0=no SN)")
    parser.add_argument("--verify", action="store_true", help="Verify factor availability only")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Verify mode
    if args.verify:
        print("=== Factor Verification ===")
        print("\nFeature-A:")
        valid_a = verify_factors(FEATURES_A)
        print("\nFeature-B:")
        valid_b = verify_factors(FEATURES_B)
        return

    # Load shared data
    print("=" * 60)
    print("Phase 3D: ML Synthesis")
    print("=" * 60)

    print("\n[1/3] Loading price & benchmark data...")
    price_df, bench_df = load_price_benchmark()

    print("\n[2/3] Loading ln_mcap pivot for SN...")
    ln_mcap_pivot = load_ln_mcap_pivot(price_df)

    # Determine experiments to run
    experiments = []
    if args.all:
        experiments = [
            ("A-REG", FEATURES_A, "regression"),
            ("A-LR", FEATURES_A, "lambdarank"),
            ("B-REG", FEATURES_B, "regression"),
            ("B-LR", FEATURES_B, "lambdarank"),
        ]
    elif args.feature_set:
        features = FEATURES_A if args.feature_set == "A" else FEATURES_B
        exp_id = f"{args.feature_set}-{'REG' if args.mode == 'regression' else 'LR'}"
        experiments = [(exp_id, features, args.mode)]
    else:
        print("ERROR: Specify --feature-set or --all")
        return

    # Run experiments
    all_results = []
    for exp_id, feature_names, mode in experiments:
        # Verify factors
        print(f"\n[Verify] Checking {len(feature_names)} factors for {exp_id}...")
        valid_features = verify_factors(feature_names)
        if len(valid_features) < 4:
            print(f"  SKIP {exp_id}: too few valid factors ({len(valid_features)})")
            continue

        # Prepare ML data
        print(f"\n[Data] Preparing ML data for {exp_id}...")
        ml_data = prepare_ml_data(valid_features, price_df, bench_df)

        if len(ml_data) < 100000:
            print(f"  SKIP {exp_id}: insufficient merged data ({len(ml_data):,})")
            continue

        # Run experiment
        result = run_experiment(
            exp_id, valid_features, mode,
            price_df, bench_df, ln_mcap_pivot, ml_data,
            sn_beta=args.beta,
        )
        all_results.append(result)

        # Free memory
        del ml_data
        gc.collect()

    # Merge with existing results (accumulate across runs)
    existing_experiments = []
    if RESULTS_FILE.exists():
        try:
            existing = json.loads(RESULTS_FILE.read_text())
            existing_experiments = existing.get("experiments", [])
        except (json.JSONDecodeError, KeyError):
            pass

    # Merge: new results override existing by exp_id
    new_ids = {r["exp_id"] for r in all_results}
    merged = [r for r in existing_experiments if r["exp_id"] not in new_ids] + all_results

    output = {
        "baseline": {
            "method": "equal_weight_CORE3+dv_ttm+SN050",
            "oos_sharpe": 0.8659,
            "oos_mdd": -0.1391,
        },
        "experiments": merged,
        "timestamp": pd.Timestamp.now().isoformat(),
    }
    RESULTS_FILE.write_text(json.dumps(output, indent=2, default=str))
    all_results = merged  # For summary table
    print(f"\n{'='*60}")
    print(f"Results saved to {RESULTS_FILE}")

    # Summary table
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Exp':10s} {'Features':>8s} {'OOS Sharpe':>11s} {'OOS MDD':>9s} "
          f"{'vs Base':>9s} {'Neg Folds':>9s} {'FI Stab':>8s}")
    print("-" * 70)
    print(f"{'Baseline':10s} {'4':>8s} {'0.8659':>11s} {'-13.91%':>9s} "
          f"{'—':>9s} {'0/5':>9s} {'—':>8s}")
    for r in all_results:
        sharpe_str = f"{r['combined_oos_sharpe']:.4f}"
        mdd_str = f"{r['combined_oos_mdd']*100:.1f}%"
        vs_str = f"{r['vs_baseline']:+.4f}"
        neg_str = f"{r['n_negative_folds']}/5"
        fi_str = f"{r['fi_stability']:.3f}"
        print(f"{r['exp_id']:10s} {r['n_features']:>8d} {sharpe_str:>11s} {mdd_str:>9s} "
              f"{vs_str:>9s} {neg_str:>9s} {fi_str:>8s}")


if __name__ == "__main__":
    main()
