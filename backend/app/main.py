"""FastAPI 入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approval import router as approval_router
from app.api.backtest import router as backtest_router
from app.api.dashboard import router as dashboard_router
from app.api.execution import router as execution_router
from app.api.execution_ops import router as execution_ops_router
from app.api.factors import router as factors_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.mining import router as mining_router
from app.api.notifications import router as notifications_router
from app.api.paper_trading import router as paper_trading_router
from app.api.params import router as params_router
from app.api.pipeline import router as pipeline_router
from app.api.pms import router as pms_router
from app.api.portfolio import router as portfolio_router
from app.api.realtime import router as realtime_router
from app.api.remote_status import router as remote_status_router
from app.api.report import router as report_router
from app.api.risk import router as risk_router
from app.api.strategies import router as strategies_router
from app.api.system import router as system_router
from app.config import settings
from app.db import engine
from app.logging_config import configure_logging
from app.services.qmt_connection_manager import qmt_manager
from app.websocket import socket_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化资源，关闭时释放连接池。"""
    configure_logging()
    # MVP 1.3b wiring: 注入 Platform DBFactorRegistry + DBFeatureFlag 到 signal_engine.
    # 幂等 + fail-safe (失败自动回 Layer 0 hardcoded, 3 层 fallback 保底).
    from app.core.platform_bootstrap import bootstrap_platform_deps

    bootstrap_platform_deps()
    qmt_manager.startup()
    # 初始化 StreamBus（预热连接）
    from app.core.stream_bus import close_stream_bus, get_stream_bus

    get_stream_bus()
    yield
    close_stream_bus()
    qmt_manager.shutdown()
    await engine.dispose()


app = FastAPI(
    title="QuantMind V2",
    description="A股+外汇绝对收益量化交易系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API 路由注册 ---
app.include_router(health_router)
app.include_router(approval_router)
app.include_router(backtest_router)
app.include_router(dashboard_router)
app.include_router(execution_router)
app.include_router(execution_ops_router)
app.include_router(realtime_router)
app.include_router(market_router)
app.include_router(notifications_router)
app.include_router(paper_trading_router)
app.include_router(pms_router)
app.include_router(params_router)
app.include_router(portfolio_router)
app.include_router(report_router)
app.include_router(risk_router)
app.include_router(factors_router)
app.include_router(mining_router)
app.include_router(pipeline_router)
app.include_router(strategies_router)
app.include_router(remote_status_router)
app.include_router(system_router)


@app.get("/health")
async def health_check():
    """简易健康检查（向后兼容）。"""
    return {
        "status": "ok",
        "execution_mode": settings.EXECUTION_MODE,
    }


# --- WebSocket挂载（/ws/socket.io）---
# python-socketio ASGI应用挂载到 /ws 路径
# 前端连接地址: ws://localhost:8000/ws/socket.io
app.mount("/ws", socket_app)
