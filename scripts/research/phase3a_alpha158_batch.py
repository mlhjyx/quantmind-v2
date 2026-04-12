#!/usr/bin/env python3
"""Phase 3A-1: Alpha158 剩余因子批量入库。

从klines_daily读取OHLCV，调用alpha158_factors引擎计算全部158因子，
写入factor_values。已存在因子用ON CONFLICT DO UPDATE覆盖。

设计:
  - 按年份+分批股票处理（内存管理）
  - 每年加载前60日lookback数据（rolling窗口需要）
  - NaN → None（铁律29）
  - execute_values批量写入，batch_size=5000

用法:
  python scripts/research/phase3a_alpha158_batch.py
  python scripts/research/phase3a_alpha158_batch.py --start 2020 --end 2026
  python scripts/research/phase3a_alpha158_batch.py --start 2020 --end 2026 --stock-batch 200
"""

import argparse
import gc
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from engines.alpha158_factors import compute_all_alpha158, get_alpha158_names

DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"
BATCH_SIZE = 5000
LOOKBACK_DAYS = 90  # 60天窗口 + 30天安全边际


def load_klines_year(conn, year: int, lookback_start: date = None) -> pd.DataFrame:
    """加载指定年份的klines_daily数据，含lookback。"""
    if lookback_start is None:
        lookback_start = date(year - 1, 10, 1)  # 前一年10月开始（~90交易日lookback）

    sql = """
        SELECT code, trade_date, open, high, low, close, volume, amount
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date < %s
          AND volume > 0
        ORDER BY code, trade_date
    """
    year_end = date(year + 1, 1, 1)
    df = pd.read_sql(sql, conn, params=(lookback_start, year_end))
    print(f"  Loaded klines {year} (with lookback from {lookback_start}): {len(df):,} rows, {df['code'].nunique()} stocks")
    return df


def write_factor_batch(conn, rows: list[tuple]) -> int:
    """批量写入factor_values表 — 使用COPY+临时表+UPSERT，比execute_values快10-50x。

    rows = [(code, trade_date, factor_name, raw_value), ...]
    """
    if not rows:
        return 0

    import io

    cur = conn.cursor()

    # 1. 创建临时表(每次调用都重建，确保干净)
    cur.execute("DROP TABLE IF EXISTS _alpha158_staging")
    cur.execute("""
        CREATE TEMP TABLE _alpha158_staging (
            code VARCHAR, trade_date DATE, factor_name VARCHAR, raw_value DOUBLE PRECISION
        )
    """)

    # 2. COPY数据到临时表 (极快)
    buf = io.StringIO()
    for code, td, fname, val in rows:
        buf.write(f"{code}\t{td}\t{fname}\t{val}\n")
    buf.seek(0)
    cur.copy_from(buf, "_alpha158_staging", columns=("code", "trade_date", "factor_name", "raw_value"))

    # 3. UPSERT到正式表
    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _alpha158_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)

    total = len(rows)
    conn.commit()
    return total


