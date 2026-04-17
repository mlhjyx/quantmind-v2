"""Phase 3E-II Track 2.5: WF validation for microstructure factor candidates.

Tests adding each top microstructure factor to CORE4 (CORE3+dv_ttm).
Microstructure data only covers 2019-2026 (~1750 trading days),
so we use 3-fold WF instead of 5-fold.

WF Config: train=750d, gap=5, test=250d, n_splits=3
PASS: OOS Sharpe > 0.8659 (current baseline)

Usage:
    python scripts/research/phase3e_wf_validate.py
    python scripts/research/phase3e_wf_validate.py --factor high_freq_volatility_20
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers
for name in ("engines.backtest", "engines.signal_engine", "engines.walk_forward",
             "engines.backtest.engine", "engines.backtest.broker"):
    logging.getLogger(name).setLevel(logging.WARNING)

# CORE4 baseline
CORE4_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "bp_ratio": 1,
    "dv_ttm": 1,
}
BASELINE_SHARPE = 0.8659  # WF OOS baseline (5-fold, 2014-2026)

# Top microstructure candidates by neutral IC (from ic_neutral_screen.csv)
# Direction = sign of neutral IC
TOP_CANDIDATES = [
    ("high_freq_volatility_20", -1),     # neutral_ic=-0.094
    ("volume_autocorr_20", -1),          # neutral_ic=-0.083
    ("intraday_kurtosis_20", -1),        # neutral_ic=-0.081
    ("intraday_skewness_20", -1),        # neutral_ic=-0.078
    ("max_intraday_drawdown_20", 1),     # neutral_ic=+0.078
    ("weighted_price_contribution_20", -1),  # neutral_ic=-0.070
]

OUT_DIR = Path("cache/phase3e")


def load_data(factor_names: list[str], start_date: str, end_date: str):
    """Load price, benchmark, CORE4 + microstructure factor data.

    Uses fresh connections per query to avoid PG timeout on large results.
    """
    from app.services.price_utils import _get_sync_conn

    t0 = time.time()

    # Price data (largest query — fresh connection)
    logger.info("Loading price data...")
    conn1 = _get_sync_conn()
    price_data = pd.read_sql(
        """WITH latest_af AS (
               SELECT DISTINCT ON (code) code, adj_factor AS latest_adj_factor
               FROM klines_daily WHERE adj_factor IS NOT NULL AND adj_factor > 0
               ORDER BY code, trade_date DESC
           )
           SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
                  COALESCE(k.adj_factor, 1.0) AS adj_factor,
                  CASE WHEN laf.latest_adj_factor > 0
                       THEN k.close * COALESCE(k.adj_factor, 1.0) / laf.latest_adj_factor
                       ELSE k.close END AS adj_close,
                  db.turnover_rate,
                  COALESCE(ss.is_st, FALSE) AS is_st,
                  COALESCE(ss.is_suspended, FALSE) AS is_suspended,
                  COALESCE(ss.is_new_stock, FALSE) AS is_new_stock,
                  ss.board
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN latest_af laf ON k.code = laf.code
           LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn1,
        params=(start_date, end_date),
    )
    conn1.close()
    logger.info("  price_data: %d rows (%.0fs)", len(price_data), time.time() - t0)

    # Benchmark + factor data + mcap (fresh connection)
    conn2 = _get_sync_conn()

    benchmark = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn2,
        params=(start_date, end_date),
    )

    # Factor data (all needed factors from DB)
    logger.info("Loading factor data for %d factors...", len(factor_names))
    t1 = time.time()
    factor_df = pd.read_sql(
        """SELECT code, trade_date, factor_name,
                  COALESCE(neutral_value, raw_value) as raw_value
           FROM factor_values
           WHERE factor_name IN %s AND trade_date BETWEEN %s AND %s
             AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)""",
        conn2,
        params=(tuple(factor_names), start_date, end_date),
    )
    logger.info("  factor_data: %d rows (%.0fs)", len(factor_df), time.time() - t1)

    # ln_mcap pivot for size-neutral
    logger.info("Loading ln_mcap for size-neutral...")
    mcap_df = pd.read_sql(
        """SELECT code, trade_date, total_mv FROM daily_basic
           WHERE trade_date BETWEEN %s AND %s AND total_mv > 0""",
        conn2,
        params=(start_date, end_date),
    )
    mcap_df["ln_mcap"] = np.log(mcap_df["total_mv"].astype(float) + 1e-12)
    ln_mcap_pivot = mcap_df.pivot_table(
        index="trade_date", columns="code", values="ln_mcap"
    )

    conn2.close()
    logger.info("All data loaded in %.0fs", time.time() - t0)
    return price_data, benchmark, factor_df, ln_mcap_pivot


