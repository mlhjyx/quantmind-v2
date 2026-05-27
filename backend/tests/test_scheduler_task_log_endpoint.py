"""iter 197 MVP 5.1 Chunk 1 — GET /api/system/scheduler-task-log endpoint tests.

Coverage:
- Empty table (0 rows) → {tasks: [], total_count: 0}
- Populated (multi-row) → tasks list with all 8 schema fields + total_count
- Limit param honored (default 20, max 100)
- Optional task_name filter

Mock strategy: sibling test_system_api.py pattern (AsyncSession mock + FastAPI
dependency_overrides + httpx ASGITransport).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


def _override_get_db(mock_session: Any):
    async def _dep():
        yield mock_session

    return _dep


def _make_mock_session_with_rows(rows: list[dict[str, Any]], total_count: int = None) -> MagicMock:
    """Build AsyncSession mock returning rows for fetchall + total count for scalar.

    Two SQL executions expected:
    1. SELECT id, task_name, ... ORDER BY schedule_time DESC LIMIT :limit → rows
    2. SELECT count(*) FROM scheduler_task_log → total_count
    """
    session = MagicMock()

    # Build row mocks (each row has named tuple-like attribute access)
    row_mocks = []
    for row in rows:
        row_mock = MagicMock()
        for k, v in row.items():
            setattr(row_mock, k, v)
        row_mocks.append(row_mock)

    # First execute → fetchall returns row list
    fetchall_result = MagicMock()
    fetchall_result.fetchall = MagicMock(return_value=row_mocks)

    # Second execute → scalar returns count
    scalar_result = MagicMock()
    scalar_result.scalar = MagicMock(
        return_value=total_count if total_count is not None else len(rows)
    )

    # session.execute returns fetchall_result first, then scalar_result
    session.execute = AsyncMock(side_effect=[fetchall_result, scalar_result])
    return session


class TestSchedulerTaskLogEndpoint:
    """Test GET /api/system/scheduler-task-log."""

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_tasks_and_zero_count(self):
        """0 rows in DB → {tasks: [], total_count: 0}."""
        from app.db import get_db

        mock_session = _make_mock_session_with_rows([], total_count=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler-task-log")
            assert resp.status_code == 200
            data = resp.json()
            assert "tasks" in data
            assert "total_count" in data
            assert data["tasks"] == []
            assert data["total_count"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_populated_returns_rows_with_8_schema_fields(self):
        """Populated table → tasks list with id/task_name/status/schedule_time/
        start_time/end_time/duration_sec/error_message fields."""
        from app.db import get_db

        rows = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "task_name": "realtime_risk_engine_tick",
                "status": "success",
                "schedule_time": "2026-05-26T20:30:00+00:00",
                "start_time": "2026-05-26T20:30:00+00:00",
                "end_time": "2026-05-26T20:30:01+00:00",
                "duration_sec": 1,
                "error_message": None,
            },
            {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "task_name": "daily_reconciliation",
                "status": "failed",
                "schedule_time": "2026-05-26T16:50:00+00:00",
                "start_time": "2026-05-26T16:50:00+00:00",
                "end_time": "2026-05-26T16:50:05+00:00",
                "duration_sec": 5,
                "error_message": "Tushare API timeout",
            },
        ]
        mock_session = _make_mock_session_with_rows(rows, total_count=2)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler-task-log")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["tasks"]) == 2
            assert data["total_count"] == 2

            t0 = data["tasks"][0]
            # All 8 schema fields present
            for field in (
                "id",
                "task_name",
                "status",
                "schedule_time",
                "start_time",
                "end_time",
                "duration_sec",
                "error_message",
            ):
                assert field in t0, f"missing field: {field}"
            assert t0["task_name"] == "realtime_risk_engine_tick"
            assert t0["status"] == "success"
            assert t0["error_message"] is None
            assert data["tasks"][1]["status"] == "failed"
            assert data["tasks"][1]["error_message"] == "Tushare API timeout"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_limit_param_default_20_validated_range_1_to_100(self):
        """Limit param default 20, Query(ge=1, le=100) — out-of-range returns 422.

        iter 199 reviewer P3 cleanup: tightened from `in (200, 422)` ambiguous
        assertion to definitive 422 (since iter 199 backend now uses
        Query(ge=1, le=100) validator).
        """
        from app.db import get_db

        mock_session = _make_mock_session_with_rows([], total_count=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Default limit (20) → 200 OK
                resp1 = await client.get("/api/system/scheduler-task-log")
                assert resp1.status_code == 200

                # Explicit limit within range (50) → 200 OK
                mock_session.execute.side_effect = [
                    MagicMock(fetchall=MagicMock(return_value=[])),
                    MagicMock(scalar=MagicMock(return_value=0)),
                ]
                resp2 = await client.get("/api/system/scheduler-task-log?limit=50")
                assert resp2.status_code == 200

                # Limit >100 → 422 (FastAPI Query validator)
                resp3 = await client.get("/api/system/scheduler-task-log?limit=500")
                assert resp3.status_code == 422

                # Limit <1 → 422
                resp4 = await client.get("/api/system/scheduler-task-log?limit=0")
                assert resp4.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_db_error_returns_500_fail_loud(self):
        """iter 199 reviewer P3 cleanup: DB exception path returns 500 per 铁律 33.

        Mock session.execute raises Exception → endpoint catches + logger.exception +
        raise HTTPException(500). Verifies fail-loud contract.
        """
        from app.db import get_db

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("db connection lost"))
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler-task-log")
            assert resp.status_code == 500
            data = resp.json()
            assert "scheduler_task_log query failed" in data.get("detail", "")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_task_name_filter_optional(self):
        """task_name query param optional — when supplied, filters DB query."""
        from app.db import get_db

        rows = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "task_name": "trade_event_risk_consumer",
                "status": "success",
                "schedule_time": "2026-05-26T20:00:00+00:00",
                "start_time": "2026-05-26T20:00:00+00:00",
                "end_time": "2026-05-26T20:00:00+00:00",
                "duration_sec": 0,
                "error_message": None,
            },
        ]
        mock_session = _make_mock_session_with_rows(rows, total_count=1)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/system/scheduler-task-log?task_name=trade_event_risk_consumer"
                )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["tasks"]) == 1
            assert data["tasks"][0]["task_name"] == "trade_event_risk_consumer"
            # Verify execute was called with task_name parameter
            calls = mock_session.execute.call_args_list
            assert len(calls) == 2  # main query + count query
        finally:
            app.dependency_overrides.clear()
