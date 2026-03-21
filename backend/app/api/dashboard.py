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
