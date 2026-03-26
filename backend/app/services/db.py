"""统一同步数据库连接管理。

所有sync Service和scripts通过此模块获取psycopg2连接。
替代散落在price_utils/_get_sync_conn等处的重复实现。
"""

import psycopg2

from app.config import settings


def get_sync_conn() -> psycopg2.extensions.connection:
    """获取psycopg2同步连接。

    自动将asyncpg URL转为psycopg2格式。
    """
    url = settings.DATABASE_URL
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return psycopg2.connect(url)
