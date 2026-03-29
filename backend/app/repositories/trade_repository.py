"""Trade Repository — trade_log表访问。

交易记录的读写，支持Paper Trading和实盘。
"""

from datetime import date

from app.repositories.base_repository import BaseRepository


class TradeRepository(BaseRepository):
    """trade_log表的数据访问。"""

    async def get_trades(
        self,
        strategy_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        execution_mode: str = "paper",
        limit: int = 100,
    ) -> list[dict]:
        """获取交易记录。"""
        sql = """SELECT id, code, trade_date, direction, quantity,
                        fill_price, slippage_bps, commission, stamp_tax,
                        total_cost, reject_reason
                 FROM trade_log
                 WHERE strategy_id = :sid AND execution_mode = :mode"""
        params: dict = {"sid": strategy_id, "mode": execution_mode}

        if start_date:
            sql += " AND trade_date >= :start"
            params["start"] = start_date
        if end_date:
            sql += " AND trade_date <= :end"
            params["end"] = end_date

        sql += " ORDER BY trade_date DESC, created_at DESC LIMIT :lim"
        params["lim"] = limit

        rows = await self.fetch_all(sql, params)
        return [
            {
                "id": str(r[0]),
                "code": r[1],
                "trade_date": r[2],
                "direction": r[3],
                "quantity": r[4],
                "fill_price": float(r[5]) if r[5] else 0,
                "slippage_bps": float(r[6]) if r[6] else 0,
                "commission": float(r[7]) if r[7] else 0,
                "stamp_tax": float(r[8]) if r[8] else 0,
                "total_cost": float(r[9]) if r[9] else 0,
                "reject_reason": r[10],
            }
            for r in rows
        ]

    async def get_trade_summary(
        self,
        strategy_id: str,
        trade_date: date,
        execution_mode: str = "paper",
    ) -> dict:
        """获取指定日期的交易汇总。"""
        row = await self.fetch_one(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN direction='buy' THEN 1 ELSE 0 END) as buys,
                      SUM(CASE WHEN direction='sell' THEN 1 ELSE 0 END) as sells,
                      SUM(total_cost) as total_cost
               FROM trade_log
               WHERE strategy_id = :sid AND trade_date = :td AND execution_mode = :mode""",
            {"sid": strategy_id, "td": trade_date, "mode": execution_mode},
        )
        return {
            "total": row[0] or 0,
            "buys": row[1] or 0,
            "sells": row[2] or 0,
            "total_cost": float(row[3]) if row[3] else 0,
        }

    async def insert_trade(
        self,
        code: str,
        trade_date: date,
        strategy_id: str,
        direction: str,
        quantity: int,
        fill_price: float,
        slippage_bps: float,
        commission: float,
        stamp_tax: float,
        total_cost: float,
        execution_mode: str = "paper",
        reject_reason: str | None = None,
    ) -> None:
        """插入交易记录。"""
        await self.execute(
            """INSERT INTO trade_log
               (code, trade_date, strategy_id, direction, quantity,
                fill_price, slippage_bps, commission, stamp_tax,
                total_cost, execution_mode, reject_reason)
               VALUES (:code, :td, :sid, :dir, :qty, :fp, :slip,
                       :comm, :tax, :tc, :mode, :rr)""",
            {
                "code": code, "td": trade_date, "sid": strategy_id,
                "dir": direction, "qty": quantity, "fp": fill_price,
                "slip": slippage_bps, "comm": commission, "tax": stamp_tax,
                "tc": total_cost, "mode": execution_mode, "rr": reject_reason,
            },
        )
