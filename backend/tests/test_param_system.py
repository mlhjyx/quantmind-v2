"""参数配置系统测试 — param_defaults / param_service / params API 全覆盖。

测试层:
  1. Defaults层: PARAM_DEFINITIONS完整性、结构校验、关键参数默认值
  2. Validation层: 合法值/超范围/类型错误/枚举约束
  3. API层: GET列表/GET单个/PUT更新成功/PUT校验失败

Mock策略: ParamRepository全部mock，不依赖DB。
API测试通过FastAPI dependency_overrides注入mock session。
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.param_defaults import (
    PARAM_DEFINITIONS,
    ParamDef,
    ParamModule,
    ParamType,
    get_all_param_defs,
    get_modules,
    get_param_def,
)
from app.services.param_service import ParamService, ParamValidationError


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════


def _make_mock_repo(
    db_params: list[dict[str, Any]] | None = None,
    single_param: dict[str, Any] | None = None,
) -> MagicMock:
    """创建ParamRepository mock。"""
    repo = MagicMock()
    repo.get_all_params = AsyncMock(return_value=db_params or [])
    repo.get_param = AsyncMock(return_value=single_param)
    repo.upsert_param = AsyncMock()
    repo.update_param_value = AsyncMock(return_value=True)
    repo.insert_change_log = AsyncMock()
    repo.get_change_log = AsyncMock(return_value=[])
    return repo


def _make_param_service_with_mock(
    db_params: list[dict[str, Any]] | None = None,
    single_param: dict[str, Any] | None = None,
) -> ParamService:
    """创建带mock repo的ParamService。"""
    svc = ParamService.__new__(ParamService)
    svc.repo = _make_mock_repo(db_params=db_params, single_param=single_param)
    return svc


# ═══════════════════════════════════════════════════
# 1. Defaults层测试
# ═══════════════════════════════════════════════════


class TestParamDefaults:
    """param_defaults.py 参数定义完整性测试。"""

    def test_param_count_at_least_50(self) -> None:
        """PARAM_DEFINITIONS应包含>=50个参数定义。"""
        assert len(PARAM_DEFINITIONS) >= 50, (
            f"参数定义数量不足: 期望>=50, 实际={len(PARAM_DEFINITIONS)}"
        )

    def test_every_param_has_required_fields(self) -> None:
        """每个参数必须有key/default_value/param_type/description/module五个核心字段。"""
        for key, param_def in PARAM_DEFINITIONS.items():
            assert isinstance(param_def, ParamDef), f"{key} 类型错误"
            assert param_def.key == key, f"{key} key不匹配: {param_def.key}"
            assert param_def.default_value is not None or param_def.param_type == ParamType.STR, (
                f"{key} 缺少default_value"
            )
            assert isinstance(param_def.param_type, ParamType), (
                f"{key} param_type不是ParamType枚举"
            )
            assert isinstance(param_def.module, ParamModule), (
                f"{key} module不是ParamModule枚举"
            )
            assert param_def.description and len(param_def.description) > 0, (
                f"{key} 缺少description"
            )

    def test_critical_param_defaults(self) -> None:
        """关键参数存在且默认值正确。

        验证CLAUDE.md中明确提及的参数:
        - signal.top_n = 30 (CLAUDE.md: 等权Top-N)
        - risk.l2_portfolio_daily_loss = -0.03
        - signal.turnover_cap = 0.5 (CLAUDE.md: 换手率上限50%)
        - backtest.lot_size = 100 (CLAUDE.md: A股100股/手)
        - execution.mode = "paper" (Phase 0)
        """
        critical_params = {
            "signal.top_n": 30,
            "risk.l2_portfolio_daily_loss": -0.03,
            "signal.turnover_cap": 0.5,
            "backtest.lot_size": 100,
            "execution.mode": "paper",
            "paper_trading.graduation_days": 60,
            "factor.neutralize_method": "market_industry",
        }
        for key, expected_value in critical_params.items():
            param_def = get_param_def(key)
            assert param_def is not None, f"关键参数 {key} 未定义"
            assert param_def.default_value == expected_value, (
                f"{key} 默认值错误: 期望={expected_value}, 实际={param_def.default_value}"
            )

    def test_get_modules_returns_all(self) -> None:
        """get_modules()应返回所有已注册模块。"""
        modules = get_modules()
        expected = {"factor", "signal", "backtest", "risk", "paper_trading",
                    "universe", "execution", "gp_engine", "scheduler", "data"}
        # 允许有更多模块但必须包含这些核心模块
        for mod in expected:
            assert mod in modules, f"模块 {mod} 缺失"

    def test_get_all_param_defs_filter_by_module(self) -> None:
        """按模块过滤返回正确子集。"""
        signal_params = get_all_param_defs(module="signal")
        assert len(signal_params) > 0, "signal模块应有参数"
        for key, param_def in signal_params.items():
            assert param_def.module == ParamModule.SIGNAL, (
                f"{key} 不属于signal模块: {param_def.module}"
            )


# ═══════════════════════════════════════════════════
# 2. Validation层测试
# ═══════════════════════════════════════════════════


class TestParamValidation:
    """ParamService.validate_param 校验逻辑测试。"""

    def _make_svc(self) -> ParamService:
        return _make_param_service_with_mock()

    def test_valid_value_passes(self) -> None:
        """合法值通过校验: top_n=30在[5,100]范围内。"""
        svc = self._make_svc()
        # 不应抛出异常
        svc.validate_param("signal.top_n", 30)

    def test_valid_float_value_passes(self) -> None:
        """合法float值通过校验。"""
        svc = self._make_svc()
        svc.validate_param("factor.ic_threshold", 0.05)

    def test_out_of_range_rejected(self) -> None:
        """超范围值被拒绝: top_n=200 > max=100。"""
        svc = self._make_svc()
        with pytest.raises(ParamValidationError, match="超过最大值"):
            svc.validate_param("signal.top_n", 200)

    def test_below_min_rejected(self) -> None:
        """低于最小值被拒绝: top_n=1 < min=5。"""
        svc = self._make_svc()
        with pytest.raises(ParamValidationError, match="低于最小值"):
            svc.validate_param("signal.top_n", 1)

    def test_type_error_rejected(self) -> None:
        """类型错误被拒绝: top_n="abc"不是int。"""
        svc = self._make_svc()
        with pytest.raises(ParamValidationError, match="类型应为int"):
            svc.validate_param("signal.top_n", "abc")

    def test_bool_not_accepted_as_int(self) -> None:
        """bool不能作为int传入（Python中bool是int子类，需特殊处理）。"""
        svc = self._make_svc()
        with pytest.raises(ParamValidationError, match="类型应为int"):
            svc.validate_param("signal.top_n", True)

    def test_enum_invalid_rejected(self) -> None:
        """枚举约束: weight_method="invalid"被拒绝。"""
        svc = self._make_svc()
        with pytest.raises(ParamValidationError, match="不在可选列表"):
            svc.validate_param("signal.weight_method", "invalid")

    def test_enum_valid_passes(self) -> None:
        """枚举合法值通过: weight_method="ic_weighted"。"""
        svc = self._make_svc()
        svc.validate_param("signal.weight_method", "ic_weighted")

    def test_float_accepts_int(self) -> None:
        """float类型参数接受int值（Python int是float子集）。"""
        svc = self._make_svc()
        # backtest.initial_capital是float类型, 传入int不应报错
        svc.validate_param("backtest.initial_capital", 500000)


# ═══════════════════════════════════════════════════
# 3. API层测试
# ═══════════════════════════════════════════════════


def _override_param_service(svc: ParamService):
    """创建dependency_overrides用的工厂。"""
    from app.api.params import _get_param_service

    def _override():
        return svc

    return _get_param_service, _override


class TestParamAPI:
    """params API路由测试（mock DB）。"""

    @pytest.mark.asyncio
    async def test_get_params_list(self) -> None:
        """GET /api/params 返回按模块分组的参数列表。"""
        svc = _make_param_service_with_mock()
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/params")
            assert resp.status_code == 200
            data = resp.json()
            assert "modules" in data, "响应缺少modules字段"
            assert "params" in data, "响应缺少params字段"
            assert isinstance(data["modules"], list)
            assert isinstance(data["params"], dict)
            # 至少有几个模块
            assert len(data["modules"]) >= 5
            # params按模块分组，每组是list
            for mod, params_list in data["params"].items():
                assert isinstance(params_list, list), f"{mod}的params不是list"
        finally:
            app.dependency_overrides.pop(dep_key, None)

    @pytest.mark.asyncio
    async def test_get_single_param(self) -> None:
        """GET /api/params/{key} 返回单个参数（默认定义fallback）。"""
        svc = _make_param_service_with_mock()
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/params/signal.top_n")
            assert resp.status_code == 200
            data = resp.json()
            assert data["param_name"] == "signal.top_n"
            assert data["param_value"] == 30
            assert data["module"] == "signal"
            assert "description" in data
        finally:
            app.dependency_overrides.pop(dep_key, None)

    @pytest.mark.asyncio
    async def test_get_nonexistent_param_404(self) -> None:
        """GET /api/params/{key} 不存在的参数返回404。"""
        svc = _make_param_service_with_mock()
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/params/nonexistent.param.key")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(dep_key, None)

    @pytest.mark.asyncio
    async def test_put_update_success(self) -> None:
        """PUT /api/params/{key} 更新成功返回200。"""
        svc = _make_param_service_with_mock()
        # update_param调用后get_param会被再次调用返回更新后值
        # mock repo.get_param返回None（首次），update走upsert路径
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/params/signal.top_n",
                    json={
                        "value": 25,
                        "reason": "测试调整Top-N到25",
                    },
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["param_name"] == "signal.top_n"
        finally:
            app.dependency_overrides.pop(dep_key, None)

    @pytest.mark.asyncio
    async def test_put_out_of_range_returns_400(self) -> None:
        """PUT /api/params/{key} 超范围值返回400。"""
        svc = _make_param_service_with_mock()
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/params/signal.top_n",
                    json={
                        "value": 200,
                        "reason": "尝试设置超范围值",
                    },
                )
            assert resp.status_code == 400
            assert "超过最大值" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(dep_key, None)

    @pytest.mark.asyncio
    async def test_put_missing_reason_returns_422(self) -> None:
        """PUT /api/params/{key} 缺少reason字段返回422。"""
        svc = _make_param_service_with_mock()
        dep_key, dep_override = _override_param_service(svc)
        app.dependency_overrides[dep_key] = dep_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.put(
                    "/api/params/signal.top_n",
                    json={"value": 25},
                )
            assert resp.status_code == 422, "缺少必填字段reason应返回422"
        finally:
            app.dependency_overrides.pop(dep_key, None)
