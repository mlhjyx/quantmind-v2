#!/usr/bin/env python3
"""因子计算脚本 — 批量计算并写入factor_values表。

用法:
    # 计算单日（6核心因子）
    python scripts/calc_factors.py --date 2025-03-14

    # 按年批量计算（推荐，利用batch模式高效加载）
    python scripts/calc_factors.py --start 2024-01-02 --end 2024-12-31

    # 使用完整18因子集
    python scripts/calc_factors.py --start 2024-01-02 --end 2024-12-31 --factor-set full

    # dry-run模式（计算但不写入）
    python scripts/calc_factors.py --date 2025-03-14 --dry-run

    # 按半年分片（16GB内存限制，避免OOM）
    python scripts/calc_factors.py --start 2020-01-02 --end 2026-03-19 --chunk-months 6
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn
from engines.factor_engine import (
    compute_batch_factors,
    compute_daily_factors,
    save_daily_factors,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def split_date_range(
    start: date, end: date, chunk_months: int
) -> list[tuple[date, date]]:
    """将日期范围按月分片，避免内存溢出。"""
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(
            date(
                current.year + (current.month + chunk_months - 1) // 12,
                (current.month + chunk_months - 1) % 12 + 1,
                1,
            ),
            end,
        )
        # 如果chunk_end超过end，截断
        if chunk_end > end:
            chunk_end = end
        chunks.append((current, chunk_end))
        # 下一个chunk从chunk_end的下一天开始
        if chunk_end >= end:
            break
        next_month = chunk_end.month % 12 + 1
        next_year = chunk_end.year + (1 if next_month == 1 else 0)
        current = date(next_year, next_month, 1)
    return chunks


def main():
    parser = argparse.ArgumentParser(description="QuantMind V2 因子计算")
    parser.add_argument("--date", type=str, help="单日计算 (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="开始日期")
    parser.add_argument("--end", type=str, help="结束日期")
    parser.add_argument(
        "--factor-set",
        choices=["core", "full", "ml", "lgbm", "all"],
        default="core",
        help="因子集: core(5)/full(16)/ml(12)/lgbm(28)/all(含deprecated)",
    )
    parser.add_argument("--dry-run", action="store_true", help="只计算不写入")
    parser.add_argument(
        "--chunk-months",
        type=int,
        default=6,
        help="分片月数(默认6，避免OOM)",
    )
    parser.add_argument(
        "--factors",
        type=str,
        nargs="+",
        default=None,
        help="只计算指定因子(空格分隔)，如 --factors price_level_factor dv_ttm",
    )
    args = parser.parse_args()

    if args.date:
        start = end = datetime.strptime(args.date, "%Y-%m-%d").date()
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        parser.error("请指定 --date 或 --start/--end")

    conn = _get_sync_conn()

    # 单日模式用原始逐日函数
    if start == end:
        logger.info(f"单日模式: {start}, 因子集={args.factor_set}")
        result_df = compute_daily_factors(start, factor_set=args.factor_set, conn=conn)
        if not result_df.empty and not args.dry_run:
            save_daily_factors(start, result_df, conn=conn)
        conn.close()
        return

    # 批量模式: 按chunk分片处理
    chunks = split_date_range(start, end, args.chunk_months)
    factor_filter = args.factors
    logger.info(
        f"批量模式: {start} → {end}, {len(chunks)}个分片 (每片{args.chunk_months}月), "
        f"因子集={args.factor_set}"
        + (f", 指定因子={factor_filter}" if factor_filter else "")
    )

    total_rows = 0
    total_dates = 0
    t0 = time.time()

    for ci, (cs, ce) in enumerate(chunks):
        logger.info(f"=== 分片 {ci+1}/{len(chunks)}: {cs} → {ce} ===")
        stats = compute_batch_factors(
            cs, ce,
            factor_set=args.factor_set,
            conn=conn,
            write=not args.dry_run,
            factor_names=factor_filter,
        )
        total_rows += stats["total_rows"]
        total_dates += stats["dates"]

    elapsed = time.time() - t0
    logger.info(
        f"全部完成: {total_dates}天, {total_rows}行, "
        f"耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)"
    )

    conn.close()


if __name__ == "__main__":
    main()
