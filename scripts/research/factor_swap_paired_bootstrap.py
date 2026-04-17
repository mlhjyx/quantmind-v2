#!/usr/bin/env python3
"""Step 6-F Part 1: 因子替换 paired bootstrap.

测试 turnover_stability_20 / turnover_std_20 / maxret_20 等强 IR 因子
是否能显著替换 turnover_mean_20 (CORE 5 之一).

方法:
  1. 三个测试组:
     A. base = CORE 5 (现有)
     B. variant_stability = turnover_stability_20 替换 turnover_mean_20
     C. variant_std = turnover_std_20 替换 turnover_mean_20
     D. variant_maxret = maxret_20 替换 turnover_mean_20
  2. 每组用 run_hybrid_backtest 跑 12 年回测
  3. Paired bootstrap (N=1000): 重采样日收益率, 比较 Sharpe 差
  4. 输出 Sharpe 差 / 95% CI / p-value / 逐年度对比

数据源: cache/backtest/*.parquet
基线: 12yr in-sample Sharpe=0.5309 (Step 6-D)

输出:
  cache/baseline/factor_swap_bootstrap.json
  cache/baseline/factor_swap_yearly.json (逐年度对比)

用法:
    python scripts/research/factor_swap_paired_bootstrap.py
    python scripts/research/factor_swap_paired_bootstrap.py --n-bootstrap 1000
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
from engines.backtest import BacktestConfig, PMSConfig  # noqa: E402
from engines.backtest.runner import run_hybrid_backtest  # noqa: E402
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino  # noqa: E402
from engines.slippage_model import SlippageConfig  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"

# 候选替换 (factor_to_replace, replacement, replacement_direction)
SWAPS = [
    ("turnover_mean_20", "turnover_stability_20", -1),
    ("turnover_mean_20", "turnover_std_20", -1),
    ("turnover_mean_20", "maxret_20", -1),
]

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}

DEFAULT_N_BOOTSTRAP = 1000
RNG_SEED = 42


def load_price_bench():
    print("[Load] price + benchmark...")
    t0 = time.time()
    price_parts, bench_parts = [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))
    price_df = pd.concat(price_parts, ignore_index=True).sort_values(["code", "trade_date"])
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date").sort_values("trade_date")
    print(f"  price: {price_df.shape}, bench: {bench_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df


def load_factors_from_db(factor_names: list[str], conn) -> pd.DataFrame:
    """加载多因子, 优先 Parquet, fallback DB."""
    parts = []
    parquet_factors = set()

    # 先尝试 parquet
    for year_dir in CACHE_DIR.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        fp = year_dir / "factor_data.parquet"
        if not fp.exists():
            continue
        fdf = pd.read_parquet(fp)
        fdf = fdf[fdf["factor_name"].isin(factor_names)]
        if not fdf.empty:
            parts.append(fdf)
            parquet_factors.update(fdf["factor_name"].unique())

    # DB fallback for missing factors
    missing = set(factor_names) - parquet_factors
    if missing:
        print(f"  loading from DB: {sorted(missing)}")
        placeholders = ",".join(["%s"] * len(missing))
        db_df = pd.read_sql(
            f"""SELECT code, trade_date, factor_name, neutral_value
                FROM factor_values
                WHERE factor_name IN ({placeholders}) AND neutral_value IS NOT NULL""",
            conn,
            params=tuple(missing),
        )
        # 列名兼容
        db_df["raw_value"] = db_df["neutral_value"]
        parts.append(db_df[["code", "trade_date", "factor_name", "raw_value"]])

    factor_df = pd.concat(parts, ignore_index=True)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
    return factor_df


def run_strategy(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    directions: dict,
    config: BacktestConfig,
) -> dict:
    """跑一次回测, 返回 nav + metrics."""
    result = run_hybrid_backtest(factor_df, directions, price_df, config, bench_df)
    nav = result.daily_nav
    returns = nav.pct_change().dropna()

    sharpe = float(calc_sharpe(returns))
    mdd = float(calc_max_drawdown(nav))
    sortino = float(calc_sortino(returns))
    n_days = len(nav)
    years = n_days / 244
    total_ret = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual = float((1 + total_ret) ** (1 / max(years, 0.01)) - 1)

    return {
        "nav": nav,
        "returns": returns,
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 6),
        "sortino": round(sortino, 4),
        "annual": round(annual, 6),
        "total_return": round(total_ret, 6),
        "n_days": n_days,
        "directions": dict(directions),
    }


def paired_bootstrap_sharpe_diff(
    base_returns: pd.Series, variant_returns: pd.Series, n: int, rng
) -> dict:
    """对齐两个收益序列, 重采样配对差, 计算 (Sharpe(variant) - Sharpe(base)) 分布."""
    df = pd.DataFrame({"b": base_returns, "v": variant_returns}).dropna()
    if len(df) < 30:
        return {"error": "insufficient overlap"}

    n_obs = len(df)
    diffs = []
    for _ in range(n):
        idx = rng.integers(0, n_obs, size=n_obs)
        sample = df.iloc[idx]
        sb = calc_sharpe(sample["b"])
        sv = calc_sharpe(sample["v"])
        diffs.append(sv - sb)

    diffs = np.array(diffs)
    actual_diff = float(calc_sharpe(df["v"]) - calc_sharpe(df["b"]))

    # p-value: bootstrap 分布中 < 0 的比例 (双边)
    p_lower = float(np.mean(diffs <= 0))  # variant 不优于 base
    p_upper = float(np.mean(diffs >= 0))  # variant 不劣于 base
    p_value = 2 * min(p_lower, p_upper)

    return {
        "actual_sharpe_diff": round(actual_diff, 4),
        "bootstrap_mean": round(float(diffs.mean()), 4),
        "bootstrap_std": round(float(diffs.std(ddof=1)), 4),
        "ci_95_lower": round(float(np.percentile(diffs, 2.5)), 4),
        "ci_95_upper": round(float(np.percentile(diffs, 97.5)), 4),
        "p_value": round(p_value, 4),
        "p_one_sided_better": round(1 - p_lower, 4),
        "n_obs": n_obs,
        "n_bootstrap": n,
    }


def yearly_breakdown(returns: pd.Series) -> dict:
    """逐年度 Sharpe."""
    r = returns.copy()
    r.index = pd.to_datetime(r.index)
    yearly = {}
    for year in range(2014, 2027):
        mask = r.index.year == year
        sub = r[mask]
        if len(sub) < 20:
            continue
        s = float(calc_sharpe(sub))
        yearly[year] = round(s, 4)
    return yearly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-bootstrap", type=int, default=DEFAULT_N_BOOTSTRAP)
    args = parser.parse_args()

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df = load_price_bench()
    conn = get_sync_conn()

    # 收集所有需要的因子
    all_factors = list(CORE_DIRECTIONS.keys())
    for _, replacement, _ in SWAPS:
        if replacement not in all_factors:
            all_factors.append(replacement)

    print(f"\n[Factors] 加载 {len(all_factors)} 因子: {all_factors}")
    factor_df = load_factors_from_db(all_factors, conn)
    print(f"  factor_df: {factor_df.shape}, factors loaded: {sorted(factor_df['factor_name'].unique())}")

    # Backtest config
    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    # === Base ===
    print("\n[Base] CORE 5 (current)")
    t0 = time.time()
    base_factor_df = factor_df[factor_df["factor_name"].isin(CORE_DIRECTIONS.keys())].copy()
    base = run_strategy(base_factor_df, price_df, bench_df, CORE_DIRECTIONS, config)
    print(f"  Sharpe={base['sharpe']}, MDD={base['mdd']:.2%}, Annual={base['annual']:.2%}, {time.time()-t0:.0f}s")

    # === Variants ===
    variants_results = {}
    rng = np.random.default_rng(RNG_SEED)
    for to_replace, replacement, repl_direction in SWAPS:
        label = f"{to_replace}→{replacement}"
        print(f"\n[Variant] {label}")
        new_dirs = dict(CORE_DIRECTIONS)
        del new_dirs[to_replace]
        new_dirs[replacement] = repl_direction
        variant_factor_df = factor_df[factor_df["factor_name"].isin(new_dirs.keys())].copy()
        if variant_factor_df.empty:
            print("  ERROR: no factor data")
            continue

        t0 = time.time()
        variant = run_strategy(variant_factor_df, price_df, bench_df, new_dirs, config)
        print(f"  Sharpe={variant['sharpe']}, MDD={variant['mdd']:.2%}, Annual={variant['annual']:.2%}, {time.time()-t0:.0f}s")

        # Paired bootstrap
        print(f"  bootstrap N={args.n_bootstrap}...")
        boot = paired_bootstrap_sharpe_diff(
            base["returns"], variant["returns"], args.n_bootstrap, rng
        )
        print(
            f"  diff={boot['actual_sharpe_diff']:+.4f} "
            f"CI95=[{boot['ci_95_lower']}, {boot['ci_95_upper']}] "
            f"p={boot['p_value']}"
        )

        # Yearly breakdown
        yearly_base = yearly_breakdown(base["returns"])
        yearly_variant = yearly_breakdown(variant["returns"])
        # Difference per year
        yearly_diff = {
            yr: round(yearly_variant.get(yr, 0) - yearly_base.get(yr, 0), 4)
            for yr in sorted(set(yearly_base) | set(yearly_variant))
        }

        variants_results[label] = {
            "to_replace": to_replace,
            "replacement": replacement,
            "metrics": {k: v for k, v in variant.items() if k not in ("nav", "returns", "directions")},
            "directions": variant["directions"],
            "vs_base": {
                "sharpe_diff": round(variant["sharpe"] - base["sharpe"], 4),
                "mdd_diff": round(variant["mdd"] - base["mdd"], 6),
                "annual_diff": round(variant["annual"] - base["annual"], 4),
            },
            "bootstrap": boot,
            "yearly_base": yearly_base,
            "yearly_variant": yearly_variant,
            "yearly_diff": yearly_diff,
        }

    conn.close()

    # 保存
    base_metrics = {k: v for k, v in base.items() if k not in ("nav", "returns", "directions")}
    base_yearly = yearly_breakdown(base["returns"])

    output = {
        "meta": {
            "n_bootstrap": args.n_bootstrap,
            "rng_seed": RNG_SEED,
            "config": {
                "top_n": 20,
                "rebalance": "monthly",
                "slippage": "volume_impact",
                "stamp_tax": "historical",
                "pms": True,
            },
        },
        "base": {
            "factors": list(CORE_DIRECTIONS.keys()),
            "directions": CORE_DIRECTIONS,
            "metrics": base_metrics,
            "yearly_sharpe": base_yearly,
        },
        "variants": variants_results,
    }
    out_path = BASELINE_DIR / "factor_swap_bootstrap.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    # === 总结 ===
    print("\n" + "=" * 88)
    print("  Factor Swap Paired Bootstrap")
    print("=" * 88)
    print(f"  Base CORE 5: Sharpe={base['sharpe']}, MDD={base['mdd']:.2%}, Annual={base['annual']:.2%}")
    print()

    for label, r in variants_results.items():
        m = r["metrics"]
        b = r["bootstrap"]
        sig = ""
        if b.get("p_value") is not None and b["p_value"] < 0.05:
            sig = " ✅ SIGNIFICANT (p<0.05)"
        elif b.get("p_value") is not None and b["p_value"] < 0.10:
            sig = " ⚠️ MARGINAL (p<0.10)"
        print(f"  {label}")
        print(
            f"    Sharpe={m['sharpe']} (Δ={r['vs_base']['sharpe_diff']:+.4f}) "
            f"MDD={m['mdd']:+.2%} (Δ={r['vs_base']['mdd_diff']:+.2%}) "
            f"Annual={m['annual']:+.2%}"
        )
        print(
            f"    Bootstrap CI95=[{b['ci_95_lower']:+.4f}, {b['ci_95_upper']:+.4f}], "
            f"p={b['p_value']}{sig}"
        )
        # Crisis years
        crisis_2017 = r["yearly_diff"].get(2017, 0)
        crisis_2018 = r["yearly_diff"].get(2018, 0)
        crisis_2022 = r["yearly_diff"].get(2022, 0)
        crisis_2023 = r["yearly_diff"].get(2023, 0)
        print(
            f"    Crisis improvement: 2017={crisis_2017:+.3f} 2018={crisis_2018:+.3f} "
            f"2022={crisis_2022:+.3f} 2023={crisis_2023:+.3f}"
        )

    print("=" * 88)


if __name__ == "__main__":
    main()
