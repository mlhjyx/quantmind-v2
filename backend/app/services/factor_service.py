"""FactorService — 因子计算引擎的Service层封装。

封装 backend/engines/factor_engine.py 的计算函数，
提供API层可调用的异步接口。

设计文档对照:
- docs/DEV_BACKEND.md §三 services/factor_service.py
- docs/DEV_FACTOR_MINING.md（因子计算规则+预处理顺序）

FastAPI Depends注入模式:
    async def get_factor_service(
        session: AsyncSession = Depends(get_async_session),
    ) -> FactorService:
        return FactorService(session)
"""

import structlog
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class FactorService:
    """因子计算+查询Service层。

    提供:
    - get_factor_values: 查询指定日期/因子的已计算值
    - compute_factor: 触发单因子重算（异步Celery任务）
    - get_factor_ic: 查询因子IC时序
    - get_factor_list: 查询因子注册表
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_factor_values(
        self,
        factor_name: str,
        trade_date: date,
        codes: list[str] | None = None,
        neutralized: bool = True,
    ) -> pd.DataFrame:
        """查询指定因子在指定日期的截面值。

        Args:
            factor_name: 因子名称（对应factor_registry.factor_name）
            trade_date: 交易日
            codes: 可选股票代码过滤，None表示全市场
            neutralized: True返回neutral_value（中性化后），False返回raw_value

        Returns:
            pd.DataFrame: columns=[code, factor_name, value]
            空DataFrame表示无数据
        """
        # factor_values表是扁平结构: code/trade_date/factor_name/raw_value/neutral_value/zscore
        # 不需要JOIN factor_registry或symbols（Sprint 1.19集成修复）
        value_col = "neutral_value" if neutralized else "raw_value"

        sql = text(
            f"""
            SELECT code,
                   factor_name,
                   {value_col} AS value
            FROM factor_values
            WHERE factor_name = :factor_name
              AND trade_date = :trade_date
              AND {value_col} IS NOT NULL
            """
        )
        params: dict[str, Any] = {
            "factor_name": factor_name,
            "trade_date": trade_date,
        }

        if codes:
            sql = text(
                f"""
                SELECT code,
                       factor_name,
                       {value_col} AS value
                FROM factor_values
                WHERE factor_name = :factor_name
                  AND trade_date = :trade_date
                  AND {value_col} IS NOT NULL
                  AND code = ANY(:codes)
                """
            )
            params["codes"] = codes

        result = await self._session.execute(sql, params)
        rows = result.fetchall()

        if not rows:
            logger.warning(
                f"[FactorService] get_factor_values: "
                f"factor={factor_name}, date={trade_date}, 无数据"
            )
            return pd.DataFrame(columns=["code", "factor_name", "value"])

        df = pd.DataFrame(rows, columns=["code", "factor_name", "value"])
        df["value"] = df["value"].astype(float)
        return df

    async def get_factor_ic(
        self,
        factor_name: str,
        start_date: date,
        end_date: date,
        forward_days: int = 20,
    ) -> pd.DataFrame:
        """查询因子IC时序。

        Args:
            factor_name: 因子名称
            start_date: 起始日期
            end_date: 截止日期
            forward_days: 前向收益窗口（天），对应factor_ic表的forward_days列

        Returns:
            pd.DataFrame: columns=[trade_date, ic_value, factor_name]
            按trade_date升序排列
        """
        # factor_ic_history存储多周期IC: ic_1d/ic_5d/ic_10d/ic_20d
        ic_col = {1: "ic_1d", 5: "ic_5d", 10: "ic_10d", 20: "ic_20d"}.get(
            forward_days, "ic_20d"
        )
        sql = text(
            f"""
            SELECT trade_date, {ic_col} AS ic_value, factor_name
            FROM factor_ic_history
            WHERE factor_name = :factor_name
              AND trade_date BETWEEN :start_date AND :end_date
            ORDER BY trade_date ASC
            """
        )
        result = await self._session.execute(
            sql,
            {
                "factor_name": factor_name,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame(columns=["trade_date", "ic_value", "factor_name"])
        return pd.DataFrame(rows, columns=["trade_date", "ic_value", "factor_name"])

    async def get_factor_list(self, status: str | None = None) -> list[dict[str, Any]]:
        """查询因子注册表。

        Args:
            status: 可选过滤状态（'active'/'deprecated'等），None返回全部

        Returns:
            list[dict]: 因子信息列表，含factor_name/category/direction/status等
        """
        if status:
            sql = text(
                """
                SELECT name AS factor_name, category, direction, status,
                       hypothesis AS description, created_at
                FROM factor_registry
                WHERE status = :status
                ORDER BY category, name
                """
            )
            result = await self._session.execute(sql, {"status": status})
        else:
            sql = text(
                """
                SELECT name AS factor_name, category, direction, status,
                       hypothesis AS description, created_at
                FROM factor_registry
                ORDER BY category, name
                """
            )
            result = await self._session.execute(sql)

        rows = result.fetchall()
        keys = ["factor_name", "category", "direction", "status", "description", "created_at"]
        return [dict(zip(keys, row, strict=False)) for row in rows]

    async def compute_factor(
        self,
        factor_name: str,
        start_date: date,
        end_date: date,
    ) -> str:
        """触发因子重算Celery任务（异步，不等待完成）。

        Args:
            factor_name: 因子名称
            start_date: 计算起始日期
            end_date: 计算截止日期

        Returns:
            Celery任务ID（task_id）
        """
        from app.tasks.astock_tasks import compute_factor_task  # type: ignore

        task = compute_factor_task.delay(
            factor_name=factor_name,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        logger.info(
            f"[FactorService] 因子重算任务已提交: "
            f"factor={factor_name}, "
            f"period={start_date}~{end_date}, "
            f"task_id={task.id}"
        )
        return task.id

    async def get_factor_stats(
        self,
        factor_name: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """查询因子统计摘要（IC均值/IC_IR/覆盖率）。

        Args:
            factor_name: 因子名称
            start_date: 起始日期
            end_date: 截止日期

        Returns:
            dict: {ic_mean, ic_std, ic_ir, coverage_mean, data_points}
        """
        sql = text(
            """
            SELECT
                AVG(ic_20d)                       AS ic_mean,
                STDDEV(ic_20d)                    AS ic_std,
                AVG(ic_20d) /
                    NULLIF(STDDEV(ic_20d), 0)     AS ic_ir,
                COUNT(*)                          AS data_points
            FROM factor_ic_history
            WHERE factor_name = :factor_name
              AND trade_date BETWEEN :start_date AND :end_date
            """
        )
        result = await self._session.execute(
            sql,
            {
                "factor_name": factor_name,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        if not row:
            return {"ic_mean": None, "ic_std": None, "ic_ir": None, "data_points": 0}
        return {
            "ic_mean": float(row[0]) if row[0] is not None else None,
            "ic_std": float(row[1]) if row[1] is not None else None,
            "ic_ir": float(row[2]) if row[2] is not None else None,
            "data_points": int(row[3]),
        }

    async def get_factor_gate_fields(self, factor_name: str) -> dict[str, Any] | None:
        """查询因子Gate相关字段（gate_ic/gate_ir/gate_t）。

        Args:
            factor_name: 因子名称。

        Returns:
            dict含gate_ic/gate_ir/gate_t，不存在返回None。
        """
        sql = text(
            """
            SELECT gate_ic, gate_ir, gate_t
            FROM factor_registry
            WHERE name = :name
            LIMIT 1
            """
        )
        result = await self._session.execute(sql, {"name": factor_name})
        row = result.fetchone()
        if not row:
            return None
        return {
            "gate_ic": float(row[0]) if row[0] is not None else None,
            "gate_ir": float(row[1]) if row[1] is not None else None,
            "gate_t": float(row[2]) if row[2] is not None else None,
        }
