"""RapidDrop5min + RapidDrop15min — 快速下跌检测 (S5 L1 实时化).

设计动机:
  - 5min 跌 > 5%: 异动 signal, 触发 L2 sentiment 关联查询
  - 15min 跌 > 8%: 严重异动, 候选 staged sell

阈值配置 (RT_* 环境变量):
  - RT_RAPID_DROP_5MIN=0.05    5min 跌幅阈值
  - RT_RAPID_DROP_15MIN=0.08   15min 跌幅阈值

数据依赖: RiskContext.realtime[code] 含 price_5min_ago / price_15min_ago.
若某股缺失 rolling price, 该股 silent skip.

关联铁律: 24 / 31 / 33
"""

from __future__ import annotations

import logging
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


class RapidDrop5min(RiskRule):
    """5min 快速下跌检测 — 5min 内跌幅超过 5%.

    触发: (current_price - price_5min_ago) / price_5min_ago <= -threshold
    Action: alert_only (触发 L2 sentiment 关联查询, 非立即 sell)
    Severity: P1 (异动 signal)
    """

    rule_id: str = "rapid_drop_5min"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, threshold: float = 0.05) -> None:
        self._threshold = threshold

    def update_threshold(self, new_value: float) -> None:
        """S7→S5 wire: DynamicThresholdEngine 更新阈值."""
        self._threshold = new_value

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        results: list[RuleResult] = []
        for pos in context.positions:
            if pos.current_price <= 0 or pos.shares <= 0:
                continue

            tick = context.realtime.get(pos.code)
            if tick is None:
                continue

            price_5min_ago = tick.get("price_5min_ago")
            if price_5min_ago is None or price_5min_ago <= 0:
                continue

            drop_pct = (pos.current_price - price_5min_ago) / price_5min_ago
            if drop_pct > -self._threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"RapidDrop5min: {pos.code} 5min 快速下跌 "
                        f"(跌幅={drop_pct:.2%} <= -{self._threshold:.0%}, "
                        f"price={pos.current_price:.2f}, "
                        f"5min_ago={price_5min_ago:.2f})"
                    ),
                    metrics={
                        "drop_pct": round(drop_pct, 6),
                        "current_price": pos.current_price,
                        "price_5min_ago": price_5min_ago,
                        "threshold": self._threshold,
                        "shares": float(pos.shares),
                    },
                )
            )
        return results


class RapidDrop15min(RiskRule):
    """15min 快速下跌检测 — 15min 内跌幅超过 8%.

    触发: (current_price - price_15min_ago) / price_15min_ago <= -threshold
    Action: alert_only (候选 staged sell, 非立即 sell)
    Severity: P1 (严重异动)
    """

    rule_id: str = "rapid_drop_15min"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, threshold: float = 0.08) -> None:
        self._threshold = threshold

    def update_threshold(self, new_value: float) -> None:
        """S7→S5 wire: DynamicThresholdEngine 更新阈值."""
        self._threshold = new_value

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        results: list[RuleResult] = []
        for pos in context.positions:
            if pos.current_price <= 0 or pos.shares <= 0:
                continue

            tick = context.realtime.get(pos.code)
            if tick is None:
                continue

            price_15min_ago = tick.get("price_15min_ago")
            if price_15min_ago is None or price_15min_ago <= 0:
                continue

            drop_pct = (pos.current_price - price_15min_ago) / price_15min_ago
            if drop_pct > -self._threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"RapidDrop15min: {pos.code} 15min 快速下跌 "
                        f"(跌幅={drop_pct:.2%} <= -{self._threshold:.0%}, "
                        f"price={pos.current_price:.2f}, "
                        f"15min_ago={price_15min_ago:.2f})"
                    ),
                    metrics={
                        "drop_pct": round(drop_pct, 6),
                        "current_price": pos.current_price,
                        "price_15min_ago": price_15min_ago,
                        "threshold": self._threshold,
                        "shares": float(pos.shares),
                    },
                )
            )
        return results
