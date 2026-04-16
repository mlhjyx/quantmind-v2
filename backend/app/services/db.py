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
            url = "postgresql://" + url[len(prefix) :]
            break
    return url


class _TrackedConnection:
    """psycopg2连接包装器，close()时自动递减活跃计数。

    __getattr__ 透传读属性, __setattr__ 透传写属性 (如 conn.autocommit=True).
    __slots__ 仅含 _conn/_counted, 其他 set 操作转发到底层 psycopg2 connection.
    """

    __slots__ = ("_conn", "_counted")

    def __init__(self, conn: psycopg2.extensions.connection):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_counted", True)

    def close(self):
        if self._counted:
            global _active_count
            _active_count = max(0, _active_count - 1)
            object.__setattr__(self, "_counted", False)
        self._conn.close()

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *args):
        return self._conn.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name in ("_conn", "_counted"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)


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
