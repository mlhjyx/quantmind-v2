"""Sprint 1.23 新增API端点测试 — Portfolio/Market/Execution/Report/Risk扩展。

测试策略: dependency_overrides mock掉Session，只验证路由层逻辑
（参数解析、状态码、响应结构），不依赖真实数据库。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers: mock session工厂
# ---------------------------------------------------------------------------


def _make_session_mock(rows: list | None = None, first: dict | None = None) -> MagicMock:
    """创建返回固定数据的AsyncSession mock。"""
    session = MagicMock(spec=AsyncSession)
    result_mock = MagicMock()
    result_mock.mappings.return_value.all.return_value = rows or []
    result_mock.mappings.return_value.first.return_value = first
    session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# Portfolio API 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portfolio_holdings_empty():
    """持仓列表——数据库无数据返回空列表。"""
    from app.api.portfolio import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/portfolio/holdings")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_holdings_with_data():
    """持仓列表——正常返回结构。"""
    from datetime import date
    from decimal import Decimal

    from app.api.portfolio import _get_session

    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "code": "000001.SZ",
        "name": "平安银行",
        "industry": "银行",
        "quantity": 1000,
        "avg_cost": Decimal("12.50"),
        "market_value": Decimal("13500.00"),
        "weight": Decimal("0.067"),
        "unrealized_pnl": Decimal("1000.00"),
        "holding_days": 15,
        "trade_date": date(2026, 3, 28),
    }[k]

    session_mock = _make_session_mock(rows=[row])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/portfolio/holdings?execution_mode=paper")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["code"] == "000001.SZ"
    assert data[0]["name"] == "平安银行"
    assert data[0]["trade_date"] == "2026-03-28"


@pytest.mark.asyncio
async def test_portfolio_sector_distribution_empty():
    """行业分布——无数据返回空列表。"""
    from app.api.portfolio import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/portfolio/sector-distribution")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_daily_pnl_empty():
    """每日盈亏——无数据返回空列表。"""
    from app.api.portfolio import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/portfolio/daily-pnl?days=20")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_daily_pnl_days_validation():
    """每日盈亏——days参数边界验证。"""
    from app.api.portfolio import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_ok = await client.get("/api/portfolio/daily-pnl?days=250")
        resp_bad = await client.get("/api/portfolio/daily-pnl?days=0")

    app.dependency_overrides.clear()
    assert resp_ok.status_code == 200
    assert resp_bad.status_code == 422


# ---------------------------------------------------------------------------
# Market API 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_indices_empty_returns_mock():
    """指数行情——无数据返回mock数据（5条）。"""
    from app.api.market import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/market/indices")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5
    codes = [d["code"] for d in data]
    assert "000300.SH" in codes
    assert "000001.SH" in codes


@pytest.mark.asyncio
async def test_market_sectors_empty():
    """行业板块——无数据返回空列表。"""
    from app.api.market import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/market/sectors")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_market_top_movers_up():
    """涨幅榜——direction=up 参数正确传递。"""
    from app.api.market import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/market/top-movers?direction=up&limit=5")

    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_market_top_movers_down():
    """跌幅榜——direction=down 参数正确传递。"""
    from app.api.market import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/market/top-movers?direction=down&limit=3")

    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_market_top_movers_invalid_direction():
    """涨跌榜——无效direction参数返回422。"""
    from app.api.market import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/market/top-movers?direction=sideways")

    app.dependency_overrides.clear()
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Execution API 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_pending_orders_empty():
    """待执行订单——无数据返回空列表。"""
    from app.api.execution import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/execution/pending-orders")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_execution_log_today():
    """执行日志——date=today 参数解析正确。"""
    from app.api.execution import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/execution/log?date=today")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_execution_log_specific_date():
    """执行日志——指定日期格式。"""
    from app.api.execution import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/execution/log?date=2026-03-28")

    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_execution_algo_config_no_data():
    """算法配置——无策略配置返回默认值。"""
    from app.api.execution import _get_session

    session_mock = _make_session_mock(first=None)
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/execution/algo-config")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["top_n"] == 20  # F74 fix: PT_TOP_N changed 15→20 (Phase 2.4)
    assert data["rebalance_freq"] == "monthly"
    assert data["cash_buffer"] == 0.03


# ---------------------------------------------------------------------------
# Report API 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_list_empty():
    """报告列表——无数据返回空列表。"""
    from app.api.report import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reports/list")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_report_quick_stats_empty():
    """快速统计——无数据返回零值结构。"""
    from app.api.report import _get_session

    session_mock = _make_session_mock(rows=[])
    app.dependency_overrides[_get_session] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reports/quick-stats")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "today" in data
    assert "week" in data
    assert "month" in data
    assert "year" in data
    assert "as_of" in data
    assert data["today"]["return"] == 0.0


@pytest.mark.asyncio
async def test_report_generate_returns_task_id():
    """触发报告生成——返回task_id和status。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/reports/generate")

    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert "status" in data
    assert data["status"] in ("queued", "accepted")


# ---------------------------------------------------------------------------
# Risk API 扩展端点测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risk_overview_no_data():
    """风险概览——无数据返回零值结构。"""
    from app.api.risk import _get_risk_service, get_db

    session_mock = _make_session_mock(rows=[])

    risk_svc_mock = MagicMock()
    risk_svc_mock.get_current_state = AsyncMock(side_effect=Exception("no state"))

    app.dependency_overrides[get_db] = lambda: session_mock
    app.dependency_overrides[_get_risk_service] = lambda: risk_svc_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/risk/overview")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "var_95" in data
    assert "cvar_95" in data
    assert "beta" in data
    assert "volatility_annualized" in data
    assert "sharpe_60d" in data
    assert "max_drawdown" in data
    assert "circuit_level" in data
    assert "position_multiplier" in data


@pytest.mark.asyncio
async def test_risk_limits_returns_8_items():
    """风控限额——返回8项限额。"""
    from app.api.risk import get_db

    session_mock = _make_session_mock(rows=[], first=None)
    app.dependency_overrides[get_db] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/risk/limits")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 8
    for item in data:
        assert "name" in item
        assert "limit" in item
        assert "current" in item
        assert "usage_pct" in item
        assert "status" in item
        assert item["status"] in ("normal", "warning", "danger")


@pytest.mark.asyncio
async def test_risk_stress_tests_returns_6_scenarios():
    """压力测试——返回6个历史场景。"""
    from app.api.risk import get_db

    session_mock = _make_session_mock(rows=[], first=None)
    app.dependency_overrides[get_db] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/risk/stress-tests")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 6
    for item in data:
        assert "scenario" in item
        assert "market_drop" in item
        assert "estimated_loss" in item
        assert "estimated_nav" in item
        assert "beta_used" in item
        # 压力测试场景下估算亏损应为负数
        assert item["estimated_loss"] < 0


@pytest.mark.asyncio
async def test_risk_stress_tests_nav_calculation():
    """压力测试——estimated_nav计算正确（nav * (1 + loss)）。"""
    from app.api.risk import get_db

    # 模拟nav=1.1的情况
    nav_row = MagicMock()
    nav_row.__getitem__ = lambda self, k: {"nav": 1.1}[k]

    result_mock = MagicMock()
    result_mock.mappings.return_value.first.return_value = nav_row
    session_mock = MagicMock(spec=AsyncSession)
    session_mock.execute = AsyncMock(return_value=result_mock)

    app.dependency_overrides[get_db] = lambda: session_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/risk/stress-tests")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    # 所有场景estimated_nav应小于1.1（跌损后）
    for item in data:
        assert item["estimated_nav"] < 1.1
