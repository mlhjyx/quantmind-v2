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

    Session 40 修复 (2026-04-28): 加 ``__del__`` finalizer 兜底 counter accuracy.
    背景: MVP 3.1 真生产首日 (4-27 10:10 起) celery worker 频繁告警
    ``sync连接数达到上限(15)，可能存在连接泄漏``. 实测 PG ``pg_stat_activity``
    active+idle conns = 2, **非真 PG 资源泄漏** — 而是 ``_active_count`` counter logic
    漏洞: 调用方未显式 ``conn.close()`` (依赖 GC / ``with`` 退出 / 异常路径) 时,
    psycopg2 conn 通过 GC ``__del__`` 关闭 socket 但 ``_TrackedConnection.close()``
    未被调用 → ``_counted=True`` 永不 decrement → 计数器累积 → 假告警每次 acquire
    fire warning. 本 finalizer 在 GC 路径 decrement counter 兜底.
    """

    __slots__ = ("_conn", "_counted")

    def __init__(self, conn: psycopg2.extensions.connection):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_counted", True)

    def close(self):
        if self._counted:
            global _active_count
            # max(0, ...) 兜底防 counter underflow. CPython GIL 保证 close() 单线程不会
            # 同时跟 __del__ 双 decrement (设 _counted=False 后 __del__ 走 no-op gate).
            _active_count = max(0, _active_count - 1)
            object.__setattr__(self, "_counted", False)
        self._conn.close()

    def __del__(self):
        """GC 兜底 counter decrement + connection close (Session 40 fix).

        调用方未显式 close() 时 (GC / ``with`` 路径 / 异常未 close), GC finalize
        wrapper → 此处 decrement counter + 主动 close 底层 conn (defense-in-depth).

        关于底层 conn close (PR #115 reviewer P2 采纳): 原设计仅 decrement counter,
        依赖 psycopg2.connection 自身 __del__ 关闭 socket. 但 PyPy / cyclic ref /
        非 CPython 运行时 conn.__del__ 可能延迟. 此处显式调 conn.close() 加 defense
        (psycopg2 close() 在已关闭 conn 上是 idempotent no-op, 安全).

        Interpreter shutdown 时 globals 可能 None / __slots__ 属性可能未 init →
        silent_ok try/except 防 finalizer 抛异常污染 stderr.
        """
        try:
            if self._counted:
                object.__setattr__(self, "_counted", False)
                global _active_count
                _active_count = max(0, _active_count - 1)
            # P2 reviewer 采纳: defense-in-depth 主动 close conn (idempotent)
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass  # silent_ok: __del__ during interpreter shutdown when globals may be unset

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
