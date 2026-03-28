"""远程状态API — 供Tailscale远程访问的轻量健康检查端点。

提供 /api/v1/status 和 /api/v1/ping 两个端点，用于远程监控
Paper Trading运行状态、系统组件健康和最近调度时间。
"""

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import psutil
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/v1", tags=["remote-status"])

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


def _is_localhost(request: Request) -> bool:
    """判断请求是否来自本机。"""
    client_host = request.client.host if request.client else ""
    return client_host in ("127.0.0.1", "::1", "localhost")


def _check_api_key(request: Request) -> None:
    """检查 X-API-Key 认证头。

    规则：
    - 若 REMOTE_API_KEY 未配置，所有请求放行（开发模式）。
    - 本地 localhost 请求跳过认证。
    - 其余请求必须携带正确的 X-API-Key。

    Args:
        request: FastAPI 请求对象。

    Raises:
        HTTPException: 认证失败时抛出 401。
    """
    api_key = settings.REMOTE_API_KEY
    if not api_key:
        return
    if _is_localhost(request):
        return
    header_key = request.headers.get("X-API-Key", "")
    if header_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


# ---------------------------------------------------------------------------
# 内部检查函数
# ---------------------------------------------------------------------------


async def _check_pg(session: AsyncSession) -> bool:
    """检查 PostgreSQL 是否可达。

    Args:
        session: 数据库会话。

    Returns:
        连接正常返回 True，否则 False。
    """
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis_sync() -> bool:
    """同步检查 Redis 连通性。

    Returns:
        ping 成功返回 True，否则 False。
    """
    try:
        r = redis_lib.Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception:
        return False


def _check_celery_sync() -> bool:
    """通过 Celery inspect ping 检查 worker（同步）。

    Returns:
        有 worker 存活返回 True，否则 False。
    """
    import subprocess

    backend_dir = os.path.join(os.path.dirname(__file__), "..", "..")
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
            timeout=6,
            cwd=str(backend_dir),
        )
        output = result.stdout + result.stderr
        return "pong" in output.lower()
    except Exception:
        return False


def _disk_free_gb() -> float:
    """返回 D 盘剩余空间（GB）。"""
    try:
        usage = psutil.disk_usage("D:\\")
        return round(usage.free / (1024**3), 1)
    except Exception:
        return 0.0


def _memory_used_pct() -> float:
    """返回系统内存使用百分比。"""
    try:
        return psutil.virtual_memory().percent
    except Exception:
        return 0.0


async def _get_pt_status(session: AsyncSession) -> dict[str, Any]:
    """从数据库读取 Paper Trading 最新运行状态。

    查询 performance_series 最近一条记录获取 NAV，
    查询 paper_trading_runs 获取当前运行元信息。

    Args:
        session: 数据库会话。

    Returns:
        PT 状态字典，包含 is_running/day/nav/nav_change_pct/strategy。
    """
    try:
        # 最新 NAV 记录
        nav_row = await session.execute(
            text(
                """
                SELECT ps.nav, ps.cumulative_return, ps.trade_date,
                       ptr.strategy_version, ptr.status,
                       (SELECT COUNT(*) FROM performance_series ps2
                        WHERE ps2.run_id = ps.run_id) AS day_count
                FROM performance_series ps
                JOIN paper_trading_runs ptr ON ps.run_id = ptr.id
                WHERE ptr.status = 'running'
                ORDER BY ps.trade_date DESC
                LIMIT 1
                """
            )
        )
        row = nav_row.fetchone()
        if row is None:
            return {
                "is_running": False,
                "day": 0,
                "nav": 0.0,
                "nav_change_pct": 0.0,
                "strategy": "none",
            }

        nav = float(row.nav)
        cumulative_return = float(row.cumulative_return)
        # nav_change_pct 用累计收益率表示（相对初始资金）
        nav_change_pct = round(cumulative_return * 100, 2)
        return {
            "is_running": True,
            "day": int(row.day_count),
            "nav": round(nav, 2),
            "nav_change_pct": nav_change_pct,
            "strategy": row.strategy_version or "v1.1",
        }
    except Exception:
        return {
            "is_running": False,
            "day": 0,
            "nav": 0.0,
            "nav_change_pct": 0.0,
            "strategy": "unknown",
        }


