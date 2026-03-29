"""SQLAlchemy 2.0 声明式基类与通用Mixin

所有新建ORM模型统一继承此Base。
已有模型(pipeline_run/approval_queue/mining_knowledge)仍使用pipeline_run.Base，
两个Base共享同一registry不会冲突（extend_existing=True）。

注意: 本项目使用 asyncpg + SQLAlchemy async engine，参见 app/db.py。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 命名约定，与DDL保持一致
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类。

    所有新建域模型继承此类。使用 mapped_column() 风格声明字段。
    """

    metadata = MetaData(naming_convention=convention)


class TimestampMixin:
    """通用时间戳Mixin: created_at + updated_at。

    created_at: 行插入时由数据库自动填充(server_default)。
    updated_at: 行更新时由SQLAlchemy填充(onupdate)。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        comment="最后更新时间",
    )
