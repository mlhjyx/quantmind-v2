"""Realtime API — 前端统一实时数据源。

缓存在RealtimeDataService内部（5s/10s TTL）。
路由使用sync def（非async），FastAPI自动在线程池中执行。
"""

from typing import Any

import structlog
from fastapi import APIRouter

from app.services.realtime_data_service import RealtimeDataService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


def _make_conn():
    """创建psycopg2连接。延迟导入避免import-time阻塞。"""
    try:
        from app.services.db import get_sync_conn
        return get_sync_conn()
    except Exception as e:
        logger.warning("realtime DB连接失败", error=str(e))
        return None


# 延迟初始化的连接
_lazy_conn = None
_conn_tried = False


def _get_conn():
    """懒加载DB连接，失败只尝试一次不重试。"""
    global _lazy_conn, _conn_tried
    if not _conn_tried:
        _conn_tried = True
        _lazy_conn = _make_conn()
        if _lazy_conn:
            logger.info("realtime DB连接成功")
    # 检查连接是否仍然有效
    if _lazy_conn is not None:
        try:
            _lazy_conn.rollback()  # 重置事务状态
        except Exception:
            logger.warning("realtime DB连接已断开，重新连接")
            _lazy_conn = _make_conn()
    return _lazy_conn


@router.get("/portfolio")
def get_portfolio() -> dict[str, Any]:
    """组合快照 — 5秒缓存。"""
    svc = RealtimeDataService(conn=_get_conn())
    return svc.get_portfolio_snapshot()


@router.get("/market")
def get_market() -> dict[str, Any]:
    """市场概览 — 10秒缓存。"""
    svc = RealtimeDataService(conn=_get_conn())
    return svc.get_market_overview()
