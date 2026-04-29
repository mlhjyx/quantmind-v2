"""NewPositionVolatilityRule — 新仓高波动告警 (MVP 3.1b Phase 1.5b, Session 44).

设计动机 (Session 44 真生产事件回放):
  卓然 (688121) entry 4-22 → 4-23 close 9.79 = -10.17%. SingleStockStopLoss L1
  在 -10% 触发, 但**已经亏 1 天**. 若有"新仓 7 天内 -5% 即告警"规则, 用户能在
  当天就收到 P1 钉钉, 提前 1 天介入.

  本规则补 SingleStockStopLossRule 的早期预警 gap — 静态阈值 (-10/-15/-20/-25)
  对买入即跌不够灵敏, 时间维度的"新仓宽容期"应更严格.

逻辑:
  触发条件 = (holding_days <= new_days) AND (loss_pct < -loss_threshold)
  - new_days 默认 7 (1 周建仓宽容期)
  - loss_threshold 默认 0.05 (5%, 比 SingleStock L1 -10% 更早)

  与 SingleStockStopLossRule 关系:
    - 7 天内 -5% → 本规则 (P1, 比 SingleStock L1 更早 + 更严格 condition)
    - 任意时间 -10% → SingleStockStopLoss L1 (P2)
    - 任意时间 -25% → SingleStockStopLoss L4 (P0)
    - 共存互补, 不冲突 (rule_id 不同 → dedup 独立 → 不会双告警同事件)

依赖 Phase 1.5a (PR #147):
  - 读 Position.entry_date (从 trade_log MIN(buy.trade_date) since last sell 派生)
  - entry_date is None → silent skip (无法判断"是否新仓")

关联铁律: 24 (单一职责: 仅"新仓+亏损"双 condition) / 31 (纯计算) / 33 (silent_ok skip)
"""
from __future__ import annotations

import logging
from typing import Final, Literal

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


_DEFAULT_NEW_DAYS_THRESHOLD: Final[int] = 7
_DEFAULT_LOSS_PCT_THRESHOLD: Final[float] = 0.05  # 5%


class NewPositionVolatilityRule(RiskRule):
    """新仓高波动告警 (买入即跌的早期预警, 与 SingleStockStopLoss 互补).

    触发: holding_days <= new_days AND loss_pct <= -loss_pct (符号: 亏损是负数).

    示例触发场景:
      4-22 entry @ 10.90, 4-23 close 9.79 → holding_days=1, loss_pct=-10.17%
        - 7 (new) ✓ AND -10.17 < -5% ✓ → P1 alert (1 天内即告警)
        SingleStockStopLossRule L1 同时触发 -10.17% < -10% → P2 alert
        两 rule 各发 1 钉钉 (rule_id 不同, dedup 独立, 不冲突)

    跳过条件:
      - entry_date is None (Phase 1.5a 缺数据, 无法判断"是否新仓")
      - shares <= 0 (已平仓)
      - entry_price <= 0 / current_price <= 0 (无法算 loss_pct)
      - holding_days > new_days (已不"新")
      - loss_pct >= -loss_threshold (跌幅未到阈值, 含浮盈)

    Args:
      new_days_threshold: 新仓判定窗口 (default 7 days)
      loss_pct_threshold: 亏损触发阈值 (positive value, default 0.05 = 5%)
    """

    rule_id: str = "new_position_volatility"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self,
        new_days_threshold: int = _DEFAULT_NEW_DAYS_THRESHOLD,
        loss_pct_threshold: float = _DEFAULT_LOSS_PCT_THRESHOLD,
    ) -> None:
        if new_days_threshold < 1:
            raise ValueError(
                f"NewPositionVolatilityRule new_days_threshold must be >= 1, "
                f"got {new_days_threshold}"
            )
        if loss_pct_threshold <= 0 or loss_pct_threshold > 1:
            raise ValueError(
                f"NewPositionVolatilityRule loss_pct_threshold must be in (0, 1], "
                f"got {loss_pct_threshold}"
            )
        self._new_days_threshold = new_days_threshold
        self._loss_pct_threshold = loss_pct_threshold

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        return self.rule_id if triggered_rule_id == self.rule_id else triggered_rule_id

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查每 position: (新仓 + 亏损 ≥ 阈值) 双条件命中触发."""
        results: list[RuleResult] = []
        today = context.timestamp.date()

        for pos in context.positions:
            # silent_ok: skip 路径 (无 entry_date / 已平仓 / 价格异常)
            if (pos.entry_date is None or pos.shares <= 0
                    or pos.entry_price <= 0 or pos.current_price <= 0):
                continue

            holding_days = (today - pos.entry_date).days
            if holding_days > self._new_days_threshold:
                # silent_ok: 已不"新仓" (惯例 7 天后由 SingleStockStopLoss 接管)
                continue

            loss_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            if loss_pct > -self._loss_pct_threshold:
                # silent_ok: 跌幅未到阈值 (含浮盈 / 轻度亏损)
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,  # alert_only
                    reason=(
                        f"NewPositionVolatility triggered: "
                        f"holding_days={holding_days} <= {self._new_days_threshold} "
                        f"AND loss_pct={loss_pct:.2%} <= -{self._loss_pct_threshold:.0%} "
                        f"(entry_date={pos.entry_date.isoformat()}, "
                        f"entry={pos.entry_price:.4f}, current={pos.current_price:.4f})"
                    ),
                    metrics={
                        "holding_days": float(holding_days),
                        "new_days_threshold": float(self._new_days_threshold),
                        "loss_pct": round(loss_pct, 6),
                        "loss_pct_threshold": self._loss_pct_threshold,
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "shares": float(pos.shares),
                    },
                )
            )

        return results
