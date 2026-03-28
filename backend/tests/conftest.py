"""pytest共享fixtures — 异步DB session + API测试client。

连接真实PostgreSQL: quantmind_v2。
每个测试用例创建独立connection+transaction，结束后ROLLBACK。
"""

import sys
import uuid
from pathlib import Path

import pytest

# 确保backend目录和项目根目录在sys.path中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import pytest_asyncio
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        create_async_engine,
    )
    from app.main import app

    DATABASE_URL = "postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2"

    @pytest_asyncio.fixture
    async def db_session():
        """每个测试用例获得独立AsyncSession + ROLLBACK。

        每个测试用例:
        1. 创建独立engine (pool_size=1避免连接泄漏)
        2. 获取connection -> 开启事务
        3. 测试结束 -> rollback -> 关闭
        """
        engine = create_async_engine(DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
        async with engine.connect() as conn:
            # 开启显式事务
            txn = await conn.begin()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await txn.rollback()
        await engine.dispose()

    @pytest_asyncio.fixture
    async def client():
        """异步HTTP客户端，用于API路由测试。

        通过httpx ASGITransport直接调用FastAPI app，无需启动服务器。
        """
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest_asyncio.fixture
    async def strategy_id(db_session: AsyncSession):
        """创建一个测试用strategy，返回其UUID。"""
        sid = uuid.uuid4()
        await db_session.execute(
            text(
                """INSERT INTO strategy (id, name, market, mode, active_version, status)
                   VALUES (:id, :name, 'astock', 'visual', 1, 'draft')"""
            ),
            {"id": sid, "name": f"test_strategy_{sid.hex[:8]}"},
        )
        return sid

except ImportError:
    # fastapi/sqlalchemy/pytest_asyncio not installed — skip DB/API fixtures
    pass
