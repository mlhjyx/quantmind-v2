"""Dashboard API 路由。

提供 Dashboard 页面所需的 7 指标卡、NAV 时间序列、待处理事项。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _get_dashboard_service(
    session: AsyncSession = Depends(get_db),
) -> DashboardService:
    """通过 Depends 注入 DashboardService。"""
    return DashboardService(session)


@router.get("/summary")
async def dashboard_summary(
    strategy_id: str = Query(default="", description="策略ID，为空时使用默认Paper策略"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> dict[str, Any]:
    """获取 Dashboard 7 指标卡数据。

    返回 NAV、Sharpe、MDD、持仓数、日收益、累计收益、现金比。

    Args:
        strategy_id: 策略ID。为空时使用配置中的 PAPER_STRATEGY_ID。
        execution_mode: 执行模式。

    Returns:
        7 个指标卡数据字典。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_summary(sid, execution_mode)


@router.get("/nav-series")
async def dashboard_nav_series(
    period: str = Query(default="3m", description="时间周期: 1m/3m/6m/1y/all"),
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取 NAV 时间序列。

    Args:
        period: 时间周期，支持 1m/3m/6m/1y/all。
        strategy_id: 策略ID。
        execution_mode: 执行模式。

    Returns:
        NAV 时间序列列表，每项含 trade_date/nav/daily_return/cumulative_return/drawdown。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_nav_series(sid, period, execution_mode)


@router.get("/pending-actions")
async def dashboard_pending_actions(
    strategy_id: str = Query(default="", description="策略ID"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取待处理事项（熔断/健康异常/管道失败）。

    Args:
        strategy_id: 策略ID。

    Returns:
        待处理事项列表，每项含 type/severity/message/time。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_pending_actions(sid)


@router.get("/market-ticker")
async def dashboard_market_ticker(
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取市场行情栏实时数据。

    读取 index_daily 最新日期的沪深300/上证/创业板行情，
    以及当日全市场 klines_daily 成交额汇总。

    Returns:
        list: 每项含 label/code/value/change_pct/is_up。
    """
    return await svc.get_market_ticker()


@router.get("/alerts")
async def dashboard_alerts(
    hours: int = Query(default=24, ge=1, le=168, description="时间窗口（小时）"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取活跃预警列表（P0-P2）。

    从 notifications 表读取未读记录或最近 hours 小时内的记录，
    按 level(P0>P1>P2>P3) 和时间倒序排列。

    Args:
        hours: 时间窗口，默认24小时，最大168小时（7天）。

    Returns:
        list: 每项含 level/title/desc/time/color。
    """
    return await svc.get_alerts(hours=hours)


@router.get("/strategies")
async def dashboard_strategies(
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取所有策略概览。

    从 strategy 表读取策略定义，通过 LATERAL JOIN 附加最新绩效数据
    (performance_series 最新一条)。

    Returns:
        list: 每项含 id/name/status/market/sharpe/pnl/mdd。
    """
    return await svc.get_strategies_overview()


@router.get("/monthly-returns")
async def dashboard_monthly_returns(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> dict[str, list[float | None]]:
    """获取月度收益矩阵。

    按年月聚合 performance_series.daily_return，
    返回 {year: [jan, feb, ..., dec]} 格式供前端热力图渲染。
    无数据的月份返回 null。

    Args:
        strategy_id: 策略ID。为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        dict: {year(str): [12个月收益或null]}，JSON key为字符串年份。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    raw = await svc.get_monthly_returns(sid, execution_mode)
    # JSON key必须为字符串
    return {str(yr): months for yr, months in raw.items()}


@router.get("/industry-distribution")
async def dashboard_industry_distribution(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> list[dict[str, Any]]:
    """获取当前持仓行业分布（饼图数据）。

    读取 position_snapshot 最新日期持仓，JOIN symbols.industry_sw1，
    按权重汇总后返回百分比和颜色。

    Args:
        strategy_id: 策略ID。为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        list: 每项含 name/pct/color，按权重降序排列。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_industry_distribution(sid, execution_mode)
