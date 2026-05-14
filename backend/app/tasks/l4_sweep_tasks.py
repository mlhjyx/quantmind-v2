"""L4 STAGED PENDING_CONFIRM expired sweep + broker wire — Celery task (S8 8c).

V3 §S8 8c full scope (Plan §A): Celery Beat sweep PENDING_CONFIRM expired +
broker_qmt sell wire. 8c-partial (PR #308) covered sweep + STAGED smoke;
8c-followup (this PR) wires broker sell post-TIMEOUT_EXECUTED.

Flow:
  1. Celery Beat fires every 1min during trading hours (crontab `* 9-14 * * 1-5`
     Asia/Shanghai). Reviewer P1-1 fix (8c-partial): previous docstring omitted
     hour range.
  2. Task SELECTs execution_plans WHERE status='PENDING_CONFIRM' AND
     cancel_deadline < NOW() — ORDER BY cancel_deadline ASC LIMIT SWEEP_BATCH_LIMIT
  3. For each expired plan, race-safe UPDATE status to TIMEOUT_EXECUTED with
     user_decision='timeout' (atomic compare-and-set, 反 race with concurrent
     webhook user CONFIRM/CANCEL)
  4. **8c-followup**: after each successful TIMEOUT_EXECUTED transition, invoke
     StagedExecutionService.execute_plan to call broker.sell + writeback
     broker_order_id + broker_fill_status + EXECUTED/FAILED final state.
     Broker is paper-stub by default (EXECUTION_MODE=paper or
     LIVE_TRADING_DISABLED=true → RiskBacktestAdapter); live MiniQMTBroker only
     when settings flip + explicit user ack.
  5. Structured log per transition AND per broker outcome so operator sees the
     full pipeline state.

铁律 31: not directly invoked (task layer, not engine).
铁律 32: caller (this task) owns conn.commit; service modules don't commit.
铁律 33: fail-loud — SQL errors propagate to Celery retry; per-row errors
  logged but don't abort batch (反 single bad row blocking sweep). Broker
  exceptions are captured via execute_plan_sell + persisted as FAILED state.
铁律 41: Asia/Shanghai timezone via celery_app.py; cancel_deadline UTC.
铁律 44 X9: post-merge ops checklist `Servy restart QuantMind-CeleryBeat AND
  QuantMind-Celery` per LL-141 sustained.

关联 ADR: ADR-058 (8c-partial sediment) + ADR-059 NEW (8c-followup sediment)
关联 LL: LL-152 (8c-partial sediment) + LL-153 NEW (8c-followup sediment)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings
from app.services.db import get_sync_conn
from app.services.risk.staged_execution_service import (
    StagedExecutionOutcome,
    StagedExecutionService,
)
from app.services.risk.staged_execution_service import (
    get_default_service as get_default_staged_service,
)
from app.tasks.celery_app import celery_app
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S,
)

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
    """Transition expired PENDING_CONFIRM plans → TIMEOUT_EXECUTED → EXECUTED.

    Beat schedule: `risk-l4-sweep-1min` (every 1min during trading hours,
    crontab `* 9-14 * * 1-5` Asia/Shanghai).

    8c-followup: after each TIMEOUT_EXECUTED transition, broker.sell is
    invoked + broker_order_id persisted + final EXECUTED/FAILED state.

    Returns:
        {
            "ok": bool,
            "scanned": int (rows matching expiry filter),
            "transitioned": int (rows where TIMEOUT_EXECUTED UPDATE succeeded),
            "races": int (TIMEOUT_EXECUTED UPDATE rowcount=0, concurrent webhook),
            "batch_limited": bool (True if hit SWEEP_BATCH_LIMIT),
            "executed": int (8c-followup: broker.sell success + EXECUTED persisted),
            "broker_failed": int (8c-followup: broker rejection / error → FAILED),
            "broker_race": int (8c-followup: race on EXECUTED/FAILED writeback),
        }

    Raises:
        Any psycopg2.Error propagates to Celery retry.
    """
    # Reviewer LOW fix (8c-partial): pre-assign conn=None so a get_sync_conn()
    # failure doesn't raise UnboundLocalError in the finally block (which would
    # mask the original exception, e.g. PG connection refused).
    conn = None
    try:
        conn = get_sync_conn()
        # Build one staged service per task invocation — shared across rows in
        # the batch. Live broker connect (if applicable) paid once per Beat tick.
        staged_service = get_default_staged_service()
        result = _sweep_inner(conn=conn, staged_service=staged_service)
        conn.commit()
        logger.info(
            "[l4-sweep] scanned=%d transitioned=%d races=%d executed=%d "
            "broker_failed=%d broker_race=%d batch_limited=%s",
            result["scanned"],
            result["transitioned"],
            result["races"],
            result["executed"],
            result["broker_failed"],
            result["broker_race"],
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


def _sweep_inner(
    *,
    conn: Any,
    staged_service: StagedExecutionService | None = None,
    limit: int = SWEEP_BATCH_LIMIT,
) -> dict[str, Any]:
    """Inner sweep — SELECT expired + race-safe UPDATE loop + broker wire.

    Separated from the Celery task body for unit-testability without monkey-
    patching get_sync_conn. Caller owns conn lifecycle + commit/rollback.

    Args:
        conn: psycopg2 connection (caller owns commit/rollback).
        staged_service: injectable for tests. None → no broker wire (legacy
            8c-partial behavior; transitions still write TIMEOUT_EXECUTED but
            broker_order_id remains NULL).
        limit: max rows per batch (default SWEEP_BATCH_LIMIT from settings).

    After TIMEOUT_EXECUTED transition, broker.sell is invoked via
    staged_service.execute_plan; broker_order_id + broker_fill_status + final
    status are persisted in the same conn (atomic per row pair).
    """
    cur = conn.cursor()
    try:
        # Step 1: SELECT expired PENDING_CONFIRM plans
        # Reviewer P1-2 note (8c-partial): cancel_deadline column is TIMESTAMPTZ;
        # PostgreSQL NOW() returns the session's current UTC timestamp regardless
        # of Celery's `timezone="Asia/Shanghai" + enable_utc=False` config (PG
        # TIMESTAMPTZ arithmetic is timezone-correct internally). 铁律 41 sustained.
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
        executed = 0
        broker_failed = 0
        broker_race = 0

        # Step 2: race-safe UPDATE per row (atomic compare-and-set), then broker
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
                    "[l4-sweep] TIMEOUT_EXECUTED plan_id=%s symbol=%s qty=%d deadline=%s",
                    plan_id,
                    plan_row["symbol_id"],
                    plan_row["qty"],
                    plan_row["cancel_deadline"].isoformat(),
                )

                # 8c-followup: invoke broker.sell + writeback. Skipped if no
                # staged_service injected (legacy unit test path).
                if staged_service is not None:
                    try:
                        staged_r = staged_service.execute_plan(plan_id=plan_id, conn=conn)
                    except Exception:
                        # 铁律 33: broker DB write raised — propagate to Celery
                        # retry handler. Per-row sweep doesn't swallow DB errors.
                        logger.exception(
                            "[l4-sweep] staged_service.execute_plan raised for plan_id=%s",
                            plan_id,
                        )
                        raise
                    if staged_r.outcome == StagedExecutionOutcome.EXECUTED:
                        executed += 1
                        logger.info(
                            "[l4-sweep] EXECUTED plan_id=%s order_id=%s",
                            plan_id,
                            staged_r.broker_order_id,
                        )
                    elif staged_r.outcome == StagedExecutionOutcome.FAILED:
                        broker_failed += 1
                        logger.warning(
                            "[l4-sweep] broker FAILED plan_id=%s error=%s",
                            plan_id,
                            staged_r.error_msg,
                        )
                    elif staged_r.outcome == StagedExecutionOutcome.RACE:
                        broker_race += 1
                        logger.info(
                            "[l4-sweep] broker writeback race plan_id=%s final_status=%s",
                            plan_id,
                            (
                                staged_r.final_status.value
                                if staged_r.final_status is not None
                                else "<missing>"
                            ),
                        )
                    else:
                        # Reviewer LOW (code-reviewer): NOT_FOUND / NOT_EXECUTABLE
                        # should be unreachable since we just successfully UPDATEd
                        # status to TIMEOUT_EXECUTED on this row. Defensive log
                        # surfaces the unexpected condition for debugging
                        # (铁律 33 fail-loud — silent count loss would mask drift).
                        logger.warning(
                            "[l4-sweep] unexpected staged outcome=%s for plan_id=%s "
                            "(post-TIMEOUT_EXECUTED transition; investigate)",
                            staged_r.outcome.value,
                            plan_id,
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
            "executed": executed,
            "broker_failed": broker_failed,
            "broker_race": broker_race,
            "batch_limited": scanned == limit,
        }
    finally:
        cur.close()


# ─────────────────────────────────────────────────────────────
# V3 §14 mode 12 — broker plan stuck sweep + BROKER_PLAN_STUCK 元告警 (HC-2b2 G7)
# ─────────────────────────────────────────────────────────────


def _emit_broker_plan_stuck_meta_alert(
    stuck_plans: list[tuple[str, str, str]], *, now: datetime
) -> None:
    """Emit BROKER_PLAN_STUCK 元告警 via HC-1b channel fallback chain (V3 §14 mode 12).

    Event-emitted rule (NOT polled — 见 meta_alert_interface.MetaAlertRuleId docstring):
    sweep 检测到 plan 卡在 CONFIRMED/TIMEOUT_EXECUTED 且 retry 仍未推进 → 直接构造
    MetaAlert + 走 push_triggered (主 DingTalk → 备 email → 极端 log-P0).

    一个 alert 汇总所有 still-stuck plan (沿用 evaluate_staged_overdue 单 alert 汇总体例).
    Fail-soft: 元告警 push 自身失败仅 log (反 — notification 失败连带吞掉 sweep 结果).

    Args:
        stuck_plans: list of (plan_id, status, reason) — retry 后仍卡的 plan.
        now: tz-aware 评估时刻.
    """
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415
        from app.services.risk.meta_monitor_service import MetaMonitorService  # noqa: PLC0415
        from backend.qm_platform.risk.metrics.meta_alert_interface import (  # noqa: PLC0415
            RULE_SEVERITY,
            MetaAlert,
            MetaAlertRuleId,
        )

        rule_id = MetaAlertRuleId.BROKER_PLAN_STUCK
        worst = stuck_plans[0]
        detail = (
            f"{len(stuck_plans)} execution_plan(s) stuck in CONFIRMED/TIMEOUT_EXECUTED "
            f"> {BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S}s — retry 仍未推进, broker 接口故障? "
            f"(e.g. plan_id={worst[0]} status={worst[1]} reason={worst[2]}) "
            f"— 需 user 手工干预 reconciliation"
        )
        alert = MetaAlert(
            rule_id=rule_id,
            severity=RULE_SEVERITY[rule_id],
            triggered=True,
            detail=detail,
            observed_at=now,
        )
        # push_triggered = HC-1b public API (channel fallback chain). conn owned
        # here — failure-path helper 自管事务 (反 复用 sweep conn 的不确定状态).
        conn = get_sync_conn()
        try:
            MetaMonitorService().push_triggered([alert], conn=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as push_exc:  # noqa: BLE001 — fail-soft: 元告警 push 失败不吞 sweep 结果
        logger.error(
            "[l4-broker-stuck-sweep] BROKER_PLAN_STUCK 元告警 push itself failed "
            "(sweep 结果 caller 仍返回): %s",
            push_exc,
        )


def _sweep_stuck_inner(
    *,
    conn: Any,
    staged_service: StagedExecutionService,
    now: datetime,
    limit: int = SWEEP_BATCH_LIMIT,
) -> dict[str, Any]:
    """Inner sweep — SELECT stuck CONFIRMED/TIMEOUT_EXECUTED plans + retry execute_plan.

    A plan in CONFIRMED/TIMEOUT_EXECUTED for > BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S
    means execute_plan never completed (broker call 挂 / DB writeback 失败 / worker
    中途死). **CONFIRMED-stuck 此前 0 retry 路径** — l4_sweep 只扫 PENDING_CONFIRM,
    webhook CONFIRM 后的 execute_plan 失败无人重试.

    Per-plan independent transaction (commit-per-plan): 这是 reconciliation safety
    net — 一个 un-resolvable plan 必须 NOT block 其余 plan 的 reconcile (区别于
    l4_sweep 的 all-or-nothing batch — 那是 cohesive batch).

    retry execute_plan outcomes:
      - EXECUTED / FAILED / RACE / NOT_EXECUTABLE → plan 推进到/已是终态 = resolved.
      - execute_plan raises (DB error / borked txn) → plan 仍卡 → rollback + 计入
        still_stuck → 汇总 emit BROKER_PLAN_STUCK 元告警.

    Caller owns conn lifecycle; this fn commits/rollbacks per-plan internally
    (task IS the transaction owner — per-plan boundary is a deliberate choice).
    """
    cutoff = now - timedelta(seconds=BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S)
    cur = conn.cursor()
    try:
        # COALESCE(user_decision_at, created_at): TIMEOUT_EXECUTED + webhook-CONFIRMED
        # both set user_decision_at; created_at is the fallback (defensive — a plan
        # should never be CONFIRMED/TIMEOUT_EXECUTED with NULL user_decision_at).
        cur.execute(
            """
            SELECT plan_id::text AS plan_id, status,
                   COALESCE(user_decision_at, created_at) AS stuck_since
            FROM execution_plans
            WHERE status IN ('CONFIRMED', 'TIMEOUT_EXECUTED')
              AND COALESCE(user_decision_at, created_at) < %s
            ORDER BY COALESCE(user_decision_at, created_at) ASC
            LIMIT %s
            """,
            (cutoff, limit),
        )
        cols = [c.name for c in cur.description]
        stuck_rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        cur.close()

    scanned = len(stuck_rows)
    resolved = 0
    still_stuck: list[tuple[str, str, str]] = []

    for row in stuck_rows:
        plan_id = row["plan_id"]
        status = row["status"]
        try:
            r = staged_service.execute_plan(plan_id=plan_id, conn=conn)
            conn.commit()  # per-plan independent transaction (task owns boundary)
            resolved += 1
            logger.info(
                "[l4-broker-stuck-sweep] plan_id=%s was %s — retry resolved: "
                "outcome=%s final_status=%s",
                plan_id,
                status,
                r.outcome.value,
                r.final_status.value if r.final_status is not None else "<none>",
            )
        except Exception as exc:  # noqa: BLE001 — per-plan resilient (反 1 bad plan 阻断整 sweep)
            conn.rollback()  # clear borked txn before the next plan's query
            reason = f"{type(exc).__name__}: {exc}"
            still_stuck.append((plan_id, status, reason))
            logger.warning(
                "[l4-broker-stuck-sweep] plan_id=%s status=%s retry FAILED (still stuck): %s",
                plan_id,
                status,
                reason,
            )

    if still_stuck:
        _emit_broker_plan_stuck_meta_alert(still_stuck, now=now)

    return {
        "ok": True,
        "scanned": scanned,
        "resolved": resolved,
        "still_stuck": len(still_stuck),
        "still_stuck_plan_ids": [p[0] for p in still_stuck],
        "batch_limited": scanned == limit,
    }


@celery_app.task(
    name="app.tasks.l4_sweep_tasks.sweep_stuck_broker_plans",
    soft_time_limit=60,  # retry loop over stuck plans — generous vs sweep_pending's 30s
    time_limit=120,
)
def sweep_stuck_broker_plans() -> dict[str, Any]:
    """Sweep execution_plans stuck in CONFIRMED/TIMEOUT_EXECUTED → retry + 元告警.

    Beat schedule: `risk-l4-broker-stuck-sweep` (every 5min, all hours — stuck plans
    persist across any time incl overnight; CONFIRMED-stuck has NO other retry path).

    V3 §14 mode 12 (HC-2b2 G7): broker_qmt 接口故障 — sell 单提交但 status 未推进.
    Detects plans stuck > BROKER_PLAN_STUCK_OVERDUE_THRESHOLD_S, retries execute_plan
    (idempotent — race-safe UPDATE), plans still stuck after retry → BROKER_PLAN_STUCK
    元告警 (P0, user 手工干预 reconciliation).

    Returns:
        {ok, scanned, resolved, still_stuck, still_stuck_plan_ids, batch_limited}

    Raises:
        psycopg2.Error from get_sync_conn / the stuck-plan SELECT propagates to
        Celery retry. Per-plan execute_plan errors are caught + escalated (NOT raised)
        — 一个 bad plan 不阻断 sweep.
    """
    conn = None
    try:
        conn = get_sync_conn()
        staged_service = get_default_staged_service()
        result = _sweep_stuck_inner(conn=conn, staged_service=staged_service, now=datetime.now(UTC))
        logger.info(
            "[l4-broker-stuck-sweep] scanned=%d resolved=%d still_stuck=%d batch_limited=%s",
            result["scanned"],
            result["resolved"],
            result["still_stuck"],
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
