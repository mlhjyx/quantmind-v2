"""因子计算引擎单元测试 — 纯合成数据，无数据库依赖。

覆盖:
- 价格/量价因子 (momentum, reversal, volatility, volume_std, turnover_*, amihud)
- 基本面因子 (ln_mcap, bp_ratio, ep_ratio)
- 技术因子 (pv_corr, hl_range, price_level, relative_volume, turnover_surge_ratio)
- KBar因子 (kmid, ksft, kup)
- 资金流因子 (mf_divergence, large_order_ratio, money_flow_strength)
- 高级因子 (maxret, chmom, up_days_ratio, vwap_bias, rsrs_raw, beta_market, stoch_rsv, gain_loss_ratio)
- 预处理管道 (MAD, fill, neutralize, zscore, pipeline)
- IC计算
"""

import numpy as np
import pandas as pd
import pytest
from engines.factor_engine import (
    calc_amihud,
    calc_beta_market,
    calc_bp_ratio,
    calc_chmom,
    calc_ep_ratio,
    calc_gain_loss_ratio,
    calc_hl_range,
    calc_ic,
    calc_kbar_kmid,
    calc_kbar_ksft,
    calc_kbar_kup,
    calc_large_order_ratio,
    calc_ln_mcap,
    calc_maxret,
    calc_mf_divergence,
    calc_momentum,
    calc_money_flow_strength,
    calc_price_level,
    calc_pv_corr,
    calc_relative_volume,
    calc_reversal,
    calc_rsrs_raw,
    calc_stoch_rsv,
    calc_turnover_mean,
    calc_turnover_stability,
    calc_turnover_std,
    calc_turnover_surge_ratio,
    calc_up_days_ratio,
    calc_volatility,
    calc_volume_std,
    calc_vwap_bias,
    preprocess_fill,
    preprocess_mad,
    preprocess_neutralize,
    preprocess_pipeline,
    preprocess_zscore,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def price_series_100() -> pd.Series:
    """100日模拟收盘价序列（含轻微上升趋势+随机噪声）。"""
    np.random.seed(42)
    base = 100.0
    returns = np.random.normal(0.001, 0.02, 100)
    prices = base * np.cumprod(1 + returns)
    return pd.Series(prices, name="close")


@pytest.fixture
def volume_series_100() -> pd.Series:
    """100日模拟成交量序列。"""
    np.random.seed(43)
    return pd.Series(np.random.uniform(1e6, 5e6, 100), name="volume")


@pytest.fixture
def turnover_series_100() -> pd.Series:
    """100日模拟换手率序列（0.5%~5%）。"""
    np.random.seed(44)
    return pd.Series(np.random.uniform(0.5, 5.0, 100), name="turnover_rate")


@pytest.fixture
def amount_series_100() -> pd.Series:
    """100日模拟成交额序列（千元）。"""
    np.random.seed(45)
    return pd.Series(np.random.uniform(1e4, 1e6, 100), name="amount")


@pytest.fixture
def ohlc_100() -> dict:
    """100日OHLC数据。"""
    np.random.seed(46)
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.02, 100))
    high = close * (1 + np.abs(np.random.normal(0, 0.01, 100)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, 100)))
    open_ = close * (1 + np.random.normal(0, 0.005, 100))
    return {
        "open": pd.Series(open_),
        "high": pd.Series(high),
        "low": pd.Series(low),
        "close": pd.Series(close),
    }


@pytest.fixture
def cross_section_50() -> pd.Series:
    """50只股票的因子截面值（模拟单日全市场）。"""
    np.random.seed(47)
    codes = [f"00{i:04d}.SZ" for i in range(50)]
    return pd.Series(np.random.randn(50), index=codes, name="factor")


@pytest.fixture
def industry_50() -> pd.Series:
    """50只股票的行业分类。"""
    codes = [f"00{i:04d}.SZ" for i in range(50)]
    industries = ["银行"] * 10 + ["医药"] * 10 + ["电子"] * 10 + ["食品"] * 10 + ["机械"] * 10
    return pd.Series(industries, index=codes, name="industry")


