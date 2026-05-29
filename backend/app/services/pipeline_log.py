"""Pipeline decision log helpers.

PN-005 uses a per-run Redis list for the first usable log-history closure:
`pipeline:logs:{run_id}` stores newest-first JSON rows that match the frontend
`PipelineLogEntry` contract.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

PipelineLogLevel = Literal["info", "warning", "error", "decision"]
PIPELINE_LOG_MAXLEN = 10_000


def _get_pipeline_log_redis() -> Any:
    """Return a Redis client for pipeline logs.

    Tests monkeypatch this helper to avoid opening a real Redis connection.
    """
    import redis as redis_lib  # noqa: PLC0415

    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def pipeline_log_key(run_id: str) -> str:
    """Return the Redis list key for one pipeline run."""
    return f"pipeline:logs:{run_id}"


def emit_pipeline_log(
    *,
    run_id: str,
    agent: str,
    level: PipelineLogLevel,
    content: str,
    redis_client: Any | None = None,
    maxlen: int = PIPELINE_LOG_MAXLEN,
) -> bool:
    """Append a structured pipeline log line to Redis.

    This is observability-only. Redis failure must not roll back trigger,
    approve, or reject flows, so the helper emits a warning and returns False.
    """
    entry = {
        "id": uuid.uuid4().hex,
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "agent": agent,
        "level": level,
        "content": content,
    }
    try:
        client = redis_client or _get_pipeline_log_redis()
        key = pipeline_log_key(run_id)
        client.lpush(key, json.dumps(entry, ensure_ascii=False))
        client.ltrim(key, 0, maxlen - 1)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft observability path, warning emitted.
        logger.warning("pipeline_log_emit_failed run_id=%s error=%s", run_id, exc)
        return False
