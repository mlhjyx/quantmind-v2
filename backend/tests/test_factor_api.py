"""单元测试 — Factor API Router (Sprint 1.16)

覆盖:
- GET /api/factors            — 列表端点
- GET /api/factors/health     — 健康度端点
- GET /api/factors/correlation — 相关性矩阵端点
- GET /api/factors/{name}     — 单因子详情端点
- GET /api/factors/{name}/report — 评估报告端点
- 404 处理
- _calc_t_stat 辅助函数

设计文档对照: docs/DEV_BACKEND.md / docs/DEV_FACTOR_MINING.md
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest

try:
    from fastapi.testclient import TestClient

    from app.api.factors import _calc_t_stat, _get_factor_service, router

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed in this environment",
)


# ---------------------------------------------------------------------------
# 辅助: mock FactorService
# ---------------------------------------------------------------------------

_MOCK_FACTOR_LIST = [
    {
        "factor_name": "turnover_mean_20",
        "category": "liquidity",
        "direction": -1,
        "status": "active",
        "description": "换手率均值",
        "created_at": date(2024, 1, 1),
    },
    {
        "factor_name": "volatility_20",
        "category": "risk",
        "direction": -1,
        "status": "active",
        "description": "波动率",
        "created_at": date(2024, 1, 1),
    },
]

_MOCK_STATS = {
    "ic_mean": 0.032,
    "ic_std": 0.045,
    "ic_ir": 0.711,
    "data_points": 24,
}

_MOCK_IC_DF = pd.DataFrame(
    {
        "trade_date": pd.date_range("2024-01-31", periods=6, freq="ME").date,
        "ic_value": [0.03, 0.04, 0.02, 0.035, 0.028, 0.041],
        "factor_name": ["turnover_mean_20"] * 6,
    }
)


def _build_mock_service(**overrides: Any) -> AsyncMock:
    """构建带默认返回值的 FactorService mock。"""
    svc = AsyncMock()
    svc.get_factor_list = AsyncMock(return_value=overrides.get("factor_list", _MOCK_FACTOR_LIST))
    svc.get_factor_stats = AsyncMock(return_value=overrides.get("stats", _MOCK_STATS))
    svc.get_factor_ic = AsyncMock(return_value=overrides.get("ic_df", _MOCK_IC_DF))
    return svc


def _inject(app: Any, svc: AsyncMock) -> None:
    """通过 dependency_overrides 注入 mock FactorService。"""
    app.dependency_overrides[_get_factor_service] = lambda: svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_client():
    """返回 (app, client)，测试结束后清理 dependency_overrides。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    yield app, client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/factors — 列表端点
# ---------------------------------------------------------------------------


class TestListFactors:
    """GET /api/factors 测试。"""

    def test_returns_200_with_list(self, app_client) -> None:
        """正常请求返回200和因子列表。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_contains_expected_fields(self, app_client) -> None:
        """每个因子项包含必要字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors")
        data = resp.json()
        if data:
            item = data[0]
            assert "name" in item
            assert "category" in item
            assert "status" in item
            assert "ic_mean" in item
            assert "ic_ir" in item

    def test_filter_by_status(self, app_client) -> None:
        """status参数应传递给 FactorService。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[_MOCK_FACTOR_LIST[0]])
        _inject(app, svc)
        resp = client.get("/api/factors?status=active")
        assert resp.status_code == 200
        svc.get_factor_list.assert_called_once_with(status="active")

    def test_filter_by_category(self, app_client) -> None:
        """category参数应过滤结果。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors?category=liquidity")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["category"] == "liquidity" for item in data)


# ---------------------------------------------------------------------------
# GET /api/factors/health — 健康度端点
# ---------------------------------------------------------------------------


