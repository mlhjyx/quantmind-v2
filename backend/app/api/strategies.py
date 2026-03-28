"""策略管理 API 路由。

提供策略CRUD、版本管理、因子查询、回测触发。
CLAUDE.md: strategy_configs.config 是 JSONB，每次变更插入新 version 行。

ruff noqa: B008 — FastAPI Depends() in default args is the standard pattern.
"""
# ruff: noqa: B008

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


class CreateStrategyRequest(BaseModel):
    """创建策略的请求体。"""

    name: str = Field(..., min_length=1, description="策略名称")
    market: str = Field(..., description="市场类型: astock/forex")
    config: dict[str, Any] = Field(default_factory=dict, description="策略初始配置(JSONB)")
    factor_names: list[str] = Field(default_factory=list, description="因子名称列表")


class UpdateStrategyRequest(BaseModel):
    """更新策略配置的请求体。"""

    name: str | None = Field(default=None, description="策略名称")
    status: str | None = Field(default=None, description="状态: active/paused/draft/archived")
    factor_config: dict[str, Any] | None = Field(default=None, description="因子配置(JSONB)")
    backtest_config: dict[str, Any] | None = Field(default=None, description="回测配置(JSONB)")


class CreateVersionRequest(BaseModel):
    """创建新配置版本的请求体。"""

    config: dict[str, Any] = Field(..., description="新版本配置(JSONB)")
    changelog: str = Field(..., min_length=1, description="变更说明")


class RollbackRequest(BaseModel):
    """回滚版本的请求体。"""

    target_version: int = Field(..., ge=1, description="目标版本号")


class TriggerBacktestRequest(BaseModel):
    """触发回测的请求体。"""

    start_date: str = Field(..., description="回测开始日期(YYYY-MM-DD)")
    end_date: str = Field(..., description="回测结束日期(YYYY-MM-DD)")
    top_n: int = Field(default=15, ge=1, le=100, description="选股数量")
    rebalance_freq: str = Field(
        default="monthly", description="调仓频率: daily/weekly/biweekly/monthly"
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="其他回测参数")


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
    return await svc.strategy_repo.list_strategies(market=market or None, status=status or None)


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
        raise HTTPException(status_code=404, detail=str(e)) from e


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
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("")
async def create_strategy(
    body: CreateStrategyRequest,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """创建新策略。

    Args:
        body: 包含 name/market/config/factor_names 的请求体。

    Returns:
        新策略信息，含 strategy_id/name/market/status。
    """
    return await svc.create_strategy(
        name=body.name,
        market=body.market,
        config=body.config,
        factor_names=body.factor_names,
    )


@router.put("/{strategy_id}")
async def update_strategy(
    strategy_id: str,
    body: UpdateStrategyRequest,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """更新策略配置。

    Args:
        strategy_id: 策略ID。
        body: 待更新字段（name/status/factor_config/backtest_config）。

    Returns:
        更新结果，含 strategy_id/updated。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return await svc.update_strategy(strategy_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: str,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """软删除策略（status → 'archived'）。

    Args:
        strategy_id: 策略ID。

    Returns:
        删除结果，含 strategy_id/archived。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    try:
        return await svc.delete_strategy(strategy_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{strategy_id}/factors")
async def get_strategy_factors(
    strategy_id: str,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """获取策略关联因子及分类信息。

    Args:
        strategy_id: 策略ID。

    Returns:
        因子列表，含 strategy_id/factor_names/factors（每项含 name/category/direction/ic_decay_halflife）。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    result = await svc.get_strategy_factors(strategy_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
    return result


@router.post("/{strategy_id}/backtest")
async def trigger_strategy_backtest(
    strategy_id: str,
    body: TriggerBacktestRequest,
    svc: StrategyService = Depends(_get_strategy_service),
) -> dict[str, Any]:
    """触发策略回测（异步Celery任务）。

    Args:
        strategy_id: 策略ID。
        body: 回测配置（start_date/end_date/top_n/rebalance_freq/extra）。

    Returns:
        回测提交结果，含 strategy_id/run_id。

    Raises:
        HTTPException: 策略不存在时返回 404。
    """
    config = {
        "start_date": body.start_date,
        "end_date": body.end_date,
        "top_n": body.top_n,
        "rebalance_freq": body.rebalance_freq,
        **body.extra,
    }
    try:
        return await svc.trigger_backtest(strategy_id, config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