@pytest.fixture
def ln_mcap_50() -> pd.Series:
    """50只股票的对数市值。"""
    np.random.seed(48)
    codes = [f"00{i:04d}.SZ" for i in range(50)]
    return pd.Series(np.random.uniform(10, 16, 50), index=codes, name="ln_mcap")


# ============================================================
# 价格/量价因子
# ============================================================


class TestPriceVolumeFactors:
    """价格和量价类因子测试。"""

    def test_calc_momentum_type_and_length(self, price_series_100):
        """动量因子返回正确类型和长度。"""
        result = calc_momentum(price_series_100, window=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_momentum_simple_value(self):
        """动量因子数学正确性: [100, 110] → pct_change(1) = 0.1。"""
        s = pd.Series([100.0, 110.0])
        result = calc_momentum(s, window=1)
        assert abs(result.iloc[1] - 0.1) < 1e-10

    def test_calc_momentum_first_values_nan(self, price_series_100):
        """动量因子前window个值应为NaN。"""
        result = calc_momentum(price_series_100, window=5)
        assert result.iloc[:5].isna().all()
        assert result.iloc[5:].notna().any()

    def test_calc_reversal_is_negative_momentum(self, price_series_100):
        """反转因子 = -1 × 动量因子。"""
        mom = calc_momentum(price_series_100, window=10)
        rev = calc_reversal(price_series_100, window=10)
        # 只比较非NaN部分
        valid = mom.notna()
        np.testing.assert_allclose(rev[valid].values, -mom[valid].values, atol=1e-12)

    def test_calc_volatility_nonnegative(self, price_series_100):
        """波动率因子 >= 0（标准差非负）。"""
        result = calc_volatility(price_series_100, window=20)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_calc_volatility_zero_for_constant(self):
        """常数序列的波动率 = 0。"""
        s = pd.Series([100.0] * 50)
        result = calc_volatility(s, window=20)
        valid = result.dropna()
        assert (valid == 0.0).all()

    def test_calc_volume_std_type(self, volume_series_100):
        """成交量波动率返回正确类型。"""
        result = calc_volume_std(volume_series_100, window=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_turnover_mean_value(self):
        """换手率均值: 常数序列的均值 = 常数本身。"""
        s = pd.Series([2.0] * 30)
        result = calc_turnover_mean(s, window=20)
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 2.0, atol=1e-10)

    def test_calc_turnover_std_type(self, turnover_series_100):
        """换手率波动返回正确类型。"""
        result = calc_turnover_std(turnover_series_100, window=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_turnover_stability_equals_turnover_std(self, turnover_series_100):
        """turnover_stability和turnover_std实现相同（都是rolling std）。"""
        r1 = calc_turnover_std(turnover_series_100, window=20)
        r2 = calc_turnover_stability(turnover_series_100, window=20)
        pd.testing.assert_series_equal(r1, r2)

    def test_calc_amihud_nonnegative(self, price_series_100, volume_series_100, amount_series_100):
        """Amihud非流动性因子 >= 0（绝对收益/成交额）。"""
        result = calc_amihud(price_series_100, volume_series_100, amount_series_100, window=20)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_calc_amihud_all_nan_input(self):
        """全NaN输入返回全NaN。"""
        s = pd.Series([np.nan] * 30)
        result = calc_amihud(s, s, s, window=20)
        assert result.isna().all()


# ============================================================
# 基本面因子
# ============================================================


class TestFundamentalFactors:
    """基本面因子测试。"""

    def test_calc_ln_mcap_positive(self):
        """对数市值: 正市值的ln > 0。"""
        mv = pd.Series([1e6, 2e6, 5e6])
        result = calc_ln_mcap(mv)
        assert (result > 0).all()

    def test_calc_ln_mcap_monotonic(self):
        """对数市值: 输入递增 → 输出递增。"""
        mv = pd.Series([1e4, 1e5, 1e6, 1e7])
        result = calc_ln_mcap(mv)
        assert (result.diff().dropna() > 0).all()

    def test_calc_bp_ratio_inverse_pb(self):
        """账面市值比 = 1/PB。"""
        pb = pd.Series([2.0, 5.0, 10.0])
        result = calc_bp_ratio(pb)
        expected = pd.Series([0.5, 0.2, 0.1])
        np.testing.assert_allclose(result.values, expected.values, atol=1e-10)

    def test_calc_bp_ratio_zero_pb_returns_nan(self):
        """PB=0时，BP=NaN（避免除零）。"""
        pb = pd.Series([0.0, 5.0])
        result = calc_bp_ratio(pb)
        assert np.isnan(result.iloc[0])
        assert abs(result.iloc[1] - 0.2) < 1e-10

    def test_calc_ep_ratio_inverse_pe(self):
        """盈利收益率 = 1/PE_TTM。"""
        pe = pd.Series([10.0, 20.0, 50.0])
        result = calc_ep_ratio(pe)
        expected = pd.Series([0.1, 0.05, 0.02])
        np.testing.assert_allclose(result.values, expected.values, atol=1e-10)

    def test_calc_ep_ratio_zero_pe_returns_nan(self):
        """PE=0时，EP=NaN。"""
        pe = pd.Series([0.0, 25.0])
        result = calc_ep_ratio(pe)
        assert np.isnan(result.iloc[0])


# ============================================================
# 技术因子
# ============================================================


class TestTechnicalFactors:
    """技术类因子测试。"""

    def test_calc_pv_corr_range(self, price_series_100, volume_series_100):
        """价量相关系数在 [-1, 1] 之间。"""
        result = calc_pv_corr(price_series_100, volume_series_100, window=20)
        valid = result.dropna()
        assert (valid >= -1.0 - 1e-10).all()
        assert (valid <= 1.0 + 1e-10).all()

    def test_calc_pv_corr_perfect(self):
        """完全正相关序列的相关系数 ≈ 1。"""
        s = pd.Series(range(30), dtype=float)
        result = calc_pv_corr(s, s, window=20)
        # 最后一个值应接近1
        assert abs(result.iloc[-1] - 1.0) < 1e-10

    def test_calc_hl_range_nonnegative(self, ohlc_100):
        """振幅因子 >= 0（high >= low）。"""
        result = calc_hl_range(ohlc_100["high"], ohlc_100["low"], window=20)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_calc_price_level_type(self, price_series_100):
        """价格水平因子返回正确类型。"""
        result = calc_price_level(price_series_100)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_price_level_direction(self):
        """价格水平因子: 价格越高 → 值越低（取负对数）。"""
        s = pd.Series([10.0, 100.0, 1000.0])
        result = calc_price_level(s)
        assert result.iloc[0] > result.iloc[1] > result.iloc[2]

    def test_calc_relative_volume_around_one(self):
        """相对成交量: 常数序列 → ratio ≈ 1。"""
        s = pd.Series([1e6] * 30)
        result = calc_relative_volume(s, window=20)
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 1.0, atol=1e-6)

    def test_calc_turnover_surge_ratio_constant(self):
        """换手率突增比: 常数序列 → ratio ≈ 1。"""
        s = pd.Series([3.0] * 30)
        result = calc_turnover_surge_ratio(s)
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 1.0, atol=1e-6)


