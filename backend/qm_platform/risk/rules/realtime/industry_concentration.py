"""IndustryConcentration — 行业集中度检测 (S5 L1 实时化).

设计动机:
  - 单行业暴露 > 30%: 行业集中风险, 反 4-29 多股同时跌停教训
  - 跨行业持仓 vs 集中度: 防止单一行业系统性风险

阈值配置 (RT_* 环境变量):
  - RT_INDUSTRY_CONCENTRATION=0.30  单行业最大暴露比例

数据依赖: RiskContext.realtime[code] 含 industry (SW1 行业名).
若某股缺失 industry, 该股归入 "unknown" 计数 (不跳过, 因为未知行业也是风险).

关联铁律: 24 / 31 / 33
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

_DEFAULT_CONCENTRATION: float = 0.30


class IndustryConcentration(RiskRule):
    """行业集中度检测 — 单行业暴露超过阈值.

    触发: 任一行业中持仓股数 / 总持仓股数 > threshold
    Action: alert_only
    Severity: P2
    """

    rule_id: str = "industry_concentration"
    severity: Severity = Severity.P2
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, threshold: float = _DEFAULT_CONCENTRATION) -> None:
        self._threshold = threshold

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        total = len(context.positions)
        if total == 0:
            return []

        # 统计行业分布
        industry_counts: Counter[str] = Counter()
        unknown_count = 0

        if context.realtime is not None:
            for pos in context.positions:
                tick = context.realtime.get(pos.code)
                if tick is not None:
                    industry = tick.get("industry")
                    if industry and isinstance(industry, str):
                        industry_counts[industry] += 1
                    else:
                        unknown_count += 1
                else:
                    unknown_count += 1
        else:
            # 无 realtime 数据时, 所有股归入 unknown
            unknown_count = total

        if unknown_count > 0:
            industry_counts["unknown"] = unknown_count

        # 找最大集中度
        most_common = industry_counts.most_common(1)
        if not most_common:
            return []

        top_industry, top_count = most_common[0]
        concentration = top_count / total

        if concentration <= self._threshold:
            return []

        return [
            RuleResult(
                rule_id=self.rule_id,
                code="",
                shares=0,
                reason=(
                    f"IndustryConcentration: "
                    f"行业 '{top_industry}' 持仓 {top_count}/{total} "
                    f"({concentration:.1%} > {self._threshold:.0%})"
                ),
                metrics={
                    "top_industry": top_industry,
                    "top_count": top_count,
                    "total_positions": total,
                    "concentration": round(concentration, 4),
                    "threshold": self._threshold,
                    "unknown_count": unknown_count,
                    "industry_breakdown": dict(industry_counts),
                },
            )
        ]
