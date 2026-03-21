"""前复权价格计算工具函数。

前复权公式: adj_close = close × (adj_factor / latest_adj_factor)
其中 latest_adj_factor 是该股票最新交易日的 adj_factor。

关键注意事项（CHECKLIST 2.4节）:
- adj_factor 是累积因子，每次除权事件后会增大
- latest_adj_factor 会随新数据到来而变化，所有历史adj_close随之更新
- 本模块不物化adj_close，每次动态计算，避免V1的缓存不一致问题

使用场景:
- 因子计算层需要复权价格时调用
- 回测引擎需要复权收益率时调用
- 数据验证时抽样比对
"""

import logging
from datetime import date
from typing import Optional

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import settings

logger = logging.getLogger(__name__)


def _get_sync_conn() -> psycopg2.extensions.connection:
    """获取同步数据库连接（复用data_loader的逻辑）。"""
    url = settings.DATABASE_URL
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return psycopg2.connect(url)


# ============================================================
# 核心SQL模板
# ============================================================

# 获取每只股票最新adj_factor（用最新trade_date，不用MAX(adj_factor)）
_SQL_LATEST_ADJ = """
WITH latest_adj AS (
    SELECT DISTINCT ON (code)
        code,
        adj_factor AS latest_adj_factor
    FROM klines_daily
    ORDER BY code, trade_date DESC
)
SELECT code, latest_adj_factor FROM latest_adj
"""

# 获取指定日期范围的前复权价格（含OHLC）
_SQL_ADJ_PRICES = """
WITH latest_adj AS (
    SELECT DISTINCT ON (code)
        code,
        adj_factor AS latest_adj_factor
    FROM klines_daily
    ORDER BY code, trade_date DESC
)
SELECT
    k.code,
    k.trade_date,
    k.open,
    k.high,
    k.low,
    k.close,
    k.volume,
    k.amount,
    k.adj_factor,
    la.latest_adj_factor,
    k.open  * k.adj_factor / la.latest_adj_factor AS adj_open,
    k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
    k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
    k.close * k.adj_factor / la.latest_adj_factor AS adj_close
FROM klines_daily k
JOIN latest_adj la ON k.code = la.code
WHERE k.trade_date BETWEEN %s AND %s
  AND k.adj_factor IS NOT NULL
ORDER BY k.code, k.trade_date
"""

# 获取指定股票的前复权价格
_SQL_ADJ_PRICES_BY_CODE = """
WITH latest_adj AS (
    SELECT DISTINCT ON (code)
        code,
        adj_factor AS latest_adj_factor
    FROM klines_daily
    WHERE code = %s
    ORDER BY code, trade_date DESC
)
SELECT
    k.code,
    k.trade_date,
    k.open,
    k.high,
    k.low,
    k.close,
    k.volume,
    k.amount,
    k.adj_factor,
    la.latest_adj_factor,
    k.close * k.adj_factor / la.latest_adj_factor AS adj_close
FROM klines_daily k
JOIN latest_adj la ON k.code = la.code
WHERE k.code = %s
  AND k.trade_date BETWEEN %s AND %s
  AND k.adj_factor IS NOT NULL
ORDER BY k.trade_date
"""

# 计算前复权收益率（用于因子IC计算）
_SQL_FORWARD_RETURN = """
WITH latest_adj AS (
    SELECT DISTINCT ON (code)
        code,
        adj_factor AS latest_adj_factor
    FROM klines_daily
    ORDER BY code, trade_date DESC
),
adj AS (
    SELECT
        k.code,
        k.trade_date,
        k.close * k.adj_factor / la.latest_adj_factor AS adj_close
    FROM klines_daily k
    JOIN latest_adj la ON k.code = la.code
    WHERE k.trade_date BETWEEN %s AND %s
      AND k.adj_factor IS NOT NULL
)
SELECT
    a1.code,
    a1.trade_date,
    a1.adj_close,
    a2.adj_close AS future_adj_close,
    (a2.adj_close / NULLIF(a1.adj_close, 0) - 1) AS forward_return
FROM adj a1
JOIN adj a2 ON a1.code = a2.code
WHERE a2.trade_date = %s AND a1.trade_date = %s
"""


