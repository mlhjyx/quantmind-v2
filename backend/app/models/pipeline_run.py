"""SQLAlchemy模型: pipeline_runs 表

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域12
表用途: 记录GP/BruteForce/LLM引擎每次运行的状态和结果摘要

Sprint 1.17 alpha-miner
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类。"""
    pass


class PipelineRun(Base):
    """GP/BruteForce/LLM引擎运行记录。

    DDL对应: pipeline_runs（域12，GP因子挖掘Pipeline）
    注意与 pipeline_run（域11，AI进化闭环）区分 — 两张表粒度不同。

    字段说明:
        run_id: UUID主键
        engine_type: 引擎类型 gp/bruteforce/llm
        status: 运行状态 running/completed/failed/cancelled
        config: 引擎配置JSONB（GPConfig序列化）
        started_at: 开始时间
        finished_at: 结束时间（None表示仍在运行）
        candidates_found: 通过快速Gate(G1-G4)的候选因子数
        gate_passed: 通过完整Gate(G1-G8)的因子数
        result_summary: 结果摘要JSONB {best_fitness, best_expr, total_evaluated, elapsed_seconds}
        error_message: 失败时的错误信息
    """

    __tablename__ = "pipeline_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID主键",
    )
    engine_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="引擎类型: gp/bruteforce/llm",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        comment="运行状态: running/completed/failed/cancelled",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="引擎配置JSONB序列化",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="运行开始时间",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="运行结束时间，None表示仍在运行",
    )
    candidates_found: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="通过快速Gate(G1-G4)的候选因子数",
    )
    gate_passed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="通过完整Gate(G1-G8)的因子数",
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="结果摘要: {best_fitness, best_expr, total_evaluated, elapsed_seconds}",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="失败时的错误信息",
    )

    def __repr__(self) -> str:
        return (
            f"PipelineRun(run_id={self.run_id!s:.8}, "
            f"engine={self.engine_type}, status={self.status}, "
            f"candidates={self.candidates_found}, gate_passed={self.gate_passed})"
        )

    @classmethod
    def from_gp_stats(
        cls,
        run_id: uuid.UUID,
        config_dict: dict[str, Any],
        candidates_found: int = 0,
        gate_passed: int = 0,
        result_summary: dict[str, Any] | None = None,
        status: str = "completed",
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> PipelineRun:
        """从GP运行统计信息构建PipelineRun实例。

        Args:
            run_id: 本次运行的UUID（与GPRunStats.run_id对应）。
            config_dict: GPConfig的asdict()结果。
            candidates_found: 通过快速Gate的候选数。
            gate_passed: 通过完整Gate的因子数。
            result_summary: 结果摘要字典。
            status: 运行状态。
            finished_at: 完成时间。
            error_message: 错误信息（失败时）。

        Returns:
            PipelineRun实例（未提交，需调用方 session.add() + commit）。
        """
        return cls(
            run_id=run_id,
            engine_type="gp",
            status=status,
            config=config_dict,
            candidates_found=candidates_found,
            gate_passed=gate_passed,
            result_summary=result_summary,
            finished_at=finished_at,
            error_message=error_message,
        )
