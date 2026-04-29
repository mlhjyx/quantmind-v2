"""SingleStockStopLossRule — 单股止损规则 (MVP 3.1b Phase 1, P0 真生产事件驱动).

设计动机 (Session 44, 2026-04-29 真生产事件):
  PT live 卓然股份 (688121) -29.17% / -¥14,306, 30 天 risk_event_log 0 触发.
  实测 PMS / IntradayPortfolioDrop / CB 4 规则全部对此场景设计上失效 —
    - PMS 要求先有浮盈后回撤 (买入即跌从未浮盈, 全 skip)
    - IntradayPortfolioDrop 是组合层 -3% (单股 -29% / NAV ¥1M = -1.4% < 3%)

本规则补"单股层"空白: 直接看 entry_price vs current_price, 不依赖浮盈/组合.

阈值 (4 档, 与 PMSRule 三档对称设计):
  - L1 -10%: P2 alert (信息记录, 提示用户审视)
  - L2 -15%: P1 alert (当日响应, 钉钉触达)
  - L3 -20%: P0 alert (立即处理, 钉钉 + 短信预备)
  - L4 -25%: P0 alert/sell (用户开 flag 后启用真正自动止损)

action 默认 alert_only:
  误触发自动卖 = 真金事故; 钉钉告警让用户决策 (与 PMSRule action='sell' 区分 —
  PMS 是"已盈利保护"不致灾, 单股止损是真金止血必须人工 review).
  -25% 档 future flag (settings.SINGLE_STOCK_AUTO_SELL_L4) 启用 sell action.

关联铁律: 24 (单一职责) / 31 (纯计算无 IO) / 33 (fail-loud) / 34 (config SSOT 阈值)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StopLossThreshold:
    """单档止损阈值 (frozen, 不可变).

    Args:
      level: 1/2/3/4 档号 (1 最宽 -10%, 4 最严 -25%)
      max_loss_pct: 最大亏损阈 (e.g. 0.10 = -10%)
      severity: P2/P1/P0 告警级
      action: alert_only (默认) / sell (-25% 档 future flag)
    """

    level: int
    max_loss_pct: float
    severity: Severity
    action: Literal["alert_only", "sell"]


# 默认 4 档阈值 (与 PMSRule 三档对称, 阈值升序: L1 最宽 → L4 最严)
_DEFAULT_LEVELS: Final[tuple[StopLossThreshold, ...]] = (
    StopLossThreshold(level=1, max_loss_pct=0.10, severity=Severity.P2, action="alert_only"),
    StopLossThreshold(level=2, max_loss_pct=0.15, severity=Severity.P1, action="alert_only"),
    StopLossThreshold(level=3, max_loss_pct=0.20, severity=Severity.P0, action="alert_only"),
    StopLossThreshold(level=4, max_loss_pct=0.25, severity=Severity.P0, action="alert_only"),
)


class SingleStockStopLossRule(RiskRule):
    """单股止损规则 (4 档阶梯, 设计与 PMSRule 互补).

    单 position 按 L4→L3→L2→L1 顺序 (最严先) 命中后停止,
    返 RuleResult.rule_id = "single_stock_stoploss_l{N}".

    与 PMSRule 互补:
      - PMSRule: 浮盈 ≥ +10/20/30% AND 回撤 ≥ 10/12/15% → 保护"涨完回撤"
      - 本规则: 单股 loss ≥ 10/15/20/25% → 保护"买入即跌" (PMS 失效场景)

    跳过条件 (silent skip, 对齐 PMSRule pattern):
      - entry_price <= 0 (未建仓 / 命名空间漂移 avg_cost=0)
      - current_price <= 0 (Redis 无价 / 数据异常)
      - shares <= 0 (空仓 / 已平仓待清理)

    Invariants:
      rule_id = "single_stock_stoploss" (基础, RuleResult 动态 "_l{N}")
      severity = 由触发档动态 override (基础值 P1 占位, 实际看 triggered level)
      action = "alert_only" (默认, future SINGLE_STOCK_AUTO_SELL_L4 flag 启 sell L4)

    Args:
      levels: 阈值配置, None 用 _DEFAULT_LEVELS. 支持 .env 注入未来扩展.
      auto_sell_l4: True 时 L4 档 action='sell' (默认 False, 全 alert_only).
    """

    rule_id: str = "single_stock_stoploss"
    severity: Severity = Severity.P1  # 基础占位, 触发时按 level 动态
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self,
        levels: tuple[StopLossThreshold, ...] | None = None,
        auto_sell_l4: bool = False,
    ) -> None:
        self._levels = levels if levels is not None else _DEFAULT_LEVELS
        # Precondition: levels 按 max_loss_pct 升序 (L1 最宽 → L4 最严, 反序遍历命中最严)
        if not all(
            self._levels[i].max_loss_pct <= self._levels[i + 1].max_loss_pct
            for i in range(len(self._levels) - 1)
        ):
            raise ValueError(
                f"SingleStockStopLossRule levels must be sorted by max_loss_pct ASC, "
                f"got {self._levels!r}"
            )
        self._auto_sell_l4 = auto_sell_l4

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        """反查 root rule_id: single_stock_stoploss_l{N} → single_stock_stoploss.

        非 single_stock_stoploss_l{N} pattern passthrough (不声明拥有).
        """
        prefix = "single_stock_stoploss_l"
        if triggered_rule_id.startswith(prefix) and triggered_rule_id[len(prefix):].isdigit():
            return "single_stock_stoploss"
        return triggered_rule_id

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查每个 position 单股止损阈值. 反序 (L4 先) 命中即返."""
        results: list[RuleResult] = []
        # 反序: L4 (-25%) 最严先查, 命中即 break, 不会被 L1 覆盖
        levels_desc = sorted(self._levels, key=lambda l: l.max_loss_pct, reverse=True)

        for pos in context.positions:
            if pos.entry_price <= 0 or pos.current_price <= 0 or pos.shares <= 0:
                continue

            loss_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            # loss_pct < 0 表示亏损, abs(loss_pct) >= threshold 触发
            # 等价: loss_pct <= -threshold (注意符号)
            triggered_level: StopLossThreshold | None = None
            for lvl in levels_desc:
                if loss_pct <= -lvl.max_loss_pct:
                    triggered_level = lvl
                    break

            if triggered_level is None:
                continue

            # auto_sell_l4 flag override L4 档 action
            effective_action = triggered_level.action
            if triggered_level.level == 4 and self._auto_sell_l4:
                effective_action = "sell"

            # alert_only 时 shares=0 (不卖); sell 时填全部 shares
            result_shares = pos.shares if effective_action == "sell" else 0

            results.append(
                RuleResult(
                    rule_id=f"single_stock_stoploss_l{triggered_level.level}",
                    code=pos.code,
                    shares=result_shares,
                    reason=(
                        f"SingleStockStopLoss L{triggered_level.level} triggered: "
                        f"loss={loss_pct:.2%} <= -{triggered_level.max_loss_pct:.0%} "
                        f"(entry={pos.entry_price:.4f}, current={pos.current_price:.4f}, "
                        f"shares={pos.shares}, action={effective_action})"
                    ),
                    metrics={
                        "level": float(triggered_level.level),
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "loss_pct": round(loss_pct, 6),
                        "max_loss_threshold": triggered_level.max_loss_pct,
                        "shares": float(pos.shares),
                        # severity 写 metrics 便于下游 audit (rule.severity 是 ClassVar
                        # 占位 P1, 实际触发档 severity 在 triggered_level)
                        "severity_level_p": float(
                            {Severity.P0: 0, Severity.P1: 1, Severity.P2: 2, Severity.INFO: 3}[
                                triggered_level.severity
                            ]
                        ),
                    },
                )
            )

        return results
