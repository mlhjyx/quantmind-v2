#!/usr/bin/env python3
"""Step 6-E Part 3B (fast replacement): 12 年 IC 批量重算.

compute_factor_ic.py 在 12 年数据上 O(n²) 过慢 (30+ min 无进度). 本脚本用
engines.ic_calculator (vectorized) 完成相同任务, 预期 5-10 分钟/全因子。

策略:
  - 一次性加载 12 年 price + benchmark (复用)
  - 预计算 forward excess return (共享全因子)
  - 按因子循环, 从 Parquet 缓存或 DB 加载, 调 compute_ic_series
  - 批量 upsert 到 factor_ic_history (ic_1d/ic_5d/ic_10d/ic_20d)

不同于 compute_factor_ic.py:
  - 共享 ic_calculator 逻辑 (铁律 19 口径统一)
  - 用 neutral_value + excess return (CSI300)
  - 直接写 factor_ic_history 替代旧 "raw_return IC"

输出:
  - DB: factor_ic_history upsert (ON CONFLICT)
  - stdout: 每因子汇总

用法:
    python scripts/fast_ic_recompute.py             # 12 年全因子
    python scripts/fast_ic_recompute.py --factor bp_ratio  # 单因子
    python scripts/fast_ic_recompute.py --core      # 仅 CORE 5
    python scripts/fast_ic_recompute.py --dry-run   # 不写 DB
"""

from __future__ import annotations

import argparse
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
)
from psycopg2.extras import execute_values  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "backtest"

CORE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

HORIZONS = [1, 5, 10, 20]  # 跟 factor_ic_history 表 schema 对齐


def load_price_bench():
    """12 年 price + benchmark."""
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