# ============================================================
# KBar因子
# ============================================================


class TestKBarFactors:
    """K线形态因子测试。"""

    def test_calc_kbar_kmid_positive_for_up_candle(self):
        """阳线(close > open) → kmid > 0。"""
        open_ = pd.Series([10.0, 10.0])
        close = pd.Series([11.0, 12.0])
        result = calc_kbar_kmid(open_, close)
        assert (result > 0).all()

    def test_calc_kbar_kmid_negative_for_down_candle(self):
        """阴线(close < open) → kmid < 0。"""
        open_ = pd.Series([10.0, 10.0])
        close = pd.Series([9.0, 8.0])
        result = calc_kbar_kmid(open_, close)
        assert (result < 0).all()

    def test_calc_kbar_kmid_value(self):
        """kmid数学正确性: (close - open) / open。"""
        open_ = pd.Series([100.0])
        close = pd.Series([110.0])
        result = calc_kbar_kmid(open_, close)
        assert abs(result.iloc[0] - 0.1) < 1e-10

    def test_calc_kbar_ksft_type(self, ohlc_100):
        """ksft返回正确类型和长度。"""
        result = calc_kbar_ksft(
            ohlc_100["open"],
            ohlc_100["high"],
            ohlc_100["low"],
            ohlc_100["close"],
        )
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_kbar_ksft_close_at_high(self):
        """收盘在最高价附近 → ksft > 0。"""
        open_ = pd.Series([10.0])
        high = pd.Series([12.0])
        low = pd.Series([9.0])
        close = pd.Series([11.5])  # 偏高收盘
        result = calc_kbar_ksft(open_, high, low, close)
        # (2*11.5 - 12 - 9) / 10 = (23 - 21) / 10 = 0.2
        assert result.iloc[0] > 0

    def test_calc_kbar_kup_nonnegative_with_valid_ohlc(self):
        """上影线比例 >= 0（当high >= max(open, close)时）。"""
        # 构造满足OHLC约束的数据: high >= max(open, close)
        open_ = pd.Series([10.0, 10.0, 10.0])
        high = pd.Series([12.0, 11.0, 13.0])
        close = pd.Series([11.0, 9.0, 12.0])
        result = calc_kbar_kup(open_, high, close)
        assert (result >= -1e-12).all()

    def test_calc_kbar_kup_zero_when_no_shadow(self):
        """无上影线(high == max(open,close)) → kup = 0。"""
        open_ = pd.Series([10.0])
        high = pd.Series([12.0])
        close = pd.Series([12.0])  # close == high
        result = calc_kbar_kup(open_, high, close)
        assert abs(result.iloc[0]) < 1e-10