class TestFactorsHealth:
    """GET /api/factors/health 测试。"""

    def test_returns_200(self, app_client) -> None:
        """健康度端点返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/health")
        assert resp.status_code == 200

    def test_response_structure(self, app_client) -> None:
        """响应包含 as_of/active_count/factors 字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/health")
        data = resp.json()
        assert "as_of" in data
        assert "active_count" in data
        assert "factors" in data
        assert isinstance(data["factors"], list)

    def test_active_count_matches_active_factors(self, app_client) -> None:
        """active_count 应等于 active 因子数量。"""
        app, client = app_client
        svc = _build_mock_service()
        svc.get_factor_list = AsyncMock(return_value=_MOCK_FACTOR_LIST)
        _inject(app, svc)
        resp = client.get("/api/factors/health")
        data = resp.json()
        assert data["active_count"] == len(_MOCK_FACTOR_LIST)

    def test_factor_health_has_decay_warning_field(self, app_client) -> None:
        """每个因子健康记录包含 decay_warning 字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/health")
        data = resp.json()
        for item in data.get("factors", []):
            assert "decay_warning" in item
            assert isinstance(item["decay_warning"], bool)


# ---------------------------------------------------------------------------
# GET /api/factors/correlation — 相关性矩阵端点
# ---------------------------------------------------------------------------


class TestFactorCorrelation:
    """GET /api/factors/correlation 测试。"""

    def test_returns_200(self, app_client) -> None:
        """相关性矩阵端点返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/correlation")
        assert resp.status_code == 200

    def test_response_structure(self, app_client) -> None:
        """响应包含 factor_names/matrix/period 字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/correlation")
        data = resp.json()
        assert "factor_names" in data
        assert "matrix" in data
        assert "period" in data

    def test_matrix_is_square(self, app_client) -> None:
        """相关性矩阵应是方阵。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/correlation")
        data = resp.json()
        names = data["factor_names"]
        matrix = data["matrix"]
        if names:
            assert len(matrix) == len(names)
            assert all(len(row) == len(names) for row in matrix)

    def test_diagonal_is_one(self, app_client) -> None:
        """相关性矩阵对角线应为1.0。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/correlation")
        data = resp.json()
        matrix = data["matrix"]
        for i, row in enumerate(matrix):
            assert abs(row[i] - 1.0) < 1e-9, f"对角线[{i},{i}]={row[i]}，应为1.0"

    def test_empty_factors_returns_empty_matrix(self, app_client) -> None:
        """无因子时返回空矩阵。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[])
        _inject(app, svc)
        resp = client.get("/api/factors/correlation")
        data = resp.json()
        assert data["factor_names"] == []
        assert data["matrix"] == []


# ---------------------------------------------------------------------------
# GET /api/factors/{name} — 单因子详情
# ---------------------------------------------------------------------------


class TestGetFactorDetail:
    """GET /api/factors/{name} 测试。"""

    def test_returns_200_for_existing_factor(self, app_client) -> None:
        """存在的因子返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20")
        assert resp.status_code == 200

    def test_returns_404_for_missing_factor(self, app_client) -> None:
        """不存在的因子返回404。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[])
        _inject(app, svc)
        resp = client.get("/api/factors/nonexistent_factor")
        assert resp.status_code == 404

    def test_response_has_ic_series(self, app_client) -> None:
        """响应包含ic_series列表。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20")
        data = resp.json()
        assert "ic_series" in data
        assert isinstance(data["ic_series"], list)

    def test_response_has_stats(self, app_client) -> None:
        """响应包含stats字段（ic_mean/ic_ir/t_stat）。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20")
        data = resp.json()
        assert "stats" in data
        stats = data["stats"]
        assert "ic_mean" in stats
        assert "ic_ir" in stats
        assert "t_stat" in stats

    def test_ic_series_dates_are_strings(self, app_client) -> None:
        """ic_series中每项的trade_date应是字符串（JSON可序列化）。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20")
        data = resp.json()
        for item in data.get("ic_series", []):
            assert isinstance(item["trade_date"], str)


# ---------------------------------------------------------------------------
# GET /api/factors/{name}/report — 评估报告
# ---------------------------------------------------------------------------


class TestGetFactorReport:
    """GET /api/factors/{name}/report 测试。"""

    def test_returns_200(self, app_client) -> None:
        """评估报告端点返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20/report")
        assert resp.status_code == 200

    def test_returns_404_for_missing_factor(self, app_client) -> None:
        """不存在的因子返回404。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[])
        _inject(app, svc)
        resp = client.get("/api/factors/bad_factor/report")
        assert resp.status_code == 404

    def test_report_has_six_tab_sections(self, app_client) -> None:
        """报告包含6 Tab所需的所有字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/turnover_mean_20/report")
        data = resp.json()
        assert "overview" in data
        assert "ic_analysis" in data
        assert "quintile_returns" in data
        assert "gate_report" in data
        assert "ic_decay" in data
        assert "backtest_summary" in data


# ---------------------------------------------------------------------------
# _calc_t_stat 辅助函数
# ---------------------------------------------------------------------------


class TestCalcTStat:
    """_calc_t_stat 辅助函数单元测试。"""

    def test_normal_case(self) -> None:
        """正常输入应返回正确t统计量。"""
        stats = {"ic_mean": 0.03, "ic_std": 0.045, "data_points": 24}
        t = _calc_t_stat(stats)
        # t = 0.03 / (0.045 / sqrt(24)) ≈ 0.03 / 0.00919 ≈ 3.27
        assert t is not None
        assert abs(t - 3.27) < 0.1

    def test_none_ic_mean_returns_none(self) -> None:
        """ic_mean为None时返回None。"""
        stats = {"ic_mean": None, "ic_std": 0.045, "data_points": 24}
        assert _calc_t_stat(stats) is None

    def test_zero_ic_std_returns_none(self) -> None:
        """ic_std为0时返回None（防止除零）。"""
        stats = {"ic_mean": 0.03, "ic_std": 0.0, "data_points": 24}
        assert _calc_t_stat(stats) is None

    def test_insufficient_data_returns_none(self) -> None:
        """data_points<2时返回None。"""
        stats = {"ic_mean": 0.03, "ic_std": 0.045, "data_points": 1}
        assert _calc_t_stat(stats) is None

    def test_positive_ic_positive_t(self) -> None:
        """正IC应产生正t值。"""
        stats = {"ic_mean": 0.05, "ic_std": 0.04, "data_points": 36}
        t = _calc_t_stat(stats)
        assert t is not None
        assert t > 0

    def test_negative_ic_negative_t(self) -> None:
        """负IC应产生负t值。"""
        stats = {"ic_mean": -0.05, "ic_std": 0.04, "data_points": 36}
        t = _calc_t_stat(stats)
        assert t is not None
        assert t < 0


