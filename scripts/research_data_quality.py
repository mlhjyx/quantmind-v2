#!/usr/bin/env python3
"""数据质量巡检 + 交叉一致性 + 异常值检查。"""
import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn


def main():
    conn = _get_sync_conn()
    cur = conn.cursor()

    # === CROSS-TABLE STOCK COVERAGE ===
    print("=== CROSS-TABLE STOCK COVERAGE (2024-12-31) ===")
    queries = [
        ("klines_daily (vol>0)", "SELECT COUNT(DISTINCT code) FROM klines_daily WHERE trade_date = '2024-12-31' AND volume > 0"),
        ("daily_basic", "SELECT COUNT(DISTINCT code) FROM daily_basic WHERE trade_date = '2024-12-31'"),
        ("moneyflow_daily", "SELECT COUNT(DISTINCT code) FROM moneyflow_daily WHERE trade_date = '2024-12-31'"),
        ("factor_values", "SELECT COUNT(DISTINCT code) FROM factor_values WHERE trade_date = '2024-12-31'"),
    ]
    for label, q in queries:
        cur.execute(q)
        print(f"  {label:30s}: {cur.fetchone()[0]}")

    # moneyflow gap detail
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT code FROM klines_daily WHERE trade_date = '2024-12-31' AND volume > 0
            EXCEPT
            SELECT DISTINCT code FROM moneyflow_daily WHERE trade_date = '2024-12-31'
        ) t
    """)
    print(f"  klines - moneyflow gap:       {cur.fetchone()[0]} stocks missing moneyflow")

    conn.rollback()

    # === DUPLICATES ===
    print("\n=== DUPLICATE CHECK ===")
    for tbl, keys in [
        ("klines_daily", "code, trade_date"),
        ("daily_basic", "code, trade_date"),
        ("factor_values", "code, trade_date, factor_name"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM (SELECT {keys} FROM {tbl} GROUP BY {keys} HAVING COUNT(*) > 1) t")
        print(f"  {tbl:25s}: {cur.fetchone()[0]} duplicate groups")
    conn.rollback()

    # === ANOMALIES ===
    print("\n=== ANOMALY CHECK ===")
    checks = [
        ("PE_TTM extreme (|>9999|)", "SELECT COUNT(*) FROM daily_basic WHERE (pe_ttm < -9999 OR pe_ttm > 99999) AND trade_date >= '2021-01-01'"),
        ("PB negative", "SELECT COUNT(*) FROM daily_basic WHERE pb < 0 AND trade_date >= '2021-01-01'"),
        ("total_mv = 0", "SELECT COUNT(*) FROM daily_basic WHERE total_mv = 0 AND trade_date >= '2021-01-01'"),
        ("close <= 0", "SELECT COUNT(*) FROM klines_daily WHERE close <= 0 AND trade_date >= '2021-01-01'"),
        ("|zscore| > 10 (2025+)", "SELECT COUNT(*) FROM factor_values WHERE ABS(zscore) > 10 AND trade_date >= '2025-01-01'"),
        ("klines turnover NULL (2025+)", "SELECT COUNT(*) FROM klines_daily WHERE turnover_rate IS NULL AND trade_date >= '2025-01-01'"),
    ]
    for label, q in checks:
        try:
            cur.execute(q)
            print(f"  {label:35s}: {cur.fetchone()[0]}")
        except Exception as e:
            conn.rollback()
            print(f"  {label:35s}: ERROR {e}")
    conn.rollback()

    # === TIMELINESS ===
    print("\n=== DATA TIMELINESS ===")
    for tbl in ["klines_daily", "daily_basic", "moneyflow_daily", "index_daily", "factor_values"]:
        cur.execute(f"SELECT MAX(trade_date) FROM {tbl}")
        print(f"  {tbl:25s}: {cur.fetchone()[0]}")
    conn.rollback()

    # === INDEX_COMPONENTS (CSI300 history) ===
    cur.execute("SELECT COUNT(*) FROM index_components")
    print(f"\n  index_components rows: {cur.fetchone()[0]} (0 = no historical components)")
    conn.rollback()

    # === CLOSE CONSISTENCY klines vs daily_basic ===
    print("\n=== CLOSE PRICE CONSISTENCY (klines vs daily_basic) ===")
    cur.execute("""
        SELECT COUNT(*) FROM klines_daily k
        JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        WHERE k.trade_date = '2025-12-31'
        AND ABS(k.close - db.close) > 0.01
    """)
    print(f"  Mismatched close (2025-12-31): {cur.fetchone()[0]}")
    conn.rollback()

    # === UNUSED TABLES (0 rows) ===
    print("\n=== EMPTY TABLES (DDL created but no data) ===")
    cur.execute("""
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
        ORDER BY tablename
    """)
    all_tables = [r[0] for r in cur.fetchall()]
    empty = []
    for t in all_tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            if cur.fetchone()[0] == 0:
                empty.append(t)
        except Exception:
            conn.rollback()
    print(f"  {len(empty)} empty tables: {', '.join(empty)}")

    conn.close()

if __name__ == "__main__":
    main()