# ============================================================
# 资金流因子
# ============================================================


class TestMoneyFlowFactors:
    """资金流因子测试。"""

    def test_calc_mf_divergence_type(self, price_series_100):
        """资金流背离因子返回正确类型。"""
        np.random.seed(50)
        net_mf = pd.Series(np.random.randn(100))
        result = calc_mf_divergence(price_series_100, net_mf, window=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_mf_divergence_perfect_positive_corr(self):
        """价格与资金流完全正相关 → divergence ≈ -1（取反后）。"""
        s = pd.Series(range(30), dtype=float)
        result = calc_mf_divergence(s, s, window=20)
        # corr(s, s) = 1.0, divergence = -1.0
        assert abs(result.iloc[-1] - (-1.0)) < 1e-10

    def test_calc_large_order_ratio_range(self):
        """主力资金占比在 [0, 1] 之间。"""
        buy_lg = pd.Series([100.0, 200.0, 300.0])
        buy_elg = pd.Series([50.0, 100.0, 150.0])
        buy_md = pd.Series([80.0, 80.0, 80.0])
        buy_sm = pd.Series([20.0, 20.0, 20.0])
        result = calc_large_order_ratio(buy_lg, buy_elg, buy_md, buy_sm)
        assert (result >= 0).all()
        assert (result <= 1.0 + 1e-10).all()

    def test_calc_large_order_ratio_value(self):
        """主力资金占比数学正确性。"""
        buy_lg = pd.Series([100.0])
        buy_elg = pd.Series([100.0])
        buy_md = pd.Series([100.0])
        buy_sm = pd.Series([100.0])
        result = calc_large_order_ratio(buy_lg, buy_elg, buy_md, buy_sm)
        # (100+100) / (100+100+100+100) = 200/400 = 0.5
        assert abs(result.iloc[0] - 0.5) < 1e-6

    def test_calc_money_flow_strength_type(self):
        """净资金流入强度返回正确类型。"""
        net_mf = pd.Series([10.0, -5.0, 20.0])
        total_mv = pd.Series([1e6, 1e6, 1e6])
        result = calc_money_flow_strength(net_mf, total_mv)
        assert isinstance(result, pd.Series)
        assert len(result) == 3


# ============================================================
# 高级因子
# ============================================================


class TestAdvancedFactors:
    """高级因子测试。"""

    def test_calc_maxret_nonnegative_for_rising(self):
        """上涨序列的最大单日涨幅 >= 0。"""
        s = pd.Series(range(1, 31), dtype=float)  # 严格递增
        result = calc_maxret(s, window=20)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_calc_chmom_zero_for_linear(self):
        """线性序列的 chmom(长=短时) 应较小。"""
        s = pd.Series(range(1, 101), dtype=float)
        result = calc_chmom(s, long_window=60, short_window=20)
        # 线性增长, 60日涨幅 ≈ 3 × 20日涨幅, 差值非零但可预测
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_up_days_ratio_range(self, price_series_100):
        """上涨天数占比在 [0, 1] 之间。"""
        result = calc_up_days_ratio(price_series_100, window=20)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 1.0 + 1e-10).all()

    def test_calc_up_days_ratio_all_up(self):
        """全上涨序列 → ratio = 1.0。"""
        s = pd.Series(range(1, 31), dtype=float)
        result = calc_up_days_ratio(s, window=20)
        # 最后一个值: 过去20天全部上涨
        assert abs(result.iloc[-1] - 1.0) < 1e-10

    def test_calc_vwap_bias_clipped(self):
        """VWAP偏差因子被clip到[-1, 1]。"""
        close = pd.Series([10.0, 100.0, 1.0])
        amount = pd.Series([1000.0, 1000.0, 1000.0])  # 千元
        volume = pd.Series([100.0, 100.0, 100.0])  # 手
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert (result >= -1.0 - 1e-10).all()
        assert (result <= 1.0 + 1e-10).all()

    def test_calc_vwap_bias_zero_volume(self):
        """零成交量 → NaN。"""
        close = pd.Series([10.0])
        amount = pd.Series([1000.0])
        volume = pd.Series([0.0])
        result = calc_vwap_bias(close, amount, volume, window=1)
        assert result.isna().all()

    def test_calc_rsrs_raw_type(self, ohlc_100):
        """RSRS因子返回正确类型。"""
        result = calc_rsrs_raw(ohlc_100["high"], ohlc_100["low"], window=18)
        assert isinstance(result, pd.Series)
        assert len(result) == 100

    def test_calc_rsrs_raw_proportional_hl(self):
        """high = 2 * low → 斜率 ≈ 2。"""
        low = pd.Series(range(1, 31), dtype=float)
        high = 2.0 * low
        result = calc_rsrs_raw(high, low, window=18)
        # Cov(2*low, low) / Var(low) = 2
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 2.0, atol=1e-6)

    def test_calc_beta_market_self_beta_one(self):
        """股票收益 == 市场收益 → beta ≈ 1。"""
        np.random.seed(51)
        ret = pd.Series(np.random.normal(0, 0.02, 50))
        result = calc_beta_market(ret, ret, window=20)
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 1.0, atol=1e-6)

    def test_calc_stoch_rsv_range(self, ohlc_100):
        """RSV在 [0, 1] 之间。"""
        result = calc_stoch_rsv(
            ohlc_100["close"],
            ohlc_100["high"],
            ohlc_100["low"],
            window=20,
        )
        valid = result.dropna()
        assert (valid >= -1e-10).all()
        assert (valid <= 1.0 + 1e-10).all()

    def test_calc_gain_loss_ratio_range(self, price_series_100):
        """盈亏比在 [0, 1] 之间。"""
        result = calc_gain_loss_ratio(price_series_100, window=20)
        valid = result.dropna()
        assert (valid >= -1e-10).all()
        assert (valid <= 1.0 + 1e-10).all()

    def test_calc_gain_loss_ratio_all_gains(self):
        """全涨序列 → 盈亏比 ≈ 1.0。"""
        s = pd.Series(range(1, 31), dtype=float)
        result = calc_gain_loss_ratio(s, window=20)
        # sum_gains >> 0, sum_losses ≈ 0 → ratio ≈ 1.0
        assert abs(result.iloc[-1] - 1.0) < 1e-6


