"""交易日历工具函数。

提供交易日判断和导航功能，供所有Service和scripts使用。
从 run_paper_trading.py L121-166 迁移。

增强: 集成TradingDayChecker多层fallback（Tushare API → 本地DB → 启发式）。
原有函数签名不变，内部自动使用增强逻辑。
"""

from datetime import date


def is_trading_day(conn, trade_date: date) -> bool:
    """检查是否为A股交易日（多层fallback）。

    优先用本地DB（快），查不到时fallback到Tushare API + 启发式。
    """
    # 快速路径: 本地DB查询
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE trade_date = %s AND market = 'astock'""",
        (trade_date,),
    )
    row = cur.fetchone()
    cur.close()
    if row is not None:
        return bool(row[0])

    # 本地无记录: 用TradingDayChecker fallback
    try:
        from engines.trading_day_checker import TradingDayChecker
        checker = TradingDayChecker(conn)
        is_td, reason = checker.is_trading_day(trade_date)
        return is_td
    except Exception:
        # 最终兜底: 周末=非交易日
        return trade_date.weekday() < 5


def get_next_trading_day(conn, trade_date: date) -> date | None:
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
    if row and row[0]:
        return row[0]

    # DB无记录: fallback
    try:
        from engines.trading_day_checker import TradingDayChecker
        return TradingDayChecker(conn).next_trading_day(trade_date)
    except Exception:
        from datetime import timedelta
        d = trade_date + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d


def get_prev_trading_day(conn, trade_date: date) -> date | None:
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
    if row and row[0]:
        return row[0]

    # DB无记录: fallback
    try:
        from engines.trading_day_checker import TradingDayChecker
        return TradingDayChecker(conn).prev_trading_day(trade_date)
    except Exception:
        from datetime import timedelta
        d = trade_date - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d


def acquire_lock(conn, lock_id: int = 202603210001) -> bool:
    """pg_advisory_lock并发保护。"""
    cur = conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
    got = cur.fetchone()[0]
    cur.close()
    return got
