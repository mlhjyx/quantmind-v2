"""VolumeSpike — 盘中成交量异动检测 (S5 L1 实时化).

设计动机:
  - 5min vol > 20day avg × 3: 异常放量, 触发 capital_flow 关联查询
  - 区分: 大涨放量 (利好) vs 大跌放量 (恐慌), 本规则仅检测量异动, 方向由其他规则覆盖

阈值配置 (RT_* 环境变量):
  - RT_VOLUME_SPIKE_RATIO=3.0  5min vol / 20day avg 倍率阈值

数据依赖: RiskContext.realtime[code] 含 day_volume + avg_daily_volume.
若某股缺失 avg_daily_volume, 该股 silent skip.

关联铁律: 24 / 31 / 33
"""

from __future__ import annotations

import logging
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

# 5min 成交量 vs 20日均量 整数比, 避免 .env float parse 问题
_DEFAULT_SPIKE_RATIO: float = 3.0


class VolumeSpike(RiskRule):
    """盘中成交量异动 — 当前累计量 vs 20日均量 比超阈值.

    触发: day_volume / avg_daily_volume >= threshold
    Action: alert_only (触发 capital_flow 查询, 非 sell)
    Severity: P1 (异动 signal)
    """

    rule_id: str = "volume_spike"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, threshold: float = _DEFAULT_SPIKE_RATIO) -> None:
        self._threshold = threshold

    def update_threshold(self, new_value: float) -> None:
        """S7→S5 wire: DynamicThresholdEngine 更新阈值."""
        self._threshold = new_value

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        results: list[RuleResult] = []
        for pos in context.positions:
            if pos.shares <= 0:
                continue

            tick = context.realtime.get(pos.code)
            if tick is None:
                continue

            day_vol = tick.get("day_volume")
            avg_daily_vol = tick.get("avg_daily_volume")
            if day_vol is None or avg_daily_vol is None or avg_daily_vol <= 0:
                continue

            ratio = day_vol / avg_daily_vol
            if ratio < self._threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"VolumeSpike: {pos.code} 成交量异动 "
                        f"(day_vol={day_vol}, avg_daily_vol={avg_daily_vol:.0f}, "
                        f"ratio={ratio:.1f}x >= {self._threshold:.0f}x)"
                    ),
                    metrics={
                        "day_volume": day_vol,
                        "avg_daily_volume": round(avg_daily_vol, 2),
                        "ratio": round(ratio, 4),
                        "threshold": self._threshold,
                    },
                )
            )
        return results
