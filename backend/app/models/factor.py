"""SQLAlchemy模型: 域3 因子表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域3
包含: factor_registry / factor_values / factor_ic_history

因子状态机: candidate -> active -> warning -> critical -> retired
factor_values为TimescaleDB hypertable，按trade_date分chunk(1月)。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FactorRegistry(Base):
    """因子注册表。

    DDL对应: factor_registry（域3）
    状态机: candidate -> active -> warning -> critical -> retired
    """

    __tablename__ = "factor_registry"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID主键",
    )
    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="因子名称（全局唯一）",
    )
    category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="因子类别: price_volume/liquidity/money_flow/fundamental/size",
    )
    direction: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="因子方向: 1=正向(值越大越好) -1=反向",
    )
    expression: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="因子表达式（FactorDSL或描述）",
    )
    code_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="因子计算代码",
    )
    hypothesis: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="经济学假设说明",
    )
    source: Mapped[str | None] = mapped_column(
        String(20),
        default="builtin",
        comment="来源: builtin/gp/llm/brute/manual",
    )
    lookback_days: Mapped[int | None] = mapped_column(
        Integer,
        default=60,
        comment="回溯天数",
    )
    status: Mapped[str | None] = mapped_column(
        String(20),
        default="active",
        comment="状态: candidate/active/warning/critical/retired",
    )
    gate_ic: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Gate通过时的IC均值",
    )
    gate_ir: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Gate通过时的IC_IR",
    )
    gate_mono: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Gate通过时的单调性得分",
    )
    gate_t: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Gate通过时的t统计量",
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"FactorRegistry(name={self.name}, category={self.category}, status={self.status})"


class FactorValue(Base):
    """因子值(长表)。

    DDL对应: factor_values（域3, TimescaleDB hypertable）
    写入模式: 按日期批量写(单事务写入当日全部)。
    处理顺序: 去极值 -> 填充 -> 中性化 -> 标准化。
    """

    __tablename__ = "factor_values"
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
    factor_name: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="因子名称（关联factor_registry.name）",
    )
    raw_value: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6),
        nullable=True,
        comment="原始因子值",
    )
    neutral_value: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6),
        nullable=True,
        comment="中性化后值（去极值->填充->中性化->标准化顺序）",
    )
    zscore: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 6),
        nullable=True,
        comment="标准化后值",
    )

    def __repr__(self) -> str:
        return (
            f"FactorValue(code={self.code}, date={self.trade_date}, "
            f"factor={self.factor_name}, raw={self.raw_value})"
        )


class FactorICHistory(Base):
    """因子IC历史。

    DDL对应: factor_ic_history（域3）
    IC=相对沪深300超额收益Spearman相关系数。ic_abs=绝对收益IC。
    """

    __tablename__ = "factor_ic_history"
    __table_args__ = {"extend_existing": True}

    factor_name: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="因子名称",
    )
    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="交易日期",
    )
    ic_1d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="1日超额收益IC（相对沪深300）",
    )
    ic_5d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="5日超额收益IC",
    )
    ic_10d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="10日超额收益IC",
    )
    ic_20d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="20日超额收益IC",
    )
    ic_abs_1d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="1日绝对收益IC",
    )
    ic_abs_5d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="5日绝对收益IC",
    )
    ic_ma20: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="IC 20日均值",
    )
    ic_ma60: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
        nullable=True,
        comment="IC 60日均值",
    )
    decay_level: Mapped[str | None] = mapped_column(
        String(10),
        default="normal",
        comment="衰减级别: normal/warning/critical",
    )

    def __repr__(self) -> str:
        return (
            f"FactorICHistory(factor={self.factor_name}, "
            f"date={self.trade_date}, ic_20d={self.ic_20d})"
        )
