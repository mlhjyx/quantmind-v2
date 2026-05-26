"""iter 184 MVP 4.8 Phase J §1.5 — Trade event Redis Stream consumer helper.

XREADGROUP on qm:fill:executed (outbox publisher output since MVP 3.4 batch 5,
PR #130 2026-04-28). At-least-once delivery via consumer group
risk-engine-fill-consumer.

Manifest §1.5 claim "no event publish" was STALE per iter 183 §v9.49 reality
re-grounding catch — outbox publisher already wires qm:fill:executed. True
gap was 0 consumer on risk side. This module is the consumer.

Caller pattern: invoked from trade_event_risk_tasks Celery Beat task (10s).
Caller MUST XACK after successful processing via ack_fill_event helper.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from typing import Any

import redis

logger = logging.getLogger(__name__)

STREAM_NAME = "qm:fill:executed"
CONSUMER_GROUP = "risk-engine-fill-consumer"


def _default_consumer_name() -> str:
    """Reviewer P2-2 fix iter 184: unique consumer identity per worker process.

    Was hardcoded 'consumer-1' which breaks XPENDING/XCLAIM crash-recovery when
    multi-worker. Derived from hostname + pid so each Celery worker process
    has stable unique identity within the risk-engine-fill-consumer group.
    """
    return f"{socket.gethostname()}-{os.getpid()}"


# Module-level evaluated at first access (still lazy if caller imports module
# without invoking consume_fill_events). Stable per-process.
DEFAULT_CONSUMER_NAME = _default_consumer_name()


def _ensure_consumer_group(r: redis.Redis, stream: str, group: str) -> None:
    """Idempotent consumer group creation. MKSTREAM creates stream if missing.

    BUSYGROUP error is expected on re-call (group already exists) — swallow.
    Other ResponseError propagates (fail-loud per 铁律 33).
    """
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            return  # already exists
        raise


def consume_fill_events(
    r: redis.Redis,
    *,
    consumer_name: str = DEFAULT_CONSUMER_NAME,
    count: int = 100,
    block_ms: int = 0,  # non-blocking by default
) -> list[dict[str, Any]]:
    """Read pending fill events via XREADGROUP.

    Returns list of {event_id, data, stream} dicts. Auto-creates consumer group.
    Caller MUST XACK after processing via `ack_fill_event` helper.

    Reviewer P2-1 fix iter 184: removed `r=None` default — caller MUST pass
    redis client (singleton via `trade_event_risk_tasks._get_redis()`) to
    prevent connection leakage per-invocation in non-task callers.

    Args:
        r: redis.Redis client (caller-supplied singleton)
        consumer_name: consumer identity within group (default = hostname+pid;
            stable per worker process for XPENDING/XCLAIM crash-recovery)
        count: max events per XREADGROUP call (default 100)
        block_ms: blocking timeout in ms (default 0 = non-blocking immediate)

    Returns:
        list of {event_id: str, data: dict, stream: str} (empty if no pending)
    """
    _ensure_consumer_group(r, STREAM_NAME, CONSUMER_GROUP)

    streams = {STREAM_NAME: ">"}  # ">" = only new messages for this consumer
    raw = r.xreadgroup(
        CONSUMER_GROUP,
        consumer_name,
        streams,
        count=count,
        block=block_ms,
    )
    if not raw:
        return []

    out: list[dict[str, Any]] = []
    for stream_name, messages in raw:
        for msg_id, fields in messages:
            data = _parse_event_fields(fields)
            out.append({"event_id": msg_id, "data": data, "stream": stream_name})
    return out


def _parse_event_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Parse stream message fields. Outbox publishes JSON payload under 'payload' key."""
    raw_payload = fields.get("payload") or fields.get("data") or "{}"
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8")
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning(
            "[trade-event-consumer] payload not JSON (raw 200 chars): %s",
            raw_payload[:200] if isinstance(raw_payload, str) else str(raw_payload)[:200],
        )
        return {"_raw_payload": raw_payload}


def ack_fill_event(r: redis.Redis, event_id: str) -> None:
    """XACK after successful processing per consumer group at-least-once contract."""
    r.xack(STREAM_NAME, CONSUMER_GROUP, event_id)
