"""ModifierBase — 权重/仓位调节器抽象基类。

R3研究结论(§7.2): Modifier不独立选股，只产出调节因子。
与BaseStrategy的关键区别:
- 输入是core策略的target_weights
- 输出是adjustment_factors {code: factor}
- factor=1.0不调节, >1升权, <1降权, =0清仓

设计约束(R3 §6.4):
- adjustment_factor范围 [0.5, 1.5]（可配置）
- 调节后权重必须归一化
- 单日最大调节量 = 总权重的20%（防Modifier接管）

设计文档对照:
- docs/research/R3_multi_strategy_framework.md §7.2
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from engines.base_strategy import StrategyContext

logger = logging.getLogger(__name__)

# R3 §6.4 默认调节约束
DEFAULT_ADJUSTMENT_CLIP_LOW: float = 0.5
DEFAULT_ADJUSTMENT_CLIP_HIGH: float = 1.5
DEFAULT_MAX_DAILY_ADJUSTMENT: float = 0.20


@dataclass
class ModifierResult:
    """Modifier调节结果。

    Attributes:
        adjustment_factors: {code: factor}，factor=1.0不调节
        triggered: 是否实际触发了调节
        reasoning: 调节原因说明
        warnings: 告警列表
    """

    adjustment_factors: dict[str, float]
    triggered: bool
    reasoning: str
    warnings: list[str] = field(default_factory=list)


class ModifierBase(ABC):
    """权重/仓位调节器基类。

    子类必须实现:
    - compute_adjustments: 计算调节因子
    - should_trigger: 判断是否触发调节

    可选覆盖:
    - validate_adjustments: 调节因子合法性验证

    属性:
        name: 调节器唯一名称（用于日志/审计）
        config: 配置字典
        clip_range: 调节系数裁剪范围 (low, high)
    """

    def __init__(
        self,
        name: str,
        config: dict,
        clip_range: tuple[float, float] = (
            DEFAULT_ADJUSTMENT_CLIP_LOW,
            DEFAULT_ADJUSTMENT_CLIP_HIGH,
        ),
    ) -> None:
        self.name = name
        self.config = config
        self.clip_low, self.clip_high = clip_range

    @abstractmethod
    def compute_adjustments(
        self,
        base_weights: dict[str, float],
        context: StrategyContext,
    ) -> ModifierResult:
        """计算调节因子。

        Args:
            base_weights: 核心策略的目标权重 {code: weight}
            context: 运行时上下文（含trade_date/conn/factor_df等）

        Returns:
            ModifierResult，adjustment_factors中:
            - 只包含需要调节的code（未包含的code factor默认=1.0）
            - factor范围由子类保证，apply_adjustments会做clip
        """

    @abstractmethod
    def should_trigger(self, context: StrategyContext) -> bool:
        """判断是否触发调节（事件型/条件型均可）。

        Args:
            context: 运行时上下文

        Returns:
            True表示本Modifier在当前时点应该生效
        """

    def apply_adjustments(
        self,
        base_weights: dict[str, float],
        result: ModifierResult,
        max_daily_adjustment: float = DEFAULT_MAX_DAILY_ADJUSTMENT,
    ) -> dict[str, float]:
        """将调节因子应用到基础权重，含clip+归一化+最大调节量限制。

        R3 §6.4约束:
        1. clip adjustment_factor到[clip_low, clip_high]
        2. 应用调节，检查总调节量是否超过max_daily_adjustment
        3. 归一化保持原始总权重

        Args:
            base_weights: 核心策略目标权重
            result: Modifier计算结果
            max_daily_adjustment: 单日最大调节量（相对总权重）

        Returns:
            调节+归一化后的目标权重
        """
        if not result.triggered or not result.adjustment_factors:
            return base_weights

        import numpy as np

        factors = result.adjustment_factors
        adjusted: dict[str, float] = {}

        for code, weight in base_weights.items():
            raw_factor = factors.get(code, 1.0)
            clipped = float(np.clip(raw_factor, self.clip_low, self.clip_high))
            adjusted[code] = weight * clipped

        # 检查总调节量
        original_total = sum(base_weights.values())
        adjusted_total = sum(adjusted.values())
        delta = abs(adjusted_total - original_total)

        if original_total > 1e-9 and delta / original_total > max_daily_adjustment:
            # 超过最大调节量，按比例缩减调节幅度
            logger.warning(
                f"[{self.name}] 调节量={delta / original_total:.1%} > "
                f"上限{max_daily_adjustment:.1%}，按比例缩减"
            )
            # 线性插值：缩减到 max_daily_adjustment
            scale_needed = max_daily_adjustment / (delta / original_total)
            adjusted = {
                code: base_weights[code] + (w - base_weights[code]) * scale_needed
                for code, w in adjusted.items()
            }
            adjusted_total = sum(adjusted.values())

        # 归一化，保持原始总权重
        if adjusted_total > 1e-9:
            norm_scale = original_total / adjusted_total
            adjusted = {c: w * norm_scale for c, w in adjusted.items()}

        logger.info(
            f"[{self.name}] 调节完成: {len(factors)}只个股调节, "
            f"原总权重={original_total:.3f}, 调节后={sum(adjusted.values()):.3f}"
        )
        return adjusted
