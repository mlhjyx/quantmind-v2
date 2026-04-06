"""策略管理 schema。

对应 API 路由: /api/strategies/*
设计文档: CLAUDE.md 策略版本化纪律 + docs/DEV_BACKEND.md 策略服务。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateStrategyRequest(BaseModel):
    """创建策略的请求体。"""

    name: str = Field(..., min_length=1, description="策略名称")
    market: str = Field(..., description="市场类型: astock/forex")
    config: dict[str, Any] = Field(default_factory=dict, description="策略初始配置(JSONB)")
    factor_names: list[str] = Field(default_factory=list, description="因子名称列表")


class UpdateStrategyRequest(BaseModel):
    """更新策略配置的请求体。"""

    name: str | None = Field(default=None, description="策略名称")
    status: str | None = Field(
        default=None,
        description="状态: active/paused/draft/archived",
    )
    factor_config: dict[str, Any] | None = Field(
        default=None,
        description="因子配置(JSONB)",
    )
    backtest_config: dict[str, Any] | None = Field(
        default=None,
        description="回测配置(JSONB)",
    )


class CreateVersionRequest(BaseModel):
    """创建新配置版本的请求体。"""

    config: dict[str, Any] = Field(..., description="新版本配置(JSONB)")
    changelog: str = Field(..., min_length=1, description="变更说明")


class RollbackRequest(BaseModel):
    """回滚版本的请求体。"""

    target_version: int = Field(..., ge=1, description="目标版本号")


class TriggerBacktestRequest(BaseModel):
    """触发回测的请求体。"""

    start_date: str = Field(..., description="回测开始日期(YYYY-MM-DD)")
    end_date: str = Field(..., description="回测结束日期(YYYY-MM-DD)")
    top_n: int = Field(default=20, ge=1, le=100, description="选股数量")
    rebalance_freq: str = Field(
        default="monthly",
        description="调仓频率: daily/weekly/biweekly/monthly",
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="其他回测参数")


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class StrategyResponse(BaseModel):
    """策略列表项响应。"""

    id: str = Field(..., description="策略ID")
    name: str = Field(..., description="策略名称")
    market: str | None = Field(default=None, description="市场类型: astock/forex")
    status: str | None = Field(default=None, description="策略状态")
    active_version: int | None = Field(default=None, description="当前激活版本号")
    created_at: str | None = Field(default=None, description="创建时间")


class StrategyVersionResponse(BaseModel):
    """策略配置版本响应。"""

    version: int = Field(..., description="版本号")
    strategy_id: str = Field(..., description="策略ID")
    config: dict[str, Any] = Field(default_factory=dict, description="版本配置(JSONB)")
    changelog: str = Field(default="", description="变更说明")
    created_at: str | None = Field(default=None, description="版本创建时间")


class StrategyDetailResponse(BaseModel):
    """策略详情（基本信息 + 当前配置 + 版本历史）。"""

    strategy: StrategyResponse = Field(..., description="策略基本信息")
    active_config: dict[str, Any] = Field(
        default_factory=dict,
        description="当前激活版本的配置",
    )
    version_history: list[StrategyVersionResponse] = Field(
        default_factory=list,
        description="版本历史列表",
    )


class StrategyFactorsResponse(BaseModel):
    """策略关联因子响应。"""

    strategy_id: str = Field(..., description="策略ID")
    factor_names: list[str] = Field(default_factory=list, description="因子名称列表")
    factors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="因子详情列表（含 name/category/direction/ic_decay_halflife）",
    )
