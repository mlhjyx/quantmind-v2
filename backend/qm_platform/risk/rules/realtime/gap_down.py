"""GapDownOpen — 集合竞价跳空检测 (S5 L1 实时化).

设计动机 (4-29 集合竞价跳空场景):
  - 9:25 集合竞价后立即发现跳空, 9:30 开盘前 actionable alert
  - 跳空开盘后 T+1 无法止损, 必须开盘前准备 sell 单

触发: (open_price - prev_close) / prev_close <= -threshold (默认 -5%)
Cadence: pre_market (9:25, 每日一次)
Action: alert_only (准备 9:30 限价卖单)

关联铁律: 24 / 31 / 33
"""

from __future__ import annotations

import logging
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


class GapDownOpen(RiskRule):
    """集合竞价跳空下跌检测.

    触发: 开盘价相对前收盘跌幅 >= threshold
    Action: alert_only (候选 9:30 限价卖单)
    Severity: P0 (集合竞价刚结束, 9:30 前决策窗口)
    """

    rule_id: str = "gap_down_open"
    severity: Severity = Severity.P0
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

            prev_close = tick.get("prev_close")
            open_price = tick.get("open_price")
            if prev_close is None or prev_close <= 0:
                continue
            if open_price is None or open_price <= 0:
                continue

            gap_pct = (open_price - prev_close) / prev_close
            if gap_pct > -self._threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"GapDownOpen: {pos.code} 集合竞价跳空 "
                        f"(跌幅={gap_pct:.2%} <= -{self._threshold:.0%}, "
                        f"open={open_price:.2f}, prev_close={prev_close:.2f})"
                    ),
                    metrics={
                        "gap_pct": round(gap_pct, 6),
                        "open_price": open_price,
                        "prev_close": prev_close,
                        "threshold": self._threshold,
                        "shares": float(pos.shares),
                    },
                )
            )
        return results
