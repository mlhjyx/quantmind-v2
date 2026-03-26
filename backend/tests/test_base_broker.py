"""BaseBroker ABC + 工厂函数测试。

验证:
1. BaseBroker不可直接实例化
2. SimBroker/PaperBroker/MiniQMTBroker都是BaseBroker子类
3. 工厂函数get_broker正确创建实例
4. 无效mode报ValueError
5. SimBroker的BaseBroker接口正确工作
"""

from engines.backtest_engine import BacktestConfig, SimBroker
from engines.base_broker import BaseBroker, get_broker
from engines.paper_broker import PaperBroker


class TestBaseBrokerABC:
    """BaseBroker抽象基类测试。"""

    def test_cannot_instantiate(self) -> None:
        """BaseBroker不可直接实例化。"""
        try:
            BaseBroker()  # type: ignore[abstract]
            raise AssertionError("应该抛出TypeError")
        except TypeError as e:
            assert "abstract" in str(e).lower() or "instantiate" in str(e).lower()

    def test_simbroker_is_base_broker(self) -> None:
        """SimBroker是BaseBroker子类。"""
        config = BacktestConfig()
        broker = SimBroker(config)
        assert isinstance(broker, BaseBroker)

    def test_paper_broker_is_base_broker(self) -> None:
        """PaperBroker是BaseBroker子类。"""
        broker = PaperBroker(strategy_id="test", initial_capital=1_000_000)
        assert isinstance(broker, BaseBroker)

    def test_mini_qmt_broker_is_base_broker(self) -> None:
        """MiniQMTBroker是BaseBroker子类。"""
        from engines.broker_qmt import MiniQMTBroker
        broker = MiniQMTBroker(qmt_path="fake_path", account_id="12345")
        assert isinstance(broker, BaseBroker)


class TestSimBrokerInterface:
    """SimBroker的BaseBroker接口测试。"""

    def test_get_positions_empty(self) -> None:
        """空持仓返回空dict。"""
        broker = SimBroker(BacktestConfig())
        assert broker.get_positions() == {}

    def test_get_positions_with_holdings(self) -> None:
        """有持仓时返回holdings副本。"""
        broker = SimBroker(BacktestConfig())
        broker.holdings = {"000001.SZ": 1000, "600519.SH": 500}
        positions = broker.get_positions()
        assert positions == {"000001.SZ": 1000, "600519.SH": 500}
        # 验证是副本不是引用
        positions["999999.SZ"] = 100
        assert "999999.SZ" not in broker.holdings

    def test_get_cash(self) -> None:
        """get_cash返回当前现金。"""
        broker = SimBroker(BacktestConfig(initial_capital=500_000))
        assert broker.get_cash() == 500_000.0
        broker.cash = 123456.78
        assert broker.get_cash() == 123456.78

    def test_get_total_value(self) -> None:
        """get_total_value = 持仓市值 + 现金。"""
        broker = SimBroker(BacktestConfig(initial_capital=100_000))
        broker.holdings = {"000001.SZ": 1000}
        broker.cash = 50_000.0

        prices = {"000001.SZ": 10.0}
        total = broker.get_total_value(prices)
        # 1000 * 10 + 50000 = 60000
        assert total == 60_000.0

    def test_get_total_value_consistent_with_portfolio_value(self) -> None:
        """get_total_value和get_portfolio_value返回相同结果。"""
        broker = SimBroker(BacktestConfig())
        broker.holdings = {"000001.SZ": 500, "600519.SH": 100}
        broker.cash = 200_000.0
        prices = {"000001.SZ": 15.0, "600519.SH": 1800.0}

        assert broker.get_total_value(prices) == broker.get_portfolio_value(prices)


class TestPaperBrokerInterface:
    """PaperBroker的BaseBroker接口测试。"""

    def test_get_positions_before_load(self) -> None:
        """load_state前返回空dict。"""
        broker = PaperBroker(strategy_id="test")
        assert broker.get_positions() == {}

    def test_get_cash_before_load(self) -> None:
        """load_state前返回初始资金。"""
        broker = PaperBroker(strategy_id="test", initial_capital=500_000)
        assert broker.get_cash() == 500_000.0

    def test_get_total_value_before_load(self) -> None:
        """load_state前返回初始资金。"""
        broker = PaperBroker(strategy_id="test", initial_capital=500_000)
        assert broker.get_total_value({}) == 500_000.0


class TestGetBrokerFactory:
    """工厂函数测试。"""

    def test_backtest_mode(self) -> None:
        """backtest模式返回SimBroker。"""
        broker = get_broker("backtest")
        assert isinstance(broker, SimBroker)
        assert isinstance(broker, BaseBroker)

    def test_backtest_with_config(self) -> None:
        """backtest模式接受自定义config。"""
        config = BacktestConfig(initial_capital=500_000, top_n=10)
        broker = get_broker("backtest", config=config)
        assert isinstance(broker, SimBroker)
        assert broker.cash == 500_000.0

    def test_paper_mode(self) -> None:
        """paper模式返回PaperBroker。"""
        broker = get_broker("paper", strategy_id="test_strat")
        assert isinstance(broker, PaperBroker)
        assert isinstance(broker, BaseBroker)

    def test_live_mode(self) -> None:
        """live模式返回MiniQMTBroker。"""
        from engines.broker_qmt import MiniQMTBroker
        broker = get_broker("live", qmt_path="fake", account_id="123")
        assert isinstance(broker, MiniQMTBroker)
        assert isinstance(broker, BaseBroker)

    def test_invalid_mode(self) -> None:
        """无效mode报ValueError。"""
        try:
            get_broker("invalid_mode")
            raise AssertionError("应该抛出ValueError")
        except ValueError as e:
            assert "invalid_mode" in str(e)
            assert "backtest" in str(e)
