"""系统管理 API 路由。

提供数据源状态、系统健康检查、调度任务状态等管理接口。
"""

import asyncio
import os
import platform
import subprocess
from typing import Any

import psutil
import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

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


async def _query_datasource(
    session: AsyncSession, table: str, date_col: str
) -> dict[str, Any]:
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
    try:
        result = subprocess.run(
            [
                "python",
                "-m",
                "celery",
                "-A",
                "app.tasks",
                "inspect",
                "ping",
                "--timeout=3",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=str(_backend_dir()),
        )
        output = result.stdout + result.stderr
        # 有 pong 响应说明 worker 存活
        if "pong" in output.lower():
            # 统计存活 worker 数
            worker_count = output.lower().count("pong")
            return {"ok": True, "worker_count": worker_count}
        return {"ok": False, "worker_count": 0, "error": "No workers responded"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "worker_count": 0, "error": "inspect timeout"}
    except Exception as exc:
        logger.exception("Celery worker检查失败")
        return {"ok": False, "worker_count": 0, "error": str(exc)}


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
        包含 ok、used_gb、total_gb、percent 的字典。CLAUDE.md 要求总占用 <16GB。
    """
    try:
        vm = psutil.virtual_memory()
        used_gb = vm.used / (1024**3)
        total_gb = vm.total / (1024**3)
        return {
            "ok": used_gb < 16,
            "used_gb": round(used_gb, 1),
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
        任务状态列表，每项包含 task_name、schedule、last_run、next_run、status。
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
            last_result = item.get("LastResult", 0)
            # Windows Task Scheduler: 0=成功, 267011=还未运行
            status = (
                "success"
                if last_result == 0
                else "never_run"
                if last_result == 267011
                else "failed"
            )
            tasks.append(
                {
                    "task_name": item.get("Name", ""),
                    "schedule": "",  # 简化：不解析 trigger 配置
                    "last_run": item.get("LastRun", ""),
                    "next_run": item.get("NextRun", ""),
                    "status": status,
                    "last_result_code": last_result,
                }
            )
        return tasks
    except Exception:
        logger.exception("查询Windows Task Scheduler任务失败")
        return []


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
    tasks = [
        _query_datasource(session, cfg["table"], cfg["date_col"])
        for cfg in _DATASOURCE_TABLE_CONFIG
    ]
    results = await asyncio.gather(*tasks)

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
    # PG/Redis 并发检查
    pg_result, redis_result = await asyncio.gather(
        _check_pg(session),
        asyncio.get_event_loop().run_in_executor(None, _check_redis),
    )
    celery_result = await asyncio.get_event_loop().run_in_executor(None, _check_celery)
    disk_result = _check_disk()
    memory_result = _check_memory()

    all_ok = (
        pg_result["ok"]
        and redis_result["ok"]
        and disk_result["ok"]
        and memory_result["ok"]
    )
    # Celery worker 不在线不算整体失败（可能是开发环境），但 degraded
    overall_status = (
        "ok"
        if all_ok and celery_result.get("ok")
        else "degraded"
        if all_ok
        else "critical"
    )

    return {
        "overall_status": overall_status,
        "pg": pg_result,
        "redis": redis_result,
        "celery": celery_result,
        "disk": disk_result,
        "memory": memory_result,
    }


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
