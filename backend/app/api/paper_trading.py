"""Paper Trading API 路由。

提供 Paper Trading 状态查询、毕业进度、持仓和交易记录。
"""

import math
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository
from app.services.paper_trading_service import PaperTradingService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])

# 固定毕业标准（CLAUDE.md 策略版本化纪律章节）
_GRADUATION_SHARPE_TARGET = 0.72
_GRADUATION_MDD_LIMIT = -0.35  # MDD < 35%（绝对值）
_GRADUATION_SLIP_DEV_LIMIT = 0.50  # 滑点偏差 < 50%
_GRADUATION_MODEL_SLIPPAGE_BPS = 64.5  # R4研究: PT实测64.5bps基准


def _get_paper_trading_service(
    session: AsyncSession = Depends(get_db),
) -> PaperTradingService:
    """通过 Depends 注入 PaperTradingService。"""
    return PaperTradingService(session)


def _get_position_repo(
    session: AsyncSession = Depends(get_db),
) -> PositionRepository:
    """通过 Depends 注入 PositionRepository。"""
    return PositionRepository(session)


def _get_trade_repo(
    session: AsyncSession = Depends(get_db),
) -> TradeRepository:
    """通过 Depends 注入 TradeRepository。"""
    return TradeRepository(session)


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入 AsyncSession（直接SQL端点使用）。"""
    return session


@router.get("/status")
async def paper_trading_status(
    strategy_id: str = Query(default="", description="策略ID"),
    svc: PaperTradingService = Depends(_get_paper_trading_service),
) -> dict[str, Any]:
    """获取 Paper Trading 当前状态。

    返回净值、持仓数、运行天数、Sharpe、MDD、累计收益、是否达到毕业最低天数。

    Args:
        strategy_id: 策略ID。为空时使用默认Paper策略。

    Returns:
        Paper Trading 状态字典。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_status(sid)