def run_wf_for_config(
    config_name: str,
    directions: dict[str, int],
    factor_df: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame,
) -> dict:
    """Run 3-fold WF for a given factor configuration."""
    from engines.backtest.config import BacktestConfig, PMSConfig
    from engines.slippage_model import SlippageConfig
    from engines.walk_forward import WalkForwardEngine, WFConfig, make_equal_weight_signal_func

    wf_config = WFConfig(
        n_splits=3,
        train_window=750,
        gap=5,
        test_window=250,
    )

    bt_config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_bps=0,
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
        lot_size=100,
        benchmark_code="000300.SH",
    )

    # Filter factor_df to only needed factors
    needed = set(directions.keys())
    fdf = factor_df[factor_df["factor_name"].isin(needed)].copy()

    signal_func = make_equal_weight_signal_func(
        fdf, directions, price_data,
        top_n=20,
        rebalance_freq="monthly",
        size_neutral_beta=0.50,
        ln_mcap_pivot=ln_mcap_pivot,
    )

    engine = WalkForwardEngine(wf_config, bt_config)
    logger.info("[%s] Running 3-fold WF with factors: %s", config_name, list(directions.keys()))

    t0 = time.time()
    wf_result = engine.run(signal_func, price_data, benchmark)
    elapsed = time.time() - t0

    # Collect fold details
    fold_details = []
    for fr in wf_result.fold_results:
        fold_details.append({
            "fold": fr.fold_idx,
            "test_period": f"{fr.test_period[0]}~{fr.test_period[1]}",
            "oos_sharpe": round(fr.oos_sharpe, 4),
            "oos_mdd": round(fr.oos_mdd, 4),
            "oos_annual_return": round(fr.oos_annual_return, 4),
        })

    result = {
        "config_name": config_name,
        "factors": list(directions.keys()),
        "n_factors": len(directions),
        "oos_sharpe": round(wf_result.combined_oos_sharpe, 4),
        "oos_mdd": round(wf_result.combined_oos_mdd, 4),
        "oos_annual_return": round(wf_result.combined_oos_annual_return, 4),
        "oos_total_return": round(wf_result.combined_oos_total_return, 4),
        "total_oos_days": wf_result.total_oos_days,
        "negative_folds": sum(1 for fr in wf_result.fold_results if fr.oos_sharpe < 0),
        "folds": fold_details,
        "elapsed_s": round(elapsed, 0),
        "pass": wf_result.combined_oos_sharpe > BASELINE_SHARPE,
    }

    marker = "PASS" if result["pass"] else "FAIL"
    neg = result["negative_folds"]
    logger.info(
        "[%s] OOS Sharpe=%.4f, MDD=%.2f%%, %d neg folds -> %s (%.0fs)",
        config_name, result["oos_sharpe"], result["oos_mdd"] * 100,
        neg, marker, elapsed,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", type=str, help="Test single factor only")
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 3E-II Track 2.5: WF Validation")
    print(f"Baseline: CORE3+dv_ttm OOS Sharpe={BASELINE_SHARPE}")
    print("WF Config: 3-fold, train=750d, gap=5, test=250d")
    print("=" * 70)

    # Determine which factors to test
    if args.factor:
        # Find direction from TOP_CANDIDATES
        direction = None
        for name, d in TOP_CANDIDATES:
            if name == args.factor:
                direction = d
                break
        if direction is None:
            print(f"Unknown factor: {args.factor}")
            sys.exit(1)
        candidates = [(args.factor, direction)]
    else:
        candidates = TOP_CANDIDATES

    # All factor names needed (CORE4 + all candidates)
    all_factor_names = list(CORE4_DIRECTIONS.keys()) + [c[0] for c in candidates]
    all_factor_names = list(set(all_factor_names))

    # Load data once (2019-01-01 to 2026-04-13 for microstructure overlap)
    t0 = time.time()
    price_data, benchmark, factor_df, ln_mcap_pivot = load_data(
        all_factor_names, "2019-01-01", "2026-04-13"
    )

    # Run baseline (CORE4 only, 3-fold on same period for fair comparison)
    print(f"\n{'=' * 70}")
    print("[Baseline] CORE4 only (3-fold, 2019-2026)")
    print(f"{'=' * 70}")
    baseline = run_wf_for_config(
        "CORE4_baseline", CORE4_DIRECTIONS,
        factor_df, price_data, benchmark, ln_mcap_pivot,
    )

    # Run each candidate (CORE4 + 1 microstructure factor)
    results = [baseline]
    for fname, direction in candidates:
        print(f"\n{'=' * 70}")
        print(f"[Test] CORE4 + {fname} (direction={direction:+d})")
        print(f"{'=' * 70}")

        test_directions = {**CORE4_DIRECTIONS, fname: direction}
        r = run_wf_for_config(
            f"CORE4+{fname}", test_directions,
            factor_df, price_data, benchmark, ln_mcap_pivot,
        )
        r["delta_sharpe"] = round(r["oos_sharpe"] - baseline["oos_sharpe"], 4)
        results.append(r)

    # Save results
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "wf_validation.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    # Summary
    print(f"\n{'=' * 70}")
    print("WF Validation Summary")
    print(f"{'=' * 70}")
    print(f"  {'Config':<45} {'Sharpe':>8} {'MDD':>8} {'Delta':>8} {'Result':>8}")
    print(f"  {'-' * 80}")
    for r in results:
        delta = r.get("delta_sharpe", 0)
        d_str = f"{delta:+.4f}" if delta else "---"
        marker = "PASS" if r["pass"] else "FAIL"
        print(
            f"  {r['config_name']:<45} "
            f"{r['oos_sharpe']:>8.4f} {r['oos_mdd']:>7.2%} "
            f"{d_str:>8} {marker:>8}"
        )

    pass_configs = [r for r in results[1:] if r["pass"]]
    print(f"\n  {len(pass_configs)}/{len(results)-1} candidates PASS (Sharpe > baseline {baseline['oos_sharpe']:.4f})")
    print(f"  Total time: {time.time() - t0:.0f}s")
    print(f"  Results: {out_path}")


if __name__ == "__main__":
    main()
