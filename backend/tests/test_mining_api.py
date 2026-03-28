"""单元测试 — Mining API Router + MiningService (Sprint 1.17)

覆盖:
  POST /api/mining/run               — 正常提交 / 无效engine / 并发冲突409
  GET  /api/mining/tasks             — 列表 / engine筛选 / status筛选
  GET  /api/mining/tasks/{task_id}   — 正常获取 / 404
  POST /api/mining/tasks/{task_id}/cancel — 正常取消 / 已完成400 / 404
  POST /api/mining/evaluate          — 正常evaluate / 非法DSL400

测试策略:
  - 通过 dependency_overrides 注入 mock MiningService（不依赖DB/Celery）
  - 边界条件: 404/400/409 所有 HTTPException 路径
  - 使用 TestClient 同步调用 FastAPI 路由
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.mining import _get_mining_service, router
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


# ---------------------------------------------------------------------------
# 辅助: 构建 TestClient，通过 dependency_overrides 注入 mock
# ---------------------------------------------------------------------------

def _mock_svc() -> MagicMock:
    """创建 MiningService mock（所有方法都是 AsyncMock）。"""
    svc = MagicMock()
    svc.start_mining_task = AsyncMock()
    svc.list_tasks = AsyncMock()
    svc.get_task_detail = AsyncMock()
    svc.cancel_task = AsyncMock()
    svc.evaluate_factor_gate = AsyncMock()
    return svc


@pytest.fixture()
def app_client():
    """返回 (app, client)，测试结束后清理 dependency_overrides。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    yield app, client
    app.dependency_overrides.clear()


def _inject(app: Any, svc: Any) -> None:
    """通过 dependency_overrides 注入 mock MiningService。"""
    app.dependency_overrides[_get_mining_service] = lambda: svc


# ---------------------------------------------------------------------------
# POST /api/mining/run
# ---------------------------------------------------------------------------


