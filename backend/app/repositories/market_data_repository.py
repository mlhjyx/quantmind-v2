"""Market Data Repository — klines_daily + daily_basic + index_daily + symbols表访问。

行情数据、基本面数据、指数数据、股票基础信息的读取。
CLAUDE.md: 所有(symbol_id, date)组合必须有联合索引。
"""

from datetime import date
from typing import Optional

from app.repositories.base_repository import BaseRepository


class MarketDataRepository(BaseRepository):
    """行情+基本面+指数+股票信息的数据访问。"""

    async def get_daily_prices(
        self, trade_date: date, codes: Optional[list[str]] = None
    ) -> list[dict]:
        """获取指定日期的行情数据。"""
        sql = """SELECT code, open, high, low, close, pre_close,
                        volume, amount, up_limit, down_limit
                 FROM klines_daily WHERE trade_date = :td"""
        params: dict = {"td": trade_date}
        if codes:
            sql += " AND code = ANY(:codes)"
            params["codes"] = codes
        sql += " ORDER BY code"

        rows = await self.fetch_all(sql, params)
        return [
            {
                "code": r[0], "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "pre_close": float(r[5]) if r[5] else 0,
                "volume": float(r[6]), "amount": float(r[7]),
                "up_limit": float(r[8]) if r[8] else None,
                "down_limit": float(r[9]) if r[9] else None,
            }
            for r in rows
        ]

    async def get_benchmark_close(
        self, trade_date: date, index_code: str = "000300.SH"
    ) -> Optional[float]:
        """获取基准指数收盘价。"""
        val = await self.fetch_scalar(
            "SELECT close FROM index_daily WHERE index_code = :ic AND trade_date = :td",
            {"ic": index_code, "td": trade_date},
        )
        return float(val) if val else None

    async def get_benchmark_series(
        self,
        start_date: date,
        end_date: date,
        index_code: str = "000300.SH",
    ) -> list[dict]:
        """获取基准指数时间序列。"""
        rows = await self.fetch_all(
            """SELECT trade_date, close FROM index_daily
               WHERE index_code = :ic AND trade_date BETWEEN :s AND :e
               ORDER BY trade_date""",
            {"ic": index_code, "s": start_date, "e": end_date},
        )
        return [{"trade_date": r[0], "close": float(r[1])} for r in rows]

    async def get_symbol_info(self, code: str) -> Optional[dict]:
        """获取股票基础信息。"""
        row = await self.fetch_one(
            """SELECT code, name, industry_sw1, industry_sw2, market,
                      list_date, delist_date, board_type, price_limit
               FROM symbols WHERE code = :code""",
            {"code": code},
        )
        if not row:
            return None
        return {
            "code": row[0], "name": row[1], "industry_sw1": row[2],
            "industry_sw2": row[3], "market": row[4],
            "list_date": row[5], "delist_date": row[6],
            "board_type": row[7], "price_limit": float(row[8]) if row[8] else 0.1,
        }

    async def is_trading_day(self, trade_date: date, market: str = "astock") -> bool:
        """检查是否为交易日。"""
        val = await self.fetch_scalar(
            """SELECT is_trading_day FROM trading_calendar
               WHERE trade_date = :td AND market = :m""",
            {"td": trade_date, "m": market},
        )
        return bool(val)

    async def get_next_trading_day(
        self, trade_date: date, market: str = "astock"
    ) -> Optional[date]:
        """获取下一个交易日。"""
        return await self.fetch_scalar(
            """SELECT MIN(trade_date) FROM trading_calendar
               WHERE market = :m AND is_trading_day = TRUE AND trade_date > :td""",
            {"m": market, "td": trade_date},
        )

    async def get_latest_data_date(self) -> Optional[date]:
        """获取最新行情日期。"""
        return await self.fetch_scalar("SELECT MAX(trade_date) FROM klines_daily")
