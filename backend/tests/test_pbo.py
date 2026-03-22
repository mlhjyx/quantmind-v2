"""Probability of Backtest Overfitting (PBO) 测试。

覆盖:
- 随机策略 PBO ≈ 0.5
- 明显优势策略 PBO ≈ 0
- n_partitions 验证（偶数、最小4）
- interpret_pbo 三级判断
- 边界和异常输入
"""

import math

import numpy as np
import pytest

from engines.pbo import interpret_pbo, probability_of_backtest_overfitting


# ===========================================================================
# PBO核心功能测试
# ===========================================================================


class TestPBO:
    """PBO计算核心逻辑。"""

    def test_random_strategies_pbo_around_half(self):
        """纯随机策略（无真实alpha），PBO应接近0.5。

        N个随机策略中选IS最优，在OOS中排名不应有系统性偏好，
        因此PBO(logit > 0的概率) ≈ 0.5。
        """
        rng = np.random.default_rng(42)
        # 20个纯随机策略 × 500时间点
        returns = rng.normal(0, 0.01, size=(20, 500))

        result = probability_of_backtest_overfitting(returns, n_partitions=8)

        assert 0.2 <= result["pbo"] <= 0.8, (
            f"随机策略PBO={result['pbo']:.3f}，应在0.2~0.8附近"
        )

    def test_strong_strategy_low_pbo(self):
        """一个策略有明显持续alpha，PBO应接近0。

        如果策略0在每个时间段都明显优于其他策略，
        则IS最优选出策略0后，OOS中策略0仍然排名靠前 → logit < 0 → PBO低。
        """
        rng = np.random.default_rng(42)
        n_strategies = 10
        n_timepoints = 600

        # 大部分策略是噪声
        returns = rng.normal(0, 0.01, size=(n_strategies, n_timepoints))
        # 策略0有持续正alpha（每个时间点+0.005）
        returns[0] += 0.005

        result = probability_of_backtest_overfitting(returns, n_partitions=8)

        assert result["pbo"] < 0.3, (
            f"强alpha策略PBO={result['pbo']:.3f}，应 < 0.3"
        )

    def test_overfit_strategies_high_pbo(self):
        """大量策略中最优者大概率是过拟合产物 → PBO偏高。

        100个随机策略中挑IS最优的，IS最优≠OOS最优的概率较大。
        PBO应至少接近随机水平（≈0.5），不应很低。
        """
        rng = np.random.default_rng(42)
        # 100个纯噪声策略，更多策略更容易overfit
        returns = rng.normal(0, 0.01, size=(100, 400))

        result = probability_of_backtest_overfitting(returns, n_partitions=8)

        # 纯噪声策略PBO不应很低（即不应看起来像有真实alpha）
        assert result["pbo"] >= 0.15, (
            f"100个噪声策略PBO={result['pbo']:.3f}，不应低于0.15"
        )

    def test_result_structure(self):
        """返回字典包含所有必要字段。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 100))

        result = probability_of_backtest_overfitting(returns, n_partitions=4)

        required_keys = {"pbo", "logit_distribution", "n_combinations",
                         "n_partitions", "n_strategies", "n_timepoints"}
        assert required_keys.issubset(result.keys())
        assert 0 <= result["pbo"] <= 1
        assert result["n_strategies"] == 5
        assert result["n_timepoints"] == 100
        assert result["n_partitions"] == 4

    def test_n_combinations_correct(self):
        """组合数 C(S, S/2) 应正确计算。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 100))

        result = probability_of_backtest_overfitting(returns, n_partitions=8)

        expected_combos = math.comb(8, 4)  # C(8,4) = 70
        assert result["n_combinations"] == expected_combos
        assert len(result["logit_distribution"]) == expected_combos

    def test_logit_distribution_length(self):
        """logit_distribution长度应等于组合数。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 200))

        for n_parts in [4, 6, 8]:
            result = probability_of_backtest_overfitting(returns, n_partitions=n_parts)
            expected = math.comb(n_parts, n_parts // 2)
            assert len(result["logit_distribution"]) == expected


# ===========================================================================
# n_partitions参数验证
# ===========================================================================


class TestPBOPartitions:
    """n_partitions 边界验证。"""

    def test_odd_partitions_rejected(self):
        """奇数分区数应抛ValueError。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 100))

        with pytest.raises(ValueError, match="偶数"):
            probability_of_backtest_overfitting(returns, n_partitions=7)

    def test_min_partitions_4(self):
        """n_partitions < 4 应抛ValueError。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 100))

        with pytest.raises(ValueError, match=">=4"):
            probability_of_backtest_overfitting(returns, n_partitions=2)

    def test_partitions_4_works(self):
        """n_partitions=4（最小合法值）应正常运行。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 100))

        result = probability_of_backtest_overfitting(returns, n_partitions=4)

        assert result["n_partitions"] == 4
        assert result["n_combinations"] == math.comb(4, 2)  # C(4,2)=6

    def test_partitions_exceeding_max_truncated(self):
        """n_partitions > 20 被截断到20。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 1000))

        result = probability_of_backtest_overfitting(returns, n_partitions=22)

        assert result["n_partitions"] == 20

    def test_timepoints_less_than_partitions_rejected(self):
        """时间点数 < 分区数应抛ValueError。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(5, 6))

        with pytest.raises(ValueError, match="时间点数"):
            probability_of_backtest_overfitting(returns, n_partitions=8)


