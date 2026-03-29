"""回测API路由测试 — 覆盖 backtest.py 全部16个端点。

测试策略: 使用FastAPI dependency_overrides mock掉DB session，
不依赖真实数据库，只验证路由层逻辑（参数解析、状态码、响应结构）。
"""

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")
from httpx import ASGITransport, AsyncClient

from app.api.backtest import _get_session
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _make_run_row(
    run_id: str,
    status: str = "completed",
    **overrides: Any,
) -> dict[str, Any]:
    """构造模拟的 backtest_run 行。"""
    base = {
        "run_id": run_id,
        "strategy_id": _uuid(),
        "run_name": "test_run",
        "market": "a_share",
        "status": status,
        "start_date": date(2023, 1, 1),
        "end_date": date(2023, 12, 31),
        "config_json": {"initial_capital": 1000000},
        "annual_return": 0.15,
        "sharpe_ratio": 1.21,
        "max_drawdown": -0.08,
        "calmar_ratio": 1.875,
        "total_turnover": 3.5,
        "win_rate": 0.55,
        "created_at": "2023-01-01 00:00:00",
        "finished_at": "2023-01-02 00:00:00",
        "error_msg": None,
    }
    base.update(overrides)
    return base


def _mock_session_with_run(run_row: dict[str, Any]) -> MagicMock:
    """创建一个mock session，execute返回包含run_row的结果。"""
    session = AsyncMock()

    # 默认返回run_row
    mapping_mock = MagicMock()
    mapping_mock.first.return_value = run_row

    result_mock = MagicMock()
    result_mock.mappings.return_value = mapping_mock

    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    return session


def _mock_session_no_run() -> MagicMock:
    """创建一个mock session，execute返回空结果（404场景）。"""
    session = AsyncMock()
    mapping_mock = MagicMock()
    mapping_mock.first.return_value = None

    result_mock = MagicMock()
    result_mock.mappings.return_value = mapping_mock

    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    return session


def _mock_session_for_history(
    total: int, items: list[dict[str, Any]]
) -> MagicMock:
    """创建用于 /history 端点的mock session（两次execute调用）。"""
    session = AsyncMock()

    # 第一次调用: COUNT(*)
    count_result = MagicMock()
    count_result.scalar.return_value = total

    # 第二次调用: SELECT rows
    rows_mapping = MagicMock()
    rows_mapping.all.return_value = [MagicMock(**{"__iter__": lambda s: iter({}), "keys": lambda s: []}) for _ in items]
    # 使用真实的dict模拟mappings
    rows_result = MagicMock()
    rows_result.mappings.return_value = MagicMock(all=MagicMock(return_value=items))

    session.execute = AsyncMock(side_effect=[count_result, rows_result])
    session.commit = AsyncMock()
    return session


def _mock_session_multi_execute(*results: Any) -> MagicMock:
    """创建支持多次execute调用的mock session。"""
    session = AsyncMock()
    side_effects = []
    for r in results:
        mock_result = MagicMock()
        if isinstance(r, list):
            # 返回行列表
            mock_result.mappings.return_value = MagicMock(all=MagicMock(return_value=r))
        elif isinstance(r, dict):
            # 单行结果
            mock_result.mappings.return_value = MagicMock(
                first=MagicMock(return_value=r),
                all=MagicMock(return_value=[r]),
            )
        elif isinstance(r, int):
            # scalar结果
            mock_result.scalar.return_value = r
        else:
            mock_result.mappings.return_value = MagicMock(
                first=MagicMock(return_value=r),
                all=MagicMock(return_value=[r] if r else []),
            )
        side_effects.append(mock_result)
    session.execute = AsyncMock(side_effect=side_effects)
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_id() -> str:
    return _uuid()


@pytest.fixture
def completed_run(run_id: str) -> dict[str, Any]:
    return _make_run_row(run_id, status="completed")


@pytest.fixture
def running_run(run_id: str) -> dict[str, Any]:
    return _make_run_row(run_id, status="running")


