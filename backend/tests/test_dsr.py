"""Deflated Sharpe Ratio (DSR) 单元测试。

测试覆盖:
  - deflated_sharpe_ratio() 基本计算正确性
  - n_trials=1 退化为简单显著性检验
  - DSR<0.95 标记过拟合
  - 非正态校正（偏度/峰度影响）
  - 边界条件和输入校验

不依赖数据库，纯数学计算测试。
"""

import math

import pytest
from engines.dsr import (
    _expected_max_sharpe,
    _sharpe_std,
    deflated_sharpe_ratio,
    interpret_dsr,
)

# ────────────────────────────────────────────
# _sharpe_std 内部函数测试
# ────────────────────────────────────────────

class TestSharpeStd:
    """Sharpe标准差估计函数测试。"""

    def test_normal_distribution(self) -> None:
        """正态分布(skew=0, kurt=3)下，Var(SR) = 1/T。"""
        sr = 0.05  # 日频sharpe
        t = 250
        result = _sharpe_std(sr, t, skewness=0.0, kurtosis=3.0)
        expected = math.sqrt(1.0 / t)
        assert abs(result - expected) < 1e-10

    def test_zero_sharpe_normal(self) -> None:
        """SR=0时，无论偏度峰度如何，分子=1。"""
        result = _sharpe_std(0.0, 250, skewness=-1.0, kurtosis=5.0)
        expected = math.sqrt(1.0 / 250)
        assert abs(result - expected) < 1e-10

    def test_negative_skew_increases_std(self) -> None:
        """负偏度 + 正SR → 增加Sharpe方差(分子>1)。"""
        sr = 0.1
        normal_std = _sharpe_std(sr, 250, skewness=0.0, kurtosis=3.0)
        negskew_std = _sharpe_std(sr, 250, skewness=-1.0, kurtosis=3.0)
        # skew=-1, sr=0.1: 分子 = 1 - (-1)*0.1/3 = 1 + 0.033 > 1
        assert negskew_std > normal_std

    def test_excess_kurtosis_increases_std(self) -> None:
        """超额峰度(kurt>3) + 正SR → 增加Sharpe方差。"""
        sr = 0.1
        normal_std = _sharpe_std(sr, 250, skewness=0.0, kurtosis=3.0)
        fat_tail_std = _sharpe_std(sr, 250, skewness=0.0, kurtosis=6.0)
        # kurt=6: 分子 = 1 + (6-3)*0.01/4 = 1.0075 > 1
        assert fat_tail_std > normal_std

    def test_more_observations_reduces_std(self) -> None:
        """更多观测数降低Sharpe的标准差。"""
        std_250 = _sharpe_std(0.05, 250, 0.0, 3.0)
        std_1000 = _sharpe_std(0.05, 1000, 0.0, 3.0)
        assert std_1000 < std_250

    def test_min_observations_clamp(self) -> None:
        """n_observations=0被clamp到1，不会除零。"""
        result = _sharpe_std(0.05, 0, 0.0, 3.0)
        assert math.isfinite(result)
        assert result > 0


# ────────────────────────────────────────────
# _expected_max_sharpe 内部函数测试
# ────────────────────────────────────────────

class TestExpectedMaxSharpe:
    """多重检验下期望最大Sharpe测试。"""

    def test_single_trial_returns_zero(self) -> None:
        """n_trials=1时，期望最大Sharpe为0(无膨胀)。"""
        result = _expected_max_sharpe(1, sharpe_std=0.05)
        assert result == 0.0

    def test_more_trials_increases_expected_max(self) -> None:
        """更多试验次数 → 期望最大Sharpe更高。"""
        e10 = _expected_max_sharpe(10, sharpe_std=0.05)
        e100 = _expected_max_sharpe(100, sharpe_std=0.05)
        e1000 = _expected_max_sharpe(1000, sharpe_std=0.05)
        assert e10 < e100 < e1000

    def test_larger_std_increases_expected_max(self) -> None:
        """更大的Sharpe标准差 → 期望最大值更高。"""
        e_small = _expected_max_sharpe(50, sharpe_std=0.02)
        e_large = _expected_max_sharpe(50, sharpe_std=0.10)
        assert e_small < e_large

    def test_positive_result(self) -> None:
        """n_trials>1时结果应为正。"""
        result = _expected_max_sharpe(10, sharpe_std=0.05)
        assert result > 0.0


