"""分钟级日频特征计算编排器。

从MinuteDataCache加载Parquet → 计算10个日频特征 → 20日rolling → 写入factor_values。

Usage:
    python scripts/compute_minute_features.py --compute                # 全部年份
    python scripts/compute_minute_features.py --compute --year 2025    # 单年
    python scripts/compute_minute_features.py --ic-screen              # IC快筛
    python scripts/compute_minute_features.py --spot-check             # 抽样验算

Architecture:
    1. MinuteDataCache.load_year(year) → DataFrame
    2. GroupBy (code, trade_date) → compute_daily_minute_features() (纯函数, 铁律31)
    3. Per-stock 20-day rolling mean → factor values
    4. COPY+UPSERT to factor_values (铁律29: NaN→None, 铁律17: DataPipeline)

注: opening_volume_share 使用 rolling min (AlphaZero Alpha2 原文), 其余用 rolling mean。
"""

from __future__ import annotations

import argparse
import gc
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# 设置路径
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "research"))
sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from engines.minute_feature_engine import (  # noqa: E402
    _DAILY_KEYS,
    MINUTE_FEATURES,
    compute_daily_minute_features,
)
from minute_data_loader import MinuteDataCache  # noqa: E402

ROLLING_WINDOW = 20
# opening_volume_share 用 rolling min (AlphaZero Alpha2 原文: 5日最小值)
ROLLING_MIN_FACTORS = {"opening_volume_share"}


def process_year(year: int, cache: MinuteDataCache) -> pd.DataFrame:
    """处理单年: Parquet → 日频指标 → 20日rolling。

    Returns:
        DataFrame [code, trade_date, factor_name, raw_value]
    """
    print(f"\n{'='*60}")
    print(f"Processing {year} — 10 minute features")
    print(f"{'='*60}")

    t0 = time.time()
    df = cache.load_year(year)
    n_stocks = df["code"].nunique()
    print(f"  Loaded: {len(df):,} rows, {n_stocks} stocks")

    # ---- Step 1: 计算每日每股的raw指标 ----
    print("  Computing daily metrics...", end="", flush=True)
    t1 = time.time()

    daily_records: list[tuple] = []
    grouped = df.groupby(["code", "trade_date"], sort=False)
    total_groups = len(grouped)

    for i, ((code, td), group) in enumerate(grouped):
        o = group["open"].values.astype(np.float64)
        h = group["high"].values.astype(np.float64)
        lo = group["low"].values.astype(np.float64)
        c = group["close"].values.astype(np.float64)
        v = group["volume"].values.astype(np.float64)
        amt = group["amount"].values.astype(np.float64)
        mod = group["minute_of_day"].values

        metrics = compute_daily_minute_features(o, h, lo, c, v, amt, mod)
        for key, val in metrics.items():
            daily_records.append((code, td, key, val))

        if (i + 1) % 50000 == 0:
            print(f" {i+1}/{total_groups}", end="", flush=True)

    print(f" done ({time.time()-t1:.0f}s, {total_groups} groups)")

    del df, grouped
    gc.collect()

    daily_df = pd.DataFrame(
        daily_records, columns=["code", "trade_date", "factor_key", "value"]
    )
    del daily_records
    print(f"  Daily metrics: {len(daily_df):,} rows")

    # ---- Step 2: 20日rolling ----
    print("  Computing 20-day rolling...", end="", flush=True)
    t2 = time.time()

    parts = []
    for factor_key in _DAILY_KEYS:
        factor_name = factor_key + "_20"
        fdf = daily_df[daily_df["factor_key"] == factor_key].copy()
        fdf = fdf.sort_values(["code", "trade_date"])

        # 选择rolling函数: min for opening_volume_share, mean for others
        if factor_key in ROLLING_MIN_FACTORS:
            fdf["raw_value"] = (
                fdf.groupby("code")["value"]
                .transform(lambda x: x.rolling(ROLLING_WINDOW, min_periods=10).min())
            )
        else:
            fdf["raw_value"] = (
                fdf.groupby("code")["value"]
                .transform(lambda x: x.rolling(ROLLING_WINDOW, min_periods=10).mean())
            )

        valid = fdf.dropna(subset=["raw_value"])
        valid = valid[["code", "trade_date", "raw_value"]].copy()
        valid["factor_name"] = factor_name
        parts.append(valid)

    print(f" done ({time.time()-t2:.0f}s)")
    del daily_df
    gc.collect()

    result_df = pd.concat(parts, ignore_index=True)[
        ["code", "trade_date", "factor_name", "raw_value"]
    ]
    del parts

    elapsed = time.time() - t0
    n_factors = result_df["factor_name"].nunique()
    print(
        f"  Result: {len(result_df):,} rows, {n_factors} factors, {elapsed:.0f}s total"
    )
    return result_df


