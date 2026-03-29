"""Portfolio API 路由 — 持仓、行业分布、每日盈亏。

Sprint 1.23: 为前端Portfolio页面补齐后端API。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

from datetime import date, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── 依赖注入 ──


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入 AsyncSession。"""
    return session


# ── 路由 ──


@router.get("/holdings")
async def get_holdings(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取当前持仓列表（position_snapshot最新日期）。

    从 position_snapshot 读取最新日期的持仓记录，
    JOIN symbols 获取股票名称和行业信息。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        持仓列表，每项含 code/name/industry/quantity/avg_cost/market_value/
        weight/unrealized_pnl/holding_days。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        WITH latest_date AS (
            SELECT MAX(trade_date) AS max_date
            FROM position_snapshot
            WHERE strategy_id = CAST(:sid AS uuid)
              AND execution_mode = :mode
        )
        SELECT
            ps.code,
            s.name,
            s.industry_sw1 AS industry,
            ps.quantity,
            ps.avg_cost,
            ps.market_value,
            ps.weight,
            ps.unrealized_pnl,
            ps.holding_days,
            ps.trade_date
        FROM position_snapshot ps
        LEFT JOIN symbols s ON s.code = ps.code
        JOIN latest_date ld ON ps.trade_date = ld.max_date
        WHERE ps.strategy_id = CAST(:sid AS uuid)
          AND ps.execution_mode = :mode
        ORDER BY ps.weight DESC NULLS LAST
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "mode": execution_mode})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询当前持仓失败")
        return []

    return [
        {
            "code": r["code"],
            "name": r["name"] or r["code"],
            "industry": r["industry"] or "未知",
            "quantity": r["quantity"] or 0,
            "avg_cost": float(r["avg_cost"]) if r["avg_cost"] else 0.0,
            "market_value": float(r["market_value"]) if r["market_value"] else 0.0,
            "weight": float(r["weight"]) if r["weight"] else 0.0,
            "unrealized_pnl": float(r["unrealized_pnl"]) if r["unrealized_pnl"] else 0.0,
            "holding_days": r["holding_days"] or 0,
            "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None,
        }
        for r in rows
    ]


@router.get("/sector-distribution")
async def get_sector_distribution(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取当前持仓行业分布。

    从 position_snapshot 最新日期持仓，JOIN symbols.industry_sw1，
    按权重汇总后返回百分比。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        行业分布列表，每项含 name/pct/value（市值元）。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        WITH latest_date AS (
            SELECT MAX(trade_date) AS max_date
            FROM position_snapshot
            WHERE strategy_id = CAST(:sid AS uuid)
              AND execution_mode = :mode
        ),
        holdings AS (
            SELECT
                COALESCE(s.industry_sw1, '其他') AS industry,
                SUM(ps.weight) AS total_weight,
                SUM(ps.market_value) AS total_value
            FROM position_snapshot ps
            LEFT JOIN symbols s ON s.code = ps.code
            JOIN latest_date ld ON ps.trade_date = ld.max_date
            WHERE ps.strategy_id = CAST(:sid AS uuid)
              AND ps.execution_mode = :mode
            GROUP BY COALESCE(s.industry_sw1, '其他')
        )
        SELECT
            industry AS name,
            ROUND(total_weight * 100, 2) AS pct,
            total_value AS value
        FROM holdings
        ORDER BY total_weight DESC NULLS LAST
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "mode": execution_mode})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询行业分布失败")
        return []

    return [
        {
            "name": r["name"],
            "pct": float(r["pct"]) if r["pct"] else 0.0,
            "value": float(r["value"]) if r["value"] else 0.0,
        }
        for r in rows
    ]


@router.get("/daily-pnl")
async def get_daily_pnl(
    days: int = Query(default=20, ge=1, le=250, description="返回天数"),
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取每日盈亏序列。

    从 performance_series 按日读取，返回日收益率和累计收益。

    Args:
        days: 返回天数，默认20天。
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        每日盈亏列表（最新在后），每项含
        trade_date/daily_return/cumulative_return/nav/drawdown。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    cutoff = date.today() - timedelta(days=days)

    sql = text("""
        SELECT
            trade_date,
            nav,
            daily_return,
            cumulative_return,
            drawdown,
            position_count,
            turnover
        FROM performance_series
        WHERE strategy_id = CAST(:sid AS uuid)
          AND execution_mode = :mode
          AND trade_date >= :cutoff
        ORDER BY trade_date ASC
        LIMIT :lim
    """)

    try:
        result = await session.execute(
            sql, {"sid": sid, "mode": execution_mode, "cutoff": cutoff, "lim": days}
        )
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询每日盈亏序列失败")
        return []

    return [
        {
            "trade_date": r["trade_date"].isoformat(),
            "nav": float(r["nav"]) if r["nav"] else 1.0,
            "daily_return": float(r["daily_return"]) if r["daily_return"] else 0.0,
            "cumulative_return": float(r["cumulative_return"]) if r["cumulative_return"] else 0.0,
            "drawdown": float(r["drawdown"]) if r["drawdown"] else 0.0,
            "position_count": r["position_count"] or 0,
            "turnover": float(r["turnover"]) if r["turnover"] else 0.0,
        }
        for r in rows
    ]
