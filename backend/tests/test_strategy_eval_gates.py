"""MVP 3.5 batch 3 — Strategy Gates (G1' / G2' / G3') + PlatformStrategyEvaluator 测试.

覆盖 (12 tests):
  - StrategyG1SharpeGate (3): 强信号 PASS / 无信号 FAIL / 数据缺失 data_unavailable
  - StrategyG2MaxDrawdownGate (3): 跌幅小 PASS / 大 FAIL / 自定义 threshold + 短序列
  - StrategyG3RegressionGate (4): max_diff=0 PASS / max_diff>0 FAIL / no_baseline SKIP /
    runner 异常
  - PlatformStrategyEvaluator (2): evaluate_strategy 全 PASS / sim_to_real_check 5bps 阈值
"""
from __future__ import annotations

import numpy as np
import pytest
from qm_platform.eval import (
    STRATEGY_G2_DEFAULT_MAX_DD,
    GateContext,
    PlatformStrategyEvaluator,
    StrategyG1SharpeGate,
    StrategyG2MaxDrawdownGate,
    StrategyG3RegressionGate,
    build_strategy_context,
    default_strategy_pipeline,
)

# ---------- StrategyG1SharpeGate (3) ----------


def test_strategy_g1_strong_signal_passes():
    rng = np.random.default_rng(0)
    candidate = rng.normal(0.001, 0.005, size=200)  # 日收益 0.1% 稳定
    baseline = rng.normal(0.0, 0.005, size=200)
    ctx = build_strategy_context(
        "S1", candidate_daily_returns=candidate, baseline_daily_returns=baseline
    )
    result = StrategyG1SharpeGate(rng_seed=42).evaluate(ctx)
    assert result.passed is True
    assert result.observed is not None
    assert result.observed < 0.05


def test_strategy_g1_no_signal_fails():
    rng = np.random.default_rng(0)
    candidate = rng.normal(0.0, 0.005, size=200)
    baseline = rng.normal(0.0, 0.005, size=200)
    ctx = build_strategy_context(
        "S1", candidate_daily_returns=candidate, baseline_daily_returns=baseline
    )
    result = StrategyG1SharpeGate(rng_seed=42).evaluate(ctx)
    assert result.passed is False
    assert result.observed is not None
    assert result.observed > 0.05


def test_strategy_g1_data_unavailable():
    ctx = build_strategy_context("S1")
    result = StrategyG1SharpeGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["reason"] == "data_unavailable"
    assert "extra.candidate_daily_returns" in result.details["missing"]
    assert "extra.baseline_daily_returns" in result.details["missing"]


# ---------- StrategyG2MaxDrawdownGate (3) ----------


def test_strategy_g2_small_drawdown_passes():
    """NAV 平稳上涨, 仅小幅 drawdown → PASS (-15% > -30% default)."""
    nav = np.array([1.0, 1.05, 1.10, 0.95, 1.00, 1.20, 1.30])
    ctx = build_strategy_context("S1", nav_series=nav)
    result = StrategyG2MaxDrawdownGate().evaluate(ctx)
    # 实际 dd = (0.95 - 1.10) / 1.10 ≈ -0.136
    assert result.passed is True
    assert result.observed is not None
    assert result.observed > -0.30


def test_strategy_g2_large_drawdown_fails():
    """NAV 暴跌 50% → FAIL."""
    nav = np.array([1.0, 1.20, 1.30, 0.50, 0.55, 0.60])
    ctx = build_strategy_context("S1", nav_series=nav)
    result = StrategyG2MaxDrawdownGate().evaluate(ctx)
    # dd ≈ (0.50 - 1.30) / 1.30 ≈ -0.615
    assert result.passed is False
    assert result.observed is not None
    assert result.observed < -0.30


def test_strategy_g2_custom_threshold_override():
    """ctx.extra["max_dd_threshold"] override 默认 -0.30."""
    nav = np.array([1.0, 1.20, 1.00, 1.30])  # dd ≈ -0.167
    ctx = build_strategy_context("S1", nav_series=nav, max_dd_threshold=-0.10)
    result = StrategyG2MaxDrawdownGate().evaluate(ctx)
    # threshold 严到 -0.10, 实际 -0.167 < -0.10 → FAIL
    assert result.passed is False
    assert result.threshold == -0.10


# ---------- StrategyG3RegressionGate (4) ----------


def test_strategy_g3_max_diff_zero_passes():
    runner = lambda: {"max_diff": 0.0, "sharpe": 0.65, "config_hash": "abc"}  # noqa: E731
    ctx = build_strategy_context("S1", regression_runner=runner)
    result = StrategyG3RegressionGate().evaluate(ctx)
    assert result.passed is True
    assert result.observed == 0.0


