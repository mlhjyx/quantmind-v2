"""iter 210 MVP 5.5 C1 — GET /api/system/beat-schedule endpoint tests.

Coverage:
- Empty CELERY_BEAT_SCHEDULE → {entries: [], total_count: 0}
- Populated (multi-entry) → entries with all 7 fields + total_count
- last_fire cross-ref from scheduler_task_log query
- DB error during last_fire query → degraded mode (entries still returned)

Mock strategy: patch CELERY_BEAT_SCHEDULE + AsyncSession + ASGITransport.

Patch target: `app.tasks.beat_schedule.CELERY_BEAT_SCHEDULE` (source module
attribute) — NOT `app.api.system.CELERY_BEAT_SCHEDULE`. The endpoint uses
`from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE` INSIDE the function
body (lazy import), which rebinds to function-local scope on each call. Patching
the source module is correct; patching `app.api.system` fails because the
attribute doesn't exist at module-level (lazy import never sets module attr).
Reviewer iter 210 P1 recommendation was incorrect for this pattern.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


def _override_get_db(mock_session: Any):
    async def _dep():
        yield mock_session

    return _dep


def _make_mock_session_for_last_fire(rows: list[dict[str, Any]]) -> MagicMock:
    """Mock AsyncSession for last_fire LATERAL JOIN query."""
    session = MagicMock()
    row_mocks = []
    for row in rows:
        m = MagicMock()
        for k, v in row.items():
            setattr(m, k, v)
        row_mocks.append(m)
    result = MagicMock()
    result.fetchall = MagicMock(return_value=row_mocks)
    session.execute = AsyncMock(return_value=result)
    return session


class TestBeatScheduleEndpoint:
    """Test GET /api/system/beat-schedule."""

    @pytest.mark.asyncio
    async def test_empty_beat_schedule_returns_empty_entries(self):
        """0 Beat entries → {entries: [], total_count: 0}."""
        from app.db import get_db

        mock_session = _make_mock_session_for_last_fire([])
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with patch("app.tasks.beat_schedule.CELERY_BEAT_SCHEDULE", {}):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/beat-schedule")
            assert resp.status_code == 200
            data = resp.json()
            assert data["entries"] == []
            assert data["total_count"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_populated_returns_entries_with_7_fields(self):
        """Populated Beat schedule → entries list with all 7 fields per entry."""
        from app.db import get_db

        # Mock crontab-like schedule object
        class MockSchedule:
            def __repr__(self) -> str:
                return "<crontab: */5 * * * * (m/h/d/dM/MY)>"

        fake_schedule = {
            "risk-l1-realtime-tick": {
                "task": "risk.realtime_risk_tick",
                "schedule": MockSchedule(),
                "options": {"queue": "default", "expires": 60},
            },
            "trade-event-risk-consumer-tick": {
                "task": "risk.trade_event_consumer_tick",
                "schedule": MockSchedule(),
                "options": {"queue": "default", "expires": 8},
            },
        }
        # Last_fire from scheduler_task_log
        rows = [
            {
                "task_name": "risk.realtime_risk_tick",
                "start_time": "2026-05-26T22:30:00+00:00",
                "status": "success",
            },
        ]
        mock_session = _make_mock_session_for_last_fire(rows)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with patch("app.tasks.beat_schedule.CELERY_BEAT_SCHEDULE", fake_schedule):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/beat-schedule")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 2
            assert len(data["entries"]) == 2

            # Verify 7 schema fields
            e0 = data["entries"][0]
            for field in (
                "beat_key",
                "task_name",
                "schedule_display",
                "expires_sec",
                "queue",
                "last_fire_time",
                "last_fire_status",
            ):
                assert field in e0, f"missing field: {field}"
            assert e0["queue"] == "default"
            # Entries sorted by beat_key alphabetically
            assert data["entries"][0]["beat_key"] == "risk-l1-realtime-tick"
            assert data["entries"][1]["beat_key"] == "trade-event-risk-consumer-tick"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_last_fire_cross_referenced_from_scheduler_task_log(self):
        """last_fire_time + last_fire_status populated from scheduler_task_log query."""
        from app.db import get_db

        class MockSchedule:
            def __repr__(self) -> str:
                return "<test schedule>"

        fake_schedule = {
            "task-A": {
                "task": "risk.task_a",
                "schedule": MockSchedule(),
                "options": {},
            },
            "task-B": {
                "task": "risk.task_b",
                "schedule": MockSchedule(),
                "options": {},
            },
        }
        rows = [
            {
                "task_name": "risk.task_a",
                "start_time": "2026-05-26T20:00:00+00:00",
                "status": "success",
            },
            {
                "task_name": "risk.task_b",
                "start_time": "2026-05-26T20:30:00+00:00",
                "status": "failed",
            },
        ]
        mock_session = _make_mock_session_for_last_fire(rows)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with patch("app.tasks.beat_schedule.CELERY_BEAT_SCHEDULE", fake_schedule):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/beat-schedule")
            assert resp.status_code == 200
            data = resp.json()
            # Find each task entry
            entries_by_key = {e["beat_key"]: e for e in data["entries"]}
            assert entries_by_key["task-A"]["last_fire_time"] == "2026-05-26T20:00:00+00:00"
            assert entries_by_key["task-A"]["last_fire_status"] == "success"
            assert entries_by_key["task-B"]["last_fire_time"] == "2026-05-26T20:30:00+00:00"
            assert entries_by_key["task-B"]["last_fire_status"] == "failed"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_db_error_degraded_mode_no_last_fire(self):
        """DB exception during last_fire query → degraded mode (entries still returned without last_fire)."""
        from app.db import get_db

        class MockSchedule:
            def __repr__(self) -> str:
                return "<test>"

        fake_schedule = {
            "task-X": {
                "task": "risk.task_x",
                "schedule": MockSchedule(),
                "options": {},
            },
        }
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("db down"))
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with patch("app.tasks.beat_schedule.CELERY_BEAT_SCHEDULE", fake_schedule):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/beat-schedule")
            # Degraded mode: returns 200 with entries (no last_fire) — silent_ok per 铁律 33
            # since Beat schedule list itself is still useful
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 1
            assert data["entries"][0]["last_fire_time"] is None
            assert data["entries"][0]["last_fire_status"] is None
        finally:
            app.dependency_overrides.clear()
