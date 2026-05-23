"""Tests for D1 O10 factor correlation prune endpoint (PN-002 iter 11).

Coverage:
- Default POST (no body) returns 200 + report shape, service called with defaults
- Explicit threshold/lookback_days override defaults, forwarded to service
- dry_run=False returns 422 (PN-002 §6 out-of-scope), service NOT called
- 0 active factors edge case → empty pairs (defensive, no panic)
- threshold out of range [0.0, 1.0] → 422 by Pydantic Field(ge=0, le=1)

Pattern: 沿用 test_pipeline_automation_level.py — dependency_overrides +
AsyncMock + ASGITransport (mock-based, no real DB).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")
from httpx import ASGITransport, AsyncClient

from app.api.factors import _get_factor_service
from app.main import app


def _mock_svc_with_pairs(pairs: list[dict[str, Any]] | None = None) -> MagicMock:
    """Mock FactorService.analyze_correlation_prune returning a fixed report.

    Mirrors PN-002 §2.2 contract shape.
    """
    svc = MagicMock()
    pairs_list = pairs or []
    svc.analyze_correlation_prune = AsyncMock(
        return_value={
            "threshold_used": 0.85,
            "lookback_days_used": 365,
            "pairs": pairs_list,
            "dropped_count": len(pairs_list),
            "total_pairs_above_threshold": len(pairs_list),
            "computed_at": "2026-05-23T23:50:00Z",
        }
    )
    return svc


@pytest.fixture
async def client() -> Any:
    """Async HTTP client wrapping the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_correlation_prune_default_returns_report(client: AsyncClient) -> None:
    """POST with no body uses all defaults, returns 200 + PN-002 §2.2 shape."""
    sample_pair = {
        "factor_a": "turnover_mean_20",
        "factor_b": "amihud_20",
        "correlation": 0.87,
        "ic_a_mean_abs": 0.024,
        "ic_b_mean_abs": 0.019,
        "drop_recommendation": "amihud_20",
        "reason": "|corr|=0.8700 >= threshold=0.85; ...",
    }
    svc = _mock_svc_with_pairs([sample_pair])
    app.dependency_overrides[_get_factor_service] = lambda: svc
    try:
        response = await client.post("/api/factors/correlation-prune")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["threshold_used"] == 0.85
        assert body["lookback_days_used"] == 365
        assert body["dropped_count"] == 1
        assert body["total_pairs_above_threshold"] == 1
        assert body["pairs"] == [sample_pair]
        # Verify service called with defaults
        svc.analyze_correlation_prune.assert_awaited_once_with(
            threshold=0.85, lookback_days=365, dry_run=True
        )
    finally:
        app.dependency_overrides.pop(_get_factor_service, None)


@pytest.mark.asyncio
async def test_correlation_prune_explicit_overrides(client: AsyncClient) -> None:
    """Explicit threshold/lookback_days override defaults, forwarded to service."""
    svc = _mock_svc_with_pairs([])
    app.dependency_overrides[_get_factor_service] = lambda: svc
    try:
        response = await client.post(
            "/api/factors/correlation-prune",
            json={"threshold": 0.70, "lookback_days": 180, "dry_run": True},
        )
        assert response.status_code == 200, response.text
        svc.analyze_correlation_prune.assert_awaited_once_with(
            threshold=0.70, lookback_days=180, dry_run=True
        )
    finally:
        app.dependency_overrides.pop(_get_factor_service, None)


@pytest.mark.asyncio
async def test_correlation_prune_dry_run_false_returns_422(client: AsyncClient) -> None:
    """dry_run=False is explicitly out-of-scope (PN-002 §6) → 422."""
    svc = _mock_svc_with_pairs([])
    app.dependency_overrides[_get_factor_service] = lambda: svc
    try:
        response = await client.post(
            "/api/factors/correlation-prune",
            json={"dry_run": False},
        )
        assert response.status_code == 422, response.text
        # Service must NOT have been called (handler rejects pre-call)
        svc.analyze_correlation_prune.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(_get_factor_service, None)


@pytest.mark.asyncio
async def test_correlation_prune_empty_factors_returns_empty_pairs(
    client: AsyncClient,
) -> None:
    """0 active factors / service returns 0 pairs → 200 + empty report (no panic)."""
    svc = _mock_svc_with_pairs([])
    app.dependency_overrides[_get_factor_service] = lambda: svc
    try:
        response = await client.post("/api/factors/correlation-prune")
        assert response.status_code == 200
        body = response.json()
        assert body["pairs"] == []
        assert body["dropped_count"] == 0
        assert body["total_pairs_above_threshold"] == 0
    finally:
        app.dependency_overrides.pop(_get_factor_service, None)


@pytest.mark.asyncio
async def test_correlation_prune_threshold_out_of_range_returns_422(
    client: AsyncClient,
) -> None:
    """threshold > 1.0 or < 0.0 violates Field(ge=0, le=1) → 422 by Pydantic."""
    svc = _mock_svc_with_pairs([])
    app.dependency_overrides[_get_factor_service] = lambda: svc
    try:
        resp_high = await client.post(
            "/api/factors/correlation-prune",
            json={"threshold": 1.5},
        )
        assert resp_high.status_code == 422, resp_high.text

        resp_neg = await client.post(
            "/api/factors/correlation-prune",
            json={"threshold": -0.1},
        )
        assert resp_neg.status_code == 422, resp_neg.text

        # Pydantic rejects pre-handler → service NOT called
        svc.analyze_correlation_prune.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(_get_factor_service, None)
