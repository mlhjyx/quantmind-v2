"""因子库 schema。

对应 API 路由: /api/factors/*
数据来源: FactorService / FactorAnalyzer / FactorGatePipeline。

设计文档:
  - docs/DEV_FACTOR_MINING.md: Factor Gate G1-G8
  - docs/DEV_FRONTEND_UI.md: 因子库页面 (6 Tab 所需数据)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 因子列表 / 概览
# ---------------------------------------------------------------------------


class FactorSummary(BaseModel):
    """因子摘要（列表页单行）。"""

    id: str = Field(..., description="因子标识（通常与 factor_name 相同）")
    name: str = Field(..., description="因子名称")
    category: str = Field(default="", description="因子类别: momentum/value/liquidity等")
    direction: int = Field(default=1, description="因子方向: 1=正向 / -1=反向")
    status: str = Field(default="active", description="状态: active/new/degraded/retired")
    ic: float = Field(default=0.0, description="IC均值")
    ir: float = Field(default=0.0, description="IC_IR（IC信息比）")
    t_stat: float = Field(default=0.0, description="t统计量")
    fdr_t_stat: float = Field(default=0.0, description="FDR校正后t统计量")
    recommended_freq: str = Field(default="月度", description="推荐调仓频率")
    description: str | None = Field(default=None, description="因子描述")
    source: str | None = Field(default=None, description="因子来源")


class FactorListItem(BaseModel):
    """因子列表项（含 IC 统计）。"""

    name: str = Field(..., description="因子名称")
    category: str | None = Field(default=None, description="因子类别")
    direction: int | None = Field(default=None, description="因子方向")
    status: str | None = Field(default=None, description="因子状态")
    description: str | None = Field(default=None, description="因子描述")
    ic_mean: float | None = Field(default=None, description="IC均值")
    ic_ir: float | None = Field(default=None, description="IC信息比")
    t_stat: float | None = Field(default=None, description="t统计量")
    data_points: int = Field(default=0, description="IC数据点数")
    created_at: str | None = Field(default=None, description="创建时间")


class FactorStatsOverview(BaseModel):
    """因子库统计概览（Dashboard 因子卡片）。"""

    total: int = Field(default=0, description="因子总数")
    active: int = Field(default=0, description="活跃因子数")
    candidate: int = Field(default=0, description="候选因子数")
    warning: int = Field(default=0, description="预警因子数")
    critical: int = Field(default=0, description="严重异常因子数")
    retired: int = Field(default=0, description="已退役因子数")
    top_factors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top因子列表（按IC绝对值降序）",
    )


# ---------------------------------------------------------------------------
# 因子健康度
# ---------------------------------------------------------------------------


class FactorHealthItem(BaseModel):
    """单因子健康度指标。"""

    name: str = Field(..., description="因子名称")
    ic_mean_30d: float | None = Field(default=None, description="最近30天IC均值")
    ic_mean_90d: float | None = Field(default=None, description="最近90天IC均值")
    ic_trend: str = Field(
        default="unknown",
        description="IC趋势: improving/stable/degrading/unknown",
    )
    decay_warning: bool = Field(
        default=False,
        description="IC衰减>50%警告",
    )
    coverage_pct: float | None = Field(default=None, description="最新截面覆盖率(%)")
    status: str = Field(default="active", description="因子状态")


class FactorHealthResponse(BaseModel):
    """Active 因子健康度概览。"""

    as_of: str = Field(..., description="数据截止日期")
    active_count: int = Field(..., description="活跃因子数量")
    factors: list[FactorHealthItem] = Field(
        default_factory=list,
        description="各因子健康指标列表",
    )


# ---------------------------------------------------------------------------
# 因子相关性
# ---------------------------------------------------------------------------


class FactorCorrelationResponse(BaseModel):
    """因子间截面相关性矩阵。"""

    factor_names: list[str] = Field(default_factory=list, description="因子名称列表")
    matrix: list[list[float]] = Field(
        default_factory=list,
        description="N x N Spearman相关系数矩阵",
    )
    period: dict[str, str] = Field(
        default_factory=dict,
        description="分析期间: {start, end}",
    )


# ---------------------------------------------------------------------------
# IC 趋势
# ---------------------------------------------------------------------------


class FactorICTrendItem(BaseModel):
    """因子 IC 时序单点。"""

    trade_date: str = Field(..., description="交易日期")
    ic_value: float | None = Field(default=None, description="IC值")


class FactorICSeriesResponse(BaseModel):
    """因子 IC 时序数据。"""

    factor_name: str = Field(..., description="因子名称")
    ic_series: list[FactorICTrendItem] = Field(
        default_factory=list,
        description="IC时序列表",
    )


# ---------------------------------------------------------------------------
# 因子详情
# ---------------------------------------------------------------------------


class FactorStatsDetail(BaseModel):
    """因子 IC 统计摘要。"""

    ic_mean: float | None = Field(default=None, description="IC均值")
    ic_std: float | None = Field(default=None, description="IC标准差")
    ic_ir: float | None = Field(default=None, description="IC信息比")
    t_stat: float | None = Field(default=None, description="t统计量")
    data_points: int = Field(default=0, description="数据点数")


class FactorDetailResponse(BaseModel):
    """单因子详情（概览 + IC统计 + IC时序）。"""

    factor_name: str = Field(..., description="因子名称")
    category: str | None = Field(default=None, description="因子类别")
    direction: int | None = Field(default=None, description="因子方向")
    status: str | None = Field(default=None, description="因子状态")
    description: str | None = Field(default=None, description="因子描述")
    stats: FactorStatsDetail = Field(
        default_factory=FactorStatsDetail,
        description="IC统计摘要",
    )
    ic_series: list[FactorICTrendItem] = Field(
        default_factory=list,
        description="IC时序列表",
    )
    analysis_period: dict[str, Any] = Field(
        default_factory=dict,
        description="分析期间: {start, end, forward_days}",
    )
    created_at: str | None = Field(default=None, description="创建时间")


# ---------------------------------------------------------------------------
# 因子评估报告（6 Tab）
# ---------------------------------------------------------------------------


class FactorReportOverview(BaseModel):
    """因子报告 Tab1: 概览。"""

    category: str | None = Field(default=None, description="因子类别")
    direction: int | None = Field(default=None, description="因子方向")
    status: str | None = Field(default=None, description="因子状态")
    description: str | None = Field(default=None, description="因子描述")
    created_at: str | None = Field(default=None, description="创建时间")


class FactorReportICAnalysis(BaseModel):
    """因子报告 Tab2: IC分析。"""

    stats: FactorStatsDetail = Field(
        default_factory=FactorStatsDetail,
        description="IC统计摘要",
    )
    ic_series: list[FactorICTrendItem] = Field(
        default_factory=list,
        description="IC时序列表",
    )


class FactorReportResponse(BaseModel):
    """因子完整评估报告（6 Tab 数据）。"""

    factor_name: str = Field(..., description="因子名称")
    analysis_period: dict[str, str] = Field(
        default_factory=dict,
        description="分析期间",
    )
    overview: FactorReportOverview = Field(
        default_factory=FactorReportOverview,
        description="Tab1: 概览",
    )
    ic_analysis: FactorReportICAnalysis = Field(
        default_factory=FactorReportICAnalysis,
        description="Tab2: IC分析",
    )
    quintile_returns: dict[str, Any] = Field(
        default_factory=dict,
        description="Tab3: 分组收益",
    )
    gate_report: dict[str, Any] = Field(
        default_factory=dict,
        description="Tab4: Gate G1-G8报告",
    )
    ic_decay: dict[str, Any] = Field(
        default_factory=dict,
        description="Tab5: IC衰减（1/5/10/20日）",
    )
    backtest_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Tab6: 历史回测摘要",
    )