# ────────────────────────────────────────────
# deflated_sharpe_ratio 主函数测试
# ────────────────────────────────────────────

class TestDeflatedSharpeRatio:
    """DSR主函数测试。"""

    def test_basic_calculation_returns_valid_range(self) -> None:
        """DSR返回值在[0, 1]区间。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=1.2,
            n_trials=50,
            n_observations=1000,
            skewness=-0.3,
            kurtosis=4.5,
        )
        assert 0.0 <= dsr <= 1.0

    def test_high_sharpe_few_trials_gives_high_dsr(self) -> None:
        """高Sharpe + 少试验次数 → 高DSR(显著)。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=2.0,
            n_trials=5,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert dsr > 0.95

    def test_low_sharpe_many_trials_gives_low_dsr(self) -> None:
        """低Sharpe + 大量试验 → 低DSR(过拟合)。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=0.5,
            n_trials=1000,
            n_observations=500,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert dsr < 0.5

    def test_more_trials_decreases_dsr(self) -> None:
        """固定Sharpe，增加试验次数 → DSR下降。"""
        common = dict(
            observed_sharpe=1.0,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
        )
        dsr_10 = deflated_sharpe_ratio(n_trials=10, **common)
        dsr_100 = deflated_sharpe_ratio(n_trials=100, **common)
        dsr_1000 = deflated_sharpe_ratio(n_trials=1000, **common)
        assert dsr_10 > dsr_100 > dsr_1000

    def test_more_observations_increases_dsr(self) -> None:
        """固定其他参数，增加观测数 → DSR上升(样本更充分)。"""
        common = dict(
            observed_sharpe=1.0,
            n_trials=50,
            skewness=0.0,
            kurtosis=3.0,
        )
        dsr_250 = deflated_sharpe_ratio(n_observations=250, **common)
        dsr_2500 = deflated_sharpe_ratio(n_observations=2500, **common)
        assert dsr_2500 > dsr_250

    # ── n_trials=1 退化测试 ──

    def test_n_trials_1_degenerates_to_simple_test(self) -> None:
        """n_trials=1时退化为简单Sharpe显著性检验(无多重检验校正)。"""
        # 正态分布，高Sharpe → 应该显著
        dsr = deflated_sharpe_ratio(
            observed_sharpe=2.0,
            n_trials=1,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
        )
        # n_trials=1: DSR = Phi(SR_obs / sigma_SR)
        # 高Sharpe应该给出接近1的DSR
        assert dsr > 0.95

    def test_n_trials_1_zero_sharpe(self) -> None:
        """n_trials=1, SR=0 → DSR=0.5 (50%概率, 不显著)。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=0.0,
            n_trials=1,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert abs(dsr - 0.5) < 0.01

    def test_n_trials_1_negative_sharpe(self) -> None:
        """n_trials=1, 负Sharpe → DSR<0.5。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=-1.0,
            n_trials=1,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert dsr < 0.5

    # ── DSR<0.95 过拟合标记测试 ──

    def test_overfitting_flag_threshold(self) -> None:
        """DSR<0.95的策略应被标记为可疑/过拟合。"""
        # 中等Sharpe + 大量试验 → DSR<0.95
        dsr = deflated_sharpe_ratio(
            observed_sharpe=1.0,
            n_trials=200,
            n_observations=500,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert dsr < 0.95, f"DSR={dsr:.4f}应<0.95(过拟合嫌疑)"

    def test_genuine_alpha_passes_threshold(self) -> None:
        """真实alpha(高SR+少试验+长样本)应通过0.95阈值。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=2.5,
            n_trials=3,
            n_observations=2500,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert dsr > 0.95, f"DSR={dsr:.4f}应>0.95(真实alpha)"

    # ── 非正态校正测试 ──

    def test_negative_skew_reduces_dsr(self) -> None:
        """负偏度(左尾肥) → DSR下降(高估风险)。"""
        common = dict(
            observed_sharpe=1.0,
            n_trials=50,
            n_observations=1000,
            kurtosis=3.0,
        )
        dsr_normal = deflated_sharpe_ratio(skewness=0.0, **common)
        dsr_negskew = deflated_sharpe_ratio(skewness=-2.0, **common)
        assert dsr_negskew < dsr_normal

    def test_fat_tails_reduces_dsr(self) -> None:
        """尖峰厚尾(kurtosis>3) → DSR下降。"""
        common = dict(
            observed_sharpe=1.0,
            n_trials=50,
            n_observations=1000,
            skewness=0.0,
        )
        dsr_normal = deflated_sharpe_ratio(kurtosis=3.0, **common)
        dsr_fat = deflated_sharpe_ratio(kurtosis=8.0, **common)
        assert dsr_fat < dsr_normal

    def test_positive_skew_increases_dsr(self) -> None:
        """正偏度(右尾肥) → DSR上升(低估风险但实际分布有利)。"""
        common = dict(
            observed_sharpe=1.0,
            n_trials=50,
            n_observations=1000,
            kurtosis=3.0,
        )
        dsr_normal = deflated_sharpe_ratio(skewness=0.0, **common)
        dsr_posskew = deflated_sharpe_ratio(skewness=1.0, **common)
        assert dsr_posskew > dsr_normal

    # ── 外部提供sharpe_std测试 ──

    def test_custom_sharpe_std(self) -> None:
        """传入自定义sharpe_std(例如从bootstrap获得)。"""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=1.5,
            n_trials=20,
            n_observations=1000,
            skewness=0.0,
            kurtosis=3.0,
            sharpe_std=0.05,
        )
        assert 0.0 <= dsr <= 1.0

    # ── 输入校验测试 ──

    def test_invalid_n_trials_raises(self) -> None:
        """n_trials<1应抛ValueError。"""
        with pytest.raises(ValueError, match="n_trials"):
            deflated_sharpe_ratio(
                observed_sharpe=1.0,
                n_trials=0,
                n_observations=1000,
                skewness=0.0,
                kurtosis=3.0,
            )

    def test_invalid_n_observations_raises(self) -> None:
        """n_observations<2应抛ValueError。"""
        with pytest.raises(ValueError, match="n_observations"):
            deflated_sharpe_ratio(
                observed_sharpe=1.0,
                n_trials=10,
                n_observations=1,
                skewness=0.0,
                kurtosis=3.0,
            )


# ────────────────────────────────────────────
# interpret_dsr 测试
# ────────────────────────────────────────────

class TestInterpretDSR:
    """DSR解读函数测试。"""

    def test_significant(self) -> None:
        result = interpret_dsr(0.96)
        assert "统计显著" in result

    def test_suspicious(self) -> None:
        result = interpret_dsr(0.7)
        assert "可疑" in result

    def test_not_significant(self) -> None:
        result = interpret_dsr(0.3)
        assert "不显著" in result

    def test_boundary_095(self) -> None:
        """0.95边界: >0.95才是显著。"""
        assert "可疑" in interpret_dsr(0.95)
        assert "统计显著" in interpret_dsr(0.951)

    def test_boundary_050(self) -> None:
        """0.5边界: >0.5才是可疑。"""
        assert "不显著" in interpret_dsr(0.5)
        assert "可疑" in interpret_dsr(0.501)
