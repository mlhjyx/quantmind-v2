"""Realtime risk rules — 实时 tick 级风控规则 (S5, L1 实时化).

本包规则继承 RiskRule ABC, 区分 cadence:
  - tick: 每 tick 触发 (LimitDownDetection, NearLimitDown)
  - 5min: 每 5min 触发 (RapidDrop5min, VolumeSpike, CorrelatedDrop)
  - 15min: 每 15min 触发 (RapidDrop15min, IndustryConcentration, LiquidityCollapse)
  - pre_market: 9:25 开盘前触发 (GapDownOpen)

所有规则纯计算 (铁律 31), tick 数据通过 RiskContext.realtime 注入.
"""

from .gap_down import GapDownOpen
from .limit_down import LimitDownDetection, NearLimitDown
from .rapid_drop import RapidDrop5min, RapidDrop15min

__all__ = [
    "LimitDownDetection",
    "NearLimitDown",
    "GapDownOpen",
    "RapidDrop5min",
    "RapidDrop15min",
]
