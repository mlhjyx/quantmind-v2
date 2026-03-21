"""基础Repository — 通用CRUD操作。

所有Repository继承此基类，通过AsyncSession操作DB。
遵循CLAUDE.md: 所有数据库操作用async/await。
"""

from datetime import date
from typing import Any, Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository:
    """Repository基类 — 通过AsyncSession访问DB。

    所有子类通过FastAPI Depends注入session，
    保证同一请求共享session（CLAUDE.md §Service依赖注入）。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(self, sql: str, params: Optional[dict] = None) -> Any:
        """执行原生SQL。"""
        result = await self.session.execute(text(sql), params or {})
        return result

    async def fetch_one(self, sql: str, params: Optional[dict] = None) -> Optional[Any]:
        """查询单行。"""
        result = await self.session.execute(text(sql), params or {})
        return result.fetchone()

    async def fetch_all(self, sql: str, params: Optional[dict] = None) -> list[Any]:
        """查询多行。"""
        result = await self.session.execute(text(sql), params or {})
        return result.fetchall()

    async def fetch_scalar(self, sql: str, params: Optional[dict] = None) -> Any:
        """查询标量值。"""
        result = await self.session.execute(text(sql), params or {})
        row = result.fetchone()
        return row[0] if row else None