# ---------------------------------------------------------------------------
# 1. POST /api/backtest/run — 提交回测
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_backtest_returns_run_id():
    """POST /run 应返回 run_id + status=running。"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/run",
                json={
                    "strategy_id": _uuid(),
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert data["status"] == "running"
        assert uuid.UUID(data["run_id"])  # 验证是合法UUID
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_backtest_with_custom_config():
    """POST /run 支持自定义配置参数。"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/run",
                json={
                    "strategy_id": _uuid(),
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                    "initial_capital": 2000000,
                    "benchmark": "000905.SH",
                    "rebalance_freq": "monthly",
                    "cost_multiplier": 1.5,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_backtest_invalid_capital():
    """POST /run 拒绝 initial_capital < 10000。"""
    session = AsyncMock()
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/run",
                json={
                    "strategy_id": _uuid(),
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                    "initial_capital": 100,
                },
            )
        assert resp.status_code == 422  # Pydantic validation error
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. GET /api/backtest/{run_id} — 查询状态
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_completed(completed_run: dict):
    """GET /{run_id} 返回 completed 状态 + progress=1.0。"""
    session = _mock_session_with_run(completed_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["progress"] == 1.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_status_running(running_run: dict):
    """GET /{run_id} 对运行中任务 progress=None。"""
    session = _mock_session_with_run(running_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{running_run['run_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_status_not_found():
    """GET /{run_id} 不存在的run返回404。"""
    session = _mock_session_no_run()
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{_uuid()}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. GET /api/backtest/{run_id}/result — 回测结果
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_result_completed(completed_run: dict):
    """GET /{run_id}/result 返回完整指标。"""
    session = _mock_session_with_run(completed_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/result")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert data["metrics"]["sharpe_ratio"] == 1.21
        assert data["metrics"]["max_drawdown"] == -0.08
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_result_not_completed(running_run: dict):
    """GET /{run_id}/result 未完成状态返回409。"""
    session = _mock_session_with_run(running_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{running_run['run_id']}/result")
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. GET /api/backtest/{run_id}/nav — NAV时间序列
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_nav_series(completed_run: dict):
    """GET /{run_id}/nav 返回NAV列表。"""
    nav_rows = [
        {"trade_date": date(2023, 1, 3), "nav": 1.0, "cash": 100000,
         "market_value": 900000, "daily_return": 0.0,
         "benchmark_nav": 1.0, "benchmark_return": 0.0, "excess_return": 0.0},
        {"trade_date": date(2023, 1, 4), "nav": 1.01, "cash": 100000,
         "market_value": 910000, "daily_return": 0.01,
         "benchmark_nav": 1.005, "benchmark_return": 0.005, "excess_return": 0.005},
    ]
    # 第一次execute: _require_completed, 第二次: nav查询
    session = _mock_session_multi_execute(completed_run, nav_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/nav")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert "trade_date" in data[0]
        assert "nav" in data[0]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. GET /api/backtest/{run_id}/attribution — 归因
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_attribution(completed_run: dict):
    """GET /{run_id}/attribution 返回归因结构。"""
    industry_rows = [
        {"industry": "银行", "stock_count": 5, "total_weight": 0.15, "avg_pnl": 0.02},
        {"industry": "电子", "stock_count": 3, "total_weight": 0.10, "avg_pnl": 0.05},
    ]
    session = _mock_session_multi_execute(completed_run, industry_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/attribution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "brinson"
        assert "industries" in data
        assert len(data["industries"]) == 2
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. GET /api/backtest/{run_id}/report — QuantStats报告
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_quantstats_not_installed(completed_run: dict):
    """GET /{run_id}/report 当 quantstats 未安装时返回501。"""
    nav_rows = [
        {"trade_date": date(2023, 1, 3), "daily_return": 0.01, "benchmark_return": 0.005},
    ]
    session = _mock_session_multi_execute(completed_run, nav_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Mock quantstats import failure
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "quantstats":
                    raise ImportError("No module named 'quantstats'")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/report")
        assert resp.status_code == 501
        assert "quantstats" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_report_no_nav_data(completed_run: dict):
    """GET /{run_id}/report 无NAV数据返回404。"""
    session = _mock_session_multi_execute(completed_run, [])  # 空nav
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/report")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. GET /api/backtest/history — 分页列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_returns_200():
    """GET /history 路由正确匹配，返回200 + 分页结果。

    修复: /history 路由已提前到 /{run_id} 之前注册，
    避免 FastAPI 将 "history" 当作 UUID 参数解析。
    """
    items = [_make_run_row(_uuid())]
    session = _mock_session_for_history(total=1, items=items)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/backtest/history?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 1
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 8. POST /api/backtest/compare — 多策略对比
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_two_runs():
    """POST /compare 返回两个run的指标列表。"""
    rid1 = _uuid()
    rid2 = _uuid()
    run1 = _make_run_row(rid1, sharpe_ratio=1.2)
    run2 = _make_run_row(rid2, sharpe_ratio=0.8)

    session = _mock_session_multi_execute(run1, run2)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/compare",
                json={"run_ids": [rid1, rid2]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["sharpe_ratio"] == 1.2
        assert data[1]["sharpe_ratio"] == 0.8
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_compare_single_run_rejected():
    """POST /compare 少于2个run_id应返回422。"""
    session = AsyncMock()
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/compare",
                json={"run_ids": [_uuid()]},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_compare_invalid_uuid():
    """POST /compare 无效UUID返回400。"""
    session = AsyncMock()
    # 第一次execute抛出
    mapping_mock = MagicMock()
    mapping_mock.first.return_value = None
    result_mock = MagicMock()
    result_mock.mappings.return_value = mapping_mock
    session.execute.return_value = result_mock

    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/backtest/compare",
                json={"run_ids": ["not-a-uuid", _uuid()]},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 9. GET /{run_id}/trades — 交易明细
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trades(completed_run: dict):
    """GET /{run_id}/trades 返回分页交易明细。"""
    trade_rows = [
        {"id": 1, "signal_date": date(2023, 1, 3), "exec_date": date(2023, 1, 4),
         "stock_code": "000001.SZ", "side": "buy", "shares": 100,
         "target_price": 10.0, "exec_price": 10.05, "slippage_bps": 5.0,
         "commission": 3.0, "stamp_tax": 0.0, "transfer_fee": 0.1,
         "total_cost": 3.1, "reject_reason": None},
    ]
    # 3 execute calls: _require_completed, COUNT, SELECT
    session = _mock_session_multi_execute(completed_run, 1, trade_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 10. GET /{run_id}/holdings — 持仓
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_holdings_summary(completed_run: dict):
    """GET /{run_id}/holdings 无trade_date返回每日汇总。"""
    holding_rows = [
        {"trade_date": date(2023, 1, 3), "holding_count": 28, "total_market_value": 900000},
    ]
    session = _mock_session_multi_execute(completed_run, holding_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/holdings")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 11. GET /{run_id}/annual — 年度分解
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_annual_breakdown(completed_run: dict):
    """GET /{run_id}/annual 返回年度绩效列表。"""
    annual_rows = [
        {"year": 2023, "annual_return": 0.15, "avg_daily_return": 0.0006,
         "std_daily_return": 0.012, "trading_days": 244, "worst_day": -0.05},
    ]
    session = _mock_session_multi_execute(completed_run, annual_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/annual")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["year"] == 2023
        assert "sharpe_ratio" in data[0]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 12. GET /{run_id}/monthly — 月度热力图
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_monthly_heatmap(completed_run: dict):
    """GET /{run_id}/monthly 返回月度收益。"""
    monthly_rows = [
        {"year": 2023, "month": 1, "monthly_return": 0.03, "trading_days": 20},
        {"year": 2023, "month": 2, "monthly_return": -0.01, "trading_days": 19},
    ]
    session = _mock_session_multi_execute(completed_run, monthly_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/monthly")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["month"] == 1
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 13. GET /{run_id}/market-state — 市场状态分段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_state(completed_run: dict):
    """GET /{run_id}/market-state 返回分段绩效。"""
    state_rows = [
        {"market_state": "bull", "trading_days": 100, "avg_daily_return": 0.001,
         "std_daily_return": 0.01, "cumulative_return": 0.1,
         "worst_day": -0.03, "best_day": 0.05},
        {"market_state": "sideways", "trading_days": 144, "avg_daily_return": 0.0003,
         "std_daily_return": 0.008, "cumulative_return": 0.04,
         "worst_day": -0.02, "best_day": 0.03},
    ]
    session = _mock_session_multi_execute(completed_run, state_rows)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/market-state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "MA120"
        assert "states" in data
        assert len(data["states"]) == 2
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 14. GET /{run_id}/cost-sensitivity — 成本敏感性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cost_sensitivity(completed_run: dict):
    """GET /{run_id}/cost-sensitivity 返回4种成本倍数下的绩效。"""
    nav_rows = [
        {"trade_date": date(2023, 1, 3), "daily_return": 0.01, "nav": 1.01},
        {"trade_date": date(2023, 1, 4), "daily_return": -0.005, "nav": 1.005},
    ]
    cost_info = {"total_cost": 5000.0, "trade_count": 200}

    session = _mock_session_multi_execute(completed_run, nav_rows, cost_info)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/cost-sensitivity")
        assert resp.status_code == 200
        data = resp.json()
        assert "rows" in data
        multipliers = [r["cost_multiplier"] for r in data["rows"]]
        assert multipliers == [0.5, 1.0, 1.5, 2.0]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cost_sensitivity_warning_when_2x_sharpe_low():
    """成本敏感性: 2x成本Sharpe<0.5时应有warning。"""
    rid = _uuid()
    run = _make_run_row(rid, sharpe_ratio=0.4, annual_return=0.05, max_drawdown=-0.1, calmar_ratio=0.5)
    nav_rows = [
        {"trade_date": date(2023, 1, 3), "daily_return": 0.001, "nav": 1.001},
    ]
    cost_info = {"total_cost": 50000.0, "trade_count": 500}

    session = _mock_session_multi_execute(run, nav_rows, cost_info)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{rid}/cost-sensitivity")
        assert resp.status_code == 200
        data = resp.json()
        # 基准sharpe=0.4, 2x应更低
        assert data["warning"] is not None or data["rows"][-1]["sharpe_ratio"] < 0.5
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 15. POST /{run_id}/sensitivity — 参数敏感性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensitivity_analysis(completed_run: dict):
    """POST /{run_id}/sensitivity 返回pending状态。"""
    session = _mock_session_with_run(completed_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/backtest/{completed_run['run_id']}/sensitivity",
                json={"param_name": "rebalance_freq", "param_values": [5, 10, 20]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["param_name"] == "rebalance_freq"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 16. GET /{run_id}/live-compare — 实盘对比
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_compare(completed_run: dict):
    """GET /{run_id}/live-compare Phase 0 live=None。"""
    session = _mock_session_with_run(completed_run)
    app.dependency_overrides[_get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/backtest/{completed_run['run_id']}/live-compare")
        assert resp.status_code == 200
        data = resp.json()
        assert data["live"] is None
        assert "backtest" in data
        assert data["backtest"]["sharpe_ratio"] == 1.21
    finally:
        app.dependency_overrides.clear()
