"""PerformanceRepository测试。

重点: get_rolling_stats计算正确性、upsert_daily幂等性、NAV序列查询。
"""

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 一个不存在于DB中的合法UUID，用于"空数据"测试
_EMPTY_UUID = str(uuid.UUID(int=0))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repositories.performance_repository import PerformanceRepository


@pytest_asyncio.fixture
async def perf_repo(db_session: AsyncSession) -> PerformanceRepository:
    return PerformanceRepository(db_session)


@pytest_asyncio.fixture
async def seeded_perf_data(db_session: AsyncSession, strategy_id):
    """插入10天绩效数据，用于查询测试。

    NAV从1.0逐步变化，模拟真实走势。
    """
    base = date(2025, 1, 6)  # 周一
    navs = [1.0, 1.01, 1.005, 1.02, 1.015, 1.03, 1.025, 1.04, 1.035, 1.05]
    for i, nav_val in enumerate(navs):
        td = base + timedelta(days=i)
        daily_ret = (nav_val / navs[i - 1] - 1) if i > 0 else 0.0
        cum_ret = nav_val - 1.0
        dd = min(0, nav_val / max(navs[: i + 1]) - 1)
        await db_session.execute(
            text(
                """INSERT INTO performance_series
                   (trade_date, strategy_id, nav, daily_return, cumulative_return,
                    drawdown, cash_ratio, cash, position_count, turnover,
                    benchmark_nav, execution_mode)
                   VALUES (:td, :sid, :nav, :ret, :cum, :dd, :cr, :cash, :pc, :to, :bn, 'paper')"""
            ),
            {
                "td": td, "sid": strategy_id, "nav": nav_val,
                "ret": round(daily_ret, 8), "cum": round(cum_ret, 8),
                "dd": round(dd, 8), "cr": 0.05, "cash": 50000.0,
                "pc": 30, "to": 0.1, "bn": 1.0 + i * 0.003,
            },
        )
    return {"strategy_id": str(strategy_id), "base_date": base, "navs": navs}


# ──────────────────────────────────────────────
# get_latest_nav
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_latest_nav_returns_most_recent(perf_repo, seeded_perf_data):
    """get_latest_nav应返回最新日期的记录。"""
    sid = seeded_perf_data["strategy_id"]
    result = await perf_repo.get_latest_nav(sid, "paper")

    assert result is not None
    # 最新一天的NAV是1.05
    assert result["nav"] == pytest.approx(1.05, abs=1e-4)
    assert result["trade_date"] == seeded_perf_data["base_date"] + timedelta(days=9)
    assert result["position_count"] == 30


@pytest.mark.asyncio
async def test_get_latest_nav_empty(perf_repo):
    """无数据时返回None。"""
    result = await perf_repo.get_latest_nav(_EMPTY_UUID, "paper")
    assert result is None


# ──────────────────────────────────────────────
# get_nav_series
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nav_series_full(perf_repo, seeded_perf_data):
    """不带日期范围返回全部。"""
    sid = seeded_perf_data["strategy_id"]
    series = await perf_repo.get_nav_series(sid)
    assert len(series) == 10
    # 按日期升序
    assert series[0]["trade_date"] < series[-1]["trade_date"]


@pytest.mark.asyncio
async def test_get_nav_series_with_date_range(perf_repo, seeded_perf_data):
    """带日期范围过滤。"""
    sid = seeded_perf_data["strategy_id"]
    base = seeded_perf_data["base_date"]
    series = await perf_repo.get_nav_series(
        sid, start_date=base + timedelta(days=2), end_date=base + timedelta(days=5)
    )
    assert len(series) == 4  # day2,3,4,5


# ──────────────────────────────────────────────
# get_rolling_stats (重点测试)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rolling_stats_sharpe_calculation(perf_repo, seeded_perf_data):
    """验证Sharpe计算: daily_mean / daily_std * sqrt(252)。"""
    sid = seeded_perf_data["strategy_id"]
    stats = await perf_repo.get_rolling_stats(sid, lookback_days=10)

    assert stats is not None
    assert stats["days"] == 10

    # 手动计算期望值
    navs = seeded_perf_data["navs"]
    # repo按DESC取，rets对应倒序nav
    navs_desc = list(reversed(navs))
    # daily_return是存入DB的值，我们重新算
    daily_rets_stored = []
    for i in range(len(navs)):
        if i == 0:
            daily_rets_stored.append(0.0)
        else:
            daily_rets_stored.append(round(navs[i] / navs[i - 1] - 1, 8))

    # repo内部rets来自DB的daily_return字段（DESC取出）
    rets = list(reversed(daily_rets_stored))
    daily_mean = np.mean(rets)
    daily_std = np.std(rets, ddof=1)
    expected_sharpe = round(daily_mean / daily_std * np.sqrt(252), 3)

    assert stats["sharpe"] == pytest.approx(expected_sharpe, abs=0.01)


