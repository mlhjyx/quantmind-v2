#!/usr/bin/env python
"""Phase 2.4 Audit: 9 Critical Questions Investigation.

Validates Phase 2.4 findings reliability before Walk-Forward verification.

Usage:
    cd backend && python ../scripts/research/phase24_audit_questions.py --q1
    cd backend && python ../scripts/research/phase24_audit_questions.py --q2
    cd backend && python ../scripts/research/phase24_audit_questions.py --all
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
import time
import warnings
from bisect import bisect_right
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, message=".*SQLAlchemy.*")
import numpy as np
import pandas as pd

# Suppress verbose debug logging from backtest engine (structlog-based)
import structlog
from scipy import stats as scipy_stats

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
)
logging.getLogger().setLevel(logging.WARNING)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
PROJECT_ROOT = BACKEND_DIR.parent
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

CACHE_DIR = PROJECT_ROOT / "cache"
AUDIT_CACHE = CACHE_DIR / "phase24_audit"
PHASE22_CACHE = CACHE_DIR / "phase22"
PHASE24_CACHE = CACHE_DIR / "phase24"

# ─── Import shared utilities from phase24_research_exploration ──────
from phase24_research_exploration import (
    CORE5_DIRECTIONS,
    CORE5_FACTORS,
    OOS_END,
    OOS_START,
    SN_BETA,
    YUAN_TO_YI,
    build_exclusion_set,
    compute_composite_scores,
    compute_metrics,
    filter_factor_by_mcap,
    get_db_conn,
    get_monthly_rebal_dates,
    load_factor_from_parquet,
    load_factors_from_db,
    load_mcap_data,
    load_price_data,
    run_standard_experiment,
)

# ─── Constants ──────────────────────────────────────────────
BEST_FACTORS = ["turnover_mean_20", "volatility_20", "bp_ratio", "RSQR_20", "dv_ttm"]
BEST_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "bp_ratio": 1,
    "RSQR_20": -1,
    "dv_ttm": 1,
}
CORE3_FACTORS = ["turnover_mean_20", "volatility_20", "bp_ratio"]
CORE3_DIRECTIONS = {"turnover_mean_20": -1, "volatility_20": -1, "bp_ratio": 1}

PHASE22_OOS_START = date(2020, 1, 2)
PHASE22_OOS_END = date(2026, 3, 12)

ALL_7_FACTORS = CORE5_FACTORS + ["RSQR_20", "dv_ttm"]

TRADING_DAYS_PER_YEAR = 244  # A股


# ─── Utility Functions ──────────────────────────────────────


def save_result(data: dict, name: str):
    """Save result to audit cache as JSON."""
    AUDIT_CACHE.mkdir(parents=True, exist_ok=True)
    fp = AUDIT_CACHE / f"{name}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved: {fp}")


def load_cached(name: str) -> dict | None:
    """Load cached result if exists."""
    fp = AUDIT_CACHE / f"{name}.json"
    if fp.exists():
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    return None


def _optimize_factor_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce memory footprint of factor_df by converting object columns to category."""
    df = df.copy()
    for col in ["factor_name", "code"]:
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].astype("category")
    return df


def run_backtest_full(
    factor_df,
    directions,
    price_data,
    bench,
    top_n=20,
    rebalance_freq="monthly",
    sn_beta=0.0,
    conn=None,
    bt_config_override=None,
):
    """Run backtest and return full BacktestResult (not just metrics dict)."""
    from engines.backtest.config import BacktestConfig
    from engines.backtest.runner import run_hybrid_backtest
    from engines.signal_engine import SignalConfig

    # Optimize memory for large factor dataframes
    factor_df = _optimize_factor_dtypes(factor_df)

    bt_config = bt_config_override or BacktestConfig(
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        initial_capital=1_000_000,
    )
    sig_config = SignalConfig(
        factor_names=list(directions.keys()),
        top_n=top_n,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        size_neutral_beta=sn_beta,
    )
    return run_hybrid_backtest(
        factor_df=factor_df,
        directions=directions,
        price_data=price_data,
        config=bt_config,
        benchmark_data=bench,
        signal_config=sig_config,
        conn=conn,
    )


def build_manual_portfolios(factor_df, directions, price_data, rebal_dates, top_n, sn_beta, conn):
    """Build target_portfolios dict for SimpleBacktester (manual rebalance dates)."""
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
    factor_date_list = sorted(factor_df["trade_date"].unique())

    target_portfolios = {}
    for rd in rebal_dates:
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]
        day_data = factor_df[factor_df["trade_date"] == fd]
        if day_data.empty:
            continue
        exclude = build_exclusion_set(price_data, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]
        scores = compute_composite_scores(day_data, directions)
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index and sn_beta > 0:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], sn_beta)
        top = scores.nlargest(top_n)
        if len(top) < 3:
            continue
        w = 1.0 / len(top)
        target_portfolios[rd] = {code: w for code in top.index}

    return target_portfolios, ln_mcap_pivot


# ─── Lazy Data Cache ────────────────────────────────────────


class AuditDataCache:
    """Lazy-loaded data cache to avoid redundant loads across 9 questions."""

    def __init__(self):
        self._price = None
        self._bench = None
        self._core5_parquet = None
        self._core5_db = None
        self._conn = None
        self._mcap_df = None
        self._best_factor_df = None
        self._lr_predictions = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = get_db_conn()
        return self._conn

    @property
    def price(self):
        if self._price is None:
            print("\n[DataCache] Loading price + benchmark...")
            self._price, self._bench = load_price_data(2020, 2026)
        return self._price

    @property
    def bench(self):
        if self._bench is None:
            _ = self.price  # triggers load
        return self._bench

    @property
    def core5_parquet(self):
        if self._core5_parquet is None:
            print("\n[DataCache] Loading CORE5 from parquet...")
            self._core5_parquet = load_factor_from_parquet(2020, 2026)
        return self._core5_parquet

    @property
    def core5_db(self):
        """Load CORE5 from DB with COALESCE(neutral_value, raw_value) — matches Phase 2.2."""
        if self._core5_db is None:
            print("\n[DataCache] Loading CORE5 from DB (COALESCE)...")
            self._core5_db = load_factors_from_db(
                CORE5_FACTORS, date(2014, 1, 1), date(2026, 12, 31), self.conn
            )
        return self._core5_db

    @property
    def mcap_df(self):
        if self._mcap_df is None:
            print("\n[DataCache] Loading mcap data...")
            self._mcap_df = load_mcap_data(OOS_START, OOS_END, self.conn)
        return self._mcap_df

    @property
    def best_factor_df(self):
        """CORE3 from parquet + RSQR_20/dv_ttm from DB, merged."""
        if self._best_factor_df is None:
            print("\n[DataCache] Building best factor df (CORE3+RSQR+dv)...")
            core3 = self.core5_parquet[self.core5_parquet["factor_name"].isin(CORE3_FACTORS)].copy()
            db_factors = load_factors_from_db(["RSQR_20", "dv_ttm"], OOS_START, OOS_END, self.conn)
            self._best_factor_df = pd.concat([core3, db_factors], ignore_index=True)
            print(
                f"  Best factor df: {len(self._best_factor_df):,} rows, "
                f"factors: {sorted(self._best_factor_df['factor_name'].unique())}"
            )
        return self._best_factor_df

    @property
    def lr_predictions(self):
        if self._lr_predictions is None:
            fp = PHASE22_CACHE / "oos_predictions_lambdarank.parquet"
            if fp.exists():
                print(f"\n[DataCache] Loading LambdaRank predictions from {fp}...")
                self._lr_predictions = pd.read_parquet(fp)
                self._lr_predictions["trade_date"] = pd.to_datetime(
                    self._lr_predictions["trade_date"]
                ).dt.date
                print(f"  LR predictions: {len(self._lr_predictions):,} rows")
            else:
                print(f"  WARNING: LambdaRank predictions not found at {fp}")
                self._lr_predictions = pd.DataFrame()
        return self._lr_predictions

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ======================================================================
# Q1: Baseline Sharpe 0.6652 vs 0.6211 Reconciliation
# ======================================================================


