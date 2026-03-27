"""SimBroker volume-impact slippage integration tests (Bouchaud 2018)."""

import math

import pandas as pd
import pytest
from datetime import date

from engines.backtest_engine import BacktestConfig, SimBroker
from engines.slippage_model import SlippageConfig


class TestSimBrokerVolumeImpact:
    """SimBroker uses volume_impact when slippage_mode='volume_impact'."""

    def _make_row(
        self,
        *,
        open_: float = 10.0,
        close: float = 10.0,
        pre_close: float = 9.8,
        volume: float = 5_000_000,
        amount: float = 50_000,       # 千元(Tushare daily.amount惯例)=5000万元
        total_mv: float = 5_000_000,  # 万元(Tushare daily_basic.total_mv惯例)=500亿元
        turnover_rate: float = 5.0,
        volatility_20: float | None = None,
    ) -> pd.Series:
        data = {
            "open": open_,
            "close": close,
            "pre_close": pre_close,
            "volume": volume,
            "amount": amount,
            "total_mv": total_mv,
            "turnover_rate": turnover_rate,
            "trade_date": date(2024, 1, 2),
            "up_limit": round(pre_close * 1.1, 2),
            "down_limit": round(pre_close * 0.9, 2),
        }
        if volatility_20 is not None:
            data["volatility_20"] = volatility_20
        return pd.Series(data)

    def test_volume_impact_mode_different_from_fixed(self) -> None:
        """volume_impact模式与fixed模式的滑点应不同."""
        config_vi = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
            slippage_bps=10.0,
        )
        config_fixed = BacktestConfig(
            slippage_mode="fixed",
            slippage_bps=10.0,
        )
        row = self._make_row()

        broker_vi = SimBroker(config_vi)
        broker_fixed = SimBroker(config_fixed)

        slip_vi = broker_vi.calc_slippage(10.0, 100_000, row)
        slip_fixed = broker_fixed.calc_slippage(10.0, 100_000, row)

        assert slip_vi != slip_fixed

    def test_fixed_mode_unchanged(self) -> None:
        """fixed模式行为与旧版完全一致."""
        config = BacktestConfig(slippage_mode="fixed", slippage_bps=10.0)
        broker = SimBroker(config)
        row = self._make_row()
        slip = broker.calc_slippage(10.0, 100_000, row)
        assert slip == pytest.approx(10.0 * 10.0 / 10000)

    def test_large_cap_lower_slippage(self) -> None:
        """大盘股冲击低于小盘股."""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # total_mv使用万元单位(Tushare daily_basic惯例)
        # 10_000_000万元 = 1000亿元(大盘), 500_000万元 = 50亿元(小盘)
        row_large = self._make_row(total_mv=10_000_000)
        row_small = self._make_row(total_mv=500_000)

        broker = SimBroker(config)
        slip_large = broker.calc_slippage(10.0, 100_000, row_large)
        slip_small = broker.calc_slippage(10.0, 100_000, row_small)

        assert slip_large < slip_small

    def test_zero_volume_extreme_slippage(self) -> None:
        """零成交量应返回极大滑点."""
        config = BacktestConfig(slippage_mode="volume_impact")
        row = self._make_row(volume=0, amount=0)
        broker = SimBroker(config)
        slip = broker.calc_slippage(10.0, 100_000, row)
        assert slip > 0.01  # 应该很大

    def test_default_config_is_volume_impact(self) -> None:
        """默认BacktestConfig使用volume_impact模式."""
        config = BacktestConfig()
        assert config.slippage_mode == "volume_impact"

    def test_sell_direction_higher_slippage(self) -> None:
        """卖出方向冲击应高于买入(sell_penalty=1.2)."""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        row = self._make_row()
        broker = SimBroker(config)

        slip_buy = broker.calc_slippage(10.0, 100_000, row, direction="buy")
        slip_sell = broker.calc_slippage(10.0, 100_000, row, direction="sell")

        assert slip_sell > slip_buy

    def test_unit_conversion_amount_thousands(self) -> None:
        """amount为千元(Tushare daily.amount)时应自动转为元并正确计算冲击."""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # amount=50_000 千元 = 5000万元, 小于1e9阈值, 应×1000
        row = self._make_row(amount=50_000)
        broker = SimBroker(config)
        slip = broker.calc_slippage(10.0, 100_000, row)
        assert 0 < slip < 0.10  # 合理范围(Y参数更大,滑点可能更高)

    def test_unit_conversion_total_mv_wan(self) -> None:
        """total_mv为万元(Tushare daily_basic.total_mv)时应自动转为元."""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # total_mv=5_000_000 万元 = 500亿元 → 大盘股(Y_large=0.8)
        # 小于1e12阈值, 应×10000
        row = self._make_row(total_mv=5_000_000)
        broker = SimBroker(config)
        slip = broker.calc_slippage(10.0, 100_000, row)
        assert slip > 0  # 基本确认转换后计算正常

    # ── volatility_20 → sigma_daily 集成测试 ──

    def test_with_volatility_20_high_vol_more_slippage(self) -> None:
        """行情数据包含volatility_20时: 高波动率 → 更大滑点。"""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # volatility_20=0.20(20%年化) → sigma_daily=0.20/sqrt(252)≈0.0126
        row_low = self._make_row(volatility_20=0.20)
        # volatility_20=0.60(60%年化) → sigma_daily=0.60/sqrt(252)≈0.0378
        row_high = self._make_row(volatility_20=0.60)

        broker = SimBroker(config)
        slip_low = broker.calc_slippage(10.0, 100_000, row_low)
        slip_high = broker.calc_slippage(10.0, 100_000, row_high)

        assert slip_high > slip_low

    def test_without_volatility_20_uses_default(self) -> None:
        """行情数据无volatility_20时使用默认sigma_daily=0.02。"""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # 不传volatility_20
        row_no_vol = self._make_row()
        # 传入等价于默认的volatility_20=0.02*sqrt(252)
        default_annual = 0.02 * math.sqrt(252)
        row_explicit = self._make_row(volatility_20=default_annual)

        broker = SimBroker(config)
        slip_no_vol = broker.calc_slippage(10.0, 100_000, row_no_vol)
        slip_explicit = broker.calc_slippage(10.0, 100_000, row_explicit)

        assert slip_no_vol == pytest.approx(slip_explicit, rel=1e-6)

    def test_volatility_20_zero_uses_default(self) -> None:
        """volatility_20=0时回退到默认sigma_daily=0.02。"""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        row_zero = self._make_row(volatility_20=0)
        row_default = self._make_row()  # 无volatility_20 → 默认

        broker = SimBroker(config)
        slip_zero = broker.calc_slippage(10.0, 100_000, row_zero)
        slip_default = broker.calc_slippage(10.0, 100_000, row_default)

        assert slip_zero == pytest.approx(slip_default, rel=1e-6)

    def test_volatility_20_negative_uses_default(self) -> None:
        """volatility_20<0时回退到默认sigma_daily=0.02。"""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        row_neg = self._make_row(volatility_20=-0.3)
        row_default = self._make_row()

        broker = SimBroker(config)
        slip_neg = broker.calc_slippage(10.0, 100_000, row_neg)
        slip_default = broker.calc_slippage(10.0, 100_000, row_default)

        assert slip_neg == pytest.approx(slip_default, rel=1e-6)

    def test_sigma_daily_conversion_numerical(self) -> None:
        """volatility_20到sigma_daily转换数值验证。"""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # volatility_20=0.3174(≈50.36%年化) → sigma_daily=0.3174/sqrt(252)=0.02
        vol_20_for_sigma_002 = 0.02 * math.sqrt(252)  # ≈0.3174
        row = self._make_row(volatility_20=vol_20_for_sigma_002)

        broker = SimBroker(config)
        slip = broker.calc_slippage(10.0, 100_000, row)

        # 与默认sigma_daily=0.02应完全一致
        row_default = self._make_row()
        slip_default = broker.calc_slippage(10.0, 100_000, row_default)

        assert slip == pytest.approx(slip_default, rel=1e-6)
