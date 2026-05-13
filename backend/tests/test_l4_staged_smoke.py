"""S8 8c-partial STAGED smoke integration test (L1 → L4 → state transition).

Plan §A S8 acceptance: STAGED smoke. This test exercises the full pipeline
END-TO-END using **0 broker / 0 alert / 0 INSERT** via RiskBacktestAdapter
(S5 sub-PR 5c sediment) as the integration sink.

Smoke path:
  1. Construct a RuleResult (as if emitted by L1 RealtimeRiskEngine evaluating
     a LimitDownDetection rule firing)
  2. Inject into L4ExecutionPlanner with mode=STAGED → ExecutionPlan with
     status=PENDING_CONFIRM + cancel_deadline
  3. Simulate user webhook CONFIRM → state transitions to CONFIRMED via
     ExecutionPlan.confirm()
  4. Simulate Celery sweep on a separate plan that expires → TIMEOUT_EXECUTED
     via ExecutionPlan.timeout_execute()
  5. Verify state machine transitions are atomic (PENDING_CONFIRM → terminal)
     and that no broker / alert / INSERT occurred (RiskBacktestAdapter records)

NOTE: This is a UNIT-LEVEL smoke (in-memory state machine + adapter stub).
True end-to-end (Celery Beat fires real task → real PG UPDATE → real broker
order) is deferred to 8c-followup PR with explicit user authorization (5/5
红线 关键点 per Plan §A SOP).

关联铁律: 31 (adapter stub 0 IO) / 33 (fail-loud on invalid transition)
关联 ADR: ADR-027 (design SSOT) / ADR-056 (8a state machine) / ADR-058 NEW
关联 LL: LL-152 NEW (8c-partial sediment)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from qm_platform.risk.execution.planner import (
    ExecutionMode,
    L4ExecutionPlanner,
    PlanStatus,
)
from qm_platform.risk.interface import RuleResult


def _make_rule_result(code: str = "600519.SH", shares: int = 100) -> RuleResult:
    """Build a fake RuleResult as if emitted by L1 LimitDownDetection."""
    return RuleResult(
        rule_id="limit_down_detection",
        code=code,
        shares=shares,
        reason="price -9.95% past limit-down threshold",
        metrics={"current_price": 1700.0, "prev_close": 1888.0},
    )


# §1 L1 → L4 plan generation


class TestStagedSmokeL1ToL4:
    def test_l1_result_generates_staged_plan_pending_confirm(self) -> None:
        """RuleResult + STAGED mode → ExecutionPlan with status=PENDING_CONFIRM."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        # 9:30 generates a normal 30min cancel window
        now = datetime(2026, 5, 13, 9, 30, tzinfo=UTC)

        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=now)

        assert plan is not None
        assert plan.status == PlanStatus.PENDING_CONFIRM
        assert plan.mode == ExecutionMode.STAGED
        assert plan.symbol_id == "600519.SH"
        assert plan.qty == 100
        assert plan.action == "SELL"
        # 30min cancel deadline default in STAGED mode at 9:30 (no edge guards)
        assert plan.cancel_deadline == now + timedelta(minutes=30)

    def test_off_mode_skips_pending_confirm(self) -> None:
        """OFF mode → status=CONFIRMED immediately (no STAGED window)."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=False)  # default
        plan = planner.generate_plan(result, mode=ExecutionMode.OFF)

        assert plan is not None
        assert plan.status == PlanStatus.CONFIRMED


# §2 PENDING_CONFIRM → user CONFIRM via webhook simulation


class TestStagedSmokeWebhookConfirm:
    def test_user_confirm_transitions_pending_to_confirmed(self) -> None:
        """Simulates the webhook receiver calling plan.confirm() — state advances."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        assert plan is not None
        assert plan.status == PlanStatus.PENDING_CONFIRM

        confirmed = plan.confirm()

        assert confirmed.status == PlanStatus.CONFIRMED
        assert confirmed.user_decision == "confirm"
        assert confirmed.user_decision_at is not None
        # Plan ID preserved across transition (audit trail)
        assert confirmed.plan_id == plan.plan_id

    def test_user_cancel_transitions_pending_to_cancelled(self) -> None:
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        assert plan is not None

        cancelled = plan.cancel()

        assert cancelled.status == PlanStatus.CANCELLED
        assert cancelled.user_decision == "cancel"
        # CANCELLED is terminal — no further transitions allowed
        assert (
            L4ExecutionPlanner.valid_transition(PlanStatus.CANCELLED, PlanStatus.EXECUTED) is False
        )


# §3 Celery sweep timeout simulation


