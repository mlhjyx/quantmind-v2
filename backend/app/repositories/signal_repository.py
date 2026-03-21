"""Signal Repository — signals表访问。

信号记录的读写，支持Paper Trading和实盘。
"""

from datetime import date
from typing import Optional

from app.repositories.base_repository import BaseRepository


class SignalRepository(BaseRepository):
    """signals表的数据访问。"""

    async def get_signals(
        self,
        strategy_id: str,
        trade_date: date,
        execution_mode: str = "paper",
    ) -> list[dict]:
        """获取指定日期的信号。"""
        rows = await self.fetch_all(
            """SELECT code, alpha_score, rank, target_weight, action
               FROM signals
               WHERE strategy_id = :sid AND trade_date = :td AND execution_mode = :mode
               ORDER BY rank""",
            {"sid": strategy_id, "td": trade_date, "mode": execution_mode},
        )
        return [
            {
                "code": r[0],
                "alpha_score": float(r[1]) if r[1] else 0,
                "rank": r[2],
                "target_weight": float(r[3]) if r[3] else 0,
                "action": r[4],
            }
            for r in rows
        ]

    async def get_latest_signals(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> list[dict]:
        """获取最新日期的信号。"""
        latest_date = await self.fetch_scalar(
            """SELECT MAX(trade_date) FROM signals
               WHERE strategy_id = :sid AND execution_mode = :mode""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        if not latest_date:
            return []
        return await self.get_signals(strategy_id, latest_date, execution_mode)

    async def save_signals(
        self,
        trade_date: date,
        strategy_id: str,
        signals: list[dict],
        execution_mode: str = "paper",
    ) -> None:
        """保存信号（DELETE+INSERT幂等）。

        signals: [{"code": str, "alpha_score": float, "rank": int,
                   "target_weight": float, "action": str}]
        """
        await self.execute(
            """DELETE FROM signals
               WHERE trade_date = :td AND strategy_id = :sid AND execution_mode = :mode""",
            {"td": trade_date, "sid": strategy_id, "mode": execution_mode},
        )
        for sig in signals:
            await self.execute(
                """INSERT INTO signals
                   (code, trade_date, strategy_id, alpha_score, rank,
                    target_weight, action, execution_mode)
                   VALUES (:code, :td, :sid, :score, :rank, :tw, :action, :mode)""",
                {
                    "code": sig["code"], "td": trade_date, "sid": strategy_id,
                    "score": sig["alpha_score"], "rank": sig["rank"],
                    "tw": sig["target_weight"], "action": sig["action"],
                    "mode": execution_mode,
                },
            )
