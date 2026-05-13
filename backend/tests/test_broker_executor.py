"""Unit tests for broker_executor PURE engine (S8 8c-followup).

覆盖:
  - execute_plan_sell: SUCCESS path (stub_sell_ok / ok / filled / partial_filled)
  - execute_plan_sell: FAILURE path (rejected / error / broker raises)
  - Defensive: plan.status not in {CONFIRMED, TIMEOUT_EXECUTED} → ValueError
  - broker_order_id resolution: explicit / None → "stub-<prefix>"
  - filled_shares + fill_price extraction
  - new_plan.status reflects success/failure (EXECUTED / FAILED)
  - timeout argument propagated to broker_call

铁律 31 sustained: 0 broker import in tests — broker is a mock callable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.qm_platform.risk.execution.broker_executor import (
    DEFAULT_BROKER_TIMEOUT_SEC,
    BrokerExecutionResult,
    execute_plan_sell,
)
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    ExecutionPlan,
    PlanStatus,
)


def _make_plan(
    *,
    status: PlanStatus = PlanStatus.CONFIRMED,
    plan_id: str = "abc12345-0000-0000-0000-000000000001",
    symbol_id: str = "600519.SH",
    qty: int = 1000,
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=plan_id,
        mode=ExecutionMode.STAGED,
        symbol_id=symbol_id,
        action="SELL",
        qty=qty,
        limit_price=98.0,
        batch_index=1,
        batch_total=1,
        scheduled_at=datetime.now(UTC),
        cancel_deadline=datetime.now(UTC) + timedelta(minutes=30),
        status=status,
    )


class _RecordingBroker:
    """Minimal recording broker callable matching BrokerCallable signature."""

    def __init__(self, result: dict[str, Any] | None = None, raises: Exception | None = None):
        self._result = result
        self._raises = raises
        self.calls: list[tuple[str, int, str, float]] = []

    def __call__(self, code: str, shares: int, reason: str, timeout: float) -> dict[str, Any]:
        self.calls.append((code, shares, reason, timeout))
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


# ── SUCCESS path ──


class TestExecuteSellSuccess:
    def test_stub_sell_ok_status(self):
        broker = _RecordingBroker(
            result={
                "status": "stub_sell_ok",
                "code": "600519.SH",
                "shares": 1000,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": None,
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert isinstance(result, BrokerExecutionResult)
        assert result.success is True
        # stub order_id synthesized
        assert result.order_id == "stub-abc12345"
        assert result.filled_shares == 0
        assert result.error_msg is None
        assert result.new_plan.status == PlanStatus.EXECUTED

    def test_ok_status_with_explicit_order_id(self):
        broker = _RecordingBroker(
            result={
                "status": "ok",
                "code": "600519.SH",
                "shares": 1000,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": "98765",
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is True
        assert result.order_id == "98765"
        assert result.new_plan.status == PlanStatus.EXECUTED

    def test_filled_status_with_fill_data(self):
        broker = _RecordingBroker(
            result={
                "status": "filled",
                "code": "600519.SH",
                "shares": 1000,
                "filled_shares": 1000,
                "price": 99.50,
                "order_id": "ABC-001",
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is True
        assert result.order_id == "ABC-001"
        assert result.filled_shares == 1000
        assert result.fill_price == pytest.approx(99.50)
        assert result.new_plan.status == PlanStatus.EXECUTED

    def test_partial_filled_status_counts_success(self):
        broker = _RecordingBroker(
            result={
                "status": "partial_filled",
                "code": "600519.SH",
                "shares": 1000,
                "filled_shares": 400,
                "price": 99.50,
                "order_id": "X-PART",
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        # Broker accepted (filled some) — counts as success in this layer.
        assert result.success is True
        assert result.filled_shares == 400

    def test_timeout_executed_status_executable(self):
        """TIMEOUT_EXECUTED plans (post Celery sweep) are executable."""
        broker = _RecordingBroker(result={"status": "ok", "order_id": "T-001"})
        plan = _make_plan(status=PlanStatus.TIMEOUT_EXECUTED)
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is True
        assert result.new_plan.status == PlanStatus.EXECUTED


# ── FAILURE path ──


class TestExecuteSellFailure:
    def test_rejected_status(self):
        broker = _RecordingBroker(
            result={
                "status": "rejected",
                "code": "600519.SH",
                "shares": 1000,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": None,
                "error": "live_trading_disabled",
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is False
        assert result.order_id is None
        assert result.filled_shares == 0
        assert "live_trading_disabled" in (result.error_msg or "")
        assert result.new_plan.status == PlanStatus.FAILED

    def test_error_status_with_message(self):
        broker = _RecordingBroker(
            result={
                "status": "error",
                "error": "connection_refused",
            }
        )
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is False
        assert "connection_refused" in (result.error_msg or "")
        assert result.new_plan.status == PlanStatus.FAILED

    def test_unknown_status_treated_as_failure(self):
        broker = _RecordingBroker(result={"status": "weird_unknown_status"})
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is False
        # Error msg references the unknown status for debugging
        assert "weird_unknown_status" in (result.error_msg or "")

    def test_broker_raises_propagates_as_failure(self):
        """Broker exception is captured + returned as FAILED result (反 silent)."""
        broker = _RecordingBroker(raises=RuntimeError("xtquant not loaded"))
        plan = _make_plan()
        result = execute_plan_sell(plan=plan, broker_call=broker)
        assert result.success is False
        assert "RuntimeError" in (result.error_msg or "")
        assert "xtquant not loaded" in (result.error_msg or "")
        assert result.new_plan.status == PlanStatus.FAILED


# ── Defensive ──


class TestDefensive:
    @pytest.mark.parametrize(
        "bad_status",
        [
            PlanStatus.PENDING_CONFIRM,
            PlanStatus.CANCELLED,
            PlanStatus.EXECUTED,
            PlanStatus.FAILED,
        ],
    )
    def test_non_executable_status_raises_value_error(self, bad_status: PlanStatus):
        broker = _RecordingBroker(result={"status": "ok"})
        plan = _make_plan(status=bad_status)
        with pytest.raises(ValueError, match="not executable"):
            execute_plan_sell(plan=plan, broker_call=broker)

    def test_default_timeout_propagated(self):
        broker = _RecordingBroker(result={"status": "ok"})
        plan = _make_plan()
        execute_plan_sell(plan=plan, broker_call=broker)
        assert len(broker.calls) == 1
        _, _, _, called_timeout = broker.calls[0]
        assert called_timeout == DEFAULT_BROKER_TIMEOUT_SEC

    def test_explicit_timeout_propagated(self):
        broker = _RecordingBroker(result={"status": "ok"})
        plan = _make_plan()
        execute_plan_sell(plan=plan, broker_call=broker, timeout=12.5)
        assert broker.calls[0][3] == 12.5

    def test_reason_includes_plan_id_prefix(self):
        broker = _RecordingBroker(result={"status": "ok"})
        plan = _make_plan(plan_id="abcdef01-0000-0000-0000-000000000099")
        execute_plan_sell(plan=plan, broker_call=broker)
        _, _, called_reason, _ = broker.calls[0]
        # Audit trail: reason includes l4_ prefix + first 8 chars of plan_id
        assert called_reason == "l4_abcdef01"

    def test_symbol_and_qty_propagated_to_broker(self):
        broker = _RecordingBroker(result={"status": "ok"})
        plan = _make_plan(symbol_id="000001.SZ", qty=500)
        execute_plan_sell(plan=plan, broker_call=broker)
        called_code, called_shares, _, _ = broker.calls[0]
        assert called_code == "000001.SZ"
        assert called_shares == 500
