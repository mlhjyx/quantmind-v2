"""iter 202 MVP 5.2 Chunk 1 — GET /api/factors/ic-monitoring endpoint tests.

Coverage:
- Empty result (0 factors in factor_registry) → {decay_heatmap: [], core_factors: [], total_count: 0}
- Populated (multi-factor mix of pools) → factors list with all 9 fields + core_factors subset
- Optional pool=CORE filter

Mock strategy: sibling test_scheduler_task_log_endpoint.py pattern.
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


def _make_session_with_rows(rows: list[dict[str, Any]]) -> MagicMock:
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


class TestIcMonitoringEndpoint:
    """Test GET /api/factors/ic-monitoring."""

    @pytest.mark.asyncio
    async def test_empty_factor_registry_returns_empty_arrays(self):
        """0 factors → {decay_heatmap: [], core_factors: [], total_count: 0}."""
        from app.db import get_db

        mock_session = _make_session_with_rows([])
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/factors/ic-monitoring")
            assert resp.status_code == 200
            data = resp.json()
            assert data["decay_heatmap"] == []
            assert data["core_factors"] == []
            assert data["total_count"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_populated_returns_decay_heatmap_with_9_fields_and_core_subset(self):
        """Populated mix → all 9 schema fields + core_factors filtered to pool=CORE."""
        from app.db import get_db

        rows = [
            {
                "name": "turnover_mean_20",
                "status": "active",
                "pool": "CORE",
                "category": "liquidity",
                "ic_decay_ratio": 0.85,
                "ic_ma20": 0.042,
                "ic_ma60": 0.038,
                "decay_level": "normal",
                "latest_trade_date": "2026-05-26",
            },
            {
                "name": "dv_ttm",
                "status": "warning",
                "pool": "CORE",
                "category": "value",
                "ic_decay_ratio": 0.51,
                "ic_ma20": 0.020,
                "ic_ma60": 0.039,
                "decay_level": "warning",
                "latest_trade_date": "2026-05-26",
            },
            {
                "name": "momentum_10",
                "status": "candidate",
                "pool": "CANDIDATE",
                "category": "momentum",
                "ic_decay_ratio": None,
                "ic_ma20": None,
                "ic_ma60": None,
                "decay_level": None,
                "latest_trade_date": None,
            },
        ]
        mock_session = _make_session_with_rows(rows)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/factors/ic-monitoring")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 3
            assert len(data["decay_heatmap"]) == 3
            # core_factors filtered subset
            assert len(data["core_factors"]) == 2
            assert {f["name"] for f in data["core_factors"]} == {"turnover_mean_20", "dv_ttm"}

            # Verify 9 schema fields on first row
            r0 = data["decay_heatmap"][0]
            for field in (
                "name",
                "status",
                "pool",
                "category",
                "ic_decay_ratio",
                "ic_ma20",
                "ic_ma60",
                "decay_level",
                "latest_trade_date",
            ):
                assert field in r0, f"missing field: {field}"
            assert r0["name"] == "turnover_mean_20"
            assert r0["decay_level"] == "normal"

            # Verify None handling for unbacked factor
            r2 = data["decay_heatmap"][2]
            assert r2["ic_ma20"] is None
            assert r2["decay_level"] is None
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_pool_filter_param_passed_to_sql(self):
        """pool=CORE filter → SQL params include {'pool': 'CORE'}."""
        from app.db import get_db

        rows = [
            {
                "name": "bp_ratio",
                "status": "active",
                "pool": "CORE",
                "category": "value",
                "ic_decay_ratio": 0.92,
                "ic_ma20": 0.034,
                "ic_ma60": 0.033,
                "decay_level": "normal",
                "latest_trade_date": "2026-05-26",
            },
        ]
        mock_session = _make_session_with_rows(rows)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/factors/ic-monitoring?pool=CORE")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 1
            assert data["decay_heatmap"][0]["pool"] == "CORE"
            # Verify execute was called with pool param
            calls = mock_session.execute.call_args_list
            assert len(calls) == 1
            # Second arg of execute is the params dict
            params = calls[0].args[1]
            assert params.get("pool") == "CORE"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_db_error_returns_500_fail_loud(self):
        """DB exception → 500 per 铁律 33."""
        from app.db import get_db

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("db connection lost"))
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/factors/ic-monitoring")
            assert resp.status_code == 500
            data = resp.json()
            assert "ic-monitoring query failed" in data.get("detail", "")
        finally:
            app.dependency_overrides.clear()
