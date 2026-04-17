"""P0-6 part 2: 10 minute 因子噪声鲁棒性测试 (铁律 20).

对 neutral_value 加 N(0, σ) 高斯噪声, σ = noise_pct × std(clean).
retention = |noisy_IC| / |clean_IC|.

5% retention < 0.95: 警告
20% retention < 0.50: fragile, 不入 Active

输出: reports/p0_minute_g_robust.json
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "backend"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("g_robust")

MINUTE_FACTORS = [
    "high_freq_volatility_20", "volume_concentration_20", "volume_autocorr_20",
    "smart_money_ratio_20", "opening_volume_share_20", "closing_trend_strength_20",
    "vwap_deviation_20", "order_flow_imbalance_20", "intraday_momentum_20",
    "volume_price_divergence_20",
]
NOISE_PCTS = [0.05, 0.20]
HORIZON = 20


def main():
    from engines.ic_calculator import (
        compute_forward_excess_returns,
        compute_ic_series,
        summarize_ic_stats,
    )

    from app.services.data_orchestrator import DataOrchestrator

    t_all = time.time()
    orch = DataOrchestrator("2021-01-01", "2025-12-31")
    ctx = orch.shared_pool._ensure_loaded()
    benchmark_df = ctx["benchmark_df"]
    for col in ("close",):
        if col in benchmark_df.columns:
            benchmark_df[col] = benchmark_df[col].astype("float64")

    # price_df
    cur = orch._conn.cursor()
    cur.execute(
        """
        SELECT code, trade_date, close * COALESCE(adj_factor, 1.0) AS adj_close
        FROM klines_daily
        WHERE trade_date BETWEEN %s AND %s AND close IS NOT NULL
        """,
        ("2021-01-01", "2025-12-31"),
    )
    price_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "adj_close"])
    cur.close()
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df["adj_close"] = price_df["adj_close"].astype("float64")
    logger.info(f"price_df: {len(price_df):,} rows")

    fwd = compute_forward_excess_returns(price_df, benchmark_df, horizon=HORIZON)

    rng = np.random.default_rng(42)
    results = {}
    for fn in MINUTE_FACTORS:
        logger.info(f"[{fn}] ...")
        t0 = time.time()
        nv = orch.get_neutral_values(fn)
        if nv.empty:
            logger.warning(f"  {fn}: empty neutral_value, skip")
            continue
        nv["trade_date"] = pd.to_datetime(nv["trade_date"])
        factor_wide = nv.pivot_table(index="trade_date", columns="code", values="value", aggfunc="last")
        clean_std = factor_wide.stack().std()
        clean_ic = compute_ic_series(factor_wide, fwd)
        clean_stats = summarize_ic_stats(clean_ic)
        clean_abs_mean = abs(clean_stats.get("mean", 0.0))
        if clean_abs_mean < 1e-6:
            logger.warning(f"  {fn}: clean IC ~ 0, skip")
            continue

        per_noise = {}
        for noise_pct in NOISE_PCTS:
            sigma = noise_pct * clean_std
            noise = rng.standard_normal(factor_wide.shape) * sigma
            noisy = factor_wide + noise
            noisy_ic = compute_ic_series(noisy, fwd)
            noisy_stats = summarize_ic_stats(noisy_ic)
            noisy_abs_mean = abs(noisy_stats.get("mean", 0.0))
            retention = noisy_abs_mean / clean_abs_mean if clean_abs_mean > 0 else 0.0
            per_noise[f"noise_{int(noise_pct*100)}pct"] = {
                "noisy_ic_mean": noisy_stats.get("mean"),
                "retention": retention,
                "fragile_at_20pct": noise_pct >= 0.20 and retention < 0.50,
            }
        results[fn] = {
            "clean_ic_mean": clean_stats.get("mean"),
            "clean_ic_ir": clean_stats.get("ir"),
            "noise_tests": per_noise,
            "elapsed_sec": round(time.time() - t0, 1),
        }
        retention_5 = per_noise["noise_5pct"]["retention"]
        retention_20 = per_noise["noise_20pct"]["retention"]
        logger.info(
            f"  {fn}: clean_IC={clean_stats.get('mean',0):.4f} "
            f"ret5%={retention_5:.3f} ret20%={retention_20:.3f} "
            f"{'FRAGILE' if per_noise['noise_20pct']['fragile_at_20pct'] else 'ROBUST'}"
        )

    out = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "factors": MINUTE_FACTORS,
        "horizon": HORIZON,
        "noise_pcts": NOISE_PCTS,
        "results": results,
        "elapsed_sec": round(time.time() - t_all, 1),
    }
    out_path = REPO_ROOT / "reports" / f"p0_minute_g_robust_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    logger.info(f"[report] {out_path}")
    logger.info(f"[done] {(time.time()-t_all)/60:.2f} min")


if __name__ == "__main__":
    main()