# ---------------------------------------------------------------------------
# GET /api/factors/summary — FactorSummary[]数组端点（供StrategyWorkspace使用）
# ---------------------------------------------------------------------------


class TestGetFactorsSummary:
    """GET /api/factors/summary 测试（FactorSummary[]格式）。"""

    def test_returns_200(self, app_client) -> None:
        """正常请求返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        assert resp.status_code == 200

    def test_returns_list(self, app_client) -> None:
        """响应是数组格式（FactorSummary[]）。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        assert isinstance(data, list), f"期望list，得到: {type(data)}"

    def test_items_have_factor_summary_fields(self, app_client) -> None:
        """每项包含前端 FactorSummary interface 必要字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        for item in data:
            for field in ("id", "name", "category", "ic", "ir", "direction",
                          "recommended_freq", "t_stat", "fdr_t_stat", "status"):
                assert field in item, f"缺少字段: {field}"

    def test_status_mapped_to_frontend_enum(self, app_client) -> None:
        """status 值映射到前端枚举: active/new/degraded/retired。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        valid_statuses = {"active", "new", "degraded", "retired"}
        for item in data:
            assert item["status"] in valid_statuses, f"无效status: {item['status']}"

    def test_id_equals_name(self, app_client) -> None:
        """id 字段与 name 字段相同（factor_name作为id）。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        for item in data:
            assert item["id"] == item["name"]

    def test_count_matches_mock_factor_list(self, app_client) -> None:
        """返回条数与 factor_list 条数一致。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        assert len(data) == len(_MOCK_FACTOR_LIST)

    def test_empty_factor_list_returns_empty_array(self, app_client) -> None:
        """因子库为空时返回空数组。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[])
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_ic_ir_are_numeric(self, app_client) -> None:
        """ic/ir/t_stat 字段为数值类型。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/summary")
        data = resp.json()
        for item in data:
            assert isinstance(item["ic"], (int, float))
            assert isinstance(item["ir"], (int, float))
            assert isinstance(item["t_stat"], (int, float))


# ---------------------------------------------------------------------------
# GET /api/factors/stats — 因子库概览统计端点（供Dashboard使用）
# ---------------------------------------------------------------------------


class TestGetFactorsStats:
    """GET /api/factors/stats 测试（{total,active,...}对象格式）。"""

    def test_returns_200(self, app_client) -> None:
        """正常请求返回200。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        assert resp.status_code == 200

    def test_response_contains_count_fields(self, app_client) -> None:
        """响应包含 total/active/candidate/warning/critical/retired 字段。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        for field in ("total", "active", "candidate", "warning", "critical", "retired"):
            assert field in data, f"缺少字段: {field}"

    def test_response_contains_top_factors(self, app_client) -> None:
        """响应包含 top_factors 列表。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        assert "top_factors" in data
        assert isinstance(data["top_factors"], list)

    def test_active_count_matches_mock(self, app_client) -> None:
        """active 计数与 mock 数据中 active 状态因子数一致。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        assert data["active"] == 2

    def test_total_equals_sum_of_statuses(self, app_client) -> None:
        """total 等于各状态之和。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        computed_total = (
            data["active"] + data["candidate"] + data["warning"]
            + data["critical"] + data["retired"]
        )
        assert data["total"] == computed_total

    def test_top_factors_have_required_fields(self, app_client) -> None:
        """top_factors 每项包含 name/ic_mean/ic_ir/direction/status/trend。"""
        app, client = app_client
        svc = _build_mock_service()
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        for item in data["top_factors"]:
            for field in ("name", "ic_mean", "ic_ir", "direction", "status", "trend"):
                assert field in item, f"top_factors 缺少字段: {field}"

    def test_top_factors_max_10(self, app_client) -> None:
        """top_factors 最多返回10条。"""
        app, client = app_client
        big_list = [
            {
                "factor_name": f"factor_{i}",
                "category": "liquidity",
                "direction": 1,
                "status": "active",
                "description": f"factor {i}",
                "created_at": None,
            }
            for i in range(12)
        ]
        svc = _build_mock_service(factor_list=big_list)
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        data = resp.json()
        assert len(data["top_factors"]) <= 10

    def test_empty_factor_list_returns_zeros(self, app_client) -> None:
        """因子库为空时各计数均为0，top_factors为空列表。"""
        app, client = app_client
        svc = _build_mock_service(factor_list=[])
        _inject(app, svc)
        resp = client.get("/api/factors/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["top_factors"] == []
