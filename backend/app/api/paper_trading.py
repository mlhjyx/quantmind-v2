"""Paper Trading API 路由。

提供 Paper Trading 状态查询、毕业进度、持仓和交易记录。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository
from app.services.paper_trading_service import PaperTradingService

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


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
    return await svc.get_graduation_progress(
        sid, backtest_sharpe, backtest_mdd, model_slippage_bps
    )


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
