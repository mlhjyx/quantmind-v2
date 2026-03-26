"""StrategyRegistry — 策略注册表。

集中管理所有策略类型，支持按名称创建策略实例。
预注册: equal_weight, multi_freq。
"""

import logging

from engines.base_strategy import BaseStrategy, StrategyMeta

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """策略注册表。按名称注册/创建策略实例。"""

    _registry: dict[str, type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type[BaseStrategy]) -> None:
        """注册策略类型。

        Args:
            name: 策略名称（如 "equal_weight"）
            strategy_class: BaseStrategy子类
        """
        if not issubclass(strategy_class, BaseStrategy):
            raise TypeError(
                f"{strategy_class.__name__} 不是 BaseStrategy 子类"
            )
        if name in cls._registry:
            logger.warning(f"策略 '{name}' 已注册，将被覆盖")
        cls._registry[name] = strategy_class
        logger.debug(f"注册策略: {name} -> {strategy_class.__name__}")

    @classmethod
    def create(
        cls, name: str, config: dict, strategy_id: str
    ) -> BaseStrategy:
        """按名称创建策略实例。

        Args:
            name: 策略名称
            config: 策略配置dict（对应strategy_configs.config JSONB）
            strategy_id: 策略ID

        Returns:
            BaseStrategy实例

        Raises:
            ValueError: 策略名称未注册
        """
        if name not in cls._registry:
            available = ", ".join(cls._registry.keys()) or "(空)"
            raise ValueError(
                f"策略不存在: '{name}'。可用策略: {available}"
            )
        return cls._registry[name](config=config, strategy_id=strategy_id)

    @classmethod
    def list_available(cls) -> list[str]:
        """列出所有已注册策略名称。"""
        return list(cls._registry.keys())

    @classmethod
    def get_meta(cls, name: str) -> StrategyMeta:
        """获取策略元信息。

        Args:
            name: 策略名称

        Returns:
            StrategyMeta实例

        Raises:
            ValueError: 策略不存在
        """
        if name not in cls._registry:
            raise ValueError(f"策略不存在: '{name}'")
        return cls._registry[name].get_meta()

    @classmethod
    def list_all_meta(cls) -> dict[str, StrategyMeta]:
        """列出所有已注册策略的元信息。"""
        return {name: klass.get_meta() for name, klass in cls._registry.items()}


def _register_builtin_strategies() -> None:
    """注册内置策略。模块导入时自动执行。"""
    from engines.strategies.equal_weight import EqualWeightStrategy
    from engines.strategies.multi_freq import MultiFreqStrategy

    StrategyRegistry.register("equal_weight", EqualWeightStrategy)
    StrategyRegistry.register("multi_freq", MultiFreqStrategy)


_register_builtin_strategies()
