"""策略管理 API 路由。

提供策略列表、详情、版本创建和版本回滚。
CLAUDE.md: strategy_configs.config 是 JSONB，每次变更插入新 version 行。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _get_strategy_service(
    session: AsyncSession = Depends(get_db),
) -> StrategyService:
    """通过 Depends 注入 StrategyService。"""
    return StrategyService(session)


class CreateVersionRequest(BaseModel):
    """创建新配置版本的请求体。"""

    config: dict[str, Any] = Field(..., description="新版本配置(JSONB)")
    changelog: str = Field(..., min_length=1, description="变更说明")


class RollbackRequest(BaseModel):
    """回滚版本的请求体。"""

    target_version: int = Field(..., ge=1, description="目标版本号")


@router.get("")
async def list_strategies(
    market: str = Query(default="", description="市场筛选: a_share/forex"),
    status: str = Query(default="", description="状态筛选: active/paused/retired"),
    svc: StrategyService = Depends(_get_strategy_service),
) -> list[dict[str, Any]]:
    """获取策略列表。

    支持按市场和状态筛选。

    Args:
        market: 市场类型，为空时不筛选。
        status: 策略状态，为空时不筛选。

    Returns:
        策略列表，每项含 id/name/market/status/active_version/created_at。
    """
    return await svc.strategy_repo.list_strategies(
        market=market or None, status=status or None
    )


@router.get("/{strategy_id}")
async def get_strategy_detail(
    strategy_id: str,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """获取策略详情（基本信息 + 当前配置 + 版本历史）。

    Args:
        strategy_id: 策略ID。

    Returns:
        策略详情字典，含 strategy/active_config/version_history。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    detail = await svc.get_strategy_detail(strategy_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
    return detail


@router.post("/{strategy_id}/versions")
async def create_strategy_version(
    strategy_id: str,
    body: CreateVersionRequest,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """创建新配置版本。

    每次变更插入新 version 行，不更新旧行。新版本自动成为当前激活版本。

    Args:
        strategy_id: 策略ID。
        body: 包含 config(JSONB) 和 changelog(变更说明) 的请求体。

    Returns:
        新版本信息，含 version/strategy_id/changelog。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    try:
        return await svc.create_version(strategy_id, body.config, body.changelog)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{strategy_id}/rollback")
async def rollback_strategy_version(
    strategy_id: str,
    body: RollbackRequest,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """回滚到指定版本。

    回滚 = 把 active_version 指回旧版本号，不删除任何版本记录。

    Args:
        strategy_id: 策略ID。
        body: 包含 target_version(目标版本号) 的请求体。

    Returns:
        回滚结果，含 strategy_id/rolled_back_to/previous_version。

    Raises:
        HTTPException: 策略不存在或目标版本无效时返回 400/404。
    """
    try:
        return await svc.rollback(strategy_id, body.target_version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
