"""SimBroker成本计算+持仓更新测试。"""

from datetime import date

import pandas as pd
from engines.backtest.broker import SimBroker
from engines.backtest.config import BacktestConfig, PMSConfig
from engines.slippage_model import SlippageConfig


def _make_config(**overrides) -> BacktestConfig:
    defaults = dict(
        initial_capital=1_000_000,
        slippage_mode="fixed",
        slippage_bps=0,  # 零滑点简化测试
        slippage_config=SlippageConfig(),
        commission_rate=0.0000854,
        stamp_tax_rate=0.0005,
        historical_stamp_tax=False,
        transfer_fee_rate=0.00001,
        lot_size=100,
        pms=PMSConfig(enabled=False),
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def _make_row(**overrides) -> pd.Series:
    defaults = {
        "code": "600519.SH",
        "trade_date": date(2024, 6, 28),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "pre_close": 100.0,
        "volume": 50000,
        "amount": 500_000_000,  # 5亿元(Step 3-A后DB存元)
        "up_limit": 110.0,
        "down_limit": 90.0,
        "turnover_rate": 5.0,
    }
    defaults.update(overrides)
    return pd.Series(defaults)


class TestCommission:
    def test_commission_min_5yuan(self):
        """佣金最低5元。"""
        config = _make_config()
        broker = SimBroker(config)
        row = _make_row(open=10.0, close=10.0)
        # 买1手(100股)×10元=1000元, 佣金=1000×0.0000854=0.085元 < 5元 → 取5元
        fill = broker.execute_buy("600519.SH", 1100, row)
        assert fill is not None
        assert fill.commission == 5.0

    def test_commission_normal(self):
        """正常佣金(>5元时按比例)。"""
        config = _make_config()
        broker = SimBroker(config)
        row = _make_row(open=1000.0, close=1000.0)
        # 买1手×1000元=100000元, 佣金=100000×0.0000854=8.54元 > 5元
        fill = broker.execute_buy("600519.SH", 110000, row)
        assert fill is not None
        assert fill.commission > 5.0


class TestStampTax:
    def test_sell_has_tax(self):
        """卖出有印花税。"""
        config = _make_config(stamp_tax_rate=0.0005)
        broker = SimBroker(config)
        broker.holdings["600519.SH"] = 100
        row = _make_row(open=100.0, close=100.0)
        fill = broker.execute_sell("600519.SH", 100, row)
        assert fill is not None
        assert fill.tax > 0

    def test_buy_no_tax(self):
        """买入无印花税。"""
        config = _make_config()
        broker = SimBroker(config)
        row = _make_row(open=100.0, close=100.0)
        fill = broker.execute_buy("600519.SH", 11000, row)
        assert fill is not None
        assert fill.tax == 0

    def test_historical_tax_before_2023(self):
        """2023-08-28前印花税0.1%。"""
        config = _make_config(historical_stamp_tax=True)
        broker = SimBroker(config)
        broker.holdings["600519.SH"] = 100
        row = _make_row(trade_date=date(2022, 6, 1), open=100.0, close=100.0)
        fill = broker.execute_sell("600519.SH", 100, row)
        assert fill is not None
        # 100股×100元=10000元, tax=10000×0.001=10元
        assert abs(fill.tax - 10.0) < 0.1

    def test_historical_tax_after_2023(self):
        """2023-08-28后印花税0.05%。"""
        config = _make_config(historical_stamp_tax=True)
        broker = SimBroker(config)
        broker.holdings["600519.SH"] = 100
        row = _make_row(trade_date=date(2024, 6, 1), open=100.0, close=100.0)
        fill = broker.execute_sell("600519.SH", 100, row)
        assert fill is not None
        # 100股×100元=10000元, tax=10000×0.0005=5元
        assert abs(fill.tax - 5.0) < 0.1


class TestLotSize:
    def test_lot_size_floor(self):
        """买入整手(100股floor)。"""
        config = _make_config()
        broker = SimBroker(config)
        row = _make_row(open=100.0, close=100.0)
        # 给15000元, 100元/股, 最多150股 → floor到100股
        fill = broker.execute_buy("600519.SH", 15000, row)
        assert fill is not None
        assert fill.shares % 100 == 0
        assert fill.shares == 100


class TestHoldingsUpdate:
    def test_buy_updates_holdings_and_cash(self):
        """买入后holdings增加, cash减少。"""
        config = _make_config()
        broker = SimBroker(config)
        initial_cash = broker.cash
        row = _make_row(open=100.0, close=100.0)
        fill = broker.execute_buy("600519.SH", 11000, row)
        assert fill is not None
        assert broker.holdings.get("600519.SH", 0) == fill.shares
        assert broker.cash < initial_cash

    def test_sell_updates_holdings_and_cash(self):
        """卖出后holdings减少, cash增加。"""
        config = _make_config()
        broker = SimBroker(config)
        broker.holdings["600519.SH"] = 200
        broker.cash = 500_000
        row = _make_row(open=100.0, close=100.0)
        fill = broker.execute_sell("600519.SH", 200, row)
        assert fill is not None
        assert "600519.SH" not in broker.holdings
        assert broker.cash > 500_000
