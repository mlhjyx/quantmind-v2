"""数据入库模块 — 将Tushare拉取的数据批量写入PostgreSQL。

按日期批量写入，单日单事务。使用psycopg2直接操作（不走ORM），
因为这是批量数据加载，ORM开销不划算。

单位保持Tushare原始值：
- volume: 手 (1手=100股)
- amount: 千元
- pct_change: 已×100 (5.06 = 5.06%)
- total_mv/circ_mv: 万元
"""

import logging
from datetime import date

import pandas as pd
import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import execute_values

from app.config import settings

logger = logging.getLogger(__name__)


def get_sync_conn() -> psycopg2.extensions.connection:
    """获取同步数据库连接（用于批量加载）。"""
    url = settings.DATABASE_URL
    # 支持 postgresql+asyncpg:// 和 postgresql:// 两种格式
    for prefix in ('postgresql+asyncpg://', 'postgres://'):
        url = url.replace(prefix, 'postgresql://')
    return psycopg2.connect(url)


def _df_to_records(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    """将DataFrame转为psycopg2 execute_values需要的tuple列表。"""
    sub = df[cols].copy()
    sub = sub.where(pd.notna(sub), other=None)
    return list(sub.itertuples(index=False, name=None))


# 缓存symbols code集合（避免每次upsert都查库）
_symbols_cache: set[str] | None = None


def _get_valid_codes(conn: psycopg2.extensions.connection) -> set[str]:
    """获取symbols表中全部code，用于FK过滤。"""
    global _symbols_cache
    if _symbols_cache is None:
        with conn.cursor() as cur:
            cur.execute('SELECT code FROM symbols')
            _symbols_cache = {r[0] for r in cur.fetchall()}
        logger.info(f'Loaded {len(_symbols_cache)} valid codes from symbols')
    return _symbols_cache


def _filter_valid_codes(
    df: pd.DataFrame, conn: psycopg2.extensions.connection
) -> pd.DataFrame:
    """过滤掉symbols表中不存在的code，避免FK约束失败。"""
    valid = _get_valid_codes(conn)
    mask = df['code'].isin(valid)
    dropped = len(df) - mask.sum()
    if dropped > 0:
        logger.debug(f'Filtered out {dropped} rows with unknown codes')
    return df[mask].reset_index(drop=True)


def upsert_klines_daily(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert klines_daily数据。

    Args:
        df: 列名与klines_daily表对齐的DataFrame
        conn: 可选的数据库连接，不传则内部创建（兼容旧调用方式）
    Returns:
        写入行数
    """
    if df.empty:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_sync_conn()

    # FK过滤：移除symbols表中不存在的code
    df = _filter_valid_codes(df, conn)
    if df.empty:
        if own_conn:
            conn.close()
        return 0

    cols = [
        'code', 'trade_date', 'open', 'high', 'low', 'close',
        'pre_close', 'change', 'pct_change', 'volume', 'amount',
        'turnover_rate', 'adj_factor', 'is_suspended', 'is_st',
        'up_limit', 'down_limit'
    ]

    for col in cols:
        if col not in df.columns:
            df[col] = None

    sql = f"""
        INSERT INTO klines_daily ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (code, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            pre_close = EXCLUDED.pre_close,
            change = EXCLUDED.change,
            pct_change = EXCLUDED.pct_change,
            volume = EXCLUDED.volume,
            amount = EXCLUDED.amount,
            turnover_rate = EXCLUDED.turnover_rate,
            adj_factor = EXCLUDED.adj_factor,
            is_suspended = EXCLUDED.is_suspended,
            is_st = EXCLUDED.is_st,
            up_limit = EXCLUDED.up_limit,
            down_limit = EXCLUDED.down_limit
    """

    records = _df_to_records(df, cols)
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, records, page_size=10000)
        conn.commit()
        logger.info(f'Upserted {len(records)} rows to klines_daily')
        return len(records)
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def upsert_daily_basic(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert daily_basic数据。"""
    if df.empty:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_sync_conn()

    df = df.rename(columns={'ts_code': 'code'})
    # Strip交易所后缀: 000001.SZ → 000001
    df['code'] = df['code'].str.split('.').str[0]
    # FK过滤
    df = _filter_valid_codes(df, conn)
    if df.empty:
        if own_conn:
            conn.close()
        return 0

    cols = [
        'code', 'trade_date', 'close', 'turnover_rate', 'turnover_rate_f',
        'volume_ratio', 'pe', 'pe_ttm', 'pb', 'ps', 'ps_ttm',
        'dv_ratio', 'dv_ttm',
        'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv'
    ]
    available_cols = [c for c in cols if c in df.columns]

    sql = f"""
        INSERT INTO daily_basic ({', '.join(available_cols)})
        VALUES %s
        ON CONFLICT (code, trade_date) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in available_cols if c not in ('code', 'trade_date'))}
    """

    records = _df_to_records(df, available_cols)
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, records, page_size=10000)
        conn.commit()
        logger.info(f'Upserted {len(records)} rows to daily_basic')
        return len(records)
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def upsert_index_daily(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert index_daily数据。"""
    if df.empty:
        return 0

    df = df.rename(columns={
        'ts_code': 'index_code',
        'vol': 'volume',
        'pct_chg': 'pct_change',
    })

    cols = ['index_code', 'trade_date', 'open', 'high', 'low',
            'close', 'pre_close', 'pct_change', 'volume', 'amount']
    available_cols = [c for c in cols if c in df.columns]

    sql = f"""
        INSERT INTO index_daily ({', '.join(available_cols)})
        VALUES %s
        ON CONFLICT (index_code, trade_date) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in available_cols if c not in ('index_code', 'trade_date'))}
    """

    records = _df_to_records(df, available_cols)
    own_conn = conn is None
    if own_conn:
        conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, records, page_size=10000)
        conn.commit()
        logger.info(f'Upserted {len(records)} rows to index_daily')
        return len(records)
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


_ALLOWED_TABLES = {'klines_daily', 'daily_basic', 'index_daily'}


def get_last_loaded_date(table: str, date_col: str = 'trade_date') -> date | None:
    """获取某表最新已加载的日期，用于断点续传。"""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f'Invalid table: {table!r}')
    conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            query = psql.SQL('SELECT MAX({col}) FROM {tbl}').format(
                col=psql.Identifier(date_col),
                tbl=psql.Identifier(table),
            )
            cur.execute(query)
            return cur.fetchone()[0]
    finally:
        conn.close()
