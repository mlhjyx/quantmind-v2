"""通知系统测试 -- Templates + Throttler + NotificationService + API端点。

测试策略:
- Templates / Throttler: 纯单元测试，无外部依赖。
- NotificationService: mock DB session + mock dingtalk，验证业务逻辑。
- API端点: dependency_overrides mock掉 Repo/Service，验证路由层。
"""

import time
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.notification_templates import (
    TEMPLATE_REGISTRY,
    NotificationTemplate,
    get_template,
)
from app.services.notification_throttler import NotificationThrottler


# ============================================================================
# Templates Tests (4个)
# ============================================================================


class TestNotificationTemplates:
    """通知模板单元测试。"""

    def test_get_template_existing_key(self):
        """已注册的key返回对应模板对象。"""
        tpl = get_template("health_check_failed")
        assert isinstance(tpl, NotificationTemplate)
        assert tpl.key == "health_check_failed"
        assert tpl.default_level == "P0"

    def test_get_template_unknown_key_raises(self):
        """未注册的key抛出KeyError。"""
        with pytest.raises(KeyError, match="通知模板.*不存在"):
            get_template("nonexistent_template_key")

    def test_render_replaces_variables(self):
        """render正确替换占位变量，返回(title, content, level)三元组。"""
        tpl = get_template("health_check_failed")
        title, content, level = tpl.render(
            check_time="2026-03-22 17:00:00",
            failed_items="PostgreSQL连接",
        )
        assert "PostgreSQL连接" in title
        assert "2026-03-22 17:00:00" in content
        assert level == "P0"

    def test_all_14_templates_render_without_error(self):
        """全部14个注册模板都能成功render，不抛异常。"""
        assert len(TEMPLATE_REGISTRY) == 19, f"期望19个模板，实际{len(TEMPLATE_REGISTRY)}个"

        # 每个模板的测试变量
        test_kwargs: dict[str, dict[str, Any]] = {
            "health_check_failed": {
                "check_time": "2026-03-22 17:00",
                "failed_items": "Redis",
            },
            "circuit_breaker_triggered": {
                "market": "A股",
                "state": "降仓",
                "drawdown": 12.5,
                "trigger_reason": "月亏>10%",
            },
            "daily_signal_complete": {
                "trade_date": "2026-03-22",
                "signal_count": 30,
                "buy_count": 10,
                "sell_count": 5,
                "hold_count": 15,
            },
            "daily_execute_complete": {
                "market": "A股",
                "filled": 28,
                "total": 30,
                "rejected": 2,
                "slippage_bps": 3.5,
            },
            "rebalance_summary": {
                "market": "A股",
                "trade_date": "2026-03-22",
                "buy_count": 10,
                "sell_count": 5,
                "turnover": 23.4,
                "buy_list": "600519,000858",
                "sell_list": "601318",
            },
            "paper_trading_daily_report": {
                "trade_date": "2026-03-22",
                "nav": 1.05,
                "daily_return": "+0.3%",
                "cum_return": "+5.0%",
                "position_count": 28,
                "beta": 0.25,
            },
            "factor_ic_decay": {
                "factor_name": "momentum_20d",
                "ic_current": 0.012,
                "ic_baseline": 0.035,
                "decay_pct": 65.7,
            },
            "parameter_changed": {
                "param_name": "rebalance_threshold",
                "old_value": 0.05,
                "new_value": 0.03,
                "changed_by": "admin",
            },
            "pipeline_error": {
                "task_name": "daily_factor_calc",
                "stage": "因子计算",
                "error_message": "NaN detected",
                "impact": "当日信号延迟",
            },
            "factor_coverage_low": {
                "factor_name": "turnover_mean_20",
                "count": 50,
                "trade_date": "2026-03-22",
            },
            "factor_coverage_warning": {
                "factor_name": "volatility_20",
                "count": 200,
                "trade_date": "2026-03-22",
            },
            "industry_concentration_high": {
                "max_industry": "银行",
                "max_weight": "35.2%",
                "trade_date": "2026-03-22",
                "industry_distribution": "银行35.2%, 食品20.1%",
            },
            "high_turnover_alert": {
                "overlap_ratio": "40%",
                "trade_date": "2026-03-22",
                "prev_count": 15,
                "overlap_count": 6,
                "new_codes": "600519,000858",
                "exit_codes": "601318,000001",
            },
            "drawdown_warning": {
                "current_dd": 12.5,
                "threshold": 15.0,
                "nav": 950000,
            },
            "data_update_failed": {
                "source": "Tushare",
                "date": "2026-03-22",
                "error": "API rate limit exceeded",
            },
            "paper_milestone": {
                "day": 30,
                "total": 60,
                "nav": 1050000,
                "sharpe": 0.95,
                "mdd": 8.5,
            },
            "signal_blocked": {
                "date": "2026-03-22",
                "reason": "健康预检失败: Redis连接异常",
            },
            "factor_active_count_low": {
                "count": 3,
                "min_count": 5,
            },
            "system_disk_warning": {
                "free_gb": 8.5,
                "threshold_gb": 10,
                "largest_dir": "/data/logs",
            },
        }

        for key, tpl in TEMPLATE_REGISTRY.items():
            kwargs = test_kwargs[key]
            title, content, level = tpl.render(**kwargs)
            assert isinstance(title, str) and len(title) > 0, f"模板{key}的title为空"
            assert isinstance(content, str) and len(content) > 0, f"模板{key}的content为空"
            assert level in ("P0", "P1", "P2", "P3"), f"模板{key}的level={level}不合法"


# ============================================================================
# Throttler Tests (4个)
# ============================================================================


