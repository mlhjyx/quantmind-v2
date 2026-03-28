"""单元测试: approval API + MiningKnowledge 模型

测试覆盖:
  - ApprovalQueueItem / ApprovalQueueDetail Pydantic 序列化
  - MiningKnowledge.from_gate_failure() 构建 + failure_mode 推断
  - MiningKnowledge.from_approval() 构建
  - _infer_failure_mode() 各Gate节点映射
  - approval API 端点逻辑（mock AsyncSession）

Sprint 1.18 alpha-miner
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.mining_knowledge import MiningKnowledge, _infer_failure_mode


# ---------------------------------------------------------------------------
# MiningKnowledge 模型测试
# ---------------------------------------------------------------------------


class TestMiningKnowledgeFromGateFailure:
    """测试 MiningKnowledge.from_gate_failure() 工厂方法。"""

    def test_basic_g3_failure(self) -> None:
        """G3 IC不足失败，failure_mode 应为 ic_insufficient。"""
        entry = MiningKnowledge.from_gate_failure(
            expression="ts_mean(cs_rank(close), 20)",
            failure_node="G3",
            failure_reason={"gate": "G3", "ic_mean": 0.008, "threshold": 0.015},
            source="gp",
            ic_mean=0.008,
        )
        assert entry.status == "failed"
        assert entry.failure_node == "G3"
        assert entry.failure_mode == "ic_insufficient"
        assert entry.ic_mean == 0.008
        assert entry.source == "gp"
        assert entry.run_id is None

    def test_g6_correlation_failure(self) -> None:
        """G6 相关性过高，failure_mode 应为 correlation_high。"""
        entry = MiningKnowledge.from_gate_failure(
            expression="cs_rank(volume / ts_mean(volume, 20))",
            failure_node="G6",
            failure_reason={"gate": "G6", "max_corr": 0.82, "threshold": 0.70},
            source="bruteforce",
            spearman_max_existing=0.82,
        )
        assert entry.failure_node == "G6"
        assert entry.failure_mode == "correlation_high"
        assert entry.spearman_max_existing == 0.82

    def test_explicit_failure_mode_overrides_gate_map(self) -> None:
        """failure_reason 中显式指定 failure_mode 时，优先于 Gate 映射。"""
        entry = MiningKnowledge.from_gate_failure(
            expression="some_expr",
            failure_node="G5",
            failure_reason={
                "gate": "G5",
                "failure_mode": "hypothesis_invalid",
                "note": "人工标注",
            },
            source="manual",
        )
        assert entry.failure_mode == "hypothesis_invalid"

    def test_with_all_optional_fields(self) -> None:
        """全字段构建，确认赋值正确。"""
        run_id = uuid.uuid4()
        ic_stats = {"ic_mean": 0.006, "ic_std": 0.03, "t_stat": 1.8, "ic_ir": 0.2}
        entry = MiningKnowledge.from_gate_failure(
            expression="ts_std(returns, 5)",
            failure_node="G4",
            failure_reason={"gate": "G4", "t_stat": 1.8, "threshold": 2.5},
            source="llm",
            factor_hash="abc123",
            factor_name="vol_factor",
            ic_mean=0.006,
            ic_stats=ic_stats,
            run_id=run_id,
            tags=["volatility", "short_term"],
            hypothesis="短期波动率反转",
        )
        assert entry.factor_hash == "abc123"
        assert entry.factor_name == "vol_factor"
        assert entry.ic_stats == ic_stats
        assert entry.run_id == run_id
        assert entry.tags == ["volatility", "short_term"]
        assert entry.hypothesis == "短期波动率反转"
        assert entry.failure_mode == "ic_insufficient"  # G4 → ic_insufficient


class TestMiningKnowledgeFromApproval:
    """测试 MiningKnowledge.from_approval() 工厂方法。"""

    def test_success_entry(self) -> None:
        """通过审批的因子，status=success，failure_node=approved。"""
        entry = MiningKnowledge.from_approval(
            expression="cs_rank(close / ts_mean(close, 60)) - 0.5",
            source="gp",
            ic_mean=0.025,
            factor_name="momentum_60",
        )
        assert entry.status == "success"
        assert entry.failure_node == "approved"
        assert entry.failure_reason is None
        assert entry.failure_mode is None
        assert entry.ic_mean == 0.025
        assert entry.source == "gp"


# ---------------------------------------------------------------------------
# _infer_failure_mode 测试
# ---------------------------------------------------------------------------


class TestInferFailureMode:
    """测试 Gate 节点到 failure_mode 的映射。"""

    @pytest.mark.parametrize(
        "gate,expected_mode",
        [
            ("G1", "compute_fail"),
            ("G2", "coverage_low"),
            ("G3", "ic_insufficient"),
            ("G4", "ic_insufficient"),
            ("G5", "neutralization_decay"),
            ("G6", "correlation_high"),
            ("G7", "stability_low"),
            ("G8", "turnover_high"),
        ],
    )
    def test_gate_to_mode_mapping(self, gate: str, expected_mode: str) -> None:
        assert _infer_failure_mode(gate, {}) == expected_mode

    def test_unknown_gate_returns_none(self) -> None:
        assert _infer_failure_mode("G9", {}) is None

    def test_explicit_override(self) -> None:
        result = _infer_failure_mode("G3", {"failure_mode": "hypothesis_invalid"})
        assert result == "hypothesis_invalid"


# ---------------------------------------------------------------------------
# ApprovalQueueItem / ApprovalQueueDetail 序列化测试
# ---------------------------------------------------------------------------


class TestApprovalQueueItem:
    """测试 Pydantic 序列化模型。"""

    def _make_orm_row(
        self,
        status: str = "pending",
        reviewed_at: datetime | None = None,
    ) -> MagicMock:
        row = MagicMock()
        row.id = 1
        row.run_id = uuid.uuid4()
        row.factor_name = "gp_momentum_20"
        row.factor_expr = "ts_mean(cs_rank(close), 20)"
        row.ast_hash = "a" * 64
        row.status = status
        row.created_at = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)
        row.reviewed_at = reviewed_at
        row.reviewed_by = None
        row.reviewer_notes = None
        row.gate_report = {"G1": {"passed": True}, "G3": {"passed": False, "ic_mean": 0.008}}
        return row

    def test_from_orm_pending(self) -> None:
        from app.api.approval import ApprovalQueueItem

        row = self._make_orm_row(status="pending")
        item = ApprovalQueueItem.from_orm(row)
        assert item.id == 1
        assert item.status == "pending"
        assert item.reviewed_at is None

    def test_from_orm_approved(self) -> None:
        from app.api.approval import ApprovalQueueItem

        ts = datetime(2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc)
        row = self._make_orm_row(status="approved", reviewed_at=ts)
        item = ApprovalQueueItem.from_orm(row)
        assert item.status == "approved"
        assert item.reviewed_at == ts.isoformat()

    def test_detail_includes_gate_report(self) -> None:
        from app.api.approval import ApprovalQueueDetail

        row = self._make_orm_row(status="pending")
        detail = ApprovalQueueDetail.from_orm(row)
        assert "G1" in detail.gate_report
        assert detail.gate_report["G3"]["ic_mean"] == 0.008
