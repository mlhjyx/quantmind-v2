"""Pipeline API Router — AI因子挖掘Pipeline编排接口。

提供Pipeline运行状态查询、历史记录、人工审批等端点。

端点列表:
  GET  /api/pipeline/status                       — 当前Pipeline运行状态
  GET  /api/pipeline/runs                         — 运行历史（分页）
  GET  /api/pipeline/runs/{run_id}                — 单次运行详情
  POST /api/pipeline/runs/{run_id}/approve/{id}   — 审批通过候选因子
  POST /api/pipeline/runs/{run_id}/reject/{id}    — 审批拒绝候选因子

设计文档:
  - docs/DEV_AI_EVOLUTION.md §4: Pipeline完整流程
  - docs/GP_CLOSED_LOOP_DESIGN.md §6.2: 人工审批后的处理
  - docs/DEV_BACKEND.md: FastAPI Depends注入规范

ruff noqa: B008 — FastAPI Depends() in default args is the standard pattern.
"""
# ruff: noqa: B008

from __future__ import annotations

import structlog
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


def _require_local(request: Request) -> None:
    """审批操作仅允许从本机访问（PT安全策略）。"""
    client_ip = request.client.host if request.client else ""
    if client_ip not in _LOCALHOST_IPS:
        raise HTTPException(status_code=403, detail="审批操作仅允许本机访问")

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    """审批通过请求体。"""

    decision_reason: str | None = Field(
        default=None,
        description="审批理由（可选）",
    )


class RejectRequest(BaseModel):
    """审批拒绝请求体。"""

    decision_reason: str = Field(
        description="拒绝理由（必填，用于GP下轮学习）",
        min_length=5,
    )


