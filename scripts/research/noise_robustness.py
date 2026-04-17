#!/usr/bin/env python3
"""Step 6-F Part 4: 因子噪声鲁棒性检查 (AlphaEval 维度).

对 batch_gate PASS 因子加 5% 高斯噪声后重算 IC, 计算 retention 比率。
retention < 0.5 标记为 fragile, 不应进入 Active 池。

数据源: cache/backtest/*/*.parquet (12 年缓存)
IC 口径: 共享 ic_calculator (铁律 19)

噪声方法 (AlphaEval 标准):
  noisy_value = clean_value + noise
  noise ~ N(0, sigma)
  sigma = 0.05 * std(clean_value)  # 5% 相对噪声

计算:
  clean_IC  = Spearman(neutral_value, fwd_excess_return)
  noisy_IC  = Spearman(neutral_value + noise, fwd_excess_return)
  retention = |noisy_IC| / |clean_IC|

输出:
  cache/baseline/noise_robustness.json — 排名表 + fragile 标记

用法:
    python scripts/research/noise_robustness.py
    python scripts/research/noise_robustness.py --noise-pct 0.05
"""

from __future__ import annotations

import argparse
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
    IC_CALCULATOR_ID,
    IC_CALCULATOR_VERSION,
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"

HORIZON = 20
DEFAULT_NOISE_PCT = 0.05
RNG_SEED = 42  # 可复现性


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
    print(f"  price: {price_df.shape}, bench: {bench_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df


def load_pass_factors_from_batch_gate() -> list[str]:
    """从 batch_gate_results.json 读出 PASS 因子."""
    p = BASELINE_DIR / "batch_gate_results.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} 不存在, 请先跑 batch_gate.py")
    data = json.loads(p.read_text())
    pass_factors = [
        f for f, r in data["results"].items()
        if r.get("overall_verdict") == "PASS"
    ]
    return pass_factors