# ============================================================
# Python API
# ============================================================

def get_adj_prices(
    start_date: date,
    end_date: date,
    codes: Optional[list[str]] = None,
    conn: Optional[psycopg2.extensions.connection] = None,
) -> pd.DataFrame:
    """获取前复权OHLC价格。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        codes: 可选，股票代码列表。None表示全部
        conn: 可选，复用已有连接

    Returns:
        DataFrame with columns: code, trade_date, open, high, low, close,
        volume, amount, adj_factor, latest_adj_factor,
        adj_open, adj_high, adj_low, adj_close
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        if codes and len(codes) == 1:
            # 单只股票优化路径
            df = pd.read_sql(
                _SQL_ADJ_PRICES_BY_CODE,
                conn,
                params=(codes[0], codes[0], start_date, end_date),
            )
        else:
            df = pd.read_sql(
                _SQL_ADJ_PRICES,
                conn,
                params=(start_date, end_date),
            )
            if codes:
                df = df[df["code"].isin(codes)]
        return df
    finally:
        if close_conn:
            conn.close()


def get_latest_adj_factors(
    conn: Optional[psycopg2.extensions.connection] = None,
) -> pd.Series:
    """获取每只股票的最新adj_factor。

    Returns:
        Series indexed by code, values are latest_adj_factor
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        df = pd.read_sql(_SQL_LATEST_ADJ, conn)
        return df.set_index("code")["latest_adj_factor"]
    finally:
        if close_conn:
            conn.close()


def calc_adj_close_series(
    code: str,
    start_date: date,
    end_date: date,
    conn: Optional[psycopg2.extensions.connection] = None,
) -> pd.DataFrame:
    """获取单只股票的前复权收盘价序列。

    用于数据验证和因子调试。

    Returns:
        DataFrame with columns: trade_date, close, adj_factor, adj_close
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        df = pd.read_sql(
            _SQL_ADJ_PRICES_BY_CODE,
            conn,
            params=(code, code, start_date, end_date),
        )
        return df[["trade_date", "close", "adj_factor", "adj_close"]]
    finally:
        if close_conn:
            conn.close()


def verify_adj_factor_event(
    code: str,
    event_date: date,
    expected_ratio: Optional[float] = None,
    conn: Optional[psycopg2.extensions.connection] = None,
) -> dict:
    """验证指定股票在某日是否存在除权事件。

    用于数据质量验证：对比已知分红日的adj_factor跳变。

    Args:
        code: 股票代码
        event_date: 预期除权日
        expected_ratio: 预期adj_factor比值（如1.05表示5%分红）
        conn: 可选连接

    Returns:
        dict with keys: code, event_date, prev_adj, curr_adj, ratio, match
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 获取event_date当天和前一交易日的adj_factor
            cur.execute("""
                SELECT trade_date, adj_factor
                FROM klines_daily
                WHERE code = %s
                  AND trade_date <= %s
                ORDER BY trade_date DESC
                LIMIT 2
            """, (code, event_date))
            rows = cur.fetchall()

            if len(rows) < 2:
                return {
                    "code": code,
                    "event_date": event_date,
                    "error": "insufficient data",
                }

            curr = rows[0]
            prev = rows[1]
            ratio = float(curr["adj_factor"]) / float(prev["adj_factor"])

            result = {
                "code": code,
                "event_date": event_date,
                "prev_date": prev["trade_date"],
                "curr_date": curr["trade_date"],
                "prev_adj": float(prev["adj_factor"]),
                "curr_adj": float(curr["adj_factor"]),
                "ratio": round(ratio, 6),
            }

            if expected_ratio is not None:
                result["expected_ratio"] = expected_ratio
                result["match"] = abs(ratio - expected_ratio) < 0.001

            return result
    finally:
        if close_conn:
            conn.close()
