"""Unit tests for minute_feature_engine — 10个日频特征纯计算函数。

用合成48-bar数据验证每个特征的数学正确性。
"""

from __future__ import annotations

import numpy as np
import pytest
from engines.minute_feature_engine import (
    _DAILY_KEYS,
    MINUTE_FACTOR_DIRECTION,
    MINUTE_FEATURES,
    _calc_closing_trend_strength,
    _calc_high_freq_volatility,
    _calc_intraday_momentum,
    _calc_opening_volume_share,
    _calc_order_flow_imbalance,
    _calc_smart_money_ratio,
    _calc_volume_autocorr,
    _calc_volume_concentration,
    _calc_volume_price_divergence,
    _calc_vwap_deviation,
    compute_daily_minute_features,
)

# ============================================================
# Fixtures: 合成48-bar数据
# ============================================================

@pytest.fixture
def synthetic_bars():
    """生成一个典型交易日的48个5分钟bar数据。"""
    np.random.seed(42)
    n = 48

    # 模拟A股典型走势: 上午微涨, 下午震荡
    base_price = 10.0
    returns = np.random.normal(0.0002, 0.003, n)
    prices = base_price * np.cumprod(1 + returns)

    o = np.roll(prices, 1)
    o[0] = base_price
    h = np.maximum(prices, o) * (1 + np.abs(np.random.normal(0, 0.001, n)))
    lo = np.minimum(prices, o) * (1 - np.abs(np.random.normal(0, 0.001, n)))
    c = prices

    # 成交量: 开盘和尾盘偏高 (U型分布)
    base_vol = np.full(n, 1000.0)
    base_vol[:6] *= 2.0   # 开盘30分钟量大
    base_vol[-6:] *= 1.5  # 尾盘量大
    v = (base_vol * (1 + np.random.uniform(-0.2, 0.2, n))).astype(np.float64)

    # 成交额 = price * volume * 100 (手→股)
    amt = c * v * 100.0

    # minute_of_day: 0-23 上午, 24-47 下午
    mod = np.arange(n, dtype=np.int8)

    return o, h, lo, c, v, amt, mod


@pytest.fixture
def flat_bars():
    """平盘日: 所有bar价格相同, 量均匀。"""
    n = 48
    price = 10.0
    o = np.full(n, price)
    h = np.full(n, price)
    lo = np.full(n, price)
    c = np.full(n, price)
    v = np.full(n, 1000.0)
    amt = c * v * 100.0
    mod = np.arange(n, dtype=np.int8)
    return o, h, lo, c, v, amt, mod


# ============================================================
# 注册表测试
# ============================================================

class TestRegistry:
    def test_feature_count(self):
        assert len(MINUTE_FEATURES) == 10

    def test_all_have_direction(self):
        for f in MINUTE_FEATURES:
            assert f in MINUTE_FACTOR_DIRECTION, f"{f} missing direction"

    def test_directions_are_valid(self):
        for f, d in MINUTE_FACTOR_DIRECTION.items():
            assert d in (-1, 1), f"{f} has invalid direction {d}"

    def test_daily_keys_match(self):
        assert len(_DAILY_KEYS) == 10
        for k in _DAILY_KEYS:
            assert k + "_20" in MINUTE_FEATURES


# ============================================================
# 完整计算测试
# ============================================================

class TestComputeDaily:
    def test_returns_all_keys(self, synthetic_bars):
        result = compute_daily_minute_features(*synthetic_bars)
        assert set(result.keys()) == set(_DAILY_KEYS)

    def test_all_values_finite(self, synthetic_bars):
        result = compute_daily_minute_features(*synthetic_bars)
        for k, val in result.items():
            assert np.isfinite(val), f"{k} is not finite: {val}"

    def test_insufficient_data_returns_nan(self):
        # 只有5个bar, 不足
        n = 5
        o = np.full(n, 10.0)
        result = compute_daily_minute_features(
            o, o.copy(), o.copy(), o.copy(),
            np.full(n, 100.0), np.full(n, 100000.0),
            np.arange(n, dtype=np.int8),
        )
        for k, val in result.items():
            assert np.isnan(val), f"{k} should be NaN with insufficient data"

    def test_flat_day_reasonable(self, flat_bars):
        result = compute_daily_minute_features(*flat_bars)
        # 平盘日: 波动率应为0或接近0
        assert result["high_freq_volatility"] == pytest.approx(0.0, abs=1e-10)
        # 量均匀: HHI = 1/48 ≈ 0.0208
        assert result["volume_concentration"] == pytest.approx(1.0 / 48, rel=0.01)


# ============================================================
# 各特征独立测试
# ============================================================

class TestHighFreqVolatility:
    def test_zero_for_constant_prices(self):
        ret = np.zeros(47)
        assert _calc_high_freq_volatility(ret) == pytest.approx(0.0)

    def test_positive_for_volatile(self):
        ret = np.array([0.01, -0.01, 0.02, -0.02] * 10 + [0.01] * 7)
        assert _calc_high_freq_volatility(ret) > 0

    def test_nan_for_too_few(self):
        ret = np.array([0.01, 0.02])
        assert np.isnan(_calc_high_freq_volatility(ret))


class TestVolumeConcentration:
    def test_uniform_volume(self):
        v = np.full(48, 100.0)
        hhi = _calc_volume_concentration(v, v.sum())
        # HHI = 48 * (1/48)^2 = 1/48
        assert hhi == pytest.approx(1.0 / 48, rel=0.001)

    def test_concentrated_volume(self):
        v = np.zeros(48)
        v[0] = 10000.0  # 全部集中在1个bar
        hhi = _calc_volume_concentration(v, v.sum())
        assert hhi == pytest.approx(1.0, rel=0.001)

    def test_zero_volume_returns_nan(self):
        assert np.isnan(_calc_volume_concentration(np.zeros(48), 0.0))


