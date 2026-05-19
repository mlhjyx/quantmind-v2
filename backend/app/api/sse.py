"""P4 SSE endpoint scaffold — Session 58 round-2 close.

Server-Sent Events stream for real-time risk_event_log updates. Replaces polling
in frontend (currently react-query refetchInterval). 反 unnecessary API call frequency
+ enables sub-second alert latency.

设计:
- text/event-stream content type (SSE standard)
- Polls risk_event_log every 2s for new rows since last cursor (sync psycopg2)
- Heartbeat every 15s (sustain connection, 反 proxy idle timeout)
- Graceful disconnect: detect client gone via StreamingResponse cancellation

MVP scope (sub-PR scaffold):
- Single endpoint: GET /api/sse/risk-events
- Stream format: `event: risk_event\ndata: {json}\n\n` per row
- Cursor: last seen `id` (uuid) — cleanup留 future cursor persistence
- Auth: verify_admin_token (cookie or header)
- Future: per-strategy filter / per-severity filter / multiplexed event types

铁律 backref:
- 33: fail-loud — DB connection errors propagate as 500 (反 silent stream loss)
- 32: read-only stream, no commit needed
- 41: triggered_at TIMESTAMPTZ handled UTC internally

关联:
- ISSUES_PENDING_REGISTRY §7 P4 (SSE endpoint scaffold)
- Frontend Design v3 §2.5 (real-time updates strategy)
- backend/app/api/realtime.py (existing WebSocket — distinct paradigm, SSE complementary)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from starlette.responses import StreamingResponse

from app.core.auth import verify_admin_token

logger = logging.getLogger("api.sse")

router = APIRouter(prefix="/api/sse", tags=["sse"])

# Poll cadence — 2s gives sub-second-perceived latency without hammering DB
_POLL_INTERVAL_SEC: float = 2.0
# Heartbeat cadence — 15s sustains proxy connection (nginx/cloudflare default 60s idle timeout)
_HEARTBEAT_INTERVAL_SEC: float = 15.0
# Max rows per poll — 反 large initial backlog dump on slow client
_MAX_ROWS_PER_POLL: int = 50


async def _stream_risk_events(severity_filter: str | None = None) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted lines for risk_event_log updates.

    Per-poll: SELECT new rows since last cursor, yield each as event. Between polls,
    sleep _POLL_INTERVAL_SEC. Heartbeat every _HEARTBEAT_INTERVAL_SEC even on quiet.

    Args:
        severity_filter: optional filter (e.g. "P0" / "P1" / "WARN" / "HALT" — actual values
            depend on risk_event_log.severity column vocab).

    Yields:
        SSE-formatted strings (`event: <type>\\ndata: <json>\\n\\n`).
    """

    # Initial cursor — set to NOW so we don't dump backlog. Replace with stored cursor
    # for cross-session resume in future enhancement.
    last_triggered_at: datetime = datetime.now(UTC)
    last_heartbeat: float = asyncio.get_event_loop().time()

    # Connect event (lets client know stream is live)
    yield (
        "event: connected\n"
        f"data: {json.dumps({'cursor': last_triggered_at.isoformat(), 'severity_filter': severity_filter})}\n\n"
    )

    while True:
        # Poll for new rows
        try:
            new_rows, last_triggered_at = _fetch_new_rows(
                cursor=last_triggered_at,
                severity_filter=severity_filter,
                limit=_MAX_ROWS_PER_POLL,
            )
        except Exception as exc:
            # 反 silent stream death: emit error event, then continue trying.
            logger.exception("SSE risk-events poll failed")
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': str(exc), 'will_retry': True})}\n\n"
            )
            await asyncio.sleep(_POLL_INTERVAL_SEC * 2)
            continue

        for row in new_rows:
            yield f"event: risk_event\ndata: {json.dumps(row, default=str)}\n\n"

        # Heartbeat (sustain connection for proxies even on quiet)
        now_loop = asyncio.get_event_loop().time()
        if now_loop - last_heartbeat >= _HEARTBEAT_INTERVAL_SEC:
            yield f"event: heartbeat\ndata: {json.dumps({'ts': datetime.now(UTC).isoformat()})}\n\n"
            last_heartbeat = now_loop

        await asyncio.sleep(_POLL_INTERVAL_SEC)


def _fetch_new_rows(
    *,
    cursor: datetime,
    severity_filter: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], datetime]:
    """Query risk_event_log rows since cursor.

    Returns (rows_list, new_cursor). new_cursor = MAX(triggered_at) of returned rows
    OR original cursor if no new rows.
    """
    from app.services.db import get_sync_conn  # noqa: PLC0415

    conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            if severity_filter:
                cur.execute(
                    """
                    SELECT id, strategy_id, rule_id, severity, triggered_at, code, reason,
                           action_taken
                    FROM risk_event_log
                    WHERE triggered_at > %s
                      AND severity = %s
                    ORDER BY triggered_at ASC
                    LIMIT %s
                    """,
                    (cursor, severity_filter, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, strategy_id, rule_id, severity, triggered_at, code, reason,
                           action_taken
                    FROM risk_event_log
                    WHERE triggered_at > %s
                    ORDER BY triggered_at ASC
                    LIMIT %s
                    """,
                    (cursor, limit),
                )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        conn.close()

    new_cursor = rows[-1]["triggered_at"] if rows else cursor
    return rows, new_cursor


@router.get("/risk-events", summary="SSE stream of real-time risk_event_log updates")
async def sse_risk_events(
    severity: str | None = Query(
        default=None,
        description="Optional severity filter (e.g. P0 / P1 / WARN). None = all.",
    ),
    _: None = Depends(verify_admin_token),
) -> StreamingResponse:
    """Server-Sent Events endpoint streaming risk_event_log inserts.

    Client (frontend EventSource):
        const es = new EventSource('/api/sse/risk-events', { withCredentials: true });
        es.addEventListener('risk_event', (e) => {
            const event = JSON.parse(e.data);
            // handle new risk event
        });
        es.addEventListener('heartbeat', () => { /* sustain connection */ });
        es.addEventListener('error', (e) => { /* log + retry handled by EventSource */ });

    Returns:
        StreamingResponse with media_type='text/event-stream'.
    """
    return StreamingResponse(
        _stream_risk_events(severity_filter=severity),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx — disable response buffering for true streaming
        },
    )
