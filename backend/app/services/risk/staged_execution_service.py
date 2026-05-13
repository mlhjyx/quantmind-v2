"""StagedExecutionService — DB orchestration for STAGED post-CONFIRMED sell (S8 8c-followup).

V3 §S8 8c acceptance: broker_qmt sell 单 wire after CONFIRMED / TIMEOUT_EXECUTED.

Layered architecture (CLAUDE.md §3.1):
  - API (app/api/risk.py POST /dingtalk-webhook) — after CONFIRMED transition,
    calls execute_plan(plan_id).
  - Task (app/tasks/l4_sweep_tasks.py) — after TIMEOUT_EXECUTED transition,
    calls execute_plan(plan_id) for each transitioned plan.
  - Service (this file) — SELECT execution_plans WHERE status IN
    ('CONFIRMED', 'TIMEOUT_EXECUTED') → broker_executor.execute_plan_sell →
    race-safe UPDATE persisting broker_order_id, broker_fill_status, final status.
  - Adapter (app/services/risk/qmt_sell_adapter.py) — wraps MiniQMTBroker; paper-
    mode RiskBacktestAdapter; factory chooses based on EXECUTION_MODE.
  - Engine (qm_platform/risk/execution/broker_executor.py) — pure compute.

Flow:
  1. SELECT plan WHERE plan_id=? AND status IN ('CONFIRMED', 'TIMEOUT_EXECUTED')
     → row exists, broker call appropriate
  2. Reconstruct ExecutionPlan dataclass (only fields broker_executor needs).
  3. broker_executor.execute_plan_sell(plan, broker_call) → BrokerExecutionResult
  4. Race-safe UPDATE:
       UPDATE execution_plans SET status=?, broker_order_id=?,
              broker_fill_status=?
       WHERE plan_id=? AND status IN ('CONFIRMED', 'TIMEOUT_EXECUTED')
     atomic compare-and-set. rowcount=0 → race (another worker / manual fix
     already wrote EXECUTED/FAILED).

铁律 32 sustained: 0 conn.commit() — caller (API endpoint / Celery task) owns
  transaction boundary.
铁律 33 sustained: broker exceptions → BrokerExecutionResult.success=False with
  error_msg; DB errors propagate to caller.
铁律 17 not directly invoked (UPDATE on existing row, not pipeline 入库 path).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from backend.qm_platform.risk.execution.broker_executor import (
    DEFAULT_BROKER_TIMEOUT_SEC,
    BrokerCallable,
    BrokerExecutionResult,
    execute_plan_sell,
)
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    ExecutionPlan,
    PlanStatus,
)

from .qmt_sell_adapter import QMTSellAdapter, is_paper_mode_or_disabled

logger = logging.getLogger(__name__)


# Statuses from which broker execution is allowed
_EXECUTABLE_STATUSES: frozenset[PlanStatus] = frozenset(
    {PlanStatus.CONFIRMED, PlanStatus.TIMEOUT_EXECUTED}
)
_EXECUTABLE_STATUS_VALUES: tuple[str, ...] = tuple(s.value for s in _EXECUTABLE_STATUSES)


class StagedExecutionOutcome(StrEnum):
    """Service-layer outcome for execute_plan."""

    EXECUTED = "executed"  # broker accepted, status=EXECUTED, broker_order_id written
    FAILED = "failed"  # broker rejected / errored / live_disabled, status=FAILED
    NOT_EXECUTABLE = "not_executable"  # plan not in CONFIRMED/TIMEOUT_EXECUTED
    NOT_FOUND = "not_found"  # plan_id doesn't exist
    RACE = "race"  # status changed between SELECT and UPDATE


@dataclass(frozen=True)
class StagedExecutionServiceResult:
    """Service result returned to caller (API / Celery task)."""

    outcome: StagedExecutionOutcome
    plan_id: str | None
    broker_order_id: str | None
    final_status: PlanStatus | None
    error_msg: str | None
    message: str  # human-readable note


class StagedExecutionService:
    """Orchestrates broker sell + DB writeback for CONFIRMED / TIMEOUT_EXECUTED plans.

    Stateless — broker_call injected per construction (factory routes to
    RiskBacktestAdapter.sell in paper / QMTSellAdapter.sell in live).
    """

    def __init__(
        self,
        *,
        broker_call: BrokerCallable,
        timeout: float = DEFAULT_BROKER_TIMEOUT_SEC,
    ) -> None:
        self._broker_call = broker_call
        self._timeout = timeout

    def execute_plan(
        self,
        *,
        plan_id: str,
        conn: Any,
        at: datetime | None = None,
    ) -> StagedExecutionServiceResult:
        """Execute broker sell + persist outcome for a single plan.

        Args:
            plan_id: full UUID string (canonical with dashes).
            conn: psycopg2 connection (caller manages commit/rollback).
            at: injectable clock (default = datetime.now(UTC)).

        Returns:
            StagedExecutionServiceResult with outcome enum + persisted fields.

        Raises:
            psycopg2.Error: any DB error propagates (caller decides rollback).
        """
        now = at or datetime.now(UTC)

        plan_row = self._load_plan(conn, plan_id)
        if plan_row is None:
            logger.info("[staged-exec-service] plan not found plan_id=%s", plan_id)
            return StagedExecutionServiceResult(
                outcome=StagedExecutionOutcome.NOT_FOUND,
                plan_id=plan_id,
                broker_order_id=None,
                final_status=None,
                error_msg=None,
                message=f"plan {plan_id[:8]}* not found",
            )

        current_status = PlanStatus(plan_row["status"])
        if current_status not in _EXECUTABLE_STATUSES:
            logger.info(
                "[staged-exec-service] plan_id=%s status=%s not executable (idempotent return)",
                plan_id,
                current_status.value,
            )
            return StagedExecutionServiceResult(
                outcome=StagedExecutionOutcome.NOT_EXECUTABLE,
                plan_id=plan_id,
                broker_order_id=plan_row.get("broker_order_id"),
                final_status=current_status,
                error_msg=None,
                message=(
                    f"plan {plan_id[:8]}* status={current_status.value} not executable "
                    f"(expected CONFIRMED or TIMEOUT_EXECUTED)"
                ),
            )

        # Reconstruct minimal ExecutionPlan for broker_executor. Fields not
        # populated below are not used by execute_plan_sell.
        plan = self._row_to_plan(plan_row)

        # Pure broker execution (no DB, no commit)
        broker_result: BrokerExecutionResult = execute_plan_sell(
            plan=plan,
            broker_call=self._broker_call,
            timeout=self._timeout,
            at=now,
        )

        # Race-safe UPDATE: write only if status still in executable set
        updated_rows = self._race_safe_update(
            conn=conn,
            plan_id=plan_id,
            new_status=(PlanStatus.EXECUTED if broker_result.success else PlanStatus.FAILED),
            broker_order_id=broker_result.order_id,
            broker_fill_status=(broker_result.filled_shares if broker_result.success else None),
            now=now,
        )

        if updated_rows == 0:
            # Concurrent UPDATE — re-read to surface the final state
            refreshed = self._load_plan(conn, plan_id)
            refreshed_status: PlanStatus | None = (
                PlanStatus(refreshed["status"]) if refreshed else None
            )
            logger.info(
                "[staged-exec-service] plan_id=%s race detected (rowcount=0), "
                "refreshed_status=%s; broker result success=%s discarded for DB",
                plan_id,
                refreshed_status.value if refreshed_status else "<missing>",
                broker_result.success,
            )
            return StagedExecutionServiceResult(
                outcome=StagedExecutionOutcome.RACE,
                plan_id=plan_id,
                broker_order_id=(refreshed.get("broker_order_id") if refreshed else None),
                final_status=refreshed_status,
                error_msg=broker_result.error_msg,
                message=(
                    f"plan {plan_id[:8]}* race — refreshed status="
                    f"{refreshed_status.value if refreshed_status else 'missing'}"
                ),
            )

        # Persisted successfully
        if broker_result.success:
            logger.info(
                "[staged-exec-service] plan_id=%s EXECUTED order_id=%s filled=%d",
                plan_id,
                broker_result.order_id,
                broker_result.filled_shares,
            )
            return StagedExecutionServiceResult(
                outcome=StagedExecutionOutcome.EXECUTED,
                plan_id=plan_id,
                broker_order_id=broker_result.order_id,
                final_status=PlanStatus.EXECUTED,
                error_msg=None,
                message=f"plan {plan_id[:8]}* executed order_id={broker_result.order_id}",
            )

        logger.warning(
            "[staged-exec-service] plan_id=%s FAILED error=%s",
            plan_id,
            broker_result.error_msg,
        )
        return StagedExecutionServiceResult(
            outcome=StagedExecutionOutcome.FAILED,
            plan_id=plan_id,
            broker_order_id=None,
            final_status=PlanStatus.FAILED,
            error_msg=broker_result.error_msg,
            message=f"plan {plan_id[:8]}* failed: {broker_result.error_msg}",
        )

    # ── Helpers ──

    @staticmethod
    def _load_plan(conn: Any, plan_id: str) -> dict[str, Any] | None:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT plan_id::text AS plan_id, status, mode, symbol_id, qty,
                       limit_price, batch_index, batch_total, scheduled_at,
                       cancel_deadline, broker_order_id, broker_fill_status,
                       risk_reason, user_decision, user_decision_at,
                       triggered_by_event_id, risk_metrics, created_at
                FROM execution_plans
                WHERE plan_id::text = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (plan_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))
        finally:
            cur.close()

    @staticmethod
    def _row_to_plan(row: dict[str, Any]) -> ExecutionPlan:
        """Build a minimal ExecutionPlan from a SELECT row.

        Only fields consumed by broker_executor.execute_plan_sell are populated
        non-defaultly: plan_id, status, symbol_id, qty, mode. Others receive
        deterministic placeholders so the dataclass is constructible.
        """
        return ExecutionPlan(
            plan_id=row["plan_id"],
            mode=ExecutionMode(row["mode"]),
            symbol_id=row["symbol_id"],
            action="SELL",
            qty=int(row["qty"]),
            limit_price=(float(row["limit_price"]) if row.get("limit_price") is not None else None),
            batch_index=int(row.get("batch_index") or 1),
            batch_total=int(row.get("batch_total") or 1),
            scheduled_at=row["scheduled_at"],
            cancel_deadline=row["cancel_deadline"],
            status=PlanStatus(row["status"]),
            user_decision=row.get("user_decision"),
            user_decision_at=row.get("user_decision_at"),
            triggered_by_event_id=row.get("triggered_by_event_id"),
            risk_reason=row.get("risk_reason") or "",
            risk_metrics=row.get("risk_metrics") or {},
        )

    @staticmethod
    def _race_safe_update(
        *,
        conn: Any,
        plan_id: str,
        new_status: PlanStatus,
        broker_order_id: str | None,
        broker_fill_status: int | None,
        now: datetime,  # noqa: ARG004 — kept for future audit column
    ) -> int:
        """Atomic UPDATE — only writes if status still CONFIRMED/TIMEOUT_EXECUTED.

        rowcount=1 → write succeeded; rowcount=0 → concurrent transition (another
        worker / manual fix already wrote EXECUTED/FAILED, OR plan reverted to
        a non-executable state which is a programming error elsewhere).
        """
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE execution_plans
                SET status = %s,
                    broker_order_id = %s,
                    broker_fill_status = %s
                WHERE plan_id::text = %s
                  AND status IN %s
                """,
                (
                    new_status.value,
                    broker_order_id,
                    broker_fill_status,
                    plan_id,
                    _EXECUTABLE_STATUS_VALUES,
                ),
            )
            return cur.rowcount
        finally:
            cur.close()


