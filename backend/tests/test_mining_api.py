"""单元测试 — Mining API Router + MiningService (Sprint 1.17)

覆盖:
  POST /api/mining/run               — 正常提交 / 无效engine / 并发冲突409
  GET  /api/mining/tasks             — 列表 / engine筛选 / status筛选
  GET  /api/mining/tasks/{task_id}   — 正常获取 / 404
  POST /api/mining/tasks/{task_id}/cancel — 正常取消 / 已完成400 / 404
  POST /api/mining/evaluate          — 正常evaluate / 非法DSL400

测试策略:
  - Mock MiningService 所有方法（单元测试不依赖DB/Celery）
  - 边界条件: 404/400/409 所有 HTTPException 路径
  - 使用 TestClient 同步调用 FastAPI 路由
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.mining import router
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


# ---------------------------------------------------------------------------
# 辅助: 构建 TestClient，注入 mock MiningService
# ---------------------------------------------------------------------------

def _make_client(mock_svc: Any) -> TestClient:
    """构建带 mock MiningService 的 TestClient。"""
    app = FastAPI()
    app.include_router(router)

    with patch("app.api.mining._get_mining_service", return_value=mock_svc):
        client = TestClient(app, raise_server_exceptions=False)
        return client, app


def _mock_svc() -> MagicMock:
    """创建 MiningService mock（所有方法都是 AsyncMock）。"""
    svc = MagicMock()
    svc.start_mining_task = AsyncMock()
    svc.list_tasks = AsyncMock()
    svc.get_task_detail = AsyncMock()
    svc.cancel_task = AsyncMock()
    svc.evaluate_factor_gate = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# POST /api/mining/run
# ---------------------------------------------------------------------------


class TestRunMining:
    """POST /api/mining/run 端点测试。"""

    def test_run_gp_success(self) -> None:
        """正常提交GP任务，返回202+task_id。"""
        svc = _mock_svc()
        svc.start_mining_task.return_value = {
            "task_id": "abc-123",
            "run_id": "gp_2026w14_abc123",
            "status": "submitted",
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/run", json={
                "engine": "gp",
                "generations": 50,
                "population": 100,
                "islands": 3,
            })

        assert resp.status_code == 202
        data = resp.json()
        assert data["task_id"] == "abc-123"
        assert data["run_id"] == "gp_2026w14_abc123"
        assert data["engine"] == "gp"
        assert data["status"] == "submitted"

        svc.start_mining_task.assert_called_once()
        call_kwargs = svc.start_mining_task.call_args
        assert call_kwargs.kwargs["engine"] == "gp"
        assert call_kwargs.kwargs["config"]["generations"] == 50

    def test_run_invalid_engine_returns_422(self) -> None:
        """无效engine值（非gp/bruteforce/llm）返回422。"""
        svc = _mock_svc()
        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/run", json={
                "engine": "unknown_engine",
                "generations": 10,
            })

        assert resp.status_code == 422  # pydantic pattern validation

    def test_run_conflict_409(self) -> None:
        """同引擎任务已在运行时返回409。"""
        svc = _mock_svc()
        svc.start_mining_task.side_effect = RuntimeError("gp引擎已有任务在运行")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/run", json={"engine": "gp"})

        assert resp.status_code == 409
        assert "已有任务在运行" in resp.json()["detail"]

    def test_run_bad_params_400(self) -> None:
        """ValueError时返回400。"""
        svc = _mock_svc()
        svc.start_mining_task.side_effect = ValueError("config非法")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/run", json={"engine": "gp"})

        assert resp.status_code == 400

    def test_run_bruteforce_engine(self) -> None:
        """bruteforce引擎可正常提交。"""
        svc = _mock_svc()
        svc.start_mining_task.return_value = {
            "task_id": "bf-456",
            "run_id": "bruteforce_2026w14_bf456",
            "status": "submitted",
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/run", json={"engine": "bruteforce"})

        assert resp.status_code == 202
        assert resp.json()["engine"] == "bruteforce"


# ---------------------------------------------------------------------------
# GET /api/mining/tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    """GET /api/mining/tasks 端点测试。"""

    _SAMPLE_TASKS = [
        {
            "run_id": "gp_2026w14_abc",
            "engine": "gp",
            "status": "completed",
            "started_at": "2026-03-28T22:00:00",
            "finished_at": "2026-03-29T00:05:00",
            "config": {"generations": 50},
            "stats": {"total_evaluated": 4000, "passed_gate_full": 3},
            "error_message": None,
        }
    ]

    def test_list_default(self) -> None:
        """默认列表返回200+数组。"""
        svc = _mock_svc()
        svc.list_tasks.return_value = self._SAMPLE_TASKS

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).get("/api/mining/tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["engine"] == "gp"

    def test_list_with_engine_filter(self) -> None:
        """engine筛选参数正确传递给 MiningService。"""
        svc = _mock_svc()
        svc.list_tasks.return_value = []

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            TestClient(app).get("/api/mining/tasks?engine=gp&status=completed")

        svc.list_tasks.assert_called_once_with(engine="gp", status="completed", limit=20)

    def test_list_with_limit(self) -> None:
        """limit参数正确传递。"""
        svc = _mock_svc()
        svc.list_tasks.return_value = []

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            TestClient(app).get("/api/mining/tasks?limit=5")

        svc.list_tasks.assert_called_once_with(engine=None, status=None, limit=5)

    def test_list_empty_result(self) -> None:
        """空列表返回200+[]。"""
        svc = _mock_svc()
        svc.list_tasks.return_value = []

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).get("/api/mining/tasks")

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/mining/tasks/{task_id}
# ---------------------------------------------------------------------------


class TestGetTaskDetail:
    """GET /api/mining/tasks/{task_id} 端点测试。"""

    _SAMPLE_DETAIL = {
        "task_id": "abc-123",
        "run_id": "gp_2026w14_abc",
        "engine": "gp",
        "status": "completed",
        "started_at": "2026-03-28T22:00:00",
        "finished_at": "2026-03-29T00:05:00",
        "config": {"generations": 50},
        "stats": {"total_evaluated": 4000, "passed_gate_full": 3},
        "error_message": None,
        "candidates": [
            {
                "id": 1,
                "factor_name": "gp_a3f8c2",
                "factor_expr": "ts_mean(cs_rank(close), 20)",
                "ast_hash": "a3f8c2d1e4f5a6b7",
                "gate_result": {"G1": "PASS", "G2": "PASS"},
                "sharpe_1y": 0.62,
                "sharpe_5y": 0.48,
                "status": "pending",
                "created_at": "2026-03-29T00:05:00",
            }
        ],
    }

    def test_get_detail_success(self) -> None:
        """正常获取任务详情，返回200+完整字典。"""
        svc = _mock_svc()
        svc.get_task_detail.return_value = self._SAMPLE_DETAIL

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).get("/api/mining/tasks/abc-123")

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "abc-123"
        assert data["status"] == "completed"
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["factor_expr"] == "ts_mean(cs_rank(close), 20)"

    def test_get_detail_404(self) -> None:
        """task_id 不存在时返回404。"""
        svc = _mock_svc()
        svc.get_task_detail.return_value = None

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).get("/api/mining/tasks/nonexistent-id")

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_get_detail_passes_task_id(self) -> None:
        """task_id 正确传递给 MiningService。"""
        svc = _mock_svc()
        svc.get_task_detail.return_value = self._SAMPLE_DETAIL

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            TestClient(app).get("/api/mining/tasks/my-task-id")

        svc.get_task_detail.assert_called_once_with("my-task-id")


# ---------------------------------------------------------------------------
# POST /api/mining/tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelTask:
    """POST /api/mining/tasks/{task_id}/cancel 端点测试。"""

    def test_cancel_success(self) -> None:
        """正常取消运行中任务，返回200。"""
        svc = _mock_svc()
        svc.cancel_task.return_value = {
            "task_id": "abc-123",
            "run_id": "gp_2026w14_abc",
            "cancelled": True,
            "message": "取消信号已发送",
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/tasks/abc-123/cancel")

        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True

    def test_cancel_404(self) -> None:
        """task_id 不存在时返回404。"""
        svc = _mock_svc()
        svc.cancel_task.side_effect = LookupError("任务不存在: xyz")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/tasks/xyz/cancel")

        assert resp.status_code == 404

    def test_cancel_already_completed_400(self) -> None:
        """已完成的任务取消返回400。"""
        svc = _mock_svc()
        svc.cancel_task.side_effect = ValueError("任务已结束 (status=completed)，无法取消。")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/tasks/done-task/cancel")

        assert resp.status_code == 400
        assert "无法取消" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/mining/evaluate
# ---------------------------------------------------------------------------


class TestEvaluateFactor:
    """POST /api/mining/evaluate 端点测试。"""

    def test_evaluate_success(self) -> None:
        """正常评估因子，返回200+Gate结果。"""
        svc = _mock_svc()
        svc.evaluate_factor_gate.return_value = {
            "factor_name": "eval_a3f8c2d1",
            "factor_expr": "ts_mean(cs_rank(close), 20)",
            "gate_result": {
                "G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS",
                "G5": "PASS", "G6": "PASS", "G7": "PENDING", "G8": "PENDING",
            },
            "overall_passed": True,
            "ic_mean": 0.0312,
            "t_stat": 3.15,
            "elapsed_seconds": 4.2,
            "quick_only": False,
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "ts_mean(cs_rank(close), 20)",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_passed"] is True
        assert data["ic_mean"] == pytest.approx(0.0312, abs=1e-6)
        assert data["gate_result"]["G1"] == "PASS"

    def test_evaluate_quick_only(self) -> None:
        """run_quick_only=True 正确传递给 MiningService。"""
        svc = _mock_svc()
        svc.evaluate_factor_gate.return_value = {
            "factor_name": "eval_x",
            "factor_expr": "ts_mean(close, 20)",
            "gate_result": {"G1": "PASS"},
            "overall_passed": False,
            "ic_mean": 0.01,
            "t_stat": 1.5,
            "elapsed_seconds": 0.8,
            "quick_only": True,
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "ts_mean(close, 20)",
                "run_quick_only": True,
            })

        svc.evaluate_factor_gate.assert_called_once_with(
            factor_expr="ts_mean(close, 20)",
            factor_name=None,
            quick_only=True,
        )

    def test_evaluate_invalid_dsl_400(self) -> None:
        """非法DSL表达式返回400。"""
        svc = _mock_svc()
        svc.evaluate_factor_gate.side_effect = ValueError("DSL 表达式非法: 未知算子 unknown_op")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "unknown_op(close, 5)",
            })

        assert resp.status_code == 400
        assert "DSL" in resp.json()["detail"] or "非法" in resp.json()["detail"]

    def test_evaluate_db_unavailable_503(self) -> None:
        """DB不可用时返回503。"""
        svc = _mock_svc()
        svc.evaluate_factor_gate.side_effect = ConnectionError("行情数据加载失败")

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "ts_mean(close, 20)",
            })

        assert resp.status_code == 503

    def test_evaluate_empty_expr_422(self) -> None:
        """空 factor_expr 触发 pydantic 校验错误422。"""
        svc = _mock_svc()

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            resp = TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "",
            })

        assert resp.status_code == 422

    def test_evaluate_with_custom_name(self) -> None:
        """自定义 factor_name 正确传递给 MiningService。"""
        svc = _mock_svc()
        svc.evaluate_factor_gate.return_value = {
            "factor_name": "my_custom_factor",
            "factor_expr": "inv(pb)",
            "gate_result": {},
            "overall_passed": False,
            "ic_mean": 0.0,
            "t_stat": 0.0,
            "elapsed_seconds": 1.0,
            "quick_only": False,
        }

        client, app = _make_client(svc)
        with patch("app.api.mining._get_mining_service", return_value=svc):
            TestClient(app).post("/api/mining/evaluate", json={
                "factor_expr": "inv(pb)",
                "factor_name": "my_custom_factor",
            })

        svc.evaluate_factor_gate.assert_called_once_with(
            factor_expr="inv(pb)",
            factor_name="my_custom_factor",
            quick_only=False,
        )


# ---------------------------------------------------------------------------
# MiningService 单元测试（同引擎并发锁逻辑）
# ---------------------------------------------------------------------------


class TestMiningServiceConcurrencyLock:
    """MiningService.start_mining_task 并发锁逻辑测试。

    不依赖DB：mock SQLAlchemy session。
    """

    @pytest.mark.asyncio
    async def test_concurrent_gp_raises_runtime_error(self) -> None:
        """同引擎已有 running 任务时抛出 RuntimeError。"""
        from unittest.mock import AsyncMock, MagicMock

        # Mock session 返回有 running 记录
        mock_row = MagicMock()
        mock_row.fetchone.return_value = ("gp_2026w14_existing",)

        mock_execute_result = MagicMock()
        mock_execute_result.fetchone.return_value = ("gp_2026w14_existing",)

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_execute_result

        from app.services.mining_service import MiningService
        svc = MiningService(mock_session)

        with pytest.raises(RuntimeError, match="已有任务在运行"):
            await svc.start_mining_task(engine="gp", config={"generations": 10})

    @pytest.mark.asyncio
    async def test_invalid_engine_raises_value_error(self) -> None:
        """非法 engine 抛出 ValueError。"""
        from unittest.mock import AsyncMock
        mock_session = AsyncMock()

        from app.services.mining_service import MiningService
        svc = MiningService(mock_session)

        with pytest.raises(ValueError, match="必须是"):
            await svc.start_mining_task(engine="invalid", config={})
