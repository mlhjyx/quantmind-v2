"""SQLAlchemy模型: mining_knowledge 表（扩展版）

对应DDL: docs/QUANTMIND_V2_DDL_FINAL.sql 域10 mining_knowledge
表用途: 因子挖掘知识库，记录每次挖掘尝试（成功/失败），供 Idea Agent 读取
       避免重复挖掘已失败的方向，实现 AlphaAgent 论文中的失败记忆注入

域10 原有 mining_knowledge 表基于 Sprint 1.18 扩展:
  - 新增 failure_node: 记录在哪个 Gate 节点失败（G1-G8 或 approved/entry）
  - 新增 factor_hash: AST结构哈希（与 gp_approval_queue.ast_hash 一致）
  - 新增 run_id: 关联 pipeline_runs（可选，手动挖掘时为 NULL）
  - 新增 tags: 标签数组，便于 Idea Agent 按类别查询
  - 新增 ic_stats: IC详细统计 JSONB（ic_mean/ic_std/t_stat/ic_ir）
  - 原 failure_reason JSONB: 结构化失败原因 {"gate":"G3","ic_mean":0.008}

failure_mode 分类（AlphaAgent论文启示）:
  - ic_insufficient: IC未达阈值 (Gate G3)
  - correlation_high: 与现有因子相关过高 (Gate G6)
  - neutralization_decay: 中性化后IC大幅衰减 (Gate G5)
  - hypothesis_invalid: 经济学假设不成立（人工判断）
  - coverage_low: 覆盖率不足 (Gate G2)
  - turnover_high: 隐含换手率过高 (Gate G8)
  - stability_low: IC稳定性不足 (Gate G7)
  - compute_fail: 因子计算本身失败 (Gate G1)

Sprint 1.18 alpha-miner
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pipeline_run import Base, PipelineRun


class MiningKnowledge(Base):
    """因子挖掘知识库条目。

    DDL对应: mining_knowledge（域10，因子挖掘）
    Sprint 1.18扩展: failure_node / factor_hash / run_id / tags / ic_stats

    字段说明:
        id: UUID主键
        factor_name: 因子名称（可选，GP产出因子无固定名称）
        factor_hash: AST结构哈希，与 gp_approval_queue.ast_hash 一致
        expression: FactorDSL表达式字符串
        hypothesis: 经济学假设（文字说明）
        ic_mean: IC均值
        ic_stats: IC详细统计 {ic_mean, ic_std, t_stat, ic_ir, ic_win_rate}
        status: success/failed
        failure_node: 失败所在Pipeline节点 (G1-G8 | approved | entry)
        failure_reason: 结构化失败原因 {"gate":"G3","ic_mean":0.008}
        failure_mode: 失败模式分类（便于 Idea Agent 按模式查询）
        spearman_max_existing: 与现有因子池最大Spearman相关性
        source: 来源引擎 gp/bruteforce/llm/manual
        run_id: 关联 pipeline_runs.run_id（手动挖掘为 NULL）
        tags: 标签数组，如 ["momentum", "reversal", "volume"]
        created_at: 创建时间
    """

    __tablename__ = "mining_knowledge"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID主键",
    )
    factor_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="因子名称（GP产出因子可能无固定名称）",
    )
    factor_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="AST结构哈希，与 gp_approval_queue.ast_hash 一致，用于跨表去重",
    )
    expression: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="FactorDSL表达式字符串",
    )
    hypothesis: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="经济学假设文字说明",
    )
    ic_mean: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="IC均值（原始IC，中性化前）",
    )
    ic_stats: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="IC详细统计: {ic_mean, ic_std, t_stat, ic_ir, ic_win_rate}",
    )
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="结果状态: success=进入审批/通过 | failed=被Gate拒绝",
    )
    failure_node: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="失败的Pipeline节点: G1/G2/G3/G4/G5/G6/G7/G8 | approved | entry",
    )
    failure_reason: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment='结构化失败原因: {"gate":"G3","ic_mean":0.008,"threshold":0.015}',
    )
    failure_mode: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
        comment=(
            "失败模式分类: ic_insufficient/correlation_high/neutralization_decay/"
            "hypothesis_invalid/coverage_low/turnover_high/stability_low/compute_fail"
        ),
    )
    spearman_max_existing: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="与现有因子池最大Spearman相关性（Gate G6检查值）",
    )
    source: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="来源引擎: gp/bruteforce/llm/manual",
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_runs.run_id", ondelete="SET NULL"),
        nullable=True,
        comment="关联 pipeline_runs.run_id，手动挖掘为 NULL",
    )
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="标签数组，如 ['momentum', 'reversal']，便于 Idea Agent 分类查询",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="写入知识库时间",
    )

    # 关联
    pipeline_run: Mapped[PipelineRun | None] = relationship(
        "PipelineRun",
        foreign_keys=[run_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"MiningKnowledge(id={str(self.id)[:8]}, "
            f"status={self.status}, node={self.failure_node}, "
            f"source={self.source})"
        )

    @classmethod
    def from_gate_failure(
        cls,
        expression: str,
        failure_node: str,
        failure_reason: dict[str, Any],
        source: str,
        factor_hash: str | None = None,
        factor_name: str | None = None,
        ic_mean: float | None = None,
        ic_stats: dict[str, Any] | None = None,
        spearman_max_existing: float | None = None,
        run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        hypothesis: str | None = None,
    ) -> MiningKnowledge:
        """从 Gate 失败结果构建知识库条目。

        Args:
            expression: DSL表达式字符串。
            failure_node: 失败节点（G1-G8）。
            failure_reason: 结构化失败原因字典。
            source: 来源引擎 gp/bruteforce/llm/manual。
            factor_hash: AST哈希（可选）。
            factor_name: 因子名称（可选）。
            ic_mean: IC均值（G3失败时有值）。
            ic_stats: IC详细统计（可选）。
            spearman_max_existing: 与现有因子相关性（G6失败时有值）。
            run_id: 关联的运行ID（可选）。
            tags: 标签列表（可选）。
            hypothesis: 经济学假设（可选）。

        Returns:
            MiningKnowledge实例（未提交）。
        """
        # 推断 failure_mode
        failure_mode = _infer_failure_mode(failure_node, failure_reason)

        return cls(
            expression=expression,
            factor_hash=factor_hash,
            factor_name=factor_name,
            hypothesis=hypothesis,
            ic_mean=ic_mean,
            ic_stats=ic_stats,
            status="failed",
            failure_node=failure_node,
            failure_reason=failure_reason,
            failure_mode=failure_mode,
            spearman_max_existing=spearman_max_existing,
            source=source,
            run_id=run_id,
            tags=tags,
        )

    @classmethod
    def from_approval(
        cls,
        expression: str,
        source: str,
        ic_mean: float | None = None,
        ic_stats: dict[str, Any] | None = None,
        factor_hash: str | None = None,
        factor_name: str | None = None,
        spearman_max_existing: float | None = None,
        run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        hypothesis: str | None = None,
    ) -> MiningKnowledge:
        """从通过审批的因子构建知识库条目（status=success）。

        Args:
            expression: DSL表达式字符串。
            source: 来源引擎。
            ic_mean: IC均值。
            ic_stats: IC详细统计。
            factor_hash: AST哈希（可选）。
            factor_name: 因子名称（可选）。
            spearman_max_existing: 与现有因子相关性。
            run_id: 关联的运行ID（可选）。
            tags: 标签列表（可选）。
            hypothesis: 经济学假设（可选）。

        Returns:
            MiningKnowledge实例（未提交）。
        """
        return cls(
            expression=expression,
            factor_hash=factor_hash,
            factor_name=factor_name,
            hypothesis=hypothesis,
            ic_mean=ic_mean,
            ic_stats=ic_stats,
            status="success",
            failure_node="approved",
            failure_reason=None,
            failure_mode=None,
            spearman_max_existing=spearman_max_existing,
            source=source,
            run_id=run_id,
            tags=tags,
        )


# ---------------------------------------------------------------------------
# 失败模式推断（私有辅助）
# ---------------------------------------------------------------------------

_GATE_TO_MODE: dict[str, str] = {
    "G1": "compute_fail",
    "G2": "coverage_low",
    "G3": "ic_insufficient",
    "G4": "ic_insufficient",  # t_stat 不足，同属IC不足类
    "G5": "neutralization_decay",
    "G6": "correlation_high",
    "G7": "stability_low",
    "G8": "turnover_high",
}


def _infer_failure_mode(
    failure_node: str,
    failure_reason: dict[str, Any],
) -> str | None:
    """根据失败节点推断失败模式分类。

    Args:
        failure_node: 失败的 Gate 节点，如 "G3"。
        failure_reason: 结构化失败原因字典。

    Returns:
        失败模式字符串，或 None（节点不在映射中）。
    """
    # 优先从 failure_reason 中读取显式 failure_mode
    if explicit := failure_reason.get("failure_mode"):
        return str(explicit)

    return _GATE_TO_MODE.get(failure_node)