def write_to_db(result_df: pd.DataFrame, conn) -> int:
    """写入factor_values (COPY+UPSERT)。铁律29: NaN→None。"""
    if result_df.empty:
        return 0

    cur = conn.cursor()

    # Staging table
    cur.execute("DROP TABLE IF EXISTS _mf_staging")
    cur.execute("""
        CREATE TEMP TABLE _mf_staging (
            code VARCHAR, trade_date DATE, factor_name VARCHAR,
            raw_value DOUBLE PRECISION
        )
    """)

    # COPY (铁律29: NaN→\\N for NULL)
    tmp = result_df.copy()
    mask = ~np.isfinite(tmp["raw_value"].values)
    tmp.loc[mask, "raw_value"] = None

    buf = io.StringIO()
    for code, td, fname, val in zip(
        tmp["code"], tmp["trade_date"], tmp["factor_name"], tmp["raw_value"], strict=False
    ):
        val_str = "\\N" if val is None or pd.isna(val) else str(val)
        buf.write(f"{code}\t{td}\t{fname}\t{val_str}\n")
    written = len(tmp)
    del tmp

    buf.seek(0)
    cur.copy_from(
        buf,
        "_mf_staging",
        columns=("code", "trade_date", "factor_name", "raw_value"),
        null="\\N",
    )

    # UPSERT
    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _mf_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)

    conn.commit()
    print(f"  DB write: {written:,} rows upserted")
    return written


def ic_screen(conn) -> None:
    """IC快筛: 读取已入库的minute features, 计算neutral IC。"""

    cur = conn.cursor()

    print("\n=== IC Screen: Minute Features ===\n")
    print(f"{'Factor':<35} {'IC_mean':>10} {'IC_std':>10} {'t_stat':>10} {'N_months':>10}")
    print("-" * 80)

    for factor_name in MINUTE_FEATURES:
        cur.execute("""
            SELECT COUNT(*) FROM factor_values
            WHERE factor_name = %s AND raw_value IS NOT NULL
        """, (factor_name,))
        count = cur.fetchone()[0]
        if count == 0:
            print(f"{factor_name:<35} {'NO DATA':>10}")
            continue

        # 按月计算IC
        cur.execute("""
            SELECT DATE_TRUNC('month', fv.trade_date) as month,
                   CORR(fv.raw_value, kd.close_pct) as ic
            FROM factor_values fv
            JOIN (
                SELECT code, trade_date,
                       LEAD(close, 20) OVER (PARTITION BY code ORDER BY trade_date) / close - 1 as close_pct
                FROM klines_daily
            ) kd ON fv.code = kd.code AND fv.trade_date = kd.trade_date
            WHERE fv.factor_name = %s
              AND fv.raw_value IS NOT NULL
              AND kd.close_pct IS NOT NULL
            GROUP BY month
            HAVING COUNT(*) >= 30
            ORDER BY month
        """, (factor_name,))

        rows = cur.fetchall()
        if len(rows) < 6:
            print(f"{factor_name:<35} {'<6 months':>10}")
            continue

        ics = np.array([r[1] for r in rows if r[1] is not None], dtype=np.float64)
        ics = ics[np.isfinite(ics)]
        if len(ics) < 6:
            print(f"{factor_name:<35} {'<6 valid':>10}")
            continue

        ic_mean = np.mean(ics)
        ic_std = np.std(ics, ddof=1)
        t_stat = ic_mean / (ic_std / np.sqrt(len(ics))) if ic_std > 1e-10 else 0.0

        print(f"{factor_name:<35} {ic_mean:>10.4f} {ic_std:>10.4f} {t_stat:>10.2f} {len(ics):>10}")


