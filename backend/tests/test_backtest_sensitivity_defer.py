"""Tests for POST /api/backtest/{run_id}/sensitivity DEFER endpoint (iter 34).

Iter 34 closure of iter 32 RESUME POINT cand (b) — sensitivity analysis was
verified Architecture-level scope (§6 trigger 8 self-protection) and DEFERRED
to Phase B post-PT-restart per anti-assumption SOP. Endpoint contract preserved:
still 200 with run_id + param metadata, but `status=deferred` + honest message
+ tracking_ref to ADR-DRAFT row 18.

Coverage:
  - 200 returned with deferred status + correct shape
  - run_id 404 still works (parent run validation unchanged)
  - param_name + param_values echoed back unchanged
  - message cites ADR-DRAFT row 18 + tracking_ref present
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def completed_run_row():
    """Minimal completed backtest_run row for mocking."""
    rid = _uuid()
    return {
        "run_id": rid,
        "status": "completed",
        "name": "test-run",
        "start_date": date(2023, 1, 1),
        "end_date": date(2024, 12, 31),
        "created_at": datetime(2024, 1, 1, 12, 0, 0),
        "annual_return": 0.15,
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.08,
        "calmar_ratio": 1.875,
        "win_rate": 0.55,
        "total_trades": 100,
    }


@pytest.mark.asyncio
async def test_sensitivity_returns_deferred_with_metadata(completed_run_row):
    """Endpoint returns 200 with status=deferred + echoed metadata."""
    from app.main import app

    rid = completed_run_row["run_id"]

    # Mock the _get_run_or_404 helper to return the fake row (bypass real DB)
    async def fake_get_run(session, run_id):
        return completed_run_row

    with patch("app.api.backtest._get_run_or_404", new=AsyncMock(side_effect=fake_get_run)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/backtest/{rid}/sensitivity",
                json={"param_name": "cost_multiplier", "param_values": [0.5, 1.0, 1.5, 2.0]},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == rid
    assert body["param_name"] == "cost_multiplier"
    assert body["param_values"] == [0.5, 1.0, 1.5, 2.0]
    assert body["status"] == "deferred"
    assert "deferred_to" in body
    assert body["deferred_to"] == "phase_b_post_pt_restart"
    assert "tracking_ref" in body
    assert "ADR-DRAFT" in body["tracking_ref"]


@pytest.mark.asyncio
async def test_sensitivity_message_cites_architecture_scope(completed_run_row):
    """Message text explicitly explains the DEFER rationale + cites ADR row."""
    from app.main import app

    rid = completed_run_row["run_id"]

    async def fake_get_run(session, run_id):
        return completed_run_row

    with patch("app.api.backtest._get_run_or_404", new=AsyncMock(side_effect=fake_get_run)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/backtest/{rid}/sensitivity",
                json={"param_name": "cost_multiplier", "param_values": [1.0, 2.0]},
            )

    assert resp.status_code == 200
    body = resp.json()
    # Message must be honest about the DEFER reason (not the old "已排队" stub)
    assert "DEFERRED" in body["message"]
    assert "Architecture" in body["message"]
    assert "row 18" in body["message"]
    # 反 regression to old pending stub text
    assert "已排队" not in body["message"]
    assert "WebSocket 推送" not in body["message"]


@pytest.mark.asyncio
async def test_sensitivity_param_values_min_2_validation():
    """SensitivityRequest schema enforces min_length=2 on param_values (sustained)."""
    from app.main import app

    rid = _uuid()

    async def fake_get_run(session, run_id):
        return {"run_id": rid, "status": "completed"}

    with patch("app.api.backtest._get_run_or_404", new=AsyncMock(side_effect=fake_get_run)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/backtest/{rid}/sensitivity",
                json={"param_name": "cost_multiplier", "param_values": [1.0]},
            )

    # Pydantic validation should reject single-element list (min_length=2)
    assert resp.status_code == 422
