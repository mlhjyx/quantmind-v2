"""统一同步数据库连接管理。

所有sync Service和scripts通过此模块获取psycopg2连接。
调用方用完后必须conn.close()释放连接。
"""

import psycopg2

from app.config import settings

# 跟踪活跃连接数，防止泄漏
_active_count: int = 0
_MAX_CONNECTIONS: int = 15


def _get_dsn() -> str:
    """将asyncpg URL转为psycopg2格式。"""
    url = settings.DATABASE_URL
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return url


class _TrackedConnection:
    """psycopg2连接包装器，close()时自动递减活跃计数。"""

    __slots__ = ("_conn", "_counted")

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn
        self._counted = True

    def close(self):
        if self._counted:
            global _active_count
            _active_count = max(0, _active_count - 1)
            self._counted = False
        self._conn.close()

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *args):
        return self._conn.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_sync_conn():
    """获取psycopg2同步连接。

    调用方用完后必须 conn.close() 释放连接。
    内置连接数上限保护，防止泄漏导致PG连接耗尽。
    """
    global _active_count
    if _active_count >= _MAX_CONNECTIONS:
        import structlog
        structlog.get_logger(__name__).warning(
            f"sync连接数达到上限({_MAX_CONNECTIONS})，可能存在连接泄漏"
        )
    conn = psycopg2.connect(_get_dsn())
    _active_count += 1
    return _TrackedConnection(conn)
