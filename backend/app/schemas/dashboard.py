"""Dashboard 页面响应 schema。

对应 API 路由: /api/dashboard/*
数据来源: DashboardService（7指标卡 + NAV时序 + 待处理事项 + 行情 + 预警 + 月度收益 + 行业分布）。
"""

from __future__ import annotations

from datetime import date  # noqa: F401 — used in annotations

from pydantic import BaseModel, Field


class DashboardSummaryResponse(BaseModel):
    """Dashboard 7 指标卡数据。"""

    nav: float | None = Field(default=None, description="最新净值")
    daily_return: float | None = Field(default=None, description="当日收益率")
    cumulative_return: float | None = Field(default=None, description="累计收益率")
    sharpe: float | None = Field(default=None, description="Sharpe比率")
    mdd: float | None = Field(default=None, description="最大回撤")
    position_count: int | None = Field(default=None, description="当前持仓数量")
    cash_ratio: float | None = Field(default=None, description="现金占比")
    trade_date: str | None = Field(default=None, description="数据日期")


class NAVPointResponse(BaseModel):
    """NAV 时间序列单点。"""

    trade_date: str = Field(..., description="交易日期")
    nav: float = Field(..., description="净值")
    daily_return: float | None = Field(default=None, description="日收益率")
    cumulative_return: float | None = Field(default=None, description="累计收益率")
    drawdown: float | None = Field(default=None, description="当前回撤")


class PendingActionResponse(BaseModel):
    """待处理事项（熔断/健康异常/管道失败）。"""

    type: str = Field(..., description="事项类型: circuit_breaker/health/pipeline")
    severity: str = Field(..., description="严重程度: P0/P1/P2/P3")
    message: str = Field(..., description="事项描述")
    time: str | None = Field(default=None, description="触发时间")


class MarketTickerResponse(BaseModel):
    """市场行情栏单条数据。"""

    label: str = Field(..., description="显示名称（如 沪深300）")
    code: str = Field(..., description="指数代码（如 000300.SH）")
    value: float | None = Field(default=None, description="当前点位/金额")
    change_pct: float | None = Field(default=None, description="涨跌幅(%)")
    is_up: bool = Field(default=True, description="是否上涨")


class AlertResponse(BaseModel):
    """活跃预警记录。"""

    level: str = Field(..., description="预警级别: P0/P1/P2/P3")
    title: str = Field(..., description="预警标题")
    desc: str | None = Field(default=None, description="预警描述")
    time: str | None = Field(default=None, description="触发时间")
    color: str | None = Field(default=None, description="显示颜色（前端渲染用）")


class StrategyOverviewResponse(BaseModel):
    """策略概览（Dashboard 策略卡片）。"""

    id: str = Field(..., description="策略ID")
    name: str = Field(..., description="策略名称")
    status: str | None = Field(default=None, description="策略状态")
    market: str | None = Field(default=None, description="市场类型")
    sharpe: float | None = Field(default=None, description="Sharpe比率")
    pnl: float | None = Field(default=None, description="累计盈亏")
    mdd: float | None = Field(default=None, description="最大回撤")


class MonthlyReturnsResponse(BaseModel):
    """月度收益矩阵（热力图数据）。

    key 为年份字符串，value 为 12 个月收益率（无数据为 None）。
    """

    data: dict[str, list[float | None]] = Field(
        default_factory=dict,
        description="月度收益矩阵: {year: [jan, feb, ..., dec]}",
    )


class IndustryDistributionResponse(BaseModel):
    """行业分布饼图单条数据。"""

    name: str = Field(..., description="行业名称")
    pct: float = Field(..., description="占比(%)")
    color: str | None = Field(default=None, description="饼图颜色")