@router.get("/graduation")
async def paper_trading_graduation(
    strategy_id: str = Query(default="", description="策略ID"),
    backtest_sharpe: float = Query(default=0, description="回测Sharpe基准"),
    backtest_mdd: float = Query(default=0, description="回测MDD基准(负数)"),
    model_slippage_bps: float = Query(default=0, description="模型预估滑点(bps)"),
    svc: PaperTradingService = Depends(_get_paper_trading_service),
) -> dict[str, Any]:
    """获取毕业标准达标情况。

    将 Paper Trading 实际表现与回测基准逐项对比，检查 5 条毕业标准。

    Args:
        strategy_id: 策略ID。
        backtest_sharpe: 回测 Sharpe 基准。
        backtest_mdd: 回测最大回撤（负数，如 -0.12）。
        model_slippage_bps: 模型预估滑点 (bps)。

    Returns:
        毕业进度字典，含 criteria/all_passed/summary。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await svc.get_graduation_progress(sid, backtest_sharpe, backtest_mdd, model_slippage_bps)


@router.get("/graduation-status")
async def paper_trading_graduation_status(
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """获取Paper Trading毕业状态（固定标准版）。

    使用CLAUDE.md中定义的固定毕业标准，无需传入回测基准参数。
    毕业标准: Sharpe >= 0.72, MDD < 35%, 滑点偏差 < 50%。

    days_running 从 performance_series 最早日期到最新日期的自然日数。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        session: AsyncSession（Depends注入）。

    Returns:
        dict: {
            "days_running": int,           # 自然日数
            "sharpe": float,
            "mdd": float,                  # 负数，如 -0.12
            "slippage_deviation": float,   # 小数，如 0.30 = 30%
            "graduate_ready": bool,        # 是否全部达标
            "criteria": [
                {"name": str, "target": str, "actual": str, "passed": bool}
            ]
        }
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    # 1. 从 performance_series 获取日期范围和统计量
    perf_sql = text("""
        SELECT
            MIN(trade_date)           AS start_date,
            MAX(trade_date)           AS end_date,
            COUNT(*)                  AS trading_days,
            AVG(daily_return)         AS avg_return,
            STDDEV_SAMP(daily_return) AS std_return,
            MIN(drawdown)             AS max_drawdown
        FROM performance_series
        WHERE strategy_id = CAST(:sid AS uuid)
          AND execution_mode = 'paper'
    """)
    try:
        result = await session.execute(perf_sql, {"sid": sid})
        row = result.mappings().one_or_none()
    except Exception:
        logger.exception("查询Paper Trading绩效数据失败")
        row = None

    if row is None or row["start_date"] is None:
        sharpe = 0.0
        mdd = 0.0
        days_running = 0
    else:
        start_date = row["start_date"]
        end_date = row["end_date"]
        days_running = (end_date - start_date).days if end_date and start_date else 0

        avg_ret = float(row["avg_return"]) if row["avg_return"] else 0.0
        std_ret = float(row["std_return"]) if row["std_return"] else 0.0
        # 日收益率年化 Sharpe (252交易日)
        sharpe = float(avg_ret / std_ret * math.sqrt(252)) if std_ret > 1e-12 else 0.0
        mdd = float(row["max_drawdown"]) if row["max_drawdown"] else 0.0

    # 2. 计算实际平均滑点（从 trade_log）
    slip_sql = text("""
        SELECT AVG(slippage_bps) AS avg_slippage
        FROM trade_log
        WHERE strategy_id = CAST(:sid AS uuid)
          AND execution_mode = 'paper'
          AND slippage_bps IS NOT NULL
    """)
    try:
        slip_result = await session.execute(slip_sql, {"sid": sid})
        slip_row = slip_result.mappings().one_or_none()
        actual_slippage_bps = (
            float(slip_row["avg_slippage"]) if slip_row and slip_row["avg_slippage"] else 0.0
        )
    except Exception:
        logger.exception("查询Paper Trading滑点数据失败")
        actual_slippage_bps = 0.0

    slippage_deviation = (
        abs(actual_slippage_bps - _GRADUATION_MODEL_SLIPPAGE_BPS) / _GRADUATION_MODEL_SLIPPAGE_BPS
        if _GRADUATION_MODEL_SLIPPAGE_BPS > 0 and actual_slippage_bps > 0
        else 0.0
    )

    criteria = [
        {
            "name": "Sharpe",
            "target": f">= {_GRADUATION_SHARPE_TARGET}",
            "actual": f"{sharpe:.3f}",
            "passed": sharpe >= _GRADUATION_SHARPE_TARGET,
        },
        {
            "name": "最大回撤",
            "target": f"> {_GRADUATION_MDD_LIMIT:.0%}",
            "actual": f"{mdd:.2%}",
            "passed": mdd > _GRADUATION_MDD_LIMIT,
        },
        {
            "name": "滑点偏差",
            "target": f"< {_GRADUATION_SLIP_DEV_LIMIT:.0%}",
            "actual": f"{slippage_deviation:.1%} (实测{actual_slippage_bps:.1f}bps)",
            "passed": slippage_deviation < _GRADUATION_SLIP_DEV_LIMIT,
        },
    ]

    graduate_ready = all(c["passed"] for c in criteria)

    return {
        "days_running": days_running,
        "sharpe": sharpe,
        "mdd": mdd,
        "slippage_deviation": slippage_deviation,
        "graduate_ready": graduate_ready,
        "criteria": criteria,
    }


@router.get("/positions")
async def paper_trading_positions(
    strategy_id: str = Query(default="", description="策略ID"),
    repo: PositionRepository = Depends(_get_position_repo),
) -> list[dict[str, Any]]:
    """获取 Paper Trading 当前持仓。

    返回最新日期的全部持仓，按权重降序排列。

    Args:
        strategy_id: 策略ID。

    Returns:
        持仓列表，每项含 code/quantity/market_value/weight/avg_cost/unrealized_pnl/holding_days。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await repo.get_latest_positions(sid, execution_mode="paper")


@router.get("/trades")
async def paper_trading_trades(
    strategy_id: str = Query(default="", description="策略ID"),
    limit: int = Query(default=50, ge=1, le=500, description="返回条数上限"),
    repo: TradeRepository = Depends(_get_trade_repo),
) -> list[dict[str, Any]]:
    """获取 Paper Trading 最近交易记录。

    按交易日期降序返回，默认最近 50 条。

    Args:
        strategy_id: 策略ID。
        limit: 返回条数上限，1-500。

    Returns:
        交易记录列表，每项含 id/code/trade_date/direction/quantity/fill_price 等。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    return await repo.get_trades(sid, execution_mode="paper", limit=limit)
