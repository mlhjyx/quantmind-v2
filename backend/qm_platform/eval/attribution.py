"""MVP 4.2 Performance Attribution — DailyAttribution dataclass + interface (iter 59 entry).

Per QPB v1.16 §Wave 4 详细 MVP 4.2 spec + docs/mvp/MVP_4_2_attribution.md.

每日自动产出 DailyAttribution JSON, 拆解 PT NAV 变化为:
  - by_factor: per-factor P&L
  - by_sector: per-sector P&L
  - by_regime: regime context
  - by_cost: commission/slippage/impact/overnight_gap
  - alpha_vs_benchmark: 超额 vs CSI300/等权
  - unexplained_residual: 归因残差 (>阈值告警)

实施分批 (multi-iter campaign per MVP_4_2_attribution.md §4):
  - iter 59 (本): dataclass skeleton + interface stub + shape tests
  - iter 60+: compute_by_factor (WLS regression)
  - iter 61+: compute_by_sector (SW1 industry mapping)
  - iter 62+: compute_by_cost (trade_log aggregation)
  - iter 63+: compute_by_regime (HMM regime_detector)
  - iter 64+: residual alert via AlertRouter SDK (复用 batch 3.x pattern)
  - iter 65+: Daily Beat task

铁律对齐:
  - 24 (MVP ≤ 2页 spec)
  - 31 (Engine 纯计算 — compute_* 函数 stateless, 0 DB/HTTP/Redis)
  - 38 (Blueprint sustained — QPB v1.16 §Wave 4)

Platform 严格隔离 (沿用 MVP 1.1 test_platform_strict_isolation):
  - 0 import backend.app.* / backend.data.* / backend.engines.*
  - DI via conn_factory (writes) + DAL (reads), 沿用 factor/strategy registry 体例
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class RegimeInfo:
    """Regime detection context for daily attribution.

    Source: backend/engines/regime_detector.py 3-state HMM (bull/sideways/bear).
    iter 59: shape only; iter 63+ wire actual HMM probabilities.
    """

    detected: str  # "bull" / "sideways" / "bear"
    expected_perf_bps: float  # HMM 期望日收益 (basis points)
    actual_perf_bps: float  # 实际日收益 (basis points)


@dataclass(frozen=True)
class DailyAttribution:
    """每日归因 JSON payload (QPB v1.16 §Wave 4 MVP 4.2 spec).

    All P&L fields are decimal fractions (0.0012 = 0.12% = 12 bps).
    Residual = nav_change_pct - sum(by_factor) - sum(by_sector) - sum(by_cost) - alpha_vs_benchmark.
    """

    trade_date: date
    strategy_id: str
    execution_mode: str  # "paper" / "live" (sustained sustained namespace from V3 红线)
    nav_change_pct: float  # daily NAV change as decimal (0.012 = 1.2%)
    by_factor: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    by_regime: RegimeInfo | None = None
    by_cost: dict[str, float] = field(default_factory=dict)
    alpha_vs_benchmark: float = 0.0  # vs CSI300 default
    unexplained_residual: float = 0.0


class AttributionEngine(Protocol):
    """MVP 4.2 attribution engine interface (iter 59 stub).

    Implementations (iter 60+):
      - WLSFactorAttributor (compute_by_factor via factor exposure regression)
      - SectorAttributor (compute_by_sector via SW1 industry mapping)
      - CostAttributor (compute_by_cost via trade_log slippage / commission fields)
      - RegimeAttributor (compute_by_regime via HMM 3-state probabilities)
      - ResidualAlerter (compute_residual_alert + AlertRouter SDK dispatch)
    """

    def compute(
        self,
        trade_date: date,
        strategy_id: str,
        execution_mode: str = "paper",
    ) -> DailyAttribution:
        """Compute daily attribution for given strategy + execution mode."""
        ...


def residual_exceeds_threshold(
    attribution: DailyAttribution,
    threshold_bps: float = 20.0,
) -> bool:
    """Check if unexplained_residual exceeds alert threshold.

    Default threshold 20 bps (= 0.20% = 0.002 decimal). Per QPB MVP 4.2 spec:
    "残差 > 阈值自动 flag" (iter 64+ wire AlertRouter SDK dispatch).

    Args:
        attribution: DailyAttribution payload.
        threshold_bps: alert threshold in basis points (default 20).

    Returns:
        True if abs(unexplained_residual) > threshold_bps / 10000.
    """
    return abs(attribution.unexplained_residual) > (threshold_bps / 10000.0)


__all__ = [
    "AttributionEngine",
    "DailyAttribution",
    "RegimeInfo",
    "residual_exceeds_threshold",
]
