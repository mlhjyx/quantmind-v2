"""Position Repository — position_snapshot表访问。

持仓快照的读写，支持Paper Trading和实盘。
"""

from datetime import date
from typing import Optional

from app.repositories.base_repository import BaseRepository


class PositionRepository(BaseRepository):
    """position_snapshot表的数据访问。"""

    async def get_latest_positions(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> list[dict]:
        """获取最新日期的全部持仓。"""
        rows = await self.fetch_all(
            """SELECT code, quantity, market_value, weight, avg_cost,
                      unrealized_pnl, holding_days
               FROM position_snapshot
               WHERE strategy_id = :sid AND execution_mode = :mode
                 AND trade_date = (
                   SELECT MAX(trade_date) FROM position_snapshot
                   WHERE strategy_id = :sid AND execution_mode = :mode
                 )
               ORDER BY weight DESC""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        return [
            {
                "code": r[0],
                "quantity": r[1] or 0,
                "market_value": float(r[2]) if r[2] else 0,
                "weight": float(r[3]) if r[3] else 0,
                "avg_cost": float(r[4]) if r[4] else 0,
                "unrealized_pnl": float(r[5]) if r[5] else 0,
                "holding_days": r[6] or 0,
            }
            for r in rows
        ]

    async def get_positions_at_date(
        self, strategy_id: str, trade_date: date, execution_mode: str = "paper"
    ) -> list[dict]:
        """获取指定日期的持仓。"""
        rows = await self.fetch_all(
            """SELECT code, quantity, market_value, weight
               FROM position_snapshot
               WHERE strategy_id = :sid AND trade_date = :td AND execution_mode = :mode
               ORDER BY weight DESC""",
            {"sid": strategy_id, "td": trade_date, "mode": execution_mode},
        )
        return [
            {
                "code": r[0],
                "quantity": r[1] or 0,
                "market_value": float(r[2]) if r[2] else 0,
                "weight": float(r[3]) if r[3] else 0,
            }
            for r in rows
        ]

    async def get_position_count(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> int:
        """获取最新持仓数量。"""
        val = await self.fetch_scalar(
            """SELECT COUNT(*) FROM position_snapshot
               WHERE strategy_id = :sid AND execution_mode = :mode
                 AND trade_date = (
                   SELECT MAX(trade_date) FROM position_snapshot
                   WHERE strategy_id = :sid AND execution_mode = :mode
                 )""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        return val or 0

    async def get_industry_exposure(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> list[dict]:
        """获取行业暴露（最新持仓join symbols表）。"""
        rows = await self.fetch_all(
            """SELECT s.industry_sw1, SUM(p.weight) as total_weight, COUNT(*) as n_stocks
               FROM position_snapshot p
               JOIN symbols s ON p.code = s.code
               WHERE p.strategy_id = :sid AND p.execution_mode = :mode
                 AND p.trade_date = (
                   SELECT MAX(trade_date) FROM position_snapshot
                   WHERE strategy_id = :sid AND execution_mode = :mode
                 )
               GROUP BY s.industry_sw1
               ORDER BY total_weight DESC""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        return [
            {"industry": r[0], "weight": float(r[1]), "n_stocks": r[2]}
            for r in rows
        ]

    async def save_snapshot(
        self,
        trade_date: date,
        strategy_id: str,
        positions: list[dict],
        execution_mode: str = "paper",
    ) -> None:
        """保存持仓快照（DELETE+INSERT幂等）。

        positions: [{"code": str, "quantity": int, "market_value": float, "weight": float}]
        """
        # 删除旧快照
        await self.execute(
            """DELETE FROM position_snapshot
               WHERE trade_date = :td AND strategy_id = :sid AND execution_mode = :mode""",
            {"td": trade_date, "sid": strategy_id, "mode": execution_mode},
        )

        # 插入新快照
        for pos in positions:
            await self.execute(
                """INSERT INTO position_snapshot
                   (code, trade_date, strategy_id, quantity, market_value, weight, execution_mode)
                   VALUES (:code, :td, :sid, :qty, :mv, :w, :mode)""",
                {
                    "code": pos["code"],
                    "td": trade_date,
                    "sid": strategy_id,
                    "qty": pos["quantity"],
                    "mv": pos["market_value"],
                    "w": pos["weight"],
                    "mode": execution_mode,
                },
            )
