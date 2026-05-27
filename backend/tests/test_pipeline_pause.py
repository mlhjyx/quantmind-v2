"""Tests for D1 O3 pipeline pause gate (PN-003 iter 12).

Coverage (PN-003 §5, 6 cases):
1. POST /pause with empty body sets paused_at, reason=None.
2. POST /pause with reason persists reason.
3. POST /pause when already paused is idempotent (no overwrite of paused_at).
4. POST /resume when paused clears paused_at to None.
5. POST /resume when not paused is idempotent (200, paused_at=None).
6. POST /trigger when paused returns 409.

Pattern: 沿用 test_pipeline_automation_level.py — dependency_overrides
+ AsyncMock + ASGITransport (mock-based, no DB).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")
from httpx import ASGITransport, AsyncClient

from app.api.pipeline import _require_local
from app.db import get_db
from app.main import app

_FIXED_PAUSED_AT = datetime(2026, 5, 24, 0, 30, 0, tzinfo=UTC)


def _mock_pause_row(paused_at: Any, paused_reason: str | None) -> MagicMock:
    """Tuple-like Row mock for SELECT paused_at, paused_reason."""
    row = MagicMock()

    def _getitem(k: int) -> Any:
        if k == 0:
            return paused_at
        if k == 1:
            return paused_reason
        raise IndexError(f"Row has only 2 columns (paused_at, paused_reason), got {k}")

    row.__getitem__.side_effect = _getitem
    return row


def _mock_session(rows_seq: list[Any]) -> MagicMock:
    """Mock session where successive execute() calls return result mocks.

    Each entry in rows_seq becomes the .first() return value of one execute().
    The handler calls execute() for each SELECT *and* each INSERT — so the
    sequence must include a placeholder (use `None`) for every INSERT/UPDATE
    call in between SELECTs. INSERT-stage placeholders need a result mock too
    or the AsyncMock iterator will raise StopAsyncIteration.
    """
    session = AsyncMock()
    results = []
    for r in rows_seq:
        result_mock = MagicMock()
        result_mock.first.return_value = r
        results.append(result_mock)
    session.execute.side_effect = results
    session.commit = AsyncMock()
    return session


def _insert_placeholder() -> Any:
    """Sentinel returned by .first() for INSERT-stage calls (value unread)."""
    return None


@pytest.fixture
def override_local() -> Any:
    """Override _require_local to bypass IP check in tests."""
    app.dependency_overrides[_require_local] = lambda: None
    yield
    app.dependency_overrides.pop(_require_local, None)


@pytest.fixture
async def client() -> Any:
    """Async HTTP client wrapping the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_pause_empty_body_sets_paused_at(client: AsyncClient, override_local: Any) -> None:
    """POST /pause with empty body sets paused_at and reason=None."""
    # Handler execute() sequence: (1) SELECT pre-state → unpaused row,
    # (2) INSERT/UPSERT → placeholder, (3) SELECT post-state → paused row.
    session = _mock_session(
        [
            _mock_pause_row(None, None),
            _insert_placeholder(),
            _mock_pause_row(_FIXED_PAUSED_AT, None),
        ]
    )
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post("/api/pipeline/pause", json={})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["paused_at"] is not None
        assert body["paused_reason"] is None
        assert session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_pause_with_reason_persists_reason(client: AsyncClient, override_local: Any) -> None:
    """POST /pause with reason persists the reason string."""
    session = _mock_session(
        [
            _mock_pause_row(None, None),
            _insert_placeholder(),
            _mock_pause_row(_FIXED_PAUSED_AT, "maintenance window"),
        ]
    )
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post(
            "/api/pipeline/pause",
            json={"reason": "maintenance window"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["paused_reason"] == "maintenance window"
        # Verify the INSERT was attempted with the reason payload
        first_insert_call = session.execute.call_args_list[1]
        assert first_insert_call.args[1] == {"reason": "maintenance window"}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_pause_when_already_paused_is_idempotent(
    client: AsyncClient, override_local: Any
) -> None:
    """POST /pause when already paused returns current state, no overwrite.

    Only the initial SELECT should execute; no INSERT/UPDATE, no commit.
    """
    session = _mock_session([_mock_pause_row(_FIXED_PAUSED_AT, "old reason")])
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post(
            "/api/pipeline/pause",
            json={"reason": "new reason that must NOT overwrite"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Reason stays at "old reason" — idempotent no-overwrite
        assert body["paused_reason"] == "old reason"
        # Only 1 execute (the initial SELECT), 0 commits
        assert session.execute.call_count == 1
        assert not session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_resume_when_paused_clears_state(client: AsyncClient, override_local: Any) -> None:
    """POST /resume clears paused_at + paused_reason."""
    session = _mock_session(
        [_insert_placeholder()]
    )  # resume body uses 1 execute (UPSERT), no SELECT
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post("/api/pipeline/resume")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["paused_at"] is None
        assert body["paused_reason"] is None
        assert session.execute.called
        assert session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_resume_when_not_paused_is_idempotent(
    client: AsyncClient, override_local: Any
) -> None:
    """POST /resume when already active is idempotent (200, null state)."""
    session = _mock_session([_insert_placeholder()])
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post("/api/pipeline/resume")
        assert response.status_code == 200, response.text
        # Same NULL state as paused-clear path; the SQL is unconditional UPSERT,
        # so execute is called regardless and idempotency lives at the SQL level.
        body = response.json()
        assert body == {"paused_at": None, "paused_reason": None}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_trigger_returns_409_when_paused(
    client: AsyncClient, override_local: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /trigger when paused returns 409 via service-level _is_paused gate.

    Mocks MiningService.start_mining_task to raise RuntimeError as it would
    when the gate trips; the route layer must convert it to 409 (matching
    the existing engine-running-conflict pattern at pipeline.py:171).
    """
    from app.services import mining_service as mining_service_mod

    async def _raise_paused(self: Any, engine: str, config: dict[str, Any]) -> Any:
        raise RuntimeError(
            f"Pipeline paused since {_FIXED_PAUSED_AT.isoformat()} (maintenance); "
            "call POST /api/pipeline/resume before triggering."
        )

    monkeypatch.setattr(
        mining_service_mod.MiningService,
        "start_mining_task",
        _raise_paused,
    )

    # get_db dependency must still resolve to *something* — provide a stub
    session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.post(
            "/api/pipeline/trigger",
            json={"engine": "gp", "config": {}},
        )
        assert response.status_code == 409, response.text
        assert "paused" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db, None)