def process_year(conn, year: int, stock_batch_size: int = 500) -> dict:
    """处理一个年份的所有Alpha158因子。

    分批加载股票计算，避免OOM。
    """
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)
    lookback_start = date(year - 1, 10, 1)

    # 获取该年份有数据的股票列表
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT code FROM klines_daily WHERE trade_date >= %s AND trade_date < %s AND volume > 0",
        (year_start, year_end),
    )
    all_codes = sorted([r[0] for r in cur.fetchall()])
    print(f"  {year}: {len(all_codes)} stocks total")

    stats = {"total_written": 0, "total_rows": 0, "stocks_processed": 0, "batches": 0}

    # 分批处理股票
    for batch_idx in range(0, len(all_codes), stock_batch_size):
        batch_codes = all_codes[batch_idx:batch_idx + stock_batch_size]
        t_batch = time.time()

        # 加载这批股票的数据（含lookback）
        codes_str = ",".join(f"'{c}'" for c in batch_codes)
        sql = f"""
            SELECT code, trade_date, open, high, low, close, volume, amount
            FROM klines_daily
            WHERE code IN ({codes_str})
              AND trade_date >= %s AND trade_date < %s
              AND volume > 0
            ORDER BY code, trade_date
        """
        price_df = pd.read_sql(sql, conn, params=(lookback_start, year_end))

        if price_df.empty:
            continue

        # psycopg2返回datetime.date，转为pd.Timestamp以便比较
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])

        # 计算Alpha158
        try:
            result_df = compute_all_alpha158(price_df, skip_slow=False)
        except Exception as e:
            print(f"    BATCH {batch_idx//stock_batch_size} FAILED: {e}")
            continue

        if result_df.empty:
            continue

        # 只保留当年数据（去掉lookback部分）
        result_df = result_df[result_df["trade_date"] >= pd.Timestamp(year_start)].copy()

        # 铁律29: NaN → 跳过, Inf → 跳过
        vals = result_df["value"]
        valid_mask = vals.notna() & np.isfinite(vals.fillna(0))
        result_df = result_df[valid_mask].copy()

        # Clip to NUMERIC(16,6) range: |value| < 10^10
        MAX_ABS = 9_999_999_999.0
        result_df["value"] = result_df["value"].clip(-MAX_ABS, MAX_ABS)

        # 构建写入rows — 转为Python原生类型(psycopg2不认numpy类型)
        codes = result_df["code"].tolist()
        dates = result_df["trade_date"].dt.date.tolist()
        fnames = result_df["factor_name"].tolist()
        values = [float(v) for v in result_df["value"].values]
        rows = list(zip(codes, dates, fnames, values, strict=False))

        # 写入DB
        written = write_factor_batch(conn, rows)
        stats["total_written"] += written
        stats["total_rows"] += len(result_df)
        stats["stocks_processed"] += len(batch_codes)
        stats["batches"] += 1

        elapsed = time.time() - t_batch
        print(f"    Batch {batch_idx//stock_batch_size + 1}/{(len(all_codes) + stock_batch_size - 1)//stock_batch_size}: "
              f"{len(batch_codes)} stocks, {written:,} rows written ({elapsed:.1f}s)")

        del price_df, result_df, rows
        gc.collect()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Phase 3A-1: Alpha158因子批量入库")
    parser.add_argument("--start", type=int, default=2014)
    parser.add_argument("--end", type=int, default=2026)
    parser.add_argument("--stock-batch", type=int, default=500, help="每批处理的股票数")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_CONN)
    t_total = time.time()

    all_names = get_alpha158_names()
    print("=" * 70)
    print(f"  Phase 3A-1: Alpha158因子批量入库 ({args.start}-{args.end})")
    print(f"  因子数量: {len(all_names)}")
    print(f"  股票批次: {args.stock_batch}")
    print("=" * 70)

    grand_total = 0

    for year in range(args.start, args.end + 1):
        t_year = time.time()
        print(f"\n{'='*40} {year} {'='*40}")

        stats = process_year(conn, year, stock_batch_size=args.stock_batch)
        grand_total += stats["total_written"]

        elapsed = time.time() - t_year
        print(f"  {year} 完成: {stats['total_written']:,} rows, "
              f"{stats['stocks_processed']} stocks, {elapsed:.1f}s")

    total_elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print("  Alpha158 全部完成")
    print(f"  总写入: {grand_total:,} rows")
    print(f"  总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print("=" * 70)

    # 验证: 检查因子覆盖率
    print("\n── 因子覆盖率验证 ──")
    cur = conn.cursor()
    cur.execute("""
        SELECT factor_name, COUNT(*) as cnt
        FROM factor_values
        WHERE factor_name IN %s
        GROUP BY factor_name
        ORDER BY cnt DESC
    """, (tuple(all_names),))

    covered = 0
    for row in cur.fetchall():
        covered += 1
        if covered <= 10 or covered > len(all_names) - 5:
            print(f"  {row[0]:>15s}: {row[1]:>12,} rows")
        elif covered == 11:
            print(f"  ... ({len(all_names) - 15} more factors) ...")

    print(f"\n  覆盖率: {covered}/{len(all_names)} factors in DB")

    # NaN检查（抽样5个因子）
    print("\n── NaN抽样检查 ──")
    sample_factors = ["QTLD60", "MIN10", "STD20", "CORR10", "VMA60"]
    for fname in sample_factors:
        cur.execute(
            "SELECT COUNT(*) FROM factor_values WHERE factor_name = %s AND raw_value = 'NaN'",
            (fname,),
        )
        nan_count = cur.fetchone()[0]
        status = "✅" if nan_count == 0 else f"❌ {nan_count} NaN rows"
        print(f"  {fname:>15s}: {status}")

    conn.close()


if __name__ == "__main__":
    main()
