"""PositionHoldingTimeRule — 长尾持仓警示 (MVP 3.1b Phase 1.5b, Session 44).

设计动机:
  月度调仓策略下, 30 天以上持仓 = 至少跨过 1 个调仓周期未被换仓. 可能原因:
    1. universe filter 漏 (e.g. ST 标记滞后, 股票应被排除却仍在 portfolio)
    2. 持仓状态污染 (Session 10 P0-β execution_mode 命名空间漂移类 bug)
    3. 单股 idiosyncratic 风险积累 (用户主动 hold 但忘了 review)

  本规则以**时间维度**补 PMS / SingleStockStopLoss 的盲区 — 后两者基于 P&L,
  本规则基于 holding_days. 用户应主动 review 决定 hold/sell, 规则不自动卖.

阈值:
  默认 30 天 (P2 alert_only). 与 A 股月度调仓节奏对齐.
  自定义 ctor: PositionHoldingTimeRule(threshold_days=N).

依赖 Phase 1.5a (PR #147):
  - 读 Position.entry_date (从 trade_log MIN(buy.trade_date) since last sell 派生)
  - entry_date is None → silent skip (旧持仓 backfill 缺数据)

关联铁律: 24 (单一职责) / 31 (纯计算无 IO) / 33 (silent_ok skip 路径)
"""
from __future__ import annotations

import logging
from typing import Final, Literal
from zoneinfo import ZoneInfo

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


_DEFAULT_HOLDING_DAYS_THRESHOLD: Final[int] = 30

# P2 reviewer 采纳 (PR #148): timezone 统一 (与 NewPositionVolatilityRule +
# IntradayAlertDedup 一致), 防 UTC midnight 边界事故.
_CHINA_TZ = ZoneInfo("Asia/Shanghai")


class PositionHoldingTimeRule(RiskRule):
    """长尾持仓警示规则 (与 PMS / SingleStockStopLoss 互补).

    与现有 4 rules 的关系:
      - PMSRule: 浮盈 + 回撤 → "锁利润"维度
      - SingleStockStopLossRule: 单股 loss 阶梯 → "止损"维度
      - IntradayPortfolioDropRule: 组合层 drop → "盘中"维度
      - **本规则**: holding_days → "时间"维度 (新增 idiomatic)

    跳过条件 (silent skip, 对齐 PMSRule pattern):
      - entry_date is None: 无 trade_log buy 历史 (旧持仓 / 新策略未建仓)
      - shares <= 0: 已平仓待清理

    Args:
      threshold_days: holding_days >= 阈值即触发. 默认 30 (月度调仓 1 周期).
    """

    rule_id: str = "position_holding_time"
    severity: Severity = Severity.P2
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self, threshold_days: int = _DEFAULT_HOLDING_DAYS_THRESHOLD,
    ) -> None:
        if threshold_days < 1:
            raise ValueError(
                f"PositionHoldingTimeRule threshold_days must be >= 1, "
                f"got {threshold_days}"
            )
        self._threshold_days = threshold_days

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        """反查 root rule_id. 本规则单一 rule_id, 无 _l{N} 子档."""
        return self.rule_id if triggered_rule_id == self.rule_id else triggered_rule_id

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """按 (today - entry_date) 计算 holding_days, >= threshold 触发."""
        results: list[RuleResult] = []
        # P2 reviewer 采纳 (PR #148): astimezone CST 防 UTC midnight 边界错位.
        today = context.timestamp.astimezone(_CHINA_TZ).date()

        for pos in context.positions:
            if pos.entry_date is None or pos.shares <= 0:
                # silent_ok: 无 entry_date (Phase 1.5a 缺数据) 或已平仓 → skip
                continue

            holding_days = (today - pos.entry_date).days
            # P1 defense reviewer 采纳 (PR #148): holding_days < 0 防 future
            # entry_date 异常 (defense-in-depth, NewPositionVolatilityRule 关键 bug
            # 同源, 此处 -2 < 30 已正确 skip 但显式 guard 防未来 threshold=0 时漏挡).
            if holding_days < 0 or holding_days < self._threshold_days:
                # silent_ok: 异常 (future entry_date) 或持仓未达阈值
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,  # alert_only, 不卖
                    reason=(
                        f"PositionHoldingTime triggered: holding_days={holding_days} "
                        f">= threshold {self._threshold_days} days "
                        f"(entry_date={pos.entry_date.isoformat()}, "
                        f"today={today.isoformat()}, shares={pos.shares})"
                    ),
                    metrics={
                        "holding_days": float(holding_days),
                        "threshold_days": float(self._threshold_days),
                        "shares": float(pos.shares),
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                    },
                )
            )

        return results