class TestNotificationThrottler:
    """通知防洪泛限流器单元测试。"""

    def test_first_call_allows(self):
        """首次调用返回True（允许发送）。"""
        throttler = NotificationThrottler()
        assert throttler.throttle("P0", "测试标题") is True

    def test_immediate_repeat_blocked(self):
        """立刻重复调用同一(level, title)返回False（被限流）。"""
        throttler = NotificationThrottler()
        assert throttler.throttle("P1", "重复测试") is True
        assert throttler.throttle("P1", "重复测试") is False

    def test_p0_short_interval_p3_long_interval(self):
        """P0间隔60s远短于P3间隔3600s。"""
        throttler = NotificationThrottler()
        assert throttler.get_interval("P0") == 60
        assert throttler.get_interval("P3") == 3600
        assert throttler.get_interval("P0") < throttler.get_interval("P3")

    def test_different_titles_independent(self):
        """不同title之间不互相限流。"""
        throttler = NotificationThrottler()
        assert throttler.throttle("P1", "标题A") is True
        assert throttler.throttle("P1", "标题B") is True  # 不同title，应允许
        assert throttler.throttle("P1", "标题A") is False  # 同一title，应限流


# ============================================================================
# API Tests (5个)
# ============================================================================


def _make_notification_repo_mock(
    items: list[dict] | None = None,
    unread_count: int = 3,
    get_by_id_result: dict | None = None,
    mark_read_result: bool = True,
) -> MagicMock:
    """创建NotificationRepository mock。"""
    repo = MagicMock()
    repo.list_notifications = AsyncMock(return_value=items or [])
    repo.count_unread = AsyncMock(return_value=unread_count)
    repo.get_by_id = AsyncMock(return_value=get_by_id_result)
    repo.mark_read = AsyncMock(return_value=mark_read_result)
    return repo


def _make_notification_service_mock(
    send_result: dict | None = None,
) -> MagicMock:
    """创建NotificationService mock。"""
    svc = MagicMock()
    svc.send = AsyncMock(
        return_value=send_result
        or {
            "id": "test-uuid-001",
            "level": "P2",
            "category": "system",
            "market": "system",
            "title": "测试通知",
            "content": "这是一条测试通知",
            "link": None,
            "is_read": False,
            "is_acted": False,
            "created_at": "2026-03-22T17:00:00",
        }
    )
    return svc


@pytest.fixture
def _override_notification_repo():
    """Override NotificationRepository依赖，含默认数据。"""
    from app.api.notifications import _get_repo

    sample_items = [
        {
            "id": "n-001",
            "level": "P0",
            "category": "system",
            "market": "system",
            "title": "健康预检失败",
            "content": "Redis连接异常",
            "link": None,
            "is_read": False,
            "is_acted": False,
            "created_at": "2026-03-22T16:30:00",
        },
        {
            "id": "n-002",
            "level": "P2",
            "category": "pipeline",
            "market": "astock",
            "title": "信号生成完成",
            "content": "30个信号",
            "link": None,
            "is_read": True,
            "is_acted": False,
            "created_at": "2026-03-22T17:20:00",
        },
    ]
    mock_repo = _make_notification_repo_mock(
        items=sample_items,
        unread_count=3,
        get_by_id_result=sample_items[0],
        mark_read_result=True,
    )
    app.dependency_overrides[_get_repo] = lambda: mock_repo
    yield mock_repo
    app.dependency_overrides.pop(_get_repo, None)


@pytest.fixture
def _override_notification_repo_not_found():
    """Override NotificationRepository，通知不存在场景。"""
    from app.api.notifications import _get_repo

    mock_repo = _make_notification_repo_mock(
        get_by_id_result=None,
        mark_read_result=False,
    )
    app.dependency_overrides[_get_repo] = lambda: mock_repo
    yield mock_repo
    app.dependency_overrides.pop(_get_repo, None)


@pytest.fixture
def _override_notification_service():
    """Override NotificationService依赖。"""
    from app.api.notifications import _get_service

    mock_svc = _make_notification_service_mock()
    app.dependency_overrides[_get_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(_get_service, None)


class TestNotificationAPI:
    """通知API端点测试（5个端点）。"""

    @pytest.mark.asyncio
    async def test_list_notifications(self, client, _override_notification_repo):
        """GET /api/notifications 返回items列表和unread_count。"""
        resp = await client.get("/api/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 2
        assert "unread_count" in data
        assert data["unread_count"] == 3

    @pytest.mark.asyncio
    async def test_unread_count(self, client, _override_notification_repo):
        """GET /api/notifications/unread-count 返回unread_count数字。"""
        resp = await client.get("/api/notifications/unread-count")
        assert resp.status_code == 200
        data = resp.json()
        assert "unread_count" in data
        assert isinstance(data["unread_count"], int)
        assert data["unread_count"] == 3

    @pytest.mark.asyncio
    async def test_send_test_notification(
        self, client, _override_notification_service, _override_notification_repo
    ):
        """POST /api/notifications/test 发送测试通知返回success。"""
        resp = await client.post(
            "/api/notifications/test",
            json={
                "level": "P2",
                "category": "system",
                "title": "测试通知",
                "content": "测试内容",
                "market": "system",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "notification" in data

    @pytest.mark.asyncio
    async def test_mark_read(self, client, _override_notification_repo):
        """PUT /api/notifications/{id}/read 标记已读返回success。"""
        resp = await client.put("/api/notifications/n-001/read")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["id"] == "n-001"

    @pytest.mark.asyncio
    async def test_get_nonexistent_notification_returns_404(
        self, client, _override_notification_repo_not_found
    ):
        """GET /api/notifications/{id} 不存在的通知返回404。"""
        resp = await client.get("/api/notifications/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert "不存在" in data["detail"]
