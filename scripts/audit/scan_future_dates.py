#!/usr/bin/env python3
"""扫全 DB trade_date 未来日期脏数据 (Session 26 LL-068).

背景: test_pt_audit fixture 用 date(2099,4,30) 泄漏到生产 klines_daily,
    被 data_quality_check MAX(trade_date) 掩盖 4-20+ 滞后 2 天. 本脚本扫描
    所有含 trade_date 列的表, 报告 > today+7d 的 row, **不自动 DELETE** —
    由 user 人工审核 (可能是 fixture sentinel 也可能是真实未来日期合约).

用法:
    python scripts/audit/scan_future_dates.py              # 扫全表
    python scripts/audit/scan_future_dates.py --days 7     # cutoff today+7d (默认)
    python scripts/audit/scan_future_dates.py --tables klines_daily,daily_basic
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402

# 已知含 trade_date 列的业务表 (从 contracts.py + DDL 抽取).
# 排除 trading_calendar — 该表 by design 存年内 pre-populated 未来交易日 (合法 future dates,
# 非脏数据). 若需扫 calendar 用 --tables trading_calendar 手工指定.
DEFAULT_TABLES = (
    "klines_daily",
    "daily_basic",
    "moneyflow_daily",
    "factor_ic_history",
    "stock_status_daily",
    "trade_log",
    "position_snapshot",
    "performance_series",
    "index_daily",
    "factor_values",
)


def scan_table(cur, table: str, cutoff: date) -> list[tuple[date, int]]:
    """返 [(trade_date, count), ...] for trade_date > cutoff."""
    cur.execute(
        f"SELECT trade_date, COUNT(*) FROM {table} WHERE trade_date > %s "  # noqa: S608
        "GROUP BY trade_date ORDER BY trade_date",
        (cutoff,),
    )
    return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="扫 DB 未来日期脏数据")
    parser.add_argument("--days", type=int, default=7, help="cutoff = today + N 天 (default 7)")
    parser.add_argument(
        "--tables",
        type=str,
        default=",".join(DEFAULT_TABLES),
        help=f"逗号分隔表名 (default: {','.join(DEFAULT_TABLES)})",
    )
    args = parser.parse_args()

    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    cutoff = date.today() + timedelta(days=args.days)

    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(url, connect_timeout=30, options="-c statement_timeout=60000")
    cur = conn.cursor()

    print(f"扫描 {len(tables)} 张表, cutoff = today+{args.days}d = {cutoff}")
    print("=" * 70)

    any_dirty = False
    try:
        for tbl in tables:
            # 表存在性检查 (部分可选表)
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s)",
                (tbl,),
            )
            if not cur.fetchone()[0]:
                print(f"  [SKIP] {tbl}: 表不存在")
                continue

            # 列存在性检查
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "AND column_name = 'trade_date')",
                (tbl,),
            )
            if not cur.fetchone()[0]:
                print(f"  [SKIP] {tbl}: 无 trade_date 列")
                continue

            rows = scan_table(cur, tbl, cutoff)
            if not rows:
                print(f"  ✓ {tbl}: 0 future rows")
                continue

            any_dirty = True
            total = sum(n for _, n in rows)
            print(f"  ⚠ {tbl}: {total} future rows")
            for d, n in rows:
                print(f"      {d}: {n} rows")
    finally:
        cur.close()
        conn.close()

    print("=" * 70)
    if any_dirty:
        print("发现未来日期脏数据. 人工审核后执行 DELETE (非自动, 防真实未来合约误删).")
        return 1
    print("全表洁净.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