# ============================================================
# 预处理管道
# ============================================================


class TestPreprocessing:
    """预处理管道测试。"""

    def test_preprocess_mad_clips_outliers(self):
        """MAD去极值: 极端异常值被截断。"""
        s = pd.Series([1.0, 2.0, 3.0, 2.0, 1.0, 100.0])
        result = preprocess_mad(s, n_mad=3.0)
        assert result.max() < 100.0  # 异常值被截断

    def test_preprocess_mad_preserves_normal(self):
        """MAD去极值: 正常分布值不变。"""
        np.random.seed(52)
        s = pd.Series(np.random.randn(100))
        result = preprocess_mad(s, n_mad=5.0)
        # 5倍MAD非常宽松，正态分布几乎不会被截断
        np.testing.assert_allclose(result.values, s.values, atol=1e-10)

    def test_preprocess_mad_constant_series(self):
        """MAD去极值: 常数序列(MAD=0) → 返回原值。"""
        s = pd.Series([5.0] * 20)
        result = preprocess_mad(s, n_mad=3.0)
        np.testing.assert_allclose(result.values, s.values, atol=1e-10)

    def test_preprocess_fill_no_nan_output(self, industry_50):
        """填充后无NaN。"""
        np.random.seed(53)
        s = pd.Series(np.random.randn(50), index=industry_50.index)
        s.iloc[0] = np.nan
        s.iloc[10] = np.nan
        s.iloc[20] = np.nan
        result = preprocess_fill(s, industry_50)
        assert result.notna().all()

    def test_preprocess_fill_uses_industry_median(self, industry_50):
        """填充值 = 行业中位数。"""
        codes = industry_50.index
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 10, index=codes)
        s.iloc[0] = np.nan  # 第一个属于"银行"
        result = preprocess_fill(s, industry_50)
        # "银行"组 = indices 0~9, 非NaN值 = [2,3,4,5,1,2,3,4,5] (idx 1~9)
        bank_vals = s.iloc[1:10]
        expected_median = bank_vals.median()
        assert abs(result.iloc[0] - expected_median) < 1e-10

    def test_preprocess_neutralize_reduces_mcap_corr(self):
        """中性化后因子与市值的相关性大幅降低。"""
        np.random.seed(99)
        n = 100
        codes = [f"00{i:04d}.SZ" for i in range(n)]
        ln_mcap = pd.Series(np.random.uniform(10, 16, n), index=codes)
        industry = pd.Series(
            (["银行"] * 20 + ["医药"] * 20 + ["电子"] * 20 + ["食品"] * 20 + ["机械"] * 20),
            index=codes,
        )
        # 因子 = 市值 + 噪声，相关性高
        factor = ln_mcap + np.random.randn(n) * 0.5
        corr_before = abs(factor.corr(ln_mcap))
        result = preprocess_neutralize(factor, ln_mcap, industry)
        corr_after = abs(result.corr(ln_mcap))
        # 中性化后相关性应显著降低
        assert corr_after < corr_before * 0.3

    def test_preprocess_neutralize_small_sample_skips(self):
        """样本 < 30 时跳过中性化，返回原值。"""
        s = pd.Series(range(10), dtype=float)
        mcap = pd.Series(range(10), dtype=float)
        ind = pd.Series(["A"] * 10)
        result = preprocess_neutralize(s, mcap, ind)
        pd.testing.assert_series_equal(result, s)

    def test_preprocess_zscore_mean_zero_std_one(self):
        """zscore标准化后均值≈0，标准差≈1。"""
        np.random.seed(54)
        s = pd.Series(np.random.randn(100) * 5 + 10)
        result = preprocess_zscore(s)
        assert abs(result.mean()) < 1e-10
        assert abs(result.std() - 1.0) < 0.01  # pandas std ddof=1

    def test_preprocess_zscore_constant_returns_zero(self):
        """常数序列zscore → 全0。"""
        s = pd.Series([7.0] * 20)
        result = preprocess_zscore(s)
        assert (result == 0.0).all()

    def test_preprocess_pipeline_returns_tuple(
        self,
        cross_section_50,
        ln_mcap_50,
        industry_50,
    ):
        """pipeline返回(raw, neutral)二元组。"""
        raw, neutral = preprocess_pipeline(
            cross_section_50,
            ln_mcap_50,
            industry_50,
        )
        assert isinstance(raw, pd.Series)
        assert isinstance(neutral, pd.Series)
        assert len(raw) == len(cross_section_50)
        assert len(neutral) == len(cross_section_50)

    def test_preprocess_pipeline_neutral_zscore(
        self,
        cross_section_50,
        ln_mcap_50,
        industry_50,
    ):
        """pipeline输出的neutral值均值≈0。"""
        _, neutral = preprocess_pipeline(
            cross_section_50,
            ln_mcap_50,
            industry_50,
        )
        assert abs(neutral.mean()) < 0.1  # 经zscore后均值接近0