def q1_baseline_reconciliation(data: AuditDataCache) -> dict:
    """Q1: 4 cross-test backtests to isolate baseline Sharpe discrepancy."""
    print("\n" + "=" * 70)
    print("Q1: Baseline Sharpe 0.6652 vs 0.6211 Reconciliation")
    print("=" * 70)

    t0 = time.time()

    # Load both factor sources
    core5_parquet = data.core5_parquet
    core5_db = data.core5_db
    price = data.price
    bench = data.bench
    conn = data.conn

    results = {}

    # Helper: filter data to a date window
    def filter_window(df, start, end, date_col="trade_date"):
        return df[(df[date_col] >= start) & (df[date_col] <= end)].copy()

    # Test A: DB factors + Phase 2.2 window
    print("\n[A] DB factors + Phase 2.2 window (2020-01-02 ~ 2026-03-12)...")
    t1 = time.time()
    factor_a = filter_window(core5_db, PHASE22_OOS_START, PHASE22_OOS_END)
    price_a = filter_window(price, PHASE22_OOS_START, PHASE22_OOS_END)
    bench_a = filter_window(bench, PHASE22_OOS_START, PHASE22_OOS_END)
    result_a = run_backtest_full(
        factor_a,
        CORE5_DIRECTIONS,
        price_a,
        bench_a,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    metrics_a = compute_metrics(result_a.daily_nav)
    metrics_a["label"] = "A: DB + Phase2.2 window"
    n_rebal_a = len(result_a.holdings_history) if hasattr(result_a, "holdings_history") else 0
    metrics_a["n_rebal"] = n_rebal_a
    print(
        f"  Sharpe={metrics_a['sharpe']}, MDD={metrics_a['mdd']}, "
        f"AnnRet={metrics_a['annual_return']}, n_rebal={n_rebal_a} ({time.time() - t1:.1f}s)"
    )
    results["test_A_db_phase22"] = metrics_a
    nav_a_series = result_a.daily_nav.copy()  # Save NAV for later analysis
    del result_a, factor_a
    gc.collect()

    # Test B: Parquet factors + Phase 2.4 window
    print("\n[B] Parquet factors + Phase 2.4 window (2020-01-01 ~ 2026-04-01)...")
    t1 = time.time()
    factor_b = filter_window(core5_parquet, OOS_START, OOS_END)
    price_b = filter_window(price, OOS_START, OOS_END)
    bench_b = filter_window(bench, OOS_START, OOS_END)
    result_b = run_backtest_full(
        factor_b,
        CORE5_DIRECTIONS,
        price_b,
        bench_b,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    metrics_b = compute_metrics(result_b.daily_nav)
    metrics_b["label"] = "B: Parquet + Phase2.4 window"
    n_rebal_b = len(result_b.holdings_history) if hasattr(result_b, "holdings_history") else 0
    metrics_b["n_rebal"] = n_rebal_b
    print(
        f"  Sharpe={metrics_b['sharpe']}, MDD={metrics_b['mdd']}, "
        f"AnnRet={metrics_b['annual_return']}, n_rebal={n_rebal_b} ({time.time() - t1:.1f}s)"
    )
    results["test_B_parquet_phase24"] = metrics_b
    del result_b, factor_b
    gc.collect()

    # Test C: Parquet factors + Phase 2.2 window (isolates factor source)
    print("\n[C] Parquet factors + Phase 2.2 window (isolates factor source)...")
    t1 = time.time()
    factor_c = filter_window(core5_parquet, PHASE22_OOS_START, PHASE22_OOS_END)
    result_c = run_backtest_full(
        factor_c,
        CORE5_DIRECTIONS,
        price_a,
        bench_a,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    metrics_c = compute_metrics(result_c.daily_nav)
    metrics_c["label"] = "C: Parquet + Phase2.2 window"
    metrics_c["n_rebal"] = (
        len(result_c.holdings_history) if hasattr(result_c, "holdings_history") else 0
    )
    print(
        f"  Sharpe={metrics_c['sharpe']}, MDD={metrics_c['mdd']}, "
        f"AnnRet={metrics_c['annual_return']} ({time.time() - t1:.1f}s)"
    )
    results["test_C_parquet_phase22"] = metrics_c
    nav_c_series = result_c.daily_nav.copy()  # Save NAV for later analysis
    del result_c, factor_c
    gc.collect()

    # Test D: DB factors + Phase 2.4 window (isolates window)
    print("\n[D] DB factors + Phase 2.4 window (isolates window)...")
    t1 = time.time()
    factor_d = filter_window(core5_db, OOS_START, OOS_END)
    result_d = run_backtest_full(
        factor_d,
        CORE5_DIRECTIONS,
        price_b,
        bench_b,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    metrics_d = compute_metrics(result_d.daily_nav)
    metrics_d["label"] = "D: DB + Phase2.4 window"
    metrics_d["n_rebal"] = (
        len(result_d.holdings_history) if hasattr(result_d, "holdings_history") else 0
    )
    print(
        f"  Sharpe={metrics_d['sharpe']}, MDD={metrics_d['mdd']}, "
        f"AnnRet={metrics_d['annual_return']} ({time.time() - t1:.1f}s)"
    )
    results["test_D_db_phase24"] = metrics_d
    del result_d, factor_d
    gc.collect()

    # NAV divergence analysis (A vs C: same window, different factor source)
    print("\n[5] NAV divergence analysis (A vs C on Phase 2.2 window)...")
    nav_a = nav_a_series
    nav_c = nav_c_series
    common_dates = nav_a.index.intersection(nav_c.index)
    if len(common_dates) > 10:
        # Normalize to start=1.0
        nav_a_norm = nav_a[common_dates] / nav_a[common_dates].iloc[0]
        nav_c_norm = nav_c[common_dates] / nav_c[common_dates].iloc[0]
        diff = (nav_a_norm - nav_c_norm).abs()
        max_diff_idx = diff.idxmax()
        results["nav_divergence"] = {
            "max_diff": round(float(diff.max()), 6),
            "max_diff_date": str(max_diff_idx),
            "mean_diff": round(float(diff.mean()), 6),
            "final_diff": round(float(diff.iloc[-1]), 6),
        }
        print(f"  Max NAV diff (A vs C, normalized): {diff.max():.6f} on {max_diff_idx}")
        print(f"  Mean diff: {diff.mean():.6f}, Final diff: {diff.iloc[-1]:.6f}")
    else:
        results["nav_divergence"] = {"error": "insufficient overlapping dates"}

    # Factor value comparison: sample 100 random triples
    print("\n[6] Factor value comparison (DB vs Parquet, 100 samples)...")
    parquet_sample = core5_parquet.sample(min(500, len(core5_parquet)), random_state=42)
    merged_sample = parquet_sample.merge(
        core5_db,
        on=["code", "trade_date", "factor_name"],
        suffixes=("_parquet", "_db"),
        how="inner",
    )
    if len(merged_sample) > 0:
        val_diff = (merged_sample["raw_value_parquet"] - merged_sample["raw_value_db"]).abs()
        results["factor_value_comparison"] = {
            "n_matched": len(merged_sample),
            "max_abs_diff": round(float(val_diff.max()), 8),
            "mean_abs_diff": round(float(val_diff.mean()), 8),
            "pct_exact_match": round(float((val_diff < 1e-10).mean() * 100), 2),
        }
        print(
            f"  Matched: {len(merged_sample)}, Max diff: {val_diff.max():.8f}, "
            f"Mean diff: {val_diff.mean():.8f}, Exact match: {(val_diff < 1e-10).mean() * 100:.1f}%"
        )
    else:
        results["factor_value_comparison"] = {"error": "no matching samples"}

    # Attribution summary
    sharpe_a = metrics_a["sharpe"]
    sharpe_b = metrics_b["sharpe"]
    sharpe_c = metrics_c["sharpe"]
    sharpe_d = metrics_d["sharpe"]
    window_effect = round((sharpe_d - sharpe_a + sharpe_b - sharpe_c) / 2, 4)
    source_effect = round((sharpe_c - sharpe_a + sharpe_b - sharpe_d) / 2, 4)
    results["attribution"] = {
        "total_diff": round(sharpe_b - sharpe_a, 4),
        "window_effect": window_effect,
        "source_effect": source_effect,
        "residual": round(sharpe_b - sharpe_a - window_effect - source_effect, 4),
    }
    print("\n  === Q1 Attribution ===")
    print(f"  Total Sharpe diff: {sharpe_b} - {sharpe_a} = {sharpe_b - sharpe_a:.4f}")
    print(f"  Window effect: {window_effect:.4f}")
    print(f"  Factor source effect: {source_effect:.4f}")

    # Summary table
    print(f"\n  {'Test':<35} {'Sharpe':>8} {'MDD':>8} {'AnnRet':>8} {'n_rebal':>8}")
    print(f"  {'-' * 67}")
    for key in [
        "test_A_db_phase22",
        "test_B_parquet_phase24",
        "test_C_parquet_phase22",
        "test_D_db_phase24",
    ]:
        m = results[key]
        print(
            f"  {m['label']:<35} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} "
            f"{m['annual_return']:>8.4f} {m['n_rebal']:>8}"
        )

    results["elapsed_min"] = round((time.time() - t0) / 60, 1)
    save_result(results, "q1_baseline_reconciliation")
    print(f"\n  Q1 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q2: Factor Profiles for dv_ttm and RSQR_20
# ======================================================================


def q2_factor_profiles(data: AuditDataCache) -> dict:
    """Q2: Run factor_profiler for dv_ttm and RSQR_20."""
    print("\n" + "=" * 70)
    print("Q2: Factor Profiles — dv_ttm and RSQR_20")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn

    from engines.factor_profiler import _load_shared_data, profile_factor

    print("\n[1] Loading profiler shared data...")
    t1 = time.time()
    close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates = _load_shared_data(conn)
    print(f"  Shared data loaded ({time.time() - t1:.1f}s)")

    results = {}
    for factor_name in ["dv_ttm", "RSQR_20"]:
        print(f"\n[2] Profiling {factor_name}...")
        t1 = time.time()
        try:
            profile = profile_factor(
                factor_name,
                close_pivot,
                fwd_excess,
                csi_monthly,
                industry_map,
                trading_dates,
                conn=conn,
                all_factor_names=ALL_7_FACTORS,
            )
        except (IndexError, Exception) as e:
            print(f"  ⚠️ Profiler failed for {factor_name}: {e}")
            print("  Likely cause: no neutral_value in factor_values table for this factor")
            # Check if data exists under raw_value
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM factor_values WHERE factor_name=%s AND raw_value IS NOT NULL LIMIT 1",
                (factor_name,),
            )
            raw_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM factor_values WHERE factor_name=%s AND neutral_value IS NOT NULL LIMIT 1",
                (factor_name,),
            )
            neutral_count = cur.fetchone()[0]
            results[factor_name] = {
                "factor_name": factor_name,
                "error": f"profiler failed: {e}",
                "raw_value_count": raw_count,
                "neutral_value_count": neutral_count,
                "verdict": "❌ CANNOT PROFILE — neutral_value not populated"
                if neutral_count == 0
                else f"⚠️ profiler error despite {neutral_count} neutral rows",
            }
            print(f"  raw_value rows: {raw_count:,}, neutral_value rows: {neutral_count:,}")
            continue
        elapsed = time.time() - t1
        print(f"  {factor_name} profiled ({elapsed:.1f}s)")

        # Extract key dimensions
        key_dims = {
            "factor_name": factor_name,
            "ic_20d": profile.get("ic_20d"),
            "ic_20d_tstat": profile.get("ic_20d_tstat"),
            "ic_1d": profile.get("ic_1d"),
            "ic_5d": profile.get("ic_5d"),
            "ic_60d": profile.get("ic_60d"),
            "ic_120d": profile.get("ic_120d"),
            "optimal_horizon": profile.get("optimal_horizon"),
            "monotonicity": profile.get("monotonicity"),
            "monotonicity_note": profile.get("monotonicity_note"),
            "ic_bull": profile.get("ic_bull"),
            "ic_bear": profile.get("ic_bear"),
            "ic_sideways": profile.get("ic_sideways"),
            "regime_sensitivity": profile.get("regime_sensitivity"),
            "top_q_turnover_monthly": profile.get("top_q_turnover_monthly"),
            "cost_feasible": profile.get("cost_feasible"),
            "estimated_annual_cost": profile.get("estimated_annual_cost"),
            "max_corr_factor": profile.get("max_corr_factor"),
            "max_corr_value": profile.get("max_corr_value"),
            "redundant_with": profile.get("redundant_with"),
            "recommended_template": profile.get("recommended_template"),
            "recommendation_reason": profile.get("recommendation_reason"),
            "rank_autocorr_5d": profile.get("rank_autocorr_5d"),
            "rank_autocorr_20d": profile.get("rank_autocorr_20d"),
            "avg_daily_coverage": profile.get("avg_daily_coverage"),
        }

        # Verdicts
        verdicts = []
        ic_20d = profile.get("ic_20d")
        ic_tstat = profile.get("ic_20d_tstat")
        if ic_tstat and abs(ic_tstat) > 2.5:
            verdicts.append(f"✅ IC significance: t={ic_tstat:.2f} > 2.5")
        else:
            verdicts.append(f"❌ IC significance: t={ic_tstat} < 2.5")

        mono = profile.get("monotonicity")
        if mono and mono > 0.6:
            verdicts.append(f"✅ Monotonicity: {mono:.3f} > 0.6")
        elif mono and mono > 0.4:
            verdicts.append(f"⚠️ Monotonicity: {mono:.3f} borderline")
        else:
            verdicts.append(f"❌ Monotonicity: {mono} < 0.4")

        ic_bull = profile.get("ic_bull")
        ic_bear = profile.get("ic_bear")
        if ic_bull is not None and ic_bear is not None:
            if ic_bull != 0 and ic_bear != 0:
                same_sign = (ic_bull > 0) == (ic_bear > 0)
                if same_sign:
                    verdicts.append(f"✅ Regime stable: bull={ic_bull:.4f}, bear={ic_bear:.4f}")
                else:
                    verdicts.append(f"❌ Regime FLIP: bull={ic_bull:.4f}, bear={ic_bear:.4f}")
            else:
                verdicts.append(f"⚠️ Regime: bull={ic_bull}, bear={ic_bear} (zero)")

        max_corr = profile.get("max_corr_value")
        max_corr_f = profile.get("max_corr_factor")
        if max_corr is not None and abs(max_corr) < 0.7:
            verdicts.append(f"✅ Redundancy OK: max |corr|={max_corr:.3f} with {max_corr_f}")
        elif max_corr is not None:
            verdicts.append(f"⚠️ Redundancy: |corr|={max_corr:.3f} with {max_corr_f}")

        key_dims["verdicts"] = verdicts
        results[factor_name] = key_dims

        print(f"\n  === {factor_name} Profile Summary ===")
        print(f"  IC(20d)={ic_20d}, t={ic_tstat}")
        print(f"  Monotonicity={mono}")
        print(
            f"  Regime: bull={ic_bull}, bear={ic_bear}, sensitivity={profile.get('regime_sensitivity')}"
        )
        print(f"  Max corr: {max_corr_f}={max_corr}")
        print(f"  Cost feasible: {profile.get('cost_feasible')}")
        for v in verdicts:
            print(f"  {v}")

    results["elapsed_min"] = round((time.time() - t0) / 60, 1)
    save_result(results, "q2_factor_profiles")
    print(f"\n  Q2 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q3: CORE3+RSQR+dv Annual Decomposition
# ======================================================================


def q3_annual_decomposition(data: AuditDataCache) -> dict:
    """Q3: Split full-period NAV into per-year Sharpe for CORE3+RSQR+dv."""
    print("\n" + "=" * 70)
    print("Q3: CORE3+RSQR+dv Annual Decomposition")
    print("=" * 70)

    t0 = time.time()

    # Run full-period backtest
    print("\n[1] Running full-period CORE3+RSQR+dv backtest...")
    t1 = time.time()
    result_best = run_backtest_full(
        data.best_factor_df,
        BEST_DIRECTIONS,
        data.price,
        data.bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=data.conn,
    )
    nav_best = result_best.daily_nav
    metrics_full = compute_metrics(nav_best)
    print(
        f"  Full period: Sharpe={metrics_full['sharpe']}, MDD={metrics_full['mdd']}, "
        f"AnnRet={metrics_full['annual_return']} ({time.time() - t1:.1f}s)"
    )

    # Also run baseline
    print("\n[2] Running full-period CORE5 baseline...")
    t1 = time.time()
    result_base = run_backtest_full(
        data.core5_parquet,
        CORE5_DIRECTIONS,
        data.price,
        data.bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=data.conn,
    )
    nav_base = result_base.daily_nav
    print(f"  Baseline done ({time.time() - t1:.1f}s)")

    # Split by year
    print("\n[3] Annual decomposition...")
    years = sorted(set(d.year for d in nav_best.index))
    yearly_results = []

    # Load cached EW yearly from Part 0.2
    cached_0_2 = None
    cached_path = PHASE24_CACHE / "part0_2_annual_decomposition.json"
    if cached_path.exists():
        with open(cached_path) as f:
            cached_0_2 = json.load(f)

    for year in years:
        # Slice NAV
        year_mask_best = [d.year == year for d in nav_best.index]
        year_mask_base = [d.year == year for d in nav_base.index]
        nav_y_best = nav_best[year_mask_best]
        nav_y_base = nav_base[year_mask_base]

        if len(nav_y_best) < 20:
            continue

        m_best = compute_metrics(nav_y_best)
        m_base = compute_metrics(nav_y_base)

        # Get cached EW yearly Sharpe
        ew_cached = None
        if cached_0_2 and "ew_yearly" in cached_0_2:
            ew_cached = cached_0_2["ew_yearly"].get(str(year))

        row = {
            "year": year,
            "core5_sharpe": m_base["sharpe"],
            "best_sharpe": m_best["sharpe"],
            "diff": round(m_best["sharpe"] - m_base["sharpe"], 4),
            "core5_return": m_base["total_return"],
            "best_return": m_best["total_return"],
            "core5_mdd": m_base["mdd"],
            "best_mdd": m_best["mdd"],
            "n_days": m_best["n_days"],
            "ew_cached_sharpe": ew_cached,
        }
        yearly_results.append(row)
        print(
            f"  {year}: CORE5={m_base['sharpe']:.4f}, BEST={m_best['sharpe']:.4f}, "
            f"diff={row['diff']:+.4f}, ret_best={m_best['total_return']:+.4f}"
        )

    # Concentration analysis
    if yearly_results:
        best_year = max(yearly_results, key=lambda r: r["best_return"])
        total_return = metrics_full["total_return"]
        concentration = abs(best_year["best_return"]) / max(abs(total_return), 0.01)

        # Count years where best beats baseline
        n_better = sum(1 for r in yearly_results if r["diff"] > 0)
        sum(1 for r in yearly_results if r["diff"] < 0)

        # 2022-2023 check
        crisis_years = [r for r in yearly_results if r["year"] in (2022, 2023)]

        print("\n  === Concentration Analysis ===")
        print(f"  Best year: {best_year['year']} (return={best_year['best_return']:+.4f})")
        print(f"  Total return: {total_return:+.4f}")
        print(f"  Concentration ratio: {concentration:.2f}")
        print(f"  Years CORE3+RSQR+dv > CORE5: {n_better}/{len(yearly_results)}")
        for cy in crisis_years:
            print(
                f"  Crisis {cy['year']}: CORE5={cy['core5_sharpe']:.4f}, "
                f"BEST={cy['best_sharpe']:.4f}, diff={cy['diff']:+.4f}"
            )
    else:
        concentration = None
        n_better = 0

    results = {
        "full_period_best": metrics_full,
        "yearly": yearly_results,
        "concentration_ratio": round(concentration, 4) if concentration else None,
        "n_years_better": n_better,
        "n_years_total": len(yearly_results),
        "elapsed_min": round((time.time() - t0) / 60, 1),
    }
    save_result(results, "q3_annual_decomposition")
    print(f"\n  Q3 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q4: IC Significant but Sharpe≈0 in Mid-Cap
# ======================================================================


def q4_midcap_ic_vs_cost(data: AuditDataCache) -> dict:
    """Q4: Compute mid-cap composite IC and cost attribution."""
    print("\n" + "=" * 70)
    print("Q4: Mid-Cap IC vs Cost — Why IC Significant but Sharpe≈0")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn

    # Filter CORE5 to mid-cap (100-500亿 = 100e8-500e8 元)
    MIN_YUAN = 100e8
    MAX_YUAN = 500e8

    print("\n[1] Loading mid-cap factor data...")
    core5 = data.core5_parquet
    mcap = data.mcap_df
    midcap_factor = filter_factor_by_mcap(core5, mcap, MIN_YUAN, MAX_YUAN)
    n_stocks_per_date = midcap_factor.groupby("trade_date")["code"].nunique()
    print(
        f"  Mid-cap factors: {len(midcap_factor):,} rows, "
        f"avg stocks/date: {n_stocks_per_date.mean():.0f}"
    )

    # Compute composite IC
    print("\n[2] Computing mid-cap composite IC...")

    price = data.price
    bench = data.bench

    # Get rebalance dates
    factor_dates = sorted(midcap_factor["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(factor_dates)

    ic_values = []
    for rd in monthly_dates:
        day_data = midcap_factor[midcap_factor["trade_date"] == rd]
        if day_data.empty:
            continue
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if len(scores) < 30:
            continue

        # Forward 20d returns
        price_rd = price[price["trade_date"] >= rd].sort_values("trade_date")
        unique_dates = sorted(price_rd["trade_date"].unique())
        if len(unique_dates) < 22:
            continue
        t_plus_20 = unique_dates[min(20, len(unique_dates) - 1)]

        price_t0 = price_rd[price_rd["trade_date"] == rd].set_index("code")["close"]
        price_t20 = price_rd[price_rd["trade_date"] == t_plus_20].set_index("code")["close"]

        bench_t0 = bench[bench["trade_date"] == rd]["close"].values
        bench_t20 = bench[bench["trade_date"] == t_plus_20]["close"].values
        if len(bench_t0) == 0 or len(bench_t20) == 0:
            continue
        bench_ret = bench_t20[0] / bench_t0[0] - 1

        common = scores.index.intersection(price_t0.index).intersection(price_t20.index)
        if len(common) < 20:
            continue

        fwd_ret = price_t20[common] / price_t0[common] - 1 - bench_ret
        corr, _ = scipy_stats.spearmanr(scores[common], fwd_ret[common])
        if not np.isnan(corr):
            ic_values.append({"date": rd, "ic": corr})

    ic_series = pd.DataFrame(ic_values)
    if len(ic_series) > 0:
        ic_mean = ic_series["ic"].mean()
        ic_std = ic_series["ic"].std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        ic_tstat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0
        ic_positive = (ic_series["ic"] > 0).mean()
    else:
        ic_mean = ic_std = ic_ir = ic_tstat = ic_positive = 0

    print(
        f"  Mid-cap composite IC: mean={ic_mean:.4f}, std={ic_std:.4f}, "
        f"IR={ic_ir:.4f}, t={ic_tstat:.2f}, %pos={ic_positive:.1%}"
    )

    # Run mid-cap backtest to get turnover
    print("\n[3] Running mid-cap backtest (Top-20, no SN)...")
    t1 = time.time()
    result_midcap = run_backtest_full(
        midcap_factor,
        CORE5_DIRECTIONS,
        price,
        bench,
        top_n=20,
        sn_beta=0.0,
        conn=conn,
    )
    metrics_midcap = compute_metrics(result_midcap.daily_nav)
    turnover = result_midcap.turnover_series if hasattr(result_midcap, "turnover_series") else None
    avg_monthly_turnover = (
        float(turnover.mean()) if turnover is not None and len(turnover) > 0 else 0.4
    )
    annual_turnover = avg_monthly_turnover * 12
    print(
        f"  Mid-cap Sharpe={metrics_midcap['sharpe']}, MDD={metrics_midcap['mdd']}, "
        f"turnover_monthly={avg_monthly_turnover:.2%} ({time.time() - t1:.1f}s)"
    )

    # Cost estimation
    single_side_cost = 0.001  # ~10bps (commission + stamp + slippage)
    annual_cost = annual_turnover * 2 * single_side_cost
    annual_return = metrics_midcap["annual_return"]

    # Theoretical alpha from IC (Grinold's fundamental law)
    # alpha ≈ IC × sigma_alpha × sqrt(breadth)
    # Rough: alpha ≈ IC × 0.20 × sqrt(12) ≈ IC × 0.69
    theoretical_alpha = ic_mean * 0.20 * np.sqrt(12) if ic_mean > 0 else 0

    print("\n  === Q4 Cost Attribution ===")
    print("  Full-A composite IC:    0.1130 (from Part 0.5)")
    print(f"  Mid-cap composite IC:   {ic_mean:.4f}")
    print(f"  IC ratio (mid/full):    {ic_mean / 0.113:.2f}")
    print(f"  Annual turnover:        {annual_turnover:.1%}")
    print(f"  Est. annual cost:       {annual_cost:.2%}")
    print(f"  Theoretical alpha:      {theoretical_alpha:.2%}")
    print(f"  Backtest annual return: {annual_return:.2%}")
    print(f"  Mid-cap Sharpe:         {metrics_midcap['sharpe']}")

    results = {
        "midcap_composite_ic": {
            "mean": round(ic_mean, 4),
            "std": round(ic_std, 4),
            "ir": round(ic_ir, 4),
            "tstat": round(ic_tstat, 2),
            "pct_positive": round(ic_positive, 4),
            "n_months": len(ic_series),
        },
        "full_a_composite_ic": 0.1130,
        "ic_ratio_mid_vs_full": round(ic_mean / 0.113, 4) if ic_mean > 0 else 0,
        "midcap_backtest": metrics_midcap,
        "avg_monthly_turnover": round(avg_monthly_turnover, 4),
        "annual_turnover": round(annual_turnover, 4),
        "est_annual_cost": round(annual_cost, 4),
        "theoretical_alpha": round(theoretical_alpha, 4),
        "elapsed_min": round((time.time() - t0) / 60, 1),
    }
    save_result(results, "q4_midcap_ic_vs_cost")
    print(f"\n  Q4 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q5: Top-N Monotonic Increase Root Cause
# ======================================================================


def q5_topn_analysis(data: AuditDataCache) -> dict:
    """Q5: Extended Top-N analysis — turnover, mcap, score concentration."""
    print("\n" + "=" * 70)
    print("Q5: Top-N Monotonic Increase — Root Cause Analysis")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn
    price = data.price
    bench = data.bench
    core5 = data.core5_parquet
    mcap = data.mcap_df

    TOP_NS = [10, 15, 20, 25, 30, 40]
    results_by_n = {}

    for n in TOP_NS:
        print(f"\n[{n}] Top-{n} extended analysis...")
        t1 = time.time()

        # Run backtest
        result = run_backtest_full(
            core5,
            CORE5_DIRECTIONS,
            price,
            bench,
            top_n=n,
            sn_beta=SN_BETA,
            conn=conn,
        )
        metrics = compute_metrics(result.daily_nav)

        # Turnover
        turnover = result.turnover_series if hasattr(result, "turnover_series") else None
        avg_turnover = (
            float(turnover.mean()) if turnover is not None and len(turnover) > 0 else None
        )

        # Market cap distribution from holdings
        holdings = result.holdings_history if hasattr(result, "holdings_history") else {}
        mcap_stats = {"mean_yi": [], "median_yi": [], "pct_micro": [], "pct_large": []}

        for hdate, stocks in holdings.items():
            if not stocks:
                continue
            codes = list(stocks.keys())
            day_mcap = mcap[(mcap["trade_date"] == hdate) & (mcap["code"].isin(codes))]
            if day_mcap.empty:
                continue
            mv_yi = day_mcap["total_mv"].values * YUAN_TO_YI
            mcap_stats["mean_yi"].append(float(np.mean(mv_yi)))
            mcap_stats["median_yi"].append(float(np.median(mv_yi)))
            mcap_stats["pct_micro"].append(float((mv_yi < 100).mean()))
            mcap_stats["pct_large"].append(float((mv_yi > 500).mean()))

        avg_mcap_yi = np.mean(mcap_stats["mean_yi"]) if mcap_stats["mean_yi"] else None
        avg_pct_micro = np.mean(mcap_stats["pct_micro"]) if mcap_stats["pct_micro"] else None
        avg_pct_large = np.mean(mcap_stats["pct_large"]) if mcap_stats["pct_large"] else None

        row = {
            "top_n": n,
            "sharpe": metrics["sharpe"],
            "mdd": metrics["mdd"],
            "annual_return": metrics["annual_return"],
            "avg_monthly_turnover": round(avg_turnover, 4) if avg_turnover else None,
            "avg_mcap_yi": round(avg_mcap_yi, 1) if avg_mcap_yi else None,
            "avg_pct_micro": round(avg_pct_micro, 4) if avg_pct_micro else None,
            "avg_pct_large": round(avg_pct_large, 4) if avg_pct_large else None,
        }
        results_by_n[n] = row
        print(
            f"  Top-{n}: Sharpe={metrics['sharpe']}, turnover={avg_turnover:.3f}, "
            f"mcap={avg_mcap_yi:.0f}亿, micro={avg_pct_micro:.1%}, "
            f"large={avg_pct_large:.1%} ({time.time() - t1:.1f}s)"
        )

    # Composite score analysis for Top-20 vs Top-40
    print("\n[Score] Composite score concentration analysis...")
    factor_dates = sorted(core5["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(sorted(price["trade_date"].unique()))
    monthly_dates = [d for d in monthly_dates if OOS_START <= d <= OOS_END]

    score_diffs = {"top20_mean": [], "top40_mean": [], "rank21_40_mean": []}
    for rd in monthly_dates[:24]:  # Sample first 24 months for speed
        day_data = core5[core5["trade_date"] == rd]
        if day_data.empty:
            # Find nearest factor date
            idx = bisect_right(factor_dates, rd)
            if idx == 0:
                continue
            fd = factor_dates[idx - 1]
            day_data = core5[core5["trade_date"] == fd]
        if day_data.empty:
            continue
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if len(scores) < 40:
            continue
        top40 = scores.nlargest(40)
        top20 = scores.nlargest(20)
        rank21_40 = top40.iloc[20:]
        score_diffs["top20_mean"].append(float(top20.mean()))
        score_diffs["top40_mean"].append(float(top40.mean()))
        score_diffs["rank21_40_mean"].append(float(rank21_40.mean()))

    avg_scores = {k: round(np.mean(v), 4) if v else None for k, v in score_diffs.items()}
    print(
        f"  Avg composite scores: Top-20={avg_scores['top20_mean']}, "
        f"Top-40={avg_scores['top40_mean']}, Rank21-40={avg_scores['rank21_40_mean']}"
    )

    # Summary table
    print(
        f"\n  {'Top-N':>6} {'Sharpe':>8} {'MDD':>8} {'Turnover':>10} "
        f"{'AvgMcap亿':>10} {'%Micro':>8} {'%Large':>8}"
    )
    print(f"  {'-' * 62}")
    for n in TOP_NS:
        r = results_by_n[n]
        print(
            f"  {n:>6} {r['sharpe']:>8.4f} {r['mdd']:>8.4f} "
            f"{r['avg_monthly_turnover']:>10.4f} {r['avg_mcap_yi']:>10.0f} "
            f"{r['avg_pct_micro']:>8.1%} {r['avg_pct_large']:>8.1%}"
        )

    results = {
        "by_topn": results_by_n,
        "composite_score_analysis": avg_scores,
        "elapsed_min": round((time.time() - t0) / 60, 1),
    }
    save_result(results, "q5_topn_analysis")
    print(f"\n  Q5 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q6: Quarterly vs Monthly Cost Attribution
# ======================================================================


def q6_cost_attribution(data: AuditDataCache) -> dict:
    """Q6: Zero-cost backtests to decompose cost vs signal effects."""
    print("\n" + "=" * 70)
    print("Q6: Quarterly vs Monthly — Cost Attribution")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn
    price = data.price
    bench = data.bench
    core5 = data.core5_parquet

    from engines.backtest.config import BacktestConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    results = {}

    # Zero-cost config
    zero_cost_config = BacktestConfig(
        top_n=20,
        rebalance_freq="monthly",
        initial_capital=1_000_000,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        transfer_fee_rate=0.0,
        slippage_bps=0.0,
        slippage_mode="fixed",
        historical_stamp_tax=False,
    )

    # 1. Monthly standard cost
    print("\n[1] Monthly + standard cost...")
    t1 = time.time()
    result_m_std = run_backtest_full(
        core5,
        CORE5_DIRECTIONS,
        price,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    metrics_m_std = compute_metrics(result_m_std.daily_nav)
    turnover_m = result_m_std.turnover_series if hasattr(result_m_std, "turnover_series") else None
    avg_turn_m = float(turnover_m.mean()) if turnover_m is not None and len(turnover_m) > 0 else 0
    print(
        f"  Sharpe={metrics_m_std['sharpe']}, turnover={avg_turn_m:.3f} ({time.time() - t1:.1f}s)"
    )
    results["monthly_standard"] = {**metrics_m_std, "avg_monthly_turnover": round(avg_turn_m, 4)}

    # 2. Monthly zero cost
    print("\n[2] Monthly + zero cost...")
    t1 = time.time()
    result_m_zero = run_backtest_full(
        core5,
        CORE5_DIRECTIONS,
        price,
        bench,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
        bt_config_override=zero_cost_config,
    )
    metrics_m_zero = compute_metrics(result_m_zero.daily_nav)
    print(f"  Sharpe={metrics_m_zero['sharpe']} ({time.time() - t1:.1f}s)")
    results["monthly_zero_cost"] = metrics_m_zero

    # Build quarterly portfolios
    print("\n[3] Building quarterly portfolios...")
    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
    all_price_dates = sorted(price["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [d for d in monthly_dates if OOS_START <= d <= OOS_END]
    factor_date_list = sorted(core5["trade_date"].unique())
    quarterly_dates = monthly_dates[::3]

    target_portfolios_q = {}
    for rd in quarterly_dates:
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]
        day_data = core5[core5["trade_date"] == fd]
        if day_data.empty:
            continue
        exclude = build_exclusion_set(price, rd)
        day_data = day_data[~day_data["code"].isin(exclude)]
        scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)
        if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[fd], SN_BETA)
        top20 = scores.nlargest(20)
        if len(top20) < 3:
            continue
        w = 1.0 / len(top20)
        target_portfolios_q[rd] = {code: w for code in top20.index}

    # 3. Quarterly standard cost
    print(f"\n[4] Quarterly + standard cost ({len(target_portfolios_q)} rebalances)...")
    t1 = time.time()
    bt_config_std = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config_std)
    result_q_std = tester.run(target_portfolios_q, price, bench)
    metrics_q_std = compute_metrics(result_q_std.daily_nav)
    turnover_q = result_q_std.turnover_series if hasattr(result_q_std, "turnover_series") else None
    avg_turn_q = float(turnover_q.mean()) if turnover_q is not None and len(turnover_q) > 0 else 0
    print(
        f"  Sharpe={metrics_q_std['sharpe']}, turnover={avg_turn_q:.3f} ({time.time() - t1:.1f}s)"
    )
    results["quarterly_standard"] = {**metrics_q_std, "avg_monthly_turnover": round(avg_turn_q, 4)}

    # 4. Quarterly zero cost
    print("\n[5] Quarterly + zero cost...")
    t1 = time.time()
    tester_zero = SimpleBacktester(zero_cost_config)
    result_q_zero = tester_zero.run(target_portfolios_q, price, bench)
    metrics_q_zero = compute_metrics(result_q_zero.daily_nav)
    print(f"  Sharpe={metrics_q_zero['sharpe']} ({time.time() - t1:.1f}s)")
    results["quarterly_zero_cost"] = metrics_q_zero

    # Attribution
    cost_drag_monthly = round(metrics_m_zero["sharpe"] - metrics_m_std["sharpe"], 4)
    cost_drag_quarterly = round(metrics_q_zero["sharpe"] - metrics_q_std["sharpe"], 4)
    signal_effect = round(metrics_m_zero["sharpe"] - metrics_q_zero["sharpe"], 4)

    results["attribution"] = {
        "cost_drag_monthly": cost_drag_monthly,
        "cost_drag_quarterly": cost_drag_quarterly,
        "signal_effect_zero_cost": signal_effect,
        "interpretation": (
            "monthly_signal_better"
            if signal_effect > 0.05
            else "quarterly_signal_equivalent"
            if signal_effect > -0.05
            else "quarterly_signal_better"
        ),
    }

    print("\n  === Q6 Attribution ===")
    print(f"  {'Config':<25} {'Sharpe':>8} {'AnnRet':>8}")
    print(f"  {'-' * 43}")
    print(
        f"  {'Monthly standard':<25} {metrics_m_std['sharpe']:>8.4f} {metrics_m_std['annual_return']:>8.4f}"
    )
    print(
        f"  {'Monthly zero-cost':<25} {metrics_m_zero['sharpe']:>8.4f} {metrics_m_zero['annual_return']:>8.4f}"
    )
    print(
        f"  {'Quarterly standard':<25} {metrics_q_std['sharpe']:>8.4f} {metrics_q_std['annual_return']:>8.4f}"
    )
    print(
        f"  {'Quarterly zero-cost':<25} {metrics_q_zero['sharpe']:>8.4f} {metrics_q_zero['annual_return']:>8.4f}"
    )
    print(f"\n  Cost drag (monthly):  {cost_drag_monthly:+.4f} Sharpe")
    print(f"  Cost drag (quarterly): {cost_drag_quarterly:+.4f} Sharpe")
    print(f"  Signal effect (zero-cost monthly - quarterly): {signal_effect:+.4f}")
    print(f"  Interpretation: {results['attribution']['interpretation']}")

    results["elapsed_min"] = round((time.time() - t0) / 60, 1)
    save_result(results, "q6_cost_attribution")
    print(f"\n  Q6 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q7: LambdaRank Signal Conflict Analysis
# ======================================================================


def q7_lambdarank_conflict(data: AuditDataCache) -> dict:
    """Q7: Cross-sectional correlation and overlap between LR and CORE5."""
    print("\n" + "=" * 70)
    print("Q7: LambdaRank Signal Conflict — Correlation & Overlap")
    print("=" * 70)

    t0 = time.time()
    lr_df = data.lr_predictions

    if lr_df.empty:
        print("  ERROR: LambdaRank predictions not available")
        return {"error": "lr_predictions_missing"}

    core5 = data.core5_parquet
    price = data.price

    # Get prediction column name
    pred_col = "prediction" if "prediction" in lr_df.columns else lr_df.columns[-1]
    print(f"  LR prediction column: {pred_col}")
    print(f"  LR date range: {lr_df['trade_date'].min()} ~ {lr_df['trade_date'].max()}")

    # Compute CORE5 composite scores for each LR date
    lr_dates = sorted(lr_df["trade_date"].unique())
    factor_dates = sorted(core5["trade_date"].unique())

    corr_values = []
    overlap_values = []

    # Use monthly rebalance dates for efficiency
    all_price_dates = sorted(price["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [
        d
        for d in monthly_dates
        if d in set(lr_dates) or any(abs((d - ld).days) < 3 for ld in lr_dates[:5])
    ]

    # Match each monthly date to nearest LR date
    for rd in monthly_dates:
        # Find nearest LR date
        lr_match = min(lr_dates, key=lambda d: abs((d - rd).days)) if lr_dates else None
        if lr_match is None or abs((lr_match - rd).days) > 5:
            continue

        # LR scores for this date
        lr_day = lr_df[lr_df["trade_date"] == lr_match].set_index("code")[pred_col]

        # CORE5 scores for nearest factor date
        idx = bisect_right(factor_dates, rd)
        if idx == 0:
            continue
        fd = factor_dates[idx - 1]
        day_data = core5[core5["trade_date"] == fd]
        if day_data.empty:
            continue
        core5_scores = compute_composite_scores(day_data, CORE5_DIRECTIONS)

        # Common stocks
        common = lr_day.index.intersection(core5_scores.index)
        if len(common) < 50:
            continue

        # Cross-sectional Spearman correlation
        corr, _ = scipy_stats.spearmanr(lr_day[common], core5_scores[common])
        if not np.isnan(corr):
            corr_values.append({"date": rd, "corr": corr})

        # Top-20 overlap
        lr_top20 = lr_day[common].nlargest(20).index
        core5_top20 = core5_scores[common].nlargest(20).index
        overlap = len(set(lr_top20) & set(core5_top20))
        overlap_values.append({"date": rd, "overlap": overlap})

    corr_df = pd.DataFrame(corr_values) if corr_values else pd.DataFrame()
    overlap_df = pd.DataFrame(overlap_values) if overlap_values else pd.DataFrame()

    if len(corr_df) > 0:
        mean_corr = corr_df["corr"].mean()
        std_corr = corr_df["corr"].std()
        pct_positive = (corr_df["corr"] > 0).mean()
    else:
        mean_corr = std_corr = pct_positive = 0

    if len(overlap_df) > 0:
        mean_overlap = overlap_df["overlap"].mean()
        min_overlap = overlap_df["overlap"].min()
        max_overlap = overlap_df["overlap"].max()
    else:
        mean_overlap = min_overlap = max_overlap = 0

    print("\n  === Q7 Results ===")
    print("  Cross-sectional correlation (LR vs CORE5):")
    print(f"    Mean: {mean_corr:.4f}, Std: {std_corr:.4f}, %positive: {pct_positive:.1%}")
    print(f"    N months: {len(corr_df)}")
    print("  Top-20 overlap:")
    print(f"    Mean: {mean_overlap:.1f}/20, Min: {min_overlap}, Max: {max_overlap}")

    # Verdict
    if mean_corr < 0.1 and mean_overlap < 5:
        verdict = "❌ Fundamentally different strategies — merge destroys both signals"
    elif mean_corr > 0.3:
        verdict = "⚠️ Partially correlated but merger still hurts — ranking distortion"
    else:
        verdict = f"⚠️ Weak correlation ({mean_corr:.3f}), low overlap ({mean_overlap:.1f}/20)"
    print(f"  Verdict: {verdict}")

    results = {
        "cross_sectional_corr": {
            "mean": round(mean_corr, 4),
            "std": round(std_corr, 4),
            "pct_positive": round(pct_positive, 4),
            "n_months": len(corr_df),
        },
        "top20_overlap": {
            "mean": round(mean_overlap, 2),
            "min": int(min_overlap),
            "max": int(max_overlap),
        },
        "verdict": verdict,
        "elapsed_min": round((time.time() - t0) / 60, 1),
    }
    save_result(results, "q7_lambdarank_conflict")
    print(f"\n  Q7 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q8: RSQR Cross-Sectional Correlations
# ======================================================================


def q8_rsqr_crosssectional_corr(data: AuditDataCache) -> dict:
    """Q8: Cross-sectional factor value correlations (7x7 matrix)."""
    print("\n" + "=" * 70)
    print("Q8: RSQR Cross-Sectional Factor Correlations (7x7)")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn

    # Load all 7 factors as wide pivots
    print("\n[1] Loading factor values for 7 factors...")
    core5 = data.core5_parquet

    # CRITICAL: RSQR_20 neutral_value is all NaN in DB (float NaN, not SQL NULL)
    # COALESCE returns NaN instead of falling through to raw_value
    # Must load raw_value directly for RSQR_20
    db_factors_query = """
        SELECT code, trade_date, factor_name,
               CASE WHEN factor_name = 'RSQR_20'
                    THEN raw_value
                    ELSE COALESCE(neutral_value, raw_value)
               END AS raw_value
        FROM factor_values
        WHERE factor_name IN ('RSQR_20', 'dv_ttm')
          AND trade_date >= %s AND trade_date <= %s
          AND raw_value IS NOT NULL
    """
    db_factors = pd.read_sql(db_factors_query, conn, params=[OOS_START, OOS_END])
    db_factors["trade_date"] = pd.to_datetime(db_factors["trade_date"]).dt.date
    print(
        f"  DB factors (fixed): {len(db_factors):,} rows, factors: {sorted(db_factors['factor_name'].unique())}"
    )

    # Also check RSQR_20 NaN issue
    rsqr_data = db_factors[db_factors["factor_name"] == "RSQR_20"]
    rsqr_nan_pct = rsqr_data["raw_value"].isna().mean() * 100
    print(f"  RSQR_20 NaN% after fix: {rsqr_nan_pct:.1f}% ({len(rsqr_data):,} rows)")

    all_factors = pd.concat([core5, db_factors], ignore_index=True)

    # Build wide pivots per factor
    factor_pivots = {}
    for fname in ALL_7_FACTORS:
        fdata = all_factors[all_factors["factor_name"] == fname]
        if fdata.empty:
            print(f"  WARNING: {fname} has no data")
            continue
        pivot = fdata.pivot_table(index="trade_date", columns="code", values="raw_value")
        factor_pivots[fname] = pivot
        print(f"  {fname}: {pivot.shape[0]} dates x {pivot.shape[1]} stocks")

    # Compute cross-sectional correlations
    print("\n[2] Computing cross-sectional rank correlations...")
    factor_names = list(factor_pivots.keys())
    n_factors = len(factor_names)

    # Sample dates for speed
    all_dates = sorted(set.intersection(*[set(p.index) for p in factor_pivots.values()]))
    sample_dates = all_dates[::20]  # Every 20th date
    print(f"  Sampling {len(sample_dates)} dates out of {len(all_dates)}")

    corr_matrix = np.zeros((n_factors, n_factors))
    corr_counts = np.zeros((n_factors, n_factors))

    for td in sample_dates:
        for i in range(n_factors):
            for j in range(i + 1, n_factors):
                fi = factor_pivots[factor_names[i]]
                fj = factor_pivots[factor_names[j]]
                if td not in fi.index or td not in fj.index:
                    continue
                si = fi.loc[td].dropna()
                sj = fj.loc[td].dropna()
                common = si.index.intersection(sj.index)
                if len(common) < 30:
                    continue
                corr, _ = scipy_stats.spearmanr(si[common], sj[common])
                if not np.isnan(corr):
                    corr_matrix[i, j] += corr
                    corr_matrix[j, i] += corr
                    corr_counts[i, j] += 1
                    corr_counts[j, i] += 1

    # Average correlations
    avg_corr = np.zeros((n_factors, n_factors))
    for i in range(n_factors):
        avg_corr[i, i] = 1.0
        for j in range(i + 1, n_factors):
            if corr_counts[i, j] > 0:
                avg_corr[i, j] = corr_matrix[i, j] / corr_counts[i, j]
                avg_corr[j, i] = avg_corr[i, j]

    # Print matrix
    print("\n  Cross-sectional Spearman Rank Correlation Matrix:")
    print(f"  {'':>20}", end="")
    for fn in factor_names:
        print(f" {fn[:10]:>10}", end="")
    print()
    for i, fn in enumerate(factor_names):
        print(f"  {fn:>20}", end="")
        for j in range(n_factors):
            print(f" {avg_corr[i, j]:>10.3f}", end="")
        print()

    # Key pairs
    print("\n  === Key Pairs ===")
    key_pairs = [
        ("RSQR_20", "amihud_20"),
        ("RSQR_20", "reversal_20"),
        ("RSQR_20", "volatility_20"),
        ("dv_ttm", "bp_ratio"),
        ("dv_ttm", "amihud_20"),
    ]
    for f1, f2 in key_pairs:
        if f1 in factor_names and f2 in factor_names:
            i = factor_names.index(f1)
            j = factor_names.index(f2)
            val = avg_corr[i, j]
            flag = "⚠️" if abs(val) > 0.5 else "✅"
            print(f"  {flag} {f1} ↔ {f2}: {val:.3f}")

    # Build serializable results
    corr_dict = {}
    for i in range(n_factors):
        for j in range(i + 1, n_factors):
            key = f"{factor_names[i]}_vs_{factor_names[j]}"
            corr_dict[key] = round(avg_corr[i, j], 4)

    results = {
        "factor_names": factor_names,
        "correlation_matrix": [
            [round(avg_corr[i, j], 4) for j in range(n_factors)] for i in range(n_factors)
        ],
        "key_pairs": corr_dict,
        "n_sample_dates": len(sample_dates),
        "elapsed_min": round((time.time() - t0) / 60, 1),
    }
    save_result(results, "q8_rsqr_correlations")
    print(f"\n  Q8 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Q9: Style Diversification Supplementary Experiment
# ======================================================================


def q9_style_diversification(data: AuditDataCache) -> dict:
    """Q9: Skip justification + defensive portfolio supplementary experiment."""
    print("\n" + "=" * 70)
    print("Q9: Style Diversification — Skip Justification + Supplement")
    print("=" * 70)

    t0 = time.time()
    conn = data.conn
    price = data.price
    bench = data.bench

    results = {}

    # Part A: Document skip reasons
    print("\n[A] Part 4 skip reasons (code evidence):")
    print("  Part 4.1 (line 1948-1955): 'dv_ttm tested in Part 2.2/2.3' → SKIPPED")
    print("  Part 4.2 (line 1957-1970): 'Part 1 showed alpha is 100% micro-cap' → SKIPPED")
    print("  Part 4.3 (line 1972-1979): 'SN barbell proven optimal in Part 1' → SKIPPED")
    print("  铁律28: 发现即报告不选择性遗漏 — should have documented skip in report")
    results["skip_reasons"] = {
        "part4_1": "dv_ttm already tested in Part 2.2/2.3",
        "part4_2": "Alpha 100% micro-cap from Part 1.3 — style diversification deemed not viable",
        "part4_3": "SN barbell proven optimal",
        "compliance_issue": "Skip not documented in final report (铁律28 violation)",
    }

    # Part B: CORE3+RSQR+dv across cap ranges (new factors might change conclusions)
    print("\n[B] Testing CORE3+RSQR+dv across cap ranges...")
    best_factor = data.best_factor_df
    mcap = data.mcap_df

    MCAP_RANGES = {
        "全A+SN": (0, float("inf"), SN_BETA),
        "微小盘(<100亿)": (0, 100e8, 0.0),
        "中盘(100-500亿)": (100e8, 500e8, 0.0),
        "大盘(>500亿)": (500e8, float("inf"), 0.0),
    }

    # Load Part 1.3 CORE5 results for comparison
    part13_path = PHASE24_CACHE / "part1_3_mcap_range_comparison.json"
    part13 = {}
    if part13_path.exists():
        with open(part13_path) as f:
            part13_data = json.load(f)
        if isinstance(part13_data, list):
            for item in part13_data:
                label = item.get("label", "")
                part13[label] = item

    cap_results = []
    for label, (min_y, max_y, sn) in MCAP_RANGES.items():
        print(f"\n  {label}...")
        t1 = time.time()

        if min_y == 0 and max_y == float("inf"):
            fdf = best_factor
        else:
            fdf = filter_factor_by_mcap(best_factor, mcap, min_y, max_y)

        if len(fdf) < 1000:
            print(f"    Too few rows ({len(fdf)}), skipping")
            continue

        metrics = run_standard_experiment(
            fdf,
            BEST_DIRECTIONS,
            price,
            bench,
            top_n=20,
            sn_beta=sn,
            conn=conn,
            label=f"BEST_{label}",
        )

        # Compare with CORE5 Part 1.3
        core5_sharpe = None
        for k, v in part13.items():
            if label[:4] in k[:4]:  # fuzzy match
                core5_sharpe = v.get("sharpe")
                break

        row = {
            "label": label,
            "best_sharpe": metrics["sharpe"],
            "best_mdd": metrics["mdd"],
            "best_ann_return": metrics["annual_return"],
            "core5_sharpe": core5_sharpe,
        }
        cap_results.append(row)
        print(
            f"    BEST Sharpe={metrics['sharpe']}, CORE5 Sharpe={core5_sharpe} "
            f"({time.time() - t1:.1f}s)"
        )

    results["cap_range_comparison"] = cap_results

    # Part C: Defensive portfolio experiment
    print("\n[C] Defensive portfolio blend experiment...")
    from engines.backtest.config import BacktestConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(OOS_START, OOS_END, conn)
    core5 = data.core5_parquet

    all_price_dates = sorted(price["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_price_dates)
    monthly_dates = [d for d in monthly_dates if OOS_START <= d <= OOS_END]

    factor_date_list = sorted(core5["trade_date"].unique())

    # Load dv_ttm and volatility for defensive portfolio
    def_factors = load_factors_from_db(["dv_ttm", "volatility_20"], OOS_START, OOS_END, conn)

    # Build blended portfolios
    for blend_name, alpha_weight in [("70_30", 0.7), ("50_50", 0.5)]:
        print(f"\n  Building {blend_name} blend...")
        target_portfolios = {}

        for rd in monthly_dates:
            idx = bisect_right(factor_date_list, rd)
            if idx == 0:
                continue
            fd = factor_date_list[idx - 1]

            # Group A: Alpha (CORE5 + SN → Top-10)
            day_core5 = core5[core5["trade_date"] == fd]
            if day_core5.empty:
                continue
            exclude = build_exclusion_set(price, rd)
            day_core5 = day_core5[~day_core5["code"].isin(exclude)]
            scores_alpha = compute_composite_scores(day_core5, CORE5_DIRECTIONS)
            if ln_mcap_pivot is not None and fd in ln_mcap_pivot.index:
                scores_alpha = apply_size_neutral(scores_alpha, ln_mcap_pivot.loc[fd], SN_BETA)
            top10_alpha = scores_alpha.nlargest(10)

            # Group B: Defensive (dv_ttm(+1) + volatility_20(+1=low vol selected) → Top-10 from >500亿)
            day_def = def_factors[def_factors["trade_date"] == fd]
            day_def = day_def[~day_def["code"].isin(exclude)]

            # Filter to large-cap (>500亿元)
            day_mcap = mcap[(mcap["trade_date"] == rd)]
            large_cap_codes = set(day_mcap[day_mcap["total_mv"] >= 500e8]["code"])
            day_def = day_def[day_def["code"].isin(large_cap_codes)]

            if day_def.empty or len(day_def["code"].unique()) < 10:
                # Fallback: just alpha portfolio
                w = 1.0 / len(top10_alpha) if len(top10_alpha) > 0 else 0
                target_portfolios[rd] = {code: w for code in top10_alpha.index}
                continue

            # Defensive score: dv_ttm(+1) + volatility_20(+1) → selects high dividend + low vol
            # Note: volatility_20 direction +1 means higher factor value ranks higher
            # But we want LOW volatility, so direction should be -1 for defensive selection
            # Actually for "defensive" we want: high dv_ttm AND low volatility
            # So dv_ttm direction = +1, volatility_20 direction = +1 (reversed from alpha)
            # Wait - volatility_20 raw_value is already neutralized, higher = higher vol
            # For defensive: we want LOW vol, so direction = -1
            def_directions = {"dv_ttm": 1, "volatility_20": -1}
            scores_def = compute_composite_scores(day_def, def_directions)
            top10_def = scores_def.nlargest(10)

            # Merge with weights
            portfolio = {}
            w_alpha = alpha_weight / max(len(top10_alpha), 1)
            w_def = (1.0 - alpha_weight) / max(len(top10_def), 1)

            for code in top10_alpha.index:
                portfolio[code] = portfolio.get(code, 0) + w_alpha
            for code in top10_def.index:
                portfolio[code] = portfolio.get(code, 0) + w_def

            # Normalize
            total_w = sum(portfolio.values())
            if total_w > 0:
                portfolio = {k: v / total_w for k, v in portfolio.items()}
            target_portfolios[rd] = portfolio

        if not target_portfolios:
            print(f"    No portfolios built for {blend_name}")
            continue

        # Run backtest
        print(f"  Running {blend_name} backtest ({len(target_portfolios)} rebalances)...")
        t1 = time.time()
        bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
        tester = SimpleBacktester(bt_config)
        result_blend = tester.run(target_portfolios, price, bench)
        metrics_blend = compute_metrics(result_blend.daily_nav)

        # Annual breakdown for 2022-2023
        nav_blend = result_blend.daily_nav
        crisis_metrics = {}
        for year in [2022, 2023]:
            year_mask = [d.year == year for d in nav_blend.index]
            nav_y = nav_blend[year_mask]
            if len(nav_y) > 20:
                crisis_metrics[year] = compute_metrics(nav_y)

        results[f"blend_{blend_name}"] = {
            **metrics_blend,
            "n_rebal": len(target_portfolios),
            "crisis_2022": crisis_metrics.get(2022),
            "crisis_2023": crisis_metrics.get(2023),
        }
        print(
            f"    Sharpe={metrics_blend['sharpe']}, MDD={metrics_blend['mdd']} ({time.time() - t1:.1f}s)"
        )

    # Pure defensive (Group B only)
    print("\n  Running pure defensive portfolio...")
    target_portfolios_def = {}
    for rd in monthly_dates:
        idx = bisect_right(factor_date_list, rd)
        if idx == 0:
            continue
        fd = factor_date_list[idx - 1]
        day_def = def_factors[def_factors["trade_date"] == fd]
        exclude = build_exclusion_set(price, rd)
        day_def = day_def[~day_def["code"].isin(exclude)]
        day_mcap = mcap[(mcap["trade_date"] == rd)]
        large_cap_codes = set(day_mcap[day_mcap["total_mv"] >= 500e8]["code"])
        day_def = day_def[day_def["code"].isin(large_cap_codes)]
        if day_def.empty:
            continue
        scores_def = compute_composite_scores(day_def, {"dv_ttm": 1, "volatility_20": -1})
        top20_def = scores_def.nlargest(20)
        if len(top20_def) < 3:
            continue
        w = 1.0 / len(top20_def)
        target_portfolios_def[rd] = {code: w for code in top20_def.index}

    if target_portfolios_def:
        t1 = time.time()
        tester = SimpleBacktester(bt_config)
        result_def = tester.run(target_portfolios_def, price, bench)
        metrics_def = compute_metrics(result_def.daily_nav)

        nav_def = result_def.daily_nav
        crisis_def = {}
        for year in [2022, 2023]:
            year_mask = [d.year == year for d in nav_def.index]
            nav_y = nav_def[year_mask]
            if len(nav_y) > 20:
                crisis_def[year] = compute_metrics(nav_y)

        results["pure_defensive"] = {
            **metrics_def,
            "crisis_2022": crisis_def.get(2022),
            "crisis_2023": crisis_def.get(2023),
        }
        print(
            f"    Sharpe={metrics_def['sharpe']}, MDD={metrics_def['mdd']} ({time.time() - t1:.1f}s)"
        )

    # Summary table
    print("\n  === Q9 Summary ===")
    print(f"  {'Config':<25} {'Sharpe':>8} {'MDD':>8} {'AnnRet':>8}")
    print(f"  {'-' * 51}")
    for key in ["blend_70_30", "blend_50_50", "pure_defensive"]:
        if key in results:
            r = results[key]
            print(f"  {key:<25} {r['sharpe']:>8.4f} {r['mdd']:>8.4f} {r['annual_return']:>8.4f}")

    results["elapsed_min"] = round((time.time() - t0) / 60, 1)
    save_result(results, "q9_style_diversification")
    print(f"\n  Q9 elapsed: {results['elapsed_min']} min")
    return results


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description="Phase 2.4 Audit: 9 Critical Questions")
    parser.add_argument("--q1", action="store_true", help="Q1: Baseline reconciliation")
    parser.add_argument("--q2", action="store_true", help="Q2: Factor profiles")
    parser.add_argument("--q3", action="store_true", help="Q3: Annual decomposition")
    parser.add_argument("--q4", action="store_true", help="Q4: Mid-cap IC vs cost")
    parser.add_argument("--q5", action="store_true", help="Q5: Top-N root cause")
    parser.add_argument("--q6", action="store_true", help="Q6: Cost attribution")
    parser.add_argument("--q7", action="store_true", help="Q7: LR conflict")
    parser.add_argument("--q8", action="store_true", help="Q8: RSQR correlations")
    parser.add_argument("--q9", action="store_true", help="Q9: Style diversification")
    parser.add_argument("--all", action="store_true", help="Run all questions")
    args = parser.parse_args()

    run_all = args.all
    if not any(
        [args.q1, args.q2, args.q3, args.q4, args.q5, args.q6, args.q7, args.q8, args.q9, run_all]
    ):
        parser.print_help()
        return

    AUDIT_CACHE.mkdir(parents=True, exist_ok=True)
    data = AuditDataCache()
    total_t0 = time.time()

    try:
        # Execution order: Q1 → Q2 → Q8 → Q3 → Q4 → Q6 → Q7 → Q5 → Q9
        if args.q1 or run_all:
            q1_baseline_reconciliation(data)
            gc.collect()

        if args.q2 or run_all:
            q2_factor_profiles(data)
            gc.collect()

        if args.q8 or run_all:
            q8_rsqr_crosssectional_corr(data)
            gc.collect()

        if args.q3 or run_all:
            q3_annual_decomposition(data)
            gc.collect()

        if args.q4 or run_all:
            q4_midcap_ic_vs_cost(data)
            gc.collect()

        if args.q6 or run_all:
            q6_cost_attribution(data)
            gc.collect()

        if args.q7 or run_all:
            q7_lambdarank_conflict(data)
            gc.collect()

        if args.q5 or run_all:
            q5_topn_analysis(data)
            gc.collect()

        if args.q9 or run_all:
            q9_style_diversification(data)
            gc.collect()

    finally:
        data.close()

    total_elapsed = (time.time() - total_t0) / 60
    print(f"\n{'=' * 70}")
    print(f"Total elapsed: {total_elapsed:.1f} min")
    print(f"Results cached in: {AUDIT_CACHE}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
