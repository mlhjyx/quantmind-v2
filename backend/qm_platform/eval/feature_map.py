"""Feature Map interface — Layer 3 AI loop (MAP-Elites Quality-Diversity archive).

Plan v9 Phase M Proposal 7: interface-only contract pre Q3-Q4 implementation trigger (per ADR-028).
0% implementation, abstract class only. Concrete implementation defer Q3-Q4.

Pattern: follow QPB SDK conventions — interface.py / factory.py / impl.py separation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureCoordinate:
    """N-dimensional feature space coordinate (MAP-Elites grid cell)."""

    dimensions: tuple[float, ...]


@dataclass(frozen=True)
class FeatureMapEntry:
    """One archive entry: candidate + its feature coordinate + performance."""

    candidate_id: str
    coord: FeatureCoordinate
    performance: float  # higher = better


class FeatureMap(ABC):
    """Abstract Quality-Diversity archive (MAP-Elites grid).

    Layer 3 AI loop: maintain diverse-yet-high-performing candidates.
    Use case: factor / strategy candidate archiving with diversity preservation.

    Status: interface-only (Q3-Q4 trigger per ADR-028).
    """

    @abstractmethod
    def insert(self, entry: FeatureMapEntry) -> bool:
        """Insert entry. Returns True if accepted (improves cell), False if rejected."""
        ...

    @abstractmethod
    def get_cell(self, coord: FeatureCoordinate) -> FeatureMapEntry | None:
        """Get entry at coordinate, None if empty."""
        ...

    @abstractmethod
    def archive(self) -> Iterable[FeatureMapEntry]:
        """Iterate all archived entries."""
        ...

    @abstractmethod
    def coverage(self) -> float:
        """Fraction of grid cells filled (0.0-1.0)."""
        ...

    @abstractmethod
    def dimensions(self) -> Sequence[str]:
        """Names of feature dimensions (e.g. ['ic_ma20', 'turnover_rate', 'corr_max'])."""
        ...
