"""VWAP偏差和RSRS因子管道测试。

测试内容:
1. VWAP基本计算正确性（含×10单位换算验证）
2. VWAP零成交量返回NaN
3. RSRS基本计算正确性
4. RSRS窗口不足返回NaN
5. 因子注册到RESERVE_FACTORS字典
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.factor_engine import (
    RESERVE_FACTOR_DIRECTION,
    RESERVE_FACTORS,
    calc_rsrs_raw,
    calc_vwap_bias,
)


class TestVwapBias:
    """VWAP偏差因子测试。"""

    def test_basic_calculation(self) -> None:
        """验证VWAP = amount×10/volume，bias = (close-VWAP)/VWAP。"""
        # amount=千元, volume=手
        # VWAP = 500 * 10 / 100 = 50.0 元/股
        close = pd.Series([52.0, 48.0, 50.0])
        amount = pd.Series([500.0, 500.0, 500.0])  # 千元
        volume = pd.Series([100.0, 100.0, 100.0])   # 手

        result = calc_vwap_bias(close, amount, volume)

        # VWAP = 50.0 for all
        # bias[0] = (52 - 50) / 50 = 0.04
        # bias[1] = (48 - 50) / 50 = -0.04
        # bias[2] = (50 - 50) / 50 = 0.0
        np.testing.assert_almost_equal(result.iloc[0], 0.04, decimal=4)
        np.testing.assert_almost_equal(result.iloc[1], -0.04, decimal=4)
        np.testing.assert_almost_equal(result.iloc[2], 0.0, decimal=4)

    def test_unit_conversion_x10(self) -> None:
        """验证单位换算: 千元×10/手 = 元/股。

        amount=1000千元=100万元, volume=200手=20000股
        VWAP = 1000*10/200 = 50 元/股 ✓ (100万元/2万股=50元)
        """
        close = pd.Series([55.0])
        amount = pd.Series([1000.0])  # 千元 = 100万元
        volume = pd.Series([200.0])   # 手 = 20000股

        result = calc_vwap_bias(close, amount, volume)
        # VWAP = 50, bias = (55-50)/50 = 0.10
        np.testing.assert_almost_equal(result.iloc[0], 0.10, decimal=4)

    def test_zero_volume_returns_nan(self) -> None:
        """零成交量时VWAP无意义，应返回NaN。"""
        close = pd.Series([10.0, 20.0, 30.0])
        amount = pd.Series([100.0, 0.0, 200.0])
        volume = pd.Series([50.0, 0.0, 100.0])

        result = calc_vwap_bias(close, amount, volume)

        assert not np.isnan(result.iloc[0]), "正常成交不应为NaN"
        assert np.isnan(result.iloc[1]), "零成交量应返回NaN"
        assert not np.isnan(result.iloc[2]), "正常成交不应为NaN"

    def test_clip_extreme_values(self) -> None:
        """极端偏差应被clip到[-1.0, 1.0]。"""
        # VWAP = 10*10/100 = 1.0, close=100 → bias=(100-1)/1=99 → clip→1.0
        close = pd.Series([100.0, 0.001])
        amount = pd.Series([10.0, 10.0])
        volume = pd.Series([100.0, 100.0])

        result = calc_vwap_bias(close, amount, volume)

        assert result.iloc[0] <= 1.0, "上界clip失败"
        assert result.iloc[1] >= -1.0, "下界clip失败"


class TestRsrsRaw:
    """RSRS阻力支撑因子测试。"""

    def test_basic_calculation(self) -> None:
        """验证RSRS = Cov(high,low)/Var(low) = OLS斜率。"""
        np.random.seed(42)
        n = 30
        low = pd.Series(np.random.randn(n).cumsum() + 50)
        # high = 1.5 * low + noise → 斜率应接近1.5
        high = 1.5 * low + np.random.randn(n) * 0.1

        result = calc_rsrs_raw(high, low, window=18)

        # 最后一个值（足够窗口后）应接近1.5
        last_valid = result.dropna().iloc[-1]
        assert abs(last_valid - 1.5) < 0.15, (
            f"RSRS斜率应接近1.5, 实际={last_valid:.4f}"
        )

    def test_window_insufficient_returns_nan(self) -> None:
        """窗口不足min_periods=9时应返回NaN。"""
        high = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
        low = pd.Series([9.0, 10.0, 11.0, 12.0, 13.0])

        result = calc_rsrs_raw(high, low, window=18)

        # 只有5个数据点，min_periods=9，全部应为NaN
        assert result.isna().all(), "窗口不足时应全部为NaN"

    def test_exact_min_periods(self) -> None:
        """刚好达到min_periods=9时应有值。"""
        np.random.seed(42)
        n = 9
        low = pd.Series(np.arange(n, dtype=float) + 50)
        high = low + 2.0

        result = calc_rsrs_raw(high, low, window=18)

        # 第9个点(index=8)应该有值
        assert not np.isnan(result.iloc[-1]), "min_periods=9时应有值"

    def test_constant_spread(self) -> None:
        """high = low + 常数时，斜率应接近1.0。"""
        n = 30
        low = pd.Series(np.arange(n, dtype=float) + 50)
        high = low + 5.0  # 恒定价差

        result = calc_rsrs_raw(high, low, window=18)

        last_valid = result.dropna().iloc[-1]
        assert abs(last_valid - 1.0) < 0.01, (
            f"恒定价差时斜率应≈1.0, 实际={last_valid:.4f}"
        )


class TestReserveRegistration:
    """验证因子正确注册到Reserve注册表。"""

    def test_vwap_in_reserve(self) -> None:
        """vwap_bias_1d应在RESERVE_FACTORS中。"""
        assert "vwap_bias_1d" in RESERVE_FACTORS

    def test_rsrs_in_reserve(self) -> None:
        """rsrs_raw_18应在RESERVE_FACTORS中。"""
        assert "rsrs_raw_18" in RESERVE_FACTORS

    def test_directions_defined(self) -> None:
        """Reserve因子方向映射应已定义。"""
        assert RESERVE_FACTOR_DIRECTION["vwap_bias_1d"] == -1
        assert RESERVE_FACTOR_DIRECTION["rsrs_raw_18"] == -1

    def test_reserve_factors_callable(self) -> None:
        """RESERVE_FACTORS中的lambda应可调用。"""
        for name, fn in RESERVE_FACTORS.items():
            assert callable(fn), f"{name} 不可调用"
