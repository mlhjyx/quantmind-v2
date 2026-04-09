#!/usr/bin/env python3
"""构建回测数据Parquet缓存 — 从DB导出到cache/backtest/。

用法:
    python scripts/build_backtest_cache.py                           # 默认2014~今天
    python scripts/build_backtest_cache.py --start 2021-01-01        # 指定起始
    python scripts/build_backtest_cache.py --start 2014-01-01 --end 2025-12-31
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from data.parquet_cache import BacktestDataCache  # noqa: E402

from app.data_fetcher.data_loader import get_sync_conn  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="构建回测Parquet缓存")
    parser.add_argument("--start", default="2014-01-01", help="起始日期")
    parser.add_argument("--end", default=str(date.today()), help="结束日期")
    args = parser.parse_args()

    print(f"Building backtest cache: {args.start} ~ {args.end}")
    t0 = time.time()

    conn = get_sync_conn()
    cache = BacktestDataCache()
    stats = cache.build(args.start, args.end, conn)
    conn.close()

    total_price = sum(s["price_rows"] for s in stats.values())
    total_factor = sum(s["factor_rows"] for s in stats.values())
    elapsed = time.time() - t0

    print(f"\nDone: {len(stats)} years, {total_price:,} price rows, {total_factor:,} factor rows")
    print(f"Total time: {elapsed:.0f}s")

    # Print per-year summary
    for year, s in sorted(stats.items()):
        yr_dir = Path("cache/backtest") / str(year)
        sizes = {}
        for f in ["price_data.parquet", "factor_data.parquet", "benchmark.parquet"]:
            p = yr_dir / f
            if p.exists():
                sizes[f.split(".")[0]] = p.stat().st_size / 1024 / 1024
        print(
            f"  {year}: price={s['price_rows']:>8,} ({sizes.get('price_data',0):.1f}MB) "
            f"factor={s['factor_rows']:>10,} ({sizes.get('factor_data',0):.1f}MB) "
            f"({s['elapsed_sec']:.1f}s)"
        )


if __name__ == "__main__":
    main()
