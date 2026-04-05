"""因子挖掘 API 路由。

提供 GP/BruteForce/LLM 挖掘任务的提交、查询、取消和候选因子评估。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 完整闭环流程
  - docs/DEV_BACKEND.md: Service层+FastAPI Depends注入规范
  - docs/IMPLEMENTATION_MASTER.md Sprint 1.17

端点列表:
  POST /api/mining/run                   — 启动挖掘任务
  GET  /api/mining/tasks                 — 任务列表（含状态/进度）
  GET  /api/mining/tasks/{task_id}       — 单任务详情
  POST /api/mining/tasks/{task_id}/cancel — 取消运行中任务
  POST /api/mining/evaluate              — 对候选因子触发Gate评估

ruff noqa: B008 — FastAPI Depends() in default args is the standard pattern.
"""
# ruff: noqa: B008

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.mining_service import MiningService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/mining", tags=["mining"])


# ---------------------------------------------------------------------------
# Depends 工厂
# ---------------------------------------------------------------------------


def _get_mining_service(
    session: AsyncSession = Depends(get_db),
) -> MiningService:
    """通过 Depends 注入 MiningService。"""
    return MiningService(session)


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class RunMiningRequest(BaseModel):
    """启动挖掘任务的请求体。"""

    engine: str = Field(
        default="gp",
        description="挖掘引擎: gp / bruteforce / llm",
        pattern="^(gp|bruteforce|llm)$",
    )
    generations: int = Field(
        default=50,
        ge=1,
        le=500,
        description="GP进化代数（仅 engine=gp 时有效）",
    )
    population: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="每岛种群大小（仅 engine=gp 时有效）",
    )
    islands: int = Field(
        default=3,
        ge=1,
        le=8,
        description="岛屿数量（仅 engine=gp 时有效）",
    )
    time_budget_minutes: float = Field(
        default=120.0,
        ge=1.0,
        le=360.0,
        description="时间预算（分钟）",
    )
    extra_config: dict[str, Any] = Field(
        default_factory=dict,
        description="额外引擎配置（JSONB）",
    )


class RunMiningResponse(BaseModel):
    """启动挖掘任务的响应。"""

    task_id: str
    run_id: str
    engine: str
    status: str
    message: str


class EvaluateFactorRequest(BaseModel):
    """候选因子 Gate 评估请求体。"""

    factor_expr: str = Field(
        ...,
        min_length=1,
        description="因子DSL表达式，如 ts_mean(cs_rank(close), 20)",
    )
    factor_name: str | None = Field(
        default=None,
        description="可选名称，未填则自动生成 gp_<hash8>",
    )
    run_quick_only: bool = Field(
        default=False,
        description="True=只跑快速Gate G1-G4，False=完整Gate G1-G8",
    )


# ---------------------------------------------------------------------------
# POST /api/mining/run
# ---------------------------------------------------------------------------


@router.post("/run", response_model=RunMiningResponse, status_code=202)
async def run_mining(
    body: RunMiningRequest,
    svc: MiningService = Depends(_get_mining_service),
) -> RunMiningResponse:
    """启动因子挖掘任务。

    提交后立即返回 task_id，前端通过 GET /tasks/{task_id} 轮询进度。
    任务在 Celery Worker 中异步执行（asyncio.run 包装）。

    Args:
        body: 引擎类型 + 配置参数。

    Returns:
        RunMiningResponse: 含 task_id/run_id/engine/status。

    Raises:
        HTTPException 400: 参数非法。
        HTTPException 409: 同引擎任务已在运行。
    """
    try:
        result = await svc.start_mining_task(
            engine=body.engine,
            config={
                "generations": body.generations,
                "population": body.population,
                "islands": body.islands,
                "time_budget_minutes": body.time_budget_minutes,
                **body.extra_config,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 已有同引擎任务在运行
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RunMiningResponse(
        task_id=result["task_id"],
        run_id=result["run_id"],
        engine=body.engine,
        status=result["status"],
        message=f"{body.engine.upper()} 挖掘任务已提交，task_id={result['task_id']}",
    )


# ---------------------------------------------------------------------------
# GET /api/mining/tasks
# ---------------------------------------------------------------------------


@router.get("/tasks")
async def list_mining_tasks(
    engine: str = Query(default="", description="按引擎筛选: gp/bruteforce/llm"),
    status: str = Query(default="", description="按状态筛选: running/completed/failed/timeout"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    svc: MiningService = Depends(_get_mining_service),
) -> list[dict[str, Any]]:
    """获取挖掘任务列表（含状态/进度）。

    按 started_at 降序排列，支持引擎和状态筛选。

    Args:
        engine: 引擎类型筛选，空=不筛选。
        status: 运行状态筛选，空=不筛选。
        limit: 最多返回条数，默认20。

    Returns:
        任务列表，每项含 run_id/engine/status/started_at/stats。
    """
    return await svc.list_tasks(
        engine=engine or None,
        status=status or None,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/mining/tasks/{task_id}
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}")
async def get_mining_task(
    task_id: str,
    svc: MiningService = Depends(_get_mining_service),
) -> dict[str, Any]:
    """获取单个挖掘任务详情。

    返回任务元信息 + GP运行统计 + 候选因子（含Gate结果）。
    前端可通过此接口轮询进度（running状态时 stats.n_generations_completed 递增）。

    Args:
        task_id: 任务ID（即 Celery task_id）。

    Returns:
        任务详情字典，含:
            - run_id: GP run ID
            - engine: 引擎类型
            - status: running/completed/failed/timeout
            - config: 引擎配置（JSONB）
            - stats: 运行统计（评估数/通过Gate数/最优适应度/耗时）
            - candidates: 候选因子列表（含Gate结果，status=completed后可用）

    Raises:
        HTTPException 404: task_id 不存在。
    """
    detail = await svc.get_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return detail


# ---------------------------------------------------------------------------
# POST /api/mining/tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


@router.post("/tasks/{task_id}/cancel")
async def cancel_mining_task(
    task_id: str,
    svc: MiningService = Depends(_get_mining_service),
) -> dict[str, Any]:
    """取消正在运行的挖掘任务。

    通过 Celery revoke 发送终止信号。已完成的任务取消无效。

    Args:
        task_id: 任务ID（即 Celery task_id）。

    Returns:
        {"task_id": str, "cancelled": bool, "message": str}

    Raises:
        HTTPException 404: task_id 不存在。
        HTTPException 400: 任务已完成，无法取消。
    """
    try:
        result = await svc.cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result


# ---------------------------------------------------------------------------
# POST /api/mining/evaluate
# ---------------------------------------------------------------------------


@router.post("/evaluate")
async def evaluate_factor(
    body: EvaluateFactorRequest,
    svc: MiningService = Depends(_get_mining_service),
) -> dict[str, Any]:
    """对候选因子触发 Gate 评估。

    可用于手动验证自定义 DSL 表达式，或对已有候选补跑完整 Gate G1-G8。

    Args:
        body: 因子DSL表达式 + 可选名称 + 是否只跑快速Gate。

    Returns:
        dict: 含 factor_name/factor_expr/gate_result/overall_passed/
              ic_mean/t_stat/elapsed_seconds。

    Raises:
        HTTPException 400: DSL 表达式非法或计算失败。
        HTTPException 503: 行情数据不可用（DB连接问题）。
    """
    try:
        result = await svc.evaluate_factor_gate(
            factor_expr=body.factor_expr,
            factor_name=body.factor_name,
            quick_only=body.run_quick_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return result
