"""数据入库模块 — 将Tushare拉取的数据批量写入PostgreSQL。

所有写入通过DataPipeline统一验证+单位转换+upsert。
Contract定义在contracts.py中。

DB存储单位(转换后):
- amount: 元 (Tushare千元×1000)
- total_mv/circ_mv: 元 (Tushare万元×10000)
- volume: 手 (保持不变)
- pct_change: %×100 (保持不变)
"""

from datetime import date

import pandas as pd
import psycopg2
import structlog
from psycopg2 import sql as psql

from app.config import settings
from app.data_fetcher.contracts import DAILY_BASIC, INDEX_DAILY, KLINES_DAILY
from app.data_fetcher.pipeline import DataPipeline

logger = structlog.get_logger(__name__)


def get_sync_conn() -> psycopg2.extensions.connection:
    """获取同步数据库连接（用于批量加载）。"""
    url = settings.DATABASE_URL
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        url = url.replace(prefix, "postgresql://")
    return psycopg2.connect(url)


# 缓存symbols code集合（避免每次upsert都查库）
_symbols_cache: set[str] | None = None


def _get_valid_codes(conn: psycopg2.extensions.connection) -> set[str]:
    """获取symbols表中全部code，用于FK过滤。"""
    global _symbols_cache  # noqa: PLW0603
    if _symbols_cache is None:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM symbols")
            _symbols_cache = {r[0] for r in cur.fetchall()}
        logger.info("Loaded %d valid codes from symbols", len(_symbols_cache))
    return _symbols_cache


def _filter_valid_codes(
    df: pd.DataFrame, conn: psycopg2.extensions.connection
) -> pd.DataFrame:
    """过滤掉symbols表中不存在的code，避免FK约束失败。"""
    valid = _get_valid_codes(conn)
    mask = df["code"].isin(valid)
    dropped = len(df) - mask.sum()
    if dropped > 0:
        logger.debug("Filtered out %d rows with unknown codes", dropped)
    return df[mask].reset_index(drop=True)


def upsert_klines_daily(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert klines_daily数据（通过DataPipeline）。

    Pipeline自动处理: rename(ts_code→code) + 单位转换(amount千元→元) + 验证 + FK过滤 + upsert。

    Args:
        df: Tushare daily数据或已对齐的DataFrame
        conn: 可选的数据库连接
    Returns:
        写入行数
    """
    if df.empty:
        return 0

    pipeline = DataPipeline(conn)
    try:
        result = pipeline.ingest(df, KLINES_DAILY)
        if result.rejected_rows > 0:
            logger.warning(
                "klines_daily: %d/%d rows rejected: %s",
                result.rejected_rows,
                result.total_rows,
                result.reject_reasons,
            )
        return result.upserted_rows
    finally:
        if conn is None:
            pipeline.close()


def upsert_daily_basic(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert daily_basic数据（通过DataPipeline）。

    Pipeline自动处理: rename(ts_code→code) + 单位转换(total_mv/circ_mv万元→元) + 验证 + FK过滤 + upsert。
    """
    if df.empty:
        return 0

    pipeline = DataPipeline(conn)
    try:
        result = pipeline.ingest(df, DAILY_BASIC)
        if result.rejected_rows > 0:
            logger.warning(
                "daily_basic: %d/%d rows rejected: %s",
                result.rejected_rows,
                result.total_rows,
                result.reject_reasons,
            )
        return result.upserted_rows
    finally:
        if conn is None:
            pipeline.close()


def upsert_index_daily(
    df: pd.DataFrame,
    conn: psycopg2.extensions.connection | None = None,
) -> int:
    """批量upsert index_daily数据（通过DataPipeline）。

    Pipeline自动处理: rename(ts_code→index_code, vol→volume, pct_chg→pct_change) + 单位转换(amount千元→元) + upsert。
    """
    if df.empty:
        return 0

    pipeline = DataPipeline(conn)
    try:
        result = pipeline.ingest(df, INDEX_DAILY)
        if result.rejected_rows > 0:
            logger.warning(
                "index_daily: %d/%d rows rejected: %s",
                result.rejected_rows,
                result.total_rows,
                result.reject_reasons,
            )
        return result.upserted_rows
    finally:
        if conn is None:
            pipeline.close()


_ALLOWED_TABLES = {"klines_daily", "daily_basic", "index_daily"}


def get_last_loaded_date(table: str, date_col: str = "trade_date") -> date | None:
    """获取某表最新已加载的日期，用于断点续传。"""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Invalid table: {table!r}")
    conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            query = psql.SQL("SELECT MAX({col}) FROM {tbl}").format(
                col=psql.Identifier(date_col),
                tbl=psql.Identifier(table),
            )
            cur.execute(query)
            return cur.fetchone()[0]
    finally:
        conn.close()
