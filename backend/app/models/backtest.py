"""SQLAlchemy模型: 域9 回测引擎表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域9
包含: backtest_run / backtest_trades

注: 域9共6张表(backtest_run/backtest_daily_nav/backtest_trades/
    backtest_holdings/backtest_wf_windows)，本文件覆盖最常用的2张。
    其余表可按需追加。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BacktestRun(Base):
    """回测运行记录。

    DDL对应: backtest_run（域9）
    包含基础指标(annual_return/sharpe/mdd) + Review新增12项指标。
    """

    __tablename__ = "backtest_run"
    __table_args__ = {"extend_existing": True}

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID主键",
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="策略ID（关联strategy.id）",
    )
    name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="回测名称",
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="完整回测配置JSONB",
    )
    factor_list: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        comment="因子列表",
    )
    status: Mapped[str | None] = mapped_column(
        String(20),
        default="pending",
        comment="状态: pending/running/success/failed",
    )
    # 基础指标
    annual_return: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="年化收益率",
    )
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Sharpe比率",
    )
    max_drawdown: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="最大回撤",
    )
    excess_return: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="超额收益",
    )
    # Review新增12项指标
    calmar_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Calmar比率(年化收益/最大回撤)",
    )
    sortino_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Sortino比率",
    )
    information_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="信息比率",
    )
    beta: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Beta系数",
    )
    win_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="胜率",
    )
    profit_loss_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="盈亏比",
    )
    annual_turnover: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="年化换手率",
    )
    max_consecutive_loss_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="最大连续亏损天数",
    )
    sharpe_ci_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Sharpe Bootstrap 95% CI下界",
    )
    sharpe_ci_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="Sharpe Bootstrap 95% CI上界",
    )
    avg_overnight_gap: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="开盘跳空平均偏差",
    )
    position_deviation: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="实际vs理论仓位偏差",
    )
    cost_sensitivity_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="成本敏感性: {0.5x:{sharpe,return,mdd}, ...}",
    )
    annual_breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="年度分解: 每年收益/Sharpe/MDD",
    )
    market_state_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="市场状态分段绩效: 牛/熊/震荡",
    )
    # 元数据
    total_trades: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="总交易次数",
    )
    start_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="回测起始日期",
    )
    end_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="回测结束日期",
    )
    elapsed_sec: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="运行耗时（秒）",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="失败时的错误信息",
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"BacktestRun(run_id={str(self.run_id)[:8]}, "
            f"name={self.name}, status={self.status}, "
            f"sharpe={self.sharpe_ratio})"
        )


class BacktestTrade(Base):
    """回测交易明细。

    DDL对应: backtest_trades（域9）
    shares为已整手约束后的股数。
    """

    __tablename__ = "backtest_trades"
    __table_args__ = {"extend_existing": True}

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("backtest_run.run_id", ondelete="CASCADE"),
        primary_key=True,
        comment="关联backtest_run.run_id",
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="交易UUID",
    )
    signal_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="信号生成日期",
    )
    exec_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="执行日期",
    )
    stock_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="股票代码",
    )
    side: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
        comment="方向: buy/sell",
    )
    shares: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="成交股数（已整手约束）",
    )
    exec_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="成交价格（元）",
    )
    slippage_bps: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        comment="滑点（基点）",
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
    total_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
        comment="总交易成本（元）",
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="拒绝原因: limit_up/limit_down/suspended/insufficient_fund",
    )

    def __repr__(self) -> str:
        return (
            f"BacktestTrade(run={str(self.run_id)[:8]}, "
            f"code={self.stock_code}, side={self.side}, "
            f"shares={self.shares}, price={self.exec_price})"
        )
