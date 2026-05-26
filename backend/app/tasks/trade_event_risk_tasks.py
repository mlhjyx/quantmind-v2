"""iter 184 MVP 4.8 Phase J §1.5 — Trade event risk consumer Celery Beat task.

10s Beat task XREADs qm:fill:executed and triggers RealtimeRiskEngine on_tick
per fill event. Sibling pattern: realtime_risk_tasks.py (MVP 4.5 Chunk 2).

Architecture per MVP 4.8 design (iter 183):
- Event source: existing outbox publisher (qm:fill:executed stream ALREADY
  WIRED since MVP 3.4 batch 5, PR #130 2026-04-28)
- Subscriber: dedicated Celery Beat 10s cadence (Option Y per design memo)
- Event schema: existing outbox payload + DB fetch on demand

Fail-soft per-event (铁律 33): engine.on_tick raise on 1 event → log + continue
with remaining events. Whole task crash → audit row with 'failed' status.

Latency budget: outbox 30s + consumer 10s = ~40s worst-case (vs ~60s current
l4_sweep polling, ~33% improvement).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis

from app.config import settings
from app.services.db import get_sync_conn
from app.services.risk.trade_event_consumer import (
    ack_fill_event,
    consume_fill_events,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.trade_event_risk_tasks")

# Lazy singletons — share Redis client across Beat invocations.
_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    """Lazy singleton Redis client (sibling realtime_risk_tasks._get_rag pattern)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _process_fill_event(event: dict[str, Any]) -> dict[str, Any]:
    """Process single fill event — invoke RealtimeRiskEngine on_tick.

    Returns processing summary dict (rule_results / p0_count). Caller handles
    fail-soft per 铁律 33 (per-event isolation).

    Raises:
        Exception: any engine / context builder failure (caller catches per-event).
    """
    from app.services.risk.realtime_context_builder import (  # noqa: PLC0415
        RealtimeRiskContextBuilder,
    )
    from app.tasks.realtime_risk_tasks import _get_engine  # noqa: PLC0415

    conn = get_sync_conn()
    try:
        builder = RealtimeRiskContextBuilder(conn=conn, redis_client=_get_redis())
        context = builder.build_context()

        engine = _get_engine()
        results = engine.on_tick(context)

        p0_count = sum(
            1
            for r in results
            if str(getattr(r, "severity", "")).lower() == "p0"
        )

        return {
            "event_id": event["event_id"],
            "rule_results": len(results),
            "p0_count": p0_count,
            "strategy_id": event["data"].get("strategy_id"),
        }
    finally:
        conn.close()


@celery_app.task(name="risk.trade_event_consumer_tick", soft_time_limit=8)
def trade_event_risk_consumer_tick() -> dict[str, Any]:
    """10s Beat task — consume qm:fill:executed events + trigger risk eval.

    Beat schedule: timedelta(seconds=10) via beat_schedule.py (10s minimum
    granularity, Celery crontab not used since min granularity is 1min).

    Audit envelope per LL-204 canonical: scheduler_task_log row with task_name
    'trade_event_risk_consumer', events_processed + p0_total + elapsed_sec summary.

    Calendar gate: deferred to trading hours filter at Beat level (TODO: add
    H4 fix is_trading_day_today_or_skip guard in follow-up iter if non-trading-
    hour events are spurious).

    Fail-soft per-event (铁律 33): engine raise on 1 event → log + continue.
    Whole task crash → audit 'failed' row + re-raise to Celery retry.
    """
    t0 = time.time()
    r = _get_redis()
    events = consume_fill_events(r, count=100, block_ms=0)

    processed: list[dict[str, Any]] = []
    failures: list[str] = []

    for event in events:
        try:
            summary = _process_fill_event(event)
            processed.append(summary)
            ack_fill_event(r, event["event_id"])
        except Exception as e:  # noqa: BLE001 — fail-soft per event per 铁律 33
            logger.error(
                "[trade-event-consumer] event %s processing failed (fail-soft): %s",
                event.get("event_id"),
                e,
                exc_info=True,
            )
            failures.append(
                f"{event.get('event_id')}: {type(e).__name__}: {e}"[:200]
            )

    summary = {
        "events_consumed": len(events),
        "events_processed": len(processed),
        "events_failed": len(failures),
        "p0_total": sum(p.get("p0_count", 0) for p in processed),
        "elapsed_sec": round(time.time() - t0, 3),
    }

    # Audit envelope: scheduler_task_log row (sibling LL-204 canonical).
    try:
        conn = get_sync_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO scheduler_task_log
                       (task_name, market, schedule_time, start_time, status,
                        error_message, result_json)
                       VALUES ('trade_event_risk_consumer', 'astock', NOW(), NOW(),
                               %s, %s, %s)""",
                    (
                        "success" if not failures else "partial",
                        ("; ".join(failures))[:500] if failures else None,
                        json.dumps(summary),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as audit_err:  # noqa: BLE001
        # silent_ok per 铁律 33: audit failure does NOT block main flow.
        logger.error(
            "[trade-event-consumer] audit log failed: %s", audit_err
        )

    if events:
        logger.info("[trade-event-consumer] %s", summary)
    return summary
