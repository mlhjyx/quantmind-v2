"""Phase 3B WF评估: 8个P1 CORE候选因子的Walk-Forward 5-fold OOS验证。

目标: 逐个测试将P1因子加入CORE3+dv_ttm基线，评估OOS Sharpe提升。

P1候选因子（按优先级）:
  1. relative_volume_20   (corr=0.17, mono=-1.0)  — 最低CORE4相关性
  2. turnover_surge_ratio  (corr=0.11, mono=-0.90) — 第二低相关性
  3. rsrs_raw_18           (corr=0.28, mono=-0.90) — 最强t统计量
  4. price_volume_corr_20  (corr=0.28, mono=-1.00) — 完美单调性
  5. large_order_ratio     (corr=0.29, mono=-0.90) — 微观结构
  6. kbar_kup              (corr=0.23, mono=-0.70) — 已修复outlier
  7. reversal_10           (corr=0.12, mono=+0.60) — 短期反转
  8. gain_loss_ratio_20    (corr=0.29, mono=-0.70) — MEDIUM衰减

基线对比:
  - CORE3+dv_ttm+SN050 WF OOS: Sharpe=0.8659, MDD=-13.91%
  - 验收标准: OOS Sharpe > 0.8659 AND overfit < 1.0 AND 0 negative folds

WF配置:
  - 5-fold, train=750天(~3年), gap=5天, test=250天(~1年)

用法:
    python scripts/research/phase3b_wf_p1_evaluation.py              # 全部8个候选
    python scripts/research/phase3b_wf_p1_evaluation.py --factor 1   # 仅第1个
    python scripts/research/phase3b_wf_p1_evaluation.py --factor 1 3 # 第1和第3个

输出: cache/phase3b/wf_p1_evaluation_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# 项目路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.metrics import calc_sharpe  # noqa: E402
from engines.size_neutral import load_ln_mcap_pivot  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    make_equal_weight_signal_func,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── CORE3+dv_ttm 基线方向 ──────────────────────────────────────

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "bp_ratio": 1,
    "dv_ttm": 1,
}

# ── P1候选因子定义 ─────────────────────────────────────────────

P1_CANDIDATES = {
    1: {"factor": "relative_volume_20", "direction": -1, "ic_20d": -0.037, "corr": 0.17, "mono": -1.0},
    2: {"factor": "turnover_surge_ratio", "direction": -1, "ic_20d": -0.023, "corr": 0.11, "mono": -0.9},
    3: {"factor": "rsrs_raw_18", "direction": -1, "ic_20d": -0.043, "corr": 0.28, "mono": -0.9},
    4: {"factor": "price_volume_corr_20", "direction": -1, "ic_20d": -0.056, "corr": 0.28, "mono": -1.0},
    5: {"factor": "large_order_ratio", "direction": -1, "ic_20d": -0.045, "corr": 0.29, "mono": -0.9},
    6: {"factor": "kbar_kup", "direction": -1, "ic_20d": -0.042, "corr": 0.23, "mono": -0.7},
    7: {"factor": "reversal_10", "direction": 1, "ic_20d": 0.037, "corr": 0.12, "mono": 0.6},
    8: {"factor": "gain_loss_ratio_20", "direction": -1, "ic_20d": -0.032, "corr": 0.29, "mono": -0.7},
}

# 基线 (Phase 2.4 WF OOS CORE3+dv_ttm+SN050)
BASELINE_WF_SHARPE = 0.8659
BASELINE_WF_MDD = -0.1391
BASELINE_FULL_SHARPE = 1.0341

CACHE_DIR = PROJECT_ROOT / "cache" / "phase3b"
OUTPUT_FILE = CACHE_DIR / "wf_p1_evaluation_results.json"


# ── 数据加载（复用wf_phase24_validation模式）──────────────────

def load_parquet_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """从Parquet缓存加载12年price + benchmark数据。"""
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    price_parts, bench_parts = [], []

    for year_dir in sorted(cache_root.iterdir()):
        if not year_dir.is_dir():
            continue
        pf = year_dir / "price_data.parquet"
        bf = year_dir / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price_df = pd.concat(price_parts, ignore_index=True).sort_values(
        ["code", "trade_date"]
    )
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")

    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.date
    bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"]).dt.date

    logger.info(
        "Price: %d行 (%s~%s), Bench: %d行",
        len(price_df),
        price_df["trade_date"].min(),
        price_df["trade_date"].max(),
        len(bench_df),
    )
    return price_df, bench_df


def load_factor_data(factor_names: list[str], conn) -> pd.DataFrame:
    """从Parquet(CORE5) + DB(其他因子)混合加载因子数据。

    CORE5因子从Parquet加载(已中性化, 列名raw_value实际是neutral_value)。
    其他因子从DB加载(COALESCE(neutral_value, raw_value))。
    """
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    core5 = {"turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"}

    parquet_factors = [f for f in factor_names if f in core5]
    db_factors = [f for f in factor_names if f not in core5]

    parts = []

    # Parquet部分 (CORE5)
    if parquet_factors:
        pq_parts = []
        for year_dir in sorted(cache_root.iterdir()):
            if not year_dir.is_dir():
                continue
            ff = year_dir / "factor_data.parquet"
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
            logger.info("Parquet因子: %d行 (%s)", len(pq_df), parquet_factors)

    # DB部分 (dv_ttm + P1候选因子)
    if db_factors:
        placeholders = ",".join(["%s"] * len(db_factors))
        query = f"""
            SELECT code, trade_date, factor_name,
                   COALESCE(neutral_value, raw_value) AS neutral_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= '2014-01-01' AND trade_date <= '2026-12-31'
              AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """
        db_df = pd.read_sql(query, conn, params=db_factors)
        db_df["trade_date"] = pd.to_datetime(db_df["trade_date"]).dt.date
        db_df["neutral_value"] = db_df["neutral_value"].astype(float)
        db_df = db_df[db_df["neutral_value"].notna() & np.isfinite(db_df["neutral_value"])]
        parts.append(db_df)
        logger.info("DB因子: %d行 (%s)", len(db_df), db_factors)

    factor_df = pd.concat(parts, ignore_index=True)
    logger.info("因子合计: %d行, %d个因子", len(factor_df), factor_df["factor_name"].nunique())
    return factor_df


# ── WF验证核心 ───────────────────────────────────────────────

def run_wf_for_candidate(
    cand_id: int,
    cand: dict,
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame,
) -> dict:
    """对单个P1候选因子（加入CORE3+dv_ttm）运行5-fold WF验证。"""
    factor_name = cand["factor"]
    direction = cand["direction"]

    # CORE3+dv_ttm + 候选因子
    directions = {**CORE_DIRECTIONS, factor_name: direction}
    name = f"CORE3+dv_ttm+{factor_name}+SN050"

    logger.info("=" * 70)
    logger.info("P1 Candidate %d: %s", cand_id, name)
    logger.info("  Factor: %s (dir=%+d, IC_20d=%.3f, corr_CORE4=%.2f, mono=%.1f)",
                factor_name, direction, cand["ic_20d"], cand["corr"], cand["mono"])
    logger.info("  Factors: %s", list(directions.keys()))
    logger.info("=" * 70)

    t0 = time.time()

    # 过滤因子数据
    cfg_factors = list(directions.keys())
    cfg_factor_df = factor_df[factor_df["factor_name"].isin(cfg_factors)].copy()

    # 检查因子数据完整性
    for fn in cfg_factors:
        cnt = (cfg_factor_df["factor_name"] == fn).sum()
        logger.info("  %s: %d行", fn, cnt)
        if cnt == 0:
            logger.error("  ❌ 因子 %s 无数据! 跳过", fn)
            return {
                "config_id": cand_id,
                "name": name,
                "factor": factor_name,
                "analysis": {"verdict": "SKIP", "reason": f"No data for {fn}"},
            }

    # WF配置
    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(
        top_n=20,
        rebalance_freq="monthly",
        initial_capital=1_000_000,
    )

    # 构建signal function
    signal_func = make_equal_weight_signal_func(
        cfg_factor_df,
        directions,
        price_df,
        top_n=20,
        rebalance_freq="monthly",
        size_neutral_beta=0.50,
        ln_mcap_pivot=ln_mcap_pivot,
    )

    # 运行WF
    all_dates = sorted(price_df["trade_date"].unique())
    engine = WalkForwardEngine(wf_config, bt_config)
    result = engine.run(signal_func, price_df, bench_df, all_dates)

    elapsed = time.time() - t0

    # 提取fold结果
    fold_data = []
    for fr in result.fold_results:
        fold_data.append({
            "fold": fr.fold_idx,
            "train_period": [str(fr.train_period[0]), str(fr.train_period[1])],
            "test_period": [str(fr.test_period[0]), str(fr.test_period[1])],
            "oos_sharpe": round(fr.oos_sharpe, 4),
            "oos_mdd": round(fr.oos_mdd, 4),
            "oos_annual_return": round(fr.oos_annual_return, 4),
            "test_days": fr.test_days,
        })

    # Full-sample backtest for overfit ratio
    logger.info("  Running full-sample backtest (2020-2026) for overfit ratio...")
    from engines.backtest.runner import run_hybrid_backtest
    from engines.signal_engine import SignalConfig

    sig_config = SignalConfig(
        factor_names=cfg_factors,
        top_n=20,
        weight_method="equal",
        rebalance_freq="monthly",
        size_neutral_beta=0.50,
    )
    p20 = price_df[price_df["trade_date"] >= date(2020, 1, 1)]
    b20 = bench_df[bench_df["trade_date"] >= date(2020, 1, 1)]
    f20 = cfg_factor_df[cfg_factor_df["trade_date"] >= date(2020, 1, 1)]

    full_result = run_hybrid_backtest(
        factor_df=f20,
        directions=directions,
        price_data=p20,
        config=bt_config,
        benchmark_data=b20,
        signal_config=sig_config,
        conn=None,
    )
    nav = full_result.daily_nav
    full_sample_sharpe = None
    if isinstance(nav, pd.Series) and len(nav) > 0:
        full_sample_sharpe = round(calc_sharpe(nav), 4)
        logger.info("  Full-sample Sharpe (2020-2026): %.4f", full_sample_sharpe)

    # 过拟合比率
    overfit_ratio = None
    if full_sample_sharpe and full_sample_sharpe > 0:
        overfit_ratio = round(result.combined_oos_sharpe / full_sample_sharpe, 4)

    # 判定
    oos_sharpe = result.combined_oos_sharpe
    oos_mdd = result.combined_oos_mdd
    beats_baseline = oos_sharpe > BASELINE_WF_SHARPE

    fold_sharpes = [fd["oos_sharpe"] for fd in fold_data]
    n_negative = sum(1 for s in fold_sharpes if s < 0)
    sharpe_std = float(np.std(fold_sharpes))
    stability = "STABLE" if sharpe_std < 1.0 and n_negative <= 1 else "UNSTABLE"

    # PASS条件: OOS > baseline, overfit < 1.0, 0 negative folds
    if beats_baseline and overfit_ratio is not None and overfit_ratio < 1.0 and n_negative == 0:
        verdict = "PASS"
    elif beats_baseline:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    # 输出
    logger.info("")
    logger.info("  --- Results for %s ---", factor_name)
    for fd in fold_data:
        logger.info(
            "  Fold %d: Sharpe=%.4f  MDD=%.4f  AnnRet=%.4f  [%s ~ %s]",
            fd["fold"], fd["oos_sharpe"], fd["oos_mdd"], fd["oos_annual_return"],
            fd["test_period"][0], fd["test_period"][1],
        )

    delta_sharpe = oos_sharpe - BASELINE_WF_SHARPE
    logger.info("")
    logger.info("  Combined OOS Sharpe:  %.4f (baseline=%.4f, delta=%+.4f)", oos_sharpe, BASELINE_WF_SHARPE, delta_sharpe)
    logger.info("  Combined OOS MDD:     %.4f (baseline=%.4f)", oos_mdd, BASELINE_WF_MDD)
    logger.info("  Overfit Ratio:        %s (full=%.4f)", overfit_ratio, full_sample_sharpe or 0)
    logger.info("  Fold Stability:       %s (std=%.2f, %d negative folds)", stability, sharpe_std, n_negative)
    logger.info("  Verdict:              %s %s", verdict, "✅" if verdict == "PASS" else "⚠️" if verdict == "MARGINAL" else "❌")
    logger.info("  Elapsed:              %.1fs", elapsed)

    return {
        "config_id": cand_id,
        "name": name,
        "factor": factor_name,
        "direction": direction,
        "ic_20d": cand["ic_20d"],
        "corr_core4": cand["corr"],
        "monotonicity": cand["mono"],
        "factors": cfg_factors,
        "directions": directions,
        "full_sample_sharpe": full_sample_sharpe,
        "folds": fold_data,
        "combined": {
            "oos_sharpe": round(oos_sharpe, 4),
            "oos_mdd": round(oos_mdd, 4),
            "oos_annual_return": round(result.combined_oos_annual_return, 4),
            "oos_total_return": round(result.combined_oos_total_return, 4),
            "total_oos_days": result.total_oos_days,
        },
        "analysis": {
            "overfit_ratio": overfit_ratio,
            "fold_sharpe_std": round(sharpe_std, 4),
            "n_negative_folds": n_negative,
            "stability": stability,
            "beats_baseline": beats_baseline,
            "delta_sharpe": round(delta_sharpe, 4),
            "verdict": verdict,
        },
        "elapsed_s": round(elapsed, 1),
    }


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 3B P1 WF Evaluation")
    parser.add_argument(
        "--factor", type=int, nargs="*", default=None,
        help="指定候选因子ID (1-8), 不指定=全部",
    )
    args = parser.parse_args()

    cand_ids = args.factor if args.factor else list(P1_CANDIDATES.keys())

    # 验证ID
    for cid in cand_ids:
        if cid not in P1_CANDIDATES:
            print(f"无效候选ID: {cid}. 可选: 1-8")
            return 1

    # 收集所有需要的因子
    all_factors = set(CORE_DIRECTIONS.keys())
    for cid in cand_ids:
        all_factors.add(P1_CANDIDATES[cid]["factor"])
    all_factors = sorted(all_factors)
    logger.info("需要因子: %s (%d个)", all_factors, len(all_factors))

    # 加载数据
    t_start = time.time()
    price_df, bench_df = load_parquet_data()

    import psycopg2
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )

    factor_df = load_factor_data(all_factors, conn)

    # ln_mcap for SN
    min_date = price_df["trade_date"].min()
    max_date = price_df["trade_date"].max()
    logger.info("Loading ln_mcap_pivot (%s ~ %s)...", min_date, max_date)
    ln_mcap_pivot = load_ln_mcap_pivot(min_date, max_date, conn)
    ln_mcap_pivot.index = pd.to_datetime(ln_mcap_pivot.index).date
    logger.info("ln_mcap_pivot: %d dates x %d stocks", *ln_mcap_pivot.shape)

    t_load = time.time() - t_start
    logger.info("数据加载完成 (%.1fs)", t_load)

    # 运行WF验证（串行，因为每个WF很耗内存）
    results = {}
    for cid in cand_ids:
        result = run_wf_for_candidate(
            cid, P1_CANDIDATES[cid], factor_df, price_df, bench_df, ln_mcap_pivot,
        )
        results[str(cid)] = result

        # 每个跑完后gc
        import gc
        gc.collect()

    conn.close()

    # ── 汇总表 ─────────────────────────────────────────────
    logger.info("\n" + "=" * 100)
    logger.info("SUMMARY: Phase 3B P1 WF Evaluation")
    logger.info("=" * 100)
    logger.info(
        "%-4s %-28s %8s %8s %8s %8s %8s %8s",
        "#", "Factor", "OOS_Sh", "Delta", "OOS_MDD", "Overfit", "NegFold", "Verdict",
    )
    logger.info("-" * 100)

    # 基线行
    logger.info(
        "%-4s %-28s %8.4f %8s %8.4f %8s %8s %8s",
        "-", "[BASELINE] CORE3+dv_ttm+SN050",
        BASELINE_WF_SHARPE, "-", BASELINE_WF_MDD, "-", "0", "-",
    )

    pass_count = 0
    for cid_str, r in sorted(results.items(), key=lambda x: int(x[0])):
        a = r.get("analysis", {})
        if a.get("verdict") == "SKIP":
            logger.info("%-4s %-28s %8s", cid_str, r["factor"], "SKIP: " + a.get("reason", ""))
            continue

        verdict = a.get("verdict", "?")
        if verdict == "PASS":
            pass_count += 1

        logger.info(
            "%-4s %-28s %8.4f %+8.4f %8.4f %8s %8d %8s %s",
            cid_str,
            r["factor"],
            r["combined"]["oos_sharpe"],
            a.get("delta_sharpe", 0),
            r["combined"]["oos_mdd"],
            f"{a['overfit_ratio']:.2f}" if a.get("overfit_ratio") else "N/A",
            a.get("n_negative_folds", -1),
            verdict,
            "✅" if verdict == "PASS" else "⚠️" if verdict == "MARGINAL" else "❌",
        )

    logger.info("-" * 100)
    logger.info("PASS: %d / %d candidates", pass_count, len(results))

    if pass_count > 0:
        logger.info("\n推荐: 以下因子可加入CORE配置:")
        for cid_str, r in sorted(results.items(), key=lambda x: int(x[0])):
            if r.get("analysis", {}).get("verdict") == "PASS":
                logger.info("  ✅ %s (dir=%+d, OOS Sharpe=%.4f, delta=%+.4f)",
                            r["factor"], r["direction"],
                            r["combined"]["oos_sharpe"],
                            r["analysis"]["delta_sharpe"])
    else:
        logger.info("\n结论: 无P1因子通过WF验证。CORE3+dv_ttm是当前等权框架的alpha上限。")

    # 保存结果
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "baseline": {
                    "sharpe": BASELINE_WF_SHARPE,
                    "mdd": BASELINE_WF_MDD,
                    "full_sample_sharpe": BASELINE_FULL_SHARPE,
                    "config": "CORE3+dv_ttm+SN050 Top20 Monthly",
                },
                "candidates": results,
                "summary": {
                    "total_candidates": len(results),
                    "pass_count": pass_count,
                },
            },
            f,
            indent=2,
            default=str,
        )
    logger.info("\n结果已保存: %s", OUTPUT_FILE)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
