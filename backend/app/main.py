"""FastAPI 入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.backtest import router as backtest_router
from app.api.dashboard import router as dashboard_router
from app.api.factors import router as factors_router
from app.api.health import router as health_router
from app.api.mining import router as mining_router
from app.api.notifications import router as notifications_router
from app.api.paper_trading import router as paper_trading_router
from app.api.params import router as params_router
from app.api.risk import router as risk_router
from app.api.strategies import router as strategies_router
from app.config import settings
from app.db import engine
from app.logging_config import configure_logging
from app.websocket import socket_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化资源，关闭时释放连接池。"""
    configure_logging()
    yield
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
app.include_router(backtest_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(paper_trading_router)
app.include_router(params_router)
app.include_router(risk_router)
app.include_router(factors_router)
app.include_router(mining_router)
app.include_router(strategies_router)


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
