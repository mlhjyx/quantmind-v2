"""L4ExecutionPlanner — STAGED 执行计划生成 + 状态机 (S8 sub-PR 8a).

V3 §7.1 STAGED 3 档:
  - OFF (default): 立即 CONFIRMED, 0 反向决策权
  - STAGED: PENDING_CONFIRM + 30min cancel 窗口 + 反向决策权
  - AUTO: 全自动 (保留, Crisis regime only)

ADR-027 §2.1:
  短期 default=OFF, STAGED_ENABLED=false
  长期 5 prerequisite 后 default=STAGED

State machine:
  PENDING_CONFIRM → CONFIRMED (user confirm / timeout)
  PENDING_CONFIRM → CANCELLED (user cancel)
  CONFIRMED → EXECUTED (broker wire success)
  CONFIRMED → FAILED (broker wire failure)
  Any → FAILED (system error)

铁律 31: 纯计算引擎, broker/DB 由上层注入. 本模块不 import broker_qmt / dingtalk_alert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from ..interface import RuleResult

logger = logging.getLogger(__name__)


class ExecutionMode(StrEnum):
    """L4 执行模式 (V3 §7.1)."""

    OFF = "OFF"  # 立即执行
    STAGED = "STAGED"  # 反向决策权, 30min cancel 窗口
    AUTO = "AUTO"  # 全自动 (Crisis regime, 保留)


class PlanStatus(StrEnum):
    """ExecutionPlan 状态 (V3 §7.5)."""

    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    TIMEOUT_EXECUTED = "TIMEOUT_EXECUTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


# Time window guardrails (ADR-027 §2.2)
_CANCEL_WINDOW_MINUTES: int = 30  # 默认
_CRITICAL_WINDOW_MIN_MINUTES: int = 2  # 集合竞价/尾盘下限
_LATE_SESSION_CUTOFF_HOUR: int = 14
_LATE_SESSION_CUTOFF_MINUTE: int = 55  # 14:55 final batch


@dataclass
class ExecutionPlan:
    """STAGED 执行计划 (V3 §7.5 输出 schema).

    由 L4ExecutionPlanner.generate_plan() 创建.
    不可变 — 状态变更通过 transition() 创建新实例.
    """

    plan_id: str  # UUID
    mode: ExecutionMode
    symbol_id: str
    action: str  # SELL/HOLD/BATCH
    qty: int
    limit_price: float | None
    batch_index: int
    batch_total: int
    scheduled_at: datetime
    cancel_deadline: datetime
    status: PlanStatus = PlanStatus.PENDING_CONFIRM
    user_decision: str | None = None
    user_decision_at: datetime | None = None
    triggered_by_event_id: int | None = None
    risk_reason: str = ""
    risk_metrics: dict[str, Any] = field(default_factory=dict)

    # ── State transitions ──

    def confirm(self, at: datetime | None = None) -> ExecutionPlan:
        """user 确认执行."""
        return self._transition(PlanStatus.CONFIRMED, "confirm", at)

    def cancel(self, at: datetime | None = None) -> ExecutionPlan:
        """user 取消."""
        return self._transition(PlanStatus.CANCELLED, "cancel", at)

    def timeout_execute(self, at: datetime | None = None) -> ExecutionPlan:
        """30min 超时 → 默认执行."""
        return self._transition(PlanStatus.TIMEOUT_EXECUTED, "timeout", at)

    def mark_executed(self, broker_order_id: str = "") -> ExecutionPlan:
        """broker wire 执行成功."""
        return ExecutionPlan(
            plan_id=self.plan_id,
            mode=self.mode,
            symbol_id=self.symbol_id,
            action=self.action,
            qty=self.qty,
            limit_price=self.limit_price,
            batch_index=self.batch_index,
            batch_total=self.batch_total,
            scheduled_at=self.scheduled_at,
            cancel_deadline=self.cancel_deadline,
            status=PlanStatus.EXECUTED,
            user_decision=self.user_decision,
            user_decision_at=self.user_decision_at,
            triggered_by_event_id=self.triggered_by_event_id,
            risk_reason=self.risk_reason,
            risk_metrics=self.risk_metrics,
        )

    def mark_failed(self, reason: str = "") -> ExecutionPlan:
        """broker wire 失败."""
        return ExecutionPlan(
            plan_id=self.plan_id,
            mode=self.mode,
            symbol_id=self.symbol_id,
            action=self.action,
            qty=self.qty,
            limit_price=self.limit_price,
            batch_index=self.batch_index,
            batch_total=self.batch_total,
            scheduled_at=self.scheduled_at,
            cancel_deadline=self.cancel_deadline,
            status=PlanStatus.FAILED,
            user_decision=self.user_decision,
            user_decision_at=self.user_decision_at,
            triggered_by_event_id=self.triggered_by_event_id,
            risk_reason=reason or self.risk_reason,
            risk_metrics=self.risk_metrics,
        )

    def is_expired(self, at: datetime | None = None) -> bool:
        """cancel_deadline 是否已过."""
        now = at or datetime.now(UTC)
        return now >= self.cancel_deadline

    def _transition(
        self,
        new_status: PlanStatus,
        decision: str,
        at: datetime | None = None,
    ) -> ExecutionPlan:
        now = at or datetime.now(UTC)
        return ExecutionPlan(
            plan_id=self.plan_id,
            mode=self.mode,
            symbol_id=self.symbol_id,
            action=self.action,
            qty=self.qty,
            limit_price=self.limit_price,
            batch_index=self.batch_index,
            batch_total=self.batch_total,
            scheduled_at=self.scheduled_at,
            cancel_deadline=self.cancel_deadline,
            status=new_status,
            user_decision=decision,
            user_decision_at=now,
            triggered_by_event_id=self.triggered_by_event_id,
            risk_reason=self.risk_reason,
            risk_metrics=self.risk_metrics,
        )


class L4ExecutionPlanner:
    """L4 执行计划生成器 (V3 §7.5).

    Pure computation (铁律 31): 不调 broker / 不发 DingTalk / 不写 DB.
    broker sell wire 和 notification 由上层注入.

    ADR-027 §2.1: 短期 default=OFF, STAGED_ENABLED=false.
    """

    # STAGED default enabled (ADR-027: short-term default=false)
    STAGED_ENABLED: bool = False

    def __init__(self, staged_enabled: bool = False) -> None:
        self._staged_enabled = staged_enabled

    # ── Main entry ──

    def generate_plan(
        self,
        result: RuleResult,
        *,
        mode: ExecutionMode | None = None,
        market_state: str = "calm",
        at: datetime | None = None,
    ) -> ExecutionPlan | None:
        """从 RuleResult 生成 ExecutionPlan.

        Args:
            result: L1 触发规则结果.
            mode: 执行模式. None → auto-detect: OFF default / STAGED if enabled.
            market_state: L3 market state (calm/stress/crisis). Crisis → AUTO candidate.
            at: 当前时间. None → UTC.now().

        Returns:
            ExecutionPlan (CONFIRMED if OFF, PENDING_CONFIRM if STAGED).
            None if result is not actionable (no code / shares=0 / bypass).
        """
        # Non-actionable rules
        if result.code == "" or result.shares == 0:
            return None

        # Determine mode
        if mode is None:
            mode = self._resolve_mode(market_state)

        now = at or datetime.now(UTC)
        deadline = self._compute_cancel_deadline(mode, now)

        # Create plan
        import uuid

        qty = result.shares if result.shares > 0 else 1

        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            mode=mode,
            symbol_id=result.code,
            action="SELL",
            qty=qty,
            limit_price=self._compute_limit_price(result),
            batch_index=1,
            batch_total=1,
            scheduled_at=now,
            cancel_deadline=deadline,
            status=(
                PlanStatus.PENDING_CONFIRM if mode == ExecutionMode.STAGED else PlanStatus.CONFIRMED
            ),
            triggered_by_event_id=None,
            risk_reason=result.reason,
            risk_metrics=result.metrics,
        )

        logger.info(
            "[L4-planner] plan_id=%s mode=%s symbol=%s qty=%d status=%s deadline=%s",
            plan.plan_id,
            plan.mode.value,
            plan.symbol_id,
            plan.qty,
            plan.status.value,
            plan.cancel_deadline.isoformat(),
        )
        return plan

    # ── Mode resolution ──

    def _resolve_mode(self, market_state: str) -> ExecutionMode:
        """Auto-detect execution mode.

        ADR-027 §2.1: STAGED_ENABLED=false → OFF default.
        Crisis regime → AUTO candidate (reserved for future).
        """
        if self._staged_enabled:
            if market_state == "crisis":
                # AUTO mode reserved — still STAGED for now
                return ExecutionMode.STAGED
            return ExecutionMode.STAGED
        return ExecutionMode.OFF

    # ── Cancel deadline (ADR-027 §2.2 guardrails) ──

    def _compute_cancel_deadline(self, mode: ExecutionMode, now: datetime) -> datetime:
        """计算 cancel_deadline.

        OFF mode: deadline = now (immediate, no window).
        STAGED mode: 30min window, with time-based guardrails.

        ADR-027 §2.2 5 guardrails:
          a. Normal (9:30-11:30 / 13:00-14:55): 30 min
          b. Auction (9:15-9:25): min(30min, remaining), floor 2min
          c. Late session (14:55-15:00): min(30min, remaining), floor 2min
          d. Cross-day: deadline > 14:55 → force 14:55 (FINAL clamp)
          e. User offline: default execute (caller responsibility)
        """
        if mode == ExecutionMode.OFF:
            return now  # immediate

        late_cutoff = now.replace(
            hour=_LATE_SESSION_CUTOFF_HOUR,
            minute=_LATE_SESSION_CUTOFF_MINUTE,
            second=0,
            microsecond=0,
        )

        # b. Auction window (9:15-9:25): adaptive first
        auction_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        auction_end = now.replace(hour=9, minute=25, second=0, microsecond=0)
        if auction_start <= now < auction_end:
            remaining = (auction_end - now).total_seconds() / 60
            window = max(
                _CRITICAL_WINDOW_MIN_MINUTES,
                min(_CANCEL_WINDOW_MINUTES, remaining),
            )
            return now + timedelta(minutes=window)

        # c. Late session (14:55-15:00): adaptive
        if now >= late_cutoff:
            remaining = (late_cutoff.replace(hour=15, minute=0) - now).total_seconds() / 60
            window = max(
                _CRITICAL_WINDOW_MIN_MINUTES,
                min(_CANCEL_WINDOW_MINUTES, remaining),
            )
            return now + timedelta(minutes=window)

        # a. Normal: default 30min
        deadline = now + timedelta(minutes=_CANCEL_WINDOW_MINUTES)

        # d. Cross-day guard: FINAL clamp, force ≤ 14:55
        if deadline > late_cutoff:
            deadline = late_cutoff

        return deadline

    # ── Limit price computation ──

    @staticmethod
    def _compute_limit_price(result: RuleResult) -> float | None:
        """Compute limit price = current_price * 0.98 (V3 §7.1: -2%)."""
        price = result.metrics.get("current_price")
        if price is not None and price > 0:
            return round(float(price) * 0.98, 4)
        return None

    # ── State machine sweep (for caller's periodic check) ──

    @staticmethod
    def check_timeout(plan: ExecutionPlan, at: datetime | None = None) -> bool:
        """检查 PENDING_CONFIRM plan 是否超时."""
        return plan.status == PlanStatus.PENDING_CONFIRM and plan.is_expired(at)

    @staticmethod
    def valid_transition(from_status: PlanStatus, to_status: PlanStatus) -> bool:
        """验证状态转换合法性."""
        _transitions: dict[PlanStatus, frozenset[PlanStatus]] = {
            PlanStatus.PENDING_CONFIRM: frozenset(
                {
                    PlanStatus.CONFIRMED,
                    PlanStatus.CANCELLED,
                    PlanStatus.TIMEOUT_EXECUTED,
                    PlanStatus.FAILED,
                }
            ),
            PlanStatus.CONFIRMED: frozenset(
                {
                    PlanStatus.EXECUTED,
                    PlanStatus.FAILED,
                }
            ),
            PlanStatus.CANCELLED: frozenset(),
            PlanStatus.TIMEOUT_EXECUTED: frozenset(
                {
                    PlanStatus.EXECUTED,
                    PlanStatus.FAILED,
                }
            ),
            PlanStatus.EXECUTED: frozenset(),
            PlanStatus.FAILED: frozenset(),
        }
        allowed = _transitions.get(from_status, frozenset())
        return to_status in allowed
