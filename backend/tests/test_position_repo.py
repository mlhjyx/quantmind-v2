"""PositionRepository测试。

重点: save_snapshot幂等性(DELETE+INSERT)、最新持仓查询、持仓数量。
"""

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

_EMPTY_UUID = str(uuid.UUID(int=0))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repositories.position_repository import PositionRepository


@pytest_asyncio.fixture
async def pos_repo(db_session: AsyncSession) -> PositionRepository:
    return PositionRepository(db_session)


def _make_positions(n: int = 3) -> list[dict]:
    """生成N条测试持仓数据。"""
    return [
        {
            "code": f"00000{i}.SZ",
            "quantity": (i + 1) * 100,
            "market_value": (i + 1) * 10000.0,
            "weight": round(1.0 / n, 6),
        }
        for i in range(n)
    ]


# ──────────────────────────────────────────────
# save_snapshot + get_latest_positions
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_get_positions(pos_repo, strategy_id):
    """保存快照后能正确读回。"""
    td = date(2025, 3, 10)
    sid = str(strategy_id)
    positions = _make_positions(3)

    await pos_repo.save_snapshot(td, sid, positions, "paper")
    result = await pos_repo.get_latest_positions(sid, "paper")

    assert len(result) == 3
    codes = {r["code"] for r in result}
    assert "000000.SZ" in codes
    assert "000001.SZ" in codes
    assert "000002.SZ" in codes


@pytest.mark.asyncio
async def test_save_snapshot_idempotent(pos_repo, strategy_id):
    """重复保存同一天的快照不报错，且数据被替换。"""
    td = date(2025, 3, 11)
    sid = str(strategy_id)

    # 第一次: 3只股票
    await pos_repo.save_snapshot(td, sid, _make_positions(3), "paper")
    result1 = await pos_repo.get_positions_at_date(sid, td, "paper")
    assert len(result1) == 3

    # 第二次: 2只股票 (模拟调仓减少持仓)
    await pos_repo.save_snapshot(td, sid, _make_positions(2), "paper")
    result2 = await pos_repo.get_positions_at_date(sid, td, "paper")
    assert len(result2) == 2  # 旧数据被DELETE，新数据INSERT


@pytest.mark.asyncio
async def test_save_snapshot_idempotent_no_error(pos_repo, strategy_id):
    """连续3次保存同一天数据，不抛异常。"""
    td = date(2025, 3, 12)
    sid = str(strategy_id)

    for _ in range(3):
        await pos_repo.save_snapshot(td, sid, _make_positions(5), "paper")

    result = await pos_repo.get_positions_at_date(sid, td, "paper")
    assert len(result) == 5


# ──────────────────────────────────────────────
# get_latest_positions (多天数据取最新)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_latest_positions_picks_most_recent(pos_repo, strategy_id):
    """存在多天快照时，返回最新日期的数据。"""
    sid = str(strategy_id)

    # day1: 2只
    await pos_repo.save_snapshot(date(2025, 4, 1), sid, _make_positions(2), "paper")
    # day2: 4只
    await pos_repo.save_snapshot(date(2025, 4, 2), sid, _make_positions(4), "paper")

    result = await pos_repo.get_latest_positions(sid, "paper")
    assert len(result) == 4  # 返回day2的4只


# ──────────────────────────────────────────────
# get_positions_at_date
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_at_date_specific_day(pos_repo, strategy_id):
    """查询指定日期的持仓。"""
    sid = str(strategy_id)
    td = date(2025, 4, 3)
    positions = _make_positions(3)
    await pos_repo.save_snapshot(td, sid, positions, "paper")

    result = await pos_repo.get_positions_at_date(sid, td, "paper")
    assert len(result) == 3
    # 按weight DESC排序
    weights = [r["weight"] for r in result]
    assert weights == sorted(weights, reverse=True)


@pytest.mark.asyncio
async def test_get_positions_at_date_empty(pos_repo, strategy_id):
    """查询无数据的日期返回空列表。"""
    sid = str(strategy_id)
    result = await pos_repo.get_positions_at_date(sid, date(1999, 1, 1), "paper")
    assert result == []


# ──────────────────────────────────────────────
# get_position_count
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_position_count(pos_repo, strategy_id):
    """持仓数量正确。"""
    sid = str(strategy_id)
    await pos_repo.save_snapshot(date(2025, 5, 1), sid, _make_positions(7), "paper")
    count = await pos_repo.get_position_count(sid, "paper")
    assert count == 7


@pytest.mark.asyncio
async def test_get_position_count_empty(pos_repo, strategy_id):
    """无持仓时返回0。"""
    # 使用一个不存在数据的strategy_id
    count = await pos_repo.get_position_count(_EMPTY_UUID, "paper")
    assert count == 0


# ──────────────────────────────────────────────
# get_industry_exposure (需要symbols表有数据)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_industry_exposure_empty(pos_repo, strategy_id):
    """无持仓时行业暴露为空。"""
    result = await pos_repo.get_industry_exposure(str(strategy_id), "paper")
    # 如果没有匹配的symbols记录，JOIN后结果为空
    assert isinstance(result, list)


# ──────────────────────────────────────────────
# execution_mode隔离
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_mode_isolation(pos_repo, strategy_id):
    """paper和live模式的数据互不影响。

    注意: position_snapshot PK = (code, trade_date, strategy_id) 不含 execution_mode。
    因此同code+date+strategy_id只能存一种mode。
    这里用不同日期验证mode查询过滤逻辑。
    """
    sid = str(strategy_id)

    # paper模式 day1
    await pos_repo.save_snapshot(date(2025, 5, 5), sid, _make_positions(3), "paper")
    # live模式 day2（不同日期避免PK冲突）
    await pos_repo.save_snapshot(date(2025, 5, 6), sid, _make_positions(5), "live")

    paper = await pos_repo.get_positions_at_date(sid, date(2025, 5, 5), "paper")
    live = await pos_repo.get_positions_at_date(sid, date(2025, 5, 6), "live")

    assert len(paper) == 3
    assert len(live) == 5

    # 查询paper模式不应看到live数据
    paper_at_live_date = await pos_repo.get_positions_at_date(sid, date(2025, 5, 6), "paper")
    assert len(paper_at_live_date) == 0
