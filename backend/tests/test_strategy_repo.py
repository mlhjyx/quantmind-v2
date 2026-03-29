"""StrategyRepository测试。

重点: create_config_version版本号递增、rollback_version、配置历史查询。
CLAUDE.md: strategy_configs每次变更插入新version行，回滚=把active_version指回旧版本号。
"""

import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repositories.strategy_repository import StrategyRepository


@pytest_asyncio.fixture
async def strat_repo(db_session: AsyncSession) -> StrategyRepository:
    return StrategyRepository(db_session)


# ──────────────────────────────────────────────
# get_strategy
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_strategy_exists(strat_repo, strategy_id):
    """能正确读取已存在的strategy。"""
    result = await strat_repo.get_strategy(str(strategy_id))
    assert result is not None
    assert result["id"] == str(strategy_id)
    assert result["market"] == "astock"
    assert result["status"] == "draft"
    assert result["active_version"] == 1


@pytest.mark.asyncio
async def test_get_strategy_not_found(strat_repo):
    """不存在的strategy返回None。"""
    result = await strat_repo.get_strategy("00000000-0000-0000-0000-000000000000")
    assert result is None


# ──────────────────────────────────────────────
# create_config_version (重点测试)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_config_version_first(strat_repo, strategy_id):
    """首次创建配置版本，版本号=1。"""
    sid = str(strategy_id)
    config = {"factors": ["pe", "pb"], "top_n": 30}
    ver = await strat_repo.create_config_version(sid, config, "初始配置")

    assert ver == 1

    # 检查active_version已更新
    strat = await strat_repo.get_strategy(sid)
    assert strat["active_version"] == 1


@pytest.mark.asyncio
async def test_create_config_version_increments(strat_repo, strategy_id):
    """连续创建多个版本，版本号严格递增。"""
    sid = str(strategy_id)

    v1 = await strat_repo.create_config_version(
        sid, {"top_n": 30}, "v1: 30只"
    )
    v2 = await strat_repo.create_config_version(
        sid, {"top_n": 50}, "v2: 50只"
    )
    v3 = await strat_repo.create_config_version(
        sid, {"top_n": 20}, "v3: 20只"
    )

    assert v1 == 1
    assert v2 == 2
    assert v3 == 3

    # active_version应指向最新
    strat = await strat_repo.get_strategy(sid)
    assert strat["active_version"] == 3


@pytest.mark.asyncio
async def test_create_config_preserves_old_versions(strat_repo, strategy_id):
    """新版本不会删除旧版本记录(插入新行，不更新旧行)。"""
    sid = str(strategy_id)

    await strat_repo.create_config_version(sid, {"a": 1}, "v1")
    await strat_repo.create_config_version(sid, {"b": 2}, "v2")
    await strat_repo.create_config_version(sid, {"c": 3}, "v3")

    history = await strat_repo.get_config_history(sid)
    assert len(history) == 3
    # 按version DESC
    versions = [h["version"] for h in history]
    assert versions == [3, 2, 1]


# ──────────────────────────────────────────────
# get_active_config
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_active_config(strat_repo, strategy_id):
    """获取当前活跃版本的配置。"""
    sid = str(strategy_id)

    await strat_repo.create_config_version(sid, {"v": 1}, "first")
    await strat_repo.create_config_version(sid, {"v": 2, "top_n": 50}, "second")

    active = await strat_repo.get_active_config(sid)
    assert active is not None
    assert active["version"] == 2
    # config是JSONB，从DB返回应该是dict
    cfg = active["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    assert cfg["v"] == 2
    assert cfg["top_n"] == 50


@pytest.mark.asyncio
async def test_get_active_config_no_config(strat_repo, strategy_id):
    """strategy存在但没有config记录时返回None。

    conftest创建的strategy的active_version=1，但没有对应的strategy_configs行。
    """
    sid = str(strategy_id)
    result = await strat_repo.get_active_config(sid)
    assert result is None


# ──────────────────────────────────────────────
# rollback_version
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_version(strat_repo, strategy_id):
    """回滚只改active_version指针，不删除版本记录。"""
    sid = str(strategy_id)

    await strat_repo.create_config_version(sid, {"v": 1}, "v1")
    await strat_repo.create_config_version(sid, {"v": 2}, "v2")
    await strat_repo.create_config_version(sid, {"v": 3}, "v3")

    # 回滚到v1
    await strat_repo.rollback_version(sid, 1)

    strat = await strat_repo.get_strategy(sid)
    assert strat["active_version"] == 1

    # 所有3个版本记录仍然存在
    history = await strat_repo.get_config_history(sid)
    assert len(history) == 3

    # active_config应该指向v1
    active = await strat_repo.get_active_config(sid)
    assert active is not None
    assert active["version"] == 1


@pytest.mark.asyncio
async def test_rollback_then_create_new(strat_repo, strategy_id):
    """回滚后再创建新版本，版本号继续递增(不是从回滚点重新计数)。"""
    sid = str(strategy_id)

    await strat_repo.create_config_version(sid, {"v": 1}, "v1")
    await strat_repo.create_config_version(sid, {"v": 2}, "v2")
    await strat_repo.create_config_version(sid, {"v": 3}, "v3")

    # 回滚到v1
    await strat_repo.rollback_version(sid, 1)

    # 创建v4 (不是v2！)
    v4 = await strat_repo.create_config_version(sid, {"v": 4}, "v4 after rollback")
    assert v4 == 4

    strat = await strat_repo.get_strategy(sid)
    assert strat["active_version"] == 4


# ──────────────────────────────────────────────
# get_config_history
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_config_history_empty(strat_repo, strategy_id):
    """无配置记录时返回空列表。"""
    sid = str(strategy_id)
    history = await strat_repo.get_config_history(sid)
    assert history == []


@pytest.mark.asyncio
async def test_get_config_history_changelog(strat_repo, strategy_id):
    """changelog正确记录。"""
    sid = str(strategy_id)
    await strat_repo.create_config_version(sid, {}, "添加PE因子")
    await strat_repo.create_config_version(sid, {}, "调整换手率上限")

    history = await strat_repo.get_config_history(sid)
    changelogs = [h["changelog"] for h in history]
    assert "调整换手率上限" in changelogs
    assert "添加PE因子" in changelogs


# ──────────────────────────────────────────────
# list_strategies
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_strategies_no_filter(strat_repo, strategy_id):
    """无过滤条件列出策略。"""
    strategies = await strat_repo.list_strategies()
    assert len(strategies) >= 1  # 至少有conftest创建的那个
    ids = [s["id"] for s in strategies]
    assert str(strategy_id) in ids


@pytest.mark.asyncio
async def test_list_strategies_filter_market(strat_repo, strategy_id):
    """按market过滤。"""
    strategies = await strat_repo.list_strategies(market="astock")
    assert len(strategies) >= 1
    for s in strategies:
        assert s["market"] == "astock"


@pytest.mark.asyncio
async def test_list_strategies_filter_status(strat_repo, strategy_id):
    """按status过滤。"""
    strategies = await strat_repo.list_strategies(status="draft")
    assert len(strategies) >= 1
    for s in strategies:
        assert s["status"] == "draft"


@pytest.mark.asyncio
async def test_list_strategies_no_match(strat_repo):
    """不匹配的过滤条件返回空（或不包含测试数据）。"""
    strategies = await strat_repo.list_strategies(market="forex_nonexist_xyz")
    # 可能有其他数据，但至少不会报错
    for s in strategies:
        assert s["market"] == "forex_nonexist_xyz"
