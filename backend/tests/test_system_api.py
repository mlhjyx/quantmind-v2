"""System API 路由测试。

覆盖三个端点: /api/system/datasources, /api/system/health, /api/system/scheduler。
使用 FastAPI dependency_overrides + unittest.mock 隔离外部依赖（DB/Redis/Celery/subprocess）。
不依赖真实数据库或 Redis，只验证路由层逻辑（状态码、响应结构、字段类型）。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# 辅助：提供假的 DB session（覆盖 get_db）
# ---------------------------------------------------------------------------


def _override_get_db(mock_session: Any):
    """返回 FastAPI Depends 覆盖函数，注入给定的 mock session。"""

    async def _dep():
        yield mock_session

    return _dep


def _make_mock_session(fetchone_result: Any = None, execute_result: Any = None) -> MagicMock:
    """创建 AsyncSession mock。

    Args:
        fetchone_result: execute().fetchone() 的返回值。
        execute_result: execute() 本身的返回值（若提供则忽略 fetchone_result）。

    Returns:
        配置好的 MagicMock。
    """
    session = MagicMock()
    if execute_result is not None:
        session.execute = AsyncMock(return_value=execute_result)
    else:
        row_mock = MagicMock()
        row_mock.latest_date = "2026-03-28"
        row_mock.row_count = 1000
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(return_value=row_mock if fetchone_result is None else fetchone_result)
        session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# /api/system/datasources
# ---------------------------------------------------------------------------


class TestDatasourcesEndpoint:
    """测试 GET /api/system/datasources。"""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """正常情况下返回 list，每项含必要字段。"""
        from app.db import get_db

        mock_session = _make_mock_session()
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/datasources")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) > 0
            for item in data:
                assert "name" in item
                assert "table" in item
                assert "latest_date" in item
                assert "row_count" in item
                assert "status" in item
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_status_ok_when_rows_exist(self):
        """有数据行时 status 应为 ok。"""
        from app.db import get_db

        mock_session = _make_mock_session()  # row_count=1000
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/datasources")
            data = resp.json()
            # 所有表都 mock 为 row_count=1000，应全为 ok
            statuses = {item["status"] for item in data}
            assert "ok" in statuses
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_status_empty_when_no_rows(self):
        """空表时 status 应为 empty。"""
        from app.db import get_db

        row_mock = MagicMock()
        row_mock.latest_date = None
        row_mock.row_count = 0
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(return_value=row_mock)
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=result_mock)
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/datasources")
            data = resp.json()
            statuses = {item["status"] for item in data}
            assert "empty" in statuses
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_status_error_on_db_exception(self):
        """DB 抛异常时对应表 status 应为 error。"""
        from app.db import get_db

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/datasources")
            # 路由层捕获了内部异常，整体仍返回 200
            assert resp.status_code == 200
            data = resp.json()
            statuses = {item["status"] for item in data}
            assert "error" in statuses
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /api/system/health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """测试 GET /api/system/health。"""

    @pytest.mark.asyncio
    async def test_returns_required_fields(self):
        """响应必须包含 overall_status, pg, redis, celery, disk, memory。"""
        from app.db import get_db

        mock_session = _make_mock_session()
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with (
                patch("app.api.system._check_redis", return_value={"ok": True}),
                patch("app.api.system._check_celery", return_value={"ok": True, "worker_count": 1}),
                patch("app.api.system._check_disk", return_value={"ok": True, "free_gb": 500.0, "total_gb": 2000.0}),
                patch("app.api.system._check_memory", return_value={"ok": True, "used_gb": 8.0, "total_gb": 32.0, "percent": 25.0}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            for field in ("overall_status", "pg", "redis", "celery", "disk", "memory"):
                assert field in data, f"缺少字段: {field}"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_overall_ok_when_all_pass(self):
        """所有组件正常时 overall_status 应为 ok。"""
        from app.db import get_db

        mock_session = _make_mock_session()
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with (
                patch("app.api.system._check_redis", return_value={"ok": True}),
                patch("app.api.system._check_celery", return_value={"ok": True, "worker_count": 2}),
                patch("app.api.system._check_disk", return_value={"ok": True, "free_gb": 500.0, "total_gb": 2000.0}),
                patch("app.api.system._check_memory", return_value={"ok": True, "used_gb": 8.0, "total_gb": 32.0, "percent": 25.0}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/health")
            assert resp.json()["overall_status"] == "ok"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_overall_critical_when_pg_down(self):
        """PG 不可用时 overall_status 应为 critical。"""
        from app.db import get_db

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("pg down"))
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with (
                patch("app.api.system._check_redis", return_value={"ok": True}),
                patch("app.api.system._check_celery", return_value={"ok": True, "worker_count": 1}),
                patch("app.api.system._check_disk", return_value={"ok": True, "free_gb": 500.0, "total_gb": 2000.0}),
                patch("app.api.system._check_memory", return_value={"ok": True, "used_gb": 8.0, "total_gb": 32.0, "percent": 25.0}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/health")
            assert resp.json()["overall_status"] == "critical"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_overall_degraded_when_celery_down(self):
        """PG/Redis/disk/memory 均 ok 但 Celery 不可用时 overall_status 应为 degraded。"""
        from app.db import get_db

        mock_session = _make_mock_session()
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with (
                patch("app.api.system._check_redis", return_value={"ok": True}),
                patch("app.api.system._check_celery", return_value={"ok": False, "worker_count": 0, "error": "no workers"}),
                patch("app.api.system._check_disk", return_value={"ok": True, "free_gb": 500.0, "total_gb": 2000.0}),
                patch("app.api.system._check_memory", return_value={"ok": True, "used_gb": 8.0, "total_gb": 32.0, "percent": 25.0}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/health")
            assert resp.json()["overall_status"] == "degraded"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_overall_critical_when_disk_full(self):
        """磁盘空间不足时 overall_status 应为 critical。"""
        from app.db import get_db

        mock_session = _make_mock_session()
        app.dependency_overrides[get_db] = _override_get_db(mock_session)
        try:
            with (
                patch("app.api.system._check_redis", return_value={"ok": True}),
                patch("app.api.system._check_celery", return_value={"ok": True, "worker_count": 1}),
                patch("app.api.system._check_disk", return_value={"ok": False, "free_gb": 50.0, "total_gb": 2000.0}),
                patch("app.api.system._check_memory", return_value={"ok": True, "used_gb": 8.0, "total_gb": 32.0, "percent": 25.0}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/system/health")
            assert resp.json()["overall_status"] == "critical"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /api/system/scheduler
# ---------------------------------------------------------------------------


class TestSchedulerEndpoint:
    """测试 GET /api/system/scheduler。"""

    @pytest.mark.asyncio
    async def test_returns_required_fields(self):
        """响应必须包含 platform, task_count, tasks。"""
        with patch("app.api.system._query_task_scheduler", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform" in data
        assert "task_count" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    @pytest.mark.asyncio
    async def test_task_count_matches_list_length(self):
        """task_count 应与 tasks 列表长度一致。"""
        fake_tasks = [
            {
                "task_name": "QM-DailySignal",
                "schedule": "",
                "last_run": "2026-03-28 16:30:00",
                "next_run": "2026-03-29 16:30:00",
                "status": "success",
                "last_result_code": 0,
            },
            {
                "task_name": "QM-Execution",
                "schedule": "",
                "last_run": "2026-03-28 09:00:00",
                "next_run": "2026-03-29 09:00:00",
                "status": "success",
                "last_result_code": 0,
            },
        ]
        with patch("app.api.system._query_task_scheduler", return_value=fake_tasks):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler")
        data = resp.json()
        assert data["task_count"] == 2
        assert len(data["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_task_item_has_required_fields(self):
        """每个任务项必须包含 task_name, last_run, next_run, status。"""
        fake_task = {
            "task_name": "QM-DailySignal",
            "schedule": "",
            "last_run": "2026-03-28 16:30:00",
            "next_run": "2026-03-29 16:30:00",
            "status": "success",
            "last_result_code": 0,
        }
        with patch("app.api.system._query_task_scheduler", return_value=[fake_task]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler")
        task = resp.json()["tasks"][0]
        for field in ("task_name", "last_run", "next_run", "status"):
            assert field in task, f"任务项缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_empty_tasks_on_non_windows(self):
        """非 Windows 环境下 tasks 应为空列表（mock _query_task_scheduler 返回空）。"""
        with patch("app.api.system._query_task_scheduler", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/system/scheduler")
        data = resp.json()
        assert data["task_count"] == 0
        assert data["tasks"] == []
