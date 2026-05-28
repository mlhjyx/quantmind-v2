"""系统管理 API 路由。

提供数据源状态、系统健康检查、调度任务状态等管理接口。
"""

import asyncio
import os
import platform
import subprocess
from collections.abc import Callable
from typing import Any

import psutil
import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

_HEALTH_DB_TIMEOUT_SEC = 3.0
_HEALTH_SYNC_TIMEOUT_SEC = 6.0

# ---------------------------------------------------------------------------
# 数据源状态配置（表名 → 显示名 + 日期字段）
# ---------------------------------------------------------------------------

_DATASOURCE_TABLE_CONFIG: list[dict[str, str]] = [
    {"name": "行情日线", "table": "klines_daily", "date_col": "trade_date"},
    {"name": "每日基本面", "table": "daily_basic", "date_col": "trade_date"},
    {"name": "因子值", "table": "factor_values", "date_col": "calc_date"},
    {"name": "股票估值", "table": "stock_valuation", "date_col": "trade_date"},
    {"name": "资金流向", "table": "moneyflow", "date_col": "trade_date"},
    {"name": "财务报表", "table": "financial_statements", "date_col": "report_date"},
    {"name": "每日信号", "table": "daily_signals", "date_col": "signal_date"},
    {"name": "回测记录", "table": "backtest_run", "date_col": "created_at"},
    {"name": "调度任务日志", "table": "scheduler_task_log", "date_col": "started_at"},
]

# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------


async def _query_datasource(session: AsyncSession, table: str, date_col: str) -> dict[str, Any]:
    """查询单张表的最新日期和行数。

    Args:
        session: 数据库会话。
        table: 表名。
        date_col: 日期/时间列名。

    Returns:
        包含 latest_date 和 row_count 的字典；查询失败时返回 None 值。
    """
    try:
        result = await session.execute(
            text(
                f"SELECT MAX({date_col})::text AS latest_date, COUNT(*) AS row_count"  # noqa: S608
                f" FROM {table}"
            )
        )
        row = result.fetchone()
        if row:
            return {"latest_date": row.latest_date, "row_count": int(row.row_count)}
        return {"latest_date": None, "row_count": 0}
    except Exception:
        logger.exception("查询数据源表 %s 状态失败", table)
        return {"latest_date": None, "row_count": None}


async def _check_pg(session: AsyncSession) -> dict[str, Any]:
    """检查 PostgreSQL 连接状态。

    Args:
        session: 数据库会话。

    Returns:
        包含 ok 布尔值和可选 error 字符串的字典。
    """
    try:
        await session.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        logger.exception("PostgreSQL连接检查失败")
        return {"ok": False, "error": str(exc)}


def _check_redis() -> dict[str, Any]:
    """检查 Redis 连接状态（同步，通过 redis-py ping）。

    Returns:
        包含 ok 布尔值和可选 error 字符串的字典。
    """
    try:
        r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        return {"ok": True}
    except Exception as exc:
        logger.exception("Redis连接检查失败")
        return {"ok": False, "error": str(exc)}