class PipelineStatusResponse(BaseModel):
    """Pipeline状态响应。"""

    active_run_id: str | None
    active_engine: str | None
    status: str
    current_node: str | None
    node_statuses: dict[str, str]
    progress: dict[str, int]
    started_at: str | None
    error: str | None


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    summary="当前Pipeline运行状态",
    response_model=dict[str, Any],
)
async def get_pipeline_status(
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询当前活跃Pipeline的运行状态（8节点状态 + 进度）。

    返回最近一条 status='running' 的 pipeline_runs 记录。
    若无运行中任务则返回最近完成的记录。

    Returns:
        包含节点状态、进度计数、当前节点名称的完整状态对象。
    """
    # 优先查 running 状态，无则查最近完成
    row = await _fetch_latest_run(session, status_filter="running")
    if row is None:
        row = await _fetch_latest_run(session, status_filter=None)

    if row is None:
        return {
            "active_run_id": None,
            "active_engine": None,
            "status": "idle",
            "current_node": None,
            "node_statuses": {},
            "progress": {},
            "started_at": None,
            "error": None,
            "message": "无Pipeline运行记录",
        }

    stats: dict[str, Any] = row["stats"] or {}
    config: dict[str, Any] = row["config"] or {}

    return {
        "active_run_id": row["run_id"],
        "active_engine": row["engine"],
        "status": row["status"],
        "current_node": stats.get("current_node"),
        "node_statuses": stats.get("node_statuses", {}),
        "progress": {
            "total_candidates": stats.get("total_evaluated", 0),
            "passed_gate": stats.get("passed_gate", 0),
            "pending_approval": stats.get("pending_approval", 0),
        },
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "error": row["error_message"],
        "config_summary": {
            "generations": config.get("generations"),
            "population": config.get("population"),
            "time_budget_minutes": config.get("time_budget_minutes"),
        },
    }


@router.get(
    "/runs",
    summary="Pipeline运行历史",
    response_model=list[dict[str, Any]],
)
async def list_pipeline_runs(
    page: int = Query(default=1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    engine: str | None = Query(default=None, description="按引擎过滤: gp/bruteforce/llm"),
    status: str | None = Query(default=None, description="按状态过滤: running/completed/failed"),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """查询Pipeline运行历史列表（分页，按started_at降序）。

    Args:
        page: 页码，从1开始。
        page_size: 每页条数，最大100。
        engine: 可选引擎过滤。
        status: 可选状态过滤。

    Returns:
        运行记录列表，每条含 run_id/engine/status/stats摘要/耗时。
    """
    conditions = []
    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    if engine:
        conditions.append("engine_type = :engine")
        params["engine"] = engine
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await session.execute(
        text(
            f"""
            SELECT run_id, engine_type AS engine, started_at, finished_at, status,
                   result_summary AS stats, error_message,
                   EXTRACT(EPOCH FROM (COALESCE(finished_at, NOW()) - started_at))::int
                     AS elapsed_seconds
            FROM pipeline_runs
            {where_clause}
            ORDER BY started_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    rows = list(result.mappings().all())

    return [
        {
            "run_id": r["run_id"],
            "engine": r["engine"],
            "status": r["status"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "elapsed_seconds": r["elapsed_seconds"],
            "stats": r["stats"] or {},
            "error_message": r["error_message"],
        }
        for r in rows
    ]


@router.get(
    "/runs/{run_id}",
    summary="单次Pipeline运行详情",
    response_model=dict[str, Any],
)
async def get_pipeline_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询单次Pipeline运行的完整详情，含每个节点的结果和所有候选因子状态。

    Args:
        run_id: Pipeline运行ID，格式如 gp_2026w14_abc123。

    Returns:
        完整运行记录，含 approval_queue 中的候选因子列表。

    Raises:
        404: run_id 不存在。
    """
    # 查 pipeline_runs 主记录
    run_result = await session.execute(
        text(
            """
            SELECT run_id, engine_type AS engine, started_at, finished_at, status,
                   config, result_summary AS stats, error_message
            FROM pipeline_runs
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id},
    )
    run_row = run_result.mappings().first()
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"run_id={run_id!r} 不存在")

    # 查该 run 的候选因子（approval_queue）
    aq_result = await session.execute(
        text(
            """
            SELECT id, factor_name, factor_expr, ast_hash,
                   gate_result, sharpe_1y, sharpe_5y,
                   backtest_report, status,
                   decision_by, decision_reason,
                   created_at, decided_at
            FROM approval_queue
            WHERE run_id = :run_id
            ORDER BY created_at ASC
            """
        ),
        {"run_id": run_id},
    )
    aq_rows = list(aq_result.mappings().all())

    candidates = [
        {
            "id": r["id"],
            "factor_name": r["factor_name"],
            "factor_expr": r["factor_expr"],
            "ast_hash": r["ast_hash"],
            "gate_result": r["gate_result"],
            "sharpe_1y": float(r["sharpe_1y"]) if r["sharpe_1y"] is not None else None,
            "sharpe_5y": float(r["sharpe_5y"]) if r["sharpe_5y"] is not None else None,
            "backtest_report": r["backtest_report"],
            "status": r["status"],
            "decision_by": r["decision_by"],
            "decision_reason": r["decision_reason"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
        }
        for r in aq_rows
    ]

    return {
        "run_id": run_row["run_id"],
        "engine": run_row["engine"],
        "status": run_row["status"],
        "started_at": run_row["started_at"].isoformat() if run_row["started_at"] else None,
        "finished_at": run_row["finished_at"].isoformat() if run_row["finished_at"] else None,
        "config": run_row["config"],
        "stats": run_row["stats"],
        "error_message": run_row["error_message"],
        "candidates": candidates,
        "candidates_count": {
            "total": len(candidates),
            "pending": sum(1 for c in candidates if c["status"] == "pending"),
            "approved": sum(1 for c in candidates if c["status"] == "approved"),
            "rejected": sum(1 for c in candidates if c["status"] == "rejected"),
        },
    }


@router.post(
    "/runs/{run_id}/approve/{factor_id}",
    summary="审批通过候选因子",
    response_model=dict[str, Any],
)
async def approve_factor(
    run_id: str,
    factor_id: int,
    body: ApproveRequest,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> dict[str, Any]:
    """人工审批通过候选因子，写入 approval_queue.status='approved'。

    审批后的后续操作（因子代码写入factor_engine、历史回填等）
    由人工触发 /api/factors/activate 端点完成（GP_CLOSED_LOOP §6.2）。

    Args:
        run_id: Pipeline运行ID。
        factor_id: approval_queue 表主键 id。
        body: 审批理由（可选）。

    Returns:
        更新后的审批记录。

    Raises:
        404: factor_id 不存在或不属于该 run_id。
        409: 因子已经被审批过（非pending状态）。
    """
    row = await _fetch_approval_item(session, run_id, factor_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"factor_id={factor_id} 在 run_id={run_id!r} 中不存在",
        )

    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"因子已被审批（status={row['status']!r}），无法重复操作",
        )

    await session.execute(
        text(
            """
            UPDATE approval_queue
            SET status = 'approved',
                decision_by = 'user',
                decision_reason = :reason,
                decided_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": factor_id, "reason": body.decision_reason},
    )
    await session.commit()

    logger.info(
        "因子审批通过: run_id=%s, factor_id=%d, factor_name=%s",
        run_id,
        factor_id,
        row["factor_name"],
    )

    # 触发因子入库 Celery 异步任务
    # factor_onboarding_task 接收 approval_queue.id，入库完成后更新 factor_registry
    onboarding_task_id: str | None = None
    try:
        task = celery_app.send_task(
            "app.tasks.onboarding_tasks.onboard_factor",
            kwargs={"approval_queue_id": factor_id},
            queue="default",
        )
        onboarding_task_id = task.id
        logger.info(
            "因子入库任务已提交: approval_queue_id=%d, task_id=%s",
            factor_id,
            onboarding_task_id,
        )
    except Exception as exc:
        # 入库任务提交失败不回滚审批结果（非阻断）
        logger.error(
            "因子入库任务提交失败（审批结果已保存）: factor_id=%d, error=%s",
            factor_id,
            exc,
        )

    return {
        "success": True,
        "factor_id": factor_id,
        "factor_name": row["factor_name"],
        "factor_expr": row["factor_expr"],
        "status": "approved",
        "decision_reason": body.decision_reason,
        "onboarding_task_id": onboarding_task_id,
        "message": (
            f"因子已审批通过，入库任务已提交（task_id={onboarding_task_id}）。"
            if onboarding_task_id
            else "因子已审批通过，但入库任务提交失败，请手动触发 /api/factors/activate。"
        ),
    }


@router.post(
    "/runs/{run_id}/reject/{factor_id}",
    summary="审批拒绝候选因子",
    response_model=dict[str, Any],
)
async def reject_factor(
    run_id: str,
    factor_id: int,
    body: RejectRequest,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> dict[str, Any]:
    """人工审批拒绝候选因子，写入 approval_queue.status='rejected'。

    拒绝理由会被 GP 下一轮进化读取，注入搜索约束（GP_CLOSED_LOOP §6.2）。

    Args:
        run_id: Pipeline运行ID。
        factor_id: approval_queue 表主键 id。
        body: 拒绝理由（必填）。

    Returns:
        更新后的审批记录。

    Raises:
        404: factor_id 不存在或不属于该 run_id。
        409: 因子已经被审批过（非pending状态）。
    """
    row = await _fetch_approval_item(session, run_id, factor_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"factor_id={factor_id} 在 run_id={run_id!r} 中不存在",
        )

    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"因子已被审批（status={row['status']!r}），无法重复操作",
        )

    await session.execute(
        text(
            """
            UPDATE approval_queue
            SET status = 'rejected',
                decision_by = 'user',
                decision_reason = :reason,
                decided_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": factor_id, "reason": body.decision_reason},
    )

    # 同步写入 mining_knowledge（供GP下轮学习）
    await _sync_rejection_to_knowledge(session, row, body.decision_reason)

    await session.commit()

    logger.info(
        "因子审批拒绝: run_id=%s, factor_id=%d, factor_name=%s, reason=%s",
        run_id,
        factor_id,
        row["factor_name"],
        body.decision_reason,
    )

    return {
        "success": True,
        "factor_id": factor_id,
        "factor_name": row["factor_name"],
        "factor_expr": row["factor_expr"],
        "status": "rejected",
        "decision_reason": body.decision_reason,
        "message": "因子已拒绝，拒绝理由已写入mining_knowledge供下轮GP参考。",
    }


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


async def _fetch_latest_run(
    session: AsyncSession,
    status_filter: str | None,
) -> Any | None:
    """查询最新的pipeline_runs记录。"""
    where = "WHERE status = :status" if status_filter else ""
    params: dict[str, Any] = {"status": status_filter} if status_filter else {}

    result = await session.execute(
        text(
            f"""
            SELECT run_id, engine_type AS engine, started_at, finished_at, status,
                   config, result_summary AS stats, error_message
            FROM pipeline_runs
            {where}
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        params,
    )
    return result.mappings().first()


async def _fetch_approval_item(
    session: AsyncSession,
    run_id: str,
    factor_id: int,
) -> Any | None:
    """查询 approval_queue 中指定 run_id + id 的记录。"""
    result = await session.execute(
        text(
            """
            SELECT id, run_id, factor_name, factor_expr, ast_hash, status
            FROM approval_queue
            WHERE id = :id AND run_id = :run_id
            """
        ),
        {"id": factor_id, "run_id": run_id},
    )
    return result.mappings().first()


async def _sync_rejection_to_knowledge(
    session: AsyncSession,
    aq_row: Any,
    decision_reason: str,
) -> None:
    """将人工拒绝记录同步写入 mining_knowledge（非阻断，失败只记录日志）。"""
    import json

    try:
        await session.execute(
            text(
                """
                INSERT INTO mining_knowledge
                    (run_id, factor_name, factor_expr, ast_hash,
                     status, rejection_reason, created_at)
                VALUES
                    (:run_id, :factor_name, :factor_expr, :ast_hash,
                     'rejected', :rejection_reason, NOW())
                ON CONFLICT (ast_hash) DO UPDATE
                    SET rejection_reason = EXCLUDED.rejection_reason,
                        status = 'rejected'
                """
            ),
            {
                "run_id": aq_row["run_id"],
                "factor_name": aq_row["factor_name"],
                "factor_expr": aq_row["factor_expr"],
                "ast_hash": aq_row["ast_hash"],
                "rejection_reason": json.dumps(
                    {"source": "human_review", "reason": decision_reason}
                ),
            },
        )
    except Exception as exc:
        logger.warning("同步rejection到mining_knowledge失败（非阻断）: %s", exc)
