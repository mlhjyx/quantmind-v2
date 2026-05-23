"""Tests for D1 O8 automation-level persistence (PN-001 iter 10).

Coverage:
- GET returns persisted level
- PUT updates level and returns new value
- 422 on invalid level (Literal["L0".."L4"] enforces enum)
- GET defensive default when DB has no row

Pattern: 沿用 test_backtest_api.py — dependency_overrides + AsyncMock + ASGITransport.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")
from httpx import ASGITransport, AsyncClient

from app.api.pipeline import _require_local
from app.db import get_db
from app.main import app


def _mock_row(level: str) -> MagicMock:
    """Tuple-like Row mock with strict index check (P2-1 review fix).

    Returns `level` only for `row[0]`; raises IndexError for any other key.
    This keeps the test honest: if the handler is later changed to use a
    different access pattern (row[1] / row.attr / row['name']), the test
    will fail loudly rather than silently passing.
    """
    row = MagicMock()

    def _getitem(k: int) -> str:
        if k == 0:
            return level
        raise IndexError(f"Row has only 1 column (automation_level), got index {k}")

    row.__getitem__.side_effect = _getitem
    return row


def _mock_session_with_level(level: str) -> MagicMock:
    """Mock session whose execute().first() returns a tuple-like Row at index 0."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.first.return_value = _mock_row(level)
    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    return session


def _mock_session_empty() -> MagicMock:
    """Mock session whose execute().first() returns None (no row)."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.first.return_value = None
    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    return session


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
async def test_get_automation_level_returns_persisted_value(client: AsyncClient) -> None:
    """GET /api/pipeline/automation-level returns the persisted level."""
    session = _mock_session_with_level("L2")
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.get("/api/pipeline/automation-level")
        assert response.status_code == 200, response.text
        assert response.json() == {"level": "L2"}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_automation_level_default_when_no_row(client: AsyncClient) -> None:
    """GET defensive default (L0) when pipeline_settings has no row."""
    session = _mock_session_empty()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.get("/api/pipeline/automation-level")
        assert response.status_code == 200, response.text
        assert response.json() == {"level": "L0"}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_put_automation_level_updates_and_returns(
    client: AsyncClient, override_local: Any
) -> None:
    """PUT updates the persisted value and echoes it back."""
    session = _mock_session_with_level("L3")  # post-update state
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.put(
            "/api/pipeline/automation-level",
            json={"level": "L3"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"level": "L3"}
        # Verify UPSERT was attempted (execute called) + commit was called
        assert session.execute.called
        assert session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_put_automation_level_invalid_returns_422(
    client: AsyncClient, override_local: Any
) -> None:
    """Invalid level (out of enum) is rejected with 422 by Pydantic Literal."""
    session = _mock_session_with_level("L0")
    app.dependency_overrides[get_db] = lambda: session
    try:
        # L5 is not in L0-L4 enum
        resp_l5 = await client.put(
            "/api/pipeline/automation-level",
            json={"level": "L5"},
        )
        assert resp_l5.status_code == 422

        # Non-enum string
        resp_foo = await client.put(
            "/api/pipeline/automation-level",
            json={"level": "foo"},
        )
        assert resp_foo.status_code == 422

        # 422 path should NOT have called execute (pydantic rejects before handler)
        assert not session.execute.called
        assert not session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_put_automation_level_403_for_non_localhost() -> None:
    """PUT from non-localhost IP returns 403 via _require_local guard (P2-2 review fix).

    Pins the security contract: removing `_require_local` from the PUT handler
    would let this test fail. Uses ASGITransport client tuple to spoof a remote IP.
    """
    session = _mock_session_with_level("L0")
    app.dependency_overrides[get_db] = lambda: session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("8.8.8.8", 12345)),
            base_url="http://test",
        ) as remote_client:
            response = await remote_client.put(
                "/api/pipeline/automation-level",
                json={"level": "L2"},
            )
            assert response.status_code == 403, response.text
            # Mutation must NOT have happened
            assert not session.execute.called
            assert not session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)
