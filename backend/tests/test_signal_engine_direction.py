"""MVP 1.3b test — signal_engine._get_direction 3 层 fallback.

验证:
  - Layer 3 (hardcoded): 无 Platform 依赖或 FeatureFlag=off → FACTOR_DIRECTION.get
  - Layer 1 (DB): FeatureFlag=on + Registry 可用 → DB cache
  - 异常降级: Layer 1 exception → Layer 3 hardcoded (铁律 33 禁 silent)
  - init_platform_dependencies 幂等 / 可重置
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.engines.signal_engine import (
    FACTOR_DIRECTION,
    _get_direction,
    init_platform_dependencies,
)


@pytest.fixture(autouse=True)
def _reset_platform_deps():
    """每个 test 前/后重置全局单例, 避免互相污染."""
    init_platform_dependencies(registry=None, flag_db=None)
    yield
    init_platform_dependencies(registry=None, flag_db=None)


# ============================================================
# Layer 3: hardcoded (默认)
# ============================================================


def test_layer3_hardcoded_when_no_deps() -> None:
    """无任何 Platform 依赖时, 直接走 FACTOR_DIRECTION."""
    assert _get_direction("turnover_mean_20") == -1  # hardcoded -1
    assert _get_direction("bp_ratio") == 1
    assert _get_direction("reversal_20") == 1  # hardcoded +1 (signal_engine 真相源)


def test_layer3_hardcoded_fallback_for_unknown() -> None:
    assert _get_direction("nonexistent_factor_xyz") == 1  # default 1


# ============================================================
# Layer 0: FeatureFlag=off → hardcoded
# ============================================================


def test_flag_off_goes_to_hardcoded() -> None:
    flag = MagicMock()
    flag.is_enabled.return_value = False
    registry = MagicMock()
    registry.get_direction.return_value = 999  # 若走 Registry 会返 999
    init_platform_dependencies(registry=registry, flag_db=flag)

    # Flag off → 不调 Registry, 走 hardcoded
    assert _get_direction("turnover_mean_20") == -1
    registry.get_direction.assert_not_called()


# ============================================================
# Layer 1: FeatureFlag=on + Registry
# ============================================================


def test_flag_on_reads_from_registry() -> None:
    flag = MagicMock()
    flag.is_enabled.return_value = True
    registry = MagicMock()
    registry.get_direction.return_value = -1
    init_platform_dependencies(registry=registry, flag_db=flag)

    assert _get_direction("turnover_mean_20") == -1
    registry.get_direction.assert_called_once_with("turnover_mean_20")


def test_flag_on_registry_returns_different_value() -> None:
    """若 DB 与 hardcoded 不一致 (Step 1 修复前理论场景), 以 DB 为准."""
    flag = MagicMock()
    flag.is_enabled.return_value = True
    registry = MagicMock()
    registry.get_direction.return_value = -1  # 假设 DB 有不同值
    init_platform_dependencies(registry=registry, flag_db=flag)

    # 返 DB 值 (不看 FACTOR_DIRECTION)
    result = _get_direction("test_factor_xyz")
    assert result == -1
    registry.get_direction.assert_called_once()


# ============================================================
# 异常降级 (Layer 1 exception → Layer 3)
# ============================================================


def test_registry_exception_falls_back_to_hardcoded(caplog) -> None:
    """DB 挂或 cache refresh 失败 → fallback hardcoded + logger.warning."""
    flag = MagicMock()
    flag.is_enabled.return_value = True
    registry = MagicMock()
    registry.get_direction.side_effect = RuntimeError("DB transient failure")
    init_platform_dependencies(registry=registry, flag_db=flag)

    # 应返 hardcoded, 不 raise
    result = _get_direction("turnover_mean_20")
    assert result == -1  # hardcoded
    # 确保尝试过 Registry
    registry.get_direction.assert_called_once()


def test_flag_exception_silent_fallback() -> None:
    """FlagNotFound / FlagExpired 等 → silent fallback 到 hardcoded (silent_ok)."""
    flag = MagicMock()
    flag.is_enabled.side_effect = KeyError("flag not registered")
    registry = MagicMock()
    init_platform_dependencies(registry=registry, flag_db=flag)

    # 不 raise, 不调 registry
    result = _get_direction("turnover_mean_20")
    assert result == -1  # hardcoded
    registry.get_direction.assert_not_called()


# ============================================================
# init_platform_dependencies 行为
# ============================================================


def test_init_platform_dependencies_idempotent() -> None:
    flag1 = MagicMock()
    flag2 = MagicMock()
    registry = MagicMock()
    registry.get_direction.return_value = 1
    init_platform_dependencies(registry=registry, flag_db=flag1)
    init_platform_dependencies(registry=registry, flag_db=flag2)

    # 第二次 init 覆盖第一次 (flag1 不应被调, flag2 应被调)
    flag2.is_enabled.return_value = False
    _get_direction("x")
    flag2.is_enabled.assert_called_once()
    flag1.is_enabled.assert_not_called()


def test_init_resets_to_none() -> None:
    flag = MagicMock()
    init_platform_dependencies(registry=None, flag_db=flag)
    init_platform_dependencies(registry=None, flag_db=None)

    # 后续调用不碰 flag
    _get_direction("x")
    flag.is_enabled.assert_not_called()


# ============================================================
# 生产关键因子验证
# ============================================================


@pytest.mark.parametrize(
    "factor,expected",
    [
        ("turnover_mean_20", -1),  # CORE
        ("volatility_20", -1),  # CORE
        ("bp_ratio", 1),  # CORE
        ("dv_ttm", 1),  # CORE (2026-04-12 加入)
        ("reversal_20", 1),  # CORE5_baseline (hardcoded +1, MVP 1.3b Step 1 已修 DB)
        ("amihud_20", 1),  # CORE5_baseline
    ],
)
def test_core_factors_direction_hardcoded(factor: str, expected: int) -> None:
    """Layer 3 验证 CORE + CORE5_baseline 因子 direction (regression 依赖锚点)."""
    assert _get_direction(factor) == expected
    assert FACTOR_DIRECTION.get(factor) == expected  # dict 也对齐
