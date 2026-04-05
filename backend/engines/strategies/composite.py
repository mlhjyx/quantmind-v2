"""CompositeStrategy — 核心策略 + Modifier链编排器。

R3研究结论(§6.1/§7): 100万资金下推荐"核心+Modifier叠加"架构。
Modifier不独立选股，只调节核心策略的目标权重。

数据流（R3 §7.2）:
  1. core.generate_signals(context) -> base_weights
  2. for modifier in modifiers:
         if modifier.should_trigger(context):
             result = modifier.compute_adjustments(base_weights, context)
             base_weights = modifier.apply_adjustments(base_weights, result)
  3. 归一化(cash_buffer=3%) -> final_weights
  4. (Phase B) PortfolioAggregator合并core + satellites（暂未启用）

调节约束（R3 §6.4）:
- adjustment_factor范围 [0.5, 1.5]（各Modifier自己的clip）
- 单日最大调节量 = 总权重的20%（防Modifier接管）

设计文档对照:
- docs/research/R3_multi_strategy_framework.md §6.2 §7
- backend/engines/modifiers/base.py（ModifierBase接口）
- backend/engines/portfolio_aggregator.py（Phase B卫星策略合并）
"""

import structlog
from dataclasses import dataclass, field

from engines.base_strategy import BaseStrategy, StrategyContext, StrategyDecision
from engines.modifiers.base import ModifierBase
from engines.portfolio_aggregator import AggregatedPortfolio, PortfolioAggregator

logger = structlog.get_logger(__name__)

# R3 §6.4默认约束
_DEFAULT_CASH_BUFFER: float = 0.03
_DEFAULT_MAX_DAILY_ADJUSTMENT: float = 0.20


@dataclass
class CompositeDecision:
    """CompositeStrategy的完整决策输出。

    Attributes:
        final_weights: 最终归一化权重（含cash_buffer）
        core_weights: 核心策略原始权重
        modifier_log: 各Modifier调节记录 [{name, triggered, reasoning}]
        is_rebalance: 核心策略判断的调仓标志
        warnings: 全链路告警
        aggregated_portfolio: Phase B卫星合并结果（暂为None）
    """

    final_weights: dict[str, float]
    core_weights: dict[str, float]
    modifier_log: list[dict]
    is_rebalance: bool
    warnings: list[str] = field(default_factory=list)
    aggregated_portfolio: AggregatedPortfolio | None = None


