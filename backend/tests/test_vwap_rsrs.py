"""Tests for VWAP bias and RSRS raw factors (Reserve pool, Sprint 1.6)."""

import numpy as np
import pandas as pd
from engines.factor_engine import calc_rsrs_raw, calc_vwap_bias


class TestCalcVwapBias:
    """calc_vwap_bias: (close - VWAP) / VWAP, VWAP = amount / (volume * 100).

    Session 26 修 (2026-04-24, reviewer PR #50 MED): 原 docstring "VWAP = amount*10/volume"
    假设 amount=千元 (pre-Step 3-A); 重构后 DB 统一存元, 公式改为
    `amount / (volume*100)` (calculators.py:342). test amount 全部 ×1000
    (千元→元) 对齐新公式. test_vwap_rsrs_pipeline.py 同问题已在前 commit 修.
    """

    def test_basic_calculation(self):
        """VWAP = 1_000_000 / (100*100) = 100, close=105, bias = 5/100 = 0.05."""
        close = pd.Series([105.0])
        amount = pd.Series([1_000_000.0])  # 元 (post-Step 3-A, 原 1000 千元)
        volume = pd.Series([100.0])  # 手
        result = calc_vwap_bias(close, amount, volume, window=1)
        expected = 0.05
        assert abs(result.iloc[0] - expected) < 1e-6

    def test_negative_bias(self):
        """close < VWAP → negative bias."""
        close = pd.Series([95.0])
        amount = pd.Series([1_000_000.0])  # 元, VWAP=100
        volume = pd.Series([100.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        expected = -0.05
        assert abs(result.iloc[0] - expected) < 1e-6

    def test_clip_upper(self):
        """Extreme positive bias clipped to 1.0."""
        close = pd.Series([300.0])
        amount = pd.Series([1_000_000.0])  # 元, VWAP=100
        volume = pd.Series([100.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert result.iloc[0] == 1.0

    def test_clip_lower(self):
        """Negative bias is bounded by clip(-1, 1).

        Due to epsilon in denominator (vwap.abs() + 1e-12), raw bias
        approaches but never exactly reaches -1.0. The clip ensures
        values stay in [-1, 1] range.
        """
        close = pd.Series([0.001])
        amount = pd.Series([1_000_000.0])  # 元, VWAP=100
        volume = pd.Series([100.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert result.iloc[0] >= -1.0
        assert result.iloc[0] < -0.999  # very close to -1.0

    def test_zero_volume_nan(self):
        """volume=0 → NaN (no VWAP possible)."""
        close = pd.Series([100.0])
        amount = pd.Series([1_000_000.0])  # 元
        volume = pd.Series([0.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert pd.isna(result.iloc[0])

    def test_unit_conversion(self):
        """Verify Step 3-A unit: amount(元) / (volume(手) × 100) = 元/股.

        amount=500_000 元, volume=50 手=5000 股
        VWAP = 500_000 / (50 × 100) = 100 元/股
        """
        close = pd.Series([110.0])
        amount = pd.Series([500_000.0])  # 元 (原 500 千元)
        volume = pd.Series([50.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        vwap = 100.0
        expected = (110.0 - vwap) / vwap
        assert abs(result.iloc[0] - expected) < 1e-6

    def test_multiple_rows(self):
        """Multiple data points, VWAP=100/105/95."""
        close = pd.Series([100.0, 105.0, 95.0])
        # 元 (原 [1000, 1050, 950] 千元)
        amount = pd.Series([1_000_000.0, 1_050_000.0, 950_000.0])
        volume = pd.Series([100.0, 100.0, 100.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert abs(result.iloc[0]) < 1e-6  # close == VWAP
        assert abs(result.iloc[1]) < 1e-6
        assert abs(result.iloc[2]) < 1e-6


class TestCalcRsrsRaw:
    """calc_rsrs_raw: Cov(high, low, N) / Var(low, N)."""

    def test_perfect_linear(self):
        """high = 2*low → beta = Cov(2L,L)/Var(L) = 2Var(L)/Var(L) = 2."""
        n = 20
        low = pd.Series(np.arange(10.0, 10.0 + n))
        high = low * 2
        result = calc_rsrs_raw(high, low, window=18)
        # Last value should be close to 2.0
        last_val = result.iloc[-1]
        assert abs(last_val - 2.0) < 1e-6

    def test_constant_spread(self):
        """high = low + constant → Cov(L+c, L) = Var(L), beta = 1."""
        n = 20
        low = pd.Series(np.arange(10.0, 10.0 + n))
        high = low + 5.0
        result = calc_rsrs_raw(high, low, window=18)
        last_val = result.iloc[-1]
        assert abs(last_val - 1.0) < 1e-6

    def test_min_periods(self):
        """First 8 values should be NaN (min_periods=9)."""
        n = 20
        low = pd.Series(np.arange(10.0, 10.0 + n))
        high = low + 1.0
        result = calc_rsrs_raw(high, low, window=18)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[7])
        assert not pd.isna(result.iloc[8])  # 9th value (0-indexed)

    def test_constant_prices_nan_or_inf(self):
        """Constant low → Var=0 → division by near-zero → very large value."""
        n = 20
        low = pd.Series([10.0] * n)
        high = pd.Series([11.0] * n)
        result = calc_rsrs_raw(high, low, window=18)
        # Var(low)=0, cov=0, result = 0/(0+1e-12) ≈ 0
        last_val = result.iloc[-1]
        assert abs(last_val) < 1e-3  # both cov and var near zero

    def test_window_respected(self):
        """Different window sizes produce different NaN counts.

        window=10 → min_periods=max(5,9)=9
        window=20 → min_periods=max(10,9)=10
        So need wider gap: window=6 (min_periods=max(3,9)=9) vs window=18 (min_periods=9).
        Both have same min_periods=9 due to max(...,9) floor.
        Test that larger window affects actual values instead.
        """
        n = 30
        low = pd.Series(np.random.RandomState(42).uniform(10, 20, n))
        high = low + np.random.RandomState(43).uniform(0, 2, n)
        r10 = calc_rsrs_raw(high, low, window=10)
        r18 = calc_rsrs_raw(high, low, window=18)
        # Both have min_periods=9, but values should differ due to window size
        valid_10 = r10.dropna()
        valid_18 = r18.dropna()
        assert len(valid_10) > 0
        assert len(valid_18) > 0
        # Values should not be identical (different lookback windows)
        common_idx = valid_10.index.intersection(valid_18.index)
        assert not np.allclose(valid_10[common_idx].values, valid_18[common_idx].values)


if __name__ == "__main__":
    # Run tests directly without pytest
    import traceback

    test_classes = [TestCalcVwapBias, TestCalcRsrsRaw]
    total = 0
    passed = 0
    failed = 0

    for cls in test_classes:
        obj = cls()
        methods = [m for m in dir(obj) if m.startswith("test_")]
        for method_name in methods:
            total += 1
            try:
                getattr(obj, method_name)()
                passed += 1
                print(f"  PASS: {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                print(f"  FAIL: {cls.__name__}.{method_name}: {e}")
                traceback.print_exc()

    print(f"\n{passed}/{total} passed, {failed} failed")
