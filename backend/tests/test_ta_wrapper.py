"""TA-Lib wrapper测试。

用numpy构造mock OHLCV数据，不依赖DB。
验证各指标的值域、异常处理、接口完整性。
"""

import numpy as np
import pytest

try:
    import talib  # noqa: F401
    _TALIB_AVAILABLE = True
except ImportError:
    _TALIB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TALIB_AVAILABLE,
    reason="TA-Lib C library not installed",
)


# ---------------------------------------------------------------------------
# 辅助: 构造mock OHLCV价格数据
# ---------------------------------------------------------------------------
def _make_prices(n: int = 200, seed: int = 42) -> dict[str, np.ndarray]:
    """构造mock OHLCV，模拟真实A股价格特征。

    固定seed保证确定性（CLAUDE.md规则3）。
    """
    rng = np.random.RandomState(seed)

    # 从10元起随机游走
    log_returns = rng.normal(0.0005, 0.02, n)
    close = 10.0 * np.exp(np.cumsum(log_returns))

    # open/high/low围绕close生成
    noise = rng.uniform(0.005, 0.02, n)
    high = close * (1 + noise)
    low = close * (1 - noise)
    open_ = close * (1 + rng.normal(0, 0.005, n))

    # 确保 high >= max(open, close) 且 low <= min(open, close)
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    volume = rng.uniform(1e6, 1e8, n)

    return {
        "open": open_.astype(np.float64),
        "high": high.astype(np.float64),
        "low": low.astype(np.float64),
        "close": close.astype(np.float64),
        "volume": volume.astype(np.float64),
    }


# ===========================================================================
# RSI测试
# ===========================================================================
class TestRSI:
    """RSI指标测试。"""

    def test_rsi_range(self):
        """RSI_14在[0,100]范围内（忽略NaN暖机期）。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        rsi = calculate_indicator("RSI", prices, period=14)

        valid = rsi[~np.isnan(rsi)]
        assert len(valid) > 0, "RSI全部为NaN"
        assert valid.min() >= 0.0, f"RSI最小值<0: {valid.min()}"
        assert valid.max() <= 100.0, f"RSI最大值>100: {valid.max()}"

    def test_rsi_default_period(self):
        """不传period时使用默认14。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        rsi_default = calculate_indicator("RSI", prices)
        rsi_14 = calculate_indicator("RSI", prices, period=14)
        np.testing.assert_array_equal(rsi_default, rsi_14)

    def test_rsi_missing_close_raises(self):
        """缺少close数据应抛ValueError。"""
        from wrappers.ta_wrapper import calculate_indicator

        with pytest.raises(ValueError, match="close"):
            calculate_indicator("RSI", {"high": np.array([1.0])})


# ===========================================================================
# MACD测试
# ===========================================================================
class TestMACD:
    """MACD指标测试。"""

    def test_macd_returns_non_empty(self):
        """MACD返回非空array。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        hist = calculate_indicator("MACD", prices)

        assert isinstance(hist, np.ndarray)
        assert len(hist) == len(prices["close"])
        valid = hist[~np.isnan(hist)]
        assert len(valid) > 0, "MACD histogram全部为NaN"

    def test_macd_full_three_columns(self):
        """MACD_FULL返回3列（macd_line, signal, histogram）。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        result = calculate_indicator("MACD_FULL", prices)
        assert result.shape[1] == 3, f"MACD_FULL应返回3列, 实际={result.shape[1]}"


