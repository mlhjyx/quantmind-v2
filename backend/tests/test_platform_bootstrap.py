"""MVP 1.3b wiring 补全 integration test — bootstrap_platform_deps.

单元覆盖 signal_engine._get_direction 3 层 fallback 已在 test_signal_engine_direction.py.
本模块只测 helper 本身: 注入 / 幂等 / force / reset / fail-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 确保 backend/ 在 sys.path — 测试可独立运行
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.append(_BACKEND_DIR)


@pytest.fixture(autouse=True)
def _reset_bootstrap():
    """每个 test 独立 — 重置 bootstrap state 及 signal_engine globals."""
    from app.core.platform_bootstrap import reset_platform_deps

    reset_platform_deps()
    yield
    reset_platform_deps()


def _patch_get_sync_conn(monkeypatch) -> MagicMock:
    """monkeypatch app.services.db.get_sync_conn 返 MagicMock connection."""
    mock_conn = MagicMock()
    import app.services.db as db_module

    monkeypatch.setattr(db_module, "get_sync_conn", lambda: mock_conn)
    return mock_conn


# ---------- 1. 注入成功 ----------


def test_bootstrap_injects_registry_and_flag(monkeypatch) -> None:
    _patch_get_sync_conn(monkeypatch)
    from app.core.platform_bootstrap import bootstrap_platform_deps

    result = bootstrap_platform_deps()

    assert result is True
    from engines import signal_engine

    assert signal_engine._PLATFORM_REGISTRY is not None
    assert signal_engine._PLATFORM_FLAG_DB is not None


# ---------- 2. 幂等 ----------


def test_bootstrap_is_idempotent(monkeypatch) -> None:
    _patch_get_sync_conn(monkeypatch)
    from app.core.platform_bootstrap import bootstrap_platform_deps

    assert bootstrap_platform_deps() is True

    from engines import signal_engine

    first_registry = signal_engine._PLATFORM_REGISTRY
    first_flag = signal_engine._PLATFORM_FLAG_DB

    # 第二次调用 — early return True, 不重建
    assert bootstrap_platform_deps() is True
    assert signal_engine._PLATFORM_REGISTRY is first_registry
    assert signal_engine._PLATFORM_FLAG_DB is first_flag


# ---------- 3. force=True 重建 ----------


def test_bootstrap_force_rebuilds(monkeypatch) -> None:
    _patch_get_sync_conn(monkeypatch)
    from app.core.platform_bootstrap import bootstrap_platform_deps

    bootstrap_platform_deps()
    from engines import signal_engine

    first_registry = signal_engine._PLATFORM_REGISTRY

    # force=True → 新实例
    assert bootstrap_platform_deps(force=True) is True
    assert signal_engine._PLATFORM_REGISTRY is not first_registry


# ---------- 4. reset 清空 ----------


def test_reset_clears_signal_engine_globals(monkeypatch) -> None:
    _patch_get_sync_conn(monkeypatch)
    from app.core.platform_bootstrap import bootstrap_platform_deps, reset_platform_deps

    bootstrap_platform_deps()
    from engines import signal_engine

    assert signal_engine._PLATFORM_REGISTRY is not None

    reset_platform_deps()

    assert signal_engine._PLATFORM_REGISTRY is None
    assert signal_engine._PLATFORM_FLAG_DB is None


# ---------- 5. fail-safe: init 异常 → return False, 不 raise ----------


def test_bootstrap_fail_safe_on_init_error(monkeypatch) -> None:
    """init_platform_dependencies 抛异常 → 返 False, signal_engine 保持 None (Layer 0)."""
    _patch_get_sync_conn(monkeypatch)

    import engines.signal_engine as se

    def _raise(**_kwargs):
        raise RuntimeError("simulated wiring failure")

    monkeypatch.setattr(se, "init_platform_dependencies", _raise)

    from app.core.platform_bootstrap import bootstrap_platform_deps

    result = bootstrap_platform_deps()

    assert result is False
    # signal_engine globals 维持初始 None (Layer 0 fallback)
    assert se._PLATFORM_REGISTRY is None
    assert se._PLATFORM_FLAG_DB is None


# ---------- 6. 注入后 _get_direction 回落 hardcoded (flag 查询异常场景) ----------


def test_get_direction_falls_back_when_flag_raises(monkeypatch) -> None:
    """注入后 flag.is_enabled 抛异常 → _get_direction 回 hardcoded (不 raise)."""
    _patch_get_sync_conn(monkeypatch)
    from app.core.platform_bootstrap import bootstrap_platform_deps

    bootstrap_platform_deps()

    import engines.signal_engine as se

    # mock flag.is_enabled 抛异常 — 测 _get_direction Layer 3 fallback
    fake_flag = MagicMock()
    fake_flag.is_enabled.side_effect = RuntimeError("DB 不可达")
    fake_registry = MagicMock()
    fake_registry.get_direction.return_value = 999  # 若不走 fallback 会返 999
    se.init_platform_dependencies(registry=fake_registry, flag_db=fake_flag)

    # turnover_mean_20 hardcoded = -1
    assert se._get_direction("turnover_mean_20") == -1
    # registry.get_direction 不该被调 (flag 异常前置中断)
    fake_registry.get_direction.assert_not_called()