class TestRunMining:
    """POST /api/mining/run 端点测试。"""

    def test_run_gp_success(self, app_client) -> None:
        """正常提交GP任务，返回202+task_id。"""
        app, client = app_client
        svc = _mock_svc()
        svc.start_mining_task.return_value = {
            "task_id": "abc-123",
            "run_id": "gp_2026w14_abc123",
            "status": "submitted",
        }
        _inject(app, svc)

        resp = client.post("/api/mining/run", json={
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

    def test_run_invalid_engine_returns_422(self, app_client) -> None:
        """无效engine值（非gp/bruteforce/llm）返回422。"""
        app, client = app_client
        svc = _mock_svc()
        _inject(app, svc)

        resp = client.post("/api/mining/run", json={
            "engine": "unknown_engine",
            "generations": 10,
        })

        assert resp.status_code == 422  # pydantic pattern validation

    def test_run_conflict_409(self, app_client) -> None:
        """同引擎任务已在运行时返回409。"""
        app, client = app_client
        svc = _mock_svc()
        svc.start_mining_task.side_effect = RuntimeError("gp引擎已有任务在运行")
        _inject(app, svc)

        resp = client.post("/api/mining/run", json={"engine": "gp"})

        assert resp.status_code == 409
        assert "已有任务在运行" in resp.json()["detail"]

    def test_run_bad_params_400(self, app_client) -> None:
        """ValueError时返回400。"""
        app, client = app_client
        svc = _mock_svc()
        svc.start_mining_task.side_effect = ValueError("config非法")
        _inject(app, svc)

        resp = client.post("/api/mining/run", json={"engine": "gp"})

        assert resp.status_code == 400

    def test_run_bruteforce_engine(self, app_client) -> None:
        """bruteforce引擎可正常提交。"""
        app, client = app_client
        svc = _mock_svc()
        svc.start_mining_task.return_value = {
            "task_id": "bf-456",
            "run_id": "bruteforce_2026w14_bf456",
            "status": "submitted",
        }
        _inject(app, svc)

        resp = client.post("/api/mining/run", json={"engine": "bruteforce"})

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

    def test_list_default(self, app_client) -> None:
        """默认列表返回200+数组。"""
        app, client = app_client
        svc = _mock_svc()
        svc.list_tasks.return_value = self._SAMPLE_TASKS
        _inject(app, svc)

        resp = client.get("/api/mining/tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["engine"] == "gp"

    def test_list_with_engine_filter(self, app_client) -> None:
        """engine筛选参数正确传递给 MiningService。"""
        app, client = app_client
        svc = _mock_svc()
        svc.list_tasks.return_value = []
        _inject(app, svc)

        client.get("/api/mining/tasks?engine=gp&status=completed")

        svc.list_tasks.assert_called_once_with(engine="gp", status="completed", limit=20)

    def test_list_with_limit(self, app_client) -> None:
        """limit参数正确传递。"""
        app, client = app_client
        svc = _mock_svc()
        svc.list_tasks.return_value = []
        _inject(app, svc)

        client.get("/api/mining/tasks?limit=5")

        svc.list_tasks.assert_called_once_with(engine=None, status=None, limit=5)

    def test_list_empty_result(self, app_client) -> None:
        """空列表返回200+[]。"""
        app, client = app_client
        svc = _mock_svc()
        svc.list_tasks.return_value = []
        _inject(app, svc)

        resp = client.get("/api/mining/tasks")

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

    def test_get_detail_success(self, app_client) -> None:
        """正常获取任务详情，返回200+完整字典。"""
        app, client = app_client
        svc = _mock_svc()
        svc.get_task_detail.return_value = self._SAMPLE_DETAIL
        _inject(app, svc)

        resp = client.get("/api/mining/tasks/abc-123")

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "abc-123"
        assert data["status"] == "completed"
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["factor_expr"] == "ts_mean(cs_rank(close), 20)"

    def test_get_detail_404(self, app_client) -> None:
        """task_id 不存在时返回404。"""
        app, client = app_client
        svc = _mock_svc()
        svc.get_task_detail.return_value = None
        _inject(app, svc)

        resp = client.get("/api/mining/tasks/nonexistent-id")

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_get_detail_passes_task_id(self, app_client) -> None:
        """task_id 正确传递给 MiningService。"""
        app, client = app_client
        svc = _mock_svc()
        svc.get_task_detail.return_value = self._SAMPLE_DETAIL
        _inject(app, svc)

        client.get("/api/mining/tasks/my-task-id")

        svc.get_task_detail.assert_called_once_with("my-task-id")


# ---------------------------------------------------------------------------
# POST /api/mining/tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelTask:
    """POST /api/mining/tasks/{task_id}/cancel 端点测试。"""

    def test_cancel_success(self, app_client) -> None:
        """正常取消运行中任务，返回200。"""
        app, client = app_client
        svc = _mock_svc()
        svc.cancel_task.return_value = {
            "task_id": "abc-123",
            "run_id": "gp_2026w14_abc",
            "cancelled": True,
            "message": "取消信号已发送",
        }
        _inject(app, svc)

        resp = client.post("/api/mining/tasks/abc-123/cancel")

        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True

    def test_cancel_404(self, app_client) -> None:
        """task_id 不存在时返回404。"""
        app, client = app_client
        svc = _mock_svc()
        svc.cancel_task.side_effect = LookupError("任务不存在: xyz")
        _inject(app, svc)

        resp = client.post("/api/mining/tasks/xyz/cancel")

        assert resp.status_code == 404

    def test_cancel_already_completed_400(self, app_client) -> None:
        """已完成的任务取消返回400。"""
        app, client = app_client
        svc = _mock_svc()
        svc.cancel_task.side_effect = ValueError("任务已结束 (status=completed)，无法取消。")
        _inject(app, svc)

        resp = client.post("/api/mining/tasks/done-task/cancel")

        assert resp.status_code == 400
        assert "无法取消" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/mining/evaluate
# ---------------------------------------------------------------------------


class TestEvaluateFactor:
    """POST /api/mining/evaluate 端点测试。"""

    def test_evaluate_success(self, app_client) -> None:
        """正常评估因子，返回200+Gate结果。"""
        app, client = app_client
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
        _inject(app, svc)

        resp = client.post("/api/mining/evaluate", json={
            "factor_expr": "ts_mean(cs_rank(close), 20)",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_passed"] is True
        assert data["ic_mean"] == pytest.approx(0.0312, abs=1e-6)
        assert data["gate_result"]["G1"] == "PASS"

    def test_evaluate_quick_only(self, app_client) -> None:
        """run_quick_only=True 正确传递给 MiningService。"""
        app, client = app_client
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
        _inject(app, svc)

        client.post("/api/mining/evaluate", json={
            "factor_expr": "ts_mean(close, 20)",
            "run_quick_only": True,
        })

        svc.evaluate_factor_gate.assert_called_once_with(
            factor_expr="ts_mean(close, 20)",
            factor_name=None,
            quick_only=True,
        )

    def test_evaluate_with_custom_name(self, app_client) -> None:
        """自定义factor_name传递给MiningService。"""
        app, client = app_client
        svc = _mock_svc()
        svc.evaluate_factor_gate.return_value = {
            "factor_name": "my_custom_factor",
            "factor_expr": "ts_mean(close, 20)",
            "gate_result": {"G1": "PASS"},
            "overall_passed": True,
            "ic_mean": 0.03,
            "t_stat": 2.8,
            "elapsed_seconds": 3.0,
            "quick_only": False,
        }
        _inject(app, svc)

        resp = client.post("/api/mining/evaluate", json={
            "factor_expr": "ts_mean(close, 20)",
            "factor_name": "my_custom_factor",
        })

        assert resp.status_code == 200
        svc.evaluate_factor_gate.assert_called_once_with(
            factor_expr="ts_mean(close, 20)",
            factor_name="my_custom_factor",
            quick_only=False,
        )

    def test_evaluate_invalid_dsl_400(self, app_client) -> None:
        """非法DSL表达式返回400。"""
        app, client = app_client
        svc = _mock_svc()
        svc.evaluate_factor_gate.side_effect = ValueError("DSL 表达式非法: 未知算子 unknown_op")
        _inject(app, svc)

        resp = client.post("/api/mining/evaluate", json={
            "factor_expr": "unknown_op(close, 5)",
        })

        assert resp.status_code == 400
        assert "DSL" in resp.json()["detail"] or "非法" in resp.json()["detail"]

    def test_evaluate_db_unavailable_503(self, app_client) -> None:
        """DB不可用时返回503。"""
        app, client = app_client
        svc = _mock_svc()
        svc.evaluate_factor_gate.side_effect = ConnectionError("行情数据加载失败")
        _inject(app, svc)

        resp = client.post("/api/mining/evaluate", json={
            "factor_expr": "ts_mean(close, 20)",
        })

        assert resp.status_code == 503