# ===========================================================================
# ATR测试
# ===========================================================================
class TestATR:
    """ATR指标测试。"""

    def test_atr_positive(self):
        """ATR>0（波动率为正）。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        atr = calculate_indicator("ATR", prices, period=14)

        valid = atr[~np.isnan(atr)]
        assert len(valid) > 0, "ATR全部为NaN"
        assert (valid > 0).all(), f"ATR存在非正值: min={valid.min()}"

    def test_atr_missing_high_raises(self):
        """ATR缺少high数据应抛ValueError。"""
        from wrappers.ta_wrapper import calculate_indicator

        with pytest.raises(ValueError, match="high"):
            calculate_indicator("ATR", {"close": np.array([1.0]), "low": np.array([0.9])})


# ===========================================================================
# 未知指标测试
# ===========================================================================
class TestUnknownIndicator:
    """不支持的指标名测试。"""

    def test_unknown_raises_value_error(self):
        """不支持的指标名应抛ValueError。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        with pytest.raises(ValueError, match="未知指标"):
            calculate_indicator("NONEXISTENT_INDICATOR_XYZ", prices)

    def test_case_insensitive(self):
        """指标名大小写不敏感。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        rsi_upper = calculate_indicator("RSI", prices)
        rsi_lower = calculate_indicator("rsi", prices)
        np.testing.assert_array_equal(rsi_upper, rsi_lower)


# ===========================================================================
# list_supported_indicators测试
# ===========================================================================
class TestListIndicators:
    """list_supported_indicators测试。"""

    def test_returns_list(self):
        """返回类型是list。"""
        from wrappers.ta_wrapper import list_supported_indicators

        result = list_supported_indicators()
        assert isinstance(result, list)

    def test_list_non_empty(self):
        """列表非空。"""
        from wrappers.ta_wrapper import list_supported_indicators

        result = list_supported_indicators()
        assert len(result) > 0

    def test_known_indicators_present(self):
        """核心指标(RSI/MACD/ATR)在列表中。"""
        from wrappers.ta_wrapper import list_supported_indicators

        supported = list_supported_indicators()
        for name in ["RSI", "MACD", "ATR", "BBANDS", "ADX"]:
            assert name in supported, f"{name}不在支持列表中"


# ===========================================================================
# 其他指标基本烟雾测试
# ===========================================================================
class TestOtherIndicators:
    """SMA/EMA/BBANDS/ADX/OBV/CCI/WILLR/MFI 烟雾测试。"""

    @pytest.mark.parametrize("name", ["SMA", "EMA"])
    def test_moving_averages(self, name: str):
        """均线类指标返回正确长度。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        result = calculate_indicator(name, prices, period=20)
        assert len(result) == len(prices["close"])
        valid = result[~np.isnan(result)]
        assert len(valid) > 0

    def test_bbands_full(self):
        """BBANDS_FULL返回3列(upper/middle/lower)且upper>=lower。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        result = calculate_indicator("BBANDS_FULL", prices, period=20)
        assert result.shape[1] == 3
        # upper >= lower (跳过NaN行)
        valid_mask = ~np.isnan(result[:, 0])
        upper = result[valid_mask, 0]
        lower = result[valid_mask, 2]
        assert (upper >= lower).all()

    def test_adx(self):
        """ADX在[0,100]范围内。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        adx = calculate_indicator("ADX", prices, period=14)
        valid = adx[~np.isnan(adx)]
        assert len(valid) > 0
        assert valid.min() >= 0
        assert valid.max() <= 100

    def test_obv(self):
        """OBV返回非NaN值。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        obv = calculate_indicator("OBV", prices)
        # OBV第一个值可能NaN，但大部分应有效
        valid = obv[~np.isnan(obv)]
        assert len(valid) > 0

    def test_cci(self):
        """CCI返回有效值。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        cci = calculate_indicator("CCI", prices, period=14)
        valid = cci[~np.isnan(cci)]
        assert len(valid) > 0

    def test_willr_range(self):
        """Williams %R在[-100, 0]范围内。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        willr = calculate_indicator("WILLR", prices, period=14)
        valid = willr[~np.isnan(willr)]
        assert len(valid) > 0
        assert valid.min() >= -100.0
        assert valid.max() <= 0.0

    def test_mfi_range(self):
        """MFI在[0, 100]范围内。"""
        from wrappers.ta_wrapper import calculate_indicator

        prices = _make_prices()
        mfi = calculate_indicator("MFI", prices, period=14)
        valid = mfi[~np.isnan(mfi)]
        assert len(valid) > 0
        assert valid.min() >= 0.0
        assert valid.max() <= 100.0
