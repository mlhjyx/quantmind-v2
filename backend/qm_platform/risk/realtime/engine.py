"""RealtimeRiskEngine — L1 实时化风控引擎.

按 cadence (tick/5min/15min) 评估注册规则:

  1. register(rule, cadence): 注册规则, cadence 决定何时 evaluate
  2. on_tick(ticks, context): tick 级规则评估 (LimitDownDetection, NearLimitDown)
  3. on_5min_beat(context): 5min 级规则评估 (RapidDrop5min)
  4. on_15min_beat(context): 15min 级规则评估 (RapidDrop15min)

与 PlatformRiskEngine 共享 RiskRule ABC, 但:
  - 不管理 PositionSource (由 caller 注入构建好的 RiskContext)
  - 不执行 sell/alert (仅返 RuleResult, caller 负责执行)
  - 自带 cadence 路由 (规则注册时指定 cadence)

用法:
    engine = RealtimeRiskEngine()
    engine.register(LimitDownDetection(), cadence="tick")
    engine.register(RapidDrop5min(), cadence="5min")
    ctx = RiskContext(strategy_id=..., timestamp=..., positions=..., realtime={...})
    results = engine.on_tick(ticks, ctx)
"""

from __future__ import annotations

import logging
from typing import Literal

from ..interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

Cadence = Literal["tick", "5min", "15min"]


class RealtimeRiskEngine:
    """实时风控引擎 — tick/5min/15min cadence 规则评估.

    规则按 cadence 分组注册, 调用对应 on_* 方法时仅评估该组规则.
    """

    def __init__(self) -> None:
        self._rules: dict[Cadence, dict[str, RiskRule]] = {
            "tick": {},
            "5min": {},
            "15min": {},
        }

    def register(self, rule: RiskRule, cadence: Cadence = "tick") -> None:
        """注册规则到指定 cadence 组.

        Raises:
            ValueError: rule_id 重复 或 cadence 无效.
        """
        if cadence not in self._rules:
            raise ValueError(f"Invalid cadence {cadence!r}, must be one of {list(self._rules)}")
        if rule.rule_id in self._rules[cadence]:
            raise ValueError(
                f"RiskRule rule_id={rule.rule_id!r} already registered in cadence={cadence!r}"
            )
        self._rules[cadence][rule.rule_id] = rule
        logger.info(
            "[realtime-engine] registered rule_id=%s cls=%s cadence=%s",
            rule.rule_id,
            type(rule).__name__,
            cadence,
        )

    @property
    def registered_rules(self) -> dict[Cadence, list[str]]:
        """按 cadence 分组查看已注册 rule_id."""
        return {cadence: list(rules.keys()) for cadence, rules in self._rules.items()}

    def _evaluate_group(self, cadence: Cadence, context: RiskContext) -> list[RuleResult]:
        """评估某 cadence 组全部规则."""
        results: list[RuleResult] = []
        for rule_id, rule in self._rules[cadence].items():
            try:
                rule_results = rule.evaluate(context)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "[realtime-engine] rule %s evaluate() raised %s: %s",
                    rule_id,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                continue
            results.extend(rule_results)
        return results

    def on_tick(self, context: RiskContext) -> list[RuleResult]:
        """评估 tick 级规则.

        Args:
            context: RiskContext (realtime 字段必须包含当前 tick 数据).

        Returns:
            触发规则列表. 空 = 无 tick 级规则触发.
        """
        return self._evaluate_group("tick", context)

    def on_5min_beat(self, context: RiskContext) -> list[RuleResult]:
        """评估 5min 级规则."""
        return self._evaluate_group("5min", context)

    def on_15min_beat(self, context: RiskContext) -> list[RuleResult]:
        """评估 15min 级规则."""
        return self._evaluate_group("15min", context)
