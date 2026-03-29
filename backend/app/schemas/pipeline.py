"""Pipeline（AI因子挖掘）schema。

对应 API 路由: /api/pipeline/*
设计文档:
  - docs/DEV_AI_EVOLUTION.md §4: Pipeline 完整流程
  - docs/GP_CLOSED_LOOP_DESIGN.md §6.2: 人工审批
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    """审批通过请求体。"""

    decision_reason: str | None = Field(
        default=None,
        description="审批理由（可选）",
    )


class RejectRequest(BaseModel):
    """审批拒绝请求体。"""

    decision_reason: str = Field(
        ...,
        min_length=5,
        description="拒绝理由（必填，用于GP下轮学习）",
    )


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class PipelineStatusResponse(BaseModel):
    """Pipeline 当前运行状态。"""

    active_run_id: str | None = Field(default=None, description="当前运行ID")
    active_engine: str | None = Field(default=None, description="引擎类型: gp/bruteforce/llm")
    status: str = Field(default="idle", description="状态: idle/running/completed/failed")
    current_node: str | None = Field(default=None, description="当前执行节点")
    node_statuses: dict[str, str] = Field(
        default_factory=dict,
        description="各节点状态映射",
    )
    progress: dict[str, int] = Field(
        default_factory=dict,
        description="进度: {total_candidates, passed_gate, pending_approval}",
    )
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="完成时间")
    error: str | None = Field(default=None, description="错误信息")


class PipelineRunSummary(BaseModel):
    """Pipeline 运行历史单条。"""

    run_id: str = Field(..., description="运行ID")
    engine: str = Field(..., description="引擎类型")
    status: str = Field(..., description="运行状态")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="完成时间")
    elapsed_seconds: int | None = Field(default=None, description="耗时(秒)")
    stats: dict[str, Any] = Field(default_factory=dict, description="运行统计")
    error_message: str | None = Field(default=None, description="错误信息")


class PipelineStageResponse(BaseModel):
    """Pipeline 单阶段状态。"""

    name: str = Field(..., description="阶段名称")
    status: str = Field(..., description="阶段状态: pending/running/completed/failed")
    duration_s: float | None = Field(default=None, description="耗时(秒)")
    result: dict[str, Any] | None = Field(default=None, description="阶段结果")


class ApprovalItemResponse(BaseModel):
    """候选因子审批项。"""

    id: int = Field(..., description="审批记录ID")
    factor_name: str = Field(..., description="因子名称")
    factor_expr: str | None = Field(default=None, description="因子表达式")
    ast_hash: str | None = Field(default=None, description="AST哈希（去重用）")
    gate_result: dict[str, Any] | None = Field(
        default=None,
        description="Gate G1-G8检验结果",
    )
    sharpe_1y: float | None = Field(default=None, description="1年Sharpe")
    sharpe_5y: float | None = Field(default=None, description="5年Sharpe")
    backtest_report: dict[str, Any] | None = Field(
        default=None,
        description="回测报告摘要",
    )
    status: str = Field(default="pending", description="审批状态: pending/approved/rejected")
    decision_by: str | None = Field(default=None, description="审批人")
    decision_reason: str | None = Field(default=None, description="审批理由")
    created_at: str | None = Field(default=None, description="创建时间")
    decided_at: str | None = Field(default=None, description="审批时间")


class PipelineRunDetailResponse(BaseModel):
    """Pipeline 单次运行详情（含候选因子列表）。"""

    run_id: str = Field(..., description="运行ID")
    engine: str = Field(..., description="引擎类型")
    status: str = Field(..., description="运行状态")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="完成时间")
    config: dict[str, Any] | None = Field(default=None, description="运行配置")
    stats: dict[str, Any] | None = Field(default=None, description="运行统计")
    error_message: str | None = Field(default=None, description="错误信息")
    candidates: list[ApprovalItemResponse] = Field(
        default_factory=list,
        description="候选因子列表",
    )
    candidates_count: dict[str, int] = Field(
        default_factory=dict,
        description="候选因子计数: {total, pending, approved, rejected}",
    )
