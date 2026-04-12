#!/usr/bin/env python3
"""Phase 3A-4: 基本面因子 + 盈余因子批量入库 (向量化版本)。

数据源:
  1. earnings_announcements → sue_pead (盈余惊喜, PEAD event因子)
  2. fina_indicator → roe_dt_q, roa_q, gross_margin_q, net_margin_q, profit_growth_q, eps_growth_q, leverage_q

规则:
  - 使用ann_date（公告日）确保无前瞻偏差
  - merge_asof向量化forward-fill（比Python循环快100x）
  - NaN → None（铁律29）

用法:
  python scripts/research/phase3a_fundamental_factors.py
"""

import gc
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"


def write_copy_upsert(conn, df: pd.DataFrame, factor_name: str) -> int:
    """COPY+UPSERT批量写入factor_values。df需要有code, trade_date, value列。"""
    if df.empty:
        return 0

    # 铁律29: 去除NaN和Inf
    vals = df["value"]
    valid = vals.notna() & np.isfinite(vals.fillna(0))
    df = df[valid]
    if df.empty:
        return 0

    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS _funda_staging")
    cur.execute("""CREATE TEMP TABLE _funda_staging (
        code VARCHAR, trade_date DATE, factor_name VARCHAR, raw_value DOUBLE PRECISION
    )""")

    buf = io.StringIO()
    for _, row in df.iterrows():
        buf.write(f"{row['code']}\t{row['trade_date']}\t{factor_name}\t{float(row['value'])}\n")
    buf.seek(0)
    cur.copy_from(buf, "_funda_staging", columns=("code", "trade_date", "factor_name", "raw_value"))

    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _funda_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)
    total = len(df)
    conn.commit()
    return total


def write_copy_upsert_fast(conn, codes, dates, factor_name: str, values) -> int:
    """COPY+UPSERT using pre-built lists (avoids iterrows)."""
    if len(codes) == 0:
        return 0

    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS _funda_staging")
    cur.execute("""CREATE TEMP TABLE _funda_staging (
        code VARCHAR, trade_date DATE, factor_name VARCHAR, raw_value DOUBLE PRECISION
    )""")

    buf = io.StringIO()
    for c, d, v in zip(codes, dates, values, strict=False):
        buf.write(f"{c}\t{d}\t{factor_name}\t{v}\n")
    buf.seek(0)
    cur.copy_from(buf, "_funda_staging", columns=("code", "trade_date", "factor_name", "raw_value"))

    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _funda_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)
    total = len(codes)
    conn.commit()
    return total


# ══════════════════════════════════════════════��═════════════
# Part 1: SUE/PEAD — vectorized merge_asof
# ════════════════════════════════════════════════════════════

def load_stock_dates_for_codes(conn, codes: list[str]) -> pd.DataFrame:
    """只加载指定股票的交易日（比加载全表轻10x）。"""
    if not codes:
        return pd.DataFrame(columns=["code", "trade_date"])
    # 分批IN查询避免太长SQL
    all_parts = []
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        placeholders = ",".join(["%s"] * len(batch))
        df = pd.read_sql(
            f"SELECT code, trade_date FROM klines_daily WHERE code IN ({placeholders}) AND volume > 0 ORDER BY code, trade_date",
            conn, params=tuple(batch),
        )
        all_parts.append(df)
    result = pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame(columns=["code", "trade_date"])
    result["trade_date"] = pd.to_datetime(result["trade_date"])
    return result


def compute_sue_pead(conn) -> int:
    """将earnings_announcements的eps_surprise_pct向量化映射到交易日。"""
    print("\n── SUE/PEAD因子 ──")

    # 读取盈余公告
    ea = pd.read_sql("""
        SELECT ts_code AS code, trade_date, eps_surprise_pct AS value
        FROM earnings_announcements
        WHERE eps_surprise_pct IS NOT NULL
        ORDER BY code, trade_date
    """, conn)
    ea["trade_date"] = pd.to_datetime(ea["trade_date"])
    ea["value"] = ea["value"].astype(float)
    ea = ea[ea["value"].notna() & np.isfinite(ea["value"])].copy()
    print(f"  Loaded {len(ea):,} valid earnings announcements")

    ea = ea.sort_values(["code", "trade_date"]).drop_duplicates(["code", "trade_date"], keep="last")

    # 只加载有盈余公告的股票的交易日
    ea_codes = ea["code"].unique().tolist()
    print(f"  Loading trade dates for {len(ea_codes)} stocks with earnings...")
    stock_dates = load_stock_dates_for_codes(conn, ea_codes)
    print(f"  Stock-date pairs: {len(stock_dates):,}")

    # 按code做merge_asof
    result_parts = []
    processed = 0
    for code, sdf in stock_dates.groupby("code"):
        code_ea = ea[ea["code"] == code]
        if code_ea.empty:
            continue

        merged = pd.merge_asof(
            sdf[["trade_date"]].sort_values("trade_date"),
            code_ea[["trade_date", "value"]].sort_values("trade_date"),
            on="trade_date",
            direction="backward",
            tolerance=pd.Timedelta(days=90),
        )
        merged = merged.dropna(subset=["value"])
        if not merged.empty:
            merged["code"] = code
            result_parts.append(merged)
        processed += 1
        if processed % 1000 == 0:
            print(f"    ... {processed}/{len(ea_codes)} stocks")

    if not result_parts:
        print("  sue_pead: NO DATA")
        return 0

    result = pd.concat(result_parts, ignore_index=True)
    print(f"  sue_pead: {len(result):,} rows")

    codes = result["code"].tolist()
    dates = [d.date() if hasattr(d, "date") else d for d in result["trade_date"]]
    values = [float(v) for v in result["value"].values]
    written = write_copy_upsert_fast(conn, codes, dates, "sue_pead", values)
    print(f"  sue_pead: {written:,} rows written")

    del result, result_parts, stock_dates
    gc.collect()
    return written


