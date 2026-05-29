"""Pipeline API Router — AI因子挖掘Pipeline编排接口。

提供Pipeline运行状态查询、历史记录、人工审批等端点。

端点列表:
  GET  /api/pipeline/status                       — 当前Pipeline运行状态
  GET  /api/pipeline/{run_id}/logs                — 决策日志HTTP回放
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

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services.mining_service import MiningService
from app.services.pipeline_log import emit_pipeline_log, pipeline_log_key
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}
_PIPELINE_STALE_DEFAULT_MINUTES = 24 * 60
_PIPELINE_STALE_BUDGET_MULTIPLIER = 3


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


class TriggerPipelineRequest(BaseModel):
    """手动触发 Pipeline 的请求体 (DEV_AI_EVOLUTION §12.2)。"""

    engine: str = Field(
        default="gp",
        description="挖掘引擎: gp / bruteforce / llm",
        pattern="^(gp|bruteforce|llm)$",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="引擎配置 (generations/population/islands/time_budget_minutes 等)",
    )


class TriggerPipelineResponse(BaseModel):
    """手动触发 Pipeline 的响应。"""

    run_id: str
    task_id: str
    engine: str
    status: str


class CancelPipelineResponse(BaseModel):
    """取消 Pipeline 运行的响应。"""

    task_id: str
    run_id: str
    cancelled: bool
    message: str


class PipelineLogEntry(BaseModel):
    """Pipeline 决策日志条目 (PN-005 HTTP backfill contract)."""

    id: str
    run_id: str
    timestamp: str
    agent: str
    level: Literal["info", "warning", "error", "decision"]
    content: str


# ---------------------------------------------------------------------------
# D1 O8 — Automation-level persistence (PN-001 iter 10)
# ---------------------------------------------------------------------------

AutomationLevel = Literal["L0", "L1", "L2", "L3", "L4"]


class AutomationLevelRequest(BaseModel):
    """Pipeline automation-level 更新请求体 (D1 O8, PN-001)。"""

    level: AutomationLevel = Field(
        ...,
        description="自动化级别 (L4R spec L0-L4 enum)",
    )


class AutomationLevelResponse(BaseModel):
    """Pipeline automation-level 响应。"""

    level: AutomationLevel = Field(
        ...,
        description="当前 / 更新后的自动化级别",
    )


# ---------------------------------------------------------------------------
# D1 O3 — Pipeline pause gate (PN-003 iter 12, 2026-05-23/24)
# ---------------------------------------------------------------------------


class PauseRequest(BaseModel):
    """Pipeline pause 请求体 (D1 O3, PN-003)。"""

    reason: str | None = Field(
        default=None,
        max_length=500,
        description="可选暂停理由 (UI 显示用, ≤500 字符)",
    )


class PauseStatusResponse(BaseModel):
    """Pipeline pause 状态响应 (pause / resume 共用)。"""

    paused_at: str | None = Field(
        default=None,
        description="ISO8601 时间戳; NULL = active",
    )
    paused_reason: str | None = Field(
        default=None,
        description="暂停理由 (若已设置)",
    )


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


def _get_pipeline_log_redis() -> Any:
    """Return a Redis client for pipeline log backfill.

    Kept as a tiny helper so tests can monkeypatch it without opening a real
    Redis connection.
    """
    import redis as redis_lib  # noqa: PLC0415

    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def _coerce_pipeline_log_entry(
    raw: str | bytes, *, run_id: str, fallback_id: str
) -> PipelineLogEntry | None:
    """Decode one Redis log line into the frontend contract."""
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        timestamp = str(
            payload.get("timestamp") or payload.get("ts") or datetime.now(UTC).isoformat()
        )
        level = str(payload.get("level") or "info").lower()
        if level == "warn":
            level = "warning"
        if level not in {"info", "warning", "error", "decision"}:
            level = "info"
        return PipelineLogEntry(
            id=str(payload.get("id") or fallback_id),
            run_id=str(payload.get("run_id") or run_id),
            timestamp=timestamp,
            agent=str(payload.get("agent") or payload.get("source") or "pipeline"),
            level=cast(Literal["info", "warning", "error", "decision"], level),
            content=str(payload.get("content") or payload.get("message") or ""),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("pipeline_log_decode_failed", run_id=run_id, error=str(exc))
        return None


@router.post(
    "/trigger",
    summary="手动触发 Pipeline (DEV_AI_EVOLUTION §12.2)",
    response_model=TriggerPipelineResponse,
    status_code=202,
)
async def trigger_pipeline(
    body: TriggerPipelineRequest,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> TriggerPipelineResponse:
    """手动提交一次因子挖掘 Pipeline 运行 (PipelineConsole 触发入口)。

    委托 MiningService.start_mining_task — 校验引擎 / 防同引擎并发 (铁律 9
    资源仲裁) / 写 pipeline_runs / 提交 Celery 任务。资源密集操作, 仅允许
    本机访问 (沿用 approve/reject 的 _require_local 安全策略)。

    Args:
        body: 引擎类型 + 引擎配置。

    Returns:
        TriggerPipelineResponse: run_id / task_id / engine / status。

    Raises:
        400: engine 非法。
        409: 同引擎任务已在运行 (防资源竞争)。
    """
    svc = MiningService(session)
    try:
        result = await svc.start_mining_task(engine=body.engine, config=body.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    emit_pipeline_log(
        run_id=result["run_id"],
        agent="orchestrator",
        level="decision",
        content=f"Pipeline submitted: engine={body.engine}, task_id={result['task_id']}",
    )

    return TriggerPipelineResponse(
        run_id=result["run_id"],
        task_id=result["task_id"],
        engine=body.engine,
        status=result["status"],
    )


@router.post(
    "/runs/{run_id}/cancel",
    summary="取消 Pipeline 运行",
    response_model=CancelPipelineResponse,
)
async def cancel_pipeline_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> CancelPipelineResponse:
    """Cancel a running Pipeline row via the existing MiningService path.

    This is intentionally explicit and localhost-only. It lets operators close
    stale `running` rows without hiding a DB mutation behind GET /status.
    """
    svc = MiningService(session)
    try:
        result = await svc.cancel_task(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    emit_pipeline_log(
        run_id=result["run_id"],
        agent="orchestrator",
        level="decision",
        content=f"Pipeline cancelled: run_id={result['run_id']}",
    )
    return CancelPipelineResponse(**result)


@router.get(
    "/{run_id}/logs",
    summary="Pipeline 决策日志 HTTP backfill (PN-005 O7)",
    response_model=list[PipelineLogEntry],
)
async def get_pipeline_logs(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=1000, description="最多返回日志条数"),
) -> list[PipelineLogEntry]:
    """Return recent pipeline decision logs from Redis.

    PN-005 chose Redis list storage for the first closure step:
    `pipeline:logs:{run_id}` contains JSON-encoded `PipelineLogEntry` rows,
    newest first. Missing Redis key is a valid empty state for older runs.
    Redis transport failure is fail-soft because logs are observability-only;
    the endpoint logs a warning and returns an empty list instead of breaking
    the Operator UI tab.
    """
    key = pipeline_log_key(run_id)
    try:
        raw_entries = _get_pipeline_log_redis().lrange(key, 0, limit - 1)
    except Exception as exc:  # noqa: BLE001 — fail-soft observability path, warning emitted.
        logger.warning("pipeline_log_redis_read_failed", run_id=run_id, key=key, error=str(exc))
        return []

    entries: list[PipelineLogEntry] = []
    for idx, raw in enumerate(raw_entries):
        entry = _coerce_pipeline_log_entry(raw, run_id=run_id, fallback_id=f"{run_id}:{idx}")
        if entry is not None:
            entries.append(entry)
    return entries


@router.get(
    "/automation-level",
    summary="读取当前 pipeline 自动化级别 (D1 O8, PN-001)",
    response_model=AutomationLevelResponse,
)
async def get_automation_level(
    session: AsyncSession = Depends(get_db),
) -> AutomationLevelResponse:
    """读取 pipeline_settings singleton 的 automation_level (D1 O8, PN-001).

    防御性默认: 表无 row (migration 未跑) → 返回 'L0'。
    """
    result = await session.execute(
        text("SELECT automation_level FROM pipeline_settings WHERE id = 1")
    )
    row = result.first()
    if row is None:
        return AutomationLevelResponse(level="L0")
    return AutomationLevelResponse(level=row[0])


@router.put(
    "/automation-level",
    summary="设置 pipeline 自动化级别 (D1 O8, PN-001)",
    response_model=AutomationLevelResponse,
)
async def set_automation_level(
    body: AutomationLevelRequest,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> AutomationLevelResponse:
    """更新 pipeline_settings singleton 的 automation_level (D1 O8, PN-001).

    仅本机访问 (沿用 trigger/approve/reject 的 _require_local 体例)。
    Pydantic Literal 自动 422 invalid level。
    UPSERT (CONFLICT-DO-UPDATE) — 表 singleton, 永远 id=1。
    """
    await session.execute(
        text(
            "INSERT INTO pipeline_settings (id, automation_level) "
            "VALUES (1, :level) "
            "ON CONFLICT (id) DO UPDATE SET automation_level = EXCLUDED.automation_level"
        ),
        {"level": body.level},
    )
    await session.commit()
    # Audit trail for the mutation (P3-5 review fix) — single-row pipeline UI
    # setting change is worth one info line, matches sibling mutating endpoints.
    logger.info("pipeline_automation_level_set", new_level=body.level)
    return AutomationLevelResponse(level=body.level)


# ---------------------------------------------------------------------------
# D1 O3 pause / resume endpoints (PN-003 iter 12)
# ---------------------------------------------------------------------------


async def _read_pause_state(
    session: AsyncSession,
) -> tuple[Any, str | None]:
    """读取 pipeline_settings 当前 pause 状态 (paused_at, paused_reason).

    Returns:
        (paused_at, paused_reason) — paused_at 为 datetime | None.
        表无 row → (None, None) — 与 PN-001 防御性默认对齐。
    """
    result = await session.execute(
        text("SELECT paused_at, paused_reason FROM pipeline_settings WHERE id = 1")
    )
    row = result.first()
    if row is None:
        return (None, None)
    return (row[0], row[1])


async def _read_automation_level(session: AsyncSession) -> str:
    """读取 pipeline_settings.automation_level (PN-004 iter 15 helper).

    Sibling of `_read_pause_state` + the PN-001 GET /automation-level endpoint.
    Returns 'L0' default when table is empty (PN-001 defensive default).
    """
    result = await session.execute(
        text("SELECT automation_level FROM pipeline_settings WHERE id = 1")
    )
    row = result.first()
    if row is None:
        return "L0"
    return row[0]


def _gp_weekly_schedule_next() -> tuple[str, str]:
    """Return (cron_str, next_run_iso_utc) for the gp-weekly-mining Beat task.

    D1 PN-004 iter 15 helper. Hardcoded for the only Beat-driven pipeline task
    post-PMS removal — `app/tasks/beat_schedule.py:53` SSOT
    (`crontab(hour=22, minute=0, day_of_week="0")`, i.e. Sunday 22:00 SH).

    China does not observe DST → SH UTC offset is permanently +08:00, so the
    stdlib-only datetime math here is exact (no croniter dep needed).

    Returns:
        ("0 22 * * 0", ISO8601 UTC of the next Sunday 22:00 SH).
    """
    SH = timezone(timedelta(hours=8))
    now_sh = datetime.now(tz=SH)
    days_ahead = (6 - now_sh.weekday()) % 7  # Sunday weekday() == 6
    target = now_sh.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if target <= now_sh:
        target += timedelta(days=7)
    return ("0 22 * * 0", target.astimezone(UTC).isoformat())


def _pipeline_stale_after_minutes(config: dict[str, Any]) -> int:
    """Return stale-running threshold for a mining run.

    The GP task has a hard Celery limit near 3h, but status is operator-facing.
    A 24h floor avoids mislabeling unusually slow manual experiments while still
    catching rows that would otherwise block the weekly pipeline indefinitely.
    """
    raw_budget = config.get("time_budget_minutes")
    try:
        budget_minutes = float(raw_budget)
    except (TypeError, ValueError):
        budget_minutes = 0.0
    if budget_minutes <= 0:
        return _PIPELINE_STALE_DEFAULT_MINUTES
    return int(
        max(
            _PIPELINE_STALE_DEFAULT_MINUTES,
            budget_minutes * _PIPELINE_STALE_BUDGET_MULTIPLIER,
        )
    )


def _running_stale_info(
    *,
    status: str,
    started_at: datetime | None,
    config: dict[str, Any],
    now: datetime | None = None,
) -> tuple[bool, int | None, str | None]:
    """Classify stale `running` rows without mutating DB state."""
    if status != "running" or started_at is None:
        return (False, None, None)

    now_utc = now or datetime.now(UTC)
    started_utc = started_at
    if started_utc.tzinfo is None:
        started_utc = started_utc.replace(tzinfo=UTC)
    else:
        started_utc = started_utc.astimezone(UTC)

    stale_after_minutes = _pipeline_stale_after_minutes(config)
    age = now_utc - started_utc
    if age <= timedelta(minutes=stale_after_minutes):
        return (False, stale_after_minutes, None)

    age_hours = age.total_seconds() / 3600
    reason = (
        f"running for {age_hours:.1f}h exceeds stale threshold "
        f"{stale_after_minutes}m; operator cancel/retry required"
    )
    return (True, stale_after_minutes, reason)


@router.post(
    "/pause",
    summary="暂停 Pipeline gate-at-entry (D1 O3, PN-003)",
    response_model=PauseStatusResponse,
)
async def pause_pipeline(
    body: PauseRequest | None = None,
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> PauseStatusResponse:
    """设置 pipeline_settings.paused_at = NOW() — gate-at-entry 暂停。

    语义 (PN-003 §3):
      - paused_at IS NULL → set NOW() + reason (从 body, 可空).
      - paused_at IS NOT NULL → idempotent NO-overwrite — 不刷新 paused_at,
        不覆盖 paused_reason (防止双击意外覆盖原因).
    后续 POST /trigger 返回 409 / Beat 调度跳过, 直到 /resume 调用.
    当前运行中任务 NOT aborted (mid-run cooperative abort 显式 out of scope).
    """
    body = body or PauseRequest()

    paused_at, paused_reason = await _read_pause_state(session)

    if paused_at is not None:
        # Idempotent — return current state, do not overwrite
        return PauseStatusResponse(
            paused_at=paused_at.isoformat() if hasattr(paused_at, "isoformat") else str(paused_at),
            paused_reason=paused_reason,
        )

    # Not paused yet — insert/update with reason
    await session.execute(
        text(
            "INSERT INTO pipeline_settings (id, automation_level, paused_at, paused_reason) "
            "VALUES (1, 'L0', NOW(), :reason) "
            "ON CONFLICT (id) DO UPDATE SET paused_at = NOW(), paused_reason = EXCLUDED.paused_reason"
        ),
        {"reason": body.reason},
    )
    await session.commit()

    # Re-read to get the actual NOW() timestamp the DB assigned
    new_paused_at, new_reason = await _read_pause_state(session)
    logger.info("pipeline_paused", paused_reason=body.reason)
    return PauseStatusResponse(
        paused_at=new_paused_at.isoformat() if new_paused_at is not None else None,
        paused_reason=new_reason,
    )


@router.post(
    "/resume",
    summary="恢复 Pipeline (清除 pause 状态) (D1 O3, PN-003)",
    response_model=PauseStatusResponse,
)
async def resume_pipeline(
    session: AsyncSession = Depends(get_db),
    _local: None = Depends(_require_local),
) -> PauseStatusResponse:
    """清除 pipeline_settings.paused_at — 下次 Beat / /trigger 正常执行。

    Idempotent: 已 active (paused_at IS NULL) 时 noop, 返回 NULL 状态。
    """
    await session.execute(
        text(
            "INSERT INTO pipeline_settings (id, automation_level, paused_at, paused_reason) "
            "VALUES (1, 'L0', NULL, NULL) "
            "ON CONFLICT (id) DO UPDATE SET paused_at = NULL, paused_reason = NULL"
        )
    )
    await session.commit()
    logger.info("pipeline_resumed")
    return PauseStatusResponse(paused_at=None, paused_reason=None)


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

    PN-004 contract notes (P2-2 review clarification):
        `last_run_at` is `finished_at ?? started_at` of the latest run row.
        When `is_running=True` this surfaces the **currently-running run's
        start time**, not a previous run's completion. Frontend consumers
        should read `is_running` + `last_run_at` together: running=true →
        "started at"; running=false → "last completed at".

    Returns:
        包含节点状态、进度计数、当前节点名称的完整状态对象 + PN-004
        frontend-aligned keys (run_id/is_running/is_paused/automation_level/
        nodes/schedule_cron/next_run_at/last_run_at).
    """
    # 优先查 running 状态，无则查最近完成
    row = await _fetch_latest_run(session, status_filter="running")
    if row is None:
        row = await _fetch_latest_run(session, status_filter=None)

    # D1 O3 (PN-003 iter 12) — surface pause state alongside run status
    paused_at, paused_reason = await _read_pause_state(session)
    paused_at_iso = paused_at.isoformat() if paused_at is not None else None
    # D1 PN-004 iter 15 — frontend-aligned derived fields
    automation_level = await _read_automation_level(session)
    schedule_cron, next_run_at = _gp_weekly_schedule_next()
    is_paused = paused_at is not None

    if row is None:
        return {
            # NEW frontend-aligned keys (PN-004)
            "run_id": None,
            "is_running": False,
            "is_paused": is_paused,
            "automation_level": automation_level,
            "nodes": [],
            "schedule_cron": schedule_cron,
            "next_run_at": next_run_at,
            "last_run_at": None,
            "is_stale_running": False,
            "stale_after_minutes": None,
            "stale_reason": None,
            "current_node": None,
            "paused_at": paused_at_iso,
            "paused_reason": paused_reason,
            # LEGACY aliases (deprecated, 1-sprint retention per PN-004 §2.2)
            "active_run_id": None,
            "active_engine": None,
            "status": "idle",
            "node_statuses": {},
            "progress": {},
            "started_at": None,
            "error": None,
            "message": "无Pipeline运行记录",
        }

    stats: dict[str, Any] = row["stats"] or {}
    config: dict[str, Any] = row["config"] or {}
    # Map node_statuses dict → ordered array for frontend FlowChart consumer
    node_statuses_dict = stats.get("node_statuses") or {}
    nodes_list = [{"name": k, "status": v} for k, v in node_statuses_dict.items()]
    # last_run_at: prefer finished_at (completed run); fall back to started_at
    last_run_dt = row["finished_at"] or row["started_at"]
    last_run_iso = last_run_dt.isoformat() if last_run_dt else None
    is_running = row["status"] == "running"
    is_stale_running, stale_after_minutes, stale_reason = _running_stale_info(
        status=row["status"],
        started_at=row["started_at"],
        config=config,
    )
    status_label = "stale_running" if is_stale_running else row["status"]

    return {
        # NEW frontend-aligned keys (PN-004)
        "run_id": row["run_id"],
        "is_running": is_running,
        "is_paused": is_paused,
        "automation_level": automation_level,
        "current_node": stats.get("current_node"),
        "nodes": nodes_list,
        "schedule_cron": schedule_cron,
        "next_run_at": next_run_at,
        "last_run_at": last_run_iso,
        "is_stale_running": is_stale_running,
        "stale_after_minutes": stale_after_minutes,
        "stale_reason": stale_reason,
        "paused_at": paused_at_iso,
        "paused_reason": paused_reason,
        # LEGACY aliases (deprecated, 1-sprint retention per PN-004 §2.2)
        "active_run_id": row["run_id"],
        "active_engine": row["engine"],
        "status": status_label,
        "node_statuses": node_statuses_dict,
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
    emit_pipeline_log(
        run_id=run_id,
        agent="approval",
        level="decision",
        content=f"Approved factor {row['factor_name']} (id={factor_id})",
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
    emit_pipeline_log(
        run_id=run_id,
        agent="approval",
        level="decision",
        content=f"Rejected factor {row['factor_name']} (id={factor_id}): {body.decision_reason}",
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
