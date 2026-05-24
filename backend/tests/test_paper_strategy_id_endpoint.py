"""Tests for GET /api/system/settings/paper-strategy-id (iter 39).

Closes iter 35 DEFAULT_STRATEGY_ID frontend placeholder gap — backend exposes
settings.PAPER_STRATEGY_ID + configured sentinel for frontend consumer wire.

Coverage:
  - configured case: settings.PAPER_STRATEGY_ID="some-uuid" → 200 + configured=True
  - unconfigured case: settings.PAPER_STRATEGY_ID="" → 200 + configured=False + empty sid
  - response shape: paper_strategy_id + configured + source provenance
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.mark.asyncio
async def test_get_paper_strategy_id_configured(monkeypatch):
    """settings.PAPER_STRATEGY_ID set → configured=True + value passthrough."""
    from app.config import settings

    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", "abc-123-uuid")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/system/settings/paper-strategy-id")

    assert resp.status_code == 200
    body = resp.json()
    assert body["paper_strategy_id"] == "abc-123-uuid"
    assert body["configured"] is True
    assert body["source"] == "settings.PAPER_STRATEGY_ID"


@pytest.mark.asyncio
async def test_get_paper_strategy_id_unconfigured_default(monkeypatch):
    """settings.PAPER_STRATEGY_ID="" default → configured=False + empty sid."""
    from app.config import settings

    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/system/settings/paper-strategy-id")

    assert resp.status_code == 200
    body = resp.json()
    assert body["paper_strategy_id"] == ""
    assert body["configured"] is False
    assert body["source"] == "settings.PAPER_STRATEGY_ID"


@pytest.mark.asyncio
async def test_get_paper_strategy_id_no_db_access(monkeypatch):
    """Endpoint is settings-only (no DB) — no get_db dependency required."""
    from app.config import settings

    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", "test-no-db-sid")

    # NOT overriding get_db; if endpoint accidentally depends on DB, this would fail.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/system/settings/paper-strategy-id")

    assert resp.status_code == 200
    assert resp.json()["paper_strategy_id"] == "test-no-db-sid"
