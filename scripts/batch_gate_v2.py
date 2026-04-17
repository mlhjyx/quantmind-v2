#!/usr/bin/env python3
r"""Step 6-G Part 6: batch_gate V2 — 对齐 factor_gate.py 事实标准的 Gate 实现.

修正 Step 6-E batch_gate.py 的 Gate 编号 + G2 定义错误:
- 旧版 G2 = IC 时序相关 < 0.7 (错, 实际是 G6 cross-sectional 相关)
- 旧版 G4 = 前后半段 IC 衰减 (错, 实际是中性化前后 IC 衰减)
- 旧版 Gate 编号跟 factor_gate.py / DEV_FACTOR_MINING.md 不一致

V2 对齐 factor_gate.py §G1-G8 + CLAUDE.md 宪法:

| Gate | 检验 | 阈值 | 实现 |
|------|------|------|------|
| G1 | \|IC_mean\| > 0.02 | 硬性 | neutral_value IC 全期均值 |
| G2 | IC_IR > 0.3 (CLAUDE.md 宪法) | 硬性 | IR = ic_mean / ic_std |
| G3 | t-stat > 2.0-2.5 (BH-FDR) | 动态 | abs(ic_mean) / (ic_std/√n) |
| G4 | 中性化前后 IC 衰减 < 50% | 硬性 | 1 - |neutral_IC| / |raw_IC| |
| G5 | half-life > 5天 | 硬性 | IC autocorrelation → half-life |
| G6 | cross-sectional 因子值 \|corr\| < 0.7 | 硬性 | 因子值截面 Spearman |
| G7 | coverage > 80% | 硬性 | 非 NaN 股票占比 |
| G8 | SimBroker 回测 Sharpe ≥ 基线×1.03 | 手动 (skipped in batch) |

重跑 63 因子, 输出 vs 旧版的差异, 写入 cache/baseline/batch_gate_v2_results.json.

用法:
    python scripts/batch_gate_v2.py
    python scripts/batch_gate_v2.py --factor bp_ratio
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

import numpy as np  # noqa: E402
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

# Gate thresholds (factor_gate.py 事实标准)
G1_IC = 0.02
G2_IR = 0.30  # CLAUDE.md 宪法 §因子审批硬标准: IC_IR > 0.3
G3_T_SOFT = 2.0
G3_T_HARD = 2.5
G4_NEUTRALIZATION_MAX_DECAY = 0.50
G5_MIN_HALF_LIFE = 5  # days
G6_MAX_CORR = 0.70  # cross-sectional factor value correlation
G7_MIN_COVERAGE = 0.80

CORE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]
HORIZON = 20


def load_price_bench():
    print("[Load] price + benchmark...")
    t0 = time.time()
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
    print(f"  price {price_df.shape}, bench {bench_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df


def load_factor(factor_name: str, conn) -> pd.DataFrame:
    """Load factor with BOTH raw_value AND neutral_value for G4 decay check."""
    # Parquet cache only has neutral_value (列名错误是 raw_value). Load both from DB.
    df = pd.read_sql(
        """SELECT code, trade_date, factor_name, raw_value, neutral_value
           FROM factor_values WHERE factor_name = %s""",
        conn,
        params=(factor_name,),
    )
    return df


def compute_ic_from_wide(factor_wide, fwd_ret) -> pd.Series:
    """Wrapper around compute_ic_series."""
    common = factor_wide.index.intersection(fwd_ret.index)
    if len(common) < 30:
        return pd.Series(dtype=float)
    return compute_ic_series(factor_wide.loc[common], fwd_ret.loc[common])


def half_life_from_ic(ic_series: pd.Series, max_lag: int = 60) -> float:
    """Estimate half-life from IC autocorrelation decay.

    half_life = k where autocorr(k) = 0.5
    Uses linear interpolation between lags where autocorr crosses 0.5.
    If IC is noise (no clear decay), returns 1.0 (no persistence).
    """
    clean = ic_series.dropna()
    if len(clean) < 30:
        return 0.0

    max_lag = min(max_lag, len(clean) // 3)
    autocorrs = [1.0]  # lag 0
    for lag in range(1, max_lag + 1):
        a1 = clean.iloc[lag:]
        a2 = clean.iloc[:-lag]
        if len(a1) < 10 or a1.std() == 0 or a2.std() == 0:
            autocorrs.append(0.0)
            continue
        c = float(np.corrcoef(a1.values, a2.values)[0, 1])
        if np.isnan(c):
            c = 0.0
        autocorrs.append(c)

    # Find first lag where autocorr drops below 0.5
    for i, a in enumerate(autocorrs):
        if a < 0.5:
            if i == 0:
                return 0.0
            # Linear interpolate between i-1 and i
            a_prev = autocorrs[i - 1]
            if a_prev == a:
                return float(i)
            t = (a_prev - 0.5) / (a_prev - a)
            return float(i - 1 + t)
    # Never drops below 0.5 within max_lag → very persistent
    return float(max_lag)


def compute_cross_sectional_corr(
    factor_wide_a: pd.DataFrame, factor_wide_b: pd.DataFrame
) -> float:
    """Average cross-sectional Spearman correlation between two factors across time."""
    common_dates = factor_wide_a.index.intersection(factor_wide_b.index)
    if len(common_dates) < 30:
        return 0.0

    corrs = []
    for td in common_dates[::20]:  # Sample every 20 days for speed
        a = factor_wide_a.loc[td].dropna()
        b = factor_wide_b.loc[td].dropna()
        common = a.index.intersection(b.index)
        if len(common) < 30:
            continue
        c = a.loc[common].rank().corr(b.loc[common].rank())
        if not np.isnan(c):
            corrs.append(float(c))

    return float(np.mean(np.abs(corrs))) if corrs else 0.0


def run_gates(
    factor_name: str,
    factor_df: pd.DataFrame,
    fwd_ret,
    core_factor_wides: dict,
    daily_active: pd.Series,
) -> dict:
    """Run G1-G7 gates (skip G8 SimBroker).

    Args:
        daily_active: Series indexed by trade_date, values = 每日活跃股票数.
            用于 G7 coverage 分母 (Step 6-G fix: 之前用 12yr code 全集 5419 做分母,
            导致 amihud_20 等 CORE 因子虚报 coverage ~55% < 80% 被 FAIL).
    """
    if factor_df.empty:
        return {"error": "no factor data"}

    # Pivot both raw and neutral
    if factor_df["neutral_value"].notna().sum() < 100:
        return {"error": "insufficient neutral_value"}

    neutral_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="first"
    ).sort_index()

    has_raw = factor_df["raw_value"].notna().sum() > 100
    raw_wide = None
    if has_raw:
        raw_wide = factor_df.pivot_table(
            index="trade_date", columns="code", values="raw_value", aggfunc="first"
        ).sort_index()

    # IC series (neutral)
    ic_neutral = compute_ic_from_wide(neutral_wide, fwd_ret)
    if ic_neutral.empty:
        return {"error": "ic_neutral empty"}

    neutral_stats = summarize_ic_stats(ic_neutral)
    ic_mean = neutral_stats["mean"]
    ic_ir = neutral_stats["ir"]
    t_stat = neutral_stats["t_stat"]

    gates = {}

    # G1: |IC| > 0.02
    gates["G1"] = {
        "passed": abs(ic_mean) > G1_IC,
        "metric": round(abs(ic_mean), 6),
        "threshold": G1_IC,
        "name": "|IC_mean|",
    }

    # G2: IC_IR > 0.3
    gates["G2"] = {
        "passed": abs(ic_ir) > G2_IR,
        "metric": round(float(abs(ic_ir)), 4),
        "threshold": G2_IR,
        "name": "|IC_IR|",
    }

    # G3: t-stat > 2.0 (soft)
    gates["G3"] = {
        "passed": abs(t_stat) > G3_T_SOFT,
        "metric": round(float(abs(t_stat)), 4),
        "threshold": G3_T_SOFT,
        "name": "|t-stat|",
    }

    # G4: 中性化前后 IC 衰减 < 50%
    if has_raw and raw_wide is not None:
        ic_raw = compute_ic_from_wide(raw_wide, fwd_ret)
        if not ic_raw.empty:
            raw_stats = summarize_ic_stats(ic_raw)
            raw_abs = abs(raw_stats["mean"])
            neutral_abs = abs(ic_mean)
            if raw_abs > 1e-6:
                decay = 1 - neutral_abs / raw_abs
                gates["G4"] = {
                    "passed": decay < G4_NEUTRALIZATION_MAX_DECAY,
                    "metric": round(float(decay), 4),
                    "threshold": G4_NEUTRALIZATION_MAX_DECAY,
                    "name": "中性化衰减",
                    "raw_ic": round(raw_stats["mean"], 6),
                    "neutral_ic": round(ic_mean, 6),
                }
            else:
                gates["G4"] = {"passed": True, "metric": 0.0, "note": "raw_ic ≈ 0"}
        else:
            gates["G4"] = {"passed": None, "note": "raw IC empty, skipped"}
    else:
        gates["G4"] = {"passed": None, "note": "no raw_value data, skipped"}

    # G5: half-life > 5 days (IC autocorrelation)
    hl = half_life_from_ic(ic_neutral)
    gates["G5"] = {
        "passed": hl > G5_MIN_HALF_LIFE,
        "metric": round(hl, 2),
        "threshold": G5_MIN_HALF_LIFE,
        "name": "half_life",
    }

    # G6: cross-sectional 因子值 |corr| with CORE factors < 0.7
    max_cs_corr = 0.0
    max_cs_with = None
    for core_name, core_wide in core_factor_wides.items():
        if core_name == factor_name:
            continue
        c = compute_cross_sectional_corr(neutral_wide, core_wide)
        if c > max_cs_corr:
            max_cs_corr = c
            max_cs_with = core_name
    gates["G6"] = {
        "passed": max_cs_corr < G6_MAX_CORR,
        "metric": round(max_cs_corr, 4),
        "threshold": G6_MAX_CORR,
        "max_corr_with": max_cs_with,
        "name": "cross-sectional corr with CORE",
    }

    # G7: coverage > 80% (Step 6-G fix)
    # coverage = 非 NaN 股票 / 当日活跃股票数 (per-date active universe)
    # 之前用 12yr code 全集 (~5419) 做分母导致 amihud_20 等 CORE 虚报 FAIL
    coverage_list = []
    for td in neutral_wide.index[::20]:
        row = neutral_wide.loc[td]
        non_null = row.notna().sum()
        denom = daily_active.get(td, 0)
        if denom > 0:
            coverage_list.append(non_null / denom)
    coverage = float(np.mean(coverage_list)) if coverage_list else 0.0
    gates["G7"] = {
        "passed": coverage > G7_MIN_COVERAGE,
        "metric": round(coverage, 4),
        "threshold": G7_MIN_COVERAGE,
        "name": "coverage",
    }

    # G8 skipped (SimBroker backtest)
    gates["G8"] = {"passed": None, "note": "SimBroker backtest skipped in batch"}

    # Verdict: G1-G7 全部非 False (None 算通过 = 未测试)
    # Step 6-G fix: 之前用 `is True` 严格比较, 但 numpy.bool_ 不等于 Python bool,
    # 导致 numpy 产生的 passed 值被误判为非 True → 全部因子 verdict=FAIL.
    # 改用 `bool(v) is True` 或等价的 `v is not False and v is not None`.
    def _is_pass(v):
        """True if explicitly passed, None means skipped (not failure)."""
        if v is False:
            return False
        if v is None:
            return True  # skipped gate counts as pass
        return bool(v)  # coerce numpy.bool_ to Python bool

    auto_pass = all(
        _is_pass(g.get("passed")) for gn, g in gates.items() if gn != "G8"
    )
    # 需要 G1/G2/G3/G6 真的通过 (不是 None)
    core_gates_pass = all(
        gates[gn].get("passed") is not False
        and gates[gn].get("passed") is not None
        and bool(gates[gn].get("passed"))
        for gn in ("G1", "G2", "G3", "G6")
    )
    verdict = "PASS" if core_gates_pass and auto_pass else "FAIL"

    return {
        "factor_name": factor_name,
        "verdict": verdict,
        "ic_stats": neutral_stats,
        "gates": gates,
        # Step 6-G fix: 用显式 `== False` + 类型转换, 避免 numpy.bool_ is False 失效
        "failed_gates": [
            gn for gn in ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
            if gates[gn].get("passed") is not None
            and not bool(gates[gn].get("passed"))
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", type=str)
    args = parser.parse_args()

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    print("[Load] price + benchmark...")
    price_df, bench_df = load_price_bench()
    total_universe = set(price_df["code"].unique())
    print(f"  total universe (12yr union): {len(total_universe)}")
    # Step 6-G G7 fix: 每日活跃股票数 (coverage 分母)
    daily_active = price_df.groupby("trade_date")["code"].nunique()
    print(f"  daily active: mean={int(daily_active.mean())}, min={int(daily_active.min())}, max={int(daily_active.max())}")

    print("[Precompute] forward excess return (horizon=20)...")
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=HORIZON, price_col="adj_close")

    conn = get_sync_conn()

    # Pre-load CORE factor wide tables for G6
    print("\n[Cache] CORE 5 neutral_value wide tables (for G6)...")
    core_factor_wides = {}
    for cf in CORE_FACTORS:
        df = load_factor(cf, conn)
        if df.empty:
            continue
        core_factor_wides[cf] = df.pivot_table(
            index="trade_date", columns="code", values="neutral_value", aggfunc="first"
        ).sort_index()
        print(f"  {cf}: {core_factor_wides[cf].shape}")

    # Factor list
    if args.factor:
        factor_list = [args.factor]
    else:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT factor_name FROM factor_values WHERE neutral_value IS NOT NULL ORDER BY factor_name"
        )
        factor_list = [r[0] for r in cur.fetchall()]

    print(f"\n[Batch Gate V2] {len(factor_list)} factors")
    print(f"[IC] {IC_CALCULATOR_ID} v{IC_CALCULATOR_VERSION}")

    results = {}
    t0 = time.time()
    for i, f in enumerate(factor_list):
        factor_df = load_factor(f, conn)
        if factor_df.empty:
            results[f] = {"error": "no data", "verdict": "ERROR"}
            print(f"  [{i+1}/{len(factor_list)}] {f}: no data")
            continue

        try:
            r = run_gates(f, factor_df, fwd_ret, core_factor_wides, daily_active)
            results[f] = r

            if "error" in r:
                print(f"  [{i+1}/{len(factor_list)}] {f}: {r['error']}")
                continue

            verdict = r["verdict"]
            stats = r["ic_stats"]
            failed = ",".join(r["failed_gates"]) or "-"
            print(
                f"  [{i+1}/{len(factor_list)}] {f:<30} {verdict:<4} "
                f"IC={stats['mean']:+.4f} IR={stats['ir']:+.3f} "
                f"t={stats['t_stat']:+6.2f} failed={failed}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            results[f] = {"error": str(e)[:80], "verdict": "ERROR"}

    elapsed = time.time() - t0
    print(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    conn.close()

    # Summary
    total = len(results)
    passed = sum(1 for r in results.values() if r.get("verdict") == "PASS")
    failed = sum(1 for r in results.values() if r.get("verdict") == "FAIL")
    errored = sum(1 for r in results.values() if r.get("verdict") == "ERROR")

    # CORE + candidate verdicts
    core_verdicts = {f: results.get(f, {}).get("verdict", "MISSING") for f in CORE_FACTORS}
    candidates = ["turnover_stability_20", "atr_norm_20", "gap_frequency_20", "ivol_20"]
    cand_verdicts = {f: results.get(f, {}).get("verdict", "MISSING") for f in candidates}

    summary = {
        "meta": {
            "version": "v2",
            "ic_calculator": IC_CALCULATOR_ID,
            "horizon": HORIZON,
            "total": total,
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "elapsed_sec": round(elapsed, 0),
            "thresholds": {
                "G1_IC": G1_IC,
                "G2_IR": G2_IR,
                "G3_T_SOFT": G3_T_SOFT,
                "G4_NEUTRALIZATION_MAX_DECAY": G4_NEUTRALIZATION_MAX_DECAY,
                "G5_MIN_HALF_LIFE": G5_MIN_HALF_LIFE,
                "G6_MAX_CORR": G6_MAX_CORR,
                "G7_MIN_COVERAGE": G7_MIN_COVERAGE,
            },
        },
        "core_5_verdicts": core_verdicts,
        "candidate_verdicts": cand_verdicts,
        "results": results,
    }

    # Diff vs v1
    v1_path = BASELINE_DIR / "batch_gate_results.json"
    if v1_path.exists():
        v1 = json.loads(v1_path.read_text())
        v1_results = v1.get("results", {})
        changed = {}
        for f, r in results.items():
            v1_r = v1_results.get(f, {})
            v1_v = v1_r.get("overall_verdict", "MISSING")
            v2_v = r.get("verdict", "MISSING")
            if v1_v != v2_v:
                changed[f] = {"v1": v1_v, "v2": v2_v}
        summary["v1_vs_v2_diff"] = {
            "total_changed": len(changed),
            "changes": changed,
        }

    out_path = BASELINE_DIR / "batch_gate_v2_results.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    print("\n" + "=" * 76)
    print("  Batch Gate V2 汇总 (对齐 factor_gate.py 事实标准)")
    print("=" * 76)
    print(f"  Total: {total}, PASS: {passed}, FAIL: {failed}, ERROR: {errored}")
    print("\n  CORE 5 verdicts:")
    for f, v in core_verdicts.items():
        print(f"    {f}: {v}")
    print("\n  Candidates:")
    for f, v in cand_verdicts.items():
        print(f"    {f}: {v}")
    if "v1_vs_v2_diff" in summary:
        d = summary["v1_vs_v2_diff"]
        print(f"\n  v1 → v2 变化: {d['total_changed']} 因子")
        for f, c in d["changes"].items():
            print(f"    {f}: {c['v1']} → {c['v2']}")
    print("=" * 76)


if __name__ == "__main__":
    main()
