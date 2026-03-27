"""turnover_stability_20 因子单元测试。

测试 calc_turnover_stability 函数的核心行为:
1. 常量序列 → std=0
2. 递增序列 → std>0
3. NaN处理（不够20天窗口）
4. 方向为-1确认（RESERVE_FACTOR_DIRECTION）
5. 注册表完整性
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.factor_engine import (
    RESERVE_FACTOR_DIRECTION,
    RESERVE_FACTORS,
    calc_turnover_stability,
)


class TestCalcTurnoverStability:
    """calc_turnover_stability 函数测试。"""

    def test_constant_turnover_returns_zero(self):
        """常量换手率序列 → 滚动std应为0。"""
        turnover = pd.Series([5.0] * 30)
        result = calc_turnover_stability(turnover, 20)
        # 前19个值为NaN(min_periods=10，但常量序列std=0)
        valid = result.dropna()
        assert len(valid) > 0, "应有有效输出"
        assert (valid.abs() < 1e-10).all(), f"常量序列std应为0, got {valid.values}"

    def test_increasing_turnover_positive_std(self):
        """递增换手率序列 → std>0。"""
        turnover = pd.Series(np.arange(1.0, 31.0))
        result = calc_turnover_stability(turnover, 20)
        valid = result.dropna()
        assert len(valid) > 0, "应有有效输出"
        assert (valid > 0).all(), f"递增序列std应>0, got {valid.values}"

    def test_nan_for_insufficient_window(self):
        """不够min_periods(10)天的窗口 → NaN。"""
        turnover = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = calc_turnover_stability(turnover, 20)
        # 5个数据点 < min_periods=10, 全部应为NaN
        assert result.isna().all(), f"窗口不足时应全为NaN, got {result.values}"

    def test_min_periods_boundary(self):
        """恰好10个数据点(min_periods=10) → 最后一个值应非NaN。"""
        turnover = pd.Series(np.arange(1.0, 11.0))  # 10个点
        result = calc_turnover_stability(turnover, 20)
        # min_periods = max(20//2, 5) = 10, 第10个点刚好够
        assert not np.isnan(result.iloc[-1]), "恰好满足min_periods时应有值"
        assert result.iloc[-1] > 0, "递增序列的std应>0"

    def test_nan_input_propagation(self):
        """输入含NaN时rolling应正确处理。"""
        turnover = pd.Series([1.0] * 15 + [np.nan] + [1.0] * 14)
        result = calc_turnover_stability(turnover, 20)
        # NaN会使部分窗口的有效数据减少
        assert isinstance(result, pd.Series)
        assert len(result) == 30

    def test_output_type_and_length(self):
        """输出类型和长度应与输入一致。"""
        turnover = pd.Series(np.random.RandomState(42).uniform(1, 10, 50))
        result = calc_turnover_stability(turnover, 20)
        assert isinstance(result, pd.Series)
        assert len(result) == len(turnover)


class TestTurnoverStabilityRegistration:
    """因子注册表完整性测试。"""

    def test_registered_in_reserve_factors(self):
        """turnover_stability_20 应在 RESERVE_FACTORS 中注册。"""
        assert "turnover_stability_20" in RESERVE_FACTORS

    def test_direction_is_negative_one(self):
        """方向应为 -1（低波动性 = 稳定 = 好）。"""
        assert "turnover_stability_20" in RESERVE_FACTOR_DIRECTION
        assert RESERVE_FACTOR_DIRECTION["turnover_stability_20"] == -1

    def test_reserve_lambda_callable(self):
        """RESERVE_FACTORS中的lambda应可调用。"""
        assert callable(RESERVE_FACTORS["turnover_stability_20"])


class TestTurnoverStabilityIntegration:
    """集成测试: 用模拟DataFrame验证RESERVE_FACTORS lambda。"""

    def test_reserve_lambda_with_dataframe(self):
        """用模拟数据通过RESERVE_FACTORS lambda计算。"""
        rng = np.random.RandomState(42)
        n_stocks = 3
        n_days = 30
        codes = [f"00000{i}" for i in range(n_stocks)]

        rows = []
        for code in codes:
            for day in range(n_days):
                rows.append({
                    "code": code,
                    "trade_date": f"2025-01-{day + 1:02d}",
                    "turnover_rate": rng.uniform(1, 10),
                })
        df = pd.DataFrame(rows)

        factor_func = RESERVE_FACTORS["turnover_stability_20"]
        result = factor_func(df)

        assert len(result) == n_stocks * n_days
        # 每只股票的前9个值应为NaN(min_periods=10)
        for code in codes:
            code_mask = df["code"] == code
            code_result = result[code_mask]
            assert code_result.iloc[:9].isna().all(), \
                f"Stock {code}: 前9个值应为NaN"
            assert code_result.iloc[-1:].notna().all(), \
                f"Stock {code}: 最后一个值应非NaN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
