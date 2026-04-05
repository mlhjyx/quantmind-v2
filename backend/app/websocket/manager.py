"""WebSocket管理器 — python-socketio ASGI应用 + Room管理。

架构:
    - python-socketio AsyncServer挂载到FastAPI (ASGIApp)
    - 每个backtest run_id对应一个room
    - 客户端通过join_backtest/leave_backtest事件管理订阅
    - BacktestWebSocketManager提供后端推送API

安装依赖:
    pip install python-socketio

FastAPI挂载示例（在main.py中）:
    from app.websocket import socket_app
    app.mount("/ws", socket_app)
"""

import structlog

import socketio

from app.websocket.events import (
    EVENT_LOG,
    EVENT_PROGRESS,
    EVENT_REALTIME_NAV,
    EVENT_STATUS,
    BacktestStatus,
    make_log,
    make_progress,
    make_realtime_nav,
    make_status,
)

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────
# socketio AsyncServer实例（全局单例）
# ─────────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",  # 开发环境允许所有来源，生产环境可收紧
    logger=False,
    engineio_logger=False,
)

# ASGI应用，挂载到FastAPI: app.mount("/ws", socket_app)
socket_app = socketio.ASGIApp(sio, socketio_path="/socket.io")


# ─────────────────────────────────────────────────────────
# Socket.IO 事件处理
# ─────────────────────────────────────────────────────────


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    """客户端连接。

    Args:
        sid: Socket.IO session ID
        environ: WSGI/ASGI环境变量
        auth: 认证数据（预留，当前不使用）
    """
    logger.info(f"[WebSocket] 客户端连接: sid={sid}")


@sio.event
async def disconnect(sid: str) -> None:
    """客户端断开。

    Args:
        sid: Socket.IO session ID
    """
    logger.info(f"[WebSocket] 客户端断开: sid={sid}")


@sio.event
async def join_backtest(sid: str, data: dict) -> dict:
    """加入回测room以接收进度推送。

    Args:
        sid: Socket.IO session ID
        data: {"run_id": "xxx"}

    Returns:
        {"ok": True, "run_id": "xxx"} 或 {"ok": False, "error": "..."}
    """
    run_id = data.get("run_id") if isinstance(data, dict) else None
    if not run_id:
        return {"ok": False, "error": "run_id is required"}

    room = _room_name(run_id)
    await sio.enter_room(sid, room)
    logger.info(f"[WebSocket] sid={sid} 加入room: {room}")
    return {"ok": True, "run_id": run_id}


@sio.event
async def leave_backtest(sid: str, data: dict) -> dict:
    """离开回测room。

    Args:
        sid: Socket.IO session ID
        data: {"run_id": "xxx"}

    Returns:
        {"ok": True} 或 {"ok": False, "error": "..."}
    """
    run_id = data.get("run_id") if isinstance(data, dict) else None
    if not run_id:
        return {"ok": False, "error": "run_id is required"}

    room = _room_name(run_id)
    await sio.leave_room(sid, room)
    logger.info(f"[WebSocket] sid={sid} 离开room: {room}")
    return {"ok": True}


# ─────────────────────────────────────────────────────────
# 后端推送API — BacktestWebSocketManager
# ─────────────────────────────────────────────────────────


def _room_name(run_id: str) -> str:
    """生成room名称。"""
    return f"backtest:{run_id}"


class BacktestWebSocketManager:
    """回测WebSocket推送管理器。

    后端（Celery任务/回测引擎）通过此类向前端推送进度。

    用法:
        from app.websocket.manager import BacktestWebSocketManager
        ws = BacktestWebSocketManager()
        await ws.emit_progress(run_id="abc", progress_pct=50.0, current_date=date.today(), elapsed_sec=10.0)
    """

    async def emit_progress(
        self,
        run_id: str,
        progress_pct: float,
        current_date,
        elapsed_sec: float,
    ) -> None:
        """推送回测进度。

        Args:
            run_id: 回测任务ID
            progress_pct: 进度百分比 [0, 100]
            current_date: 当前处理的交易日
            elapsed_sec: 已过去秒数
        """
        payload = make_progress(run_id, progress_pct, current_date, elapsed_sec)
        await sio.emit(EVENT_PROGRESS, payload, room=_room_name(run_id))
        logger.debug(f"[WebSocket] emit {EVENT_PROGRESS}: run_id={run_id}, {progress_pct:.1f}%")

    async def emit_status(
        self,
        run_id: str,
        status: BacktestStatus,
        message: str = "",
    ) -> None:
        """推送回测状态变更。

        Args:
            run_id: 回测任务ID
            status: running/completed/failed/cancelled
            message: 附加说明
        """
        payload = make_status(run_id, status, message)
        await sio.emit(EVENT_STATUS, payload, room=_room_name(run_id))
        logger.info(f"[WebSocket] emit {EVENT_STATUS}: run_id={run_id}, status={status}")

    async def emit_realtime_nav(
        self,
        run_id: str,
        date,
        nav: float,
        benchmark_nav: float,
    ) -> None:
        """推送实时NAV数据点。

        Args:
            run_id: 回测任务ID
            date: 日期
            nav: 策略净值（元）
            benchmark_nav: 基准净值（元）
        """
        payload = make_realtime_nav(run_id, date, nav, benchmark_nav)
        await sio.emit(EVENT_REALTIME_NAV, payload, room=_room_name(run_id))

    async def emit_log(self, run_id: str, level: str, message: str) -> None:
        """推送回测日志消息。

        Args:
            run_id: 回测任务ID
            level: 日志级别 INFO/WARNING/ERROR
            message: 日志消息
        """
        payload = make_log(run_id, level, message)
        await sio.emit(EVENT_LOG, payload, room=_room_name(run_id))

    async def emit_completed(self, run_id: str, message: str = "回测完成") -> None:
        """推送回测完成（便捷方法，同时发送100%进度和completed状态）。

        Args:
            run_id: 回测任务ID
            message: 完成说明
        """
        await self.emit_status(run_id, "completed", message)

    async def emit_failed(self, run_id: str, error: str) -> None:
        """推送回测失败。

        Args:
            run_id: 回测任务ID
            error: 错误信息
        """
        await self.emit_status(run_id, "failed", error)
        await self.emit_log(run_id, "ERROR", error)
