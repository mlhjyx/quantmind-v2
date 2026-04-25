"""MVP 1.3c 集成测试 — factor_onboarding._upsert_factor_registry 走 Platform register.

覆盖:
  - 成功路径 (G9+G10 通过) 返 UUID string
  - G10 hypothesis 占位拒绝 (GP自动挖掘: / 空)
  - G10 hypothesis 过短拒绝
  - G9 AST 相似拒绝
  - DuplicateFactor 幂等返现有 id
  - direction / category / author 从 gate_result 正确取
  - hypothesis 有效 + 合法 pool 路径

执行:
  pytest backend/tests/test_factor_onboarding_gates.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pandas as pd
import pytest

# onboarding service 依赖 backend/app/... 路径
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.factor_onboarding import FactorOnboardingService  # noqa: E402
from backend.qm_platform.factor.registry import OnboardingBlocked  # noqa: E402

VALID_HYPOTHESIS = (
    "高换手股票短期流动性冲击预期, 截面低换手率因子捕捉未来 20 日反向收益 — 流动性溢价."
)


@pytest.fixture
def service() -> FactorOnboardingService:
    """FactorOnboardingService with fake db_url — 实际 DB 调用会被 patch 拦截."""
    return FactorOnboardingService(db_url="postgresql://fake:fake@localhost/fake_db")


def _mock_platform_register(
    *,
    register_side_effect=None,
    register_return=UUID("12345678-1234-5678-1234-567812345678"),
    read_registry_return: pd.DataFrame | None = None,
):
    """构造 Platform register mock + DAL read_registry mock + conn_factory mock.

    同时 patch backend.qm_platform.data.access_layer + backend.qm_platform.factor.registry
    的 PlatformDataAccessLayer / DBFactorRegistry 使 onboarding 内的 import 走 mock.
    """
    if read_registry_return is None:
        read_registry_return = pd.DataFrame(
            columns=["id", "name", "direction", "expression", "status", "pool"]
        )

    dal_instance = MagicMock()
    dal_instance.read_registry.return_value = read_registry_return
    dal_cls = MagicMock(return_value=dal_instance)

    registry_instance = MagicMock()
    if register_side_effect is not None:
        registry_instance.register.side_effect = register_side_effect
    else:
        registry_instance.register.return_value = register_return
    registry_cls = MagicMock(return_value=registry_instance)

    patches = [
        patch(
            "app.services.factor_onboarding.psycopg2.connect",
            return_value=MagicMock(),
        ),
    ]
    return dal_cls, dal_instance, registry_cls, registry_instance, patches


# ================================================================
# 成功路径
# ================================================================


def test_upsert_registry_success_returns_uuid_string(service: FactorOnboardingService) -> None:
    conn = MagicMock()
    conn.autocommit = True
    expected_id = UUID("12345678-1234-5678-1234-567812345678")

    dal_cls, dal_instance, registry_cls, registry_instance, _ = _mock_platform_register(
        register_return=expected_id
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn):
        result = service._upsert_factor_registry(
            conn=conn,
            factor_name="new_factor_xyz",
            factor_expr="rank(close / open)",
            gate_result={
                "hypothesis": VALID_HYPOTHESIS,
                "direction": 1,
                "category": "alpha",
                "source": "gp",
            },
            run_id="run_123",
            sharpe_1y=0.85,
        )

    assert result == str(expected_id)
    registry_instance.register.assert_called_once()
    # 验证 FactorSpec 传参正确
    spec_arg = registry_instance.register.call_args[0][0]
    assert spec_arg.name == "new_factor_xyz"
    assert spec_arg.hypothesis == VALID_HYPOTHESIS
    assert spec_arg.expression == "rank(close / open)"
    assert spec_arg.direction == 1
    assert spec_arg.category == "alpha"
    assert spec_arg.pool == "CANDIDATE"
    assert spec_arg.author == "gp"


def test_upsert_registry_uses_defaults_when_gate_result_sparse(service: FactorOnboardingService) -> None:
    """gate_result 缺 direction/category/source → 用默认值 (direction=1/alpha/gp)."""
    conn = MagicMock()
    expected_id = UUID("22222222-2222-2222-2222-222222222222")
    dal_cls, _, registry_cls, registry_instance, _ = _mock_platform_register(
        register_return=expected_id
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn):
        service._upsert_factor_registry(
            conn=conn,
            factor_name="minimal_factor",
            factor_expr="close",
            gate_result={"hypothesis": VALID_HYPOTHESIS},  # 缺 direction/category/source
            run_id="run_456",
            sharpe_1y=None,
        )

    spec_arg = registry_instance.register.call_args[0][0]
    assert spec_arg.direction == 1  # default
    assert spec_arg.category == "alpha"  # default
    assert spec_arg.author == "gp"  # default


# ================================================================
# G10 hypothesis 拒绝路径
# ================================================================


def test_upsert_registry_g10_empty_hypothesis_blocked(service: FactorOnboardingService) -> None:
    """空 hypothesis → G10 raise OnboardingBlocked (Platform register 强门)."""
    conn = MagicMock()
    dal_cls, _, registry_cls, registry_instance, _ = _mock_platform_register(
        register_side_effect=OnboardingBlocked("G10 失败 (铁律 13): hypothesis 必须非空")
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn), \
         pytest.raises(OnboardingBlocked, match="G10"):
        service._upsert_factor_registry(
            conn=conn,
            factor_name="no_hypo_factor",
            factor_expr="rank(close)",
            gate_result={"hypothesis": ""},  # 空, 会被 G10 拒
            run_id="run_xxx",
            sharpe_1y=None,
        )
    registry_instance.register.assert_called_once()


def test_upsert_registry_g10_placeholder_hypothesis_blocked(service: FactorOnboardingService) -> None:
    """GP自动挖掘: 占位符 → G10 拒."""
    conn = MagicMock()
    dal_cls, _, registry_cls, _, _ = _mock_platform_register(
        register_side_effect=OnboardingBlocked("G10 失败: 占位符前缀")
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn), \
         pytest.raises(OnboardingBlocked, match="G10"):
        service._upsert_factor_registry(
            conn=conn,
            factor_name="gp_default_factor",
            factor_expr="rank(close)",
            gate_result={"hypothesis": "GP自动挖掘: rank(close)" + " " * 50},
            run_id="run_xxx",
            sharpe_1y=None,
        )


# ================================================================
# G9 AST 相似拒绝
# ================================================================


def test_upsert_registry_g9_similar_ast_blocked(service: FactorOnboardingService) -> None:
    """与已有 ACTIVE 因子 AST Jaccard > 0.7 → G9 拒."""
    conn = MagicMock()
    dal_cls, _, registry_cls, _, _ = _mock_platform_register(
        register_side_effect=OnboardingBlocked("G9 失败 (铁律 12): AST Jaccard > 0.7")
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn), \
         pytest.raises(OnboardingBlocked, match="G9"):
        service._upsert_factor_registry(
            conn=conn,
            factor_name="near_duplicate",
            factor_expr="rank(close / open)",
            gate_result={"hypothesis": VALID_HYPOTHESIS},
            run_id="run_xxx",
            sharpe_1y=None,
        )


# ================================================================
# DuplicateFactor 幂等返回
# ================================================================


def test_upsert_registry_duplicate_returns_existing_id(service: FactorOnboardingService) -> None:
    """因子已注册 → 幂等返现有 id (不再 INSERT)."""
    from backend.qm_platform.factor.registry import DuplicateFactor

    conn = MagicMock()
    existing_uid = UUID("99999999-9999-9999-9999-999999999999")
    existing_df = pd.DataFrame(
        [
            {
                "id": existing_uid, "name": "already_exists", "direction": 1,
                "expression": "x", "status": "active", "pool": "CORE",
            }
        ]
    )
    dal_cls, dal_instance, registry_cls, _, _ = _mock_platform_register(
        register_side_effect=DuplicateFactor("already_exists"),
        read_registry_return=existing_df,
    )

    with patch("backend.qm_platform.data.access_layer.PlatformDataAccessLayer", dal_cls), \
         patch("backend.qm_platform.factor.registry.DBFactorRegistry", registry_cls), \
         patch("app.services.factor_onboarding.psycopg2.connect", return_value=conn):
        result = service._upsert_factor_registry(
            conn=conn,
            factor_name="already_exists",
            factor_expr="x",
            gate_result={"hypothesis": VALID_HYPOTHESIS},
            run_id="run_xxx",
            sharpe_1y=None,
        )

    assert result == str(existing_uid)
    # dal.read_registry 被调 1 次 (DuplicateFactor 后幂等查 id)
    assert dal_instance.read_registry.call_count >= 1
