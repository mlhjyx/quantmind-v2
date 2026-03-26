"""SimBroker volume-impact slippage integration tests."""

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
    ) -> pd.Series:
        return pd.Series(
            {
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
        )

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
        # 参与率 = 100_000 / (50_000 * 1000) = 0.002
        # impact = 0.05 * sqrt(0.002) * 10000 ≈ 22.4bps, total ≈ 27.4bps
        # slip = 10 * 27.4 / 10000 ≈ 0.0274
        assert 0 < slip < 0.05  # 合理范围

    def test_unit_conversion_total_mv_wan(self) -> None:
        """total_mv为万元(Tushare daily_basic.total_mv)时应自动转为元."""
        config = BacktestConfig(
            slippage_mode="volume_impact",
            slippage_config=SlippageConfig(),
        )
        # total_mv=5_000_000 万元 = 500亿元 → 大盘股(k_large=0.05)
        # 小于1e12阈值, 应×10000
        row = self._make_row(total_mv=5_000_000)
        broker = SimBroker(config)
        slip = broker.calc_slippage(10.0, 100_000, row)
        assert slip > 0  # 基本确认转换后计算正常
