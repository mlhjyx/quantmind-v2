"""MVP 3.5 Follow-up B — engines/factor_lifecycle.py compute_composite_decision tests.

Session 43 (2026-04-28). 验证 OR 复合决策 (老 OR 新 → demote) 3 模式 × 4 场景矩阵.

来源: PR #127 12 周历史回放发现老/新路径测互补 (P1 reverse 225) — 不能 sunset,
应改 OR 复合. 本 PR 加纯函数 + 分析支持, 不改生产 run() 行为 (Phase 2 单独 PR).

覆盖:
  - extract_failed_gate_names (3): None 报告 / 空 gate_results / 提取多 fail
  - compute_composite_decision OFF (2): 老 demote / 老 None
  - compute_composite_decision G1_ONLY (4): G1 fail+老 None / G1 pass+老 None /
    G1 fail+老 demote (优先老) / 非 active 状态
  - compute_composite_decision STRICT (4): G1 only / G10 only / 双 fail / 全 pass
  - 合成决策 ic_ma 字段填入 (1)
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.engines.factor_lifecycle import (
    CompositeMode,
    FactorStatus,
    TransitionDecision,
    compute_composite_decision,
    extract_failed_gate_names,
)


def _make_gate_result(gate_name: str, passed: bool):
    return SimpleNamespace(gate_name=gate_name, passed=passed)


def _make_report(failed_gates: list[str]):
    """Build a SimpleNamespace report with gate_results field (鸭子类型)."""
    all_gates = ["G1_ic_significance", "G10_hypothesis"]
    results = [
        _make_gate_result(g, passed=(g not in failed_gates)) for g in all_gates
    ]
    return SimpleNamespace(gate_results=results)


def _make_old_decision_demote(factor_name="f1") -> TransitionDecision:
    return TransitionDecision(
        factor_name=factor_name,
        from_status="active",
        to_status=FactorStatus.WARNING.value,
        reason="ratio<0.8 (decay)",
        ic_ma20=0.04,
        ic_ma60=0.06,
        ratio=0.667,
    )


def _make_old_decision_recovery(factor_name="f1") -> TransitionDecision:
    """warning → active recovery (P1.2 reviewer 2026-04-28 PR #128)."""
    return TransitionDecision(
        factor_name=factor_name,
        from_status=FactorStatus.WARNING.value,
        to_status=FactorStatus.ACTIVE.value,
        reason="ratio>=0.8 (recovery)",
        ic_ma20=0.05,
        ic_ma60=0.06,
        ratio=0.833,
    )


# ─── extract_failed_gate_names (3) ───────────────────────────────────


def test_extract_failed_gate_names_returns_empty_for_none_report():
    assert extract_failed_gate_names(None) == set()


def test_extract_failed_gate_names_returns_empty_when_no_gate_results():
    report = SimpleNamespace()  # no gate_results attr
    assert extract_failed_gate_names(report) == set()
    report2 = SimpleNamespace(gate_results=[])
    assert extract_failed_gate_names(report2) == set()


def test_extract_failed_gate_names_collects_failed_gate_ids():
    report = _make_report(failed_gates=["G1_ic_significance"])
    assert extract_failed_gate_names(report) == {"G1_ic_significance"}

    report2 = _make_report(failed_gates=["G1_ic_significance", "G10_hypothesis"])
    assert extract_failed_gate_names(report2) == {"G1_ic_significance", "G10_hypothesis"}


# ─── compute_composite_decision OFF (2) ──────────────────────────────


def test_composite_off_returns_old_decision_when_old_demote():
    """OFF mode: 老 demote 直接透传 (生产兼容)."""
    old = _make_old_decision_demote("f1")
    report = _make_report(failed_gates=["G1_ic_significance"])  # 新也 fail, 但 OFF 不参与
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=old,
        new_report=report,
        mode=CompositeMode.OFF,
    )
    assert result is old


def test_composite_off_returns_none_when_old_none():
    """OFF mode: 老 None 直接 None (即便新 fail), 生产兼容."""
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.OFF,
    )
    assert result is None


# ─── compute_composite_decision G1_ONLY (4) ──────────────────────────


