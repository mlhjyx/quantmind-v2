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
        """验证VWAP = amount(元) / (volume(手) × 100)，bias = (close-VWAP)/VWAP。

        Session 26 修 (2026-04-24): 原 test 假设 amount 单位=千元 (×10 换算),
        但 Step 3-A DB 统一存元后 calc_vwap_bias 改为 `amount / (volume*100)`,
        test 未跟上成为 baseline 2 new fail (铁律 40). 本次 amount 从 500 千元
        改 500_000 元 (×1000), 语义等价但单位对齐 post-Step 3-A code.
        """
        # amount=元 (post-Step 3-A), volume=手 (1手=100股)
        # VWAP = 500_000 / (100 × 100) = 50.0 元/股
        close = pd.Series([52.0, 48.0, 50.0])
        amount = pd.Series([500_000.0, 500_000.0, 500_000.0])  # 元
        volume = pd.Series([100.0, 100.0, 100.0])  # 手

        result = calc_vwap_bias(close, amount, volume)

        # VWAP = 50.0 for all
        # bias[0] = (52 - 50) / 50 = 0.04
        # bias[1] = (48 - 50) / 50 = -0.04
        # bias[2] = (50 - 50) / 50 = 0.0
        np.testing.assert_almost_equal(result.iloc[0], 0.04, decimal=4)
        np.testing.assert_almost_equal(result.iloc[1], -0.04, decimal=4)
        np.testing.assert_almost_equal(result.iloc[2], 0.0, decimal=4)

    def test_post_step3a_units(self) -> None:
        """验证 Step 3-A 后单位契约: amount(元) / (volume(手) × 100) = 元/股。

        amount=1_000_000元 (100万元), volume=200手=20000股
        VWAP = 1_000_000 / (200 × 100) = 50 元/股 ✓ (100万元/2万股=50元)

        Session 26 重命名: 原 test_unit_conversion_x10 假设 ×10 换算 (pre-Step 3-A),
        与代码公式不符导致 fail. 重命名 + 单位对齐元.
        """
        close = pd.Series([55.0])
        amount = pd.Series([1_000_000.0])  # 元 = 100万元
        volume = pd.Series([200.0])  # 手 = 20000股

        result = calc_vwap_bias(close, amount, volume)
        # VWAP = 50, bias = (55-50)/50 = 0.10
        np.testing.assert_almost_equal(result.iloc[0], 0.10, decimal=4)

    def test_zero_volume_returns_nan(self) -> None:
        """零成交量时VWAP无意义，应返回NaN。"""
        close = pd.Series([10.0, 20.0, 30.0])
        # amount=元 (post-Step 3-A, reviewer PR #50 LOW 补注释).
        # 本 test 只查 NaN 行为非具体值, 单位无关 PASS.
        amount = pd.Series([100.0, 0.0, 200.0])
        volume = pd.Series([50.0, 0.0, 100.0])

        result = calc_vwap_bias(close, amount, volume)

        assert not np.isnan(result.iloc[0]), "正常成交不应为NaN"
        assert np.isnan(result.iloc[1]), "零成交量应返回NaN"
        assert not np.isnan(result.iloc[2]), "正常成交不应为NaN"

    def test_clip_extreme_values(self) -> None:
        """极端偏差应被 clip 到 [-1.0, 1.0].

        post-Step 3-A: VWAP = 10 / (100 × 100) = 0.001 元/股 (reviewer PR #50 LOW
        注释修正, 原"VWAP=10*10/100=1.0" 沿用 pre-Step 3-A 公式). close=100 → bias
        = (100-0.001)/0.001 ≈ 99998 → clip → 1.0. close=0.001 → bias ≈ 0, clip
        bound check 仍过. 断言仅验 clip 边界 [-1, 1], 故 PASS 与 VWAP 绝对值无关.
        """
        close = pd.Series([100.0, 0.001])
        amount = pd.Series([10.0, 10.0])  # 元
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
        assert abs(last_valid - 1.5) < 0.15, f"RSRS斜率应接近1.5, 实际={last_valid:.4f}"

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
        assert abs(last_valid - 1.0) < 0.01, f"恒定价差时斜率应≈1.0, 实际={last_valid:.4f}"


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