# ════════════════════════════════════════════════════════════
# Part 2: Quarterly fundamentals — vectorized merge_asof
# ════════════════════════════════════════════════════════════

FINA_FACTORS = {
    "roe_dt_q": {"col": "roe_dt", "desc": "ROE diluted (quarterly)"},
    "roa_q": {"col": "roa", "desc": "Return on assets (quarterly)"},
    "gross_margin_q": {"col": "grossprofit_margin", "desc": "Gross profit margin"},
    "net_margin_q": {"col": "netprofit_margin", "desc": "Net profit margin"},
    "profit_growth_q": {"col": "dt_netprofit_yoy", "desc": "Net profit YoY growth"},
    "eps_growth_q": {"col": "basic_eps_yoy", "desc": "EPS YoY growth"},
    "leverage_q": {"col": "debt_to_assets", "desc": "Debt to assets ratio"},
}


def compute_fina_factors(conn) -> int:
    """将fina_indicator季频因子向量化映射到交易日(point-in-time)。"""
    print("\n── 基本面因子 (fina_indicator) ──")

    cols = list(set(f["col"] for f in FINA_FACTORS.values()))
    cols_str = ", ".join(cols)
    fina = pd.read_sql(f"""
        SELECT code, ann_date, end_date, {cols_str}
        FROM fina_indicator
        WHERE ann_date IS NOT NULL
        ORDER BY code, ann_date, end_date
    """, conn)
    fina["ann_date"] = pd.to_datetime(fina["ann_date"])
    fina = fina.sort_values(["code", "ann_date", "end_date"]).drop_duplicates(
        ["code", "ann_date"], keep="last"
    )
    print(f"  Loaded {len(fina):,} fina_indicator records (deduped)")

    # 只加载有财报数据的股票的交易日
    fina_codes = fina["code"].unique().tolist()
    print(f"  Loading trade dates for {len(fina_codes)} stocks with fina data...")
    stock_dates = load_stock_dates_for_codes(conn, fina_codes)
    print(f"  Stock-date pairs: {len(stock_dates):,}")

    total_written = 0

    for fname, fdef in FINA_FACTORS.items():
        t0 = time.time()
        col = fdef["col"]

        fina_sub = fina[["code", "ann_date", col]].copy()
        fina_sub = fina_sub.rename(columns={"ann_date": "trade_date", col: "value"})
        fina_sub["value"] = fina_sub["value"].astype(float)
        fina_sub = fina_sub[fina_sub["value"].notna() & np.isfinite(fina_sub["value"])]
        fina_sub = fina_sub.sort_values(["code", "trade_date"])

        result_parts = []
        processed = 0
        for code, sdf in stock_dates.groupby("code"):
            code_fina = fina_sub[fina_sub["code"] == code]
            if code_fina.empty:
                continue

            merged = pd.merge_asof(
                sdf[["trade_date"]].sort_values("trade_date"),
                code_fina[["trade_date", "value"]].sort_values("trade_date"),
                on="trade_date",
                direction="backward",
                tolerance=pd.Timedelta(days=120),
            )
            merged = merged.dropna(subset=["value"])
            if not merged.empty:
                merged["code"] = code
                result_parts.append(merged)
            processed += 1

        if not result_parts:
            print(f"  {fname:>20s}: NO DATA")
            continue

        result = pd.concat(result_parts, ignore_index=True)

        codes = result["code"].tolist()
        dates = [d.date() if hasattr(d, "date") else d for d in result["trade_date"]]
        values = [float(v) for v in result["value"].values]

        written = write_copy_upsert_fast(conn, codes, dates, fname, values)
        total_written += written
        elapsed = time.time() - t0
        print(f"  {fname:>20s}: {written:>10,} rows ({elapsed:.1f}s)")

        del result_parts, result, codes, dates, values
        gc.collect()

    del stock_dates
    gc.collect()
    return total_written


def main():
    conn = psycopg2.connect(DB_CONN)
    t_total = time.time()

    print("=" * 70)
    print("  Phase 3A-4: 基本面 + 盈余因子入库 (向量化版本)")
    print("=" * 70)

    # Part 1: SUE/PEAD
    sue_written = compute_sue_pead(conn)

    # Part 2: Quarterly fundamentals
    fina_written = compute_fina_factors(conn)

    total_elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print(f"  完成: sue={sue_written:,}, fina={fina_written:,}")
    print(f"  总耗时: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print("=" * 70)

    # 验证
    print("\n── 验证 ──")
    cur = conn.cursor()
    all_factors = ["sue_pead"] + list(FINA_FACTORS.keys())
    for fname in all_factors:
        cur.execute("""SELECT COUNT(*), MIN(trade_date), MAX(trade_date), AVG(raw_value::float)
                       FROM factor_values WHERE factor_name = %s""", (fname,))
        r = cur.fetchone()
        if r and r[0]:
            print(f"  {fname:>20s}: {r[0]:>10,} rows | {r[1]} ~ {r[2]} | avg={float(r[3]):.4f}")
        else:
            print(f"  {fname:>20s}: NO DATA")

    # NaN check
    print("\n── NaN检查 ──")
    for fname in all_factors:
        cur.execute("SELECT COUNT(*) FROM factor_values WHERE factor_name = %s AND raw_value = 'NaN'",
                    (fname,))
        nan_count = cur.fetchone()[0]
        status = "✅" if nan_count == 0 else f"❌ {nan_count} NaN rows"
        print(f"  {fname:>20s}: {status}")

    conn.close()


if __name__ == "__main__":
    main()
