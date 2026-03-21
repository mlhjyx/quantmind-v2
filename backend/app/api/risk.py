"""风控API路由 — 熔断状态查询、L4审批。

Sprint 1.1: 4级熔断风控。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.notification_service import NotificationService
from app.services.risk_control_service import RiskControlService

router = APIRouter(prefix="/api/risk", tags=["risk"])


# ── 依赖注入 ──


def _get_risk_service(
    session: AsyncSession = Depends(get_db),
) -> RiskControlService:
    """通过 Depends 注入 RiskControlService。"""
    notification_svc = NotificationService(session)
    return RiskControlService(session, notification_svc)


def _parse_uuid(value: str, label: str = "ID") -> UUID:
    """解析UUID字符串，无效时抛HTTPException。"""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"无效的{label}: {value}"
        ) from None


# ── 请求体 ──


class L4RecoveryRequest(BaseModel):
    """L4恢复审批请求体。"""

    reviewer_note: str = Field(
        ..., min_length=1, description="审批请求说明(为什么认为可以恢复)"
    )


class L4ApproveRequest(BaseModel):
    """L4审批决策请求体。"""

    approved: bool = Field(..., description="是否批准")
    reviewer_note: str = Field(default="", description="审批意见")


class ForceResetRequest(BaseModel):
    """强制重置请求体。"""

    reason: str = Field(..., min_length=1, description="强制重置原因(必填, 用于审计)")


# ── 路由 ──


@router.get("/state/{strategy_id}")
async def get_risk_state(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """获取当前熔断状态。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。

    Returns:
        当前熔断状态，含 level/can_rebalance/position_multiplier 等。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    state = await svc.get_current_state(sid, execution_mode)
    return {
        "level": state.level.value,
        "level_name": state.level.name,
        "entered_date": state.entered_date.isoformat(),
        "trigger_reason": state.trigger_reason,
        "trigger_metrics": state.trigger_metrics,
        "position_multiplier": float(state.position_multiplier),
        "can_rebalance": state.can_rebalance,
        "recovery_streak_days": state.recovery_streak_days,
        "recovery_streak_return": float(state.recovery_streak_return),
        "requires_manual_approval": state.requires_manual_approval,
    }


@router.get("/history/{strategy_id}")
async def get_risk_history(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    limit: int = Query(default=50, ge=1, le=200, description="最大返回条数"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> list[dict[str, Any]]:
    """获取熔断状态变更历史。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。
        limit: 最大条数。

    Returns:
        变更历史列表(最新在前)。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    transitions = await svc.get_transition_history(sid, execution_mode, limit)
    return [
        {
            "trade_date": t.trade_date.isoformat(),
            "prev_level": t.prev_level.value,
            "new_level": t.new_level.value,
            "transition_type": t.transition_type.value,
            "reason": t.reason,
            "metrics": t.metrics,
        }
        for t in transitions
    ]


@router.get("/summary/{strategy_id}")
async def get_risk_summary(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """获取风控概览摘要。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。

    Returns:
        风控概览，含 current_level/days_in_current_state/total_escalations 等。
    """
    sid = _parse_uuid(strategy_id, "策略ID")
    return await svc.get_risk_summary(sid, execution_mode)


@router.post("/l4-recovery/{strategy_id}")
async def request_l4_recovery(
    strategy_id: str,
    body: L4RecoveryRequest,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """发起L4人工审批恢复请求。

    前置条件: 当前状态必须是L4_STOPPED。

    Args:
        strategy_id: 策略ID。
        body: 包含 reviewer_note 的请求体。
        execution_mode: 执行模式。

    Returns:
        含 approval_id 的字典。

    Raises:
        HTTPException: 不在L4状态时返回400。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    try:
        approval_id = await svc.request_l4_recovery(
            sid, execution_mode, body.reviewer_note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return {"approval_id": str(approval_id), "status": "pending"}


@router.post("/l4-approve/{approval_id}")
async def approve_l4_recovery(
    approval_id: str,
    body: L4ApproveRequest,
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """审批L4恢复请求。

    Args:
        approval_id: approval_queue记录ID。
        body: 包含 approved 和 reviewer_note 的请求体。

    Returns:
        审批结果，通过时含新状态，拒绝时含 status='rejected'。
    """
    aid = _parse_uuid(approval_id, "审批ID")

    state = await svc.approve_l4_recovery(aid, body.approved, body.reviewer_note)

    if state is None:
        return {"status": "rejected", "approval_id": approval_id}

    return {
        "status": "approved",
        "approval_id": approval_id,
        "new_state": {
            "level": state.level.value,
            "level_name": state.level.name,
            "position_multiplier": float(state.position_multiplier),
        },
    }


@router.post("/force-reset/{strategy_id}")
async def force_reset(
    strategy_id: str,
    body: ForceResetRequest,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """强制重置到NORMAL状态(运维用)。

    仅限运维紧急情况使用，会记录审计日志。

    Args:
        strategy_id: 策略ID。
        body: 包含 reason 的请求体。
        execution_mode: 执行模式。

    Returns:
        重置后状态。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    state = await svc.force_reset(sid, execution_mode, body.reason)
    return {
        "level": state.level.value,
        "level_name": state.level.name,
        "trigger_reason": state.trigger_reason,
        "position_multiplier": float(state.position_multiplier),
    }
