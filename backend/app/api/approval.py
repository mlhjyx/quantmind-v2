"""审批队列 API 路由。

提供 GP/BruteForce/LLM 因子挖掘Pipeline产出的因子人工审批功能。

操作的表: gp_approval_queue（域12）
与域11 approval_queue区分:
  - 域11: AI进化闭环审批（factor_entry/strategy_deploy/param_change 等多类型）
  - 域12 gp_approval_queue: 专用于3引擎产出的单个因子审批

设计文档:
  - docs/DEV_AI_EVOLUTION.md §四: Pipeline完整流程 + 审批机制（决策#33）
  - docs/QUANTMIND_V2_DDL_FINAL.sql 域12: gp_approval_queue表

端点列表:
  GET  /api/approval/queue                   — 待审批因子列表 (status=pending)
  GET  /api/approval/queue/{id}              — 单因子审批详情
  POST /api/approval/queue/{id}/approve      — 批准
  POST /api/approval/queue/{id}/reject       — 拒绝
  POST /api/approval/queue/{id}/hold         — 暂缓（需要更多数据）
  GET  /api/approval/history                 — 审批历史（approved/rejected/hold）

ruff noqa: B008 — FastAPI Depends() in default args is the standard pattern.
"""
# ruff: noqa: B008

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.approval_queue import GPApprovalQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval", tags=["approval"])


# ---------------------------------------------------------------------------
# Depends 工厂
# ---------------------------------------------------------------------------


def _get_db(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    return session


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class ApprovalActionRequest(BaseModel):
    """审批动作（approve/reject/hold）请求体。"""

    reviewer_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="审批备注",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=500,
        description="拒绝原因（仅 reject 动作使用）",
    )
    reviewed_by: str = Field(
        default="user",
        max_length=50,
        description="审批人标识: 'user' | 'auto' | agent名称",
    )


class ApprovalQueueItem(BaseModel):
    """审批队列单项响应。"""

    id: int
    run_id: str
    factor_name: str
    factor_expr: str
    ast_hash: str
    status: str
    created_at: str
    reviewed_at: str | None
    reviewed_by: str | None
    reviewer_notes: str | None

    @classmethod
    def from_orm(cls, row: GPApprovalQueue) -> ApprovalQueueItem:
        return cls(
            id=row.id,
            run_id=str(row.run_id),
            factor_name=row.factor_name,
            factor_expr=row.factor_expr,
            ast_hash=row.ast_hash,
            status=row.status,
            created_at=row.created_at.isoformat(),
            reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
            reviewed_by=row.reviewed_by,
            reviewer_notes=row.reviewer_notes,
        )


class ApprovalQueueDetail(ApprovalQueueItem):
    """审批队列详情（含 gate_report）。"""

    gate_report: dict[str, Any]

    @classmethod
    def from_orm(cls, row: GPApprovalQueue) -> ApprovalQueueDetail:  # type: ignore[override]
        return cls(
            id=row.id,
            run_id=str(row.run_id),
            factor_name=row.factor_name,
            factor_expr=row.factor_expr,
            ast_hash=row.ast_hash,
            status=row.status,
            created_at=row.created_at.isoformat(),
            reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
            reviewed_by=row.reviewed_by,
            reviewer_notes=row.reviewer_notes,
            gate_report=row.gate_report,
        )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _get_queue_item(
    item_id: int,
    session: AsyncSession,
) -> GPApprovalQueue:
    """按 id 查询审批条目，不存在则抛 404。"""
    stmt = (
        select(GPApprovalQueue)
        .options(selectinload(GPApprovalQueue.pipeline_run))
        .where(GPApprovalQueue.id == item_id)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"审批条目不存在: id={item_id}")
    return row


async def _apply_action(
    item_id: int,
    new_status: str,
    body: ApprovalActionRequest,
    session: AsyncSession,
) -> dict[str, Any]:
    """执行审批状态变更（approve/reject/hold 共用逻辑）。"""
    row = await _get_queue_item(item_id, session)

    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"条目已审批完成 (status={row.status})，无法重复操作",
        )

    notes = body.reviewer_notes or ""
    if new_status == "rejected" and body.rejection_reason:
        notes = f"[拒绝原因] {body.rejection_reason}" + (f"\n{notes}" if notes else "")

    row.status = new_status
    row.reviewer_notes = notes or None
    row.reviewed_by = body.reviewed_by
    row.reviewed_at = datetime.now(tz=UTC)

    await session.commit()
    await session.refresh(row)

    logger.info(
        "approval_action item_id=%d factor=%s status=%s reviewer=%s",
        item_id,
        row.factor_name,
        new_status,
        body.reviewed_by,
    )

    return {
        "id": row.id,
        "factor_name": row.factor_name,
        "status": row.status,
        "reviewed_at": row.reviewed_at.isoformat(),
        "reviewed_by": row.reviewed_by,
        "reviewer_notes": row.reviewer_notes,
    }


# ---------------------------------------------------------------------------
# GET /api/approval/queue — 待审批列表
# ---------------------------------------------------------------------------


