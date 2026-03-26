"""双因素滑点模型单元测试。

测试覆盖:
  - volume_impact_slippage 基本计算
  - 小盘股惩罚 (market_cap < 50亿 → 1.2x)
  - 卖出方向惩罚 (1.2x)
  - 零成交量 → 500bps
  - estimate_execution_price 返回正确价格
  - 边界条件和输入校验

不依赖数据库，纯数学计算测试。
"""

import math
from decimal import Decimal

import pytest

from engines.slippage_model import (
    SlippageConfig,
    SlippageResult,
    estimate_execution_price,
    volume_impact_slippage,
)


# ────────────────────────────────────────────
# volume_impact_slippage 基本计算
# ────────────────────────────────────────────

class TestVolumeImpactSlippage:
    """滑点计算核心函数测试。"""

    def test_basic_calculation(self) -> None:
        """大盘股小额买入：基础5bps + 少量冲击。"""
        slippage = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,  # 1000亿
            direction="buy",
        )
        # 基础5bps + impact = 0.1 * sqrt(100000/500000000) * 10000
        # = 0.1 * sqrt(0.0002) * 10000 = 0.1 * 0.01414 * 10000 = 14.14 bps
        # total = 5 + 14.14 ≈ 19.14
        assert slippage > 5.0  # 至少大于基础滑点
        assert slippage < 50.0  # 不会太离谱

    def test_base_bps_included(self) -> None:
        """基础滑点总是包含在内。"""
        slippage = volume_impact_slippage(
            trade_amount=1,  # 极小交易额 → 冲击≈0
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
            base_bps=5.0,
        )
        # 冲击极小，接近base_bps
        assert abs(slippage - 5.0) < 1.0

    def test_larger_trade_more_slippage(self) -> None:
        """交易金额越大，滑点越高。"""
        s_small = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=100_000_000_000,
            direction="buy",
        )
        s_large = volume_impact_slippage(
            trade_amount=10_000_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=100_000_000_000,
            direction="buy",
        )
        assert s_large > s_small

    def test_custom_base_bps(self) -> None:
        """自定义base_bps参数。"""
        s3 = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
            base_bps=3.0,
        )
        s10 = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
            base_bps=10.0,
        )
        # 差额应等于base_bps的差额(冲击部分相同)
        assert abs((s10 - s3) - 7.0) < 0.01

    def test_custom_impact_coeff(self) -> None:
        """更高的冲击系数→更大滑点。"""
        s_low = volume_impact_slippage(
            trade_amount=1_000_000, daily_volume=10_000_000,
            daily_amount=100_000_000, market_cap=100_000_000_000,
            direction="buy", base_bps=5.0, impact_coeff=0.05,
        )
        s_high = volume_impact_slippage(
            trade_amount=1_000_000, daily_volume=10_000_000,
            daily_amount=100_000_000, market_cap=100_000_000_000,
            direction="buy", base_bps=5.0, impact_coeff=0.2,
        )
        assert s_high > s_low

    def test_zero_trade_amount(self) -> None:
        """零交易金额返回0滑点。"""
        result = volume_impact_slippage(
            trade_amount=0,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result == 0.0

    def test_negative_trade_amount(self) -> None:
        """负交易金额返回0滑点。"""
        result = volume_impact_slippage(
            trade_amount=-100,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result == 0.0

    # ── 小盘股惩罚测试 ──

    def test_small_cap_penalty(self) -> None:
        """小盘股(市值<50亿)冲击成本乘以1.2。"""
        s_large_cap = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=10_000_000_000,  # 100亿，不触发惩罚
            direction="buy",
        )
        s_small_cap = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=3_000_000_000,  # 30亿，触发惩罚
            direction="buy",
        )
        # 小盘股impact部分应为大盘股的1.2倍
        # base_bps相同(5.0), 所以差异在impact部分
        impact_large = s_large_cap - 5.0
        impact_small = s_small_cap - 5.0
        assert abs(impact_small / impact_large - 1.2) < 0.01

    def test_small_cap_boundary_below(self) -> None:
        """市值刚好低于50亿阈值触发惩罚。"""
        s_at_boundary = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=4_999_999_999,  # 刚好低于50亿
            direction="buy",
        )
        s_above = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=5_000_000_000,  # 恰好50亿，不触发
            direction="buy",
        )
        assert s_at_boundary > s_above

    def test_small_cap_boundary_at(self) -> None:
        """市值恰好50亿(5e9)不触发惩罚。"""
        s_at = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=5_000_000_000,
            direction="buy",
        )
        s_above = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=10_000_000_000,
            direction="buy",
        )
        # 两者impact部分应相同(都不触发惩罚)
        assert abs(s_at - s_above) < 0.01

    # ── 卖出方向惩罚测试 ──

    def test_sell_direction_penalty(self) -> None:
        """卖出方向冲击乘以1.2。"""
        s_buy = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=10_000_000,
            daily_amount=100_000_000,
            market_cap=100_000_000_000,  # 大盘股，排除小盘惩罚
            direction="buy",
        )
        s_sell = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=10_000_000,
            daily_amount=100_000_000,
            market_cap=100_000_000_000,  # 大盘股，排除小盘惩罚
            direction="sell",
        )
        # 卖出impact = 买入impact * 1.2
        impact_buy = s_buy - 5.0
        impact_sell = s_sell - 5.0
        assert abs(impact_sell / impact_buy - 1.2) < 0.01

    def test_sell_and_small_cap_compound(self) -> None:
        """卖出 + 小盘股 → 两个惩罚叠加(1.2*1.2=1.44)。"""
        s_buy_large = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        s_sell_small = volume_impact_slippage(
            trade_amount=1_000_000,
            daily_volume=5_000_000,
            daily_amount=50_000_000,
            market_cap=3_000_000_000,
            direction="sell",
        )
        impact_base = s_buy_large - 5.0
        impact_compound = s_sell_small - 5.0
        # 1.2(小盘) * 1.2(卖出) = 1.44
        assert abs(impact_compound / impact_base - 1.44) < 0.01

    # ── 零成交量 → 500bps ──

    def test_zero_daily_volume_returns_500bps(self) -> None:
        """零日成交量返回500bps极大滑点。"""
        result = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=0,
            daily_amount=0,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result == 500.0

    def test_zero_daily_amount_returns_500bps(self) -> None:
        """零日成交额返回500bps。"""
        result = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=1_000_000,
            daily_amount=0,
            market_cap=100_000_000_000,
            direction="sell",
        )
        assert result == 500.0

    def test_negative_daily_volume_returns_500bps(self) -> None:
        """负日成交量返回500bps。"""
        result = volume_impact_slippage(
            trade_amount=100_000,
            daily_volume=-100,
            daily_amount=100_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result == 500.0

    # ── 方向校验 ──

    def test_invalid_direction_raises(self) -> None:
        """非法方向参数应抛ValueError。"""
        with pytest.raises(ValueError, match="direction"):
            volume_impact_slippage(
                trade_amount=100_000,
                daily_volume=50_000_000,
                daily_amount=500_000_000,
                market_cap=100_000_000_000,
                direction="hold",
            )

    def test_direction_case_sensitive(self) -> None:
        """方向必须是小写buy/sell。"""
        with pytest.raises(ValueError):
            volume_impact_slippage(
                trade_amount=100_000,
                daily_volume=50_000_000,
                daily_amount=500_000_000,
                market_cap=100_000_000_000,
                direction="Buy",
            )


# ────────────────────────────────────────────
# estimate_execution_price 测试
# ────────────────────────────────────────────

class TestEstimateExecutionPrice:
    """成交价估计函数测试。"""

    def test_returns_slippage_result(self) -> None:
        """返回类型是SlippageResult。"""
        result = estimate_execution_price(
            signal_price=10.0,
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert isinstance(result, SlippageResult)

    def test_buy_price_higher_than_signal(self) -> None:
        """买入成交价 > 信号价(滑点使买价上移)。"""
        result = estimate_execution_price(
            signal_price=10.0,
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result.execution_price > Decimal("10.0")

    def test_sell_price_lower_than_signal(self) -> None:
        """卖出成交价 < 信号价(滑点使卖价下移)。"""
        result = estimate_execution_price(
            signal_price=10.0,
            trade_amount=100_000,
            daily_volume=50_000_000,
            daily_amount=500_000_000,
            market_cap=100_000_000_000,
            direction="sell",
        )
        assert result.execution_price < Decimal("10.0")

    def test_total_bps_equals_base_plus_impact(self) -> None:
        """total_bps = base_bps + impact_bps。"""
        result = estimate_execution_price(
            signal_price=20.0,
            trade_amount=500_000,
            daily_volume=10_000_000,
            daily_amount=200_000_000,
            market_cap=50_000_000_000,
            direction="buy",
        )
        assert abs(result.total_bps - (result.base_bps + result.impact_bps)) < 0.01

    def test_execution_price_matches_slippage(self) -> None:
        """成交价应与滑点百分比一致。"""
        signal = 20.0
        result = estimate_execution_price(
            signal_price=signal,
            trade_amount=500_000,
            daily_volume=10_000_000,
            daily_amount=200_000_000,
            market_cap=50_000_000_000,
            direction="buy",
        )
        expected_price = Decimal(str(signal)) * (
            1 + Decimal(str(result.total_bps)) / Decimal("10000")
        )
        # 精度到小数点后4位
        assert abs(result.execution_price - expected_price.quantize(Decimal("0.0001"))) < Decimal("0.001")

    def test_slippage_amount_positive(self) -> None:
        """滑点金额应为正值。"""
        result = estimate_execution_price(
            signal_price=15.0,
            trade_amount=200_000,
            daily_volume=20_000_000,
            daily_amount=300_000_000,
            market_cap=80_000_000_000,
            direction="sell",
        )
        assert result.slippage_amount > 0

    def test_zero_volume_extreme_slippage(self) -> None:
        """零成交量: 500bps极大滑点。"""
        result = estimate_execution_price(
            signal_price=10.0,
            trade_amount=100_000,
            daily_volume=0,
            daily_amount=0,
            market_cap=100_000_000_000,
            direction="buy",
        )
        assert result.total_bps == 500.0
        # 买入价应显著高于信号价 (5% slippage)
        assert result.execution_price > Decimal("10.40")

    def test_decimal_precision(self) -> None:
        """结果使用Decimal精确计算, slippage_amount精确到分。"""
        result = estimate_execution_price(
            signal_price=10.55,
            trade_amount=150_000,
            daily_volume=30_000_000,
            daily_amount=300_000_000,
            market_cap=60_000_000_000,
            direction="buy",
        )
        # slippage_amount 应精确到0.01
        assert result.slippage_amount == result.slippage_amount.quantize(Decimal("0.01"))
        # execution_price 应精确到0.0001
        assert result.execution_price == result.execution_price.quantize(Decimal("0.0001"))


# ────────────────────────────────────────────
# SlippageConfig 市值分层配置测试
# ────────────────────────────────────────────


class TestSlippageConfig:
    """SlippageConfig 数据类及 get_k 分层逻辑测试。"""

    def test_defaults(self) -> None:
        """默认参数值正确。"""
        cfg = SlippageConfig()
        assert cfg.k_large == 0.05
        assert cfg.k_mid == 0.10
        assert cfg.k_small == 0.15
        assert cfg.sell_penalty == 1.2
        assert cfg.base_bps == 5.0

    def test_get_k_for_cap_large(self) -> None:
        """大盘股(>=500亿)返回k_large。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=100_000_000_000) == 0.05

    def test_get_k_for_cap_mid(self) -> None:
        """中盘股(100-500亿)返回k_mid。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=30_000_000_000) == 0.10

    def test_get_k_for_cap_small(self) -> None:
        """小盘股(<100亿)返回k_small。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=5_000_000_000) == 0.15

    def test_get_k_zero_cap_fallback(self) -> None:
        """零市值回退到k_small。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=0) == 0.15

    def test_get_k_boundary_500b(self) -> None:
        """500亿边界: >=500亿用k_large, <500亿用k_mid。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=50_000_000_000) == 0.05
        assert cfg.get_k(market_cap=49_999_999_999) == 0.10

    def test_get_k_boundary_100b(self) -> None:
        """100亿边界: >=100亿用k_mid, <100亿用k_small。"""
        cfg = SlippageConfig()
        assert cfg.get_k(market_cap=10_000_000_000) == 0.10
        assert cfg.get_k(market_cap=9_999_999_999) == 0.15


# ────────────────────────────────────────────
# volume_impact_slippage + SlippageConfig 集成测试
# ────────────────────────────────────────────


class TestVolumeImpactWithConfig:
    """传入SlippageConfig时的滑点计算测试。"""

    def test_large_cap_lower_impact(self) -> None:
        """大盘股冲击 < 小盘股冲击(同等交易规模)。"""
        cfg = SlippageConfig()
        large = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=100_000_000_000,
            direction="buy", config=cfg,
        )
        small = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=5_000_000_000,
            direction="buy", config=cfg,
        )
        assert large < small

    def test_backward_compat_without_config(self) -> None:
        """不传config时走旧逻辑, 向后兼容。"""
        result = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=100_000_000_000,
            direction="buy", base_bps=5.0, impact_coeff=0.1,
        )
        assert result > 5.0

    def test_sell_penalty_uses_config(self) -> None:
        """卖出惩罚使用config.sell_penalty。"""
        cfg = SlippageConfig(sell_penalty=1.5)
        buy = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=50_000_000_000,
            direction="buy", config=cfg,
        )
        sell = volume_impact_slippage(
            trade_amount=100_000, daily_volume=50_000_000,
            daily_amount=500_000_000, market_cap=50_000_000_000,
            direction="sell", config=cfg,
        )
        assert sell > buy
