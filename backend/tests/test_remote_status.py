"""远程状态API测试。

覆盖端点: GET /api/v1/ping, GET /api/v1/status。
使用 FastAPI dependency_overrides + unittest.mock 隔离外部依赖。
不依赖真实数据库或 Redis，只验证路由逻辑（状态码、响应结构、认证）。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _override_get_db(mock_session: Any):
    """返回注入 mock session 的 Depends 覆盖函数。"""

    async def _dep():
        yield mock_session

    return _dep


def _make_mock_session() -> MagicMock:
    """创建返回合理 PT 状态数据的 AsyncSession mock。"""
    session = MagicMock()

    # 每次 execute 调用都返回一个可配置的 result mock
    row_mock = MagicMock()
    row_mock.nav = 995000.0
    row_mock.cumulative_return = -0.005
    row_mock.trade_date = "2026-03-28"
    row_mock.strategy_version = "v1.1"
    row_mock.status = "running"
    row_mock.day_count = 3

    result_mock = MagicMock()
    result_mock.fetchone = MagicMock(return_value=row_mock)
    result_mock.scalar = MagicMock(return_value=None)

    session.execute = AsyncMock(return_value=result_mock)
    return session


def _make_empty_session() -> MagicMock:
    """创建返回空数据（无 PT 运行）的 AsyncSession mock。"""
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.fetchone = MagicMock(return_value=None)
    result_mock.scalar = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# 测试1: /api/v1/ping — 基础响应结构
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_ok():
    """ping端点返回200, ok=True, 包含ts字段。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get("/api/v1/ping")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "ts" in body
    assert isinstance(body["ts"], str)
    # ts 应是 ISO 8601 格式（包含 T 分隔符）
    assert "T" in body["ts"]


# ---------------------------------------------------------------------------
# 测试2: /api/v1/status — 响应结构完整性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_response_structure():
    """status端点返回完整结构：version/timestamp/pt_status/system/alerts。"""
    mock_session = _make_mock_session()
    app.dependency_overrides[get_db] = _override_get_db(mock_session)

    try:
        with (
            patch("app.api.remote_status._check_redis_sync", return_value=True),
            patch("app.api.remote_status._check_celery_sync", return_value=True),
            patch("app.api.remote_status._disk_free_gb", return_value=1200.0),
            patch("app.api.remote_status._memory_used_pct", return_value=45.2),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get("/api/v1/status")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()

    # 顶层字段
    assert "version" in body
    assert "timestamp" in body
    assert "pt_status" in body
    assert "system" in body
    assert "last_signal_at" in body
    assert "last_execution_at" in body
    assert "alerts" in body

    # pt_status 字段
    pt = body["pt_status"]
    assert "is_running" in pt
    assert "day" in pt
    assert "nav" in pt
    assert "nav_change_pct" in pt
    assert "strategy" in pt

    # system 字段
    sys = body["system"]
    assert "pg_ok" in sys
    assert "redis_ok" in sys
    assert "celery_ok" in sys
    assert "disk_free_gb" in sys
    assert "memory_used_pct" in sys


# ---------------------------------------------------------------------------
# 测试3: 认证 — 无 API Key 时远程请求被拒绝
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_auth_rejected_without_key():
    """REMOTE_API_KEY已设置时，提供错误key的请求返回401。

    ASGITransport 的 request.client.host 为 "testclient"（非 localhost），
    因此 localhost bypass 不会触发，可以正常验证 API Key 认证逻辑。
    """
    mock_session = _make_empty_session()
    app.dependency_overrides[get_db] = _override_get_db(mock_session)

    try:
        with (
            patch("app.api.remote_status.settings") as mock_settings,
            patch("app.api.remote_status._is_localhost", return_value=False),
            patch("app.api.remote_status._check_redis_sync", return_value=False),
            patch("app.api.remote_status._check_celery_sync", return_value=False),
            patch("app.api.remote_status._disk_free_gb", return_value=500.0),
            patch("app.api.remote_status._memory_used_pct", return_value=30.0),
        ):
            mock_settings.REMOTE_API_KEY = "secret-key-123"
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get(
                    "/api/v1/status",
                    headers={"X-API-Key": "wrong-key"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 测试4: 认证 — localhost 请求跳过认证
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_localhost_bypass_auth():
    """REMOTE_API_KEY为空（开发模式）时所有请求放行，无需携带Key。"""
    with (
        patch("app.api.remote_status.settings") as mock_settings,
        patch("app.api.remote_status._is_localhost", return_value=False),
    ):
        mock_settings.REMOTE_API_KEY = ""  # 空 key = 开发模式，全放行
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            response = await client.get("/api/v1/ping")

    assert response.status_code == 200
    assert response.json()["ok"] is True


# ---------------------------------------------------------------------------
# 测试5: 无PT运行时 pt_status.is_running = False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_no_pt_running():
    """无Paper Trading运行时，pt_status.is_running应为False，day=0。"""
    mock_session = _make_empty_session()
    app.dependency_overrides[get_db] = _override_get_db(mock_session)

    try:
        with (
            patch("app.api.remote_status._check_redis_sync", return_value=True),
            patch("app.api.remote_status._check_celery_sync", return_value=False),
            patch("app.api.remote_status._disk_free_gb", return_value=800.0),
            patch("app.api.remote_status._memory_used_pct", return_value=50.0),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get("/api/v1/status")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    pt = response.json()["pt_status"]
    assert pt["is_running"] is False
    assert pt["day"] == 0


# ---------------------------------------------------------------------------
# 测试6: 告警生成 — 磁盘不足时alerts非空
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_alert_on_low_disk():
    """磁盘剩余<100GB时，alerts列表应包含磁盘告警。"""
    mock_session = _make_empty_session()
    app.dependency_overrides[get_db] = _override_get_db(mock_session)

    try:
        with (
            patch("app.api.remote_status._check_redis_sync", return_value=True),
            patch("app.api.remote_status._check_celery_sync", return_value=True),
            patch("app.api.remote_status._disk_free_gb", return_value=50.0),  # 低于100GB
            patch("app.api.remote_status._memory_used_pct", return_value=30.0),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get("/api/v1/status")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert len(alerts) > 0
    assert any("磁盘" in a for a in alerts)


# ---------------------------------------------------------------------------
# 测试7: system字段类型验证
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_system_field_types():
    """system字段中pg_ok/redis_ok/celery_ok为bool，disk_free_gb/memory_used_pct为数值。"""
    mock_session = _make_mock_session()
    app.dependency_overrides[get_db] = _override_get_db(mock_session)

    try:
        with (
            patch("app.api.remote_status._check_redis_sync", return_value=True),
            patch("app.api.remote_status._check_celery_sync", return_value=False),
            patch("app.api.remote_status._disk_free_gb", return_value=1200.0),
            patch("app.api.remote_status._memory_used_pct", return_value=45.2),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get("/api/v1/status")
    finally:
        app.dependency_overrides.pop(get_db, None)

    sys = response.json()["system"]
    assert isinstance(sys["pg_ok"], bool)
    assert isinstance(sys["redis_ok"], bool)
    assert isinstance(sys["celery_ok"], bool)
    assert isinstance(sys["disk_free_gb"], (int, float))
    assert isinstance(sys["memory_used_pct"], (int, float))
