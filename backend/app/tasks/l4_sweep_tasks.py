"""L4 STAGED PENDING_CONFIRM expired sweep — Celery task (S8 8c-partial).

V3 §S8 8c scope (Plan §A): broker_qmt sell wire + Celery Beat sweep
PENDING_CONFIRM expired + STAGED smoke. This module covers the **sweep**
sub-item only — broker invocation deferred to 8c-followup PR (5/5 红线 关键点
needs explicit user ack per Plan §A S8 红线 SOP).

Flow:
  1. Celery Beat fires every 1min during trading hours (crontab `* 9-14 * * 1-5`
     Asia/Shanghai). Reviewer P1-1 fix: previous docstring omitted hour range.
  2. Task SELECTs execution_plans WHERE status='PENDING_CONFIRM' AND
     cancel_deadline < NOW() — ORDER BY cancel_deadline ASC LIMIT SWEEP_BATCH_LIMIT
  3. For each expired plan, race-safe UPDATE status to TIMEOUT_EXECUTED with
     user_decision='timeout' (atomic compare-and-set, 反 race with concurrent
     webhook user CONFIRM/CANCEL)
  4. Structured log per transition so operator sees TIMEOUT_EXECUTED events
  5. **Does NOT invoke broker_qmt** — production sell wire is 8c-followup scope.
     Once that lands, broker invocation will hook into the same row write.

铁律 31: not directly invoked (task layer, not engine).
铁律 32: caller (this task) owns conn.commit; service module doesn't commit.
铁律 33: fail-loud — SQL errors propagate to Celery retry; per-row errors
  logged but don't abort batch (反 single bad row blocking sweep).
铁律 41: Asia/Shanghai timezone via celery_app.py; cancel_deadline UTC.
铁律 44 X9: post-merge ops checklist `Servy restart QuantMind-CeleryBeat AND
  QuantMind-Celery` per LL-141 sustained.

关联 ADR: ADR-058 NEW (8c-partial sediment, post-merge)
关联 LL: LL-152 NEW (8c-partial sediment, post-merge)
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.db import get_sync_conn
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.l4_sweep_tasks")

# Reviewer P2-1 fix: batch limit reads from settings (override path), default 100.
# Caps blast radius if many plans expire at once (e.g. crash + restart with
# backlog). 100 plans/min is generous given typical trading-day plan volume
# (~tens/day). Backlog 1000+ rows → ~10 min full clear. Operator can raise
# via settings.L4_SWEEP_BATCH_LIMIT in .env.
SWEEP_BATCH_LIMIT: int = getattr(settings, "L4_SWEEP_BATCH_LIMIT", 100)


@celery_app.task(
    name="app.tasks.l4_sweep_tasks.sweep_pending_confirm_plans",
    soft_time_limit=30,  # 30s soft — typical sweep <1s for 100 rows
    time_limit=60,  # 60s hard kill (Beat cadence is 60s; 反 overlap)
)
def sweep_pending_confirm_plans() -> dict[str, Any]:
    """Transition expired PENDING_CONFIRM plans → TIMEOUT_EXECUTED.

    Beat schedule: `risk-l4-sweep-1min` (every 1min during trading hours,
    crontab `* 9-14 * * 1-5` Asia/Shanghai).

    Returns:
        {
            "ok": bool,
            "scanned": int (rows matching expiry filter),
            "transitioned": int (rows where atomic UPDATE succeeded),
            "races": int (rows where UPDATE rowcount=0, concurrent webhook),
            "batch_limited": bool (True if hit SWEEP_BATCH_LIMIT),
        }

    Raises:
        Any psycopg2.Error propagates to Celery retry.
    """
    # Reviewer LOW fix: pre-assign conn=None so a get_sync_conn() failure doesn't
    # raise UnboundLocalError in the finally block (which would mask the original
    # exception, e.g. PG connection refused). Standard psycopg2 pattern.
    conn = None
    try:
        conn = get_sync_conn()
        result = _sweep_inner(conn=conn)
        conn.commit()
        logger.info(
            "[l4-sweep] scanned=%d transitioned=%d races=%d batch_limited=%s",
            result["scanned"],
            result["transitioned"],
            result["races"],
            result["batch_limited"],
        )
        return result
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def _sweep_inner(*, conn: Any, limit: int = SWEEP_BATCH_LIMIT) -> dict[str, Any]:
    """Inner sweep — SELECT expired + race-safe UPDATE loop.

    Separated from the Celery task body for unit-testability without monkey-
    patching get_sync_conn. Caller owns conn lifecycle + commit/rollback.

    NOTE: broker invocation deferred to 8c-followup. Once that wires, this
    helper will additionally invoke the broker adapter for each TIMEOUT_EXECUTED
    transition (within the same conn / transaction boundary).
    """
    cur = conn.cursor()
    try:
        # Step 1: SELECT expired PENDING_CONFIRM plans
        # Reviewer P1-2 note: cancel_deadline column is TIMESTAMPTZ; PostgreSQL
        # NOW() returns the session's current UTC timestamp regardless of Celery's
        # `timezone="Asia/Shanghai" + enable_utc=False` config (PG TIMESTAMPTZ
        # arithmetic is timezone-correct internally). 铁律 41 sustained.
        cur.execute(
            """
            SELECT plan_id::text AS plan_id, symbol_id, qty, cancel_deadline,
                   created_at
            FROM execution_plans
            WHERE status = 'PENDING_CONFIRM'
              AND cancel_deadline < NOW()
            ORDER BY cancel_deadline ASC
            LIMIT %s
            """,
            (limit,),
        )
        cols = [c.name for c in cur.description]
        expired_rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

        scanned = len(expired_rows)
        transitioned = 0
        races = 0

        # Step 2: race-safe UPDATE per row (atomic compare-and-set)
        for plan_row in expired_rows:
            plan_id = plan_row["plan_id"]
            # Race: webhook user CONFIRM/CANCEL could have transitioned between
            # our SELECT and this UPDATE. The WHERE status='PENDING_CONFIRM'
            # predicate enforces atomicity — rowcount=0 means concurrent change.
            cur.execute(
                """
                UPDATE execution_plans
                SET status = 'TIMEOUT_EXECUTED',
                    user_decision = 'timeout',
                    user_decision_at = NOW()
                WHERE plan_id::text = %s
                  AND status = 'PENDING_CONFIRM'
                  AND cancel_deadline < NOW()
                """,
                (plan_id,),
            )
            if cur.rowcount == 1:
                transitioned += 1
                logger.info(
                    "[l4-sweep] TIMEOUT_EXECUTED plan_id=%s symbol=%s qty=%d "
                    "deadline=%s (broker invocation deferred to 8c-followup)",
                    plan_id,
                    plan_row["symbol_id"],
                    plan_row["qty"],
                    plan_row["cancel_deadline"].isoformat(),
                )
            else:
                # rowcount=0 → concurrent webhook user decision changed status
                races += 1
                logger.info(
                    "[l4-sweep] race detected for plan_id=%s (concurrent webhook); skip",
                    plan_id,
                )

        return {
            "ok": True,
            "scanned": scanned,
            "transitioned": transitioned,
            "races": races,
            "batch_limited": scanned == limit,
        }
    finally:
        cur.close()
