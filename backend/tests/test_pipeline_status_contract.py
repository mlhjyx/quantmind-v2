"""Tests for D1 /api/pipeline/status contract refactor (PN-004 iter 15).

Coverage (PN-004 §4, 4 cases):
1. No active run + not paused → all NEW frontend-aligned keys present with correct defaults.
2. Active running run → is_running=True, run_id populated, last_run_at = started_at.
3. Paused state surface → is_paused=True, paused_at + paused_reason populated.
4. _gp_weekly_schedule_next unit → cron correct + next_run_at always future Sunday 22:00 SH.

Pattern: 沿用 test_pipeline_pause.py + test_pipeline_automation_level.py —
dependency_overrides + AsyncMock + ASGITransport (mock-based, no DB).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")
from httpx import ASGITransport, AsyncClient

from app.api.pipeline import _gp_weekly_schedule_next
from app.db import get_db
from app.main import app

_SH = timezone(timedelta(hours=8))


def _pause_row(paused_at: Any, paused_reason: str | None) -> MagicMock:
    """Mock Row for SELECT paused_at, paused_reason (PN-003)."""
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: [paused_at, paused_reason][k]
    return row


def _auto_row(level: str) -> MagicMock:
    """Mock Row for SELECT automation_level (PN-001)."""
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: [level][k]
    return row


def _make_session_for_status(
    *,
    paused_at: Any = None,
    paused_reason: str | None = None,
    automation_level: str = "L0",
    run_row: dict[str, Any] | None = None,
) -> AsyncMock:
    """Build a mock session that satisfies get_pipeline_status's reads.

    Call sequence inside the handler:
      1. _fetch_latest_run(status_filter='running')  →  None or run row mock
      2. (if 1 was None) _fetch_latest_run(status_filter=None)  →  same or None
      3. _read_pause_state SELECT  →  pause row mock
      4. _read_automation_level SELECT  →  automation row mock

    Frontend handler internals call _fetch_latest_run twice when no run; once when
    a run exists. We attach side_effects accordingly.
    """
    session = AsyncMock()
    results: list[MagicMock] = []

    if run_row is None:
        # Two _fetch_latest_run calls (both None) — each calls session.execute once
        for _ in range(2):
            r = MagicMock()
            r.mappings.return_value.first = MagicMock(return_value=None)
            r.first = MagicMock(return_value=None)
            results.append(r)
    else:
        # One _fetch_latest_run call returning the run row
        r = MagicMock()
        r.mappings.return_value.first = MagicMock(return_value=run_row)
        r.first = MagicMock(return_value=run_row)
        results.append(r)

    # _read_pause_state SELECT
    pause_result = MagicMock()
    pause_result.first.return_value = _pause_row(paused_at, paused_reason)
    results.append(pause_result)

    # _read_automation_level SELECT
    auto_result = MagicMock()
    auto_result.first.return_value = _auto_row(automation_level)
    results.append(auto_result)

    session.execute.side_effect = results
    return session


@pytest.fixture
async def client() -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_status_no_run_not_paused(client: AsyncClient) -> None:
    """No active run + not paused → all NEW keys present with sensible defaults."""
    session = _make_session_for_status(
        paused_at=None, paused_reason=None, automation_level="L0", run_row=None
    )
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.get("/api/pipeline/status")
        assert response.status_code == 200, response.text
        body = response.json()

        # NEW frontend-aligned keys
        assert body["run_id"] is None
        assert body["is_running"] is False
        assert body["is_paused"] is False
        assert body["automation_level"] == "L0"
        assert body["nodes"] == []
        assert body["schedule_cron"] == "0 22 * * 0"
        assert body["next_run_at"] is not None  # always populated
        assert body["last_run_at"] is None
        assert body["current_node"] is None
        assert body["paused_at"] is None
        assert body["paused_reason"] is None

        # LEGACY aliases still present (1-sprint backward compat per PN-004 §2.2)
        assert body["active_run_id"] is None
        assert body["status"] == "idle"
        assert body["node_statuses"] == {}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_status_active_running_run(client: AsyncClient) -> None:
    """Active running run → is_running=True, run_id populated, last_run_at = started_at."""
    started_at = datetime(2026, 5, 24, 1, 0, 0, tzinfo=UTC)
    run_row = {
        "run_id": "gp_2026w21_abc123",
        "engine": "gp",
        "status": "running",
        "stats": {
            "current_node": "G3",
            "node_statuses": {"G1": "done", "G2": "done", "G3": "running"},
            "total_evaluated": 100,
            "passed_gate": 5,
        },
        "config": {"generations": 50, "population": 100, "time_budget_minutes": 120},
        "started_at": started_at,
        "finished_at": None,
        "error_message": None,
    }
    session = _make_session_for_status(automation_level="L2", run_row=run_row)
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.get("/api/pipeline/status")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["run_id"] == "gp_2026w21_abc123"
        assert body["is_running"] is True
        assert body["is_paused"] is False
        assert body["automation_level"] == "L2"
        assert body["current_node"] == "G3"
        assert len(body["nodes"]) == 3
        assert body["nodes"][0] == {"name": "G1", "status": "done"}
        assert body["last_run_at"] == started_at.isoformat()
        # Legacy aliases
        assert body["active_run_id"] == "gp_2026w21_abc123"
        assert body["active_engine"] == "gp"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_status_paused_surfaces_paused_fields(client: AsyncClient) -> None:
    """Paused state → is_paused=True, paused_at + paused_reason populated."""
    paused_at = datetime(2026, 5, 24, 0, 30, 0, tzinfo=UTC)
    session = _make_session_for_status(
        paused_at=paused_at,
        paused_reason="maintenance window",
        automation_level="L0",
        run_row=None,
    )
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.get("/api/pipeline/status")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["is_paused"] is True
        assert body["paused_at"] == paused_at.isoformat()
        assert body["paused_reason"] == "maintenance window"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_gp_weekly_schedule_next_unit() -> None:
    """_gp_weekly_schedule_next: cron correct + next_run_at always future Sunday 22:00 SH."""
    cron_str, next_iso = _gp_weekly_schedule_next()
    assert cron_str == "0 22 * * 0"

    # Parse next_iso back; assert it's after now (future), on a Sunday, at 22:00 SH local.
    next_dt_utc = datetime.fromisoformat(next_iso)
    now_utc = datetime.now(tz=UTC)
    assert next_dt_utc > now_utc, "next_run_at must be in the future"
    assert (next_dt_utc - now_utc) <= timedelta(days=7), (
        "next_run_at must be within next 7 days (weekly schedule)"
    )

    next_sh = next_dt_utc.astimezone(_SH)
    assert next_sh.weekday() == 6, f"expected Sunday (6), got weekday={next_sh.weekday()}"
    assert next_sh.hour == 22 and next_sh.minute == 0, (
        f"expected 22:00 SH, got {next_sh.hour}:{next_sh.minute:02d}"
    )
