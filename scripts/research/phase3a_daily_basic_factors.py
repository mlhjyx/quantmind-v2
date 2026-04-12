#!/usr/bin/env python3
"""Phase 3A-2: daily_basic衍生因子批量入库。

从daily_basic表读取估值/换手/结构字段，计算衍生因子写入factor_values。
只写raw_value，中性化在后续步骤统一执行。

新因子:
  sp_ttm       = 1/ps_ttm      (销售收益率，越高越便宜)
  ep_ttm       = 1/pe_ttm      (盈利收益率，修复broken ep_ratio)
  volume_ratio = direct         (量比，今日量/5日均量)
  turnover_f   = turnover_rate_f (自由流通换手率)
  float_pct    = free_share/total_share (自由流通占比)

用法:
  python scripts/research/phase3a_daily_basic_factors.py
  python scripts/research/phase3a_daily_basic_factors.py --start 2020 --end 2026
"""

import argparse
import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))


DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"
BATCH_SIZE = 5000


# ── 因子定义 ──────────────────────────────────────────────

FACTOR_DEFS = {
    "sp_ttm": {
        "desc": "Sales yield TTM (1/PS_TTM), higher=cheaper",
        "compute": lambda df: 1.0 / df["ps_ttm"].replace(0, np.nan),
        "direction": 1,
    },
    "ep_ttm": {
        "desc": "Earnings yield TTM (1/PE_TTM), higher=cheaper",
        "compute": lambda df: 1.0 / df["pe_ttm"].replace(0, np.nan),
        "direction": 1,
    },
    "volume_ratio_daily": {
        "desc": "Volume ratio from Tushare (today vol / 5d avg)",
        "compute": lambda df: df["volume_ratio"],
        "direction": None,  # 待IC评估确定
    },
    "turnover_f": {
        "desc": "Free-float adjusted turnover rate",
        "compute": lambda df: df["turnover_rate_f"],
        "direction": -1,  # 低换手率可能类似turnover_mean_20
    },
    "float_pct": {
        "desc": "Free float percentage (free_share/total_share)",
        "compute": lambda df: df["free_share"] / df["total_share"].replace(0, np.nan),
        "direction": None,
    },
}


def load_daily_basic_year(conn, year: int) -> pd.DataFrame:
    """加载指定年份的daily_basic数据。"""
    sql = """
        SELECT code, trade_date, pe_ttm, ps_ttm, pb, volume_ratio,
               turnover_rate_f, free_share, total_share, total_mv
        FROM daily_basic
        WHERE EXTRACT(YEAR FROM trade_date) = %s
        ORDER BY trade_date, code
    """
    df = pd.read_sql(sql, conn, params=(year,))
    print(f"  Loaded daily_basic {year}: {len(df):,} rows")
    return df


def compute_factors(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """计算所有因子，返回 {factor_name: DataFrame(code, trade_date, raw_value)}。"""
    results = {}

    for fname, fdef in FACTOR_DEFS.items():
        try:
            values = fdef["compute"](df)
            fdf = pd.DataFrame({
                "code": df["code"],
                "trade_date": df["trade_date"],
                "raw_value": values,
            })
            # 铁律29: NaN → None (在写入时处理)
            # 移除完全无效的行
            valid_mask = fdf["raw_value"].notna() & np.isfinite(fdf["raw_value"])
            fdf = fdf[valid_mask].copy()
            results[fname] = fdf
            print(f"    {fname}: {len(fdf):,} valid rows ({len(fdf)/len(df)*100:.1f}%)")
        except Exception as e:
            print(f"    {fname}: FAILED - {e}")

    return results


def write_factor_batch(conn, factor_name: str, df: pd.DataFrame) -> int:
    """写入factor_values表，返回写入行数。

    使用ON CONFLICT DO UPDATE更新raw_value。
    """
    if df.empty:
        return 0

    cur = conn.cursor()
    total_written = 0

    # 分批写入
    for i in range(0, len(df), BATCH_SIZE):
        batch = df.iloc[i:i + BATCH_SIZE]
        values = []
        for _, row in batch.iterrows():
            rv = row["raw_value"]
            # 铁律29: 确保无NaN
            if rv is None or (isinstance(rv, float) and (np.isnan(rv) or np.isinf(rv))):
                continue
            values.append((
                row["code"],
                row["trade_date"],
                factor_name,
                float(rv),
            ))

        if values:
            execute_values(
                cur,
                """INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
                   VALUES %s
                   ON CONFLICT (code, trade_date, factor_name)
                   DO UPDATE SET raw_value = EXCLUDED.raw_value""",
                values,
                page_size=BATCH_SIZE,
            )
            total_written += len(values)

    conn.commit()
    return total_written


def main():
    parser = argparse.ArgumentParser(description="Phase 3A-2: daily_basic因子入库")
    parser.add_argument("--start", type=int, default=2014)
    parser.add_argument("--end", type=int, default=2026)
    args = parser.parse_args()

    conn = psycopg2.connect(DB_CONN)
    t_total = time.time()

    print("=" * 70)
    print(f"  Phase 3A-2: daily_basic因子入库 ({args.start}-{args.end})")
    print(f"  因子: {', '.join(FACTOR_DEFS.keys())}")
    print("=" * 70)

    summary = {}

    for year in range(args.start, args.end + 1):
        t_year = time.time()
        print(f"\n── {year} ──")

        df = load_daily_basic_year(conn, year)
        if df.empty:
            print(f"  {year}: 无数据，跳过")
            continue

        factors = compute_factors(df)

        for fname, fdf in factors.items():
            written = write_factor_batch(conn, fname, fdf)
            if fname not in summary:
                summary[fname] = {"total_written": 0, "total_valid": 0}
            summary[fname]["total_written"] += written
            summary[fname]["total_valid"] += len(fdf)

        del df, factors
        gc.collect()

        elapsed = time.time() - t_year
        print(f"  {year} 完成: {elapsed:.1f}s")

    # 汇总
    total_elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print(f"  完成 ({total_elapsed:.1f}s)")
    print("=" * 70)

    for fname, stats in summary.items():
        desc = FACTOR_DEFS[fname]["desc"]
        print(f"  {fname:>20s}: {stats['total_written']:>12,} rows written | {desc}")

    print(f"\n  总耗时: {total_elapsed:.1f}s")

    # 验证: 抽查最新日期
    print("\n── 验证 ──")
    cur = conn.cursor()
    for fname in FACTOR_DEFS:
        cur.execute(
            """SELECT COUNT(*), AVG(raw_value), MIN(raw_value), MAX(raw_value)
               FROM factor_values
               WHERE factor_name = %s AND trade_date = '2026-04-10'""",
            (fname,),
        )
        r = cur.fetchone()
        if r and r[0]:
            print(f"  {fname:>20s} @ 2026-04-10: n={r[0]:,}, avg={float(r[1]):.4f}, "
                  f"min={float(r[2]):.4f}, max={float(r[3]):.4f}")
        else:
            print(f"  {fname:>20s} @ 2026-04-10: NO DATA")

    # NaN检查
    print("\n── NaN检查 ──")
    for fname in FACTOR_DEFS:
        cur.execute(
            """SELECT COUNT(*) FROM factor_values
               WHERE factor_name = %s AND raw_value = 'NaN'""",
            (fname,),
        )
        nan_count = cur.fetchone()[0]
        status = "✅" if nan_count == 0 else f"❌ {nan_count} NaN rows"
        print(f"  {fname:>20s}: {status}")

    conn.close()


if __name__ == "__main__":
    main()
