"""PortfolioAggregator — 多策略权重合并为统一执行计划。

将多个策略的目标持仓按资金分配比例合并为统一权重，
交给ExecutionService执行。

设计原则:
- 单策略时为直通(identity)，后续加策略零改动
- 合并后权重归一化到1.0
- 冲突检测: 同一股票多策略方向冲突时告警
"""

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AggregatedPortfolio:
    """聚合后的组合。"""

    target_weights: dict[str, float]  # code -> weight (归一化到1.0)
    strategy_contributions: dict[str, dict[str, float]]  # strategy_id -> {code: weight}
    warnings: list[str] = field(default_factory=list)
    total_strategies: int = 0


class PortfolioAggregator:
    """多策略权重合并器。

    用法:
        aggregator = PortfolioAggregator()
        result = aggregator.merge(
            strategy_weights={"v1.1": {"600519": 0.067, ...}},
            capital_allocation={"v1.1": 1.0},
        )
    """

    def merge(
        self,
        strategy_weights: dict[str, dict[str, float]],
        capital_allocation: dict[str, float],
    ) -> AggregatedPortfolio:
        """多策略权重 x 资金分配 -> 统一执行权重。

        Args:
            strategy_weights: {strategy_id: {code: weight}}
                每个策略的目标持仓权重（各策略内部已归一化到1.0）
            capital_allocation: {strategy_id: ratio}
                各策略的资金分配比例（总和=1.0）

        Returns:
            AggregatedPortfolio: 合并后的统一权重
        """
        warnings: list[str] = []

        # 验证capital_allocation
        alloc_sum = sum(capital_allocation.values())
        if abs(alloc_sum - 1.0) > 0.01:
            warnings.append(
                f"资金分配比例总和={alloc_sum:.3f}，偏离1.0。已自动归一化。"
            )
            if alloc_sum > 0:
                capital_allocation = {
                    k: v / alloc_sum for k, v in capital_allocation.items()
                }

        # 验证策略匹配
        missing = set(strategy_weights) - set(capital_allocation)
        if missing:
            warnings.append(f"策略{missing}无资金分配，将被跳过")

        extra = set(capital_allocation) - set(strategy_weights)
        if extra:
            warnings.append(f"资金分配了{extra}但无策略输出")

        # 合并权重
        merged: dict[str, float] = {}
        contributions: dict[str, dict[str, float]] = {}

        for sid, weights in strategy_weights.items():
            alloc = capital_allocation.get(sid, 0.0)
            if alloc <= 0:
                continue

            contrib: dict[str, float] = {}
            for code, w in weights.items():
                scaled = w * alloc
                merged[code] = merged.get(code, 0.0) + scaled
                contrib[code] = scaled

            contributions[sid] = contrib

        # 冲突检测: 负权重（理论上不会发生，但防御性检查）
        # 必须在过滤极小权重之前检查，否则负权重被 w>1e-6 静默丢弃
        negative = {c: w for c, w in merged.items() if w < 0}
        if negative:
            warnings.append(
                f"发现负权重股票（可能策略冲突）: {negative}"
            )
            merged = {c: w for c, w in merged.items() if w > 0}

        # 过滤极小权重
        merged = {c: w for c, w in merged.items() if w > 1e-6}

        # 归一化
        total = sum(merged.values())
        if total > 0:
            merged = {c: w / total for c, w in merged.items()}

        return AggregatedPortfolio(
            target_weights=merged,
            strategy_contributions=contributions,
            warnings=warnings,
            total_strategies=len(strategy_weights),
        )
