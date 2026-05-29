"""Tests for Pipeline decision log HTTP backfill (PN-005 O7)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import pipeline as pipeline_api
from app.main import app
from app.services.pipeline_log import emit_pipeline_log, pipeline_log_key


class _FakeRedis:
    def __init__(self, entries: list[str] | None = None, exc: Exception | None = None) -> None:
        self.entries = entries or []
        self.exc = exc
        self.calls: list[tuple[str, int, int]] = []
        self.writes: list[tuple[str, str]] = []
        self.trims: list[tuple[str, int, int]] = []

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        self.calls.append((key, start, end))
        if self.exc is not None:
            raise self.exc
        return self.entries[start : end + 1]

    def lpush(self, key: str, value: str) -> int:
        self.writes.append((key, value))
        if self.exc is not None:
            raise self.exc
        self.entries.insert(0, value)
        return len(self.entries)

    def ltrim(self, key: str, start: int, end: int) -> bool:
        self.trims.append((key, start, end))
        if self.exc is not None:
            raise self.exc
        self.entries = self.entries[start : end + 1]
        return True


@pytest.mark.asyncio
async def test_get_pipeline_logs_reads_redis_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET contract source reads pipeline:logs:{run_id}, newest first."""
    redis = _FakeRedis(
        [
            json.dumps(
                {
                    "id": "log-1",
                    "run_id": "gp_2026w22_abcd",
                    "timestamp": "2026-05-28T10:00:00+08:00",
                    "agent": "gate",
                    "level": "warn",
                    "content": "IC gate warning",
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-05-28T10:01:00+08:00",
                    "source": "composer",
                    "level": "decision",
                    "message": "accepted factor candidate",
                }
            ),
        ]
    )
    monkeypatch.setattr(pipeline_api, "_get_pipeline_log_redis", lambda: redis)

    result = await pipeline_api.get_pipeline_logs("gp_2026w22_abcd", limit=2)

    assert redis.calls == [("pipeline:logs:gp_2026w22_abcd", 0, 1)]
    assert [entry.model_dump() for entry in result] == [
        {
            "id": "log-1",
            "run_id": "gp_2026w22_abcd",
            "timestamp": "2026-05-28T10:00:00+08:00",
            "agent": "gate",
            "level": "warning",
            "content": "IC gate warning",
        },
        {
            "id": "gp_2026w22_abcd:1",
            "run_id": "gp_2026w22_abcd",
            "timestamp": "2026-05-28T10:01:00+08:00",
            "agent": "composer",
            "level": "decision",
            "content": "accepted factor candidate",
        },
    ]


@pytest.mark.asyncio
async def test_get_pipeline_logs_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed Redis rows are warning-level noise, not a 500 for the UI."""
    redis = _FakeRedis(
        [
            "{not-json",
            json.dumps({"content": "still returned"}),
        ]
    )
    monkeypatch.setattr(pipeline_api, "_get_pipeline_log_redis", lambda: redis)

    result = await pipeline_api.get_pipeline_logs("run-1", limit=200)

    assert len(result) == 1
    assert result[0].content == "still returned"
    assert result[0].run_id == "run-1"


@pytest.mark.asyncio
async def test_get_pipeline_logs_fail_soft_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis transport failure returns an empty log list for observability-only UI."""
    redis = _FakeRedis(exc=ConnectionError("redis down"))
    monkeypatch.setattr(pipeline_api, "_get_pipeline_log_redis", lambda: redis)

    result = await pipeline_api.get_pipeline_logs("run-1", limit=200)

    assert result == []


def test_emit_pipeline_log_writes_json_and_trims() -> None:
    """Emission helper provides real product value for the HTTP backfill endpoint."""
    redis = _FakeRedis()

    ok = emit_pipeline_log(
        run_id="run-1",
        agent="approval",
        level="decision",
        content="Approved factor",
        redis_client=redis,
        maxlen=3,
    )

    assert ok is True
    assert redis.trims == [("pipeline:logs:run-1", 0, 2)]
    key, value = redis.writes[0]
    assert key == pipeline_log_key("run-1")
    payload: dict[str, Any] = json.loads(value)
    assert payload["run_id"] == "run-1"
    assert payload["agent"] == "approval"
    assert payload["level"] == "decision"
    assert payload["content"] == "Approved factor"
    assert payload["id"]
    assert payload["timestamp"]


def test_emit_pipeline_log_fail_soft() -> None:
    """Redis failure must not break trigger/approve/reject flows."""
    redis = _FakeRedis(exc=ConnectionError("redis down"))

    ok = emit_pipeline_log(
        run_id="run-1",
        agent="orchestrator",
        level="info",
        content="submitted",
        redis_client=redis,
    )

    assert ok is False


@pytest.mark.asyncio
async def test_pipeline_logs_http_endpoint_returns_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASGI smoke verifies the route is registered, not only the handler helper."""
    redis = _FakeRedis(
        [
            json.dumps(
                {
                    "id": "log-http",
                    "run_id": "run-http",
                    "timestamp": "2026-05-28T10:02:00+08:00",
                    "agent": "orchestrator",
                    "level": "info",
                    "content": "submitted",
                }
            )
        ]
    )
    monkeypatch.setattr(pipeline_api, "_get_pipeline_log_redis", lambda: redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/pipeline/run-http/logs?limit=1")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": "log-http",
            "run_id": "run-http",
            "timestamp": "2026-05-28T10:02:00+08:00",
            "agent": "orchestrator",
            "level": "info",
            "content": "submitted",
        }
    ]
