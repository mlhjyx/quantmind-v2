#!/usr/bin/env python3
"""全量数据拉取脚本 — 按日期策略拉取2020-2025全部数据。

使用方式：
    python scripts/pull_full_data.py              # 全量拉取（自动断点续传）
    python scripts/pull_full_data.py --start 20240101  # 指定起始日期
    python scripts/pull_full_data.py --table klines    # 只拉klines_daily
    python scripts/pull_full_data.py --table basic     # 只拉daily_basic
    python scripts/pull_full_data.py --table index     # 只拉index_daily
    python scripts/pull_full_data.py --dry-run         # 只看计划，不实际拉取

数据拉取策略：
    1. 从trading_calendar获取交易日列表
    2. 检查数据库中最新已加载日期（断点续传）
    3. 按日期逐日拉取：daily + adj_factor + stk_limit → klines_daily
    4. 按日期逐日拉取：daily_basic → daily_basic
    5. 沪深300/中证500/中证1000指数日线 → index_daily

预计耗时：全量5年 ~20分钟（klines）+ ~10分钟（daily_basic）
"""

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))

from app.data_fetcher.data_loader import (
    get_last_loaded_date,
    get_sync_conn,
    upsert_daily_basic,
    upsert_index_daily,
    upsert_klines_daily,
)
from app.data_fetcher.tushare_fetcher import TushareFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# 连续失败超过此数量则终止（可能是持久性故障）
MAX_CONSECUTIVE_FAILURES = 5


def _log_progress(
    label: str, i: int, total: int, total_rows: int, start_time: float
) -> None:
    """打印进度日志。"""
    elapsed = time.time() - start_time
    if elapsed > 0:
        rate = (i + 1) / elapsed * 60
        eta = (total - i - 1) / rate if rate > 0 else 0
    else:
        rate = 0.0
        eta = 0.0
    logger.info(
        f'{label} progress: {i+1}/{total} dates, '
        f'{total_rows} rows, {rate:.1f} dates/min, '
        f'ETA {eta:.1f} min'
    )


def pull_klines(fetcher: TushareFetcher, trading_dates: list[str]) -> None:
    """拉取klines_daily（daily + adj_factor + stk_limit合并）。"""
    last_date = get_last_loaded_date('klines_daily')
    if last_date:
        last_str = last_date.strftime('%Y%m%d')
        remaining = [d for d in trading_dates if d > last_str]
        logger.info(
            f'klines_daily: last loaded {last_str}, '
            f'{len(remaining)}/{len(trading_dates)} dates remaining'
        )
    else:
        remaining = trading_dates
        logger.info(f'klines_daily: fresh start, {len(remaining)} dates to pull')

    total = len(remaining)
    if total == 0:
        logger.info('klines_daily: nothing to pull')
        return

    total_rows = 0
    failed_dates: list[str] = []
    consecutive_failures = 0
    start_time = time.time()
    conn = get_sync_conn()

    try:
        for i, td in enumerate(remaining):
            try:
                df = fetcher.merge_daily_data(td)
                if len(df) > 0:
                    rows = upsert_klines_daily(df, conn)
                    total_rows += rows
                consecutive_failures = 0

                if (i + 1) % 50 == 0 or i == total - 1:
                    _log_progress('klines', i, total, total_rows, start_time)
            except Exception as e:
                logger.error(f'Failed on date {td}: {e}')
                failed_dates.append(td)
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        f'{MAX_CONSECUTIVE_FAILURES} consecutive failures, '
                        f'aborting. Last error: {e}'
                    )
                    break
    finally:
        conn.close()

    if failed_dates:
        logger.warning(
            f'ATTENTION: {len(failed_dates)} dates failed: {failed_dates}. '
            f'Re-run to retry.'
        )

    logger.info(
        f'klines_daily DONE: {total_rows} rows in '
        f'{time.time()-start_time:.1f}s'
    )


