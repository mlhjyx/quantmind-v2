"""MVP 3.5 batch 2 — factor_lifecycle 双路径接 PlatformEvaluationPipeline 测试.

覆盖 (15 tests):
  - default_lifecycle_pipeline 构造 (3): 含 G1+G10, 不含 G3/G4 等, context_loader 注入
  - build_lifecycle_context (2): 全字段构造, 部分字段 None
  - compare_paths 老路径分支 (4): None / warning / critical / active 恢复
  - compare_paths 新路径分支 (3): ACCEPT / REJECT / WARNING
  - compare_paths 一致 / 不一致 (3): 全 keep / 全 demote / unknown 不一致
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from engines.factor_lifecycle import (
    FactorStatus,
    TransitionDecision,
    build_lifecycle_context,
    compare_paths,
    default_lifecycle_pipeline,
)

# ---------- default_lifecycle_pipeline (3) ----------


def test_default_lifecycle_pipeline_has_g1_and_g10():
    """默认 pipeline 含 G1 + G10, 不含 G3/G4/G8/G9."""
    pipeline = default_lifecycle_pipeline(context_loader=lambda n: None)
    gate_names = [g.name for g in pipeline._gates]  # noqa: SLF001 — test 内部 introspection
    assert "G1_ic_significance" in gate_names
    assert "G10_hypothesis" in gate_names
    assert "G3_paired_bootstrap" not in gate_names  # 设计稿: G3 lifecycle 上下文无 baseline 跳过
    assert "G4_oos_walkforward" not in gate_names
    assert len(gate_names) == 2


def test_default_lifecycle_pipeline_loader_injected():
    """注入的 loader 被 pipeline 使用."""
    captured: dict[str, str] = {}

    def loader(name: str):
        captured["called_with"] = name
        from qm_platform.eval import GateContext
        return GateContext(factor_name=name)

    pipeline = default_lifecycle_pipeline(context_loader=loader)
    pipeline.evaluate_full("test_factor")
    assert captured["called_with"] == "test_factor"


def test_default_lifecycle_pipeline_evaluates_full_factor():
    """端到端: ic_series 强信号 + 合法 hypothesis → ACCEPT."""
    rng = np.random.default_rng(0)
    ic = rng.normal(0.05, 0.01, size=100)

    factor_meta = MagicMock()
    factor_meta.hypothesis = "市场短期趋势惯性, ts_mean 反映动量, 预测下期涨跌方向"
    factor_meta.expression = "ts_mean(close, 20)"

    def loader(name: str):
        return build_lifecycle_context(
            name, ic_series=ic, factor_meta=factor_meta
        )

    pipeline = default_lifecycle_pipeline(context_loader=loader)
    report = pipeline.evaluate_full("good_factor")
    assert report.decision.value == "accept"
    assert report.passed is True


# ---------- build_lifecycle_context (2) ----------


def test_build_lifecycle_context_all_fields():
    rng = np.random.default_rng(1)
    ic = rng.normal(0.05, 0.01, size=60)
    baseline = rng.normal(0.0, 0.01, size=60)
    fake_meta = MagicMock()
    fake_registry = MagicMock()
    ctx = build_lifecycle_context(
        "x",
        ic_series=ic,
        ic_baseline_series=baseline,
        factor_meta=fake_meta,
        registry=fake_registry,
    )
    assert ctx.factor_name == "x"
    assert ctx.ic_series is ic
    assert ctx.ic_baseline_series is baseline
    assert ctx.factor_meta is fake_meta
    assert ctx.registry is fake_registry


def test_build_lifecycle_context_minimal():
    ctx = build_lifecycle_context("y")
    assert ctx.factor_name == "y"
    assert ctx.ic_series is None
    assert ctx.ic_baseline_series is None
    assert ctx.factor_meta is None
    assert ctx.registry is None


# ---------- compare_paths 老路径分支 (4) ----------


def _td(to_status: str) -> TransitionDecision:
    return TransitionDecision(
        factor_name="x",
        from_status=FactorStatus.ACTIVE.value,
        to_status=to_status,
        reason="test",
        ic_ma20=0.05,
        ic_ma60=0.10,
        ratio=0.5,
    )


def _report(decision_value: str):
    """伪造 EvaluationReport (鸭子类型, 仅需 decision.value)."""
    rep = MagicMock()
    rep.decision.value = decision_value
    return rep


def test_compare_paths_old_none_maps_keep():
    cmp = compare_paths("x", None, _report("accept"))
    assert cmp.old_label == "keep"
    assert cmp.consistent is True


def test_compare_paths_old_warning_maps_demote():
    cmp = compare_paths("x", _td(FactorStatus.WARNING.value), _report("reject"))
    assert cmp.old_label == "demote"
    assert cmp.consistent is True


def test_compare_paths_old_critical_maps_demote():
    cmp = compare_paths("x", _td(FactorStatus.CRITICAL.value), _report("reject"))
    assert cmp.old_label == "demote"
    assert cmp.consistent is True


def test_compare_paths_old_active_recovery_maps_keep():
    """warning→active 恢复视为 keep (因子健康)."""
    cmp = compare_paths("x", _td(FactorStatus.ACTIVE.value), _report("accept"))
    assert cmp.old_label == "keep"
    assert cmp.consistent is True


# ---------- compare_paths 新路径分支 (3) ----------


def test_compare_paths_new_accept_maps_keep():
    cmp = compare_paths("x", None, _report("accept"))
    assert cmp.new_label == "keep"


def test_compare_paths_new_reject_maps_demote():
    cmp = compare_paths("x", _td(FactorStatus.WARNING.value), _report("reject"))
    assert cmp.new_label == "demote"


def test_compare_paths_new_warning_maps_unknown():
    """新路径 WARNING (data_unavailable) → 'unknown' (不下定论)."""
    cmp = compare_paths("x", None, _report("warning"))
    assert cmp.new_label == "unknown"
    assert cmp.consistent is False  # old=keep vs new=unknown 视为 mismatch


# ---------- compare_paths 一致 / 不一致 (3) ----------


def test_compare_paths_both_keep_consistent():
    cmp = compare_paths("x", None, _report("accept"))
    assert cmp.consistent is True
    assert cmp.mismatch_summary is None


def test_compare_paths_old_keep_new_demote_mismatch():
    """老路径无变化 (keep) 但新路径 REJECT (demote) — 真 mismatch."""
    cmp = compare_paths("x", None, _report("reject"))
    assert cmp.consistent is False
    assert cmp.mismatch_summary is not None
    assert "old=keep" in cmp.mismatch_summary
    assert "new=demote" in cmp.mismatch_summary


def test_compare_paths_old_demote_new_unknown_mismatch():
    """老路径 demote 但新路径 unknown (data_unavailable) — mismatch."""
    cmp = compare_paths("x", _td(FactorStatus.WARNING.value), _report("warning"))
    assert cmp.consistent is False
    assert cmp.mismatch_summary is not None
    assert "old=demote" in cmp.mismatch_summary
    assert "new=unknown" in cmp.mismatch_summary


# ---------- DualPathComparison frozen ----------


def test_dual_path_comparison_is_frozen():
    cmp = compare_paths("x", None, _report("accept"))
    with pytest.raises((AttributeError, Exception)):
        cmp.factor_name = "y"  # type: ignore[misc] — frozen dataclass 触发异常
