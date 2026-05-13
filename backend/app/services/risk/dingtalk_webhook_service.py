"""DingTalk webhook inbound service — DB orchestration for STAGED 反向决策 (S8 8b).

V3 §S8 8b acceptance: webhook receiver → execution_plans state transition.

Layered architecture (CLAUDE.md §3.1):
  - API (app/api/risk.py) — extract headers + body, call this service
  - Service (this file) — DB read + L4ExecutionPlanner state machine + race-safe UPDATE
  - Engine (qm_platform/risk/execution/) — pure ExecutionPlan dataclass + state machine

Flow:
  1. Parser caller verified signature + parsed command (CONFIRM/CANCEL + plan_id_prefix)
  2. This service resolves plan_id_prefix → full plan_id by SELECT execution_plans
       with prefix LIKE match (≥8 hex enforced by parser; ambiguity → error)
  3. Check current status (PENDING_CONFIRM = transitionable; other = idempotent return)
  4. Check cancel_deadline not expired (反 user lost window → caller may still UPDATE
       to record 'attempted_after_expiry' audit but row already TIMEOUT_EXECUTED)
  5. UPDATE execution_plans SET status=..., user_decision=..., user_decision_at=NOW()
       WHERE plan_id=... AND status='PENDING_CONFIRM' (atomic compare-and-set, 反 race)
  6. If UPDATE rowcount=0 → status changed concurrently → re-SELECT + idempotent return

铁律 32 sustained: 0 conn.commit() in this service — caller (API endpoint or Celery
  task) owns transaction boundary.
铁律 33 sustained: fail-loud — DB errors propagate; only 'plan not found' /
  'already terminal' return as enum outcomes (反 silent skip).
铁律 17 NOT directly invoked here (read-modify-write on existing rows, not pipeline
  入库 path). UPDATE goes through standard parametrized SQL, sanitized via psycopg2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    PlanStatus,
)
from backend.qm_platform.risk.execution.webhook_parser import WebhookCommand

logger = logging.getLogger(__name__)


# ── Result types ──


class WebhookOutcome(StrEnum):
    """Service-layer result of webhook processing.

    Mapped to HTTP 200 with body indicating outcome (反 422/409 噪音 — DingTalk
    webhook auto-retry on non-2xx, idempotent webhook responses keep 2xx).
    """

    TRANSITIONED = "transitioned"  # PENDING_CONFIRM → CONFIRMED/CANCELLED success
    ALREADY_TERMINAL = "already_terminal"  # plan in CONFIRMED/CANCELLED/EXECUTED/etc
    DEADLINE_EXPIRED = "deadline_expired"  # cancel_deadline passed before user acted
    PLAN_NOT_FOUND = "plan_not_found"  # no plan matches prefix
    AMBIGUOUS_PREFIX = "ambiguous_prefix"  # multiple plans match prefix


@dataclass(frozen=True)
class DingTalkWebhookResult:
    """Service result returned to API layer."""

    outcome: WebhookOutcome
    plan_id: str | None  # resolved full UUID (may be None if not found / ambiguous)
    final_status: PlanStatus | None  # current status after processing
    message: str  # human-readable note for response body


# ── Service ──


class DingTalkWebhookService:
    """Resolves webhook command to execution_plans state transition (S8 8b).

    Pure orchestration — no broker call, no DingTalk outbound, no 红线 mutation.
    8c sub-PR wires the broker_qmt sell path post-CONFIRMED transition.
    """

    def __init__(self) -> None:
        # No state — service is stateless; conn injected per call
        pass

    def process_command(
        self,
        *,
        command: WebhookCommand,
        plan_id_prefix: str,
        conn: Any,
        at: datetime | None = None,
    ) -> DingTalkWebhookResult:
        """Resolve prefix → plan, apply transition, return outcome.

        Args:
            command: parsed CONFIRM or CANCEL
            plan_id_prefix: ≥8 hex chars, normalized (lowercase, no dashes)
            conn: psycopg2 connection (caller manages commit/rollback)
            at: injectable clock for tests (default = datetime.now(UTC))

        Returns:
            DingTalkWebhookResult with outcome + final plan_id + status + message.

        Raises:
            psycopg2.Error: any DB error (caller decides rollback / retry)
        """
        now = at or datetime.now(UTC)

        # Step 1: resolve prefix → plan row
        plans = self._resolve_prefix(conn, plan_id_prefix)
        if len(plans) == 0:
            logger.info("[dingtalk-webhook-service] plan not found prefix=%s", plan_id_prefix)
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.PLAN_NOT_FOUND,
                plan_id=None,
                final_status=None,
                message=f"no execution plan matches prefix {plan_id_prefix[:8]}*",
            )
        if len(plans) > 1:
            logger.warning(
                "[dingtalk-webhook-service] ambiguous prefix=%s matched %d plans",
                plan_id_prefix,
                len(plans),
            )
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.AMBIGUOUS_PREFIX,
                plan_id=None,
                final_status=None,
                message=(
                    f"prefix {plan_id_prefix[:8]}* matches {len(plans)} plans; "
                    "please send a longer prefix"
                ),
            )

        plan_row = plans[0]
        plan_id: str = plan_row["plan_id"]
        current_status = PlanStatus(plan_row["status"])
        cancel_deadline: datetime = plan_row["cancel_deadline"]

        # Step 2: idempotent guard — already terminal?
        if current_status != PlanStatus.PENDING_CONFIRM:
            logger.info(
                "[dingtalk-webhook-service] plan_id=%s already terminal status=%s, idempotent return",
                plan_id,
                current_status.value,
            )
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.ALREADY_TERMINAL,
                plan_id=plan_id,
                final_status=current_status,
                message=f"plan already in terminal state {current_status.value}",
            )

        # Step 3: deadline expiry check
        if now >= cancel_deadline:
            logger.info(
                "[dingtalk-webhook-service] plan_id=%s deadline expired (now=%s, "
                "cancel_deadline=%s) — user lost window",
                plan_id,
                now.isoformat(),
                cancel_deadline.isoformat(),
            )
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.DEADLINE_EXPIRED,
                plan_id=plan_id,
                final_status=current_status,
                message=(
                    f"cancel_deadline {cancel_deadline.isoformat()} passed; "
                    "Celery sweep will transition to TIMEOUT_EXECUTED"
                ),
            )

        # Step 4: build ExecutionPlan, apply transition, race-safe UPDATE
        target_status, decision_label = (
            (PlanStatus.CONFIRMED, "confirm")
            if command == WebhookCommand.CONFIRM
            else (PlanStatus.CANCELLED, "cancel")
        )

        # Verify state machine legality (defense-in-depth; should always pass given Step 2 + 3)
        if not self._is_valid_transition(current_status, target_status):
            # Defensive — should be unreachable
            logger.error(
                "[dingtalk-webhook-service] invalid transition %s → %s for plan_id=%s",
                current_status.value,
                target_status.value,
                plan_id,
            )
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.ALREADY_TERMINAL,
                plan_id=plan_id,
                final_status=current_status,
                message=f"invalid transition {current_status.value} → {target_status.value}",
            )

        # Atomic compare-and-set (反 race): UPDATE returns 0 rows if status changed
        updated_rows = self._race_safe_update(
            conn=conn,
            plan_id=plan_id,
            target_status=target_status,
            decision_label=decision_label,
            user_decision_at=now,
        )

        if updated_rows == 0:
            # Concurrent transition occurred between our SELECT and UPDATE
            logger.info(
                "[dingtalk-webhook-service] plan_id=%s concurrent transition detected, re-reading",
                plan_id,
            )
            refreshed = self._resolve_prefix(conn, plan_id_prefix)
            new_status = PlanStatus(refreshed[0]["status"]) if refreshed else current_status
            return DingTalkWebhookResult(
                outcome=WebhookOutcome.ALREADY_TERMINAL,
                plan_id=plan_id,
                final_status=new_status,
                message=f"concurrent transition; current status {new_status.value}",
            )

        logger.info(
            "[dingtalk-webhook-service] transitioned plan_id=%s %s → %s decision=%s",
            plan_id,
            current_status.value,
            target_status.value,
            decision_label,
        )
        return DingTalkWebhookResult(
            outcome=WebhookOutcome.TRANSITIONED,
            plan_id=plan_id,
            final_status=target_status,
            message=f"plan {plan_id[:8]}* {decision_label}ed",
        )

    # ── Helpers ──

    @staticmethod
    def _resolve_prefix(conn: Any, plan_id_prefix: str) -> list[dict[str, Any]]:
        """SELECT execution_plans by prefix match.

        plan_id_prefix is normalized (lowercase, no dashes). Postgres UUID type
        accepts canonical string with dashes, so we use ::text cast + REPLACE
        for prefix LIKE.
        """
        cur = conn.cursor()
        try:
            # Use psycopg2.extras.RealDictCursor-compatible fetching: build dicts manually
            cur.execute(
                """
                SELECT plan_id::text AS plan_id, status, cancel_deadline, mode, symbol_id, qty
                FROM execution_plans
                WHERE REPLACE(plan_id::text, '-', '') LIKE %s
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (plan_id_prefix + "%",),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        finally:
            cur.close()

    @staticmethod
    def _race_safe_update(
        *,
        conn: Any,
        plan_id: str,
        target_status: PlanStatus,
        decision_label: str,
        user_decision_at: datetime,
    ) -> int:
        """Atomic UPDATE WHERE status='PENDING_CONFIRM' — returns affected rowcount.

        rowcount=1 → transition succeeded; rowcount=0 → status changed concurrently.
        """
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE execution_plans
                SET status = %s,
                    user_decision = %s,
                    user_decision_at = %s
                WHERE plan_id::text = %s
                  AND status = 'PENDING_CONFIRM'
                """,
                (target_status.value, decision_label, user_decision_at, plan_id),
            )
            return cur.rowcount
        finally:
            cur.close()

    @staticmethod
    def _is_valid_transition(from_status: PlanStatus, to_status: PlanStatus) -> bool:
        """Delegate to L4ExecutionPlanner.valid_transition for SSOT."""
        from backend.qm_platform.risk.execution.planner import L4ExecutionPlanner

        return L4ExecutionPlanner.valid_transition(from_status, to_status)


# ExecutionMode re-export so callers can detect OFF/STAGED for routing (反 8c needing
# to import from qm_platform directly for what's essentially a service-layer concern)
__all__ = [
    "DingTalkWebhookResult",
    "DingTalkWebhookService",
    "ExecutionMode",
    "WebhookOutcome",
]
