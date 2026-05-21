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
    """创建psycopg2连接。延迟导入避免import-time阻塞。

    本连接仅供 RealtimeDataService 只读 SELECT，故 autocommit=True：每条查询
    自动收尾，杜绝无前端流量时连接长期 idle-in-transaction 阻塞 autovacuum
    (2026-05-22 实测 pg_stat_activity ~48h idle-in-txn 泄漏)。
    """
    try:
        from app.services.db import get_sync_conn

        conn = get_sync_conn()
        conn.autocommit = True
        return conn
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
    # 探活：autocommit 下 rollback() 不往返服务端，改用 SELECT 1 查询检测连接是否存活
    if _lazy_conn is not None:
        try:
            with _lazy_conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
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