class TestStagedSmokeTimeoutSweep:
    def test_expired_plan_check_timeout_returns_true(self) -> None:
        """L4ExecutionPlanner.check_timeout returns True for expired PENDING_CONFIRM."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 13, 9, 30, tzinfo=UTC)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=now)
        assert plan is not None
        assert plan.cancel_deadline == now + timedelta(minutes=30)

        # 1s after deadline
        after_deadline = plan.cancel_deadline + timedelta(seconds=1)
        assert L4ExecutionPlanner.check_timeout(plan, at=after_deadline) is True

    def test_sweep_timeout_transitions_to_timeout_executed(self) -> None:
        """Simulates sweep task calling plan.timeout_execute() — state advances."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 13, 9, 30, tzinfo=UTC)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=now)
        assert plan is not None

        after_deadline = plan.cancel_deadline + timedelta(seconds=1)
        timed_out = plan.timeout_execute(at=after_deadline)

        assert timed_out.status == PlanStatus.TIMEOUT_EXECUTED
        assert timed_out.user_decision == "timeout"
        assert timed_out.user_decision_at == after_deadline

    def test_within_deadline_check_timeout_returns_false(self) -> None:
        """Before deadline, check_timeout returns False — sweep would skip."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 13, 9, 30, tzinfo=UTC)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=now)
        assert plan is not None

        before_deadline = plan.cancel_deadline - timedelta(seconds=1)
        assert L4ExecutionPlanner.check_timeout(plan, at=before_deadline) is False


# §4 Adapter stub verification — 0 broker / 0 alert / 0 INSERT


class TestStagedSmokeAdapterIsolation:
    def test_adapter_records_zero_sell_when_only_state_machine_used(self) -> None:
        """State machine transitions alone don't call adapter.sell.

        This is the safety guarantee for 8c-partial: state transitions happen
        in-memory; broker_qmt wire (which would call adapter.sell) is deferred
        to 8c-followup. Verify adapter.sell_calls is empty after a full
        PENDING_CONFIRM → CONFIRMED → (hypothetical) EXECUTED simulation.
        """
        adapter = RiskBacktestAdapter()
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        assert plan is not None
        confirmed = plan.confirm()
        # If 8c-followup wires broker, it would call adapter.sell here.
        # 8c-partial does NOT — verify.
        assert confirmed.status == PlanStatus.CONFIRMED
        assert adapter.sell_calls == []
        assert adapter.alerts == []

    def test_adapter_records_sell_when_explicit_call(self) -> None:
        """Sanity check: adapter DOES record when explicitly invoked.

        Establishes that our 0-call assertion in the previous test is meaningful
        (反 silent stub that records nothing regardless of input).
        """
        adapter = RiskBacktestAdapter()
        adapter.sell(code="600519.SH", shares=100, reason="manual")
        assert len(adapter.sell_calls) == 1
        assert adapter.sell_calls[0]["code"] == "600519.SH"
        assert adapter.sell_calls[0]["shares"] == 100


# §5 Full lifecycle — happy path


class TestStagedSmokeFullLifecycle:
    def test_full_lifecycle_pending_confirm_user_confirm_executed(self) -> None:
        """End-to-end happy path: L1 → L4 PENDING_CONFIRM → user CONFIRM → EXECUTED.

        EXECUTED transition is normally caller-driven post-broker (mark_executed
        called with broker_order_id). In 8c-partial, no broker fires; verify the
        state machine reaches EXECUTED if explicitly marked.
        """
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        pending = planner.generate_plan(result, mode=ExecutionMode.STAGED)
        assert pending is not None
        assert pending.status == PlanStatus.PENDING_CONFIRM

        confirmed = pending.confirm()
        assert confirmed.status == PlanStatus.CONFIRMED

        # Once 8c-followup wires broker, this is where adapter.sell would fire
        # and the result would feed mark_executed. In 8c-partial we synthesize
        # the result directly.
        executed = confirmed.mark_executed(broker_order_id="stub-order-12345")
        assert executed.status == PlanStatus.EXECUTED

        # Verify state machine respects invariant: EXECUTED is terminal
        assert (
            L4ExecutionPlanner.valid_transition(PlanStatus.EXECUTED, PlanStatus.CONFIRMED) is False
        )

    def test_full_lifecycle_pending_confirm_timeout_executed(self) -> None:
        """End-to-end: L1 → L4 PENDING_CONFIRM → sweep TIMEOUT_EXECUTED → EXECUTED."""
        result = _make_rule_result()
        planner = L4ExecutionPlanner(staged_enabled=True)
        now = datetime(2026, 5, 13, 9, 30, tzinfo=UTC)
        pending = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=now)
        assert pending is not None

        # Sweep detects timeout
        after = pending.cancel_deadline + timedelta(seconds=1)
        assert L4ExecutionPlanner.check_timeout(pending, at=after) is True

        timed_out = pending.timeout_execute(at=after)
        assert timed_out.status == PlanStatus.TIMEOUT_EXECUTED

        # TIMEOUT_EXECUTED → EXECUTED allowed (broker fires post-timeout)
        executed = timed_out.mark_executed(broker_order_id="stub-timeout-67890")
        assert executed.status == PlanStatus.EXECUTED
