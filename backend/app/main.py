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
from app.api.news import router as news_router
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

    # P0 批 1 Fix 2 (2026-04-29): ADR-008 命名空间漂移启动断言.
    # 若 .env EXECUTION_MODE 与 DB position_snapshot 最近 30d 命名空间不一致, RAISE
    # NamespaceMismatchError 拒绝启动 (铁律 33 fail-loud).
    # 历史教训: 4-20 cutover live → 4-29 .env 改回 paper 但持仓数据继续按 live 写,
    # 14:30 risk_daily_check entry_price=0 silent skip 全部规则 → 真金 -29% 0 alert.
    # 详见 docs/audit/write_path_namespace_audit_2026_04_29.md.
    #
    # reviewer P0 采纳 (oh-my-claudecode/code-reviewer): 包 try/except 防 engine
    # 泄漏 — raise 时 yield 后 cleanup 不执行, SQLAlchemy async engine 池累积导致
    # Servy 重启循环 PG max_connections 耗尽. 显式 dispose 后再 re-raise.
    from app.services.db import get_sync_conn
    from app.services.startup_assertions import run_startup_assertions

    try:
        run_startup_assertions(get_sync_conn)
    except Exception:
        # 启动断言失败 → 显式 dispose engine 防连接池泄漏 (P0 reviewer fix)
        await engine.dispose()
        raise

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
app.include_router(news_router)
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
