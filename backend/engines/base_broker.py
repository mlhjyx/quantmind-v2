"""BaseBroker抽象基类 — 统一Broker接口。

CLAUDE.md 设计: 执行层Broker策略模式。
Paper/实盘/外汇共用同一套因子→信号→风控链路，
唯一区别是执行层。用策略模式切换。

所有Broker实现必须继承BaseBroker并实现统一查询接口，
使上层（风控、归因、监控）可以无差别地查询任何Broker的状态。
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseBroker(ABC):
    """Broker抽象基类。

    定义所有Broker必须实现的统一查询接口。
    上层代码（风控、归因、调度）通过这些方法获取Broker状态，
    不依赖具体Broker实现的内部细节。
    """

    @abstractmethod
    def get_positions(self) -> dict[str, int]:
        """获取当前持仓。

        Returns:
            {code: shares} 映射。无持仓返回空dict。
        """

    @abstractmethod
    def get_cash(self) -> float:
        """获取当前可用现金。

        Returns:
            可用现金金额。
        """

    @abstractmethod
    def get_total_value(self, prices: dict[str, float]) -> float:
        """计算组合总市值（持仓市值 + 现金）。

        Args:
            prices: {code: price} 最新价格映射。

        Returns:
            组合总市值。
        """


def get_broker(mode: str, **kwargs) -> BaseBroker:
    """Broker工厂函数。

    Args:
        mode: 执行模式 "backtest" / "paper" / "live"。
        **kwargs: 传递给具体Broker构造函数的参数。

    Returns:
        对应模式的BaseBroker实例。

    Raises:
        ValueError: 无效的mode。
    """
    if mode == "backtest":
        from engines.backtest_engine import BacktestConfig, SimBroker

        config = kwargs.get("config") or BacktestConfig()
        return SimBroker(config)
    elif mode == "paper":
        from engines.paper_broker import PaperBroker

        strategy_id = kwargs.get("strategy_id", "")
        initial_capital = kwargs.get("initial_capital", 1_000_000.0)
        return PaperBroker(strategy_id=strategy_id, initial_capital=initial_capital)
    elif mode == "live":
        from engines.broker_qmt import MiniQMTBroker

        qmt_path = kwargs.get("qmt_path", "")
        account_id = kwargs.get("account_id", "")
        return MiniQMTBroker(qmt_path=qmt_path, account_id=account_id)
    else:
        raise ValueError(
            f"无效的执行模式: {mode!r}，支持: 'backtest', 'paper', 'live'"
        )
