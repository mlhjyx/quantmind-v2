"""Capital Allocator interface — Layer 4 AI loop (multi-strategy capital allocation).

Plan v9 Phase M Proposal 7: interface-only contract pre Q3-Q4 implementation trigger (per ADR-028).
0% implementation, abstract class only.

Note: the existing CapitalAllocator ABC in .interface uses Decimal + strategies list signature
(MVP 3.2 Wave 3 static equal-weight). This module provides the Layer 4 AI loop variant that
operates on weight fractions (0.0-1.0) with AllocationContext, intended for the Q3-Q4
multi-strategy dynamic allocation trigger. Both coexist; ADR-028 governs promotion timing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyWeight:
    """One strategy's allocated weight + cap constraints."""

    strategy_id: str
    weight: float  # 0.0-1.0
    min_weight: float = 0.0
    max_weight: float = 1.0


@dataclass(frozen=True)
class AllocationContext:
    """Context for allocation decision."""

    total_capital: float  # CNY
    n_strategies: int
    market_regime: str  # 'bull' / 'bear' / 'sideways' / 'unknown'


class MultiStrategyCapitalAllocator(ABC):
    """Abstract multi-strategy capital allocator (Layer 4 AI loop weight-fraction variant).

    Layer 4 AI loop: allocate capital across N strategies based on performance + diversity.
    Initial: fixed YAML weights. Dynamic: only after 3-month stable period (per Plan v9 §7.3).

    Status: interface-only (Q3-Q4 trigger per ADR-028).

    Naming: prefixed Multi to avoid collision with the existing CapitalAllocator in interface.py
    (Decimal-based Wave 3 equal-weight allocator).
    """

    @abstractmethod
    def allocate(
        self,
        context: AllocationContext,
        strategy_ids: list[str],
    ) -> list[StrategyWeight]:
        """Return weight vector summing to 1.0."""
        ...

    @abstractmethod
    def constraint_violations(
        self,
        weights: list[StrategyWeight],
    ) -> list[str]:
        """List constraint violations (empty if valid)."""
        ...
