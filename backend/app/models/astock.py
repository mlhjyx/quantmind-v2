"""SQLAlchemy模型: 域1 基础数据表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域1
包含: symbols / klines_daily / daily_basic / trading_calendar / index_daily

单位说明(DDL COMMENT):
  - klines_daily.volume = 手(1手=100股)
  - klines_daily.amount = 千元
  - daily_basic.total_mv / circ_mv = 万元
  - index_daily.amount = 千元
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Symbol(Base):
    """股票/货币对基础信息。

    DDL对应: symbols（域1）
    必须包含退市股(list_status='D')以避免存活偏差。
    """

    __tablename__ = "symbols"
    __table_args__ = {"extend_existing": True}

    code: Mapped[str] = mapped_column(
        String(10),
        primary_key=True,
        comment="股票代码，如 000001",
    )
    ts_code: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        comment="Tushare格式代码，如 000001.SZ",
    )
    name: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="股票名称",
    )
    market: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="astock",
        comment="市场: astock/forex",
    )
    board: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="板块: main/gem/star/bse (主板/创业板/科创板/北交所)",
    )
    exchange: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="交易所: SSE/SZSE",
    )
    industry_sw1: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="申万一级行业",
    )
    industry_sw2: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="申万二级行业",
    )
    area: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="地区",
    )
    list_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="上市日期",
    )
    delist_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="退市日期（必须保留退市股！存活偏差）",
    )
    list_status: Mapped[str | None] = mapped_column(
        String(2),
        default="L",
        comment="上市状态: L=上市 D=退市 P=暂停",
    )
    is_hs: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
        comment="沪深港通标记: N/H/S",
    )
    price_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        default=Decimal("0.10"),
        comment="涨跌停幅度: 主板0.10, 创业板/科创板0.20, ST0.05, 北交所0.30",
    )
    lot_size: Mapped[int | None] = mapped_column(
        Integer,
        default=100,
        comment="最小交易单位(股)",
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        default=True,
        comment="是否活跃",
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
        return f"Symbol(code={self.code}, name={self.name}, market={self.market})"


class KlineDaily(Base):
    """日线行情。

    DDL对应: klines_daily（域1, TimescaleDB hypertable）
    价格=未复权元, volume=手(x100=股), amount=千元。
    """

    __tablename__ = "klines_daily"
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
    open: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="开盘价（元，未复权）",
    )
    high: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="最高价（元，未复权）",
    )
    low: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="最低价（元，未复权）",
    )
    close: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="收盘价（元，未复权）",
    )
    pre_close: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="昨收价（元，未复权）",
    )
    change: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="涨跌额（元）",
    )
    pct_change: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="涨跌幅（%，已乘100：5.06表示涨5.06%）",
    )
    volume: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="成交量（手，1手=100股）",
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="成交额（千元，与moneyflow的万元不同！）",
    )
    turnover_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="换手率%（总股本）",
    )
    adj_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        default=Decimal("1.0"),
        comment="累积复权因子。adj_close = close * adj_factor / latest_adj_factor",
    )
    is_suspended: Mapped[bool | None] = mapped_column(
        Boolean,
        default=False,
        comment="是否停牌",
    )
    is_st: Mapped[bool | None] = mapped_column(
        Boolean,
        default=False,
        comment="是否ST",
    )
    up_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="涨停价",
    )
    down_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="跌停价",
    )

    def __repr__(self) -> str:
        return f"KlineDaily(code={self.code}, date={self.trade_date}, close={self.close})"


class DailyBasic(Base):
    """每日指标。

    DDL对应: daily_basic（域1）
    total_mv/circ_mv=万元, turnover_rate=%。
    """

    __tablename__ = "daily_basic"
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
    close: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="收盘价（元）",
    )
    turnover_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="换手率%（总股本）",
    )
    turnover_rate_f: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="换手率-自由流通股（%，因子计算推荐用这个）",
    )
    volume_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="量比（倍）",
    )
    pe: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="市盈率（静态，倍）",
    )
    pe_ttm: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="市盈率TTM（倍，可为负）",
    )
    pb: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="市净率（倍）",
    )
    ps: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="市销率（静态）",
    )
    ps_ttm: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="市销率TTM",
    )
    dv_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="股息率（%，静态）",
    )
    dv_ttm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="股息率TTM（%）",
    )
    total_share: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 4),
        nullable=True,
        comment="总股本（万股）",
    )
    float_share: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 4),
        nullable=True,
        comment="流通股本（万股）",
    )
    free_share: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 4),
        nullable=True,
        comment="自由流通股本（万股）",
    )
    total_mv: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="总市值（万元，不是元！跨表计算注意单位）",
    )
    circ_mv: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="流通市值（万元，不是元！）",
    )

    def __repr__(self) -> str:
        return (
            f"DailyBasic(code={self.code}, date={self.trade_date}, "
            f"pe_ttm={self.pe_ttm}, total_mv={self.total_mv})"
        )


class TradingCalendar(Base):
    """交易日历。

    DDL对应: trading_calendar（域1）
    年初导入+每日T0预检校验。
    """

    __tablename__ = "trading_calendar"
    __table_args__ = {"extend_existing": True}

    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="日期",
    )
    market: Mapped[str] = mapped_column(
        String(10),
        primary_key=True,
        default="astock",
        comment="市场: astock/forex",
    )
    is_trading_day: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="是否交易日",
    )
    is_half_day: Mapped[bool | None] = mapped_column(
        Boolean,
        default=False,
        comment="是否半日交易",
    )
    pretrade_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="上一交易日",
    )

    def __repr__(self) -> str:
        return (
            f"TradingCalendar(date={self.trade_date}, market={self.market}, "
            f"trading={self.is_trading_day})"
        )


class IndexDaily(Base):
    """指数日线(沪深300/中证500/中证1000等)。

    DDL对应: index_daily（域1/域2边界）
    """

    __tablename__ = "index_daily"
    __table_args__ = {"extend_existing": True}

    index_code: Mapped[str] = mapped_column(
        String(12),
        primary_key=True,
        comment="指数代码，如 000300.SH",
    )
    trade_date: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
        comment="交易日期",
    )
    open: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="开盘价",
    )
    high: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="最高价",
    )
    low: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="最低价",
    )
    close: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="收盘价",
    )
    pre_close: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="昨收价",
    )
    pct_change: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="涨跌幅（%）",
    )
    volume: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="成交量（手）",
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2),
        nullable=True,
        comment="成交额（千元）",
    )

    def __repr__(self) -> str:
        return f"IndexDaily(index={self.index_code}, date={self.trade_date}, close={self.close})"
