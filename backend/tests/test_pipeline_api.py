"""Pipeline API 测试 — POST /api/pipeline/trigger (DEV_AI_EVOLUTION §12.2 — Plan AK).

测试策略: mock MiningService + override get_db / _require_local 依赖,
验证路由层 (引擎透传 / 错误码映射 / 本机访问限制), 不触 DB / Celery。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed")

from app.api.pipeline import _require_local
from app.db import get_db
from app.main import app


@pytest.fixture
def _override_pipeline_deps():
    """Override get_db (mock session) + _require_local (放行) — trigger 路由层测试。"""
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[_require_local] = lambda: None
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(_require_local, None)


class TestTriggerPipeline:
    """POST /api/pipeline/trigger。"""

    @pytest.mark.asyncio
    async def test_trigger_success(self, client, _override_pipeline_deps):
        """合法引擎 → 202, 返回 run_id/task_id/engine/status。"""
        with patch("app.api.pipeline.MiningService") as mock_cls:
            mock_cls.return_value.start_mining_task = AsyncMock(
                return_value={
                    "run_id": "gp_2026w21_abc123",
                    "task_id": "task-uuid-1",
                    "status": "submitted",
                }
            )
            resp = await client.post(
                "/api/pipeline/trigger",
                json={"engine": "gp", "config": {"generations": 20}},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["run_id"] == "gp_2026w21_abc123"
        assert data["task_id"] == "task-uuid-1"
        assert data["engine"] == "gp"
        assert data["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_trigger_passes_engine_and_config(self, client, _override_pipeline_deps):
        """engine + config 原样透传给 start_mining_task。"""
        with patch("app.api.pipeline.MiningService") as mock_cls:
            mock_start = AsyncMock(
                return_value={"run_id": "r", "task_id": "t", "status": "submitted"}
            )
            mock_cls.return_value.start_mining_task = mock_start
            await client.post(
                "/api/pipeline/trigger",
                json={"engine": "bruteforce", "config": {"k": "v"}},
            )
        mock_start.assert_awaited_once_with(engine="bruteforce", config={"k": "v"})

    @pytest.mark.asyncio
    async def test_trigger_already_running_returns_409(self, client, _override_pipeline_deps):
        """同引擎任务已运行 → RuntimeError → 409。"""
        with patch("app.api.pipeline.MiningService") as mock_cls:
            mock_cls.return_value.start_mining_task = AsyncMock(
                side_effect=RuntimeError("GP 引擎已有任务在运行")
            )
            resp = await client.post("/api/pipeline/trigger", json={"engine": "gp"})
        assert resp.status_code == 409
        assert "运行" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_trigger_invalid_engine_returns_422(self, client, _override_pipeline_deps):
        """非法引擎 → Pydantic pattern 拒绝 → 422。"""
        resp = await client.post("/api/pipeline/trigger", json={"engine": "xgboost"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_trigger_default_engine_gp(self, client, _override_pipeline_deps):
        """不传 engine → 默认 gp。"""
        with patch("app.api.pipeline.MiningService") as mock_cls:
            mock_start = AsyncMock(
                return_value={"run_id": "r", "task_id": "t", "status": "submitted"}
            )
            mock_cls.return_value.start_mining_task = mock_start
            resp = await client.post("/api/pipeline/trigger", json={})
        assert resp.status_code == 202
        assert mock_start.await_args.kwargs["engine"] == "gp"


class TestRequireLocal:
    """_require_local 本机访问限制。"""

    def test_rejects_non_local_ip(self):
        """非本机 IP → raise HTTPException 403。"""
        from fastapi import HTTPException

        req = MagicMock()
        req.client.host = "10.0.0.5"
        with pytest.raises(HTTPException) as exc:
            _require_local(req)
        assert exc.value.status_code == 403

    def test_allows_localhost(self):
        """127.0.0.1 → 放行 (不 raise)。"""
        req = MagicMock()
        req.client.host = "127.0.0.1"
        _require_local(req)
