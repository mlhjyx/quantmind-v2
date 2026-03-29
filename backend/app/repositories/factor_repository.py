"""Factor Repository — factor_values表访问。

因子数据的读写。factor_values是长表(TimescaleDB hypertable)。
CLAUDE.md: 索引(symbol_id, date, factor_name)，读取时永远带date范围。
"""

from datetime import date

from app.repositories.base_repository import BaseRepository


class FactorRepository(BaseRepository):
    """factor_values表的数据访问。"""

    async def get_factor_values(
        self,
        trade_date: date,
        factor_names: list[str] | None = None,
    ) -> list[dict]:
        """获取指定日期的因子值。"""
        sql = """SELECT code, factor_name, raw_value, neutral_value, zscore
                 FROM factor_values WHERE trade_date = :td"""
        params: dict = {"td": trade_date}

        if factor_names:
            sql += " AND factor_name = ANY(:fnames)"
            params["fnames"] = factor_names

        sql += " ORDER BY code, factor_name"
        rows = await self.fetch_all(sql, params)
        return [
            {
                "code": r[0], "factor_name": r[1],
                "raw_value": float(r[2]) if r[2] else None,
                "neutral_value": float(r[3]) if r[3] else None,
                "zscore": float(r[4]) if r[4] else None,
            }
            for r in rows
        ]

    async def get_factor_ic_history(
        self,
        factor_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 120,
    ) -> list[dict]:
        """获取因子IC时序（需要与forward return join计算）。

        注意：IC计算是重计算，这里只返回因子值统计。
        完整IC计算由FactorAnalyzer在engines层完成。
        """
        sql = """SELECT trade_date,
                        AVG(zscore) as mean_zscore,
                        STDDEV(zscore) as std_zscore,
                        COUNT(*) as coverage
                 FROM factor_values
                 WHERE factor_name = :fname"""
        params: dict = {"fname": factor_name}

        if start_date:
            sql += " AND trade_date >= :start"
            params["start"] = start_date
        if end_date:
            sql += " AND trade_date <= :end"
            params["end"] = end_date

        sql += " GROUP BY trade_date ORDER BY trade_date DESC LIMIT :lim"
        params["lim"] = limit

        rows = await self.fetch_all(sql, params)
        return [
            {
                "trade_date": r[0],
                "mean_zscore": float(r[1]) if r[1] else 0,
                "std_zscore": float(r[2]) if r[2] else 0,
                "coverage": r[3],
            }
            for r in rows
        ]

    async def get_latest_factor_date(self) -> date | None:
        """获取最新因子计算日期。"""
        return await self.fetch_scalar(
            "SELECT MAX(trade_date) FROM factor_values"
        )

    async def get_factor_coverage(self, trade_date: date) -> list[dict]:
        """获取指定日期各因子的覆盖率。"""
        rows = await self.fetch_all(
            """SELECT factor_name, COUNT(*) as n_stocks,
                      SUM(CASE WHEN zscore IS NULL THEN 1 ELSE 0 END) as n_null
               FROM factor_values
               WHERE trade_date = :td
               GROUP BY factor_name
               ORDER BY factor_name""",
            {"td": trade_date},
        )
        return [
            {
                "factor_name": r[0],
                "n_stocks": r[1],
                "n_null": r[2],
                "coverage": round(1 - r[2] / r[1], 4) if r[1] > 0 else 0,
            }
            for r in rows
        ]
