"""iter 214 MVP 5.4 C1 — GET /api/risk/events + /events/rule-ids endpoint tests.

Coverage:
- /events empty → {events: [], total_count: 0}
- /events populated → all 12 fields per row + total_count
- /events severity filter
- /events rule_id filter
- /events include_chain=true LEFT JOIN attaches chain object
- /events pagination (limit + offset)
- /events/rule-ids returns distinct list
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


def _make_session_for_events(rows: list[dict[str, Any]], total: int = None) -> MagicMock:
    """Mock AsyncSession with sequential execute results: main query + count query."""
    session = MagicMock()
    row_mocks = []
    for r in rows:
        m = MagicMock()
        for k, v in r.items():
            setattr(m, k, v)
        row_mocks.append(m)
    main_result = MagicMock()
    main_result.fetchall = MagicMock(return_value=row_mocks)
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=total if total is not None else len(rows))
    session.execute = AsyncMock(side_effect=[main_result, count_result])
    return session


def _make_session_for_rule_ids(rule_ids: list[str]) -> MagicMock:
    session = MagicMock()
    row_mocks = []
    for rid in rule_ids:
        m = MagicMock()
        m.rule_id = rid
        row_mocks.append(m)
    result = MagicMock()
    result.fetchall = MagicMock(return_value=row_mocks)
    session.execute = AsyncMock(return_value=result)
    return session


class TestRiskEventsEndpoint:
    """Test GET /api/risk/events."""

    @pytest.mark.asyncio
    async def test_empty_returns_empty_events(self):
        """0 rows → {events: [], total_count: 0}."""
        from app.db import get_db

        mock_session = _make_session_for_events([], total=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events")
            assert resp.status_code == 200
            data = resp.json()
            assert data["events"] == []
            assert data["total_count"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_populated_returns_events_with_12_fields(self):
        """Populated rows → all 12 core schema fields per event."""
        from app.db import get_db

        rows = [
            {
                "id": 1,
                "strategy_id": "550e8400-e29b-41d4-a716-446655440000",
                "rule_id": "pms_l1",
                "severity": "p1",
                "triggered_at": "2026-05-26T14:30:00+00:00",
                "code": "000001",
                "shares": 1000,
                "reason": "PMS L1 threshold breached: 浮盈 32% / 回撤 16%",
                "action_taken": "ALERT_DINGTALK",
                "cadence": None,
                "priority": None,
                "detection_latency_ms": None,
            },
            {
                "id": 2,
                "strategy_id": "550e8400-e29b-41d4-a716-446655440000",
                "rule_id": "trailing_stop",
                "severity": "p0",
                "triggered_at": "2026-05-26T13:45:00+00:00",
                "code": "300001",
                "shares": 500,
                "reason": "Trailing stop hit at -7% from peak",
                "action_taken": "SELL_MARKET",
                "cadence": "subscribe_quote",
                "priority": "p0",
                "detection_latency_ms": 87,
            },
        ]
        mock_session = _make_session_for_events(rows, total=2)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 2
            assert len(data["events"]) == 2

            e0 = data["events"][0]
            for field in (
                "id",
                "strategy_id",
                "rule_id",
                "severity",
                "triggered_at",
                "code",
                "shares",
                "reason",
                "action_taken",
                "cadence",
                "priority",
                "detection_latency_ms",
            ):
                assert field in e0, f"missing field: {field}"
            assert e0["rule_id"] == "pms_l1"
            assert e0["severity"] == "p1"
            # Verify realtime fields
            e1 = data["events"][1]
            assert e1["cadence"] == "subscribe_quote"
            assert e1["detection_latency_ms"] == 87
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_severity_filter_passes_param(self):
        """?severity=p0 filter passes 'p0' (lowercased) param to SQL."""
        from app.db import get_db

        mock_session = _make_session_for_events([], total=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events?severity=P0")
            assert resp.status_code == 200
            # Verify main SQL execute call received severity=p0 (lowercased)
            main_call = mock_session.execute.call_args_list[0]
            params = main_call.args[1]
            assert params.get("severity") == "p0"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_rule_id_filter_passes_param(self):
        """?rule_id=trailing_stop filter passes through to SQL."""
        from app.db import get_db

        mock_session = _make_session_for_events([], total=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events?rule_id=trailing_stop")
            assert resp.status_code == 200
            main_call = mock_session.execute.call_args_list[0]
            params = main_call.args[1]
            assert params.get("rule_id") == "trailing_stop"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_include_chain_attaches_execution_plan(self):
        """?include_chain=true LEFT JOIN execution_plans attaches chain object."""
        from app.db import get_db

        rows = [
            {
                "id": 1,
                "strategy_id": "550e8400-e29b-41d4-a716-446655440000",
                "rule_id": "pms_l2",
                "severity": "p1",
                "triggered_at": "2026-05-26T14:30:00+00:00",
                "code": "000001",
                "shares": 1000,
                "reason": "PMS L2 triggered",
                "action_taken": "STAGED_PLAN_CREATED",
                "cadence": None,
                "priority": None,
                "detection_latency_ms": None,
                # Chain JOIN fields (from execution_plans LEFT JOIN)
                "plan_id": "aaaa-bbbb-cccc-dddd",
                "plan_status": "PENDING_CONFIRM",
                "plan_action": "SELL",
                "plan_qty": 1000,
                "plan_user_decision": None,
                "plan_broker_order_id": None,
            },
            {
                "id": 2,
                "strategy_id": "550e8400-e29b-41d4-a716-446655440000",
                "rule_id": "intraday_portfolio_drop_3pct",
                "severity": "p2",
                "triggered_at": "2026-05-26T13:00:00+00:00",
                "code": None,
                "shares": None,
                "reason": "Portfolio -3% drop",
                "action_taken": "ALERT_ONLY",
                "cadence": None,
                "priority": None,
                "detection_latency_ms": None,
                # No execution plan for this event
                "plan_id": None,
                "plan_status": None,
                "plan_action": None,
                "plan_qty": None,
                "plan_user_decision": None,
                "plan_broker_order_id": None,
            },
        ]
        mock_session = _make_session_for_events(rows, total=2)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events?include_chain=true")
            assert resp.status_code == 200
            data = resp.json()
            # Event 1 has chain
            assert data["events"][0]["chain"] is not None
            assert data["events"][0]["chain"]["plan_id"] == "aaaa-bbbb-cccc-dddd"
            assert data["events"][0]["chain"]["status"] == "PENDING_CONFIRM"
            # Event 2 has chain = None
            assert data["events"][1]["chain"] is None
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_pagination_limit_offset(self):
        """?limit=20&offset=10 passed to SQL params."""
        from app.db import get_db

        mock_session = _make_session_for_events([], total=0)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events?limit=20&offset=10")
            assert resp.status_code == 200
            main_call = mock_session.execute.call_args_list[0]
            params = main_call.args[1]
            assert params.get("limit") == 20
            assert params.get("offset") == 10
        finally:
            app.dependency_overrides.clear()


class TestRiskEventsRuleIdsEndpoint:
    """Test GET /api/risk/events/rule-ids."""

    @pytest.mark.asyncio
    async def test_returns_distinct_rule_ids_sorted(self):
        """Returns {rule_ids: [...], total_count: N} with distinct sorted."""
        from app.db import get_db

        mock_session = _make_session_for_rule_ids(
            ["circuit_breaker", "intraday_portfolio_drop_3pct", "pms_l1", "trailing_stop"]
        )
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/risk/events/rule-ids")
            assert resp.status_code == 200
            data = resp.json()
            assert "rule_ids" in data
            assert "total_count" in data
            assert len(data["rule_ids"]) == 4
            assert data["rule_ids"][0] == "circuit_breaker"
            assert data["rule_ids"][-1] == "trailing_stop"
            assert data["total_count"] == 4
        finally:
            app.dependency_overrides.clear()