def pull_daily_basic(
    fetcher: TushareFetcher, trading_dates: list[str]
) -> None:
    """拉取daily_basic。"""
    last_date = get_last_loaded_date('daily_basic')
    if last_date:
        last_str = last_date.strftime('%Y%m%d')
        remaining = [d for d in trading_dates if d > last_str]
        logger.info(
            f'daily_basic: last loaded {last_str}, '
            f'{len(remaining)}/{len(trading_dates)} dates remaining'
        )
    else:
        remaining = trading_dates
        logger.info(f'daily_basic: fresh start, {len(remaining)} dates to pull')

    total = len(remaining)
    if total == 0:
        logger.info('daily_basic: nothing to pull')
        return

    total_rows = 0
    failed_dates: list[str] = []
    consecutive_failures = 0
    start_time = time.time()
    conn = get_sync_conn()

    try:
        for i, td in enumerate(remaining):
            try:
                df = fetcher.fetch_daily_basic_by_date(td)
                if len(df) > 0:
                    rows = upsert_daily_basic(df, conn)
                    total_rows += rows
                consecutive_failures = 0

                if (i + 1) % 50 == 0 or i == total - 1:
                    _log_progress('daily_basic', i, total, total_rows, start_time)
            except Exception as e:
                logger.error(f'daily_basic failed on {td}: {e}')
                failed_dates.append(td)
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        f'{MAX_CONSECUTIVE_FAILURES} consecutive failures, aborting.'
                    )
                    break
    finally:
        conn.close()

    if failed_dates:
        logger.warning(
            f'ATTENTION: {len(failed_dates)} dates failed: {failed_dates}. '
            f'Re-run to retry.'
        )

    logger.info(
        f'daily_basic DONE: {total_rows} rows in '
        f'{time.time()-start_time:.1f}s'
    )


def pull_index(fetcher: TushareFetcher, start_date: str, end_date: str) -> None:
    """拉取沪深300/中证500/中证1000指数日线。"""
    indices = [
        ('000300.SH', '沪深300'),
        ('000905.SH', '中证500'),
        ('000852.SH', '中证1000'),
    ]
    logger.info(f'Pulling {len(indices)} index daily series...')
    for index_code, name in indices:
        df = fetcher.fetch_index_daily(index_code, start_date, end_date)
        if len(df) > 0:
            rows = upsert_index_daily(df)
            logger.info(f'index_daily {name}({index_code}): {rows} rows')
        else:
            logger.warning(f'No data for index {name}({index_code})')


def main() -> None:
    parser = argparse.ArgumentParser(description='全量数据拉取')
    parser.add_argument('--start', default='20200101', help='起始日期 (YYYYMMDD)')
    parser.add_argument('--end', default=date.today().strftime('%Y%m%d'),
                        help='结束日期 (YYYYMMDD)，默认为今天')
    parser.add_argument(
        '--table', choices=['klines', 'basic', 'index', 'all'],
        default='all', help='拉取哪张表'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='只打印拉取计划，不实际调用API'
    )
    args = parser.parse_args()

    fetcher = TushareFetcher()

    # 获取交易日列表
    logger.info(f'Fetching trading dates {args.start} ~ {args.end}...')
    trading_dates = fetcher.get_trading_dates(args.start, args.end)
    logger.info(f'Total trading dates: {len(trading_dates)}')

    if args.dry_run:
        logger.info(
            f'[DRY RUN] Would pull {len(trading_dates)} dates '
            f'from {trading_dates[0]} to {trading_dates[-1]}'
        )
        logger.info(f'[DRY RUN] Tables: {args.table}')
        return

    if args.table in ('klines', 'all'):
        pull_klines(fetcher, trading_dates)

    if args.table in ('basic', 'all'):
        pull_daily_basic(fetcher, trading_dates)

    if args.table in ('index', 'all'):
        pull_index(fetcher, args.start, args.end)

    logger.info(f'All done! Total API calls: {fetcher._call_count}')


if __name__ == '__main__':
    main()
