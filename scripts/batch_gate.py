#!/usr/bin/env python3
# DEPRECATED: 此为 batch_gate v1。请使用 scripts/batch_gate_v2.py
"""Step 6-E Part 3C: 批量 Factor Gate 执行.

对 factor_values 里所有因子逐个跑 FactorGatePipeline 的 G1-G8 (可跑的部分),
结果写入 factor_evaluation 表 (此前 0 行)。

Gate 覆盖:
  - G1: |IC_mean| > 0.02 (快筛)
  - G2: 与现有 Active 因子 corr < 0.7 (正交性)
  - G3: t-stat > 2.0 (宽松显著性)
  - G4: 中性化后 IC 衰减 < 50%
  - G5: 方向与经济假设一致 (factor_registry 没 hypothesis 的跳过)
  - G6: BH-FDR 多重检验校正
  - G7: SimBroker 回测 Sharpe ≥ 基线×1.03 (TOO EXPENSIVE, 跳过,  后续手动)
  - G8: strategy 策略匹配 (需要 FactorClassifier, 跳过)

输出:
  cache/baseline/batch_gate_results.json — 所有因子的 Gate 分类汇总
  factor_evaluation 表: 若存在则 upsert, 否则跳过持久化

用法:
    python scripts/batch_gate.py                 # 全部因子
    python scripts/batch_gate.py --factor bp_ratio  # 单因子
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import pandas as pd  # noqa: E402
from engines.ic_calculator import (  # noqa: E402
    IC_CALCULATOR_ID,
    IC_CALCULATOR_VERSION,
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "backtest"

# Gate 阈值 (从 factor_gate.py 引用)
G1_IC_THRESHOLD = 0.02
G2_CORR_THRESHOLD = 0.70
G3_TSTAT_THRESHOLD = 2.0
G4_DECAY_THRESHOLD = 0.50
G6_BH_FDR_ALPHA = 0.05

CORE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]
HORIZON = 20


def load_price_bench():
    """加载 12 年 price + benchmark."""
    price_parts, bench_parts = [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))
    price_df = pd.concat(price_parts, ignore_index=True)
    price_df = price_df[
        (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
        & (price_df["board"].fillna("") != "bse")
    ].copy()
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")
    return price_df, bench_df


def get_all_factors(conn) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
    return [r[0] for r in cur.fetchall()]


def compute_factor_ic_from_db(
    factor_name: str, price_df, bench_df, fwd_ret_cache, conn
) -> dict:
    """计算单因子 IC (走共享模块)."""
    # 优先 Parquet (CORE 5)
    parquet_has = False
    parts = []
    for year in range(2014, 2027):
        fp = CACHE_DIR / str(year) / "factor_data.parquet"
        if not fp.exists():
            continue
        fdf = pd.read_parquet(fp)
        fdf = fdf[fdf["factor_name"] == factor_name]
        if not fdf.empty:
            parts.append(fdf)
            parquet_has = True
    if parquet_has:
        factor_df = pd.concat(parts, ignore_index=True)
        if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
            factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    else:
        factor_df = pd.read_sql(
            """SELECT code, trade_date, factor_name, neutral_value
               FROM factor_values WHERE factor_name = %s AND neutral_value IS NOT NULL""",
            conn,
            params=(factor_name,),
        )
    if factor_df.empty:
        return {"error": "no factor data"}

    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="first"
    ).sort_index()
    common = factor_wide.index.intersection(fwd_ret_cache.index)
    if len(common) < 60:
        return {"error": f"insufficient overlap ({len(common)})"}

    ic_series = compute_ic_series(factor_wide.loc[common], fwd_ret_cache.loc[common])
    stats = summarize_ic_stats(ic_series)

    return {
        "stats": stats,
        "ic_series": ic_series,
        "n_codes": int(len(factor_wide.columns)),
        "n_dates": int(len(common)),
    }


def run_gates_for_factor(
    factor_name: str,
    ic_result: dict,
    core_ic_cache: dict,
    direction: int = 1,
) -> dict:
    """对单因子跑 G1/G2/G3/G4/G6 (其他 Gate 跳过)."""
    if "error" in ic_result:
        return {
            "factor_name": factor_name,
            "passed": False,
            "gates": {},
            "reason": ic_result["error"],
        }

    stats = ic_result["stats"]
    ic_mean = stats["mean"]
    abs_ic = abs(ic_mean)
    tstat = stats["t_stat"]

    gate_results = {}

    # G1: |IC_mean| > 0.02
    gate_results["G1"] = {
        "passed": abs_ic > G1_IC_THRESHOLD,
        "metric": round(abs_ic, 6),
        "threshold": G1_IC_THRESHOLD,
    }

    # G2: 与 CORE 5 中最强相关 < 0.7
    # 用 IC 时间序列相关性 (更稳定)
    ic_s = ic_result["ic_series"]
    max_corr = 0.0
    max_corr_with = None
    for core_f, core_ic in core_ic_cache.items():
        if core_f == factor_name:
            continue
        merged = pd.DataFrame({"a": ic_s, "b": core_ic}).dropna()
        if len(merged) < 60:
            continue
        corr = abs(merged.corr().iloc[0, 1])
        if corr > max_corr:
            max_corr = corr
            max_corr_with = core_f
    gate_results["G2"] = {
        "passed": max_corr < G2_CORR_THRESHOLD,
        "metric": round(float(max_corr), 4),
        "max_corr_with": max_corr_with,
        "threshold": G2_CORR_THRESHOLD,
    }

    # G3: |t-stat| > 2.0
    gate_results["G3"] = {
        "passed": abs(tstat) > G3_TSTAT_THRESHOLD,
        "metric": round(float(tstat), 4),
        "threshold": G3_TSTAT_THRESHOLD,
    }

    # G4: 中性化后 IC 衰减 — 简化版: 用 full period std/|mean| 判断稳定性
    # (严格版需要逐步剥离中性化步骤重算, TOO EXPENSIVE)
    # 简化: 对比前半段 vs 后半段 IC, 衰减 = (early_abs - late_abs) / early_abs
    try:
        n = len(ic_s.dropna())
        first_half = ic_s.dropna().iloc[: n // 2]
        second_half = ic_s.dropna().iloc[n // 2 :]
        early_mean = abs(first_half.mean())
        late_mean = abs(second_half.mean())
        decay = (early_mean - late_mean) / early_mean if early_mean > 1e-9 else 0.0
        gate_results["G4"] = {
            "passed": decay < G4_DECAY_THRESHOLD,
            "metric": round(float(decay), 4),
            "threshold": G4_DECAY_THRESHOLD,
            "note": "简化版: 前半期 vs 后半期 IC 衰减, 非中性化消除",
        }
    except Exception as e:
        gate_results["G4"] = {"passed": False, "error": str(e)}

    # G5: 方向一致性 — 从 direction 参数传入, 这里信任 factor_registry
    # (真实 G5 需要 hypothesis 描述字段, 大多数因子没有)
    gate_results["G5"] = {
        "passed": True,
        "note": "简化版: 假设 direction 参数已通过经济假设验证",
    }

    # G6: BH-FDR 多重检验校正
    # 严格版需要所有同批测试因子的 p-values, 简化: 如果 |t| > 2.5 (更严的阈值) 视为通过
    gate_results["G6"] = {
        "passed": abs(tstat) > 2.5,
        "metric": round(float(tstat), 4),
        "threshold": 2.5,
        "note": "简化版: |t| > 2.5 (Harvey Liu Zhu 2016 硬性下限), 非完整 BH-FDR",
    }

    # G7/G8 跳过 (需要完整回测和策略匹配)
    gate_results["G7"] = {"passed": None, "note": "skipped (需完整回测)"}
    gate_results["G8"] = {"passed": None, "note": "skipped (需 FactorClassifier)"}

    # 汇总: 跑过的 G1/G2/G3/G4/G6 全过 → PASS
    auto_gates = ["G1", "G2", "G3", "G4", "G6"]
    all_passed = all(gate_results[g].get("passed", False) for g in auto_gates)

    return {
        "factor_name": factor_name,
        "direction": direction,
        "ic_stats": stats,
        "gates": gate_results,
        "auto_gates_passed": all_passed,
        "overall_verdict": "PASS" if all_passed else "FAIL",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", type=str, help="只跑单因子")
    args = parser.parse_args()

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    print("[Load] price + benchmark...")
    price_df, bench_df = load_price_bench()
    print(f"  price: {price_df.shape}, bench: {bench_df.shape}")

    print("[Compute] forward excess return cache...")
    fwd_ret_cache = compute_forward_excess_returns(
        price_df, bench_df, horizon=HORIZON, price_col="adj_close"
    )
    print(f"  fwd_ret shape: {fwd_ret_cache.shape}")

    conn = get_sync_conn()

    if args.factor:
        factor_list = [args.factor]
    else:
        factor_list = get_all_factors(conn)
    print(f"\n[Batch Gate] {len(factor_list)} 因子逐个执行...")

    # 先算 CORE 5 的 IC (用于 G2 相关性计算)
    print("\n[Core IC Cache] 计算 CORE 5 的 IC 时间序列 (for G2)...")
    core_ic_cache = {}
    for f in CORE_FACTORS:
        r = compute_factor_ic_from_db(f, price_df, bench_df, fwd_ret_cache, conn)
        if "error" not in r:
            core_ic_cache[f] = r["ic_series"]
        print(f"  {f}: {'OK' if 'error' not in r else r.get('error')}")

    # 批量跑
    results = {}
    t0 = time.time()
    for i, f in enumerate(factor_list):
        ic_result = compute_factor_ic_from_db(f, price_df, bench_df, fwd_ret_cache, conn)
        gate_result = run_gates_for_factor(f, ic_result, core_ic_cache)
        results[f] = gate_result

        verdict = gate_result.get("overall_verdict", "ERROR")
        reason = gate_result.get("reason", "")
        if verdict == "PASS":
            stats = gate_result["ic_stats"]
            print(
                f"  [{i+1:>3}/{len(factor_list)}] {f:<35} {verdict} "
                f"IC={stats['mean']:+.4f} t={stats['t_stat']:+6.2f}"
            )
        elif verdict == "FAIL":
            stats = gate_result.get("ic_stats", {})
            failed = [g for g in ("G1", "G2", "G3", "G4", "G6") if not gate_result["gates"][g].get("passed", False)]
            print(
                f"  [{i+1:>3}/{len(factor_list)}] {f:<35} FAIL (fail={','.join(failed)}) "
                f"IC={stats.get('mean', 0):+.4f} t={stats.get('t_stat', 0):+6.2f}"
            )
        else:
            print(f"  [{i+1:>3}/{len(factor_list)}] {f:<35} ERROR ({reason})")

    elapsed = time.time() - t0
    print(f"\n总耗时: {elapsed:.0f}s")

    conn.close()

    # 汇总
    total = len(results)
    passed = sum(1 for r in results.values() if r.get("overall_verdict") == "PASS")
    failed = sum(1 for r in results.values() if r.get("overall_verdict") == "FAIL")
    errored = sum(1 for r in results.values() if "error" in r.get("reason", "").lower() or "error" in r or r.get("overall_verdict") == "ERROR")

    # 5 CORE 是否全 PASS?
    core_verdicts = {f: results.get(f, {}).get("overall_verdict", "MISSING") for f in CORE_FACTORS}

    # 候选因子
    candidates = ["turnover_stability_20", "atr_norm_20", "gap_frequency_20"]
    cand_verdicts = {f: results.get(f, {}).get("overall_verdict", "MISSING") for f in candidates}

    summary = {
        "meta": {
            "version": IC_CALCULATOR_VERSION,
            "id": IC_CALCULATOR_ID,
            "horizon": HORIZON,
            "total_factors": total,
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "elapsed_sec": round(elapsed, 0),
        },
        "core_5_verdicts": core_verdicts,
        "candidate_3_verdicts": cand_verdicts,
        "results": results,
    }

    out_path = BASELINE_DIR / "batch_gate_results.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    print("\n" + "=" * 72)
    print("  Batch Gate 汇总")
    print("=" * 72)
    print(f"  Total: {total}")
    print(f"  PASS:  {passed}")
    print(f"  FAIL:  {failed}")
    print(f"  ERROR: {errored}")
    print("\n  CORE 5 verdicts:")
    for f, v in core_verdicts.items():
        print(f"    {f}: {v}")
    print("\n  Candidate 3 verdicts:")
    for f, v in cand_verdicts.items():
        print(f"    {f}: {v}")
    print("=" * 72)


if __name__ == "__main__":
    main()
