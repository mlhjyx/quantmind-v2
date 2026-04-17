"""WF 验证: vwap_deviation_20 / volume_price_divergence_20 加入 CORE3+dv_ttm.

背景:
- Phase 3E-II 已测 16 微结构因子加入 CORE4: WF 0/6 PASS
- 但当时 vwap_deviation_20 direction=-1 (错), 刚修正为 +1 (neutral IC=+0.0509)
- volume_price_divergence_20 neutral IR=0.700 (当前最强 minute 候选)

目标:
- 验证 direction 修正后 vwap_deviation_20 是否有新增 alpha
- 验证 volume_price_divergence_20 是否超过 Phase 3E-II 结论

基线:
- CORE3+dv_ttm+SN050 WF OOS Sharpe=0.8659, MDD=-13.91%
- 验收: OOS Sharpe > 0.8659 AND overfit_ratio < 1.0 AND 0 negative folds

用法:
    python scripts/research/wf_minute_candidates.py

输出: cache/phase3b/wf_minute_candidates_{timestamp}.json
"""

from __future__ import annotations

import json
import logging
import sys
import time
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
from engines.size_neutral import load_ln_mcap_pivot  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    make_equal_weight_signal_func,
)

from app.services.db import get_sync_conn  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── CORE3+dv_ttm 基线方向 ──
CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "bp_ratio": 1,
    "dv_ttm": 1,
}

# ── Minute 候选因子 (方向修正后的 neutral IC, 铁律 11 可追溯 factor_ic_history) ──
MINUTE_CANDIDATES = {
    1: {"factor": "vwap_deviation_20", "direction": 1, "neutral_ic": 0.0509,
        "note": "direction 修正 -1→+1 后的首次 WF 验证"},
    2: {"factor": "volume_price_divergence_20", "direction": 1, "neutral_ic": 0.0711,
        "note": "neutral IR=0.700, 当前最强 minute 候选"},
}

BASELINE_WF_SHARPE = 0.8659
BASELINE_WF_MDD = -0.1391

CACHE_DIR = PROJECT_ROOT / "cache" / "phase3b"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_parquet_price_bench() -> tuple[pd.DataFrame, pd.DataFrame]:
    """12 年 price + benchmark (cache/backtest/)."""
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    price_parts, bench_parts = [], []
    for yr in sorted(cache_root.iterdir()):
        if not yr.is_dir():
            continue
        pf = yr / "price_data.parquet"
        bf = yr / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))
    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.date
    bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"]).dt.date
    logger.info(
        "Price %d rows %s~%s, Bench %d rows",
        len(price_df), price_df["trade_date"].min(), price_df["trade_date"].max(),
        len(bench_df),
    )
    return price_df, bench_df


def load_factor_data(factor_names: list[str], conn) -> pd.DataFrame:
    """混合加载: CORE5 从 Parquet, 其他从 DB."""
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    core5 = {"turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"}
    parquet_factors = [f for f in factor_names if f in core5]
    db_factors = [f for f in factor_names if f not in core5]

    parts = []
    if parquet_factors:
        pq_parts = []
        for yr in sorted(cache_root.iterdir()):
            if not yr.is_dir():
                continue
            ff = yr / "factor_data.parquet"
            if ff.exists():
                df = pd.read_parquet(ff)
                df = df[df["factor_name"].isin(parquet_factors)]
                pq_parts.append(df)
        if pq_parts:
            pq_df = pd.concat(pq_parts, ignore_index=True)
            if "neutral_value" not in pq_df.columns and "raw_value" in pq_df.columns:
                pq_df = pq_df.rename(columns={"raw_value": "neutral_value"})
            pq_df["trade_date"] = pd.to_datetime(pq_df["trade_date"]).dt.date
            parts.append(pq_df)
            logger.info("Parquet 因子: %d 行 (%s)", len(pq_df), parquet_factors)

    if db_factors:
        placeholders = ",".join(["%s"] * len(db_factors))
        q = f"""
            SELECT code, trade_date, factor_name,
                   COALESCE(neutral_value, raw_value) AS neutral_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= '2014-01-01' AND trade_date <= '2026-12-31'
              AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """
        db_df = pd.read_sql(q, conn, params=db_factors)
        db_df["trade_date"] = pd.to_datetime(db_df["trade_date"]).dt.date
        db_df["neutral_value"] = db_df["neutral_value"].astype(float)
        db_df = db_df[db_df["neutral_value"].notna() & np.isfinite(db_df["neutral_value"])]
        parts.append(db_df)
        logger.info("DB 因子: %d 行 (%s)", len(db_df), db_factors)

    factor_df = pd.concat(parts, ignore_index=True)
    logger.info("因子合计: %d 行, %d 因子", len(factor_df), factor_df["factor_name"].nunique())
    return factor_df


