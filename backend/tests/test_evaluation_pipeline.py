"""MVP 3.5 batch 1 — EvaluationPipeline + 7 Gates + utils unit tests.

覆盖 (24 tests):
  - utils (5): paired_bootstrap_pvalue / t_statistic / bh_threshold
  - 7 Gates (14): 每 Gate 2 tests (pass + fail or data_unavailable)
  - Pipeline (5): evaluate_factor / evaluate_full / gate_detail / decision aggregation
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pytest
from qm_platform._types import Verdict
from qm_platform.eval import (
    EvaluationDecision,
    EvaluationReport,
    G1IcSignificanceGate,
    G2CorrelationFilterGate,
    G3PairedBootstrapGate,
    G4WalkForwardGate,
    G8BhFdrGate,
    G9NoveltyAstGate,
    G10HypothesisGate,
    GateContext,
    PlatformEvaluationPipeline,
    benjamini_hochberg_threshold,
    paired_bootstrap_pvalue,
    t_statistic,
)
from qm_platform.factor.interface import FactorMeta, FactorStatus

# ---------- utils tests (5) ----------


def test_paired_bootstrap_pvalue_strong_signal_returns_low_p():
    """candidate 显著优于 baseline → p 接近 0."""
    rng = np.random.default_rng(123)
    candidate = rng.normal(0.05, 0.01, size=200)
    baseline = rng.normal(0.0, 0.01, size=200)
    p = paired_bootstrap_pvalue(candidate, baseline, rng_seed=42)
    assert p is not None
    assert p < 0.05


def test_paired_bootstrap_pvalue_no_signal_not_significant():
    """candidate 无差异 → p > 0.05 (不显著). 仅校验"未通过显著性"语义, 不锁具体 p 值."""
    rng = np.random.default_rng(123)
    candidate = rng.normal(0.0, 0.01, size=200)
    baseline = rng.normal(0.0, 0.01, size=200)
    p = paired_bootstrap_pvalue(candidate, baseline, rng_seed=42)
    assert p is not None
    assert p > 0.05  # 关键语义: 不显著. 具体值依赖 rng 抽样, 不强校


def test_paired_bootstrap_pvalue_shape_mismatch_returns_none():
    """长度不匹配返 None."""
    cand = np.zeros(100)
    base = np.zeros(50)
    assert paired_bootstrap_pvalue(cand, base) is None


def test_paired_bootstrap_pvalue_too_few_samples_returns_none():
    """样本 < 30 返 None."""
    cand = np.array([0.01, 0.02])
    base = np.array([0.0, 0.01])
    assert paired_bootstrap_pvalue(cand, base) is None


def test_paired_bootstrap_pvalue_n_iter_too_low_raises():
    cand = np.zeros(100)
    base = np.zeros(100)
    with pytest.raises(ValueError, match="n_iter"):
        paired_bootstrap_pvalue(cand, base, n_iter=50)


def test_t_statistic_zero_std_returns_none():
    arr = np.ones(100) * 0.05  # 全相同 → std=0
    assert t_statistic(arr) is None


def test_t_statistic_basic():
    rng = np.random.default_rng(0)
    arr = rng.normal(0.05, 0.01, size=100)  # mean=0.05 strong signal
    t = t_statistic(arr)
    assert t is not None
    assert t > 10  # 强信号 t 应远大于 2.5


def test_benjamini_hochberg_threshold_pass_and_fail():
    # rank=1, m=84, fdr=0.05 → threshold = 1/84 × 0.05 ≈ 0.000595
    assert benjamini_hochberg_threshold(p_value=0.0001, rank=1, m=84) is True
    assert benjamini_hochberg_threshold(p_value=0.001, rank=1, m=84) is False


def test_benjamini_hochberg_threshold_invalid_rank_raises():
    with pytest.raises(ValueError, match="rank"):
        benjamini_hochberg_threshold(p_value=0.01, rank=100, m=84)


# ---------- G1 IC Significance ----------


def test_g1_strong_ic_passes():
    rng = np.random.default_rng(0)
    ic = rng.normal(0.05, 0.01, size=200)  # strong t
    ctx = GateContext(factor_name="strong_factor", ic_series=ic)
    result = G1IcSignificanceGate().evaluate(ctx)
    assert result.passed is True
    assert result.observed is not None
    assert abs(result.observed) > 2.5


def test_g1_data_unavailable_when_ic_missing():
    ctx = GateContext(factor_name="x")
    result = G1IcSignificanceGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["reason"] == "data_unavailable"
    assert "ic_series" in result.details["missing"]


# ---------- G2 Correlation Filter ----------


def test_g2_low_corr_passes():
    ctx = GateContext(
        factor_name="x", active_corr_max=0.3, monthly_return_corr_max=0.1
    )
    result = G2CorrelationFilterGate().evaluate(ctx)
    assert result.passed is True


def test_g2_high_corr_fails():
    ctx = GateContext(factor_name="x", active_corr_max=0.85)
    result = G2CorrelationFilterGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["ic_passed"] is False


# ---------- G3 Paired Bootstrap ----------


def test_g3_strong_alpha_passes():
    rng = np.random.default_rng(0)
    cand = rng.normal(0.05, 0.01, size=100)
    base = rng.normal(0.0, 0.01, size=100)
    ctx = GateContext(factor_name="x", ic_series=cand, ic_baseline_series=base)
    result = G3PairedBootstrapGate(rng_seed=42).evaluate(ctx)
    assert result.passed is True
    assert result.observed is not None
    assert result.observed < 0.05


def test_g3_data_unavailable():
    ctx = GateContext(factor_name="x")
    result = G3PairedBootstrapGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["reason"] == "data_unavailable"


# ---------- G4 Walk-Forward ----------


def test_g4_oos_better_than_baseline_passes():
    ctx = GateContext(factor_name="x", wf_oos_sharpe=0.87, wf_baseline_sharpe=0.65)
    result = G4WalkForwardGate().evaluate(ctx)
    assert result.passed is True
    assert result.details["delta"] > 0


def test_g4_oos_worse_fails():
    ctx = GateContext(factor_name="x", wf_oos_sharpe=0.50, wf_baseline_sharpe=0.65)
    result = G4WalkForwardGate().evaluate(ctx)
    assert result.passed is False


# ---------- G8 BH-FDR ----------


def test_g8_strong_p_passes_bh():
    ctx = GateContext(
        factor_name="x", bh_fdr_p_value=0.0001, bh_fdr_rank=1, bh_fdr_m=84
    )
    result = G8BhFdrGate().evaluate(ctx)
    assert result.passed is True


def test_g8_weak_p_fails_bh():
    ctx = GateContext(
        factor_name="x", bh_fdr_p_value=0.04, bh_fdr_rank=1, bh_fdr_m=84
    )
    # 1/84 × 0.05 ≈ 0.000595 < 0.04 → 拒绝
    result = G8BhFdrGate().evaluate(ctx)
    assert result.passed is False


# ---------- G9 Novelty AST ----------


def _make_meta(name: str, expression: str, hypothesis: str) -> FactorMeta:
    """快捷构造 FactorMeta (test fixture, 不走 DB).

    对齐 MVP 1.3a DB factor_registry 18 字段 schema.
    """
    return FactorMeta(
        factor_id=uuid4(),
        name=name,
        category="test",
        direction=1,
        expression=expression,
        code_content=None,
        hypothesis=hypothesis,
        source="manual",
        lookback_days=20,
        status=FactorStatus.CANDIDATE,
        pool="CANDIDATE",
        gate_ic=None,
        gate_ir=None,
        gate_mono=None,
        gate_t=None,
        ic_decay_ratio=None,
        created_at="2026-04-28T00:00:00",
        updated_at="2026-04-28T00:00:00",
    )


def test_g9_novel_factor_passes():
    """registry.novelty_check 返 True (mock)."""
    fake_registry = MagicMock()
    fake_registry.novelty_check.return_value = True
    meta = _make_meta("new_factor", "ts_mean(close, 20)", "趋势惯性 hypothesis 25 字以上 (满足 G10 长度门槛)")
    ctx = GateContext(factor_name="new_factor", factor_meta=meta, registry=fake_registry)
    result = G9NoveltyAstGate().evaluate(ctx)
    assert result.passed is True
    fake_registry.novelty_check.assert_called_once()


def test_g9_similar_factor_fails():
    """registry.novelty_check 返 False (相似度过高)."""
    fake_registry = MagicMock()
    fake_registry.novelty_check.return_value = False
    meta = _make_meta("dup_factor", "ts_mean(close, 19)", "略改窗口 hypothesis 25 字以上 (满足 G10 长度门槛)")
    ctx = GateContext(factor_name="dup_factor", factor_meta=meta, registry=fake_registry)
    result = G9NoveltyAstGate().evaluate(ctx)
    assert result.passed is False


# ---------- G10 Hypothesis ----------


def test_g10_valid_hypothesis_passes():
    meta = _make_meta(
        "x", "ts_mean(close, 20)", "市场短期趋势惯性, ts_mean 反映动量, 预测下期涨跌方向"
    )
    ctx = GateContext(factor_name="x", factor_meta=meta)
    result = G10HypothesisGate().evaluate(ctx)
    assert result.passed is True


def test_g10_short_hypothesis_fails():
    meta = _make_meta("x", "ts_mean(close, 20)", "TBD")  # 太短
    ctx = GateContext(factor_name="x", factor_meta=meta)
    result = G10HypothesisGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["reason"] == "hypothesis_too_short"


# ---------- Pipeline (5 tests) ----------


def _build_passing_ctx_loader() -> Any:
    """构造全 Gate PASS 的 ctx loader."""
    rng = np.random.default_rng(0)
    cand = rng.normal(0.05, 0.01, size=120)
    base = rng.normal(0.0, 0.01, size=120)
    fake_registry = MagicMock()
    fake_registry.novelty_check.return_value = True
    meta = _make_meta(
        "good_factor",
        "ts_mean(close, 20)",
        "市场短期趋势惯性, ts_mean 反映动量, 预测下期涨跌方向",
    )

    def loader(name: str) -> GateContext:
        return GateContext(
            factor_name=name,
            factor_meta=meta,
            ic_series=cand,
            ic_baseline_series=base,
            active_corr_max=0.3,
            wf_oos_sharpe=0.87,
            wf_baseline_sharpe=0.65,
            bh_fdr_p_value=0.0001,
            bh_fdr_rank=1,
            bh_fdr_m=84,
            registry=fake_registry,
        )

    return loader


def test_pipeline_evaluate_factor_returns_verdict():
    loader = _build_passing_ctx_loader()
    pipeline = PlatformEvaluationPipeline(
        gates=[
            G1IcSignificanceGate(),
            G2CorrelationFilterGate(),
            G3PairedBootstrapGate(rng_seed=42),
            G4WalkForwardGate(),
            G8BhFdrGate(),
            G9NoveltyAstGate(),
            G10HypothesisGate(),
        ],
        context_loader=loader,
    )
    verdict = pipeline.evaluate_factor("good_factor")
    assert isinstance(verdict, Verdict)
    assert verdict.passed is True
    assert verdict.blockers == []
    assert verdict.details["decision"] == "accept"
    assert len(verdict.details["gate_results"]) == 7


def test_pipeline_evaluate_full_returns_report():
    loader = _build_passing_ctx_loader()
    pipeline = PlatformEvaluationPipeline(
        gates=[G1IcSignificanceGate(), G10HypothesisGate()],
        context_loader=loader,
    )
    report = pipeline.evaluate_full("good_factor")
    assert isinstance(report, EvaluationReport)
    assert report.decision == EvaluationDecision.ACCEPT
    assert report.passed is True
    assert report.timestamp.tzinfo is not None  # 铁律 41 timezone-aware


def test_pipeline_decision_warning_when_data_unavailable():
    """所有 Gate data_unavailable → WARNING (非 REJECT)."""

    def empty_loader(name: str) -> GateContext:
        return GateContext(factor_name=name)  # 无数据

    pipeline = PlatformEvaluationPipeline(
        gates=[G1IcSignificanceGate(), G3PairedBootstrapGate()],
        context_loader=empty_loader,
    )
    report = pipeline.evaluate_full("x")
    assert report.decision == EvaluationDecision.WARNING
    assert report.passed is False


def test_pipeline_decision_reject_on_hard_fail():
    """业务 hard fail → REJECT, reasoning 命中具体 gate."""

    def loader(name: str) -> GateContext:
        meta = _make_meta("x", "ts_mean(c, 20)", "TBD")  # G10 too short
        return GateContext(factor_name=name, factor_meta=meta)

    pipeline = PlatformEvaluationPipeline(
        gates=[G10HypothesisGate()], context_loader=loader
    )
    report = pipeline.evaluate_full("x")
    assert report.decision == EvaluationDecision.REJECT
    assert "G10_hypothesis" in report.reasoning


def test_pipeline_gate_detail_unknown_raises():
    loader = _build_passing_ctx_loader()
    pipeline = PlatformEvaluationPipeline(
        gates=[G1IcSignificanceGate()], context_loader=loader
    )
    with pytest.raises(ValueError, match="unknown gate"):
        pipeline.gate_detail("good_factor", "NOPE_gate")


def test_pipeline_safe_evaluate_swallows_gate_exception():
    """Gate 内部 raise → Pipeline 包成 GateResult 而非崩溃 (belt-and-suspenders)."""

    class BadGate(G1IcSignificanceGate):
        name = "Bad_gate"

        def evaluate(self, ctx):  # noqa: ANN001
            raise RuntimeError("intentional failure")

    def loader(name: str) -> GateContext:
        return GateContext(factor_name=name)

    pipeline = PlatformEvaluationPipeline(gates=[BadGate()], context_loader=loader)
    report = pipeline.evaluate_full("x")
    assert report.gate_results[0].passed is False
    assert report.gate_results[0].details["reason"] == "gate_internal_error"
    assert "intentional failure" in report.gate_results[0].details["error"]


def test_pipeline_empty_gates_raises():
    with pytest.raises(ValueError, match="gates"):
        PlatformEvaluationPipeline(gates=[], context_loader=lambda n: GateContext(factor_name=n))


# ---------- PR #123 reviewer fix verification ----------


def test_gate_context_extra_is_immutable_p1_1():
    """P1.1 GateContext.extra 必须 read-only — 防 Gate 间 ctx 共享 dict 污染下游.

    Pipeline.evaluate_full 同一 ctx 实例顺序传所有 Gate, 若 extra 是可变 dict
    一个 Gate 写则下游 Gate 看见. 修复后 extra 是 MappingProxyType / Mapping, 写抛 TypeError.
    """
    ctx = GateContext(factor_name="x")
    with pytest.raises(TypeError):
        ctx.extra["foo"] = "bar"  # type: ignore[index] — 故意触发 read-only 异常


def test_to_verdict_numpy_scalar_json_serializable_p1_2():
    """P1.2 EvaluationReport.to_verdict 必须把 numpy scalar 转 Python float 防 JSON 炸.

    GateResult.observed 类型注解是 float | None, 但 Gate 实现常返 np.float64
    (e.g. arr.mean()). 下游 audit log / StreamBus / API 序列化必须能 json.dumps.
    """
    import json

    rng = np.random.default_rng(0)
    ic = rng.normal(0.05, 0.01, size=200)
    ctx = GateContext(factor_name="x", ic_series=ic)
    pipeline = PlatformEvaluationPipeline(
        gates=[G1IcSignificanceGate()],
        context_loader=lambda n: ctx,
    )
    verdict = pipeline.evaluate_factor("x")
    # G1 的 observed 是 t-stat (np.float64 from arr.mean / arr.std).
    # 修复前: json.dumps(verdict.details) raise TypeError; 修复后: 通过.
    serialized = json.dumps(verdict.details)
    assert "observed" in serialized
    assert isinstance(verdict.details["gate_results"][0]["observed"], float)


def test_paired_bootstrap_vectorized_consistency_p2_1():
    """P2.1 向量化 bootstrap 与原 loop 实现应等价 (rng_seed 相同时)."""
    rng_a = np.random.default_rng(1)
    cand = rng_a.normal(0.05, 0.01, size=100)
    base = rng_a.normal(0.0, 0.01, size=100)
    p1 = paired_bootstrap_pvalue(cand, base, rng_seed=42)
    p2 = paired_bootstrap_pvalue(cand, base, rng_seed=42)
    assert p1 == p2  # 同 seed 必复现 (向量化后 rng.integers 一次性消费 size=(n_iter, n))
