#!/usr/bin/env python3
"""Step 6-E Part 1: Alpha 衰减归因 — 单因子逐年 IC 分解.

对 CORE 5 + 3 个审计漏网候选因子, 计算 2014-2026 每年的:
  - IC mean / std / IR / t_stat / hit_rate

数据源: cache/backtest/*/*.parquet (12 年 price + factor 缓存)
共享模块: engines.ic_calculator (铁律 18 统一口径)

输出:
  cache/baseline/factor_ic_yearly_matrix.json  — CORE 5 × 12 年 IC 矩阵 + 衰减结论
  cache/baseline/candidate_ic_yearly.json      — 3 个候选因子的年度 IC (仅 5 年重叠)

用法:
    python scripts/research/alpha_decay_attribution.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

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
    summarize_ic_yearly,
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

CANDIDATE_FACTORS = [
    "turnover_stability_20",
    "atr_norm_20",
    "gap_frequency_20",
]

HORIZON = 20  # T+1 到 T+20, 约 1 个月, 对齐 monthly rebalance


# ============================================================
# 数据加载
# ============================================================


def load_price_benchmark_12yr():
    """加载 12 年 price + benchmark (从 Parquet 缓存)."""
    print("[Load] 12 年 price + benchmark...")
    t0 = time.time()
    price_parts, bench_parts = [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))

    price_df = pd.concat(price_parts, ignore_index=True)
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")

    # 排除 ST/BJ/停牌/新股 (universe 跟策略一致)
    before = len(price_df)
    price_df = price_df[
        (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
        & (price_df["board"].fillna("") != "bse")
    ].copy()
    print(f"  price filtered: {before:,} → {len(price_df):,} ({(1-len(price_df)/before)*100:.1f}% removed)")

    print(f"  price: {price_df.shape}, bench: {bench_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df


def load_factor_from_parquet(factor_name: str) -> pd.DataFrame:
    """从 cache/backtest/*/factor_data.parquet 加载某个因子 12 年的值."""
    print(f"  loading factor {factor_name}...")
    parts = []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        fp = yr_dir / "factor_data.parquet"
        if not fp.exists():
            continue
        fdf = pd.read_parquet(fp)
        fdf = fdf[fdf["factor_name"] == factor_name]
        if not fdf.empty:
            parts.append(fdf)
    if not parts:
        return pd.DataFrame()
    result = pd.concat(parts, ignore_index=True)
    # Parquet "raw_value" 实际是 neutral_value (SCHEMA.md)
    if "neutral_value" not in result.columns and "raw_value" in result.columns:
        result = result.rename(columns={"raw_value": "neutral_value"})
    return result


def load_factor_from_db(factor_name: str, conn) -> pd.DataFrame:
    """Fallback: 直接从 DB factor_values 加载 (用于 Parquet 没有的候选因子)."""
    print(f"  loading factor {factor_name} from DB...")
    df = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE factor_name = %s AND neutral_value IS NOT NULL""",
        conn,
        params=(factor_name,),
    )
    return df


# ============================================================
# IC 计算主循环
# ============================================================


def compute_factor_yearly_ic(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    factor_name: str,
) -> dict:
    """单因子 12 年 IC + 逐年细分."""
    if factor_df.empty:
        return {
            "factor_name": factor_name,
            "error": "factor_df empty",
        }

    # 构造 fwd excess returns (整个 12 年一次)
    fwd_ret = compute_forward_excess_returns(
        price_df, bench_df, horizon=HORIZON, price_col="adj_close"
    )

    # pivot 因子 (date × code)
    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="first"
    ).sort_index()

    # 只用 factor_df 的日期范围 (避免 fwd_ret 越界)
    common_dates = factor_wide.index.intersection(fwd_ret.index)
    if len(common_dates) < 60:
        return {
            "factor_name": factor_name,
            "error": f"insufficient dates ({len(common_dates)})",
        }

    factor_wide = factor_wide.loc[common_dates]
    fwd_ret_slice = fwd_ret.loc[common_dates]

    # IC 时间序列
    ic_series = compute_ic_series(factor_wide, fwd_ret_slice)

    # 全期汇总
    full_stats = summarize_ic_stats(ic_series)
    full_stats["date_start"] = str(ic_series.dropna().index.min())
    full_stats["date_end"] = str(ic_series.dropna().index.max())

    # 逐年 (2014-2026)
    yearly_df = summarize_ic_yearly(ic_series)
    yearly_records = yearly_df.to_dict("records")

    return {
        "factor_name": factor_name,
        "full_sample": full_stats,
        "yearly": yearly_records,
        "ic_series_length": len(ic_series),
        "ic_non_null": int(ic_series.notna().sum()),
    }


def split_period_stats(ic_series: pd.Series) -> dict:
    """2014-2020 vs 2021-2026 分期 (衰减判定)."""
    # ic_series.index 可能是 date 或 datetime, 先对齐成 DatetimeIndex
    dt_idx = pd.DatetimeIndex(pd.to_datetime(ic_series.index))
    mask_early = dt_idx < pd.Timestamp("2021-01-01")
    mask_late = ~mask_early

    early = pd.Series(ic_series.values[mask_early])
    late = pd.Series(ic_series.values[mask_late])

    return {
        "early_2014_2020": summarize_ic_stats(early),
        "late_2021_2026": summarize_ic_stats(late),
    }


# ============================================================
# Main
# ============================================================


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df = load_price_benchmark_12yr()
    conn = get_sync_conn()

    # ============ CORE 5 ============
    print("\n[CORE 5] 逐年 IC 分解...")
    core_results = {}
    for f in CORE_FACTORS:
        fdf = load_factor_from_parquet(f)
        if fdf.empty:
            fdf = load_factor_from_db(f, conn)
        result = compute_factor_yearly_ic(fdf, price_df, bench_df, f)

        # 补充分期统计
        if "error" not in result:
            # 重算 ic_series (不 cache 因为内存)
            factor_wide = fdf.pivot_table(
                index="trade_date", columns="code", values="neutral_value", aggfunc="first"
            ).sort_index()
            fwd_ret = compute_forward_excess_returns(
                price_df, bench_df, horizon=HORIZON, price_col="adj_close"
            )
            common = factor_wide.index.intersection(fwd_ret.index)
            ic_s = compute_ic_series(factor_wide.loc[common], fwd_ret.loc[common])
            result["period_split"] = split_period_stats(ic_s)

        core_results[f] = result

        # 打印简要
        if "error" in result:
            print(f"  {f}: ERROR {result['error']}")
        else:
            fs = result["full_sample"]
            print(
                f"  {f}: full IC={fs['mean']:+.4f} IR={fs['ir']:+.3f} "
                f"hit={fs['hit_rate']:.2%} n={fs['n_days']}"
            )

    # ============ Candidates ============
    print("\n[Candidates] 3 个漏网因子 (5yr 重叠对比)...")
    candidate_results = {}
    for f in CANDIDATE_FACTORS:
        fdf = load_factor_from_db(f, conn)
        if fdf.empty:
            candidate_results[f] = {"error": "no data"}
            continue

        result = compute_factor_yearly_ic(fdf, price_df, bench_df, f)
        candidate_results[f] = result

        if "error" in result:
            print(f"  {f}: ERROR {result['error']}")
        else:
            fs = result["full_sample"]
            print(
                f"  {f}: IC={fs['mean']:+.4f} IR={fs['ir']:+.3f} "
                f"hit={fs['hit_rate']:.2%} n={fs['n_days']}"
            )

    conn.close()

    # ============ 衰减结论 ============
    print("\n[Analysis] 衰减排名 (|IC_late| / |IC_early| 比率)...")
    decay_ranking = []
    for f in CORE_FACTORS:
        r = core_results[f]
        if "error" in r or "period_split" not in r:
            continue
        ps = r["period_split"]
        early_abs = abs(ps["early_2014_2020"]["mean"])
        late_abs = abs(ps["late_2021_2026"]["mean"])
        retention = late_abs / early_abs if early_abs > 0 else 0.0
        decay_ranking.append(
            {
                "factor_name": f,
                "early_ic_mean": ps["early_2014_2020"]["mean"],
                "late_ic_mean": ps["late_2021_2026"]["mean"],
                "early_ir": ps["early_2014_2020"]["ir"],
                "late_ir": ps["late_2021_2026"]["ir"],
                "retention_ratio": round(retention, 3),
                "decay_pct": round((1 - retention) * 100, 1),
            }
        )

    decay_ranking.sort(key=lambda x: x["retention_ratio"])  # 最差在前

    print(
        f"\n  {'Factor':<25} {'Early IC':>9} {'Late IC':>9} {'Early IR':>9} "
        f"{'Late IR':>9} {'Retention':>10} {'Decay %':>9}"
    )
    print("  " + "-" * 80)
    for r in decay_ranking:
        print(
            f"  {r['factor_name']:<25} "
            f"{r['early_ic_mean']:>+9.4f} {r['late_ic_mean']:>+9.4f} "
            f"{r['early_ir']:>+9.3f} {r['late_ir']:>+9.3f} "
            f"{r['retention_ratio']:>10.2f} {r['decay_pct']:>+8.1f}%"
        )

    # ============ 保存 ============
    core_output = {
        "meta": {
            "version": IC_CALCULATOR_VERSION,
            "id": IC_CALCULATOR_ID,
            "horizon": HORIZON,
            "computed_at": str(date.today()),
        },
        "core_factors": core_results,
        "decay_ranking": decay_ranking,
    }
    core_path = BASELINE_DIR / "factor_ic_yearly_matrix.json"
    core_path.write_text(json.dumps(core_output, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {core_path}")

    cand_output = {
        "meta": {
            "version": IC_CALCULATOR_VERSION,
            "horizon": HORIZON,
            "note": "候选因子数据只有 5 年 (2020-07 起), 无法与 CORE 做 12 年对比",
        },
        "candidates": candidate_results,
    }
    cand_path = BASELINE_DIR / "candidate_ic_yearly.json"
    cand_path.write_text(json.dumps(cand_output, indent=2, ensure_ascii=False, default=str))
    print(f"[Save] {cand_path}")

    # 5yr 重叠对比
    print("\n[Overlap] 2021-2026 CORE vs Candidates (5 yr only)...")
    print(
        f"  {'Factor':<25} {'IC mean':>9} {'IC IR':>9} {'Hit':>7} {'|IC|':>9}"
    )
    print("  " + "-" * 65)

    # CORE late period
    for f in CORE_FACTORS:
        r = core_results.get(f)
        if "error" in r or "period_split" not in r:
            continue
        late = r["period_split"]["late_2021_2026"]
        print(
            f"  {f:<25} {late['mean']:>+9.4f} {late['ir']:>+9.3f} "
            f"{late['hit_rate']:>7.2%} {abs(late['mean']):>9.4f}"
        )

    # Candidates (full period, which IS 2021-2026)
    for f in CANDIDATE_FACTORS:
        r = candidate_results.get(f)
        if r is None or "error" in r:
            continue
        fs = r.get("full_sample", {})
        print(
            f"  {f:<25} {fs.get('mean', 0):>+9.4f} {fs.get('ir', 0):>+9.3f} "
            f"{fs.get('hit_rate', 0):>7.2%} {abs(fs.get('mean', 0)):>9.4f}"
        )


if __name__ == "__main__":
    main()
