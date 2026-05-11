"""Realtime risk engine — L1 实时化风控引擎 (S5) + L0 告警实时化 (S6).

RealtimeRiskEngine 接收 xtquant tick 推送, 按 cadence (tick/5min/15min)
评估注册的实时风控规则, 返 RuleResult 列表供上层执行.

AlertDispatcher (S6): P0 立即 / P1+P2 批量缓冲告警分发.

与 PlatformRiskEngine 区别:
  - PlatformRiskEngine: Beat 驱动 (5min/14:30), 适合盘后/组合级规则
  - RealtimeRiskEngine: tick 驱动, 适合秒级跌停 detection

关联铁律: 31 (规则纯计算) / 33 (fail-loud)
"""

from .alert import AlertDispatcher
from .email_backup import EmailBackupStub
from .engine import RealtimeRiskEngine
from .subscriber import XtQuantTickSubscriber

__all__ = [
    "AlertDispatcher",
    "EmailBackupStub",
    "RealtimeRiskEngine",
    "XtQuantTickSubscriber",
]
