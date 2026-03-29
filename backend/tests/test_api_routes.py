"""API路由测试 — 覆盖 health / dashboard / paper_trading / strategies 全部13个端点。

测试策略: 使用FastAPI dependency_overrides mock掉Service/Repository层，
不依赖真实数据库，只验证路由层逻辑（参数解析、状态码、响应结构）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers: mock工厂
# ---------------------------------------------------------------------------


def _make_health_repo_mock(
    latest_health: dict | None = None,
    pipeline_status: list[dict] | None = None,
) -> MagicMock:
    """创建HealthRepository mock。"""
    repo = MagicMock()
    repo.get_latest_health = AsyncMock(return_value=latest_health)
    repo.get_pipeline_status = AsyncMock(return_value=pipeline_status or [])
    return repo


def _make_dashboard_service_mock(
    summary: dict | None = None,
    nav_series: list[dict] | None = None,
    pending_actions: list[dict] | None = None,
    market_ticker: list[dict] | None = None,
    alerts: list[dict] | None = None,
    strategies: list[dict] | None = None,
    monthly_returns: dict | None = None,
    industry_distribution: list[dict] | None = None,
) -> MagicMock:
    """创建DashboardService mock。"""
    svc = MagicMock()
    svc.get_summary = AsyncMock(
        return_value=summary
        or {
            "nav": 1.05,
            "sharpe": 1.21,
            "mdd": -0.08,
            "position_count": 28,
            "daily_return": 0.003,
            "cumulative_return": 0.05,
            "cash_ratio": 0.12,
            "trade_date": "2026-03-20",
        }
    )
    svc.get_nav_series = AsyncMock(return_value=nav_series or [])
    svc.get_pending_actions = AsyncMock(return_value=pending_actions or [])
    svc.get_market_ticker = AsyncMock(
        return_value=market_ticker
        or [
            {
                "label": "沪深300",
                "code": "000300.SH",
                "value": 3800.5,
                "change_pct": 0.8,
                "is_up": True,
            },
            {
                "label": "上证指数",
                "code": "000001.SH",
                "value": 3200.1,
                "change_pct": -0.2,
                "is_up": False,
            },
            {
                "label": "创业板指",
                "code": "399006.SZ",
                "value": 2100.3,
                "change_pct": 1.1,
                "is_up": True,
            },
            {
                "label": "成交额(亿)",
                "code": "TOTAL_AMOUNT",
                "value": 8500.0,
                "change_pct": 0.0,
                "is_up": True,
            },
        ]
    )
    svc.get_alerts = AsyncMock(
        return_value=alerts
        or [
            {
                "level": "P1",
                "title": "回撤预警",
                "desc": "MDD触及-8%",
                "time": "2026-03-29T10:00:00+08:00",
                "color": "orange",
            },
        ]
    )
    svc.get_strategies_overview = AsyncMock(
        return_value=strategies
        or [
            {
                "id": "abc-123",
                "name": "v1.1",
                "status": "paper",
                "market": "astock",
                "sharpe": None,
                "pnl": 0.05,
                "mdd": -0.08,
            },
        ]
    )
    svc.get_monthly_returns = AsyncMock(return_value=monthly_returns or {2026: [None] * 12})
    svc.get_industry_distribution = AsyncMock(
        return_value=industry_distribution
        or [
            {"name": "医药生物", "pct": 0.25, "color": "#5470c6"},
            {"name": "电子", "pct": 0.20, "color": "#91cc75"},
        ]
    )
    return svc


def _make_paper_trading_service_mock(
    status: dict | None = None,
    graduation: dict | None = None,
) -> MagicMock:
    """创建PaperTradingService mock。"""
    svc = MagicMock()
    svc.get_status = AsyncMock(
        return_value=status
        or {
            "nav": 1.02,
            "position_count": 25,
            "running_days": 45,
            "sharpe": 0.95,
            "mdd": -0.06,
            "total_return": 0.02,
            "trade_date": "2026-03-20",
            "graduation_ready": False,
        }
    )
    svc.get_graduation_progress = AsyncMock(
        return_value=graduation
        or {
            "criteria": [
                {
                    "name": "运行时长",
                    "target": ">= 60个交易日",
                    "actual": "45个交易日",
                    "passed": False,
                },
                {"name": "Sharpe", "target": ">= 0.700", "actual": "0.950", "passed": True},
                {"name": "最大回撤", "target": "<= -0.1800", "actual": "-0.0600", "passed": True},
                {"name": "滑点偏差", "target": "< 50%", "actual": "3.0bps", "passed": True},
                {
                    "name": "链路完整性",
                    "target": "全链路无中断",
                    "actual": "待实现",
                    "passed": False,
                },
            ],
            "all_passed": False,
            "summary": "3/5",
        }
    )
    return svc


def _make_position_repo_mock(
    positions: list[dict] | None = None,
) -> MagicMock:
    """创建PositionRepository mock。"""
    repo = MagicMock()
    repo.get_latest_positions = AsyncMock(return_value=positions or [])
    return repo


def _make_trade_repo_mock(
    trades: list[dict] | None = None,
) -> MagicMock:
    """创建TradeRepository mock。"""
    repo = MagicMock()
    repo.get_trades = AsyncMock(return_value=trades or [])
    return repo


def _make_strategy_service_mock(
    detail: dict | None = None,
    create_version_result: dict | None = None,
    rollback_result: dict | None = None,
    list_strategies_result: list[dict] | None = None,
    detail_returns_none: bool = False,
    create_version_raises: Exception | None = None,
    rollback_raises: Exception | None = None,
) -> MagicMock:
    """创建StrategyService mock。"""
    svc = MagicMock()

    # strategy_repo.list_strategies
    svc.strategy_repo = MagicMock()
    svc.strategy_repo.list_strategies = AsyncMock(return_value=list_strategies_result or [])

    # get_strategy_detail
    if detail_returns_none:
        svc.get_strategy_detail = AsyncMock(return_value=None)
    else:
        svc.get_strategy_detail = AsyncMock(
            return_value=detail
            or {
                "strategy": {"id": "s1", "name": "test", "active_version": 1},
                "active_config": {"version": 1, "config": {}},
                "version_history": [{"version": 1, "changelog": "init"}],
            }
        )

    # create_version
    if create_version_raises:
        svc.create_version = AsyncMock(side_effect=create_version_raises)
    else:
        svc.create_version = AsyncMock(
            return_value=create_version_result
            or {"version": 2, "strategy_id": "s1", "changelog": "update"}
        )

    # rollback
    if rollback_raises:
        svc.rollback = AsyncMock(side_effect=rollback_raises)
    else:
        svc.rollback = AsyncMock(
            return_value=rollback_result
            or {"strategy_id": "s1", "rolled_back_to": 1, "previous_version": 2}
        )

    return svc


# ---------------------------------------------------------------------------
# Fixtures: 通过dependency_overrides注入mock
# ---------------------------------------------------------------------------


@pytest.fixture
def _override_health_repo():
    """Override HealthRepository依赖，提供默认mock。"""
    from app.api.health import _get_health_repo

    mock_repo = _make_health_repo_mock(
        latest_health={
            "check_date": "2026-03-20",
            "postgresql_ok": True,
            "redis_ok": True,
            "data_fresh": True,
            "factor_nan_ok": True,
            "disk_ok": True,
            "celery_ok": True,
            "all_pass": True,
            "failed_items": [],
        }
    )
    app.dependency_overrides[_get_health_repo] = lambda: mock_repo
    yield mock_repo
    app.dependency_overrides.pop(_get_health_repo, None)


@pytest.fixture
def _override_health_repo_empty():
    """Override HealthRepository依赖，无健康检查记录。"""
    from app.api.health import _get_health_repo

    mock_repo = _make_health_repo_mock(latest_health=None)
    app.dependency_overrides[_get_health_repo] = lambda: mock_repo
    yield mock_repo
    app.dependency_overrides.pop(_get_health_repo, None)


@pytest.fixture
def _override_dashboard_service():
    """Override DashboardService依赖。"""
    from app.api.dashboard import _get_dashboard_service

    mock_svc = _make_dashboard_service_mock()
    app.dependency_overrides[_get_dashboard_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(_get_dashboard_service, None)


@pytest.fixture
def _override_paper_trading():
    """Override PaperTradingService + PositionRepository + TradeRepository。"""
    from app.api.paper_trading import (
        _get_paper_trading_service,
        _get_position_repo,
        _get_trade_repo,
    )

    mock_svc = _make_paper_trading_service_mock()
    mock_pos = _make_position_repo_mock(
        positions=[
            {
                "code": "600519",
                "quantity": 100,
                "market_value": 180000,
                "weight": 0.18,
                "avg_cost": 1700,
                "unrealized_pnl": 1000,
                "holding_days": 10,
            }
        ]
    )
    mock_trade = _make_trade_repo_mock(
        trades=[
            {
                "id": "t1",
                "code": "600519",
                "trade_date": "2026-03-19",
                "direction": "buy",
                "quantity": 100,
                "fill_price": 1700.0,
            }
        ]
    )

    app.dependency_overrides[_get_paper_trading_service] = lambda: mock_svc
    app.dependency_overrides[_get_position_repo] = lambda: mock_pos
    app.dependency_overrides[_get_trade_repo] = lambda: mock_trade
    yield mock_svc, mock_pos, mock_trade
    app.dependency_overrides.pop(_get_paper_trading_service, None)
    app.dependency_overrides.pop(_get_position_repo, None)
    app.dependency_overrides.pop(_get_trade_repo, None)


@pytest.fixture
def _override_strategy_service():
    """Override StrategyService依赖。"""
    from app.api.strategies import _get_strategy_service

    mock_svc = _make_strategy_service_mock()
    app.dependency_overrides[_get_strategy_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(_get_strategy_service, None)


@pytest.fixture
def _override_strategy_service_not_found():
    """Override StrategyService，策略不存在场景。"""
    from app.api.strategies import _get_strategy_service

    mock_svc = _make_strategy_service_mock(
        detail_returns_none=True,
        create_version_raises=ValueError("策略不存在: nonexistent"),
        rollback_raises=ValueError("策略不存在: nonexistent"),
    )
    app.dependency_overrides[_get_strategy_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(_get_strategy_service, None)


# ============================================================================
# Health API Tests (2 endpoints)
# ============================================================================


class TestHealthAPI:
    """GET /api/health 和 GET /api/health/checks 测试。"""

    @pytest.mark.asyncio
    async def test_health_status_ok(self, client, _override_health_repo):
        """正常路径: 健康检查全通过返回status=ok。"""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["all_pass"] is True
        assert "checks" in data
        checks = data["checks"]
        assert all(
            k in checks
            for k in ["postgresql", "redis", "data_fresh", "factor_nan", "disk", "celery"]
        )

    @pytest.mark.asyncio
    async def test_health_status_no_records(self, client, _override_health_repo_empty):
        """异常路径: 无健康检查记录返回status=unknown。"""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_health_check_history(self, client, _override_health_repo):
        """正常路径: /checks返回latest_health和pipeline_status结构。"""
        resp = await client.get("/api/health/checks")
        assert resp.status_code == 200
        data = resp.json()
        assert "latest_health" in data
        assert "pipeline_status" in data

    @pytest.mark.asyncio
    async def test_health_check_history_empty(self, client, _override_health_repo_empty):
        """异常路径: 无记录时latest_health为null。"""
        resp = await client.get("/api/health/checks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["latest_health"] is None


# ============================================================================
# Dashboard API Tests (3 endpoints)
# ============================================================================


class TestDashboardAPI:
    """GET /api/dashboard/summary, /nav-series, /pending-actions 测试。"""

    @pytest.mark.asyncio
    async def test_summary_returns_7_indicators(self, client, _override_dashboard_service):
        """正常路径: summary返回7个指标字段。"""
        resp = await client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()
        required_keys = [
            "nav",
            "sharpe",
            "mdd",
            "position_count",
            "daily_return",
            "cumulative_return",
            "cash_ratio",
        ]
        for key in required_keys:
            assert key in data, f"缺少指标字段: {key}"

    @pytest.mark.asyncio
    async def test_summary_with_strategy_id(self, client, _override_dashboard_service):
        """正常路径: 指定strategy_id参数。"""
        resp = await client.get("/api/dashboard/summary?strategy_id=abc&execution_mode=live")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_nav_series_returns_list(self, client, _override_dashboard_service):
        """正常路径: nav-series返回列表。"""
        resp = await client.get("/api/dashboard/nav-series?period=1m")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_pending_actions_returns_list(self, client, _override_dashboard_service):
        """正常路径: pending-actions返回列表。"""
        resp = await client.get("/api/dashboard/pending-actions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ============================================================================
# Dashboard API Tests — 5 new endpoints (Sprint 1.22)
# ============================================================================


class TestDashboardNewEndpoints:
    """GET /api/dashboard/market-ticker, /alerts, /strategies,
    /monthly-returns, /industry-distribution 测试。"""

    @pytest.mark.asyncio
    async def test_market_ticker_returns_list(self, client, _override_dashboard_service):
        """正常路径: market-ticker返回4项行情数据。"""
        resp = await client.get("/api/dashboard/market-ticker")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 4
        for item in data:
            assert "label" in item
            assert "code" in item
            assert "value" in item
            assert "change_pct" in item
            assert "is_up" in item

    @pytest.mark.asyncio
    async def test_market_ticker_fields_types(self, client, _override_dashboard_service):
        """market-ticker: value为数值，is_up为bool。"""
        resp = await client.get("/api/dashboard/market-ticker")
        data = resp.json()
        for item in data:
            assert isinstance(item["value"], (int, float))
            assert isinstance(item["is_up"], bool)

    @pytest.mark.asyncio
    async def test_alerts_returns_list(self, client, _override_dashboard_service):
        """正常路径: alerts返回预警列表。"""
        resp = await client.get("/api/dashboard/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        alert = data[0]
        assert alert["level"] == "P1"
        assert "title" in alert
        assert "desc" in alert
        assert "color" in alert

    @pytest.mark.asyncio
    async def test_alerts_hours_param(self, client, _override_dashboard_service):
        """alerts: hours参数合法范围（1-168）。"""
        resp = await client.get("/api/dashboard/alerts?hours=48")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_alerts_hours_out_of_range(self, client, _override_dashboard_service):
        """边界: hours=0 应返回422。"""
        resp = await client.get("/api/dashboard/alerts?hours=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_strategies_returns_list(self, client, _override_dashboard_service):
        """正常路径: strategies返回策略列表，包含必要字段。"""
        resp = await client.get("/api/dashboard/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        s = data[0]
        for key in ("id", "name", "status", "market", "pnl", "mdd"):
            assert key in s, f"strategies缺少字段: {key}"

    @pytest.mark.asyncio
    async def test_monthly_returns_dict_structure(self, client, _override_dashboard_service):
        """正常路径: monthly-returns返回 {year: [12个月]} 结构。"""
        resp = await client.get("/api/dashboard/monthly-returns")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        for _year_key, months in data.items():
            assert isinstance(months, list)
            assert len(months) == 12

    @pytest.mark.asyncio
    async def test_monthly_returns_with_strategy_id(self, client, _override_dashboard_service):
        """monthly-returns: 指定strategy_id和execution_mode参数。"""
        resp = await client.get(
            "/api/dashboard/monthly-returns?strategy_id=abc&execution_mode=live"
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_industry_distribution_returns_list(self, client, _override_dashboard_service):
        """正常路径: industry-distribution返回行业分布列表。"""
        resp = await client.get("/api/dashboard/industry-distribution")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        for item in data:
            assert "name" in item
            assert "pct" in item
            assert "color" in item

    @pytest.mark.asyncio
    async def test_industry_distribution_pct_numeric(self, client, _override_dashboard_service):
        """industry-distribution: pct为数值且在[0,1]范围内。"""
        resp = await client.get("/api/dashboard/industry-distribution")
        data = resp.json()
        for item in data:
            assert isinstance(item["pct"], (int, float))
            assert 0.0 <= item["pct"] <= 1.0

    @pytest.mark.asyncio
    async def test_industry_distribution_with_strategy_id(
        self, client, _override_dashboard_service
    ):
        """industry-distribution: 指定strategy_id参数。"""
        resp = await client.get(
            "/api/dashboard/industry-distribution?strategy_id=s1&execution_mode=paper"
        )
        assert resp.status_code == 200


# ============================================================================
# Paper Trading API Tests (4 endpoints)
# ============================================================================


class TestPaperTradingAPI:
    """GET /api/paper-trading/status, /graduation, /positions, /trades 测试。"""

    @pytest.mark.asyncio
    async def test_status_returns_correct_structure(self, client, _override_paper_trading):
        """正常路径: status返回所有状态字段。"""
        resp = await client.get("/api/paper-trading/status")
        assert resp.status_code == 200
        data = resp.json()
        required_keys = [
            "nav",
            "position_count",
            "running_days",
            "sharpe",
            "mdd",
            "total_return",
            "trade_date",
            "graduation_ready",
        ]
        for key in required_keys:
            assert key in data, f"缺少字段: {key}"

    @pytest.mark.asyncio
    async def test_graduation_returns_criteria(self, client, _override_paper_trading):
        """正常路径: graduation返回毕业进度结构（criteria/all_passed/summary）。"""
        resp = await client.get(
            "/api/paper-trading/graduation"
            "?backtest_sharpe=1.0&backtest_mdd=-0.12&model_slippage_bps=5.0"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "criteria" in data
        assert "all_passed" in data
        assert "summary" in data
        assert isinstance(data["criteria"], list)
        assert len(data["criteria"]) == 5

    @pytest.mark.asyncio
    async def test_graduation_default_params(self, client, _override_paper_trading):
        """正常路径: graduation不传基准参数也能正常返回。"""
        resp = await client.get("/api/paper-trading/graduation")
        assert resp.status_code == 200
        data = resp.json()
        assert "criteria" in data

    @pytest.mark.asyncio
    async def test_positions_returns_list(self, client, _override_paper_trading):
        """正常路径: positions返回持仓列表。"""
        resp = await client.get("/api/paper-trading/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["code"] == "600519"

    @pytest.mark.asyncio
    async def test_trades_returns_list(self, client, _override_paper_trading):
        """正常路径: trades返回交易记录列表。"""
        resp = await client.get("/api/paper-trading/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_trades_with_limit(self, client, _override_paper_trading):
        """正常路径: trades支持limit参数。"""
        resp = await client.get("/api/paper-trading/trades?limit=10")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trades_invalid_limit(self, client, _override_paper_trading):
        """异常路径: limit超出范围返回422。"""
        resp = await client.get("/api/paper-trading/trades?limit=0")
        assert resp.status_code == 422

        resp2 = await client.get("/api/paper-trading/trades?limit=999")
        assert resp2.status_code == 422


# ============================================================================
# Strategies API Tests (4 endpoints)
# ============================================================================


class TestStrategiesAPI:
    """GET/POST /api/strategies 测试。"""

    @pytest.mark.asyncio
    async def test_list_strategies(self, client, _override_strategy_service):
        """正常路径: 策略列表返回数组。"""
        resp = await client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_strategies_with_filters(self, client, _override_strategy_service):
        """正常路径: 带market和status筛选。"""
        resp = await client.get("/api/strategies?market=a_share&status=active")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_strategy_detail(self, client, _override_strategy_service):
        """正常路径: 获取策略详情。"""
        resp = await client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
        assert "active_config" in data
        assert "version_history" in data

    @pytest.mark.asyncio
    async def test_get_strategy_detail_not_found(
        self, client, _override_strategy_service_not_found
    ):
        """异常路径: 策略不存在返回404。"""
        resp = await client.get("/api/strategies/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "策略不存在" in data["detail"]

    @pytest.mark.asyncio
    async def test_create_strategy_version(self, client, _override_strategy_service):
        """正常路径: 创建新版本返回version递增。"""
        resp = await client.post(
            "/api/strategies/s1/versions",
            json={"config": {"param_a": 0.5}, "changelog": "调整param_a"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 2
        assert data["strategy_id"] == "s1"
        assert data["changelog"] == "update"

    @pytest.mark.asyncio
    async def test_create_version_strategy_not_found(
        self, client, _override_strategy_service_not_found
    ):
        """异常路径: 策略不存在时创建版本返回404。"""
        resp = await client.post(
            "/api/strategies/nonexistent/versions",
            json={"config": {"x": 1}, "changelog": "test"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_version_missing_changelog(self, client, _override_strategy_service):
        """异常路径: 缺少changelog返回422。"""
        resp = await client.post(
            "/api/strategies/s1/versions",
            json={"config": {"x": 1}},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_version_empty_changelog(self, client, _override_strategy_service):
        """异常路径: changelog为空字符串返回422（min_length=1）。"""
        resp = await client.post(
            "/api/strategies/s1/versions",
            json={"config": {"x": 1}, "changelog": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rollback_strategy_version(self, client, _override_strategy_service):
        """正常路径: 回滚到指定版本。"""
        resp = await client.post(
            "/api/strategies/s1/rollback",
            json={"target_version": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rolled_back_to"] == 1

    @pytest.mark.asyncio
    async def test_rollback_invalid_version(self, client, _override_strategy_service_not_found):
        """异常路径: 策略不存在时回滚返回400。"""
        resp = await client.post(
            "/api/strategies/nonexistent/rollback",
            json={"target_version": 1},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rollback_version_zero(self, client, _override_strategy_service):
        """异常路径: target_version=0不满足ge=1约束，返回422。"""
        resp = await client.post(
            "/api/strategies/s1/rollback",
            json={"target_version": 0},
        )
        assert resp.status_code == 422


# ============================================================================
# GET /api/paper-trading/graduation-status Tests
# ============================================================================


def _make_mock_session(
    perf_row: dict | None = None,
    slip_row: dict | None = None,
) -> AsyncMock:
    """构建 AsyncSession mock，返回指定的 performance_series 和 trade_log 查询结果。

    Args:
        perf_row: performance_series 查询行，None 表示无数据。
        slip_row: trade_log 滑点查询行，None 表示无数据。

    Returns:
        配置好的 AsyncSession AsyncMock。
    """
    from unittest.mock import MagicMock

    session = AsyncMock()

    def _make_mapping_result(row: dict | None):
        """构建模拟 MappingResult。"""
        result = MagicMock()
        mapping_result = MagicMock()
        mapping_result.one_or_none = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mapping_result)
        return result

    call_count = 0

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_mapping_result(perf_row)
        return _make_mapping_result(slip_row)

    session.execute = _side_effect
    return session


@pytest.fixture
def _override_graduation_status():
    """Override _get_session 依赖，注入 mock AsyncSession。"""
    from datetime import date

    from app.api.paper_trading import _get_session

    mock_session = _make_mock_session(
        perf_row={
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 3, 29),
            "trading_days": 60,
            "avg_return": 0.001,
            "std_return": 0.012,
            "max_drawdown": -0.08,
        },
        slip_row={"avg_slippage": 60.0},
    )
    app.dependency_overrides[_get_session] = lambda: mock_session
    yield mock_session
    app.dependency_overrides.pop(_get_session, None)


@pytest.fixture
def _override_graduation_status_no_data():
    """Override _get_session — 无performance数据场景。"""
    from app.api.paper_trading import _get_session

    mock_session = _make_mock_session(perf_row=None, slip_row=None)
    app.dependency_overrides[_get_session] = lambda: mock_session
    yield mock_session
    app.dependency_overrides.pop(_get_session, None)


class TestGraduationStatus:
    """GET /api/paper-trading/graduation-status 测试。"""

    @pytest.mark.asyncio
    async def test_returns_200(self, client, _override_graduation_status):
        """正常路径: 返回200。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_required_fields(self, client, _override_graduation_status):
        """响应包含 days_running/sharpe/mdd/slippage_deviation/graduate_ready/criteria。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        data = resp.json()
        for field in (
            "days_running",
            "sharpe",
            "mdd",
            "slippage_deviation",
            "graduate_ready",
            "criteria",
        ):
            assert field in data, f"缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_criteria_has_three_items(self, client, _override_graduation_status):
        """criteria 包含3条固定标准: Sharpe/最大回撤/滑点偏差。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        data = resp.json()
        assert len(data["criteria"]) == 3
        names = {c["name"] for c in data["criteria"]}
        assert "Sharpe" in names
        assert "最大回撤" in names
        assert "滑点偏差" in names

    @pytest.mark.asyncio
    async def test_criteria_items_have_required_fields(self, client, _override_graduation_status):
        """criteria 每项包含 name/target/actual/passed。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        data = resp.json()
        for item in data["criteria"]:
            for field in ("name", "target", "actual", "passed"):
                assert field in item, f"criteria 缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_graduate_ready_is_bool(self, client, _override_graduation_status):
        """graduate_ready 字段为布尔值。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        data = resp.json()
        assert isinstance(data["graduate_ready"], bool)

    @pytest.mark.asyncio
    async def test_days_running_calculated_from_date_range(
        self, client, _override_graduation_status
    ):
        """days_running 从 start_date 到 end_date 的自然日数。"""
        from datetime import date

        resp = await client.get("/api/paper-trading/graduation-status")
        data = resp.json()
        # mock: start=2026-01-01, end=2026-03-29 → 87 自然日
        expected_days = (date(2026, 3, 29) - date(2026, 1, 1)).days
        assert data["days_running"] == expected_days

    @pytest.mark.asyncio
    async def test_no_data_returns_zeros(self, client, _override_graduation_status_no_data):
        """无performance数据时返回零值但格式正确。"""
        resp = await client.get("/api/paper-trading/graduation-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_running"] == 0
        assert data["sharpe"] == 0.0
        assert data["mdd"] == 0.0
        assert isinstance(data["criteria"], list)

    @pytest.mark.asyncio
    async def test_graduate_ready_false_when_sharpe_low(self, client):
        """Sharpe不达标时 graduate_ready=False。"""
        from datetime import date

        from app.api.paper_trading import _get_session

        # Sharpe极低场景：avg_return接近0
        mock_session = _make_mock_session(
            perf_row={
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 3, 29),
                "trading_days": 60,
                "avg_return": 0.00001,
                "std_return": 0.02,
                "max_drawdown": -0.05,
            },
            slip_row={"avg_slippage": 60.0},
        )
        app.dependency_overrides[_get_session] = lambda: mock_session
        try:
            resp = await client.get("/api/paper-trading/graduation-status")
            data = resp.json()
            assert data["graduate_ready"] is False
        finally:
            app.dependency_overrides.pop(_get_session, None)


# ============================================================================
# Legacy health endpoint (main.py中的/health)
# ============================================================================


class TestLegacyHealth:
    """GET /health 向后兼容端点测试。"""

    @pytest.mark.asyncio
    async def test_legacy_health(self, client):
        """正常路径: /health返回status=ok。"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "execution_mode" in data
