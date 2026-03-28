"""SQLAlchemy模型: gp_approval_queue 表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域12
表用途: GP引擎产出因子的人工审批队列，通过完整Gate G1-G8后进入

注意与 approval_queue（域11，AI进化闭环审批）区分:
  - 域11 approval_queue: 审批类型多样（factor_entry/strategy_deploy/param_change）
  - 域12 gp_approval_queue: 专用于GP/BruteForce/LLM产出的单个因子审批

Sprint 1.17 alpha-miner
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pipeline_run import Base, PipelineRun


class GPApprovalQueue(Base):
    """GP引擎产出因子的人工审批队列。

    DDL对应: gp_approval_queue（域12，GP因子挖掘Pipeline）

    字段说明:
        id: SERIAL主键
        run_id: 关联pipeline_runs.run_id（外键）
        factor_name: 建议因子名称，如 gp_ts_mean_cs_rank_20
        factor_expr: FactorDSL表达式字符串
        ast_hash: ExprNode.to_ast_hash()结果（跨队列去重）
        gate_report: G1-G8详细结果 {G1:{passed:bool,reason:str}, ...}
        status: 审批状态 pending/approved/rejected/hold
        reviewer_notes: 审批备注
        created_at: 创建时间
        reviewed_at: 审批时间
        reviewed_by: 审批人标识 'user'|'auto'|agent名称
    """

    __tablename__ = "gp_approval_queue"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="SERIAL主键",
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        comment="关联pipeline_runs.run_id",
    )
    factor_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="建议因子名称，如 gp_ts_mean_cs_rank_20",
    )
    factor_expr: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="FactorDSL表达式字符串",
    )
    ast_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="ExprNode.to_ast_hash()结果，用于跨队列去重",
    )
    gate_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="G1-G8详细结果 {G1:{passed:bool,reason:str}, ..., G8:...}",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="审批状态: pending/approved/rejected/hold",
    )
    reviewer_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="审批备注（人工或auto）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="进入审批队列的时间",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成审批的时间",
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="审批人标识: 'user' | 'auto' | agent名称",
    )

    # 关联关系
    pipeline_run: Mapped[PipelineRun] = relationship(
        "PipelineRun",
        foreign_keys=[run_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"GPApprovalQueue(id={self.id}, "
            f"factor={self.factor_name}, status={self.status}, "
            f"hash={self.ast_hash[:8] if self.ast_hash else '?'})"
        )

    @property
    def is_pending(self) -> bool:
        """是否处于待审批状态。"""
        return self.status == "pending"

    @property
    def is_approved(self) -> bool:
        """是否已通过审批。"""
        return self.status == "approved"

    @classmethod
    def from_gp_result(
        cls,
        run_id: uuid.UUID,
        factor_name: str,
        factor_expr: str,
        ast_hash: str,
        gate_report: dict[str, Any],
    ) -> GPApprovalQueue:
        """从GP结果构建审批队列条目。

        Args:
            run_id: 关联的pipeline_runs.run_id。
            factor_name: 建议因子名称。
            factor_expr: DSL表达式字符串。
            ast_hash: ExprNode的AST哈希。
            gate_report: Gate G1-G8完整报告字典。

        Returns:
            GPApprovalQueue实例（未提交，需调用方 session.add() + commit）。
        """
        return cls(
            run_id=run_id,
            factor_name=factor_name,
            factor_expr=factor_expr,
            ast_hash=ast_hash,
            gate_report=gate_report,
            status="pending",
        )
