"""P0-7 严格验收: vwap_deviation_20 / volume_price_divergence_20.

铁律 5 硬门槛: paired bootstrap p<0.05 vs 基线
Phase 3B 经验: mean_sharpe > baseline 不够, 还需:
  1. full_sample Sharpe (2020-2026)
  2. overfit_ratio = WF_mean_sharpe / full_sample_sharpe < 1.0 (否则 IS 过拟合)
  3. 0 negative folds (已通过) + fold_sharpe_std < 1.0 (稳定性)
  4. paired bootstrap: 候选日收益 vs 基线日收益, Δ Sharpe 抽样分布 p<0.05

验收标准 (综合):
  PASS    = beats_baseline + overfit<1.0 + std<1.0 + bootstrap_p<0.05
  MARGINAL = 只满足 beats_baseline
  FAIL    = 均值不超基线

输入: cache/phase3b/wf_minute_candidates_20260417_122541.json
输出: cache/phase3b/wf_minute_validation_{ts}.json
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.backtest.runner import run_hybrid_backtest  # noqa: E402
from engines.metrics import calc_sharpe  # noqa: E402
from engines.signal_engine import SignalConfig  # noqa: E402
from engines.size_neutral import load_ln_mcap_pivot  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

# 复用 wf_minute_candidates 的 loader
sys.path.insert(0, str(SCRIPT_DIR))
from wf_minute_candidates import (  # noqa: E402
    CORE_DIRECTIONS,
    load_factor_data,
    load_parquet_price_bench,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASELINE_WF_SHARPE = 0.8659

# 候选 (基于 wf_minute_candidates 结果)
CANDIDATES = [
    {"factor": "vwap_deviation_20", "direction": 1, "wf_mean_sharpe": 1.2064,
     "fold_sharpes": [2.9607, 1.1533, 0.0166, 0.6846, 1.2167]},
    {"factor": "volume_price_divergence_20", "direction": 1, "wf_mean_sharpe": 0.8809,
     "fold_sharpes": [1.2357, 0.2591, 0.4226, 0.818, 1.6692]},
    {"factor": None, "direction": None, "wf_mean_sharpe": BASELINE_WF_SHARPE,
     "fold_sharpes": [], "name": "baseline"},  # CORE3+dv_ttm (baseline)
]

FULL_START = date(2020, 1, 1)
N_BOOTSTRAP = 1000


def run_full_sample(cand, factor_df, price_df, bench_df, ln_mcap_pivot):
    """Run full-sample backtest (2020-2026), return daily_nav + sharpe."""
    if cand["factor"] is None:
        directions = dict(CORE_DIRECTIONS)
        name = "baseline_CORE3_dv_SN050"
    else:
        directions = {**CORE_DIRECTIONS, cand["factor"]: cand["direction"]}
        name = f"CORE3_dv_{cand['factor']}_SN050"

    cfg_factors = list(directions.keys())
    sub_df = factor_df[factor_df["factor_name"].isin(cfg_factors)].copy()

    p20 = price_df[price_df["trade_date"] >= FULL_START]
    b20 = bench_df[bench_df["trade_date"] >= FULL_START]
    f20 = sub_df[sub_df["trade_date"] >= FULL_START]

    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
    sig_config = SignalConfig(
        factor_names=cfg_factors, top_n=20, weight_method="equal",
        rebalance_freq="monthly", size_neutral_beta=0.50,
    )

    logger.info("  Full sample: %s (%d factors, %d rows)", name, len(cfg_factors), len(f20))
    t0 = time.time()
    result = run_hybrid_backtest(
        factor_df=f20, directions=directions,
        price_data=p20, config=bt_config,
        benchmark_data=b20, signal_config=sig_config, conn=None,
    )
    nav = result.daily_nav
    if not isinstance(nav, pd.Series) or len(nav) == 0:
        logger.warning("  no nav for %s", name)
        return {"name": name, "full_sharpe": None, "daily_rets": None}
    full_sharpe = float(calc_sharpe(nav))
    logger.info("  %s full_sharpe=%.4f (%.1fs)", name, full_sharpe, time.time() - t0)
    daily_rets = nav.pct_change().dropna()
    return {"name": name, "full_sharpe": full_sharpe, "daily_rets": daily_rets, "nav": nav}


def paired_bootstrap_sharpe_diff(
    baseline_rets: pd.Series, cand_rets: pd.Series, n: int = 1000, seed: int = 42,
):
    """Paired bootstrap: resample (baseline, cand) 日期 pairs, compute Δ(Sharpe).

    Returns:
        (delta_mean, delta_std, p_value_one_side, ci_95)
    """
    # 对齐日期
    df = pd.concat({"b": baseline_rets, "c": cand_rets}, axis=1).dropna()
    if len(df) < 30:
        return None
    b = df["b"].values
    c = df["c"].values
    n_days = len(b)

    rng = np.random.default_rng(seed)
    deltas = np.empty(n)
    ann = np.sqrt(252)
    for i in range(n):
        idx = rng.integers(0, n_days, n_days)
        bb = b[idx]
        cc = c[idx]
        bs_sh = (bb.mean() / bb.std()) * ann if bb.std() > 0 else 0.0
        cs_sh = (cc.mean() / cc.std()) * ann if cc.std() > 0 else 0.0
        deltas[i] = cs_sh - bs_sh

    delta_mean = float(np.mean(deltas))
    delta_std = float(np.std(deltas))
    # H0: delta <= 0, H1: delta > 0. p = fraction where delta <= 0
    p_value = float((deltas <= 0).sum() / n)
    ci_lo, ci_hi = float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))
    return {
        "delta_sharpe_bootstrap_mean": round(delta_mean, 4),
        "delta_sharpe_bootstrap_std": round(delta_std, 4),
        "p_value_one_side": round(p_value, 4),
        "ci_95_lo": round(ci_lo, 4),
        "ci_95_hi": round(ci_hi, 4),
        "n_bootstrap": n,
        "n_aligned_days": n_days,
    }


def final_verdict(cand_result, baseline_full_sharpe):
    """综合 verdict."""
    wf_sh = cand_result["wf_mean_sharpe"]
    full_sh = cand_result["full_sharpe"]
    fold_sh = cand_result["fold_sharpes"]

    beats_baseline = wf_sh > BASELINE_WF_SHARPE
    n_neg = sum(1 for s in fold_sh if s < 0)
    sh_std = float(np.std(fold_sh)) if fold_sh else 0
    stable = sh_std < 1.0 and n_neg == 0

    overfit = None
    if full_sh and full_sh > 0:
        # overfit_ratio 常见定义: WF_mean / full_sample > 1 说明 WF 虚高
        overfit = round(wf_sh / full_sh, 4)

    bs = cand_result.get("bootstrap", {})
    p = bs.get("p_value_one_side") if bs else 1.0

    # 严格 PASS: 4 个都满足
    if beats_baseline and stable and overfit is not None and overfit < 1.0 and p is not None and p < 0.05:
        verdict = "STRICT_PASS"
    elif beats_baseline and p is not None and p < 0.05:
        verdict = "BOOTSTRAP_PASS_but_unstable"
    elif beats_baseline and stable:
        verdict = "MARGINAL_stable"
    elif beats_baseline:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    return {
        "wf_mean_sharpe": round(wf_sh, 4),
        "full_sample_sharpe": round(full_sh, 4) if full_sh else None,
        "overfit_ratio": overfit,
        "fold_sharpe_std": round(sh_std, 4),
        "n_negative_folds": n_neg,
        "stable": stable,
        "bootstrap_p": p,
        "beats_baseline": beats_baseline,
        "verdict": verdict,
    }


def main():
    t_all = time.time()
    logger.info("[P0-7] WF 候选严格验收")
    logger.info("=" * 72)

    price_df, bench_df = load_parquet_price_bench()
    all_factors = list(CORE_DIRECTIONS.keys()) + [
        c["factor"] for c in CANDIDATES if c["factor"]
    ]
    conn = get_sync_conn()
    try:
        factor_df = load_factor_data(all_factors, conn)
    finally:
        conn.close()

    ln_mcap_pivot = load_ln_mcap_pivot(
        min(price_df["trade_date"]), max(price_df["trade_date"]),
    )

    # Full-sample backtest for baseline + 2 candidates
    fs_results = []
    for cand in CANDIDATES:
        fr = run_full_sample(cand, factor_df, price_df, bench_df, ln_mcap_pivot)
        fs_results.append({"cand": cand, "fs": fr})

    baseline_fs = next(r for r in fs_results if r["cand"]["factor"] is None)
    baseline_rets = baseline_fs["fs"]["daily_rets"]
    baseline_full_sh = baseline_fs["fs"]["full_sharpe"]

    # 对每个候选做 bootstrap + verdict
    final_results = []
    for r in fs_results:
        cand = r["cand"]
        if cand["factor"] is None:
            continue
        cand_rets = r["fs"]["daily_rets"]
        cand_full_sh = r["fs"]["full_sharpe"]

        bs = paired_bootstrap_sharpe_diff(
            baseline_rets, cand_rets, n=N_BOOTSTRAP,
        )
        logger.info("  %s bootstrap: p=%.4f Δ_mean=%.4f CI=[%.3f, %.3f]",
                    cand["factor"], bs["p_value_one_side"],
                    bs["delta_sharpe_bootstrap_mean"], bs["ci_95_lo"], bs["ci_95_hi"])

        cand_summary = {**cand, "full_sharpe": cand_full_sh, "bootstrap": bs}
        verdict = final_verdict(cand_summary, baseline_full_sh)
        cand_summary["analysis"] = verdict

        final_results.append(cand_summary)

        logger.info("  %s verdict: %s", cand["factor"], verdict["verdict"])
        logger.info("    wf=%.3f full=%s overfit=%s std=%.2f p=%s",
                    verdict["wf_mean_sharpe"], verdict["full_sample_sharpe"],
                    verdict["overfit_ratio"], verdict["fold_sharpe_std"],
                    verdict["bootstrap_p"])

    # Report
    output = {
        "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_wf_sharpe": BASELINE_WF_SHARPE,
        "baseline_full_sample_sharpe": round(baseline_full_sh, 4) if baseline_full_sh else None,
        "bootstrap_n": N_BOOTSTRAP,
        "full_sample_period": f"{FULL_START}~max",
        "candidates": final_results,
        "elapsed_sec": round(time.time() - t_all, 1),
    }
    out_path = PROJECT_ROOT / "cache" / "phase3b" / f"wf_minute_validation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    logger.info("[report] %s", out_path)

    logger.info("=" * 72)
    logger.info("[summary]")
    logger.info("baseline full_sharpe = %.4f", baseline_full_sh)
    for r in final_results:
        v = r["analysis"]["verdict"]
        logger.info(
            "  %s: %s  wf=%.3f full=%.3f overfit=%s p=%.3f",
            r["factor"], v, r["analysis"]["wf_mean_sharpe"],
            r["analysis"]["full_sample_sharpe"] or 0,
            r["analysis"]["overfit_ratio"], r["analysis"]["bootstrap_p"],
        )


if __name__ == "__main__":
    main()
