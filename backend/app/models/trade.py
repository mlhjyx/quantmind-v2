"""SQLAlchemy模型: 域5 交易执行表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域5
包含: trade_log / position_snapshot / performance_series

单位说明:
  - trade_log: quantity=股(已整手约束), fill_price/commission/stamp_tax/total_cost=元, slippage_bps=基点
  - position_snapshot: quantity=股, avg_cost=元/股, market_value/unrealized_pnl=元
  - performance_series: nav=净值, daily_return/cumulative_return/drawdown=比例
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TradeLog(Base):
    """交易记录。

    DDL对应: trade_log（域5）
    execution_mode区分paper/live。
    quantity为已整手约束后的股数: floor(x/100)*100。
    """

    __tablename__ = "trade_log"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID主键",
    )
    code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="股票代码",
    )
    trade_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="交易日期",
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="策略ID（关联strategy.id）",
    )
    market: Mapped[str | None] = mapped_column(
        String(10),
        default="astock",
        comment="市场: astock/forex",
    )
    direction: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
        comment="方向: buy/sell",
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="股数（已整手约束: floor(x/100)*100）",
    )
    target_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="目标价格（元）",
    )
    fill_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="成交价格（元）",
    )
    slippage_bps: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        comment="滑点（基点, 1bp=0.01%）",
    )
    commission: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="佣金（元）",
    )
    stamp_tax: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="印花税（元）",
    )
    swap_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        default=Decimal("0"),
        comment="外汇Swap费用（元）",
    )
    total_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="总交易成本（元）",
    )
    execution_mode: Mapped[str | None] = mapped_column(
        String(10),
        default="paper",
        comment="执行模式: paper/live",
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="拒绝原因: limit_up/limit_down/suspended/insufficient_fund",
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="实际执行确认时间(UTC)",
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"TradeLog(id={str(self.id)[:8]}, code={self.code}, "
            f"dir={self.direction}, qty={self.quantity}, "
            f"mode={self.execution_mode})"
        )


class PositionSnapshot(Base):
    """每日持仓快照。

    DDL对应: position_snapshot（域5）
    execution_mode区分paper/live。
    """

    __tablename__ = "position_snapshot"
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
    market: Mapped[str | None] = mapped_column(
        String(10),
        default="astock",
        comment="市场: astock/forex",
    )
    quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="持仓股数",
    )
    avg_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="平均成本（元/股）",
    )
    market_value: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="市值（元）",
    )
    weight: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="持仓权重",
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="未实现盈亏（元）",
    )
    holding_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="持有天数",
    )
    execution_mode: Mapped[str | None] = mapped_column(
        String(10),
        default="paper",
        comment="执行模式: paper/live",
    )

    def __repr__(self) -> str:
        return (
            f"PositionSnapshot(code={self.code}, date={self.trade_date}, "
            f"qty={self.quantity}, weight={self.weight})"
        )


class PerformanceSeries(Base):
    """策略绩效时间序列。

    DDL对应: performance_series（域5）
    execution_mode区分paper/live。
    """

    __tablename__ = "performance_series"
    __table_args__ = {"extend_existing": True}

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
    market: Mapped[str | None] = mapped_column(
        String(10),
        default="astock",
        comment="市场: astock/forex",
    )
    nav: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6),
        nullable=True,
        comment="净值",
    )
    daily_return: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
        comment="日收益率",
    )
    cumulative_return: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
        comment="累计收益率",
    )
    drawdown: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
        comment="回撤",
    )
    cash_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="现金比例",
    )
    position_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="持仓数量",
    )
    turnover: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="换手率",
    )
    benchmark_nav: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6),
        nullable=True,
        comment="基准净值",
    )
    excess_return: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
        comment="超额收益",
    )
    execution_mode: Mapped[str | None] = mapped_column(
        String(10),
        default="paper",
        comment="执行模式: paper/live",
    )

    def __repr__(self) -> str:
        return f"PerformanceSeries(date={self.trade_date}, nav={self.nav}, dd={self.drawdown})"