class TestVolumeAutocorr:
    def test_perfect_autocorrelation(self):
        v = np.array([100, 200] * 24, dtype=np.float64)
        corr = _calc_volume_autocorr(v)
        # 交替模式 → 负自相关
        assert corr < 0

    def test_constant_volume_nan(self):
        v = np.full(48, 100.0)
        assert np.isnan(_calc_volume_autocorr(v))


class TestSmartMoneyRatio:
    def test_high_when_tail_heavy(self):
        v = np.full(48, 100.0)
        mod = np.arange(48, dtype=np.int8)
        v[mod >= 42] = 500.0  # 尾盘量5x
        ratio = _calc_smart_money_ratio(v, mod)
        assert ratio > 1.0

    def test_low_when_opening_heavy(self):
        v = np.full(48, 100.0)
        mod = np.arange(48, dtype=np.int8)
        v[mod <= 5] = 500.0  # 开盘量5x
        ratio = _calc_smart_money_ratio(v, mod)
        assert ratio < 1.0


class TestOpeningVolumeShare:
    def test_uniform_gives_sixth(self):
        v = np.full(48, 100.0)
        mod = np.arange(48, dtype=np.int8)
        share = _calc_opening_volume_share(v, mod, v.sum())
        # 6/48 = 0.125
        assert share == pytest.approx(0.125, rel=0.001)

    def test_high_opening(self):
        v = np.full(48, 100.0)
        mod = np.arange(48, dtype=np.int8)
        v[mod <= 5] = 1000.0
        share = _calc_opening_volume_share(v, mod, v.sum())
        assert share > 0.5


class TestClosingTrendStrength:
    def test_strong_uptrend_tail(self):
        n = 48
        o = np.full(n, 10.0)
        c = np.full(n, 10.0)
        mod = np.arange(n, dtype=np.int8)
        # 尾盘大涨: mod>=42的bar涨1%
        c[mod >= 42] = 10.1
        o[0] = 10.0
        c[-1] = 10.1
        strength = _calc_closing_trend_strength(c, o, mod)
        assert strength > 0  # 尾盘正趋势

    def test_flat_day(self):
        n = 48
        o = np.full(n, 10.0)
        c = np.full(n, 10.0)
        mod = np.arange(n, dtype=np.int8)
        strength = _calc_closing_trend_strength(c, o, mod)
        assert strength == pytest.approx(0.0, abs=1e-10)


class TestVwapDeviation:
    def test_close_at_vwap(self):
        n = 48
        c = np.full(n, 10.0)
        v = np.full(n, 100.0)
        amt = c * v * 100.0  # VWAP = sum(amt) / sum(v*100) = 10.0
        dev = _calc_vwap_deviation(c, amt, v)
        assert dev == pytest.approx(0.0, abs=1e-10)

    def test_close_above_vwap(self):
        n = 48
        c = np.full(n, 10.0)
        c[-1] = 11.0  # 最后收盘高于均价
        v = np.full(n, 100.0)
        amt = c * v * 100.0
        dev = _calc_vwap_deviation(c, amt, v)
        assert dev > 0  # close > VWAP


class TestOrderFlowImbalance:
    def test_all_up_bars(self):
        n = 48
        c = np.linspace(10.0, 10.5, n)
        o = c - 0.01  # close > open for all bars
        v = np.full(n, 100.0)
        bar_ret = (c - o) / o
        imb = _calc_order_flow_imbalance(c, o, v, bar_ret)
        assert imb > 0.9  # 几乎全买

    def test_all_down_bars(self):
        n = 48
        c = np.linspace(10.0, 9.5, n)
        o = c + 0.01  # close < open for all bars
        v = np.full(n, 100.0)
        bar_ret = (c - o) / o
        imb = _calc_order_flow_imbalance(c, o, v, bar_ret)
        assert imb < -0.9  # 几乎全卖


class TestIntradayMomentum:
    def test_consistent_trend_positive(self):
        n = 48
        # 上午涨, 下午也涨 → 前后差>0
        bar_ret = np.zeros(n)
        bar_ret[:24] = 0.005   # 上午正
        bar_ret[24:] = 0.001   # 下午也正但弱
        mom = _calc_intraday_momentum(bar_ret, n)
        assert mom > 0  # 前>后

    def test_reversal_negative(self):
        n = 48
        # 上午跌, 下午涨 → 前后差<0
        bar_ret = np.zeros(n)
        bar_ret[:24] = -0.005
        bar_ret[24:] = 0.005
        mom = _calc_intraday_momentum(bar_ret, n)
        assert mom < 0  # 前<后


class TestVolumePriceDivergence:
    def test_positive_when_divergent(self):
        # 构造量价背离: |ret|大时vol小, |ret|小时vol大
        np.random.seed(123)
        n = 47
        ret = np.random.normal(0, 0.01, n)
        v = np.full(48, 100.0)
        # 大波动bar给小量, 小波动bar给大量
        sorted_idx = np.argsort(np.abs(ret))
        # v[1:]对应ret, 从大到小赋值→背离
        vol_sorted = np.linspace(200, 50, n)
        v_aligned = np.empty(n)
        v_aligned[sorted_idx] = vol_sorted
        v[1:] = v_aligned

        valid_ret = ret[np.isfinite(ret)]
        div = _calc_volume_price_divergence(v, valid_ret, ret)
        assert div > 0  # 背离为正

    def test_nan_for_insufficient(self):
        ret = np.array([0.01, 0.02, 0.03])
        v = np.full(4, 100.0)
        assert np.isnan(_calc_volume_price_divergence(v, ret, ret))
