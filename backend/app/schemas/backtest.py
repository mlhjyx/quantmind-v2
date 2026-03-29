"""回测 schema。

对应 API 路由: /api/backtest/*
设计文档: docs/DEV_BACKTEST_ENGINE.md（6条硬规则 + 12项指标）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class BacktestRunRequest(BaseModel):
    """提交回测任务的请求体。"""

    strategy_id: str = Field(..., description="策略ID")
    start_date: date = Field(..., description="回测起始日期")
    end_date: date = Field(..., description="回测结束日期")
    initial_capital: float = Field(
        default=1_000_000.0,
        ge=10_000,
        description="初始资金",
    )
    benchmark: str = Field(default="000300.SH", description="基准指数代码")
    universe_preset: str = Field(default="all_a", description="股票池预设")
    rebalance_freq: str = Field(
        default="weekly",
        description="调仓频率: daily/weekly/biweekly/monthly",
    )
    slippage_model: str = Field(
        default="volume_impact",
        description="滑点模型: fixed/volume_impact",
    )
    cost_multiplier: float = Field(
        default=1.0,
        ge=0.0,
        le=5.0,
        description="成本倍数",
    )
    extra_config: dict[str, Any] = Field(
        default_factory=dict,
        description="额外配置(JSONB)",
    )


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class BacktestRunResponse(BaseModel):
    """提交回测任务的响应。"""

    run_id: str = Field(..., description="回测运行ID")
    status: str = Field(..., description="任务状态: queued/running")
    message: str = Field(default="", description="提示信息")


class BacktestStatusResponse(BaseModel):
    """回测状态查询响应。"""

    run_id: str = Field(..., description="回测运行ID")
    status: str = Field(..., description="运行状态: running/completed/failed")
    progress: float | None = Field(default=None, description="进度 0.0~1.0")
    error_msg: str | None = Field(default=None, description="错误信息")
    created_at: str | None = Field(default=None, description="创建时间")
    finished_at: str | None = Field(default=None, description="完成时间")


class BacktestResultResponse(BaseModel):
    """回测结果响应。"""

    run_id: str = Field(..., description="回测运行ID")
    status: str = Field(..., description="运行状态")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="绩效指标（Sharpe/MDD/年化收益等）",
    )
    trades_count: int = Field(default=0, description="交易笔数")
    created_at: str | None = Field(default=None, description="创建时间")
    finished_at: str | None = Field(default=None, description="完成时间")


class TradeRecord(BaseModel):
    """交易明细记录。"""

    trade_date: str = Field(..., description="交易日期")
    symbol: str = Field(..., description="证券代码")
    direction: str = Field(..., description="方向: buy/sell")
    quantity: int = Field(..., description="数量（股）")
    price: float = Field(..., description="成交价格")
    amount: float = Field(..., description="成交金额")
    commission: float = Field(default=0.0, description="佣金")
    slippage_bps: float = Field(default=0.0, description="滑点(bps)")


class SensitivityRow(BaseModel):
    """成本敏感性分析单行。"""

    cost_multiplier: float = Field(..., description="成本倍数")
    annual_return: float | None = Field(default=None, description="年化收益率")
    sharpe_ratio: float | None = Field(default=None, description="Sharpe比率")
    max_drawdown: float | None = Field(default=None, description="最大回撤")
    calmar_ratio: float | None = Field(default=None, description="Calmar比率")