# ===========================================================================
# 输入验证
# ===========================================================================


class TestPBOInputValidation:
    """输入参数验证。"""

    def test_1d_array_rejected(self):
        """1D数组应被拒绝。"""
        returns = np.random.default_rng(42).normal(0, 0.01, size=(100,))
        with pytest.raises(ValueError, match="2D"):
            probability_of_backtest_overfitting(returns)

    def test_single_strategy_rejected(self):
        """单个策略应被拒绝（至少需要2个）。"""
        returns = np.random.default_rng(42).normal(0, 0.01, size=(1, 100))
        with pytest.raises(ValueError, match="至少需要2个"):
            probability_of_backtest_overfitting(returns)

    def test_two_strategies_works(self):
        """2个策略（最小合法值）应正常运行。"""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(2, 100))

        result = probability_of_backtest_overfitting(returns, n_partitions=4)
        assert result["n_strategies"] == 2
        assert 0 <= result["pbo"] <= 1


# ===========================================================================
# interpret_pbo三级判断
# ===========================================================================


class TestInterpretPBO:
    """interpret_pbo 解读文本。"""

    def test_low_risk(self):
        """PBO < 0.3 → 低过拟合风险。"""
        text = interpret_pbo(0.1)
        assert "低过拟合" in text

    def test_medium_risk(self):
        """PBO 0.3~0.6 → 中等过拟合风险。"""
        text = interpret_pbo(0.45)
        assert "中等" in text

    def test_high_risk(self):
        """PBO > 0.6 → 高过拟合风险。"""
        text = interpret_pbo(0.75)
        assert "高过拟合" in text

    def test_negative_pbo(self):
        """PBO < 0 → 数据不足。"""
        text = interpret_pbo(-1)
        assert "数据不足" in text

    def test_boundary_030(self):
        """PBO = 0.3 → 中等风险（边界）。"""
        text = interpret_pbo(0.3)
        assert "中等" in text

    def test_boundary_060(self):
        """PBO = 0.6 → 高风险（边界）。"""
        text = interpret_pbo(0.6)
        assert "高过拟合" in text

    def test_zero_pbo(self):
        """PBO = 0 → 低风险。"""
        text = interpret_pbo(0.0)
        assert "低过拟合" in text

    def test_pbo_one(self):
        """PBO = 1.0 → 高风险。"""
        text = interpret_pbo(1.0)
        assert "高过拟合" in text
