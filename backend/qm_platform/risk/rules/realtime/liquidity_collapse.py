"""LiquidityCollapse — 流动性枯竭检测 (S5 L1 实时化).

设计动机:
  - 持仓股 day vol < 20day avg × 0.3: 流动性严重萎缩, 出货风险
  - 区分: 正常低量 (0.5-0.7x) vs 枯竭 (< 0.3x)

阈值配置 (RT_* 环境变量):
  - RT_LIQUIDITY_COLLAPSE_RATIO=0.3  day vol / 20day avg 下限

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

_DEFAULT_COLLAPSE_RATIO: float = 0.3


class LiquidityCollapse(RiskRule):
    """流动性枯竭检测 — 当前累计量 vs 20日均量 比低于阈值.

    触发: day_volume / avg_daily_volume < threshold
    Action: alert_only (出货风险 signal)
    Severity: P1
    """

    rule_id: str = "liquidity_collapse"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, threshold: float = _DEFAULT_COLLAPSE_RATIO) -> None:
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
            if ratio >= self._threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"LiquidityCollapse: {pos.code} 流动性枯竭 "
                        f"(day_vol={day_vol}, avg_daily_vol={avg_daily_vol:.0f}, "
                        f"ratio={ratio:.2f}x < {self._threshold:.0%})"
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
