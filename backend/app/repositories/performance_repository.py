"""Performance Repository — performance_series表访问。

Paper Trading和实盘的NAV/收益/回撤数据读写。
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base_repository import BaseRepository


class PerformanceRepository(BaseRepository):
    """performance_series表的数据访问。"""

    async def get_latest_nav(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> Optional[dict]:
        """获取最新一天的绩效数据。"""
        row = await self.fetch_one(
            """SELECT trade_date, nav, daily_return, cumulative_return,
                      drawdown, cash_ratio, cash, position_count, turnover,
                      benchmark_nav
               FROM performance_series
               WHERE strategy_id = :sid AND execution_mode = :mode
               ORDER BY trade_date DESC LIMIT 1""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        if not row:
            return None
        return {
            "trade_date": row[0],
            "nav": float(row[1]) if row[1] else 0,
            "daily_return": float(row[2]) if row[2] else 0,
            "cumulative_return": float(row[3]) if row[3] else 0,
            "drawdown": float(row[4]) if row[4] else 0,
            "cash_ratio": float(row[5]) if row[5] else 0,
            "cash": float(row[6]) if row[6] else 0,
            "position_count": row[7] or 0,
            "turnover": float(row[8]) if row[8] else 0,
            "benchmark_nav": float(row[9]) if row[9] else 0,
        }

    async def get_nav_series(
        self,
        strategy_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        execution_mode: str = "paper",
    ) -> list[dict]:
        """获取NAV时间序列。"""
        sql = """SELECT trade_date, nav, daily_return, cumulative_return, drawdown
                 FROM performance_series
                 WHERE strategy_id = :sid AND execution_mode = :mode"""
        params: dict = {"sid": strategy_id, "mode": execution_mode}

        if start_date:
            sql += " AND trade_date >= :start"
            params["start"] = start_date
        if end_date:
            sql += " AND trade_date <= :end"
            params["end"] = end_date

        sql += " ORDER BY trade_date"
        rows = await self.fetch_all(sql, params)
        return [
            {
                "trade_date": r[0],
                "nav": float(r[1]),
                "daily_return": float(r[2]),
                "cumulative_return": float(r[3]),
                "drawdown": float(r[4]),
            }
            for r in rows
        ]

    async def get_rolling_stats(
        self,
        strategy_id: str,
        lookback_days: int = 60,
        execution_mode: str = "paper",
    ) -> Optional[dict]:
        """获取滚动绩效统计（最近N天）。

        用于Paper Trading周五简报和毕业标准检查。
        """
        rows = await self.fetch_all(
            """SELECT nav, daily_return
               FROM performance_series
               WHERE strategy_id = :sid AND execution_mode = :mode
               ORDER BY trade_date DESC LIMIT :n""",
            {"sid": strategy_id, "mode": execution_mode, "n": lookback_days},
        )
        if not rows:
            return None

        navs = [float(r[0]) for r in rows]
        rets = [float(r[1]) for r in rows]
        n = len(rets)

        import numpy as np
        daily_mean = np.mean(rets)
        daily_std = np.std(rets, ddof=1) if n > 1 else 0
        sharpe = daily_mean / daily_std * np.sqrt(252) if daily_std > 0 else 0

        # MDD (navs是DESC排序，reversed后按时间正序遍历)
        # quant审查fix: peak必须从最早NAV开始，不是最新NAV
        peak = navs[-1]  # 最早的NAV（时间正序第一个）
        max_dd = 0
        for nav in reversed(navs):
            peak = max(peak, nav)
            max_dd = min(max_dd, nav / peak - 1)

        return {
            "days": n,
            "sharpe": round(sharpe, 3),
            "mdd": round(max_dd, 4),
            "total_return": round(navs[0] / navs[-1] - 1, 4) if navs[-1] > 0 else 0,
            "latest_nav": navs[0],
        }

    async def get_peak_nav(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> float:
        """获取历史最高NAV（用于回撤计算）。"""
        val = await self.fetch_scalar(
            """SELECT COALESCE(MAX(nav), 0)
               FROM performance_series
               WHERE strategy_id = :sid AND execution_mode = :mode""",
            {"sid": strategy_id, "mode": execution_mode},
        )
        return float(val) if val else 0

    async def upsert_daily(
        self,
        trade_date: date,
        strategy_id: str,
        nav: float,
        daily_return: float,
        cumulative_return: float,
        drawdown: float,
        cash_ratio: float,
        cash: float,
        position_count: int,
        turnover: float,
        benchmark_nav: float,
        execution_mode: str = "paper",
    ) -> None:
        """写入/更新当日绩效（幂等）。"""
        await self.execute(
            """INSERT INTO performance_series
               (trade_date, strategy_id, nav, daily_return, cumulative_return,
                drawdown, cash_ratio, cash, position_count, turnover,
                benchmark_nav, execution_mode)
               VALUES (:td, :sid, :nav, :ret, :cum, :dd, :cr, :cash, :pc, :to, :bn, :mode)
               ON CONFLICT (trade_date, strategy_id) DO UPDATE SET
                nav=EXCLUDED.nav, daily_return=EXCLUDED.daily_return,
                cumulative_return=EXCLUDED.cumulative_return,
                drawdown=EXCLUDED.drawdown, cash_ratio=EXCLUDED.cash_ratio,
                cash=EXCLUDED.cash, position_count=EXCLUDED.position_count,
                turnover=EXCLUDED.turnover, benchmark_nav=EXCLUDED.benchmark_nav""",
            {
                "td": trade_date, "sid": strategy_id, "nav": nav,
                "ret": daily_return, "cum": cumulative_return, "dd": drawdown,
                "cr": cash_ratio, "cash": cash, "pc": position_count,
                "to": turnover, "bn": benchmark_nav, "mode": execution_mode,
            },
        )