def test_composite_g1_only_synthesizes_demote_when_g1_fails_old_keep():
    """G1_ONLY: 老路径 keep + G1 fail → 合成 active→warning."""
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,  # 老路径 keep
        new_report=report,
        mode=CompositeMode.G1_ONLY,
        ic_ma20=0.05,
        ic_ma60=0.06,
    )
    assert result is not None
    assert result.factor_name == "f1"
    assert result.from_status == "active"
    assert result.to_status == FactorStatus.WARNING.value
    assert "composite_g1-only" in result.reason
    assert "G1_ic_significance" in result.reason
    assert result.ic_ma20 == 0.05
    assert result.ic_ma60 == 0.06


def test_composite_g1_only_returns_none_when_all_pass():
    """G1_ONLY: 老 None + G1 pass + G10 pass → 透传 None (无变化)."""
    report = _make_report(failed_gates=[])  # 全 pass
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    assert result is None


def test_composite_g1_only_priority_returns_old_when_old_demote_and_g1_fail():
    """G1_ONLY: 老 demote AND G1 fail → 优先返老 (老有真 ic_ma20/60/ratio 数据)."""
    old = _make_old_decision_demote("f1")
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=old,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    assert result is old  # 完整老 decision, 不被合成 reason 覆盖


def test_composite_g1_only_ignores_g10_failure():
    """G1_ONLY: 仅 G10 fail (G1 pass) → 不触发合成 (防 hypothesis 缺失批量降级)."""
    report = _make_report(failed_gates=["G10_hypothesis"])  # G1 pass, G10 fail
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    assert result is None  # G10 not part of G1_ONLY mode


# ─── compute_composite_decision STRICT (4) ────────────────────────────


def test_composite_strict_synthesizes_when_g1_fails():
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.STRICT,
        ic_ma20=0.05,
        ic_ma60=0.06,
    )
    assert result is not None
    assert result.to_status == FactorStatus.WARNING.value
    assert "composite_strict" in result.reason
    assert "G1_ic_significance" in result.reason


def test_composite_strict_synthesizes_when_only_g10_fails():
    """STRICT: 仅 G10 fail → 合成 demote (区别于 G1_ONLY)."""
    report = _make_report(failed_gates=["G10_hypothesis"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.STRICT,
    )
    assert result is not None
    assert "G10_hypothesis" in result.reason


def test_composite_strict_synthesizes_when_both_fail_lists_both_triggers():
    report = _make_report(failed_gates=["G1_ic_significance", "G10_hypothesis"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.STRICT,
    )
    assert result is not None
    assert "G1_ic_significance" in result.reason
    assert "G10_hypothesis" in result.reason


def test_composite_strict_returns_none_when_all_pass():
    report = _make_report(failed_gates=[])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.STRICT,
    )
    assert result is None


# ─── 状态机边界 + ic_ma 填入 (3) ───────────────────────────────────


def test_composite_does_not_synthesize_when_status_is_warning():
    """warning 状态 (已是 demoted) — 新路径 G1 fail 不触发额外 transition."""
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,
        old_decision=None,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    # warning 状态 + 老 None → 老路径透传 None (不合成)
    assert result is None


def test_composite_handles_missing_ic_ma_with_nan():
    """未传 ic_ma20/ic_ma60 → 合成 decision 字段为 NaN (不参与判定, 仅审计)."""
    import math

    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
        # ic_ma20 / ic_ma60 缺省
    )
    assert result is not None
    assert math.isnan(result.ic_ma20)
    assert math.isnan(result.ic_ma60)
    assert math.isnan(result.ratio)


def test_composite_handles_zero_baseline_ic_ma60_safely():
    """ic_ma60 接近 0 → ratio 用 NaN (避 ZeroDivisionError)."""
    import math

    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
        ic_ma20=0.05,
        ic_ma60=1e-10,  # ~0, 小于 MIN_ABS_IC_MA60=1e-6
    )
    assert result is not None
    assert math.isnan(result.ratio)  # 防除零


# ─── CompositeMode StrEnum sanity ─────────────────────────────────


def test_composite_mode_values_are_stable_strings():
    """CompositeMode 值是 stable contract (CLI / config 引用)."""
    assert CompositeMode.OFF.value == "off"
    assert CompositeMode.G1_ONLY.value == "g1-only"
    assert CompositeMode.STRICT.value == "strict"


