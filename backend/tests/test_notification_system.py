"""通知系统测试 -- Templates + Throttler + NotificationService + API端点。

测试策略:
- Templates / Throttler: 纯单元测试，无外部依赖。
- NotificationService: mock DB session + mock dingtalk，验证业务逻辑。
- API端点: dependency_overrides mock掉 Repo/Service，验证路由层。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from app.main import app
from app.services.notification_service import (
    _get_preferences_sync,
    _in_quiet_window,
    _should_dispatch_external,
)
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
    mark_all_read_count: int = 5,
    delete_old_count: int = 7,
) -> MagicMock:
    """创建NotificationRepository mock。"""
    repo = MagicMock()
    repo.list_notifications = AsyncMock(return_value=items or [])
    repo.count_unread = AsyncMock(return_value=unread_count)
    repo.get_by_id = AsyncMock(return_value=get_by_id_result)
    repo.mark_read = AsyncMock(return_value=mark_read_result)
    repo.mark_all_read = AsyncMock(return_value=mark_all_read_count)
    repo.delete_old = AsyncMock(return_value=delete_old_count)
    repo.get_preferences = AsyncMock(return_value=None)
    repo.upsert_preferences = AsyncMock(return_value={})
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
    async def test_mark_all_read(self, client, _override_notification_repo):
        """PUT /api/notifications/read-all 标记全部已读返回 updated_count。"""
        resp = await client.put("/api/notifications/read-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["updated_count"] == 5

    @pytest.mark.asyncio
    async def test_clear_old(self, client, _override_notification_repo):
        """DELETE /api/notifications/clear-old 清理旧通知返回 deleted_count。"""
        resp = await client.delete("/api/notifications/clear-old")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted_count"] == 7

    @pytest.mark.asyncio
    async def test_clear_old_custom_days(self, client, _override_notification_repo):
        """DELETE /api/notifications/clear-old?days=90 透传 days 给 repo.delete_old。"""
        resp = await client.delete("/api/notifications/clear-old?days=90")
        assert resp.status_code == 200
        _override_notification_repo.delete_old.assert_awaited_once_with(90)

    @pytest.mark.asyncio
    async def test_clear_old_invalid_days_returns_422(self, client, _override_notification_repo):
        """DELETE /api/notifications/clear-old?days=0 超出 [1,365] 返回 422。"""
        resp = await client.delete("/api/notifications/clear-old?days=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_nonexistent_notification_returns_404(
        self, client, _override_notification_repo_not_found
    ):
        """GET /api/notifications/{id} 不存在的通知返回404。"""
        resp = await client.get("/api/notifications/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert "不存在" in data["detail"]


# ============================================================================
# 5. 通知偏好 GET/PUT (DEV_NOTIFICATIONS §8 — Plan K)
# ============================================================================


class TestNotificationPreferences:
    """通知偏好 GET/PUT 端点测试 (mock repo)。"""

    _SAMPLE_PREFS = {
        "id": "pref-uuid-001",
        "toast_p0": True,
        "toast_p1": False,
        "toast_p2": True,
        "toast_p3": True,
        "dingtalk_enabled": True,
        "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=x",
        "dispatch_p0": True,
        "dispatch_p1": True,
        "dispatch_p2": True,
        "quiet_enabled": False,
        "quiet_start": 22,
        "quiet_end": 8,
        "updated_at": "2026-05-20T15:00:00+00:00",
    }

    @pytest.mark.asyncio
    async def test_get_preferences_no_row_returns_defaults(
        self, client, _override_notification_repo
    ):
        """GET /preferences 无记录 → 返回列默认值, id/updated_at 为 None。"""
        _override_notification_repo.get_preferences = AsyncMock(return_value=None)
        resp = await client.get("/api/notifications/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is None
        assert data["updated_at"] is None
        assert data["toast_p0"] is True
        assert data["dingtalk_enabled"] is False
        assert data["quiet_start"] == 23

    @pytest.mark.asyncio
    async def test_get_preferences_existing_row(self, client, _override_notification_repo):
        """GET /preferences 有记录 → 原样返回该行。"""
        _override_notification_repo.get_preferences = AsyncMock(
            return_value=dict(self._SAMPLE_PREFS)
        )
        resp = await client.get("/api/notifications/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pref-uuid-001"
        assert data["toast_p1"] is False
        assert data["dingtalk_webhook"].startswith("https://oapi.dingtalk.com")

    @pytest.mark.asyncio
    async def test_put_preferences_success(self, client, _override_notification_repo):
        """PUT /preferences 全量更新 → 200, upsert 收到全部 12 个字段。"""
        _override_notification_repo.upsert_preferences = AsyncMock(
            return_value=dict(self._SAMPLE_PREFS)
        )
        resp = await client.put(
            "/api/notifications/preferences",
            json={
                "toast_p0": True,
                "toast_p1": False,
                "toast_p2": True,
                "toast_p3": True,
                "dingtalk_enabled": True,
                "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=x",
                "dispatch_p0": True,
                "dispatch_p1": True,
                "dispatch_p2": True,
                "quiet_enabled": False,
                "quiet_start": 22,
                "quiet_end": 8,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "pref-uuid-001"
        sent = _override_notification_repo.upsert_preferences.call_args.args[0]
        assert sent["toast_p1"] is False
        assert sent["quiet_start"] == 22
        assert len(sent) == 12

    @pytest.mark.asyncio
    async def test_put_preferences_empty_body_uses_field_defaults(
        self, client, _override_notification_repo
    ):
        """PUT /preferences 空 body → Pydantic 字段默认值填充 (全量替换语义)。"""
        _override_notification_repo.upsert_preferences = AsyncMock(
            return_value=dict(self._SAMPLE_PREFS)
        )
        resp = await client.put("/api/notifications/preferences", json={})
        assert resp.status_code == 200
        sent = _override_notification_repo.upsert_preferences.call_args.args[0]
        assert sent["toast_p0"] is True
        assert sent["quiet_start"] == 23
        assert sent["dispatch_p2"] is False

    @pytest.mark.asyncio
    async def test_put_preferences_invalid_quiet_hour_returns_422(
        self, client, _override_notification_repo
    ):
        """PUT /preferences quiet_start=25 超出 [0,23] → 422。"""
        resp = await client.put(
            "/api/notifications/preferences",
            json={"quiet_start": 25},
        )
        assert resp.status_code == 422


# ============================================================================
# 6. 外发检查 — dispatch 开关 + 静默时段 (DEV_NOTIFICATIONS §2 line 70 — Plan AH)
# ============================================================================


class TestExternalDispatchCheck:
    """_in_quiet_window / _should_dispatch_external / _get_preferences_sync 单元测试。"""

    @pytest.mark.parametrize(
        "hour,start,end,expected",
        [
            (3, 23, 7, True),  # 跨午夜窗内 (凌晨)
            (23, 23, 7, True),  # start 边界 (含)
            (7, 23, 7, False),  # end 边界 (不含)
            (12, 23, 7, False),  # 跨午夜窗外 (正午)
            (10, 9, 17, True),  # 同日窗内
            (9, 9, 17, True),  # 同日 start 边界 (含)
            (17, 9, 17, False),  # 同日 end 边界 (不含)
            (5, 5, 5, False),  # start==end → 空窗
        ],
    )
    def test_in_quiet_window(self, hour, start, end, expected):
        assert _in_quiet_window(hour, start, end) is expected

    def test_p0_always_dispatches(self):
        """P0 始终发 — 无视静默 + 无视开关。"""
        assert _should_dispatch_external("P0", None, 3) is True  # 凌晨
        assert (
            _should_dispatch_external("P0", {"quiet_enabled": True, "dispatch_p1": False}, 3)
            is True
        )

    def test_p3_and_unknown_never_dispatch(self):
        assert _should_dispatch_external("P3", None, 12) is False
        assert _should_dispatch_external("P9", None, 12) is False

    def test_p1_defaults_noon_dispatches_night_suppressed(self):
        """P1 列默认 (dispatch_p1=T, quiet 23-7): 正午发, 凌晨抑制。"""
        assert _should_dispatch_external("P1", None, 12) is True
        assert _should_dispatch_external("P1", None, 3) is False

    def test_p1_toggle_off_never_dispatches(self):
        assert _should_dispatch_external("P1", {"dispatch_p1": False}, 12) is False

    def test_p1_quiet_disabled_dispatches_at_night(self):
        assert _should_dispatch_external("P1", {"quiet_enabled": False}, 3) is True

    def test_p2_default_toggle_off(self):
        """P2 列默认 dispatch_p2=False → 不外发。"""
        assert _should_dispatch_external("P2", None, 12) is False

    def test_p2_toggle_on_respects_quiet(self):
        assert _should_dispatch_external("P2", {"dispatch_p2": True}, 12) is True
        assert _should_dispatch_external("P2", {"dispatch_p2": True}, 3) is False

    def test_none_pref_values_fall_back_to_defaults(self):
        """偏好字典中 None 值回退到列默认 (非当作 False)。"""
        assert _should_dispatch_external("P1", {"dispatch_p1": None}, 12) is True
        assert _should_dispatch_external("P1", {"dispatch_p1": None}, 3) is False

    def test_get_preferences_sync_row(self):
        """_get_preferences_sync 有行 → dict (列顺序对齐 _prefs_row_to_dict)。"""
        from datetime import datetime as _dt

        row = (
            "pref-id",
            True,
            True,
            True,
            True,
            False,
            None,
            True,
            False,
            True,
            True,
            22,
            8,
            _dt(2026, 5, 21, 9, 0),
        )
        cur = MagicMock()
        cur.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value = cur
        prefs = _get_preferences_sync(conn)
        assert prefs is not None
        assert prefs["dispatch_p1"] is False
        assert prefs["quiet_start"] == 22
        cur.close.assert_called_once()

    def test_get_preferences_sync_no_row(self):
        """_get_preferences_sync 无行 → None。"""
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value = cur
        assert _get_preferences_sync(conn) is None


# ============================================================================
# 7. send_alert sync wrapper — 外发检查 (DEV_NOTIFICATIONS §2 — Plan AI)
# ============================================================================


def _make_prefs_row(
    *,
    dispatch_p1: bool = True,
    dispatch_p2: bool = False,
    quiet_enabled: bool = True,
    quiet_start: int = 23,
    quiet_end: int = 7,
) -> tuple:
    """构造 notification_preferences SELECT 行 (14 列, 对齐 _prefs_row_to_dict)。"""
    return (
        "pref-id",
        True,
        True,
        True,
        True,  # id, toast_p0-3
        False,
        None,  # dingtalk_enabled, dingtalk_webhook
        True,
        dispatch_p1,
        dispatch_p2,  # dispatch_p0-2
        quiet_enabled,
        quiet_start,
        quiet_end,
        None,  # quiet_*, updated_at
    )


def _make_conn_with_prefs(row: tuple) -> MagicMock:
    """MagicMock psycopg2 conn — cursor.fetchone 返回给定 prefs row。"""
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


class TestSendAlertDispatchCheck:
    """send_alert 外发检查 — 复用 _should_dispatch_external (Plan AI)。"""

    def test_p1_suppressed_by_toggle_off(self):
        """P1 + dispatch_p1=False → 抑制, 返回 True, dingtalk 不调用。"""
        from app.services import notification_service as ns

        conn = _make_conn_with_prefs(_make_prefs_row(dispatch_p1=False))
        with patch.object(ns.dingtalk, "send_markdown_sync") as mock_send:
            result = ns.send_alert("P1", "t", "c", conn=conn)
        assert result is True
        mock_send.assert_not_called()

    def test_p1_permissive_dispatches(self):
        """P1 + dispatch_p1=True + quiet 关 → 外发, dingtalk 调用。"""
        from app.services import notification_service as ns

        conn = _make_conn_with_prefs(_make_prefs_row(dispatch_p1=True, quiet_enabled=False))
        with patch.object(ns.dingtalk, "send_markdown_sync", return_value=True) as mock_send:
            result = ns.send_alert("P1", "t", "c", conn=conn)
        assert result is True
        mock_send.assert_called_once()

    def test_p0_always_dispatches_despite_suppressive_prefs(self):
        """P0 始终发 — 即使偏好对 P1 抑制。"""
        from app.services import notification_service as ns

        conn = _make_conn_with_prefs(_make_prefs_row(dispatch_p1=False))
        with patch.object(ns.dingtalk, "send_markdown_sync", return_value=True) as mock_send:
            ns.send_alert("P0", "t", "c", conn=conn)
        mock_send.assert_called_once()

    def test_no_conn_skips_pref_gate_and_dispatches(self):
        """conn=None → 无法读偏好 → fail-safe 照发。"""
        from app.services import notification_service as ns

        with patch.object(ns.dingtalk, "send_markdown_sync", return_value=True) as mock_send:
            ns.send_alert("P1", "t", "c", conn=None)
        mock_send.assert_called_once()

    def test_pref_read_failure_fail_safe_dispatches(self):
        """读偏好抛异常 → fail-safe 照发 (告警不被静默丢失)。"""
        from app.services import notification_service as ns

        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("db down")
        with patch.object(ns.dingtalk, "send_markdown_sync", return_value=True) as mock_send:
            result = ns.send_alert("P1", "t", "c", conn=conn)
        assert result is True
        mock_send.assert_called_once()
