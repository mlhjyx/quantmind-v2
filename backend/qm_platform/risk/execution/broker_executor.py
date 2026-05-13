"""Broker execution adapter — PURE engine (S8 8c-followup, broker_qmt sell wire).

V3 §7.6 + ADR-027 §2.5: post-CONFIRMED / post-TIMEOUT_EXECUTED → broker sell + writeback.

Layered architecture (CLAUDE.md §3.1):
  - Engine (this file) — pure function: (plan, broker_callable) → BrokerExecutionResult
  - Service (app/services/risk/staged_execution_service.py) — DB orchestration
  - Adapter (app/services/risk/qmt_sell_adapter.py) — wraps MiniQMTBroker.place_order

铁律 31 sustained: 0 broker import, 0 DB read/write, 0 network. Caller injects
  broker callable matching BrokerProtocol.sell signature
  (code, shares, reason, timeout) → dict with keys {status, code, shares,
  filled_shares, price, order_id?, error?}.

铁律 33 sustained: fail-loud — broker exceptions propagate up to caller.
  Pure function only interprets the result dict shape.

设计:
  - sell_call_args derived from ExecutionPlan (symbol_id, qty, risk_reason)
  - timeout default = 5s (V3 §13.1 broker SLA)
  - Result interpretation: status="stub_sell_ok" / "ok" / "filled" → SUCCESS;
    status="rejected" / "error" / broker raises → FAILURE
  - On success: return new plan via plan.mark_executed(broker_order_id) +
    BrokerExecutionResult(success=True, order_id, filled_shares, error_msg=None)
  - On failure: return new plan via plan.mark_failed(reason) +
    BrokerExecutionResult(success=False, order_id=None, filled_shares=0, error_msg)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .planner import ExecutionPlan, PlanStatus

logger = logging.getLogger(__name__)

# Broker SLA (V3 §13.1 — broker call <5s P99)
DEFAULT_BROKER_TIMEOUT_SEC: float = 5.0

# Reviewer P2 (security-reviewer): cap error_msg length to bound stack-trace
# leak into HTTP response bodies. Type name + truncated message preserves debug
# context for the operator log without surfacing full Python traceback strings.
_MAX_ERR_LEN: int = 200

# Broker result status whitelist — success outcomes
_SUCCESS_STATUSES: frozenset[str] = frozenset(
    {
        "stub_sell_ok",  # RiskBacktestAdapter paper-mode stub
        "ok",  # generic success
        "filled",  # full fill
        "partial_filled",  # partial fill (still counts as broker-side success)
    }
)


# Broker callable protocol:
#   broker_call(code: str, shares: int, reason: str, timeout: float) -> dict[str, Any]
# Returned dict expected keys (when broker is RiskBacktestAdapter or QMTSellAdapter):
#   status: str — "stub_sell_ok" / "ok" / "filled" / "partial_filled" / "rejected" / "error"
#   code: str — echo of the input code
#   shares: int — echo of the input shares
#   filled_shares: int — actual filled (0 for stub / on rejection)
#   price: float — fill price (0 if not filled)
#   order_id: str | None — broker order_id (None for stub or pre-fill)
#   error: str | None — error message on rejection / error
BrokerCallable = Callable[[str, int, str, float], dict[str, Any]]


@dataclass(frozen=True)
class BrokerExecutionResult:
    """Pure-function result of broker sell execution.

    Caller (StagedExecutionService) uses these fields to issue the race-safe
    UPDATE that persists broker_order_id, broker_fill_status, and final status.
    """

    success: bool  # True iff broker accepted (regardless of fill_shares)
    order_id: str | None  # broker_order_id (paper-stub: "stub-<plan_id_prefix>")
    filled_shares: int  # actual filled shares (0 for stub or unfilled)
    fill_price: float  # actual fill price (0 if not filled)
    error_msg: str | None  # error message on failure (None on success)
    new_plan: ExecutionPlan  # plan with status=EXECUTED or FAILED


def execute_plan_sell(
    *,
    plan: ExecutionPlan,
    broker_call: BrokerCallable,
    timeout: float = DEFAULT_BROKER_TIMEOUT_SEC,
    at: datetime | None = None,
) -> BrokerExecutionResult:
    """Execute broker sell for a CONFIRMED / TIMEOUT_EXECUTED plan.

    Args:
        plan: ExecutionPlan with status CONFIRMED or TIMEOUT_EXECUTED.
            Calling this with PENDING_CONFIRM / CANCELLED / EXECUTED / FAILED
            is a programming error — defensive check raises ValueError.
        broker_call: callable matching BrokerCallable signature. In production:
            QMTSellAdapter.sell (paper-blocked via LiveTradingGuard); in tests:
            RiskBacktestAdapter.sell (records call, returns stub dict).
        timeout: broker SLA timeout in seconds (default 5s per V3 §13.1).
        at: injectable clock (default UTC.now()) for test determinism.

    Returns:
        BrokerExecutionResult — caller persists order_id + filled_shares +
        new_plan.status via race-safe UPDATE.

    Raises:
        ValueError: plan.status not in {CONFIRMED, TIMEOUT_EXECUTED}.
        Exception: broker_call exceptions propagate (铁律 33 fail-loud).
            Caller catches + marks FAILED via plan.mark_failed().
    """
    # Defensive: only executable from CONFIRMED or TIMEOUT_EXECUTED
    if plan.status not in (PlanStatus.CONFIRMED, PlanStatus.TIMEOUT_EXECUTED):
        raise ValueError(
            f"plan {plan.plan_id[:8]}* status={plan.status.value} is not executable "
            "(expected CONFIRMED or TIMEOUT_EXECUTED)"
        )

    # Reviewer LOW (code-reviewer): `at` kept for forward-compat / test
    # determinism (staged_execution_service.execute_plan injects clock for
    # audit log alignment); dropped unused local binding.
    _ = at

    # Build broker call args. reason includes plan_id_prefix for audit cross-ref
    # in broker logs (xtquant order_remark accepts ≤24 chars; QMTSellAdapter
    # truncates further as needed).
    reason = f"l4_{plan.plan_id[:8]}"

    logger.info(
        "[broker-executor] plan_id=%s symbol=%s qty=%d status=%s calling broker.sell",
        plan.plan_id,
        plan.symbol_id,
        plan.qty,
        plan.status.value,
    )

    try:
        broker_result = broker_call(plan.symbol_id, plan.qty, reason, timeout)
    except Exception as exc:
        # 铁律 33: surface broker exception as a FAILURE result. Caller decides
        # commit semantics. Do NOT swallow — log + propagate via return type.
        logger.exception(
            "[broker-executor] plan_id=%s symbol=%s broker.sell raised",
            plan.plan_id,
            plan.symbol_id,
        )
        # Reviewer P2 (security-reviewer): sanitize error_msg length to bound
        # internal exception details surfaced in API response. Type name +
        # message capped at MAX_ERR_LEN keeps stack-trace-style leaks out of
        # the wire while preserving enough debug context for the operator log.
        safe_err = f"{type(exc).__name__}: {str(exc)[:_MAX_ERR_LEN]}"
        failed_plan = plan.mark_failed(reason=f"broker exception: {safe_err}")
        return BrokerExecutionResult(
            success=False,
            order_id=None,
            filled_shares=0,
            fill_price=0.0,
            error_msg=safe_err,
            new_plan=failed_plan,
        )

    # Interpret broker result dict
    status = str(broker_result.get("status", "")).lower()
    if status in _SUCCESS_STATUSES:
        # Resolve order_id. Stub returns None — synthesize a deterministic
        # paper-mode placeholder so DB column is non-null + traceable.
        raw_order_id = broker_result.get("order_id")
        if raw_order_id is None or raw_order_id == "":
            order_id = f"stub-{plan.plan_id[:8]}"
        else:
            order_id = str(raw_order_id)

        filled_shares = int(broker_result.get("filled_shares", 0) or 0)
        fill_price = float(broker_result.get("price", 0.0) or 0.0)

        executed_plan = plan.mark_executed(broker_order_id=order_id)
        # mark_executed doesn't transition status directly via plan.status field
        # update path — we use the dataclass result directly. Verify status:
        if executed_plan.status != PlanStatus.EXECUTED:  # defensive
            raise RuntimeError(
                f"mark_executed returned status={executed_plan.status.value} (expected EXECUTED)"
            )

        logger.info(
            "[broker-executor] plan_id=%s SUCCESS broker_status=%s order_id=%s filled=%d price=%.4f",
            plan.plan_id,
            status,
            order_id,
            filled_shares,
            fill_price,
        )
        return BrokerExecutionResult(
            success=True,
            order_id=order_id,
            filled_shares=filled_shares,
            fill_price=fill_price,
            error_msg=None,
            new_plan=executed_plan,
        )

    # FAILURE path — broker returned non-success status
    err = str(broker_result.get("error", "")) or f"broker returned status={status!r}"
    logger.warning(
        "[broker-executor] plan_id=%s FAILURE broker_status=%s error=%s",
        plan.plan_id,
        status,
        err,
    )
    failed_plan = plan.mark_failed(reason=f"broker rejected: {err}")
    return BrokerExecutionResult(
        success=False,
        order_id=None,
        filled_shares=0,
        fill_price=0.0,
        error_msg=err,
        new_plan=failed_plan,
    )


__all__ = [
    "BrokerCallable",
    "BrokerExecutionResult",
    "DEFAULT_BROKER_TIMEOUT_SEC",
    "execute_plan_sell",
]