def _check_celery() -> dict[str, Any]:
    """通过 celery inspect ping 检查 worker 状态（同步子进程调用）。

    Returns:
        包含 ok 布尔值、worker_count 和可选 error 字符串的字典。
    """
    process_fallback = _check_celery_worker_processes()
    if platform.system() == "Windows" and process_fallback["worker_count"] > 0:
        return {
            "ok": True,
            **process_fallback,
            "method": "process_fallback",
            "warning": "celery inspect skipped for Windows solo worker",
        }

    try:
        result = subprocess.run(
            [
                "python",
                "-m",
                "celery",
                "-A",
                "app.tasks.celery_app",
                "inspect",
                "ping",
                "--timeout=3",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            cwd=str(_backend_dir()),
        )
        output = result.stdout + result.stderr
        # 有 pong 响应说明 worker 存活
        if "pong" in output.lower():
            # 统计存活 worker 数
            worker_count = output.lower().count("pong")
            return {"ok": True, "worker_count": worker_count, "method": "inspect"}
        if process_fallback["worker_count"] > 0:
            return {
                "ok": True,
                **process_fallback,
                "method": "process_fallback",
                "warning": "celery inspect returned no workers",
            }
        return {"ok": False, "worker_count": 0, "error": "No workers responded"}
    except subprocess.TimeoutExpired:
        if process_fallback["worker_count"] > 0:
            return {
                "ok": True,
                **process_fallback,
                "method": "process_fallback",
                "warning": "celery inspect timeout",
            }
        return {"ok": False, "worker_count": 0, "error": "inspect timeout"}
    except Exception as exc:
        logger.exception("Celery worker检查失败")
        return {"ok": False, "worker_count": 0, "error": str(exc)}


def _check_celery_worker_processes() -> dict[str, Any]:
    """Fallback worker liveness check for Windows solo-pool deployments.

    Celery remote control may fail to answer while the Servy-managed solo worker
    process is present. Count unique worker hostnames from running commands so
    the health endpoint exposes that distinction instead of collapsing it into
    "no worker".
    """
    workers: dict[str, dict[str, Any]] = {}
    process_count = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        cmd = " ".join(str(part) for part in cmdline)
        cmd_lower = cmd.lower()
        if " -m celery " not in f" {cmd_lower} ":
            continue
        if "app.tasks.celery_app" not in cmd_lower or " worker " not in f" {cmd_lower} ":
            continue
        if " inspect " in f" {cmd_lower} " or " status " in f" {cmd_lower} ":
            continue

        process_count += 1
        worker_name = _extract_celery_worker_name(cmdline) or f"pid:{proc.info['pid']}"
        workers.setdefault(worker_name, {"name": worker_name, "pid": proc.info["pid"]})

    return {
        "worker_count": len(workers),
        "process_count": process_count,
        "workers": list(workers.values()),
    }


def _extract_celery_worker_name(cmdline: list[str]) -> str | None:
    """Extract `-n worker@host` or `--hostname worker@host` from a Celery cmdline."""
    for idx, token in enumerate(cmdline):
        if token in {"-n", "--hostname"} and idx + 1 < len(cmdline):
            return cmdline[idx + 1]
        if token.startswith("--hostname="):
            return token.split("=", 1)[1]
    return None


async def _with_timeout(
    label: str,
    awaitable: Any,
    timeout_sec: float,
) -> dict[str, Any]:
    """Run a health sub-check with a bounded timeout."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_sec)
    except TimeoutError:
        logger.warning("system_health_check_timeout", check=label, timeout_sec=timeout_sec)
        return {"ok": False, "error": f"{label} check timeout"}


async def _run_sync_check(
    label: str,
    func: Callable[[], dict[str, Any]],
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Run a synchronous health check in the executor with a bounded timeout."""
    loop = asyncio.get_running_loop()
    result = await _with_timeout(
        label,
        loop.run_in_executor(None, func),
        _HEALTH_SYNC_TIMEOUT_SEC if timeout_sec is None else timeout_sec,
    )
    if not isinstance(result, dict):
        return {"ok": False, "error": f"{label} check returned invalid result"}
    return result


def _check_disk() -> dict[str, Any]:
    """检查项目所在磁盘剩余空间。

    Returns:
        包含 ok、free_gb、total_gb 的字典。CLAUDE.md 要求 >100GB。
    """
    try:
        usage = psutil.disk_usage("D:\\")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        return {
            "ok": free_gb > 100,
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_gb, 1),
        }
    except Exception as exc:
        logger.exception("磁盘空间检查失败")
        return {"ok": False, "free_gb": None, "total_gb": None, "error": str(exc)}


def _check_memory() -> dict[str, Any]:
    """检查系统内存使用情况。

    Returns:
        包含 ok、used_gb、available_gb、total_gb、percent 的字典。
        AGENTS.md 资源规则: RAM 可用 <8GB 时不启动重型任务。
    """
    try:
        vm = psutil.virtual_memory()
        used_gb = vm.used / (1024**3)
        available_gb = vm.available / (1024**3)
        total_gb = vm.total / (1024**3)
        return {
            "ok": available_gb >= 8,
            "used_gb": round(used_gb, 1),
            "available_gb": round(available_gb, 1),
            "total_gb": round(total_gb, 1),
            "percent": vm.percent,
        }
    except Exception as exc:
        logger.exception("内存使用检查失败")
        return {"ok": False, "used_gb": None, "total_gb": None, "error": str(exc)}


def _backend_dir() -> str:
    """返回 backend 目录绝对路径。"""
    return os.path.join(os.path.dirname(__file__), "..", "..")