async def _get_last_signal_at(session: AsyncSession) -> str | None:
    """查询最近一次信号生成时间。

    Args:
        session: 数据库会话。

    Returns:
        ISO 8601 格式时间字符串，无记录时返回 None。
    """
    try:
        row = await session.execute(
            text(
                "SELECT MAX(created_at) FROM daily_signals"
            )
        )
        result = row.scalar()
        return result.isoformat() if result else None
    except Exception:
        return None


async def _get_last_execution_at(session: AsyncSession) -> str | None:
    """查询最近一次调度执行时间。

    Args:
        session: 数据库会话。

    Returns:
        ISO 8601 格式时间字符串，无记录时返回 None。
    """
    try:
        row = await session.execute(
            text(
                "SELECT MAX(started_at) FROM scheduler_task_log WHERE status = 'success'"
            )
        )
        result = row.scalar()
        return result.isoformat() if result else None
    except Exception:
        return None


async def _build_alerts(pt: dict[str, Any]) -> list[str]:
    """根据当前状态生成告警列表。

    Args:
        pt: PT 状态字典。

    Returns:
        告警消息列表，无告警时为空列表。
    """
    alerts: list[str] = []
    disk_gb = _disk_free_gb()
    if disk_gb < 100:
        alerts.append(f"磁盘剩余空间不足: {disk_gb}GB (<100GB)")
    mem_pct = _memory_used_pct()
    if mem_pct > 80:
        alerts.append(f"内存使用率过高: {mem_pct}%")
    if pt.get("is_running") and pt.get("nav_change_pct", 0) < -10:
        alerts.append(f"NAV累计亏损超过10%: {pt['nav_change_pct']}%")
    return alerts


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------


@router.get("/ping")
async def ping(request: Request) -> dict[str, Any]:
    """极简健康检查，响应时间 <50ms。

    无需数据库访问，仅返回服务存活确认。

    Args:
        request: FastAPI 请求对象（用于认证）。

    Returns:
        包含 ok 和 ts（UTC ISO时间）的字典。
    """
    _check_api_key(request)
    return {
        "ok": True,
        "ts": datetime.now(tz=UTC).isoformat(),
    }


@router.get("/status")
async def get_remote_status(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """远程综合状态端点，供 Tailscale 远程监控使用。

    并发查询 PostgreSQL/Redis/PT状态/信号时间，同步检查 Celery/磁盘/内存。
    目标响应时间 <500ms（不含 Celery 检查，Celery 检查异步化）。

    Args:
        request: FastAPI 请求对象（用于认证）。
        session: 数据库会话。

    Returns:
        包含 version/timestamp/pt_status/system/last_signal_at/
        last_execution_at/alerts 的状态字典。
    """
    _check_api_key(request)

    loop = asyncio.get_event_loop()

    # 并发执行所有检查
    (
        pg_ok,
        redis_ok,
        celery_ok,
        pt_status,
        last_signal_at,
        last_execution_at,
    ) = await asyncio.gather(
        _check_pg(session),
        loop.run_in_executor(None, _check_redis_sync),
        loop.run_in_executor(None, _check_celery_sync),
        _get_pt_status(session),
        _get_last_signal_at(session),
        _get_last_execution_at(session),
    )

    disk_free_gb = _disk_free_gb()
    memory_used_pct = _memory_used_pct()
    alerts = await _build_alerts(pt_status)

    return {
        "version": "1.0",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "pt_status": pt_status,
        "system": {
            "pg_ok": pg_ok,
            "redis_ok": redis_ok,
            "celery_ok": celery_ok,
            "disk_free_gb": disk_free_gb,
            "memory_used_pct": memory_used_pct,
        },
        "last_signal_at": last_signal_at,
        "last_execution_at": last_execution_at,
        "alerts": alerts,
    }
