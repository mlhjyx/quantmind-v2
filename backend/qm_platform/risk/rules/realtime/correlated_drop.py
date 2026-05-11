"""CorrelatedDrop — 多股联动下跌检测 (S5 L1 实时化).

设计动机:
  - 持仓 N 股同时下跌 (5min 内 ≥ 3 股 > -3%): 系统性风险 signal
  - Crisis regime 候选触发条件 (升级至 P0 级别通知)

阈值配置 (RT_* 环境变量):
  - RT_CORRELATED_DROP_COUNT=3     最少触发股数
  - RT_CORRELATED_DROP_PCT=0.03    单股最小跌幅

数据依赖: RiskContext.realtime[code] 含 price_5min_ago (用于计算 5min 跌幅).
若某股缺失 rolling price, 该股不计入联动计数 (但不影响其他股).

联动规则: 5min 内 ≥ N 股跌幅 ≥ threshold → P0 alert (系统性风险).

关联铁律: 24 / 31 / 33
"""

from __future__ import annotations

import logging
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

_DEFAULT_MIN_COUNT: int = 3
_DEFAULT_DROP_PCT: float = 0.03


class CorrelatedDrop(RiskRule):
    """多股联动下跌检测 — 5min 内 ≥ N 股跌幅 ≥ threshold.

    触发: 持仓中≥3股 5min跌幅 ≥ 3% → P0 alert
    Action: alert_only (Crisis regime 候选)
    Severity: P0 (系统性风险)
    """

    rule_id: str = "correlated_drop"
    severity: Severity = Severity.P0
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self,
        min_count: int = _DEFAULT_MIN_COUNT,
        drop_threshold: float = _DEFAULT_DROP_PCT,
    ) -> None:
        self._min_count = min_count
        self._drop_threshold = drop_threshold

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        # 收集所有满足跌幅条件的股
        triggered: list[dict] = []
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
            if drop_pct <= -self._drop_threshold:
                triggered.append(
                    {
                        "code": pos.code,
                        "drop_pct": round(drop_pct, 6),
                        "price": pos.current_price,
                        "price_5min_ago": price_5min_ago,
                    }
                )

        if len(triggered) < self._min_count:
            return []

        codes = [t["code"] for t in triggered]
        drops = [f"{t['code']}({t['drop_pct']:.2%})" for t in triggered]

        return [
            RuleResult(
                rule_id=self.rule_id,
                code=",".join(codes),
                shares=0,
                reason=(
                    f"CorrelatedDrop: {len(triggered)}/{len(context.positions)} 股 "
                    f"5min 联动下跌 ≥ {self._drop_threshold:.0%}: {', '.join(drops)}"
                ),
                metrics={
                    "triggered_count": len(triggered),
                    "total_positions": len(context.positions),
                    "min_count": self._min_count,
                    "drop_threshold": self._drop_threshold,
                    "triggered_codes": codes,
                    "triggered_drops": [t["drop_pct"] for t in triggered],
                },
            )
        ]
