"""Realtime risk engine — L1 实时化风控引擎 (S5).

RealtimeRiskEngine 接收 xtquant tick 推送, 按 cadence (tick/5min/15min)
评估注册的实时风控规则, 返 RuleResult 列表供上层执行.

与 PlatformRiskEngine 区别:
  - PlatformRiskEngine: Beat 驱动 (5min/14:30), 适合盘后/组合级规则
  - RealtimeRiskEngine: tick 驱动, 适合秒级跌停 detection

关联铁律: 31 (规则纯计算) / 33 (fail-loud)
"""

from .engine import RealtimeRiskEngine
from .subscriber import XtQuantTickSubscriber

__all__ = [
    "RealtimeRiskEngine",
    "XtQuantTickSubscriber",
]