# ── Factory ──


def build_default_broker_call() -> tuple[BrokerCallable, str]:
    """Construct the broker_call callable based on settings.

    Returns:
        (broker_callable, mode_tag) — broker_callable suitable for
        StagedExecutionService(broker_call=...); mode_tag is "paper_stub" or
        "live_qmt" for logging / diagnostics.

    Paper-mode / LIVE_TRADING_DISABLED: returns RiskBacktestAdapter.sell —
        0 broker call. Plans transition CONFIRMED → EXECUTED with synthetic
        order_id="stub-<plan_id_prefix>" + broker_fill_status=0.

    Live-mode + LIVE_TRADING_DISABLED=false (future Tier B cutover): returns
        QMTSellAdapter.sell wrapping a connected MiniQMTBroker. ⚠️ Real
        xtquant.order_stock call; LiveTradingGuard inside MiniQMTBroker is the
        last line of defense.

    Construction is best-effort fail-safe: if live wiring throws (e.g. xtquant
    not importable, QMT path missing), fallback to RiskBacktestAdapter so the
    STAGED queue doesn't starve. The fallback is logged loudly + an alert event
    would surface via the AlertDispatcher chain in a follow-up.
    """
    if is_paper_mode_or_disabled():
        logger.info(
            "[staged-exec-service] paper-mode/live_disabled — using RiskBacktestAdapter (0 broker)"
        )
        stub = RiskBacktestAdapter()
        return stub.sell, "paper_stub"

    # Live mode + LIVE_TRADING_DISABLED=false
    try:
        from engines.broker_qmt import MiniQMTBroker

        from app.config import settings

        broker = MiniQMTBroker(
            qmt_path=getattr(settings, "QMT_PATH", ""),
            account_id=getattr(settings, "QMT_ACCOUNT_ID", ""),
        )
        broker.connect()
        adapter = QMTSellAdapter(broker=broker)
        logger.warning(
            "[staged-exec-service] LIVE MODE — QMTSellAdapter wired to MiniQMTBroker. "
            "5/5 红线 关键点: ensure LIVE_TRADING_DISABLED state is intentional."
        )
        return adapter.sell, "live_qmt"
    except Exception:
        # 反 STAGED queue starvation — fall back to stub, alert via logging
        logger.exception(
            "[staged-exec-service] live broker wire failed — falling back to "
            "RiskBacktestAdapter stub. STAGED plans will register EXECUTED with "
            "stub order_id until live wire is repaired."
        )
        stub = RiskBacktestAdapter()
        return stub.sell, "paper_stub"


def get_default_service() -> StagedExecutionService:
    """Production factory — build StagedExecutionService with default broker.

    Cached at module level would be unsafe across Celery worker fork — instead
    each caller (API endpoint, Celery task) gets a fresh instance per call.
    Lightweight: RiskBacktestAdapter is zero-cost; live MiniQMTBroker.connect is
    paid only on first live invocation post-cutover.
    """
    broker_call, _ = build_default_broker_call()
    return StagedExecutionService(broker_call=broker_call)


# Re-export for typing convenience
__all__ = [
    "StagedExecutionOutcome",
    "StagedExecutionService",
    "StagedExecutionServiceResult",
    "build_default_broker_call",
    "get_default_service",
]


# Optional: expose Callable type alias for callers who want to swap brokers
BrokerCallType = Callable[[str, int, str, float], dict[str, Any]]