def run_wf_single(cand_id, cand, factor_df, price_df, bench_df, ln_mcap_pivot):
    factor_name = cand["factor"]
    direction = cand["direction"]
    directions = {**CORE_DIRECTIONS, factor_name: direction}
    name = f"CORE3+dv_ttm+{factor_name}+SN050"

    logger.info("=" * 72)
    logger.info("候选 %d: %s", cand_id, name)
    logger.info("  factor=%s dir=%+d neutral_IC=%+.4f", factor_name, direction, cand["neutral_ic"])
    logger.info("  note: %s", cand["note"])
    logger.info("=" * 72)

    t0 = time.time()
    cfg_factors = list(directions.keys())
    sub_df = factor_df[factor_df["factor_name"].isin(cfg_factors)].copy()
    for fn in cfg_factors:
        cnt = (sub_df["factor_name"] == fn).sum()
        logger.info("  %s: %d 行", fn, cnt)
        if cnt == 0:
            return {"cand_id": cand_id, "name": name, "factor": factor_name,
                    "verdict": "SKIP", "reason": f"no data for {fn}"}

    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)

    signal_func = make_equal_weight_signal_func(
        sub_df, directions, price_df,
        top_n=20, rebalance_freq="monthly",
        size_neutral_beta=0.50, ln_mcap_pivot=ln_mcap_pivot,
    )

    all_dates = sorted(price_df["trade_date"].unique())
    engine = WalkForwardEngine(wf_config, bt_config)
    result = engine.run(signal_func, price_df, bench_df, all_dates)

    elapsed = time.time() - t0

    folds = []
    oos_sharpes = []
    neg_folds = 0
    for fr in result.fold_results:
        s = float(fr.oos_sharpe)
        oos_sharpes.append(s)
        if s < 0:
            neg_folds += 1
        folds.append({
            "fold": fr.fold_idx,
            "test_period": [str(fr.test_period[0]), str(fr.test_period[1])],
            "oos_sharpe": round(s, 4),
            "oos_mdd": round(float(fr.oos_mdd), 4),
            "oos_annual_return": round(float(fr.oos_annual_return), 4),
        })

    mean_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    delta = mean_oos_sharpe - BASELINE_WF_SHARPE
    verdict = "PASS" if (mean_oos_sharpe > BASELINE_WF_SHARPE and neg_folds == 0) else "FAIL"

    logger.info("  → mean OOS Sharpe=%.4f (baseline %.4f, Δ=%+.4f)",
                mean_oos_sharpe, BASELINE_WF_SHARPE, delta)
    logger.info("  → neg_folds=%d, verdict=%s, elapsed=%.1fs", neg_folds, verdict, elapsed)

    return {
        "cand_id": cand_id,
        "name": name,
        "factor": factor_name,
        "direction": direction,
        "neutral_ic": cand["neutral_ic"],
        "mean_oos_sharpe": round(mean_oos_sharpe, 4),
        "delta_vs_baseline": round(delta, 4),
        "neg_folds": neg_folds,
        "folds": folds,
        "verdict": verdict,
        "elapsed_sec": round(elapsed, 1),
    }


def main():
    t_all = time.time()
    logger.info("[WF] Minute candidates: CORE3+dv_ttm + {vwap / vol_divergence}")
    logger.info("Baseline WF OOS Sharpe=%.4f MDD=%.4f", BASELINE_WF_SHARPE, BASELINE_WF_MDD)

    price_df, bench_df = load_parquet_price_bench()

    all_factors = list(CORE_DIRECTIONS.keys()) + [c["factor"] for c in MINUTE_CANDIDATES.values()]
    conn = get_sync_conn()
    try:
        factor_df = load_factor_data(all_factors, conn)
    finally:
        conn.close()

    # load_ln_mcap_pivot 需要 start/end
    wf_start = min(price_df["trade_date"])
    wf_end = max(price_df["trade_date"])
    ln_mcap_pivot = load_ln_mcap_pivot(wf_start, wf_end)
    logger.info("ln_mcap_pivot: %s (%s~%s)", ln_mcap_pivot.shape, wf_start, wf_end)

    results = []
    for cand_id, cand in MINUTE_CANDIDATES.items():
        r = run_wf_single(cand_id, cand, factor_df, price_df, bench_df, ln_mcap_pivot)
        results.append(r)

    output = {
        "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_wf_sharpe": BASELINE_WF_SHARPE,
        "baseline_wf_mdd": BASELINE_WF_MDD,
        "candidates": results,
        "total_elapsed_sec": round(time.time() - t_all, 1),
    }
    out_path = CACHE_DIR / f"wf_minute_candidates_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    logger.info("[report] %s", out_path)

    logger.info("=" * 72)
    logger.info("总结:")
    for r in results:
        v = r.get("verdict", "?")
        s = r.get("mean_oos_sharpe", 0)
        d = r.get("delta_vs_baseline", 0)
        logger.info("  %s: %s  Sharpe=%.4f (Δ=%+.4f)", r["factor"], v, s, d)


if __name__ == "__main__":
    main()