def load_factor(factor_name: str, conn) -> pd.DataFrame:
    """优先 Parquet, fallback DB."""
    parts = []
    for year_dir in CACHE_DIR.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        fp = year_dir / "factor_data.parquet"
        if not fp.exists():
            continue
        fdf = pd.read_parquet(fp)
        fdf = fdf[fdf["factor_name"] == factor_name]
        if not fdf.empty:
            parts.append(fdf)
    if parts:
        factor_df = pd.concat(parts, ignore_index=True)
        if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
            factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
        return factor_df

    return pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values WHERE factor_name = %s AND neutral_value IS NOT NULL""",
        conn,
        params=(factor_name,),
    )


def add_gaussian_noise(factor_wide: pd.DataFrame, noise_pct: float, rng) -> pd.DataFrame:
    """每天截面独立加噪声 (避免跨日相关性)."""
    result = factor_wide.copy()
    for td in result.index:
        row = result.loc[td].dropna()
        if len(row) < 5:
            continue
        sigma = float(row.std()) * noise_pct
        if sigma <= 0:
            continue
        noise = rng.normal(0, sigma, size=len(row))
        result.loc[td, row.index] = row.values + noise
    return result


def compute_robustness(factor_df, fwd_ret, noise_pct: float, rng) -> dict:
    """计算 clean_IC, noisy_IC, retention."""
    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="first"
    ).sort_index()

    common = factor_wide.index.intersection(fwd_ret.index)
    if len(common) < 60:
        return {"error": f"insufficient overlap ({len(common)})"}

    factor_wide = factor_wide.loc[common]
    fwd_slice = fwd_ret.loc[common]

    # Clean IC
    clean_ic = compute_ic_series(factor_wide, fwd_slice)
    clean_stats = summarize_ic_stats(clean_ic)
    clean_abs_mean = abs(clean_stats["mean"])

    # Noisy IC
    noisy_wide = add_gaussian_noise(factor_wide, noise_pct, rng)
    noisy_ic = compute_ic_series(noisy_wide, fwd_slice)
    noisy_stats = summarize_ic_stats(noisy_ic)
    noisy_abs_mean = abs(noisy_stats["mean"])

    retention = noisy_abs_mean / clean_abs_mean if clean_abs_mean > 0 else 0.0
    fragile = retention < 0.5

    return {
        "clean_ic": clean_stats["mean"],
        "noisy_ic": noisy_stats["mean"],
        "clean_ir": clean_stats["ir"],
        "noisy_ir": noisy_stats["ir"],
        "clean_t_stat": clean_stats["t_stat"],
        "noisy_t_stat": noisy_stats["t_stat"],
        "retention": round(retention, 4),
        "fragile": fragile,
        "n_days": clean_stats["n_days"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--noise-pct", type=float, default=DEFAULT_NOISE_PCT)
    parser.add_argument("--factor", type=str, help="只测单因子")
    args = parser.parse_args()

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df = load_price_bench()
    print("[Precompute] forward excess returns (horizon=20)...")
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=HORIZON, price_col="adj_close")
    print(f"  fwd_ret: {fwd_ret.shape}")

    conn = get_sync_conn()
    rng = np.random.default_rng(RNG_SEED)

    if args.factor:
        factor_list = [args.factor]
    else:
        factor_list = load_pass_factors_from_batch_gate()
    print(f"\n[Batch] {len(factor_list)} factors (PASS from batch_gate)")
    print(f"[Noise] sigma = {args.noise_pct * 100:.0f}% × cross-section std")
    print(f"[IC] {IC_CALCULATOR_ID} v{IC_CALCULATOR_VERSION}")

    results = []
    t0 = time.time()
    for i, f in enumerate(factor_list):
        factor_df = load_factor(f, conn)
        if factor_df.empty:
            print(f"  [{i+1}/{len(factor_list)}] {f}: SKIP (no data)")
            continue

        try:
            r = compute_robustness(factor_df, fwd_ret, args.noise_pct, rng)
            if "error" in r:
                print(f"  [{i+1}/{len(factor_list)}] {f}: {r['error']}")
                continue
            r["factor_name"] = f
            results.append(r)
            flag = " ❌FRAGILE" if r["fragile"] else " ✓"
            print(
                f"  [{i+1}/{len(factor_list)}] {f:<28} "
                f"clean={r['clean_ic']:+.4f} noisy={r['noisy_ic']:+.4f} "
                f"retention={r['retention']:.3f}{flag}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [{i+1}/{len(factor_list)}] {f}: ERROR {str(e)[:80]}")

    elapsed = time.time() - t0
    print(f"\n总耗时: {elapsed:.0f}s")
    conn.close()

    # 排序: retention 高 → 低
    results.sort(key=lambda x: x["retention"], reverse=True)

    # 汇总
    fragile_count = sum(1 for r in results if r["fragile"])
    summary = {
        "meta": {
            "ic_calculator_version": IC_CALCULATOR_VERSION,
            "ic_calculator_id": IC_CALCULATOR_ID,
            "horizon": HORIZON,
            "noise_pct": args.noise_pct,
            "rng_seed": RNG_SEED,
            "total_factors": len(results),
            "fragile_count": fragile_count,
            "robust_count": len(results) - fragile_count,
        },
        "ranking": results,
    }
    out_path = BASELINE_DIR / "noise_robustness.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    # 报告
    print("\n" + "=" * 76)
    print(f"  噪声鲁棒性 ({args.noise_pct * 100:.0f}% Gaussian) — 21 PASS factors")
    print("=" * 76)
    print(
        f"  {'Factor':<28} {'Clean IC':>9} {'Noisy IC':>9} {'Retention':>10} {'Fragile':>8}"
    )
    print("  " + "-" * 70)
    for r in results:
        flag = "❌YES" if r["fragile"] else "✓"
        print(
            f"  {r['factor_name']:<28} "
            f"{r['clean_ic']:>+9.4f} {r['noisy_ic']:>+9.4f} "
            f"{r['retention']:>10.3f} {flag:>8}"
        )

    print(f"\n  Robust:  {len(results) - fragile_count}")
    print(f"  Fragile: {fragile_count}")
    print("=" * 76)


if __name__ == "__main__":
    main()