class CompositeStrategy:
    """多策略编排器（核心策略 + Modifier链）。

    Phase A（100万，当前）: core + modifiers
    Phase B（200万+）:      core + satellites + modifiers（通过PortfolioAggregator）

    用法:
        composite = CompositeStrategy(
            core=EqualWeightStrategy(config, "v1.1"),
            modifiers=[RegimeModifier(regime_config)],
        )
        decision = composite.generate(context)
    """

    def __init__(
        self,
        core: BaseStrategy,
        modifiers: list[ModifierBase] | None = None,
        satellites: list[BaseStrategy] | None = None,
        capital_allocation: dict[str, float] | None = None,
        cash_buffer: float = _DEFAULT_CASH_BUFFER,
        max_daily_adjustment: float = _DEFAULT_MAX_DAILY_ADJUSTMENT,
    ) -> None:
        """初始化CompositeStrategy。

        Args:
            core: 核心策略实例（负责选股和基础权重）
            modifiers: Modifier链列表（按顺序依次应用）
            satellites: 卫星策略列表（Phase B，暂未启用）
            capital_allocation: 卫星策略资金分配（Phase B）
            cash_buffer: 现金缓冲比例（默认3%）
            max_daily_adjustment: 单日最大调节量（相对总权重）
        """
        self.core = core
        self.modifiers: list[ModifierBase] = modifiers or []
        self.satellites: list[BaseStrategy] = satellites or []
        self.capital_allocation = capital_allocation or {}
        self.cash_buffer = cash_buffer
        self.max_daily_adjustment = max_daily_adjustment
        self._aggregator = PortfolioAggregator()

        if satellites:
            logger.warning(
                "[CompositeStrategy] satellites已设置但Phase B未启用。当前仅运行core + modifiers。"
            )

    def generate(self, context: StrategyContext) -> CompositeDecision:
        """完整的多策略信号生成流程。

        Args:
            context: 运行时上下文

        Returns:
            CompositeDecision: 含final_weights和完整调节日志
        """
        warnings: list[str] = []
        modifier_log: list[dict] = []

        # ── Step 1: 核心策略产出基础权重 ──
        core_decision: StrategyDecision = self.core.generate_signals(context)
        base_weights = dict(core_decision.target_weights)
        warnings.extend(core_decision.warnings)

        logger.info(
            f"[CompositeStrategy] 核心策略={self.core.strategy_id}, "
            f"持仓={len(base_weights)}只, "
            f"总权重={sum(base_weights.values()):.3f}"
        )

        # ── Step 2: 依次应用Modifier链 ──
        current_weights = base_weights
        for modifier in self.modifiers:
            try:
                triggered = modifier.should_trigger(context)
                log_entry: dict = {
                    "modifier": modifier.name,
                    "triggered": triggered,
                    "reasoning": "",
                    "warnings": [],
                }

                if triggered:
                    result = modifier.compute_adjustments(current_weights, context)
                    log_entry["reasoning"] = result.reasoning
                    log_entry["warnings"] = result.warnings
                    warnings.extend(result.warnings)

                    current_weights = modifier.apply_adjustments(
                        current_weights,
                        result,
                        max_daily_adjustment=self.max_daily_adjustment,
                    )
                    logger.info(
                        f"[CompositeStrategy] Modifier={modifier.name} 已触发: {result.reasoning}"
                    )
                else:
                    log_entry["reasoning"] = "未触发（条件不满足）"
                    logger.debug(f"[CompositeStrategy] Modifier={modifier.name} 未触发")

                modifier_log.append(log_entry)

            except Exception as exc:
                msg = f"Modifier {modifier.name} 执行失败: {exc}，跳过"
                logger.error(f"[CompositeStrategy] {msg}", exc_info=True)
                warnings.append(msg)
                modifier_log.append(
                    {
                        "modifier": modifier.name,
                        "triggered": False,
                        "reasoning": f"异常跳过: {exc}",
                        "warnings": [msg],
                    }
                )

        # ── Step 3: 归一化（含cash_buffer）──
        final_weights = self._normalize_with_cash_buffer(current_weights)

        logger.info(
            f"[CompositeStrategy] 最终持仓={len(final_weights)}只, "
            f"总权重={sum(final_weights.values()):.3f} "
            f"(cash_buffer={self.cash_buffer:.1%})"
        )

        return CompositeDecision(
            final_weights=final_weights,
            core_weights=base_weights,
            modifier_log=modifier_log,
            is_rebalance=core_decision.is_rebalance,
            warnings=warnings,
            aggregated_portfolio=None,  # Phase B启用时填充
        )

    def _normalize_with_cash_buffer(self, weights: dict[str, float]) -> dict[str, float]:
        """归一化并应用现金缓冲。

        目标: sum(weights) = 1.0 - cash_buffer

        Args:
            weights: 调节后的权重字典

        Returns:
            归一化后的权重（总和 = 1 - cash_buffer）
        """
        if not weights:
            return {}

        total = sum(weights.values())
        if total < 1e-9:
            logger.warning("[CompositeStrategy] 权重总和接近0，返回空持仓")
            return {}

        target_total = 1.0 - self.cash_buffer
        scale = target_total / total
        return {code: w * scale for code, w in weights.items()}

    def add_modifier(self, modifier: ModifierBase) -> None:
        """动态添加Modifier（便于实验性叠加）。

        Args:
            modifier: 要添加的Modifier实例
        """
        self.modifiers.append(modifier)
        logger.info(f"[CompositeStrategy] 添加Modifier: {modifier.name}")

    def remove_modifier(self, name: str) -> bool:
        """按名称移除Modifier。

        Args:
            name: Modifier名称

        Returns:
            True表示找到并移除，False表示未找到
        """
        before = len(self.modifiers)
        self.modifiers = [m for m in self.modifiers if m.name != name]
        removed = len(self.modifiers) < before
        if removed:
            logger.info(f"[CompositeStrategy] 已移除Modifier: {name}")
        return removed

    @property
    def modifier_names(self) -> list[str]:
        """当前Modifier链的名称列表。"""
        return [m.name for m in self.modifiers]
