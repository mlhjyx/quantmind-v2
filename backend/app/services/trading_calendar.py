"""交易日历工具函数。

提供交易日判断和导航功能，供所有Service和scripts使用。
从 run_paper_trading.py L121-166 迁移。
"""

from datetime import date
from typing import Optional


def is_trading_day(conn, trade_date: date) -> bool:
    """检查是否为A股交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE trade_date = %s AND market = 'astock'""",
        (trade_date,),
    )
    row = cur.fetchone()
    cur.close()
    return bool(row and row[0])


def get_next_trading_day(conn, trade_date: date) -> Optional[date]:
    """获取trade_date之后的下一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MIN(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date > %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def get_prev_trading_day(conn, trade_date: date) -> Optional[date]:
    """获取trade_date之前的上一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date < %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def acquire_lock(conn, lock_id: int = 202603210001) -> bool:
    """pg_advisory_lock并发保护。"""
    cur = conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
    got = cur.fetchone()[0]
    cur.close()
    return got
