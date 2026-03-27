"""Alembic环境配置 — 连接现有PG数据库，支持async引擎。

使用SQLAlchemy asyncpg引擎（与FastAPI共用连接配置）。
async模式通过 run_sync 在同步上下文中执行迁移。

迁移命令:
    cd backend
    alembic revision --autogenerate -m "描述"   # 生成迁移文件
    alembic upgrade head                         # 应用所有迁移
    alembic downgrade -1                         # 回滚一步
    alembic current                              # 查看当前版本
    alembic history                              # 查看迁移历史
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 将 backend/ 目录加入 sys.path，使 app.* 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

# Alembic Config对象
config = context.config

# 从 .env/settings 动态注入数据库URL（覆盖alembic.ini中的sqlalchemy.url）
# asyncpg URL → psycopg2 URL（alembic使用同步psycopg2驱动做迁移）
_db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
config.set_main_option("sqlalchemy.url", _db_url)

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有ORM Model让Alembic能感知表结构
# 即使autogenerate暂不使用，保持导入以备后用
try:
    from app.models import Base  # noqa: F401

    target_metadata = Base.metadata
except ImportError:
    # models/__init__.py尚未定义Base时的fallback
    target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：生成SQL脚本，不需要数据库连接。

    用于生成可审查的迁移SQL文件。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在同步连接上执行迁移（供async包装调用）。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # 只管理quantmind_v2专属schema，不碰pg_catalog等系统表
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：使用asyncpg连接执行迁移。"""
    # 使用async engine，但通过 sync_engine 接口执行迁移
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # 覆盖为asyncpg URL
        url=settings.DATABASE_URL,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口：通过asyncio.run执行async迁移。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
