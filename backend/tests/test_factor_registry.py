"""MVP 1.3b test — DBFactorRegistry.get_direction + cache 行为."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.platform.factor.interface import FactorStatus
from backend.platform.factor.registry import DBFactorRegistry, StubLifecycleMonitor


@pytest.fixture
def mock_dal() -> MagicMock:
    """DAL mock, read_registry 返 3 因子 DataFrame."""
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        {
            "name": ["turnover_mean_20", "bp_ratio", "reversal_20"],
            "direction": [-1, 1, 1],
        }
    )
    return dal


# ============================================================
# get_direction 基本功能
# ============================================================


def test_get_direction_reads_from_dal(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.get_direction("turnover_mean_20") == -1
    assert r.get_direction("bp_ratio") == 1
    assert r.get_direction("reversal_20") == 1
    # DAL 只调用 1 次 (cache 命中后续)
    assert mock_dal.read_registry.call_count == 1


def test_get_direction_fallback_for_unknown(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.get_direction("nonexistent_factor") == 1  # default


def test_get_direction_first_call_loads_cache(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.cache_size() == 0
    r.get_direction("turnover_mean_20")
    assert r.cache_size() == 3


# ============================================================
# Cache TTL 行为
# ============================================================


def test_cache_hit_no_dal_call(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    r.get_direction("turnover_mean_20")
    r.get_direction("bp_ratio")
    r.get_direction("reversal_20")
    # 3 次调用, DAL 只调 1 次
    assert mock_dal.read_registry.call_count == 1


def test_cache_refresh_after_ttl(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal, cache_ttl_minutes=60)
    r.get_direction("turnover_mean_20")
    # 手动把 last_refresh 推到 61min 前
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=61)
    r.get_direction("bp_ratio")
    # DAL 被调 2 次 (第一次 + refresh)
    assert mock_dal.read_registry.call_count == 2


def test_cache_no_refresh_within_ttl(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal, cache_ttl_minutes=60)
    r.get_direction("turnover_mean_20")
    # 55min 前 (TTL 内)
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=55)
    r.get_direction("bp_ratio")
    assert mock_dal.read_registry.call_count == 1


def test_invalidate_forces_refresh(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    r.get_direction("turnover_mean_20")
    assert r.cache_size() == 3
    r.invalidate()
    assert r.cache_size() == 0
    # 下一次调用触发 refresh
    r.get_direction("turnover_mean_20")
    assert mock_dal.read_registry.call_count == 2


def test_custom_ttl_minutes() -> None:
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame({"name": ["x"], "direction": [1]})
    r = DBFactorRegistry(dal=dal, cache_ttl_minutes=5)
    r.get_direction("x")
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=6)
    r.get_direction("x")
    assert dal.read_registry.call_count == 2


# ============================================================
# DAL 异常传播 (铁律 33 禁 silent)
# ============================================================


def test_dal_exception_propagates() -> None:
    """DAL 异常不吞, 向上 raise (调用方决定 fallback)."""
    dal = MagicMock()
    dal.read_registry.side_effect = RuntimeError("DB down")
    r = DBFactorRegistry(dal=dal)
    with pytest.raises(RuntimeError, match="DB down"):
        r.get_direction("x")


def test_dal_exception_on_refresh_doesnt_corrupt_cache() -> None:
    """已有 cache 的情况下, refresh 失败不清空 cache.

    注意: 当前实现 TTL 过期时即使 refresh 失败, 异常向上 raise.
    调用方决定是否 catch + fallback. 本测试验证 cache 状态未被破坏.
    """
    dal = MagicMock()
    dal.read_registry.side_effect = [
        pd.DataFrame({"name": ["x"], "direction": [-1]}),
        RuntimeError("DB transient"),
    ]
    r = DBFactorRegistry(dal=dal, cache_ttl_minutes=60)
    r.get_direction("x")
    assert r._cache == {"x": -1}
    # 强制 TTL 过期
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=61)
    with pytest.raises(RuntimeError, match="transient"):
        r.get_direction("x")
    # cache 未被新值覆盖 (异常发生在 read_registry, _cache 还是旧值)
    assert r._cache == {"x": -1}


# ============================================================
# 其他 abstract 方法 (MVP 1.3c 未实现)
# ============================================================


def test_register_raises_not_implemented(mock_dal) -> None:
    from backend.platform.factor.interface import FactorSpec

    r = DBFactorRegistry(dal=mock_dal)
    spec = FactorSpec(
        name="x",
        hypothesis="h",
        expression="e",
        direction=1,
        category="c",
        pool="p",
        author="a",
    )
    with pytest.raises(NotImplementedError, match="MVP 1.3c"):
        r.register(spec)


def test_get_active_raises_not_implemented(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    with pytest.raises(NotImplementedError, match="MVP 1.3c"):
        r.get_active()


def test_update_status_raises_not_implemented(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    with pytest.raises(NotImplementedError, match="MVP 1.3c"):
        r.update_status("x", FactorStatus.ACTIVE, "reason")


def test_novelty_check_raises_not_implemented(mock_dal) -> None:
    from backend.platform.factor.interface import FactorSpec

    r = DBFactorRegistry(dal=mock_dal)
    spec = FactorSpec(
        name="x", hypothesis="h", expression="e", direction=1,
        category="c", pool="p", author="a",
    )
    with pytest.raises(NotImplementedError, match="MVP 1.3c"):
        r.novelty_check(spec)


# ============================================================
# StubLifecycleMonitor
# ============================================================


def test_stub_lifecycle_raises() -> None:
    monitor = StubLifecycleMonitor()
    with pytest.raises(NotImplementedError, match="MVP 1.3c"):
        monitor.evaluate_all()


# ============================================================
# 集成: direction 与 MVP 1.3a 回填数据对齐 (reversal_20 fix 验证)
# ============================================================


def test_direction_fix_reversal_20() -> None:
    """模拟 MVP 1.3b Step 1 修 DB 后的场景: reversal_20 direction=+1."""
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        {"name": ["reversal_20"], "direction": [1]}  # Step 1 修复后
    )
    r = DBFactorRegistry(dal=dal)
    assert r.get_direction("reversal_20") == 1  # 对齐 signal_engine hardcoded