@pytest.mark.asyncio
async def test_rolling_stats_mdd_calculation(perf_repo, seeded_perf_data):
    """验证MDD计算: peak回撤。"""
    sid = seeded_perf_data["strategy_id"]
    stats = await perf_repo.get_rolling_stats(sid, lookback_days=10)

    assert stats is not None
    # NAV序列: 1.0, 1.01, 1.005, 1.02, 1.015, 1.03, 1.025, 1.04, 1.035, 1.05
    # peak tracking (正序): 1.0, 1.01, 1.01, 1.02, 1.02, 1.03, 1.03, 1.04, 1.04, 1.05
    # drawdown:             0,    0, -0.00495, 0, -0.00490, 0, -0.00485, 0, -0.00481, 0
    # MDD ≈ -0.00495
    assert stats["mdd"] < 0  # 应该是负数
    # repo的MDD计算: peak从最新NAV(1.05)开始，遍历正序(1.0, 1.01, ...)
    # 所以MDD = 1.0/1.05 - 1 ≈ -0.0476
    assert stats["mdd"] == pytest.approx(-0.0476, abs=0.002)


@pytest.mark.asyncio
async def test_rolling_stats_total_return(perf_repo, seeded_perf_data):
    """验证total_return: latest_nav / earliest_nav - 1。"""
    sid = seeded_perf_data["strategy_id"]
    stats = await perf_repo.get_rolling_stats(sid, lookback_days=10)

    assert stats is not None
    # navs[0]=第一天(最早), repo DESC取出: navs[0]是最新(1.05), navs[-1]是最旧(1.0)
    expected_return = round(1.05 / 1.0 - 1, 4)
    assert stats["total_return"] == pytest.approx(expected_return, abs=0.001)
    assert stats["latest_nav"] == pytest.approx(1.05, abs=1e-4)


@pytest.mark.asyncio
async def test_rolling_stats_partial_lookback(perf_repo, seeded_perf_data):
    """lookback_days < 实际数据天数时，只取最近N天。"""
    sid = seeded_perf_data["strategy_id"]
    stats = await perf_repo.get_rolling_stats(sid, lookback_days=5)
    assert stats is not None
    assert stats["days"] == 5


@pytest.mark.asyncio
async def test_rolling_stats_empty(perf_repo):
    """无数据返回None。"""
    stats = await perf_repo.get_rolling_stats(_EMPTY_UUID)
    assert stats is None


# ──────────────────────────────────────────────
# get_peak_nav
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_peak_nav(perf_repo, seeded_perf_data):
    """peak NAV应为序列中最大值。"""
    sid = seeded_perf_data["strategy_id"]
    peak = await perf_repo.get_peak_nav(sid, "paper")
    assert peak == pytest.approx(1.05, abs=1e-4)


@pytest.mark.asyncio
async def test_get_peak_nav_empty(perf_repo):
    """无数据时返回0。"""
    peak = await perf_repo.get_peak_nav(_EMPTY_UUID, "paper")
    assert peak == 0


# ──────────────────────────────────────────────
# upsert_daily (幂等性)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_daily_insert(perf_repo, strategy_id, db_session):
    """首次写入新增记录。"""
    td = date(2025, 6, 1)
    sid = str(strategy_id)
    await perf_repo.upsert_daily(
        trade_date=td, strategy_id=sid,
        nav=1.1, daily_return=0.01, cumulative_return=0.1,
        drawdown=-0.02, cash_ratio=0.05, cash=50000.0,
        position_count=30, turnover=0.15, benchmark_nav=1.05,
    )
    result = await perf_repo.get_latest_nav(sid, "paper")
    assert result is not None
    assert result["nav"] == pytest.approx(1.1, abs=1e-4)


@pytest.mark.asyncio
async def test_upsert_daily_idempotent(perf_repo, strategy_id, db_session):
    """重复upsert同一天，不报错，值被更新。"""
    td = date(2025, 6, 2)
    sid = str(strategy_id)

    # 第一次写入
    await perf_repo.upsert_daily(
        trade_date=td, strategy_id=sid,
        nav=1.0, daily_return=0.0, cumulative_return=0.0,
        drawdown=0.0, cash_ratio=0.1, cash=100000.0,
        position_count=0, turnover=0.0, benchmark_nav=1.0,
    )

    # 第二次写入(更新NAV)
    await perf_repo.upsert_daily(
        trade_date=td, strategy_id=sid,
        nav=1.05, daily_return=0.05, cumulative_return=0.05,
        drawdown=0.0, cash_ratio=0.08, cash=80000.0,
        position_count=20, turnover=0.2, benchmark_nav=1.02,
    )

    result = await perf_repo.get_latest_nav(sid, "paper")
    assert result is not None
    assert result["nav"] == pytest.approx(1.05, abs=1e-4)
    assert result["position_count"] == 20