def load_factor(factor_name: str, conn) -> pd.DataFrame:
    """优先从 Parquet, fallback 到 DB."""
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

    # Fallback DB
    return pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values WHERE factor_name = %s AND neutral_value IS NOT NULL""",
        conn,
        params=(factor_name,),
    )


def compute_multi_horizon_ic(
    factor_df: pd.DataFrame,
    fwd_rets_cache: dict,  # 预计算好的 {horizon: wide_df}
) -> pd.DataFrame:
    """对一个因子计算多 horizon IC (1d/5d/10d/20d).

    ⚠️ fwd_rets_cache 必须由调用方预计算 (compute_forward_excess_returns),
    避免在因子循环里重复 pivot (旧版 bug 导致 2+ 小时).
    """
    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="first"
    ).sort_index()

    # 对每个 horizon 算 IC 序列 (用预计算的 fwd_rets)
    ic_dfs = {}
    for h in HORIZONS:
        fwd = fwd_rets_cache[h]
        common = factor_wide.index.intersection(fwd.index)
        if len(common) < 20:
            ic_dfs[h] = pd.Series(dtype=float)
            continue
        ic_dfs[h] = compute_ic_series(factor_wide.loc[common], fwd.loc[common])

    # 合并到一张表
    result = pd.DataFrame(
        {f"ic_{h}d": ic_dfs[h] for h in HORIZONS}
    )
    result.index.name = "trade_date"
    return result.reset_index()


def upsert_ic_history(conn, factor_name: str, ic_df: pd.DataFrame, dry_run: bool):
    """批量 upsert factor_ic_history."""
    if ic_df.empty or dry_run:
        if dry_run:
            print(f"  [DRY-RUN] {factor_name}: 将写入 {len(ic_df)} 行")
        return 0

    records = []
    for _, row in ic_df.iterrows():
        records.append(
            (
                factor_name,
                row["trade_date"],
                float(row["ic_1d"]) if pd.notna(row["ic_1d"]) else None,
                float(row["ic_5d"]) if pd.notna(row["ic_5d"]) else None,
                float(row["ic_10d"]) if pd.notna(row["ic_10d"]) else None,
                float(row["ic_20d"]) if pd.notna(row["ic_20d"]) else None,
            )
        )

    cur = conn.cursor()
    execute_values(
        cur,
        """INSERT INTO factor_ic_history (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d)
           VALUES %s
           ON CONFLICT (factor_name, trade_date) DO UPDATE SET
             ic_1d = EXCLUDED.ic_1d,
             ic_5d = EXCLUDED.ic_5d,
             ic_10d = EXCLUDED.ic_10d,
             ic_20d = EXCLUDED.ic_20d""",
        records,
        page_size=5000,
    )
    conn.commit()
    return len(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", type=str)
    parser.add_argument("--core", action="store_true", help="仅 CORE 5")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    price_df, bench_df = load_price_bench()

    # 一次性预计算所有 horizon 的 fwd_rets (cache 避免因子循环重复 pivot)
    print(f"[Precompute] forward excess returns for horizons {HORIZONS}...")
    t0 = time.time()
    fwd_rets_cache = {
        h: compute_forward_excess_returns(price_df, bench_df, horizon=h, price_col="adj_close")
        for h in HORIZONS
    }
    print(f"  fwd_rets 4 horizons cached ({time.time() - t0:.1f}s)")

    conn = get_sync_conn()

    # 决定因子列表
    if args.factor:
        factor_list = [args.factor]
    elif args.core:
        factor_list = CORE_FACTORS
    else:
        # 所有有 neutral_value 的因子
        cur = conn.cursor()
        cur.execute(
            """SELECT DISTINCT factor_name FROM factor_values
               WHERE neutral_value IS NOT NULL ORDER BY factor_name"""
        )
        factor_list = [r[0] for r in cur.fetchall()]
    print(f"\n[Batch] {len(factor_list)} 因子")
    print(f"[IC口径] {IC_CALCULATOR_ID} v{IC_CALCULATOR_VERSION}")
    print(f"[Horizons] {HORIZONS}")

    total_t0 = time.time()
    results = []
    for i, f in enumerate(factor_list):
        t0 = time.time()
        factor_df = load_factor(f, conn)
        if factor_df.empty:
            print(f"  [{i+1}/{len(factor_list)}] {f}: SKIP (no data)")
            continue

        try:
            ic_df = compute_multi_horizon_ic(factor_df, fwd_rets_cache)
            if ic_df.empty:
                print(f"  [{i+1}/{len(factor_list)}] {f}: SKIP (empty IC)")
                continue

            # 汇总
            ic_20d = ic_df["ic_20d"].dropna()
            mean = float(ic_20d.mean()) if len(ic_20d) > 0 else 0.0
            std = float(ic_20d.std(ddof=1)) if len(ic_20d) > 1 else 0.0
            ir = mean / std if std > 0 else 0.0
            n_days = int(len(ic_20d))

            rows = upsert_ic_history(conn, f, ic_df, args.dry_run)
            elapsed = time.time() - t0
            print(
                f"  [{i+1}/{len(factor_list)}] {f:<30} "
                f"IC20d={mean:+.4f} IR={ir:+5.2f} n={n_days:>4} rows={rows:>5} ({elapsed:.1f}s)"
            )
            results.append(
                {"factor": f, "ic_20d_mean": mean, "ir": ir, "n_days": n_days, "rows": rows}
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [{i+1}/{len(factor_list)}] {f}: ERROR {str(e)[:80]}")

    conn.close()
    total_elapsed = time.time() - total_t0
    print(f"\n总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"完成因子: {len(results)}/{len(factor_list)}")

    # 最强/最弱 IR 排序
    if results:
        print("\n[Top 10 by |IR|]:")
        sorted_results = sorted(results, key=lambda x: abs(x["ir"]), reverse=True)[:10]
        for r in sorted_results:
            print(f"  {r['factor']:<30} |IR|={abs(r['ir']):5.2f}  IC={r['ic_20d_mean']:+.4f}  n={r['n_days']}")


if __name__ == "__main__":
    main()