def test_composite_mode_default_off_for_backward_compat():
    """默认 mode=OFF — 调用方不传 mode 时不改变行为 (生产兼容)."""
    # 老 None + 全 pass + 默认 mode → None
    report = _make_report(failed_gates=[])
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report,
        # mode 默认
    )
    assert result is None

    # 老 None + 新 G1 fail + 默认 mode (OFF) → None (G1 不参与)
    report_fail = _make_report(failed_gates=["G1_ic_significance"])
    result2 = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=report_fail,
    )
    assert result2 is None


def test_composite_handles_none_report():
    """new_report=None → 等同 0 failed gates → 透传老决策 / None."""
    result = compute_composite_decision(
        factor_name="f1",
        current_status="active",
        old_decision=None,
        new_report=None,
        mode=CompositeMode.STRICT,
    )
    assert result is None  # 老 None + 0 failed gates → None


# ─── P1.1 + P1.2 recovery suppression (reviewer fix 2026-04-28 PR #128) ─────


def test_composite_g1_only_suppresses_recovery_when_g1_fails():
    """warning→active recovery + G1 fail → suppress recovery (返 None, 留 warning).

    设计意图: ratio 已恢复 (decay 逆转) 但 G1 仍 fail (absolute insignificance) →
    保守保持 demoted, 防 'ratio 假恢复 + 真无效' 误恢复.
    """
    recovery = _make_old_decision_recovery("f1")
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,  # 真实场景: 当前 warning
        old_decision=recovery,                       # 老路径建议恢复
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    assert result is None  # recovery 被 G1 fail 抑制


def test_composite_g1_only_passes_recovery_through_when_no_trigger():
    """warning→active recovery + 全 pass → 透传 recovery (老路径 + 新路径都说健康)."""
    recovery = _make_old_decision_recovery("f1")
    report = _make_report(failed_gates=[])  # 全 pass
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,
        old_decision=recovery,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    assert result is recovery  # 双路径同意恢复 → 透传


def test_composite_strict_suppresses_recovery_on_g10_fail():
    """STRICT: warning→active recovery + 仅 G10 fail → 也 suppress (G10 在 STRICT 触发集)."""
    recovery = _make_old_decision_recovery("f1")
    report = _make_report(failed_gates=["G10_hypothesis"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,
        old_decision=recovery,
        new_report=report,
        mode=CompositeMode.STRICT,
    )
    assert result is None  # STRICT 含 G10, suppress recovery


def test_composite_off_passes_recovery_unchanged_even_with_g1_fail():
    """OFF mode: recovery + G1 fail → 透传 recovery (生产兼容, 不参与 OR 复合)."""
    recovery = _make_old_decision_recovery("f1")
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,
        old_decision=recovery,
        new_report=report,
        mode=CompositeMode.OFF,
    )
    assert result is recovery  # OFF 不参与, 老路径绝对权威


def test_composite_warning_status_with_old_demote_decision_passes_through():
    """warning 状态 + 老 warning→critical 升级决策 → 透传升级 (老路径主导持续性)."""
    upgrade = TransitionDecision(
        factor_name="f1",
        from_status=FactorStatus.WARNING.value,
        to_status=FactorStatus.CRITICAL.value,
        reason="ratio<0.5 持续 20 天",
        ic_ma20=0.02,
        ic_ma60=0.06,
        ratio=0.333,
    )
    report = _make_report(failed_gates=["G1_ic_significance"])
    result = compute_composite_decision(
        factor_name="f1",
        current_status=FactorStatus.WARNING.value,
        old_decision=upgrade,
        new_report=report,
        mode=CompositeMode.G1_ONLY,
    )
    # 老 decision 已是 demote (warning→critical, to_status != active) → 优先返老
    assert result is upgrade


def test_composite_invalid_mode_string_raises():
    """CLI / config 误传 'g1_only' (下划线) → CompositeMode 构造时 ValueError.

    (P2.1 reviewer 2026-04-28 PR #128: 文档化 hyphen 边界, 防 typo silent.)
    """
    import pytest as _pytest

    with _pytest.raises(ValueError, match="g1_only"):
        CompositeMode("g1_only")
