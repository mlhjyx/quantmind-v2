"""IC正式评估 — 10个minute_bars日频因子。

通过ic_calculator统一口径计算raw IC (铁律19)。
neutral IC需先跑fast_neutralize_batch, 本脚本先评估raw_value。

Usage:
    python scripts/research/eval_minute_ic.py               # 评估全部10因子
    python scripts/research/eval_minute_ic.py --factor opening_volume_share_20  # 单因子

输出: 每因子 IC_mean / IC_std / ICIR / t_stat / hit_rate + 年度分解
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from engines.ic_calculator import compute_factor_ic_full  # noqa: E402
from engines.minute_feature_engine import (  # noqa: E402
    MINUTE_FACTOR_DIRECTION,
    MINUTE_FEATURES,
)

from app.services.db import get_sync_conn  # noqa: E402


def load_price_data(conn, start: str = "2019-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    """加载adj_close价格数据。"""
    sql = """
        SELECT kd.code, kd.trade_date,
               kd.close * (SELECT af.adj_factor
                           FROM klines_daily af
                           WHERE af.code = kd.code
                           ORDER BY af.trade_date DESC LIMIT 1
                          ) / NULLIF(kd.adj_factor, 0) as adj_close
        FROM klines_daily kd
        WHERE kd.trade_date BETWEEN %s AND %s
          AND kd.volume > 0
          AND kd.adj_factor IS NOT NULL
    """
    print("  Loading price data...", end="", flush=True)
    df = pd.read_sql(sql, conn, params=(start, end))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    print(f" {len(df):,} rows")
    return df


def load_price_data_simple(conn, start: str = "2019-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    """简化价格加载: 直接用close (非复权, 但IC排名不受影响)。"""
    sql = """
        SELECT code, trade_date, close as adj_close
        FROM klines_daily
        WHERE trade_date BETWEEN %s AND %s
          AND volume > 0
    """
    print("  Loading price data (simple)...", end="", flush=True)
    df = pd.read_sql(sql, conn, params=(start, end))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    print(f" {len(df):,} rows")
    return df


def load_benchmark(conn, start: str = "2019-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    """加载CSI300基准数据。"""
    sql = """
        SELECT trade_date, close
        FROM index_daily
        WHERE index_code = '000300.SH'
          AND trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """
    print("  Loading benchmark...", end="", flush=True)
    df = pd.read_sql(sql, conn, params=(start, end))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    print(f" {len(df):,} rows")
    return df


def load_factor_data(conn, factor_name: str, start: str = "2019-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    """加载单因子数据 (raw_value) via FactorCache (P1-4 迁移, DATA_SYSTEM_V1).

    优先走 Parquet 缓存, miss 时回 DB. 保持原 `neutral_value` 列名以兼容
    compute_factor_ic_full(factor_value_col='neutral_value') 调用方.
    """
    from datetime import datetime as _dt

    try:
        from data.factor_cache import FactorCache
    except ModuleNotFoundError:
        from backend.data.factor_cache import FactorCache

    cache = FactorCache()
    start_d = _dt.strptime(start, "%Y-%m-%d").date()
    end_d = _dt.strptime(end, "%Y-%m-%d").date()
    df = cache.load(
        factor_name, column="raw_value",
        start=start_d, end=end_d, conn=conn,
    )
    if df.empty:
        return pd.DataFrame(columns=["code", "trade_date", "factor_name", "neutral_value"])
    df = df.rename(columns={"value": "neutral_value"})
    df["factor_name"] = factor_name
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df[["code", "trade_date", "factor_name", "neutral_value"]]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="IC evaluation for minute features")
    parser.add_argument("--factor", type=str, help="Single factor name")
    parser.add_argument("--start", type=str, default="2021-01-01")
    parser.add_argument("--end", type=str, default="2025-12-31")
    parser.add_argument("--horizon", type=int, default=20)
    args = parser.parse_args()

    factors = [args.factor] if args.factor else MINUTE_FEATURES

    conn = get_sync_conn()
    try:
        price_df = load_price_data_simple(conn, args.start, args.end)
        benchmark_df = load_benchmark(conn, args.start, args.end)

        print(f"\n{'='*90}")
        print(f"{'Factor':<35} {'IC_mean':>8} {'IC_std':>8} {'ICIR':>8} {'t_stat':>8} {'hit%':>6} {'N_days':>7} {'dir':>4}")
        print(f"{'='*90}")

        results = []
        for factor_name in factors:
            factor_df = load_factor_data(conn, factor_name, args.start, args.end)
            if factor_df.empty:
                print(f"{factor_name:<35} {'NO DATA':>8}")
                continue

            try:
                result = compute_factor_ic_full(
                    factor_df, price_df, benchmark_df,
                    horizon=args.horizon,
                    factor_value_col="neutral_value",  # mapped from raw_value in SQL
                )
                stats = result["stats"]
                direction = MINUTE_FACTOR_DIRECTION.get(factor_name, 0)

                # 方向调整: 如果direction=-1, IC应为负数才好
                raw_ic = stats["mean"]
                directional_ic = raw_ic * direction

                print(
                    f"{factor_name:<35} "
                    f"{raw_ic:>8.4f} "
                    f"{stats['std']:>8.4f} "
                    f"{stats.get('ir', 0):>8.3f} "
                    f"{stats.get('t_stat', 0):>8.2f} "
                    f"{stats.get('hit_rate', 0)*100:>5.1f}% "
                    f"{stats.get('n_days', 0):>7} "
                    f"{'OK' if directional_ic > 0 else 'REV':>4}"
                )

                results.append({
                    "factor": factor_name,
                    "ic_mean": raw_ic,
                    "ic_std": stats["std"],
                    "icir": stats.get("ir", 0),
                    "t_stat": stats.get("t_stat", 0),
                    "hit_rate": stats.get("hit_rate", 0),
                    "n_days": stats.get("n_days", 0),
                    "direction": direction,
                    "directional_ic": directional_ic,
                })

            except Exception as e:
                print(f"{factor_name:<35} ERROR: {e}")

        if results:
            print(f"\n{'='*90}")
            print(f"\nSummary: {len(results)} factors evaluated")
            # 按 |directional_ic| 排序
            sorted_results = sorted(results, key=lambda x: abs(x["directional_ic"]), reverse=True)
            print("\nTop factors by |directional IC|:")
            for r in sorted_results[:5]:
                status = "PASS" if abs(r["t_stat"]) >= 2.5 else "WEAK" if abs(r["t_stat"]) >= 2.0 else "FAIL"
                print(f"  {r['factor']:<35} IC={r['ic_mean']:+.4f} t={r['t_stat']:.2f} [{status}]")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
