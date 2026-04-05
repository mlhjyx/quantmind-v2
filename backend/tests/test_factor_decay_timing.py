"""C3 因子衰减3级处置 + C4 因子择时权重调整 测试。

C3测试:
- test_decay_l1_trigger — IC_MA20 < IC_MA60×0.8 触发L1
- test_decay_l2_trigger — IC_MA20 < IC_MA60×0.5 触发L2
- test_decay_l3_trigger — IC<0.01连续60天触发L3
- test_healthy_factor_stays_l0 — 正常因子保持L0
- test_boundary_exactly_0_8 — 精确边界测试

C4测试:
- test_timing_equal_ic_returns_equal_weight — 无调整
- test_timing_strong_ic_upweight — 上调到1.5x
- test_timing_weak_ic_downweight — 下调到0.5x
- test_timing_weights_sum_to_one — 归一化
- test_timing_insufficient_data_fallback — 数据不足返回等权
- test_timing_l2_override — L2强制0.5x
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.factor_decay import (
    L1_RATIO,
    DecayLevel,
    DecayResult,
    calc_consecutive_low_ic_days,
    check_all_factors_decay,
    check_factor_decay,
    classify_decay_level,
)
from engines.factor_timing import (
    calc_timing_score,
    calc_timing_weights,
    compare_timing_vs_equal,
)

# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════

def _make_ic_series(
    values: list[float],
    start_date: str = "2023-01-02",
) -> pd.Series:
    """构造IC时序。"""
    dates = pd.bdate_range(start_date, periods=len(values))
    return pd.Series(values, index=dates)


# ═══════════════════════════════════════════════════
# C3: 因子衰减3级处置
# ═══════════════════════════════════════════════════

class TestDecayClassification:
    """classify_decay_level() 分级判定。"""

    def test_l0_healthy(self):
        """IC_MA20 >= IC_MA60 × 0.8 → L0。"""
        assert classify_decay_level(0.045, 0.05, 0) == DecayLevel.L0

    def test_l1_trigger(self):
        """IC_MA20 < IC_MA60 × 0.8 but >= 0.5 → L1。"""
        # IC_MA60=0.05, L1阈值=0.04, L2阈值=0.025
        # IC_MA20=0.035 < 0.04 but >= 0.025
        assert classify_decay_level(0.035, 0.05, 0) == DecayLevel.L1

    def test_l2_trigger(self):
        """IC_MA20 < IC_MA60 × 0.5 → L2。"""
        # IC_MA60=0.05, L2阈值=0.025
        # IC_MA20=0.02 < 0.025
        assert classify_decay_level(0.02, 0.05, 0) == DecayLevel.L2

    def test_l3_trigger(self):
        """IC<0.01连续60天 → L3（优先于L1/L2）。"""
        # 即使IC比值ok，连续低IC天数>=60仍触发L3
        assert classify_decay_level(0.04, 0.05, 60) == DecayLevel.L3
        assert classify_decay_level(0.04, 0.05, 100) == DecayLevel.L3

    def test_l3_not_triggered_at_59_days(self):
        """连续59天不触发L3（仍按IC比值判定）。"""
        # 0.045 >= 0.05*0.8=0.04 → L0
        assert classify_decay_level(0.045, 0.05, 59) == DecayLevel.L0

    def test_boundary_exactly_0_8(self):
        """IC_MA20 = IC_MA60 × 0.8 精确边界 → L0（不含等号）。"""
        ic_ma60 = 0.05
        ic_ma20 = ic_ma60 * L1_RATIO  # 恰好等于阈值
        # ic_ma20 < ic_ma60 * 0.8 为 False → L0
        assert classify_decay_level(ic_ma20, ic_ma60, 0) == DecayLevel.L0

    def test_boundary_just_below_0_8(self):
        """IC_MA20 略低于 IC_MA60 × 0.8 → L1。"""
        ic_ma60 = 0.05
        ic_ma20 = ic_ma60 * L1_RATIO - 0.0001
        assert classify_decay_level(ic_ma20, ic_ma60, 0) == DecayLevel.L1

    def test_zero_ic_ma60(self):
        """IC_MA60=0时不除零，使用绝对值判断。"""
        assert classify_decay_level(0.005, 0.0, 0) == DecayLevel.L2
        assert classify_decay_level(0.02, 0.0, 0) == DecayLevel.L0


class TestConsecutiveLowIC:
    """calc_consecutive_low_ic_days() 连续低IC天数。"""

    def test_all_low(self):
        """全部低于阈值。"""
        ic = _make_ic_series([0.005] * 70)
        assert calc_consecutive_low_ic_days(ic) == 70

    def test_recent_recovery(self):
        """最近一天恢复 → 连续天数=0。"""
        vals = [0.005] * 60 + [0.05]
        ic = _make_ic_series(vals)
        assert calc_consecutive_low_ic_days(ic) == 0

    def test_partial_low(self):
        """中间恢复后又低 → 只数最后一段。"""
        vals = [0.005] * 30 + [0.05] + [0.005] * 10
        ic = _make_ic_series(vals)
        assert calc_consecutive_low_ic_days(ic) == 10

    def test_empty(self):
        """空序列。"""
        assert calc_consecutive_low_ic_days(pd.Series(dtype=float)) == 0

    def test_nan_counted_as_low(self):
        """NaN视为低IC（数据缺失=因子无预测力）。"""
        vals = [0.05] + [np.nan] * 5
        ic = _make_ic_series(vals)
        assert calc_consecutive_low_ic_days(ic) == 5


class TestCheckFactorDecay:
    """check_factor_decay() 完整流程。"""

    def test_healthy_factor(self):
        """正常因子: 稳定IC → L0。"""
        rng = np.random.RandomState(42)
        ic = _make_ic_series(
            list(rng.normal(0.04, 0.01, 100))  # 稳定正IC
        )
        result = check_factor_decay("test_factor", ic)
        assert result.decay_level == DecayLevel.L0
        assert result.weight_multiplier == 1.0

    def test_decaying_factor_l2(self):
        """衰减因子: 近期IC远低于长期 → L2。"""
        # 前60天高IC，后20天低IC
        vals = [0.05] * 60 + [0.01] * 20
        ic = _make_ic_series(vals)
        result = check_factor_decay("decaying", ic)
        assert result.decay_level == DecayLevel.L2
        assert result.weight_multiplier == 0.5

    def test_retired_factor_l3(self):
        """失效因子: IC<0.01连续60天 → L3。"""
        vals = [0.05] * 20 + [0.005] * 65
        ic = _make_ic_series(vals)
        result = check_factor_decay("retired", ic)
        assert result.decay_level == DecayLevel.L3
        assert result.weight_multiplier == 0.0
        assert result.target_status == "candidate"

    def test_result_has_all_fields(self):
        """DecayResult包含所有必需字段。"""
        ic = _make_ic_series([0.04] * 80)
        result = check_factor_decay("test", ic)
        assert hasattr(result, "factor_name")
        assert hasattr(result, "decay_level")
        assert hasattr(result, "ic_ma20")
        assert hasattr(result, "ic_ma60")
        assert hasattr(result, "consecutive_low_days")
        assert hasattr(result, "reason")
        assert hasattr(result, "l1_threshold")
        assert hasattr(result, "l2_threshold")


class TestCheckAllFactorsDecay:
    """check_all_factors_decay() 批量检测。"""

    def test_multiple_factors(self):
        """多因子批量检测。"""
        data = {
            "healthy": _make_ic_series([0.04] * 80),
            "decaying": _make_ic_series([0.05] * 60 + [0.01] * 20),
        }
        results = check_all_factors_decay(data)
        assert len(results) == 2
        levels = {r.factor_name: r.decay_level for r in results}
        assert levels["healthy"] == DecayLevel.L0
        assert levels["decaying"] == DecayLevel.L2


# ═══════════════════════════════════════════════════
# C4: 因子择时权重调整
# ═══════════════════════════════════════════════════

class TestTimingScore:
    """calc_timing_score() 择时分数。"""

    def test_equal_ic_returns_one(self):
        """IC_MA20 = IC_MA60 → score = 1.0。"""
        ic = _make_ic_series([0.04] * 80)
        score = calc_timing_score(ic)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_strong_recent_ic(self):
        """近期IC强 → score > 1.0。"""
        vals = [0.03] * 60 + [0.06] * 20
        ic = _make_ic_series(vals)
        score = calc_timing_score(ic)
        assert score is not None
        assert score > 1.0

    def test_weak_recent_ic(self):
        """近期IC弱 → score < 1.0。"""
        vals = [0.06] * 60 + [0.02] * 20
        ic = _make_ic_series(vals)
        score = calc_timing_score(ic)
        assert score is not None
        assert score < 1.0

    def test_insufficient_data(self):
        """数据不足 → None。"""
        ic = _make_ic_series([0.04] * 30)
        assert calc_timing_score(ic) is None


class TestTimingWeights:
    """calc_timing_weights() 权重计算。"""

    def test_equal_ic_returns_equal_weight(self):
        """所有因子IC_MA20=IC_MA60 → 等权。"""
        factors = ["f1", "f2", "f3"]
        ic_data = {f: _make_ic_series([0.04] * 80) for f in factors}
        weights = calc_timing_weights(factors, ic_data)
        for f in factors:
            assert weights[f] == pytest.approx(1.0 / 3, abs=0.01)

    def test_strong_ic_upweight(self):
        """强IC因子 → 权重上调。"""
        factors = ["strong", "normal"]
        ic_data = {
            "strong": _make_ic_series([0.03] * 60 + [0.06] * 20),
            "normal": _make_ic_series([0.04] * 80),
        }
        weights = calc_timing_weights(factors, ic_data)
        assert weights["strong"] > weights["normal"]

    def test_weak_ic_downweight(self):
        """弱IC因子 → 权重下调。"""
        factors = ["weak", "normal"]
        ic_data = {
            "weak": _make_ic_series([0.06] * 60 + [0.02] * 20),
            "normal": _make_ic_series([0.04] * 80),
        }
        weights = calc_timing_weights(factors, ic_data)
        assert weights["weak"] < weights["normal"]

    def test_weights_sum_to_one(self):
        """权重总和 = 1.0。"""
        factors = ["f1", "f2", "f3", "f4"]
        rng = np.random.RandomState(42)
        ic_data = {}
        for f in factors:
            base = rng.uniform(0.02, 0.06)
            recent = rng.uniform(0.01, 0.08)
            ic_data[f] = _make_ic_series(
                [base] * 60 + [recent] * 20
            )
        weights = calc_timing_weights(factors, ic_data)
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-10)

    def test_insufficient_data_fallback(self):
        """IC数据不足 → 返回等权（不调整）。"""
        factors = ["f1", "f2"]
        ic_data = {
            "f1": _make_ic_series([0.04] * 30),  # 不足60天
            "f2": _make_ic_series([0.04] * 30),
        }
        weights = calc_timing_weights(factors, ic_data)
        assert weights["f1"] == pytest.approx(0.5, abs=0.01)
        assert weights["f2"] == pytest.approx(0.5, abs=0.01)

    def test_no_ic_data_fallback(self):
        """完全没有IC数据 → 等权。"""
        factors = ["f1", "f2"]
        weights = calc_timing_weights(factors, {})
        assert weights["f1"] == pytest.approx(0.5)
        assert weights["f2"] == pytest.approx(0.5)

    def test_l2_override(self):
        """L2衰减因子: 权重被强制cap到0.5x。"""
        factors = ["healthy", "l2_decay"]
        ic_data = {f: _make_ic_series([0.04] * 80) for f in factors}

        # L2衰减结果
        decay_results = [
            DecayResult(
                factor_name="l2_decay",
                decay_level=DecayLevel.L2,
                ic_ma20=0.01, ic_ma60=0.04,
                consecutive_low_days=0,
                reason="test",
                l1_threshold=0.032, l2_threshold=0.02,
            ),
        ]

        weights = calc_timing_weights(factors, ic_data, decay_results=decay_results)

        # healthy权重 > l2_decay权重
        assert weights["healthy"] > weights["l2_decay"]
        # 归一化后仍然sum=1
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-10)

    def test_l3_zero_weight(self):
        """L3退役因子: 权重=0（归一化后其他因子分担）。"""
        factors = ["active", "retired"]
        ic_data = {f: _make_ic_series([0.04] * 80) for f in factors}

        decay_results = [
            DecayResult(
                factor_name="retired",
                decay_level=DecayLevel.L3,
                ic_ma20=0.005, ic_ma60=0.04,
                consecutive_low_days=65,
                reason="test",
                l1_threshold=0.032, l2_threshold=0.02,
            ),
        ]

        weights = calc_timing_weights(factors, ic_data, decay_results=decay_results)
        # active gets all weight after normalization
        assert weights["active"] == pytest.approx(1.0, abs=0.01)
        assert weights["retired"] == pytest.approx(0.0, abs=0.01)

    def test_custom_base_weights(self):
        """自定义基础权重。"""
        factors = ["f1", "f2"]
        ic_data = {f: _make_ic_series([0.04] * 80) for f in factors}
        base = {"f1": 0.7, "f2": 0.3}
        weights = calc_timing_weights(factors, ic_data, base_weights=base)
        # IC相同 → timing_score=1.0 → 权重比例保持
        assert weights["f1"] > weights["f2"]
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-10)


class TestCompareTimingVsEqual:
    """compare_timing_vs_equal() 对比报告。"""

    def test_report_structure(self):
        """报告包含必需字段。"""
        factors = ["f1", "f2"]
        ic_data = {f: _make_ic_series([0.04] * 80) for f in factors}
        report = compare_timing_vs_equal(factors, ic_data)

        assert "equal_weights" in report
        assert "timing_weights" in report
        assert "timing_scores" in report
        assert "weight_changes" in report
        assert sum(report["equal_weights"].values()) == pytest.approx(1.0)
        assert sum(report["timing_weights"].values()) == pytest.approx(1.0)