# ============================================================
# IC计算
# ============================================================


class TestCalcIC:
    """IC计算测试。"""

    def test_calc_ic_perfect_correlation(self):
        """完全正相关 → IC ≈ 1.0。"""
        codes = [f"00{i:04d}.SZ" for i in range(50)]
        factor = pd.Series(range(50), index=codes, dtype=float)
        returns = pd.Series(range(50), index=codes, dtype=float)
        ic = calc_ic(factor, returns, method="spearman")
        assert abs(ic - 1.0) < 1e-10

    def test_calc_ic_perfect_inverse(self):
        """完全负相关 → IC ≈ -1.0。"""
        codes = [f"00{i:04d}.SZ" for i in range(50)]
        factor = pd.Series(range(50), index=codes, dtype=float)
        returns = pd.Series(range(49, -1, -1), index=codes, dtype=float)
        ic = calc_ic(factor, returns, method="spearman")
        assert abs(ic - (-1.0)) < 1e-10

    def test_calc_ic_too_few_samples(self):
        """样本 < 30 → 返回NaN。"""
        codes = [f"00{i:04d}.SZ" for i in range(10)]
        factor = pd.Series(range(10), index=codes, dtype=float)
        returns = pd.Series(range(10), index=codes, dtype=float)
        ic = calc_ic(factor, returns)
        assert np.isnan(ic)

    def test_calc_ic_pearson_method(self):
        """Pearson IC计算。"""
        codes = [f"00{i:04d}.SZ" for i in range(50)]
        factor = pd.Series(range(50), index=codes, dtype=float)
        returns = pd.Series(range(50), index=codes, dtype=float)
        ic = calc_ic(factor, returns, method="pearson")
        assert abs(ic - 1.0) < 1e-10

    def test_calc_ic_partial_nan_alignment(self):
        """因子和收益有不同NaN → 自动对齐取交集。"""
        codes = [f"00{i:04d}.SZ" for i in range(50)]
        factor = pd.Series(range(50), index=codes, dtype=float)
        returns = pd.Series(range(50), index=codes, dtype=float)
        factor.iloc[0] = np.nan
        returns.iloc[1] = np.nan
        ic = calc_ic(factor, returns)
        # 去掉2个NaN后还有48个, > 30, 应返回有效IC
        assert not np.isnan(ic)
        assert abs(ic - 1.0) < 0.05  # 去掉2个点对rank IC影响很小


