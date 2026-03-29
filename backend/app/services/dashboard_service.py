"""Dashboard Service — 聚合Dashboard所需数据。

整合 PerformanceRepository + PositionRepository + HealthRepository，
为前端Dashboard页面提供7个指标卡、NAV时间序列、待处理事项。
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.health_repository import HealthRepository
from app.repositories.market_data_repository import MarketDataRepository
from app.repositories.performance_repository import PerformanceRepository
from app.repositories.position_repository import PositionRepository


class DashboardService:
    """Dashboard数据聚合服务。

    通过FastAPI Depends注入session，聚合多个Repository的数据
    为前端Dashboard页面提供完整视图。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.perf_repo = PerformanceRepository(session)
        self.pos_repo = PositionRepository(session)
        self.health_repo = HealthRepository(session)
        self.market_repo = MarketDataRepository(session)

    async def get_summary(
        self, strategy_id: str, execution_mode: str = "paper"
    ) -> dict[str, Any]:
        """获取Dashboard 7个指标卡数据。

        返回NAV、Sharpe、MDD、持仓数、日收益、累计收益、现金比。

        Args:
            strategy_id: 策略ID。
            execution_mode: 执行模式，"paper"或"live"。

        Returns:
            包含7个指标的字典：
            - nav: 最新净值
            - sharpe: 滚动Sharpe（近60天）
            - mdd: 最大回撤
            - position_count: 当前持仓数
            - daily_return: 最新日收益率
            - cumulative_return: 累计收益率
            - cash_ratio: 现金占比
        """
        latest = await self.perf_repo.get_latest_nav(strategy_id, execution_mode)
        rolling = await self.perf_repo.get_rolling_stats(
            strategy_id, lookback_days=60, execution_mode=execution_mode
        )

        if not latest:
            return {
                "nav": 0,
                "sharpe": 0,
                "mdd": 0,
                "position_count": 0,
                "daily_return": 0,
                "cumulative_return": 0,
                "cash_ratio": 0,
                "trade_date": None,
            }

        return {
            "nav": latest["nav"],
            "sharpe": rolling["sharpe"] if rolling else 0,
            "mdd": rolling["mdd"] if rolling else 0,
            "position_count": latest["position_count"],
            "daily_return": latest["daily_return"],
            "cumulative_return": latest["cumulative_return"],
            "cash_ratio": latest["cash_ratio"],
            "trade_date": latest["trade_date"],
        }

    async def get_nav_series(
        self,
        strategy_id: str,
        period: str = "3m",
        execution_mode: str = "paper",
    ) -> list[dict[str, Any]]:
        """获取NAV时间序列。

        Args:
            strategy_id: 策略ID。
            period: 时间周期，支持 "1m"/"3m"/"6m"/"1y"/"all"。
            execution_mode: 执行模式。

        Returns:
            NAV时间序列，每项包含 trade_date/nav/daily_return/cumulative_return/drawdown。
        """
        start_date = self._resolve_period_start(period)
        return await self.perf_repo.get_nav_series(
            strategy_id,
            start_date=start_date,
            execution_mode=execution_mode,
        )

    async def get_pending_actions(
        self, strategy_id: str
    ) -> list[dict[str, Any]]:
        """获取待处理事项（熔断/健康异常/管道失败）。

        聚合健康检查失败项、熔断事件、管道任务异常，
        供Dashboard待处理事项面板展示。

        Args:
            strategy_id: 策略ID。

        Returns:
            待处理事项列表，每项包含 type/severity/message/time。
            type: "health"/"circuit_breaker"/"pipeline"
            severity: "critical"/"warning"/"info"
        """
        actions: list[dict[str, Any]] = []

        # 1. 健康检查失败项
        health = await self.health_repo.get_latest_health()
        if health and not health["all_pass"]:
            failed = health.get("failed_items") or []
            actions.append({
                "type": "health",
                "severity": "critical",
                "message": f"健康检查未通过: {', '.join(failed) if isinstance(failed, list) else str(failed)}",
                "time": health["check_date"],
            })

        # 2. 熔断事件（最近7天）
        breakers = await self.health_repo.get_circuit_breaker_history(
            strategy_id, days=7
        )
        for b in breakers:
            actions.append({
                "type": "circuit_breaker",
                "severity": "critical" if b["action"] == "stop" else "warning",
                "message": f"熔断触发: {b.get('reason', '未知原因')}",
                "time": b["time"],
            })

        # 3. 管道任务失败（当日）
        today = date.today()
        pipeline = await self.health_repo.get_pipeline_status(today)
        for task in pipeline:
            if task["status"] in ("failed", "error"):
                actions.append({
                    "type": "pipeline",
                    "severity": "warning",
                    "message": f"任务失败: {task['task_name']} - {task.get('error', '')}",
                    "time": task.get("start_time"),
                })

        return actions

    async def get_market_ticker(self) -> list[dict[str, Any]]:
        """获取市场行情栏数据（沪深300/上证/创业板/成交额）。

        Returns:
            list[dict]: 每项含 label/code/value/change_pct/is_up。
        """
        return await self.market_repo.get_market_ticker()

    async def get_alerts(self, hours: int = 24) -> list[dict[str, Any]]:
        """获取活跃预警列表（P0-P2，未读 + 最近24h）。

        Args:
            hours: 查询时间窗口（小时），默认24。

        Returns:
            list[dict]: 每项含 level/title/desc/time/color。
        """
        return await self.health_repo.get_active_alerts(hours=hours)

    async def get_strategies_overview(self) -> list[dict[str, Any]]:
        """获取所有策略概览（name/status/market/sharpe/pnl/mdd）。

        Returns:
            list[dict]: 策略列表，最新绩效通过LATERAL JOIN附加。
        """
        return await self.perf_repo.get_strategies_overview()

    async def get_monthly_returns(
        self,
        strategy_id: str,
        execution_mode: str = "paper",
    ) -> dict[int, list[float | None]]:
        """获取月度收益矩阵。

        Args:
            strategy_id: 策略ID。
            execution_mode: 执行模式。

        Returns:
            dict[int, list]: {year: [jan, feb, ..., dec]}。
        """
        sid = strategy_id
        return await self.perf_repo.get_monthly_returns(sid, execution_mode)

    async def get_industry_distribution(
        self,
        strategy_id: str,
        execution_mode: str = "paper",
    ) -> list[dict[str, Any]]:
        """获取当前持仓行业分布（饼图数据）。

        Args:
            strategy_id: 策略ID。
            execution_mode: 执行模式。

        Returns:
            list[dict]: 每项含 name/pct/color。
        """
        return await self.pos_repo.get_industry_distribution(
            strategy_id, execution_mode
        )

    @staticmethod
    def _resolve_period_start(period: str) -> date | None:
        """将周期字符串转换为起始日期。

        Args:
            period: 周期标识，支持 "1m"/"3m"/"6m"/"1y"/"all"。

        Returns:
            起始日期，"all"时返回None表示不限制。
        """
        today = date.today()
        mapping: dict[str, int] = {
            "1m": 30,
            "3m": 90,
            "6m": 180,
            "1y": 365,
        }
        days = mapping.get(period)
        if days is None:
            return None  # "all" 或未知周期，不限制起始日期
        return today - timedelta(days=days)