def test_strategy_g3_max_diff_nonzero_fails():
    runner = lambda: {"max_diff": 1e-9, "sharpe": 0.65}  # 极小但非零, 铁律 15 严格 = 0  # noqa: E731
    ctx = build_strategy_context("S1", regression_runner=runner)
    result = StrategyG3RegressionGate().evaluate(ctx)
    assert result.passed is False
    assert result.observed is not None
    assert result.observed > 0.0


def test_strategy_g3_no_baseline_skips_pass():
    """全新策略首次部署 → SKIP (PASS, reason=no_baseline)."""
    ctx = build_strategy_context("S1_new", no_baseline=True)
    result = StrategyG3RegressionGate().evaluate(ctx)
    assert result.passed is True
    assert result.details["reason"] == "no_baseline_first_deployment"


def test_strategy_g3_runner_raises_packed_in_result():
    """runner 抛异常 → Gate 不 raise, 包成 GateResult (Gate pure function 契约)."""

    def bad_runner():
        raise RuntimeError("regression test failed")

    ctx = build_strategy_context("S1", regression_runner=bad_runner)
    result = StrategyG3RegressionGate().evaluate(ctx)
    assert result.passed is False
    assert result.details["reason"] == "regression_runner_raised"
    assert "regression test failed" in result.details["error"]


# ---------- PlatformStrategyEvaluator (2) ----------


def test_strategy_evaluator_evaluate_strategy_all_pass():
    rng = np.random.default_rng(0)
    candidate = rng.normal(0.001, 0.005, size=200)
    baseline = rng.normal(0.0, 0.005, size=200)
    nav = np.cumprod(1.0 + candidate)  # 累计净值
    runner = lambda: {"max_diff": 0.0}  # noqa: E731

    def loader(strategy_id: str) -> GateContext:
        return build_strategy_context(
            strategy_id,
            candidate_daily_returns=candidate,
            baseline_daily_returns=baseline,
            nav_series=nav,
            regression_runner=runner,
        )

    evaluator = PlatformStrategyEvaluator(loader, rng_seed=42)
    verdict = evaluator.evaluate_strategy("S1_test", years=5)
    assert verdict.passed is True
    assert verdict.blockers == []
    assert verdict.details["evaluation_years"] == 5
    assert verdict.details["decision"] == "accept"


def test_strategy_evaluator_sim_to_real_within_5bps_passes():
    def loader(strategy_id: str) -> GateContext:
        return build_strategy_context(strategy_id, sim_to_real_gap_bps=3.5)

    evaluator = PlatformStrategyEvaluator(loader)
    verdict = evaluator.sim_to_real_check("S1")
    assert verdict.passed is True
    assert verdict.details["gap_bps"] == 3.5
    assert verdict.details["ironclad_rule"] == 18


def test_strategy_evaluator_sim_to_real_exceed_5bps_fails():
    def loader(strategy_id: str) -> GateContext:
        return build_strategy_context(strategy_id, sim_to_real_gap_bps=8.0)

    evaluator = PlatformStrategyEvaluator(loader)
    verdict = evaluator.sim_to_real_check("S1")
    assert verdict.passed is False
    assert "sim_to_real_gap" in verdict.blockers


def test_strategy_evaluator_sim_to_real_missing_data_warns():
    def loader(strategy_id: str) -> GateContext:
        return build_strategy_context(strategy_id)  # 无 sim_to_real_gap_bps

    evaluator = PlatformStrategyEvaluator(loader)
    verdict = evaluator.sim_to_real_check("S1")
    assert verdict.passed is False
    assert verdict.details["decision"] == "warning"


# ---------- default_strategy_pipeline factory ----------


def test_default_strategy_pipeline_has_3_gates():
    pipeline = default_strategy_pipeline(context_loader=lambda n: GateContext(factor_name=n))
    names = [g.name for g in pipeline._gates]  # noqa: SLF001
    assert "G1prime_sharpe_bootstrap" in names
    assert "G2prime_max_drawdown" in names
    assert "G3prime_regression_max_diff" in names
    assert len(names) == 3


def test_strategy_g2_default_threshold_constant():
    """STRATEGY_G2_DEFAULT_MAX_DD 默认 -0.30 (ADR-014 锁定)."""
    assert STRATEGY_G2_DEFAULT_MAX_DD == -0.30


# ---------- pytest fixture sanity ----------


def test_build_strategy_context_extra_is_immutable():
    """build_strategy_context 返回的 ctx.extra 是 read-only Mapping (P1.1 fix 一致)."""
    ctx = build_strategy_context("S1", sim_to_real_gap_bps=3.0)
    with pytest.raises(TypeError):
        ctx.extra["new_key"] = "bar"  # type: ignore[index] — read-only 触发异常
