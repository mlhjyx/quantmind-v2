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

from datetime import date
from typing import Any

import pandas as pd
import structlog
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
        ic_col = {1: "ic_1d", 5: "ic_5d", 10: "ic_10d", 20: "ic_20d"}.get(forward_days, "ic_20d")
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

    async def analyze_correlation_prune(
        self,
        threshold: float = 0.85,
        lookback_days: int = 365,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """分析 Active 因子相关性, 推荐裁剪冗余因子 (PN-002 iter 11, D1 O10).

        复用 factors.py:148 GET /correlation 的 IC-series Spearman 算法 +
        CLAUDE.md doctrine `|corr| > 0.85` → IC 较低者 (lower mean |IC|)
        标记 drop_recommendation. dry_run=True 仅返回分析报告, 0 DB mutation.
        dry_run=False 本 iter 显式 out-of-scope (PN-002 §6 — factor_registry
        mutation 需 user 显式 approve flow).

        Args:
            threshold: |corr| >= threshold 视为冗余 pair. 默认 0.85 (doctrine).
            lookback_days: IC 序列回看窗口(天). 默认 365.
            dry_run: 必须为 True (本 iter scope); False → ValueError.

        Returns:
            dict: {threshold_used, lookback_days_used, pairs, dropped_count,
                   total_pairs_above_threshold, computed_at}.

        Raises:
            ValueError: dry_run=False (out of scope this iter, PN-002 §6).
        """
        if not dry_run:
            raise ValueError(
                "dry_run=False out of scope this iter (PN-002 §6); "
                "factor_registry mutation requires explicit user approval flow"
            )

        # Lazy imports (consistent with factors.py:217-218 + 1064 体例)
        from datetime import datetime, timedelta

        import numpy as np
        from scipy import stats as sp_stats

        # 1. Active factors
        factors = await self.get_factor_list(status="active")
        factor_names = [f["factor_name"] for f in factors]

        empty_report = {
            "threshold_used": threshold,
            "lookback_days_used": lookback_days,
            "pairs": [],
            "dropped_count": 0,
            "total_pairs_above_threshold": 0,
            "computed_at": datetime.utcnow().isoformat() + "Z",
        }

        if len(factor_names) < 2:
            return empty_report

        # 2. IC series per factor (沿用 factors.py:196-204 体例)
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        ic_map: dict[str, list[float]] = {}
        for name in factor_names:
            ic_df = await self.get_factor_ic(name, start_date, end_date, forward_days=20)
            if not ic_df.empty:
                values = [float(v) for v in ic_df["ic_value"].tolist() if v is not None]
                if values:
                    ic_map[name] = values

        available = [n for n in factor_names if n in ic_map]
        if len(available) < 2:
            return empty_report

        # 3. Pairwise spearmanr + mean |IC| per factor
        min_len = min(len(ic_map[n]) for n in available)
        mean_abs_ic = {n: float(np.mean(np.abs(ic_map[n]))) for n in available}

        pairs: list[dict[str, Any]] = []
        for i in range(len(available)):
            for j in range(i + 1, len(available)):
                a, b = available[i], available[j]
                series_a = ic_map[a][-min_len:]
                series_b = ic_map[b][-min_len:]
                if len(series_a) < 3:
                    continue
                corr, _ = sp_stats.spearmanr(series_a, series_b)
                corr = float(corr) if not np.isnan(corr) else 0.0
                if abs(corr) >= threshold:
                    ic_a = mean_abs_ic[a]
                    ic_b = mean_abs_ic[b]
                    # Drop recommendation: lower mean |IC| (tied → alphabetical stable)
                    if ic_a < ic_b or (ic_a == ic_b and a < b):
                        drop, keep = a, b
                    else:
                        drop, keep = b, a
                    pairs.append(
                        {
                            "factor_a": a,
                            "factor_b": b,
                            "correlation": round(corr, 4),
                            "ic_a_mean_abs": round(ic_a, 6),
                            "ic_b_mean_abs": round(ic_b, 6),
                            "drop_recommendation": drop,
                            "reason": (
                                f"|corr|={abs(corr):.4f} >= threshold={threshold}; "
                                f"mean_abs_ic({drop})={mean_abs_ic[drop]:.6f} < "
                                f"mean_abs_ic({keep})={mean_abs_ic[keep]:.6f} — "
                                f"recommend drop {drop}"
                            ),
                        }
                    )

        logger.info(
            "[FactorService] analyze_correlation_prune: "
            f"threshold={threshold}, active={len(available)}, "
            f"pairs_above_threshold={len(pairs)}, dry_run={dry_run}"
        )

        return {
            "threshold_used": threshold,
            "lookback_days_used": lookback_days,
            "pairs": pairs,
            "dropped_count": len(pairs),
            "total_pairs_above_threshold": len(pairs),
            "computed_at": datetime.utcnow().isoformat() + "Z",
        }

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