def _query_task_scheduler() -> list[dict[str, Any]]:
    """通过 PowerShell 查询 Windows Task Scheduler 中 QM- 前缀任务。

    R6 §3.3: Task Scheduler 是主调度器，任务名前缀为 QM-。

    Returns:
        任务状态列表，每项包含 task_name、task_state、enabled、last_run、next_run、status。
    """
    if platform.system() != "Windows":
        return []
    try:
        ps_script = (
            "Get-ScheduledTask | Where-Object {$_.TaskName -like 'QM-*'} | "
            "ForEach-Object { "
            "$info = $_ | Get-ScheduledTaskInfo; "
            "[PSCustomObject]@{"
            "  Name=$_.TaskName; "
            "  State=$_.State.ToString(); "
            "  LastRun=$info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss'); "
            "  NextRun=$info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss'); "
            "  LastResult=$info.LastTaskResult"
            "}"
            "} | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        import json

        raw = json.loads(result.stdout.strip())
        # PowerShell 单个对象时返回 dict，多个时返回 list
        if isinstance(raw, dict):
            raw = [raw]
        tasks = []
        for item in raw:
            task_name = str(item.get("Name") or "")
            last_result = item.get("LastResult", 0)
            task_state = str(item.get("State") or "Unknown")
            status = _task_scheduler_status(task_name, task_state, last_result)
            tasks.append(
                {
                    "task_name": task_name,
                    "schedule": "",  # 简化：不解析 trigger 配置
                    "last_run": item.get("LastRun", ""),
                    "next_run": item.get("NextRun", ""),
                    "task_state": task_state,
                    "enabled": task_state.lower() != "disabled",
                    "status": status,
                    "last_result_code": last_result,
                    **_task_scheduler_disposition(task_name, status),
                }
            )
        return tasks
    except Exception:
        logger.exception("查询Windows Task Scheduler任务失败")
        return []


def _task_scheduler_status(task_name: str, task_state: str, last_result: int | None) -> str:
    """Map Windows task state and last result into operator-facing status."""
    normalized_state = task_state.lower()
    if normalized_state == "disabled":
        return "disabled"
    if normalized_state == "running":
        return "running"
    # Windows Task Scheduler: 0=成功, 267011=还未运行
    if last_result == 0:
        return "success"
    if last_result == 267011:
        return "never_run"
    if task_name == "QM-ICMonitor" and last_result == 1:
        return "alert"
    return "failed"


def _task_scheduler_disposition(task_name: str, status: str) -> dict[str, str | None]:
    """Return operator-facing next step metadata for non-infrastructure alerts."""
    if task_name == "QM-ICMonitor" and status == "alert":
        return {
            "status_reason": "IC factor-quality alert from scripts/ic_monitor.py",
            "operator_action_label": "Open IC monitoring",
            "operator_action_path": "/factors/monitoring",
        }
    return {
        "status_reason": None,
        "operator_action_label": None,
        "operator_action_path": None,
    }


def _beat_log_aliases(beat_key: str, task_name: str) -> set[str]:
    """Return scheduler_task_log names that can represent a Beat entry."""
    aliases = {task_name}
    if task_name:
        tail = task_name.rsplit(".", 1)[-1]
        aliases.add(tail)
        if tail.endswith("_task"):
            aliases.add(tail.removesuffix("_task"))

    key_alias = beat_key.replace("-", "_")
    aliases.add(key_alias)
    for suffix in ("_tick", "_run", "_weekly"):
        if key_alias.endswith(suffix):
            aliases.add(key_alias.removesuffix(suffix))

    explicit_alias = {
        "daily-attribution-compute": "daily_attribution_compute",
        "daily-backup-run": "daily_backup_run",
        "meta-monitor-tick": "meta_monitor",
        "weekly-backup-verify": "weekly_backup_verify",
    }.get(beat_key)
    if explicit_alias:
        aliases.add(explicit_alias)
    return {alias for alias in aliases if alias}


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------


@router.get("/datasources")
async def get_datasources(
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """查询各数据表的最新日期和行数。

    并发查询所有已配置数据源表，返回数据新鲜度和规模信息。

    Returns:
        数据源状态列表，每项包含 name、table、latest_date、row_count、status。
    """
    # AsyncSession is not concurrency-safe; run DB reads sequentially on the
    # request session to avoid "concurrent operations are not permitted".
    results = []
    for cfg in _DATASOURCE_TABLE_CONFIG:
        results.append(await _query_datasource(session, cfg["table"], cfg["date_col"]))

    output = []
    for cfg, res in zip(_DATASOURCE_TABLE_CONFIG, results, strict=True):
        row_count = res["row_count"]
        latest_date = res["latest_date"]
        # 无法查询 → error；有数据 → ok；空表 → empty
        if row_count is None:
            status = "error"
        elif row_count == 0:
            status = "empty"
        else:
            status = "ok"
        output.append(
            {
                "name": cfg["name"],
                "table": cfg["table"],
                "latest_date": latest_date,
                "row_count": row_count,
                "status": status,
            }
        )
    return output


@router.get("/health")
async def get_system_health(
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """详细系统健康检查。

    并发检查 PostgreSQL、Redis，同步检查 Celery worker、磁盘、内存。

    Returns:
        包含 pg、redis、celery、disk、memory、overall_status 的健康报告。
    """
    # The DB session must not be used concurrently. Run PG first, then execute
    # blocking external checks with bounded timeouts so this endpoint degrades
    # instead of hanging behind Celery/Redis probes.
    pg_result = await _with_timeout("postgresql", _check_pg(session), _HEALTH_DB_TIMEOUT_SEC)
    redis_result, celery_result = await asyncio.gather(
        _run_sync_check("redis", _check_redis),
        _run_sync_check("celery", _check_celery),
    )
    disk_result = _check_disk()
    memory_result = _check_memory()

    all_ok = pg_result["ok"] and redis_result["ok"] and disk_result["ok"] and memory_result["ok"]
    # Celery worker 不在线不算整体失败（可能是开发环境），但 degraded
    overall_status = (
        "ok" if all_ok and celery_result.get("ok") else "degraded" if all_ok else "critical"
    )

    return {
        "overall_status": overall_status,
        "pg": pg_result,
        "redis": redis_result,
        "celery": celery_result,
        "disk": disk_result,
        "memory": memory_result,
    }


@router.get("/streams")
async def get_streams_status() -> dict[str, Any]:
    """Redis Streams 状态概览（调试用）。

    返回所有 qm:* Stream 的消息数量和最近发布时间。
    """
    from app.core.stream_bus import get_stream_bus

    bus = get_stream_bus()
    return {"streams": bus.all_streams_status()}


@router.get("/beat-schedule")
async def get_beat_schedule(
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """iter 210 MVP 5.5 C1 — Celery Beat schedule introspection for SchedulerDashboard S3.

    Reads live `CELERY_BEAT_SCHEDULE` dict from `app.tasks.beat_schedule` module
    (single source of truth, 0 hardcoded client drift risk) + LATERAL JOIN
    `scheduler_task_log` latest row per task_name for last_fire visibility.

    Returns:
        {
            "entries": [{beat_key, task_name, schedule_display, expires_sec,
                         last_fire_time, last_fire_status}],
            "total_count": int
        }

    Architecture per docs/mvp/MVP_5_5_scheduler_dashboard.md §2.1.
    """
    try:
        # Lazy import to keep module loadable in unit-test isolation (sibling
        # qm_platform.calendar 铁律-34 exception pattern). Bound to local scope
        # so `app.api.system.CELERY_BEAT_SCHEDULE` patch target is stable in tests.
        from app.tasks.beat_schedule import (  # noqa: PLC0415
            CELERY_BEAT_SCHEDULE,
        )
    except Exception as exc:
        # Reviewer P1 iter 210: `from exc` preserves import error identity
        # (ModuleNotFoundError vs AttributeError vs ImportError) for upstream
        # async middleware / Sentry __cause__ inspection.
        logger.exception("CELERY_BEAT_SCHEDULE import failed")
        raise HTTPException(status_code=500, detail="Beat schedule config unavailable") from exc

    if not CELERY_BEAT_SCHEDULE:
        return {"entries": [], "total_count": 0}

    # Collect all task_names and canonical scheduler_task_log aliases referenced
    # by Beat schedule. Celery uses dotted task names, while audit rows use
    # short names such as `meta_monitor` and `daily_attribution_compute`.
    aliases_by_beat_key: dict[str, set[str]] = {}
    task_names: set[str] = set()
    for beat_key, entry in CELERY_BEAT_SCHEDULE.items():
        task_name = str(entry.get("task", ""))
        aliases = _beat_log_aliases(str(beat_key), task_name)
        aliases_by_beat_key[str(beat_key)] = aliases
        task_names.update(aliases)

    # Fetch last_fire per task_name from scheduler_task_log (single query, index-optimized)
    last_fires: dict[str, dict[str, Any]] = {}
    if task_names:
        try:
            # Single query: SELECT DISTINCT ON (task_name) latest row per task
            sql = """
                SELECT DISTINCT ON (task_name)
                    task_name, start_time::text AS start_time, status
                FROM scheduler_task_log
                WHERE task_name = ANY(:names)
                ORDER BY task_name, start_time DESC
            """
            result = await session.execute(text(sql), {"names": sorted(task_names)})
            for row in result.fetchall():
                last_fires[row.task_name] = {
                    "last_fire_time": row.start_time,
                    "last_fire_status": row.status,
                }
        except Exception:
            logger.exception("scheduler_task_log last_fire query failed")
            # silent_ok per 铁律 33: degraded mode (no last_fire) > full failure;
            # the Beat schedule list itself is still useful without last_fire annotation.

    entries = []
    for beat_key, entry in sorted(CELERY_BEAT_SCHEDULE.items()):
        task_name = entry.get("task", "")
        schedule_obj = entry.get("schedule")
        # crontab.__repr__() gives "<crontab: M H D dM MY (m/h/d/dM/MY)>"; timedelta
        # gives "X seconds". repr() is best-effort display string.
        schedule_display = repr(schedule_obj) if schedule_obj is not None else ""
        options = entry.get("options", {}) or {}
        fire = {}
        for alias in aliases_by_beat_key.get(str(beat_key), {task_name}):
            candidate = last_fires.get(alias)
            if candidate and (
                not fire
                or str(candidate.get("last_fire_time") or "")
                > str(fire.get("last_fire_time") or "")
            ):
                fire = candidate
        entries.append(
            {
                "beat_key": beat_key,
                "task_name": task_name,
                "schedule_display": schedule_display,
                "expires_sec": options.get("expires"),
                "queue": options.get("queue"),
                "last_fire_time": fire.get("last_fire_time"),
                "last_fire_status": fire.get("last_fire_status"),
            }
        )

    return {"entries": entries, "total_count": len(entries)}


@router.get("/scheduler-task-log")
async def get_scheduler_task_log(
    limit: int = Query(default=20, ge=1, le=100),
    task_name: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """iter 197 MVP 5.1 Chunk 1 — Recent scheduler_task_log rows for PtStatus page S5.

    Returns rows from scheduler_task_log table sorted by schedule_time DESC.
    Index-optimized via idx_scheduler_log_date.

    iter 199 reviewer P2 cleanup: Query(ge=1, le=100) replaces silent clamp —
    rogue limit now returns 422 with clear validation, sibling FastAPI idiom.

    Args:
        limit: max rows to return (default 20, validated to [1, 100], 422 on
            out-of-range).
        task_name: optional exact-match filter on task_name column.
        session: AsyncSession DB dependency.

    Returns:
        {tasks: [{id, task_name, status, schedule_time, start_time, end_time,
                  duration_sec, error_message}], total_count: int}
    """
    where_clause = ""
    params: dict[str, Any] = {"limit": limit}
    if task_name:
        where_clause = "WHERE task_name = :task_name"
        params["task_name"] = task_name

    main_sql = (
        f"SELECT id::text AS id, task_name, status, "  # noqa: S608 — fixed where_clause from whitelist
        f"schedule_time::text AS schedule_time, "
        f"start_time::text AS start_time, "
        f"end_time::text AS end_time, "
        f"duration_sec, error_message "
        f"FROM scheduler_task_log {where_clause} "
        f"ORDER BY schedule_time DESC LIMIT :limit"
    )
    count_sql = f"SELECT COUNT(*) FROM scheduler_task_log {where_clause}"  # noqa: S608

    try:
        result = await session.execute(text(main_sql), params)
        rows = result.fetchall()
        tasks = [
            {
                "id": row.id,
                "task_name": row.task_name,
                "status": row.status,
                "schedule_time": row.schedule_time,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "duration_sec": row.duration_sec,
                "error_message": row.error_message,
            }
            for row in rows
        ]
        # Pass only task_name param (no limit) for count query
        count_params = {"task_name": task_name} if task_name else {}
        count_result = await session.execute(text(count_sql), count_params)
        total_count = int(count_result.scalar() or 0)
        return {"tasks": tasks, "total_count": total_count}
    except Exception:
        logger.exception("查询 scheduler_task_log 失败")
        # fail-loud per 铁律 33 — return empty + 200 OK is silent; raise 500.
        # iter 199 reviewer P2 cleanup: `from None` drops `noqa: B904` suppression —
        # logger.exception already captured chain at line above, intentionally break here.
        raise HTTPException(status_code=500, detail="scheduler_task_log query failed") from None


@router.get("/scheduler")
async def get_scheduler_status() -> dict[str, Any]:
    """查询 Windows Task Scheduler 中 QM- 前缀计划任务状态。

    R6 §3.3: Task Scheduler 是 QuantMind 主调度器，任务名约定以 QM- 开头。
    非 Windows 环境返回空列表。

    Returns:
        包含 tasks 列表和 platform 字段的字典。
    """
    loop = asyncio.get_event_loop()
    tasks = await loop.run_in_executor(None, _query_task_scheduler)
    return {
        "platform": platform.system(),
        "task_count": len(tasks),
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# POST /api/system/test-notification  — F63-P2-6: 测试通知 webhook
# ---------------------------------------------------------------------------


@router.post("/test-notification", summary="测试通知 webhook")
async def test_notification(
    payload: dict[str, str],
) -> dict[str, Any]:
    """向指定 webhook URL 发送测试消息。

    Args:
        payload: {"webhook_url": "https://..."}.

    Returns:
        {"success": bool, "message": str}
    """
    import httpx

    webhook_url = payload.get("webhook_url", "").strip()
    if not webhook_url:
        return {"success": False, "message": "webhook_url 不能为空"}

    test_msg = {
        "msgtype": "text",
        "text": {"content": "[QuantMind] 通知测试 — 如果你看到这条消息说明 webhook 配置正确"},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=test_msg)
        if resp.status_code == 200:
            return {"success": True, "message": "测试消息已发送"}
        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as exc:
        return {"success": False, "message": f"发送失败: {exc}"}


# ---------------------------------------------------------------------------
# GET /api/system/env-state  — Frontend Design v3 §3.1.1 EnvStateBanner backing
# ---------------------------------------------------------------------------


@router.get("/calendar-info", summary="交易日历 + PT day counter (Audit Section X §39 SSOT)")
async def get_calendar_info() -> dict[str, Any]:
    """返回 trading calendar SSOT 真值 — Dashboard "PT Day X/Y" + 节假日 verify 接通.

    设计原因 (Audit Section X §39 + Frontend Design v3 #7):
        Beat schedule / schtask / Dashboard hardcoded "PT Day 3/60" 跨脚本漂移
        (LL-181 lesson). 通过 calendar SSOT 单一来源消除漂移.

    Returns:
        dict 含 today_is_trading_day / today_reason / next_trading_day /
        prev_trading_day / pt_day_counter (current_day/total/completion_pct/label).
    """
    from datetime import date as _date

    try:
        # Lazy import — 容错 calendar 模块不可加载
        from backend.qm_platform.calendar import get_calendar
    except ImportError:
        # Fallback path — 反 silent fail (铁律 33), 显式 error response
        return {
            "error": "calendar module 不可加载",
            "today_is_trading_day": None,
            "pt_day_counter": None,
        }

    try:
        cal = get_calendar()
        today = _date.today()
        is_td, reason = cal.is_trading_day_with_reason(today)
        next_td = cal.next_trading_day(today)
        prev_td = cal.prev_trading_day(today)
        pt_info = cal.pt_day_counter(today=today)

        return {
            "today": today.isoformat(),
            "today_is_trading_day": is_td,
            "today_reason": reason,
            "next_trading_day": next_td.isoformat(),
            "prev_trading_day": prev_td.isoformat(),
            "pt_day_counter": pt_info,
        }
    except Exception as exc:
        logger.exception("calendar-info 端点失败")
        return {
            "error": str(exc),
            "today": _date.today().isoformat(),
            "today_is_trading_day": None,
            "pt_day_counter": None,
        }


@router.get("/env-state", summary="当前 .env 关键字段实时状态（LL-183 prevention UI）")
async def get_env_state() -> dict[str, Any]:
    """返回前端 EnvStateBanner 渲染所需的 .env 关键字段实时快照。

    设计原因 (LL-183 silent NOT-GATING 教训):
        Dry-run 旗标可静默 bypass live broker call, 用户无任何视觉 hint
        即 EXECUTION_MODE=live + LIVE_TRADING_DISABLED=false 也看不出. 此端点
        为前端顶部 banner 提供 SSOT, 覆盖 35 pages.

    渲染语义 (前端解析):
        - mode=paper + live_trading_disabled=true → GREEN safe banner
        - mode=live + live_trading_disabled=false → RED + pulse banner
        - mode=live + live_trading_disabled=true → AMBER mismatch banner
        - mode=disabled → GRAY maintenance banner (post-shutdown like 2026-04-29)

    Returns:
        dict 含 mode / live_trading_disabled / qmt_account_id / pt_top_n /
        dingtalk_enabled / l4_auto_enabled / last_updated (ISO timestamp).
    """
    from datetime import UTC, datetime

    from app.config import settings

    # L4 AUTO mode — 5-15 V3 PT cutover plan v0.4 retired Beat polling,
    # 不在 config.py 显式字段; 走环境变量 fallback (默认 False = STAGED 人工审批)
    l4_auto_env = os.environ.get("L4_AUTO_MODE_ENABLED", "false").strip().lower()
    l4_auto_enabled = l4_auto_env in ("true", "1", "yes")

    # mode 推导: 优先 EXECUTION_MODE, 若 LIVE_TRADING_DISABLED=true 且 0 持仓 → disabled
    # 注: 'disabled' 推导需要 DB 0 持仓事实; 这里仅基于 env 字段, 由前端结合 portfolio
    #     summary 决定是否升级为 disabled 显示 (ShutdownBanner)
    mode = settings.EXECUTION_MODE  # 'paper' | 'live'

    return {
        "mode": mode,
        "live_trading_disabled": settings.LIVE_TRADING_DISABLED,
        "qmt_account_id": settings.QMT_ACCOUNT_ID or "—",
        "pt_top_n": settings.PT_TOP_N,
        "dingtalk_enabled": settings.DINGTALK_ALERTS_ENABLED,
        "l4_auto_enabled": l4_auto_enabled,
        "last_updated": datetime.now(UTC).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Iter 39: paper_strategy_id exposure (closes iter 35 DEFAULT_STRATEGY_ID
# frontend placeholder gap). Returns settings.PAPER_STRATEGY_ID + sentinel
# fields so frontend can distinguish "configured" vs "default unconfigured".
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/settings/paper-strategy-id")
async def get_paper_strategy_id() -> dict[str, Any]:
    """Returns the configured Paper Trading strategy_id (settings.PAPER_STRATEGY_ID).

    Closes iter 35 DEFAULT_STRATEGY_ID frontend placeholder gap: ReportCenter.tsx
    previously hardcoded "default-strategy" sentinel which would 200-empty-list
    on /api/reports/{sid}/list and never surface real strategy artifacts. This
    endpoint exposes the backend-configured value so the frontend can fetch +
    cache it via react-query on mount.

    Args:
        None (read-only endpoint, no DB access — pure settings cite).

    Returns:
        dict with:
          - paper_strategy_id: str (settings.PAPER_STRATEGY_ID; empty if not configured)
          - configured: bool (True if non-empty, False if "" default)
          - source: "settings.PAPER_STRATEGY_ID" (provenance for debugging)

    Notes:
        - settings.PAPER_STRATEGY_ID default is "" per backend/app/config.py:163
        - Frontend consumer (ReportCenter.tsx) should handle configured=False
          by either prompting user to set OR falling back to placeholder display
        - 0 §6 STOP trigger (read-only settings exposure, not Architecture)
    """
    from app.config import settings

    sid = settings.PAPER_STRATEGY_ID or ""
    return {
        "paper_strategy_id": sid,
        "configured": bool(sid),
        "source": "settings.PAPER_STRATEGY_ID",
    }
