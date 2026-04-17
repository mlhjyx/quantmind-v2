"""Unit tests for factor_lifecycle — pure rule evaluator (铁律 31).

Covers:
  - active ↔ warning 轻度衰减
  - warning → critical (需持续 20 天)
  - warning → active 恢复
  - candidate/critical/retired 不自动转换
  - 边界: ic_ma60 ≈ 0, None 输入
  - count_days_below_critical 工具函数
"""

from __future__ import annotations

import pytest
from engines.factor_lifecycle import (
    CRITICAL_PERSISTENCE_DAYS,
    CRITICAL_RATIO,
    WARNING_RATIO,
    FactorStatus,
    count_days_below_critical,
    evaluate_transition,
)


class TestActiveToWarning:
    def test_healthy_stays_active(self):
        # ratio = 0.9 > 0.8 → no transition
        assert (
            evaluate_transition("f", FactorStatus.ACTIVE.value, 0.090, 0.100) is None
        )

    def test_at_threshold_stays_active(self):
        # ratio == 0.8 (not strictly less than) → no transition
        # 用 0.4/0.5 保证 float 精确等于 0.8
        assert (
            evaluate_transition("f", FactorStatus.ACTIVE.value, 0.4, 0.5) is None
        )

    def test_below_threshold_transitions_to_warning(self):
        # ratio = 0.7 < 0.8 → warning
        d = evaluate_transition("f", FactorStatus.ACTIVE.value, 0.070, 0.100)
        assert d is not None
        assert d.from_status == "active"
        assert d.to_status == "warning"
        assert d.ratio == pytest.approx(0.7)

    def test_negative_ic_direction_uses_abs(self):
        # 负向因子 ic_ma20=-0.03, ic_ma60=-0.10 → |ratio|=0.3 → warning
        d = evaluate_transition("f", FactorStatus.ACTIVE.value, -0.030, -0.100)
        assert d is not None
        assert d.to_status == "warning"


class TestWarningToCritical:
    def test_below_critical_but_not_persistent_stays_warning(self):
        d = evaluate_transition(
            "f", FactorStatus.WARNING.value, 0.020, 0.100,
            days_below_critical=10,
        )
        assert d is None

    def test_persistent_below_critical_transitions(self):
        d = evaluate_transition(
            "f", FactorStatus.WARNING.value, 0.020, 0.100,
            days_below_critical=CRITICAL_PERSISTENCE_DAYS,
        )
        assert d is not None
        assert d.from_status == "warning"
        assert d.to_status == "critical"
        assert "持续" in d.reason

    def test_persistence_threshold_at_exactly_20(self):
        # 恰好 20 天 → 转 critical
        d = evaluate_transition(
            "f", FactorStatus.WARNING.value, 0.020, 0.100,
            days_below_critical=20,
        )
        assert d is not None
        assert d.to_status == "critical"

    def test_ratio_above_critical_blocks_transition(self):
        # ratio = 0.6 (warning 区间), 持续 30 天不触发 critical
        d = evaluate_transition(
            "f", FactorStatus.WARNING.value, 0.060, 0.100,
            days_below_critical=30,
        )
        assert d is None


class TestWarningRecovery:
    def test_recovery_to_active(self):
        # warning 状态, ratio 回到 0.9 ≥ 0.8 → active
        d = evaluate_transition("f", FactorStatus.WARNING.value, 0.090, 0.100)
        assert d is not None
        assert d.from_status == "warning"
        assert d.to_status == "active"
        assert "恢复" in d.reason

    def test_boundary_ratio_exactly_0_8_recovers(self):
        # 0.4/0.5 = 0.8 精确, warning 状态下 ratio ≥ 0.8 → 恢复 active
        d = evaluate_transition("f", FactorStatus.WARNING.value, 0.4, 0.5)
        assert d is not None
        assert d.to_status == "active"


class TestTerminalStates:
    def test_candidate_no_auto_transition(self):
        assert evaluate_transition("f", FactorStatus.CANDIDATE.value, 0.01, 0.10) is None

    def test_critical_no_auto_transition(self):
        # critical → retired 需 L2 人确认, 本模块不动
        assert evaluate_transition("f", FactorStatus.CRITICAL.value, 0.01, 0.10) is None

    def test_retired_no_auto_transition(self):
        assert evaluate_transition("f", FactorStatus.RETIRED.value, 0.09, 0.10) is None


class TestEdgeCases:
    def test_none_ic_ma20(self):
        assert evaluate_transition("f", FactorStatus.ACTIVE.value, None, 0.10) is None

    def test_none_ic_ma60(self):
        assert evaluate_transition("f", FactorStatus.ACTIVE.value, 0.05, None) is None

    def test_baseline_ic_near_zero_skips(self):
        # |ic_ma60| < 1e-6 → 比率不稳定, 不转换
        assert (
            evaluate_transition("f", FactorStatus.ACTIVE.value, 0.05, 1e-7) is None
        )

    def test_baseline_ic_zero_skips(self):
        assert evaluate_transition("f", FactorStatus.ACTIVE.value, 0.05, 0.0) is None


class TestCountDaysBelowCritical:
    def test_empty_series(self):
        assert count_days_below_critical([]) == 0

    def test_all_above(self):
        ratios = [0.9, 0.85, 0.7, 0.6]
        assert count_days_below_critical(ratios) == 0

    def test_all_below(self):
        ratios = [0.4, 0.3, 0.2, 0.1]
        assert count_days_below_critical(ratios) == 4

    def test_streak_from_tail(self):
        # 只数尾部连续天数, 中间断裂前的不算
        ratios = [0.3, 0.8, 0.3, 0.2, 0.1]
        assert count_days_below_critical(ratios) == 3

    def test_breaks_on_non_below(self):
        ratios = [0.1, 0.9, 0.1]
        assert count_days_below_critical(ratios) == 1

    def test_lookback_caps(self):
        # 50 天全部满足, 但 lookback=20 只看最后 20 天
        ratios = [0.1] * 50
        assert count_days_below_critical(ratios, lookback_days=20) == 20

    def test_boundary_at_critical_ratio(self):
        # ratio == 0.5 (not strictly less than) → 不算
        assert count_days_below_critical([0.5, 0.5, 0.5]) == 0


class TestTransitionDecisionFields:
    def test_decision_fields_populated(self):
        d = evaluate_transition("turnover_mean_20", "active", 0.05, 0.10)
        assert d.factor_name == "turnover_mean_20"
        assert d.ic_ma20 == 0.05
        assert d.ic_ma60 == 0.10
        assert d.ratio == pytest.approx(0.5)


def test_thresholds_match_design_doc():
    """固化 V2.1 §3.1 阈值, 防止无意改动."""
    assert WARNING_RATIO == 0.8
    assert CRITICAL_RATIO == 0.5
    assert CRITICAL_PERSISTENCE_DAYS == 20
