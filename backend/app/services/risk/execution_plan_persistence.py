"""ExecutionPlan persistence service — Phase J §1.1 Chunk 5 (iter 162).

Persists ExecutionPlan + risk_event_log audit row in a single transaction.
Called by realtime_risk_tick task after L4ExecutionPlanner.generate_plan.

Schema:
  - execution_plans (DDL域 8): plan_id, mode, symbol_id, action, qty, limit_price,
    scheduled_at, cancel_deadline, status, risk_reason, risk_metrics
  - risk_event_log (DDL域 7): strategy_id, execution_mode, rule_id, severity, code,
    shares, reason, context_snapshot, action_taken, action_result

Transaction owned by caller (Celery task) per 铁律 32.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from backend.qm_platform.risk.execution.planner import ExecutionPlan
from backend.qm_platform.risk.interface import RuleResult

logger = logging.getLogger(__name__)


def persist_plan_with_audit(
    *,
    conn: Any,
    plan: ExecutionPlan,
    result: RuleResult,
    strategy_id: str,
    execution_mode: str,
    severity: str = "p0",
    cadence: str = "tick",
) -> dict[str, Any]:
    """Insert ExecutionPlan + risk_event_log audit row.

    Args:
        conn: psycopg2 connection (caller owns commit/rollback per 铁律 32)
        plan: ExecutionPlan from L4ExecutionPlanner.generate_plan
        result: original RuleResult that triggered this plan
        strategy_id: PAPER_STRATEGY_ID UUID
        execution_mode: 'paper' or 'live'
        severity: 'p0'/'p1'/'p2' (matches risk_event_log column)
        cadence: 'tick'/'5min'/'15min' for cadence column

    Returns:
        dict — {plan_id, event_id, status} on success

    Raises:
        psycopg2.Error: caller decides rollback/retry
    """
    with conn.cursor() as cur:
        # Step 1: insert execution_plans row
        cur.execute(
            """
            INSERT INTO execution_plans (
                plan_id, mode, symbol_id, action, qty, limit_price,
                batch_index, batch_total, scheduled_at, cancel_deadline,
                status, risk_reason, risk_metrics
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (plan_id, created_at) DO NOTHING
            RETURNING plan_id
            """,
            (
                plan.plan_id,
                plan.mode.value,
                plan.symbol_id,
                plan.action,
                plan.qty,
                plan.limit_price,
                plan.batch_index,
                plan.batch_total,
                plan.scheduled_at,
                plan.cancel_deadline,
                plan.status.value,
                plan.risk_reason,
                psycopg2.extras.Json(plan.risk_metrics or {}),
            ),
        )
        plan_row = cur.fetchone()
        plan_inserted = plan_row is not None
        plan_id = plan.plan_id

        # Step 2: insert risk_event_log audit row
        context_snapshot = {
            "rule_id": result.rule_id,
            "code": result.code,
            "shares": result.shares,
            "metrics": result.metrics or {},
        }
        action_result = {
            "plan_id": plan_id,
            "plan_status": plan.status.value,
            "plan_inserted": plan_inserted,
            "cancel_deadline": plan.cancel_deadline.isoformat() if plan.cancel_deadline else None,
        }
        cur.execute(
            """
            INSERT INTO risk_event_log (
                strategy_id, execution_mode, rule_id, severity, code, shares,
                reason, context_snapshot, action_taken, action_result, cadence,
                priority
            ) VALUES (
                CAST(%s AS uuid), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                strategy_id,
                execution_mode,
                result.rule_id[:50],  # truncate to col size
                severity[:10],
                (result.code or "")[:12],
                result.shares,
                result.reason or "",
                psycopg2.extras.Json(context_snapshot),
                "L4_PLAN_CREATED",
                psycopg2.extras.Json(action_result),
                cadence[:10],
                severity.upper()[:4],
            ),
        )
        event_row = cur.fetchone()
        event_id = str(event_row[0]) if event_row else None

    logger.info(
        "[L4-persist] plan_id=%s event_id=%s status=%s inserted=%s",
        plan_id,
        event_id,
        plan.status.value,
        plan_inserted,
    )
    return {
        "plan_id": plan_id,
        "event_id": event_id,
        "status": plan.status.value,
        "plan_inserted": plan_inserted,
    }


def parse_severity_from_rule_id(rule_id: str) -> str:
    """Map rule_id prefix → severity (sustained from realtime/alert.py:_rule_severity_str).

    p0_*  → p0  (immediate)
    p1_*  → p1
    p2_*  → p2

    Default: p2 (conservative) for unknown prefix.
    """
    if rule_id.startswith("p0_"):
        return "p0"
    if rule_id.startswith("p1_"):
        return "p1"
    if rule_id.startswith("p2_"):
        return "p2"
    return "p2"