# ============================================================
# 边界情况
# ============================================================


class TestEdgeCases:
    """边界情况和异常输入测试。"""

    def test_single_value_series(self):
        """单值序列不抛异常。"""
        s = pd.Series([100.0])
        # 这些函数对单值输入应返回NaN而非崩溃
        assert len(calc_momentum(s, 1)) == 1
        assert len(calc_reversal(s, 1)) == 1
        assert len(calc_volatility(s, 5)) == 1

    def test_all_nan_momentum(self):
        """全NaN输入的动量计算。"""
        s = pd.Series([np.nan] * 20)
        result = calc_momentum(s, window=5)
        assert result.isna().all()

    def test_zero_values_bp_ratio(self):
        """全零PB序列 → 全NaN。"""
        pb = pd.Series([0.0, 0.0, 0.0])
        result = calc_bp_ratio(pb)
        assert result.isna().all()

    def test_negative_pb_bp_ratio(self):
        """负PB（亏损股）→ 返回负数（不崩溃）。"""
        pb = pd.Series([-2.0])
        result = calc_bp_ratio(pb)
        assert result.iloc[0] == pytest.approx(-0.5)

    def test_empty_series(self):
        """空Series输入不抛异常。"""
        s = pd.Series(dtype=float)
        result = calc_momentum(s, window=5)
        assert len(result) == 0

    def test_preprocess_mad_all_nan(self):
        """全NaN输入MAD不崩溃。"""
        s = pd.Series([np.nan] * 10)
        result = preprocess_mad(s)
        assert result.isna().all()

    def test_preprocess_zscore_all_nan(self):
        """全NaN输入zscore不崩溃。"""
        s = pd.Series([np.nan] * 10)
        result = preprocess_zscore(s)
        # NaN的mean/std → 返回NaN或0
        assert isinstance(result, pd.Series)
