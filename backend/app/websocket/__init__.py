"""WebSocket模块 — python-socketio集成到FastAPI (ASGI挂载)。

事件类型 (Sprint 1.15):
    backtest:progress    — 回测进度 {run_id, progress_pct, current_date, elapsed_sec}
    backtest:status      — 回测状态 {run_id, status: running/completed/failed}
    backtest:realtime_nav — 实时NAV {run_id, date, nav, benchmark_nav}
    backtest:log         — 回测日志 {run_id, level, message}

Room管理:
    每个backtest run_id一个room，客户端 join/leave。
"""

from app.websocket.manager import BacktestWebSocketManager, sio, socket_app

__all__ = ["BacktestWebSocketManager", "sio", "socket_app"]
