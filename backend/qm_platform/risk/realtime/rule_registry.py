"""RealtimeRiskEngine rule registry — SSOT for L1 rule set wiring.

V3 PT Cutover Plan v0.4 §A IC-1c WU-1: extract `register_all_realtime_rules`
out of `RiskBacktestAdapter` so both the backtest/replay adapter AND the
forthcoming L1 production runner (`scripts/realtime_risk_engine_service.py`,
IC-1c WU-2) wire the **same** 10-rule set on the **same** cadence map.

Cadence assignment per V3 §4.3 + ADR-029 §2.2 (post T1.5b-2 reviewer-fix
10-rule scope):
  - tick:  LimitDownDetection / NearLimitDown / GapDownOpen / TrailingStop  (4)
  - 5min:  RapidDrop5min / VolumeSpike / LiquidityCollapse /
           IndustryConcentration / CorrelatedDrop                            (5)
  - 15min: RapidDrop15min                                                    (1)

This module is the SINGLE SOURCE OF TRUTH. Drift between
`RiskBacktestAdapter.register_all_realtime_rules` (now a thin delegate) and
the production runner is **prevented by construction** — both import this
function. Sustains ADR-076 D1 invariant: replay 走 RealtimeRiskEngine 真实路径
+ replay-as-gate (HC-4a 5y replay + CT-1 cutover gate).

Lazy import retained from the adapter precedent — concrete rule classes are
not imported at module load so the platform stub remains usable without
pulling the rule implementations (production parity sustained per (α)).

关联铁律: 31 (engine PURE) / 33 (fail-loud on duplicate registration)
关联 ADR: ADR-029 (10 RealtimeRiskRule) / ADR-076 D1 (replay-as-gate parity)
          / ADR-078 reserved (IC-1c closure cumulative)
关联 V3: §4.3 (L1 cadence map) / §11.4 (RiskBacktestAdapter pure function)
          / §15.4 (paper-mode 5d dry-run prereq)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import RealtimeRiskEngine


def register_all_realtime_rules(engine: RealtimeRiskEngine) -> None:
    """Register the canonical 10 RealtimeRiskRule set on an engine.

    Cadence assignment per V3 §4.3 + ADR-029 §2.2.

    Args:
        engine: RealtimeRiskEngine instance to register rules into. The engine
            should be freshly constructed (no rules registered); duplicate
            registration raises per engine fail-loud (铁律 33).

    Raises:
        ValueError: any rule_id already registered on the engine.

    Note:
        Lazy import — concrete rule modules are imported inside the function
        to avoid pulling them at platform load time. This sustains stub
        usability without importing concrete rule classes (production parity
        invariant from the adapter precedent).
    """
    # Lazy import — avoid top-level circular + sustain stub usability without
    # importing concrete rule classes (production parity sustained per (α)).
    from ..rules.realtime.correlated_drop import CorrelatedDrop
    from ..rules.realtime.gap_down import GapDownOpen
    from ..rules.realtime.industry_concentration import IndustryConcentration
    from ..rules.realtime.limit_down import LimitDownDetection, NearLimitDown
    from ..rules.realtime.liquidity_collapse import LiquidityCollapse
    from ..rules.realtime.rapid_drop import RapidDrop5min, RapidDrop15min
    from ..rules.realtime.trailing_stop import TrailingStop
    from ..rules.realtime.volume_spike import VolumeSpike

    tick_rules = [
        LimitDownDetection(),
        NearLimitDown(),
        GapDownOpen(),
        TrailingStop(),
    ]
    five_min_rules = [
        RapidDrop5min(),
        VolumeSpike(),
        LiquidityCollapse(),
        IndustryConcentration(),
        CorrelatedDrop(),
    ]
    fifteen_min_rules = [
        RapidDrop15min(),
    ]

    for rule in tick_rules:
        engine.register(rule, cadence="tick")
    for rule in five_min_rules:
        engine.register(rule, cadence="5min")
    for rule in fifteen_min_rules:
        engine.register(rule, cadence="15min")


__all__ = ["register_all_realtime_rules"]
