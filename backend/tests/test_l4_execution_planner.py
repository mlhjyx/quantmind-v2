"""Unit tests for L4ExecutionPlanner + ExecutionPlan state machine (S8 sub-PR 8a).

覆盖:
  - ExecutionPlan: 创建, 状态转换 (confirm/cancel/timeout/mark_executed/mark_failed)
  - L4ExecutionPlanner: generate_plan OFF/STAGED modes
  - Cancel deadline: normal / auction / late session / cross-day guardrails
  - State transition validation
  - Timeout check
  - Non-actionable results (空 code / 0 shares)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.qm_platform.risk import RuleResult
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    ExecutionPlan,
    L4ExecutionPlanner,
    PlanStatus,
)


def _make_result(
    rule_id: str = "limit_down_detection",
    code: str = "600519.SH",
    shares: int = 1000,
    price: float = 100.0,
    reason: str = "test",
    metrics: dict | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        code=code,
        shares=shares,
        reason=reason,
        metrics=metrics or {"current_price": price, "drop_pct": -0.10},
    )


# ── ExecutionPlan state machine ──


class TestExecutionPlan:
    def _make_plan(self, **kwargs) -> ExecutionPlan:
        defaults = {
            "plan_id": "test-001",
            "mode": ExecutionMode.STAGED,
            "symbol_id": "600519.SH",
            "action": "SELL",
            "qty": 1000,
            "limit_price": 98.0,
            "batch_index": 1,
            "batch_total": 1,
            "scheduled_at": datetime.now(UTC),
            "cancel_deadline": datetime.now(UTC) + timedelta(minutes=30),
            "status": PlanStatus.PENDING_CONFIRM,
        }
        defaults.update(kwargs)
        return ExecutionPlan(**defaults)

    def test_confirm_transition(self):
        plan = self._make_plan()
        result = plan.confirm()
        assert result.status == PlanStatus.CONFIRMED
        assert result.user_decision == "confirm"
        assert result.user_decision_at is not None

    def test_cancel_transition(self):
        plan = self._make_plan()
        result = plan.cancel()
        assert result.status == PlanStatus.CANCELLED
        assert result.user_decision == "cancel"

    def test_timeout_transition(self):
        plan = self._make_plan()
        result = plan.timeout_execute()
        assert result.status == PlanStatus.TIMEOUT_EXECUTED
        assert result.user_decision == "timeout"

    def test_mark_executed(self):
        plan = self._make_plan(status=PlanStatus.CONFIRMED)
        result = plan.mark_executed("ord-123")
        assert result.status == PlanStatus.EXECUTED

    def test_mark_failed(self):
        plan = self._make_plan(status=PlanStatus.CONFIRMED)
        result = plan.mark_failed("broker connection error")
        assert result.status == PlanStatus.FAILED
        assert "broker connection error" in result.risk_reason

    def test_immutable_original(self):
        """状态转换返回新实例, 原 plan 不变."""
        plan = self._make_plan()
        confirmed = plan.confirm()
        assert plan.status == PlanStatus.PENDING_CONFIRM
        assert confirmed.status == PlanStatus.CONFIRMED

    def test_is_expired(self):
        past = datetime.now(UTC) - timedelta(minutes=1)
        plan = self._make_plan(cancel_deadline=past)
        assert plan.is_expired()

    def test_is_not_expired(self):
        future = datetime.now(UTC) + timedelta(minutes=30)
        plan = self._make_plan(cancel_deadline=future)
        assert not plan.is_expired()

    def test_is_expired_at_boundary(self):
        now = datetime.now(UTC)
        plan = self._make_plan(cancel_deadline=now)
        assert plan.is_expired(at=now)

    def test_transition_preserves_fields(self):
        """状态转换保留 plan_id, symbol, qty 等."""
        plan = self._make_plan()
        result = plan.confirm()
        assert result.plan_id == plan.plan_id
        assert result.symbol_id == plan.symbol_id
        assert result.qty == plan.qty
        assert result.mode == plan.mode


# ── L4ExecutionPlanner ──


class TestL4PlannerGeneratePlan:
    def test_off_mode_creates_confirmed_plan(self):
        """OFF mode → plan 直接 CONFIRMED."""
        planner = L4ExecutionPlanner(staged_enabled=False)
        result = _make_result()
        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)

        assert plan is not None
        assert plan.mode == ExecutionMode.OFF
        assert plan.status == PlanStatus.CONFIRMED
        assert plan.symbol_id == "600519.SH"
        assert plan.qty == 1000

    def test_staged_mode_creates_pending_plan(self):
        """STAGED mode → PENDING_CONFIRM."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        result = _make_result()
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)

        assert plan is not None
        assert plan.mode == ExecutionMode.STAGED
        assert plan.status == PlanStatus.PENDING_CONFIRM

    def test_default_mode_respects_staged_enabled(self):
        """mode=None + STAGED_ENABLED=True → STAGED."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        plan = planner.generate_plan(_make_result())
        assert plan.mode == ExecutionMode.STAGED

    def test_default_mode_off_when_disabled(self):
        """mode=None + STAGED_ENABLED=False → OFF (ADR-027 短期)."""
        planner = L4ExecutionPlanner(staged_enabled=False)
        plan = planner.generate_plan(_make_result())
        assert plan.mode == ExecutionMode.OFF

    def test_empty_code_returns_none(self):
        """空 code (行业级规则) → 不生成 plan."""
        planner = L4ExecutionPlanner()
        result = _make_result(code="", shares=0)
        assert planner.generate_plan(result) is None

    def test_zero_shares_returns_none(self):
        """shares=0 → 不生成 plan (alert_only 规则)."""
        planner = L4ExecutionPlanner()
        result = _make_result(shares=0)
        assert planner.generate_plan(result) is None

    def test_limit_price_computed(self):
        planner = L4ExecutionPlanner()
        result = _make_result(price=100.0)
        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)
        assert plan.limit_price == pytest.approx(98.0)  # -2%

    def test_limit_price_none_when_no_price(self):
        planner = L4ExecutionPlanner()
        # Pass metrics without current_price (empty dict is falsy in _make_result default)
        result = _make_result(metrics={"drop_pct": -0.10})
        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)
        assert plan.limit_price is None

    def test_risk_reason_and_metrics_preserved(self):
        planner = L4ExecutionPlanner()
        result = _make_result(
            reason="LimitDown: 600519.SH 跌停",
            metrics={"current_price": 90.0, "drop_pct": -0.10},
        )
        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)
        assert "LimitDown" in plan.risk_reason
        assert plan.risk_metrics["drop_pct"] == -0.10

    def test_unique_plan_id(self):
        planner = L4ExecutionPlanner()
        p1 = planner.generate_plan(_make_result(code="A"), mode=ExecutionMode.OFF)
        p2 = planner.generate_plan(_make_result(code="B"), mode=ExecutionMode.OFF)
        assert p1.plan_id != p2.plan_id


# ── Cancel deadline guardrails (ADR-027 §2.2) ──


class TestCancelDeadline:
    def test_normal_window_30min(self):
        """9:30-11:30 → 30min window."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.STAGED,
            at=now,
        )
        expected_deadline = now + timedelta(minutes=30)
        assert plan.cancel_deadline == expected_deadline

    def test_auction_adaptive_window(self):
        """9:20 (集合竞价中) → adaptive: min(30, 5min remaining) = 5min."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 11, 9, 20, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.STAGED,
            at=now,
        )
        # 9:20 + 5min = 9:25 (auction end)
        expected = now + timedelta(minutes=5)
        assert plan.cancel_deadline == expected

    def test_auction_near_end_floor_2min(self):
        """9:24 (仅剩 1min) → floor 2min."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 11, 9, 24, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.STAGED,
            at=now,
        )
        # remaining < 2min → floor 2min
        expected = now + timedelta(minutes=2)
        assert plan.cancel_deadline == expected

    def test_late_session_adaptive(self):
        """14:56 (尾盘) → adaptive: remaining=4min > floor 2min → 15:00."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 11, 14, 56, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.STAGED,
            at=now,
        )
        # 14:56 + 4min (remaining to 15:00) = 15:00
        assert plan.cancel_deadline.hour == 15
        assert plan.cancel_deadline.minute == 0

    def test_cross_day_guard_force_1455(self):
        """14:40 → 14:40+30=15:10 > 14:55 cutoff → force 14:55 (跨日 guard)."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 11, 14, 40, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.STAGED,
            at=now,
        )
        # 14:40 + 30min = 15:10 > 14:55 → cross-day clamp to 14:55
        assert plan.cancel_deadline.hour == 14
        assert plan.cancel_deadline.minute == 55

    def test_off_mode_immediate_deadline(self):
        """OFF mode → deadline = now (immediate)."""
        planner = L4ExecutionPlanner()
        now = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
        plan = planner.generate_plan(
            _make_result(),
            mode=ExecutionMode.OFF,
            at=now,
        )
        assert plan.cancel_deadline == now

    def test_market_state_crisis_stays_staged(self):
        """Crisis regime → still STAGED (AUTO reserved)."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        plan = planner.generate_plan(
            _make_result(),
            market_state="crisis",
        )
        assert plan.mode == ExecutionMode.STAGED  # AUTO reserved


# ── State transition validation ──


class TestValidTransition:
    def test_pending_to_confirmed_valid(self):
        assert L4ExecutionPlanner.valid_transition(PlanStatus.PENDING_CONFIRM, PlanStatus.CONFIRMED)

    def test_pending_to_executed_invalid(self):
        """PENDING → EXECUTED 不能跳过 CONFIRMED."""
        assert not L4ExecutionPlanner.valid_transition(
            PlanStatus.PENDING_CONFIRM, PlanStatus.EXECUTED
        )

    def test_confirmed_to_executed_valid(self):
        assert L4ExecutionPlanner.valid_transition(PlanStatus.CONFIRMED, PlanStatus.EXECUTED)

    def test_confirmed_to_cancelled_invalid(self):
        """已确认不能取消."""
        assert not L4ExecutionPlanner.valid_transition(PlanStatus.CONFIRMED, PlanStatus.CANCELLED)

    def test_executed_no_further_transitions(self):
        assert not L4ExecutionPlanner.valid_transition(PlanStatus.EXECUTED, PlanStatus.CONFIRMED)
        assert not L4ExecutionPlanner.valid_transition(PlanStatus.EXECUTED, PlanStatus.CANCELLED)

    def test_failed_no_further_transitions(self):
        assert not L4ExecutionPlanner.valid_transition(PlanStatus.FAILED, PlanStatus.CONFIRMED)


# ── Timeout check ──


class TestTimeoutCheck:
    def test_pending_and_expired_triggers_timeout(self):
        now = datetime.now(UTC)
        plan = ExecutionPlan(
            plan_id="t",
            mode=ExecutionMode.STAGED,
            symbol_id="600519.SH",
            action="SELL",
            qty=1000,
            limit_price=98.0,
            batch_index=1,
            batch_total=1,
            scheduled_at=now,
            cancel_deadline=now - timedelta(minutes=1),
            status=PlanStatus.PENDING_CONFIRM,
        )
        assert L4ExecutionPlanner.check_timeout(plan, at=now)

    def test_pending_not_expired_no_timeout(self):
        now = datetime.now(UTC)
        plan = ExecutionPlan(
            plan_id="t",
            mode=ExecutionMode.STAGED,
            symbol_id="600519.SH",
            action="SELL",
            qty=1000,
            limit_price=98.0,
            batch_index=1,
            batch_total=1,
            scheduled_at=now,
            cancel_deadline=now + timedelta(minutes=30),
            status=PlanStatus.PENDING_CONFIRM,
        )
        assert not L4ExecutionPlanner.check_timeout(plan, at=now)

    def test_confirmed_not_trigger_timeout(self):
        """已确认的 plan 不会 timeout."""
        now = datetime.now(UTC)
        plan = ExecutionPlan(
            plan_id="t",
            mode=ExecutionMode.STAGED,
            symbol_id="600519.SH",
            action="SELL",
            qty=1000,
            limit_price=98.0,
            batch_index=1,
            batch_total=1,
            scheduled_at=now,
            cancel_deadline=now - timedelta(minutes=1),
            status=PlanStatus.CONFIRMED,
        )
        assert not L4ExecutionPlanner.check_timeout(plan, at=now)


# ── End-to-end STAGED flow ──


class TestStagedFlow:
    def test_full_staged_lifecycle(self):
        """完整 STAGED 生命周期: trigger → pending → timeout → executed."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        result = _make_result(code="600519.SH", shares=1000, price=100.0)

        # 1. Trigger → plan created
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        assert plan.status == PlanStatus.PENDING_CONFIRM

        # 2. Timeout → default execute
        expired = planner.check_timeout(plan, at=plan.cancel_deadline + timedelta(seconds=1))
        assert expired

        executed = plan.timeout_execute()
        assert executed.status == PlanStatus.TIMEOUT_EXECUTED

        # 3. Broker wire → executed
        done = executed.mark_executed("ord-456")
        assert done.status == PlanStatus.EXECUTED

    def test_user_cancel_flow(self):
        """user 主动取消."""
        planner = L4ExecutionPlanner(staged_enabled=True)
        result = _make_result()

        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        cancelled = plan.cancel()
        assert cancelled.status == PlanStatus.CANCELLED
        assert cancelled.user_decision == "cancel"

    def test_off_mode_immediate_flow(self):
        """OFF mode → 立即 CONFIRMED → EXECUTED."""
        planner = L4ExecutionPlanner()
        result = _make_result()

        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)
        assert plan.status == PlanStatus.CONFIRMED  # immediate

        executed = plan.mark_executed("ord-789")
        assert executed.status == PlanStatus.EXECUTED
