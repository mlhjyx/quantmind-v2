"""SQLAlchemy模型: 域4 Universe与信号表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域4
包含: universe_daily / signals
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UniverseDaily(Base):
    """每日股票池。

    DDL对应: universe_daily（域4）
    排除原因: st/suspended/new/limit/liquidity/mcap/industry/delisting
    """

    __tablename__ = "universe_daily"
    __table_args__ = {"extend_existing": True}

    code: Mapped[str] = mapped_column(
        String(10),
        primary_key=True,
        comment="股票代码",
    )
    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="交易日期",
    )
    in_universe: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="是否在股票池中",
    )
    exclude_reason: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="排除原因: st/suspended/new/limit/liquidity/mcap/industry/delisting",
    )

    def __repr__(self) -> str:
        return f"UniverseDaily(code={self.code}, date={self.trade_date}, in={self.in_universe})"


class Signal(Base):
    """交易信号。

    DDL对应: signals（域4）
    execution_mode区分paper/live。
    signal_generated_at用于gap_hours毕业指标计算。
    """

    __tablename__ = "signals"
    __table_args__ = {"extend_existing": True}

    code: Mapped[str] = mapped_column(
        String(10),
        primary_key=True,
        comment="股票代码",
    )
    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="交易日期",
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        comment="策略ID（关联strategy.id）",
    )
    alpha_score: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
        comment="Alpha综合评分",
    )
    rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="排名",
    )
    target_weight: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="目标权重",
    )
    action: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="操作: buy/sell/hold",
    )
    execution_mode: Mapped[str | None] = mapped_column(
        String(10),
        default="paper",
        comment="执行模式: paper/live",
    )
    signal_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="信号生成时间(UTC), gap_hours毕业指标",
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"Signal(code={self.code}, date={self.trade_date}, "
            f"action={self.action}, rank={self.rank})"
        )
