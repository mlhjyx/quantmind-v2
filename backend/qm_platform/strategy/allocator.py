"""MVP 3.2 Strategy Framework — EqualWeightAllocator concrete.

**批 1 (Session 33 Part 1, 2026-04-24)**: 最简 CapitalAllocator 实现 — 等权 1/N 分配.

Wave 3 静态等权, 后续 Wave 4+ 扩 vol-target / max-drawdown-budget / regime-dependent.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from .interface import CapitalAllocator

if TYPE_CHECKING:
    from .interface import Strategy

_logger = logging.getLogger(__name__)


class EqualWeightAllocator(CapitalAllocator):
    """等权资本分配器 — 每策略 total_capital / len(strategies).

    Edge cases:
      - strategies 空: 返 {}
      - total_capital ≤ 0: raise ValueError (防 paper 初始化异常)
      - rounding: Decimal 精度对齐, sum(allocations) 可能差 1-2 分 (尾差归最后一个策略吸收
        避免总和超过 total_capital)
    """

    def allocate(
        self,
        strategies: list[Strategy],
        total_capital: Decimal,
        regime: str,
    ) -> dict[str, Decimal]:
        """返回 strategy_id → Decimal 资本映射.

        Args:
          strategies: 活跃策略 (调用方保证 status 过滤, 通常 get_live())
          total_capital: 总资本 Decimal, 必须 > 0
          regime: 当前 regime (本实现忽略, 扩展版本用于 regime-aware 分配)

        Returns:
          dict {strategy_id_str: allocated_capital}, sum ≤ total_capital

        Raises:
          ValueError: total_capital ≤ 0
        """
        if total_capital <= 0:
            raise ValueError(
                f"total_capital 必须 > 0, 实测 {total_capital}. "
                "paper 配置或 live cash 被异常扣完."
            )
        n = len(strategies)
        if n == 0:
            _logger.warning(
                "EqualWeightAllocator.allocate: strategies 为空, 返 {} (可能全部 retired)"
            )
            return {}

        # Decimal 等权 + 尾差吸收
        per_strategy = (total_capital / Decimal(n)).quantize(Decimal("0.01"))
        allocations: dict[str, Decimal] = {}
        running_sum = Decimal("0")
        for i, s in enumerate(strategies):
            if i < n - 1:
                alloc = per_strategy
            else:
                # 最后一个吸收 rounding 尾差 (防 sum > total_capital)
                alloc = (total_capital - running_sum).quantize(Decimal("0.01"))
            allocations[str(s.strategy_id)] = alloc
            running_sum += alloc

        _logger.info(
            "EqualWeightAllocator.allocate: n=%d total=%s per=%s regime=%s",
            n,
            total_capital,
            per_strategy,
            regime,
        )
        return allocations