def spot_check(cache: MinuteDataCache) -> None:
    """抽样验算: 检查1只股票1天的raw指标。"""
    df = cache.load_year(2025)
    dates = sorted(df["trade_date"].unique())
    test_date = dates[-10] if len(dates) >= 10 else dates[-1]
    codes = sorted(df["code"].unique())
    test_code = codes[0]

    group = df[(df["code"] == test_code) & (df["trade_date"] == test_date)]
    print(f"\n=== Spot Check: {test_code} on {test_date} ({len(group)} bars) ===")

    if len(group) == 0:
        print("No data")
        return

    o = group["open"].values.astype(np.float64)
    h = group["high"].values.astype(np.float64)
    lo = group["low"].values.astype(np.float64)
    c = group["close"].values.astype(np.float64)
    v = group["volume"].values.astype(np.float64)
    amt = group["amount"].values.astype(np.float64)
    mod = group["minute_of_day"].values

    metrics = compute_daily_minute_features(o, h, lo, c, v, amt, mod)

    print("\nDaily raw metrics (before 20-day rolling):")
    for k, val in sorted(metrics.items()):
        if np.isfinite(val):
            print(f"  {k}: {val:.6f}")
        else:
            print(f"  {k}: NaN")

    # 手动验证几个
    ret = np.diff(c) / c[:-1]
    print("\n--- Manual checks ---")
    print(f"  Bars: {len(group)}")
    print(f"  Realized vol (sum r²): {np.sum(ret**2):.8f} vs {metrics['high_freq_volatility']:.8f}")
    print(f"  Volume HHI: {np.sum((v/v.sum())**2):.6f} vs {metrics['volume_concentration']:.6f}")
    opening_share = v[mod <= 5].sum() / v.sum()
    print(f"  Opening vol share: {opening_share:.6f} vs {metrics['opening_volume_share']:.6f}")

    del df


def main():
    parser = argparse.ArgumentParser(
        description="Compute minute-bar daily features → factor_values"
    )
    parser.add_argument("--compute", action="store_true", help="Compute and write to DB")
    parser.add_argument("--year", type=int, help="Process single year")
    parser.add_argument("--ic-screen", action="store_true", help="IC screening")
    parser.add_argument("--spot-check", action="store_true", help="Spot check 1 stock-day")
    args = parser.parse_args()

    cache = MinuteDataCache()

    if args.compute:
        from app.services.db import get_sync_conn

        conn = get_sync_conn()
        try:
            years = [args.year] if args.year else cache.years_available()
            if not years:
                print("No minute_bars cache. Run: python scripts/research/minute_data_loader.py --build")
                return

            total_written = 0
            for year in sorted(years):
                result_df = process_year(year, cache)
                if not result_df.empty:
                    total_written += write_to_db(result_df, conn)
                del result_df
                gc.collect()

            print(f"\n{'='*60}")
            print(f"Total: {total_written:,} rows written to factor_values")
            print(f"Factors: {', '.join(MINUTE_FEATURES)}")
        finally:
            conn.close()

    elif args.ic_screen:
        from app.services.db import get_sync_conn

        conn = get_sync_conn()
        try:
            ic_screen(conn)
        finally:
            conn.close()

    elif args.spot_check:
        spot_check(cache)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
