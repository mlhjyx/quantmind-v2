"""健康检查 API 路由。

提供系统健康状态查询和历史健康检查记录。
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.repositories.health_repository import HealthRepository
from app.services.qmt_connection_manager import qmt_manager

router = APIRouter(prefix="/api/health", tags=["health"])


def _get_health_repo(session: AsyncSession = Depends(get_db)) -> HealthRepository:
    """通过 Depends 注入 HealthRepository。"""
    return HealthRepository(session)


@router.get("")
async def health_status(
    repo: HealthRepository = Depends(_get_health_repo),
) -> dict[str, Any]:
    """获取系统健康状态。

    返回最新一次全链路健康预检结果，包含各组件状态和总体是否通过。

    Returns:
        健康状态字典，包含各检查项布尔值和 all_pass 总体状态。
    """
    latest = await repo.get_latest_health()
    if not latest:
        return {
            "status": "unknown",
            "message": "暂无健康检查记录",
        }
    return {
        "status": "ok" if latest["all_pass"] else "degraded",
        "check_date": latest["check_date"],
        "checks": {
            "postgresql": latest["postgresql_ok"],
            "redis": latest["redis_ok"],
            "data_fresh": latest["data_fresh"],
            "factor_nan": latest["factor_nan_ok"],
            "disk": latest["disk_ok"],
            "celery": latest["celery_ok"],
        },
        "all_pass": latest["all_pass"],
        "failed_items": latest["failed_items"],
    }


@router.get("/checks")
async def health_check_history(
    repo: HealthRepository = Depends(_get_health_repo),
) -> dict[str, Any]:
    """获取历史健康检查记录。

    返回最新健康检查和当日管道任务状态。

    Returns:
        包含 latest_health 和 pipeline_status 的字典。
    """
    from datetime import date

    latest = await repo.get_latest_health()
    pipeline = await repo.get_pipeline_status(date.today())

    return {
        "latest_health": latest,
        "pipeline_status": pipeline,
    }


@router.get("/qmt")
async def qmt_health() -> dict[str, Any]:
    """获取QMT连接健康状态。

    返回QMT连接管理器的当前状态，包含连接状态、账户信息等。
    EXECUTION_MODE=paper时返回disabled状态。

    Returns:
        QMT连接状态字典。
    """
    return qmt_manager.health_check()
