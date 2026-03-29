#!/usr/bin/env python3
"""刷新symbols表 — 确保包含全部历史股票（含退市+暂停）。

使用: python scripts/refresh_symbols.py
"""

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))

from app.data_fetcher.data_loader import get_sync_conn
from app.data_fetcher.tushare_fetcher import TushareFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# 板块→涨跌停幅度映射
BOARD_MAP = {
    'SSE': {'prefix': ['6'], 'board': 'main', 'limit': 0.10},
    'SZSE_MAIN': {'prefix': ['0'], 'board': 'main', 'limit': 0.10},
    'SZSE_GEM': {'prefix': ['3'], 'board': 'gem', 'limit': 0.20},
    'SSE_STAR': {'prefix': ['688'], 'board': 'star', 'limit': 0.20},
    'BSE': {'prefix': ['8', '4'], 'board': 'bse', 'limit': 0.30},
}


def _detect_board(ts_code: str, name: str) -> tuple[str, float]:
    """根据代码和名称判断板块和涨跌停幅度。"""
    code = ts_code.split('.')[0]
    # ST股5%
    is_st = 'ST' in name.upper()

    if code.startswith('688'):
        board = 'star'
        limit = 0.20
    elif code.startswith('3'):
        board = 'gem'
        limit = 0.20
    elif code.startswith(('8', '4')) and ts_code.endswith('.BJ'):
        board = 'bse'
        limit = 0.30
    else:
        board = 'main'
        limit = 0.10

    if is_st:
        limit = 0.05

    return board, limit


def main() -> None:
    fetcher = TushareFetcher()

    # 拉取全部股票：上市+退市+暂停
    dfs = []
    for status in ['L', 'D', 'P']:
        df = fetcher._api_call_with_retry(
            'stock_basic', exchange='', list_status=status,
            fields='ts_code,symbol,name,area,industry,market,'
                   'list_date,delist_date,list_status,exchange,is_hs'
        )
        logger.info(f'stock_basic(list_status={status}): {len(df)} rows')
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)
    logger.info(f'Total symbols: {len(df)}')

    # 构建upsert记录
    conn = get_sync_conn()
    inserted = 0
    updated = 0

    try:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                ts_code = str(row['ts_code'])
                code = ts_code.split('.')[0]
                name = str(row.get('name', ''))
                board, price_limit = _detect_board(ts_code, name)
                exchange = ts_code.split('.')[-1] if '.' in ts_code else None

                # Map exchange
                if exchange == 'SH':
                    exchange = 'SSE'
                elif exchange == 'SZ':
                    exchange = 'SZSE'
                elif exchange == 'BJ':
                    exchange = 'BSE'

                list_date = None
                if pd.notna(row.get('list_date')):
                    list_date = pd.to_datetime(row['list_date']).date()
                delist_date = None
                if pd.notna(row.get('delist_date')):
                    delist_date = pd.to_datetime(row['delist_date']).date()

                list_status = str(row.get('list_status', 'L'))
                is_active = list_status == 'L'
                area = str(row.get('area', '')) or None
                industry = str(row.get('industry', '')) or None
                is_hs = str(row.get('is_hs', '')) or None

                cur.execute("""
                    INSERT INTO symbols (code, ts_code, name, market, board, exchange,
                        industry_sw1, area, list_date, delist_date, list_status,
                        is_hs, price_limit, lot_size, is_active)
                    VALUES (%s, %s, %s, 'astock', %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, 100, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        name=EXCLUDED.name, list_status=EXCLUDED.list_status,
                        delist_date=EXCLUDED.delist_date, is_active=EXCLUDED.is_active,
                        board=EXCLUDED.board, price_limit=EXCLUDED.price_limit,
                        updated_at=NOW()
                """, (
                    code, ts_code, name, board, exchange,
                    industry, area, list_date, delist_date, list_status,
                    is_hs, price_limit, is_active,
                ))

            conn.commit()

        # 统计结果
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM symbols")
            total = cur.fetchone()[0]

        logger.info(f'Symbols table now has {total} rows')

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
