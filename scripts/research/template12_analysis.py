#!/usr/bin/env python3
"""Step 6-G Part 5: Template 12 (regime-conditional) 因子详细分析.

从 factor_profile 表找 6 个 Template 12 因子, 分析:
1. Bull/Bear/Sideways 的 IC
2. IC 时序 vs CORE 5 的相关性 (能否作为 regime hedge?)
3. 跟 CORE 5 的 cross-sectional 因子值相关性

输出: cache/baseline/template12_analysis.json

用法:
    python scripts/research/template12_analysis.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from engines.ic_calculator import (  # noqa: E402
    compute_forward_excess_returns,
    compute_ic_series,
)

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"

CORE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]


def load_price_bench():
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


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_sync_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT factor_name, ic_20d, ic_ir, ic_bull, ic_bear, ic_sideways, regime_sensitivity, max_corr_factor, max_corr_value
           FROM factor_profile
           WHERE recommended_template = 12
           ORDER BY factor_name"""
    )
    t12_factors = cur.fetchall()
    print(f"[Template 12] Found {len(t12_factors)} factors from factor_profile")

    print("\n[Load] price + benchmark...")
    t0 = time.time()
    price_df, bench_df = load_price_bench()
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=20, price_col="adj_close")
    print(f"  {time.time()-t0:.1f}s")

    # Load CORE 5 + Template 12 factors — per-factor loop to avoid OOM
    # OOM fix (Step 6-G): 原版一次性 IN (11 因子) 查询加载 ~75M 行, 超出内存上限.
    # 现在改成逐因子 SELECT + 立即 pivot + 计算 IC, 即时丢弃原始长表 → 峰值 <2GB.
    all_factors = CORE_FACTORS + [r[0] for r in t12_factors]
    print(f"\n[Load+IC] {len(all_factors)} factors (5 CORE + {len(t12_factors)} T12) 逐个加载...")
    ic_series = {}
    for fname in all_factors:
        t_load = time.time()
        fdf = pd.read_sql(
            """SELECT code, trade_date, neutral_value
               FROM factor_values
               WHERE factor_name = %s AND neutral_value IS NOT NULL""",
            conn,
            params=(fname,),
        )
        if fdf.empty:
            print(f"  {fname}: SKIP (no data)")
            continue
        wide = fdf.pivot_table(
            index="trade_date", columns="code", values="neutral_value", aggfunc="first"
        ).sort_index()
        del fdf  # 即时释放长表内存
        common = wide.index.intersection(fwd_ret.index)
        if len(common) < 30:
            print(f"  {fname}: SKIP (insufficient dates: {len(common)})")
            continue
        ic = compute_ic_series(wide.loc[common], fwd_ret.loc[common])
        ic_series[fname] = ic
        del wide  # 即时释放 wide 表 (IC 时序已保留)
        print(f"  {fname}: n_days={int(ic.notna().sum())}, IC_mean={float(ic.mean()):+.4f} ({time.time()-t_load:.1f}s)")
    conn.close()

    # IC time series correlation: T12 factors vs CORE 5
    print("\n[IC Correlation Matrix] T12 factor IC series vs CORE 5 IC series")

    t12_analysis = {}
    for row in t12_factors:
        fname, ic_20d, ic_ir, ic_bull, ic_bear, ic_side, regime_sens, max_corr_f, max_corr_v = row
        if fname not in ic_series:
            continue

        t12_ic = ic_series[fname]
        # Correlation with each CORE factor's IC time series
        ic_corrs = {}
        for cf in CORE_FACTORS:
            if cf not in ic_series:
                continue
            merged = pd.DataFrame({"a": t12_ic, "b": ic_series[cf]}).dropna()
            if len(merged) < 30:
                continue
            c = float(merged.corr().iloc[0, 1])
            ic_corrs[cf] = round(c, 4) if not np.isnan(c) else 0.0

        # Regime hedge verdict
        # True hedge: t12 IC time series is NEGATIVE correlated with CORE IC time series
        # Same signal: t12 IC moves with CORE → not a hedge
        mean_corr_with_core = np.mean(list(ic_corrs.values())) if ic_corrs else 0.0

        t12_analysis[fname] = {
            "ic_20d": float(ic_20d) if ic_20d is not None else None,
            "ic_ir": float(ic_ir) if ic_ir is not None else None,
            "ic_bull": float(ic_bull) if ic_bull is not None else None,
            "ic_bear": float(ic_bear) if ic_bear is not None else None,
            "ic_sideways": float(ic_side) if ic_side is not None else None,
            "regime_sensitivity": float(regime_sens) if regime_sens is not None else None,
            "bull_bear_sign_flip": (
                ic_bull is not None and ic_bear is not None
                 and np.sign(float(ic_bull)) != np.sign(float(ic_bear))
            ),
            "max_corr_factor_profile": max_corr_f,
            "max_corr_value_profile": float(max_corr_v) if max_corr_v is not None else None,
            "ic_ts_corr_with_core": ic_corrs,
            "mean_ic_ts_corr_with_core": round(float(mean_corr_with_core), 4),
            "is_regime_hedge": mean_corr_with_core < -0.1,  # 弱负相关阈值
        }

    # 报告
    print("\n" + "=" * 100)
    print("  Template 12 (regime-conditional) 6 因子分析")
    print("=" * 100)
    print(
        f"  {'Factor':<25} {'IC20d':>8} {'IR':>7} {'Bull':>8} {'Bear':>8} "
        f"{'Regime':>7} {'Flip':>5} {'MeanICcorr':>11} {'Hedge':>6}"
    )
    print("  " + "-" * 93)
    for fname, r in t12_analysis.items():
        ic = r.get("ic_20d", 0) or 0
        ir = r.get("ic_ir", 0) or 0
        bull = r.get("ic_bull", 0) or 0
        bear = r.get("ic_bear", 0) or 0
        sens = r.get("regime_sensitivity", 0) or 0
        flip = "YES" if r.get("bull_bear_sign_flip") else "no"
        mc = r.get("mean_ic_ts_corr_with_core", 0)
        hedge = "✓" if r.get("is_regime_hedge") else "✗"
        print(
            f"  {fname:<25} {ic:>+8.4f} {ir:>+7.3f} {bull:>+8.4f} {bear:>+8.4f} "
            f"{sens:>7.4f} {flip:>5} {mc:>+11.4f} {hedge:>6}"
        )

    print("\n  注释:")
    print("    - Flip: bull/bear IC 符号是否反转 (regime 敏感)")
    print("    - MeanICcorr: 该因子 IC 时序与 5 个 CORE IC 时序的平均 Pearson 相关")
    print("    - Hedge: MeanICcorr < -0.1 标记为可能的 regime hedge")
    print("=" * 100)

    # Save
    output = {
        "meta": {
            "total_factors": len(t12_analysis),
            "core_factors": CORE_FACTORS,
            "note": "IC time series correlation 衡量 regime 是否同步; 符号反转衡量方向是否regime-dependent",
        },
        "factors": t12_analysis,
    }
    out_path = BASELINE_DIR / "template12_analysis.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")


if __name__ == "__main__":
    main()