@router.get("/queue", response_model=list[ApprovalQueueItem])
async def list_pending_queue(
    limit: int = Query(default=50, ge=1, le=200, description="最多返回条数"),
    session: AsyncSession = Depends(_get_db),
) -> list[ApprovalQueueItem]:
    """返回 status=pending 的因子审批列表，按 created_at 升序（先进先审）。

    Args:
        limit: 最多返回条数，默认50。

    Returns:
        待审批因子列表，不含 gate_report（减少传输量，详情用 /{id} 查）。
    """
    stmt = (
        select(GPApprovalQueue)
        .where(GPApprovalQueue.status == "pending")
        .order_by(GPApprovalQueue.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [ApprovalQueueItem.from_orm(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/approval/queue/{id} — 单因子详情
# ---------------------------------------------------------------------------


@router.get("/queue/{item_id}", response_model=ApprovalQueueDetail)
async def get_queue_item(
    item_id: int,
    session: AsyncSession = Depends(_get_db),
) -> ApprovalQueueDetail:
    """返回单个审批条目的完整详情，含 gate_report (G1-G8结果)。

    Args:
        item_id: gp_approval_queue.id

    Returns:
        完整审批详情含 gate_report JSONB。

    Raises:
        HTTPException 404: 条目不存在。
    """
    row = await _get_queue_item(item_id, session)
    return ApprovalQueueDetail.from_orm(row)


# ---------------------------------------------------------------------------
# POST /api/approval/queue/{id}/approve — 批准
# ---------------------------------------------------------------------------


@router.post("/queue/{item_id}/approve")
async def approve_queue_item(
    item_id: int,
    body: ApprovalActionRequest,
    session: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """批准因子进入因子库。

    将 status 更新为 approved，记录审批人和备注。
    后续由 FactorService 负责将批准的因子写入 factor_registry。

    Args:
        item_id: gp_approval_queue.id
        body: reviewer_notes（可选）+ reviewed_by（默认'user'）

    Returns:
        {id, factor_name, status, reviewed_at, reviewed_by, reviewer_notes}

    Raises:
        HTTPException 404: 条目不存在。
        HTTPException 409: 条目已完成审批（非 pending）。
    """
    return await _apply_action(item_id, "approved", body, session)


# ---------------------------------------------------------------------------
# POST /api/approval/queue/{id}/reject — 拒绝
# ---------------------------------------------------------------------------


@router.post("/queue/{item_id}/reject")
async def reject_queue_item(
    item_id: int,
    body: ApprovalActionRequest,
    session: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """拒绝因子，记录拒绝原因。

    将 status 更新为 rejected。rejection_reason 会附加到 reviewer_notes 前缀。
    拒绝的因子不会进入 factor_registry，但保留在队列供分析。

    Args:
        item_id: gp_approval_queue.id
        body: rejection_reason（建议填写）+ reviewer_notes + reviewed_by

    Returns:
        {id, factor_name, status, reviewed_at, reviewed_by, reviewer_notes}

    Raises:
        HTTPException 404: 条目不存在。
        HTTPException 409: 条目已完成审批（非 pending）。
    """
    return await _apply_action(item_id, "rejected", body, session)


# ---------------------------------------------------------------------------
# POST /api/approval/queue/{id}/hold — 暂缓
# ---------------------------------------------------------------------------


@router.post("/queue/{item_id}/hold")
async def hold_queue_item(
    item_id: int,
    body: ApprovalActionRequest,
    session: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """暂缓审批，需要更多数据或分析后再决定。

    将 status 更新为 hold。hold 状态的因子不会在 /queue 中出现（pending过滤），
    但可在 /history 中查询。

    Args:
        item_id: gp_approval_queue.id
        body: reviewer_notes（说明暂缓原因）+ reviewed_by

    Returns:
        {id, factor_name, status, reviewed_at, reviewed_by, reviewer_notes}

    Raises:
        HTTPException 404: 条目不存在。
        HTTPException 409: 条目已完成审批（非 pending）。
    """
    return await _apply_action(item_id, "hold", body, session)


# ---------------------------------------------------------------------------
# GET /api/approval/history — 审批历史
# ---------------------------------------------------------------------------


@router.get("/history")
async def get_approval_history(
    status: str = Query(
        default="",
        description="按状态筛选: approved/rejected/hold，空=全部非pending",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="最多返回条数"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
    session: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """返回审批历史（approved + rejected + hold），支持分页和状态筛选。

    Args:
        status: 状态筛选，空=全部历史（非pending）。
        limit: 最多返回条数，默认50。
        offset: 分页偏移，默认0。

    Returns:
        {total: int, items: list[ApprovalQueueDetail]}
    """
    # 构建过滤条件
    if status and status in ("approved", "rejected", "hold"):
        status_filter = GPApprovalQueue.status == status
    else:
        # 非pending的全部历史
        status_filter = GPApprovalQueue.status != "pending"

    # count
    from sqlalchemy import func as sa_func

    count_stmt = select(sa_func.count()).select_from(
        select(GPApprovalQueue).where(status_filter).subquery()
    )
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    # data
    data_stmt = (
        select(GPApprovalQueue)
        .where(status_filter)
        .order_by(GPApprovalQueue.reviewed_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    data_result = await session.execute(data_stmt)
    rows = data_result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [ApprovalQueueDetail.from_orm(r) for r in rows],
    }
