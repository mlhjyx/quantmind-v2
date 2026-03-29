"""Execution API 路由 — 执行订单、执行日志、算法配置。

Sprint 1.23: 为前端Execution页面补齐后端API。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/execution", tags=["execution"])


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入 AsyncSession。"""
    return session


@router.get("/pending-orders")
async def get_pending_orders(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取待执行/执行中的订单列表。

    从 trade_log 读取 executed_at IS NULL（尚未确认执行）的记录，
    即 T 日信号生成、T+1 尚未执行的订单。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        待执行订单列表，每项含 id/code/name/direction/quantity/
        target_price/trade_date/status。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        SELECT
            tl.id,
            tl.code,
            s.name,
            tl.direction,
            tl.quantity,
            tl.target_price,
            tl.trade_date,
            tl.reject_reason,
            tl.created_at
        FROM trade_log tl
        LEFT JOIN symbols s ON s.code = tl.code
        WHERE tl.strategy_id = CAST(:sid AS uuid)
          AND tl.execution_mode = :mode
          AND tl.executed_at IS NULL
        ORDER BY tl.created_at DESC
        LIMIT 50
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "mode": execution_mode})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询待执行订单失败")
        return []

    return [
        {
            "id": str(r["id"]),
            "code": r["code"],
            "name": r["name"] or r["code"],
            "direction": r["direction"],
            "quantity": r["quantity"],
            "target_price": float(r["target_price"]) if r["target_price"] else None,
            "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None,
            "status": "rejected" if r["reject_reason"] else "pending",
            "reject_reason": r["reject_reason"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/log")
async def get_execution_log(
    log_date: str = Query(default="today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    limit: int = Query(default=100, ge=1, le=500, description="最大条数"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取执行历史日志。

    从 trade_log 读取已执行（executed_at IS NOT NULL）的历史记录，
    支持按日期过滤。

    Args:
        log_date: 日期，"today" 或 "YYYY-MM-DD" 格式。
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。
        limit: 最大返回条数。

    Returns:
        执行日志列表，每项含 id/code/name/direction/quantity/fill_price/
        slippage_bps/commission/total_cost/executed_at。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    if log_date == "today":
        filter_date = date.today()
    else:
        try:
            filter_date = date.fromisoformat(log_date)
        except ValueError:
            filter_date = date.today()

    sql = text("""
        SELECT
            tl.id,
            tl.code,
            s.name,
            tl.direction,
            tl.quantity,
            tl.target_price,
            tl.fill_price,
            tl.slippage_bps,
            tl.commission,
            tl.stamp_tax,
            tl.total_cost,
            tl.trade_date,
            tl.reject_reason,
            tl.executed_at,
            tl.created_at
        FROM trade_log tl
        LEFT JOIN symbols s ON s.code = tl.code
        WHERE tl.strategy_id = CAST(:sid AS uuid)
          AND tl.execution_mode = :mode
          AND tl.trade_date = :fdate
        ORDER BY tl.created_at DESC
        LIMIT :lim
    """)

    try:
        result = await session.execute(
            sql, {"sid": sid, "mode": execution_mode, "fdate": filter_date, "lim": limit}
        )
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询执行历史日志失败")
        return []

    return [
        {
            "id": str(r["id"]),
            "code": r["code"],
            "name": r["name"] or r["code"],
            "direction": r["direction"],
            "quantity": r["quantity"],
            "target_price": float(r["target_price"]) if r["target_price"] else None,
            "fill_price": float(r["fill_price"]) if r["fill_price"] else None,
            "slippage_bps": float(r["slippage_bps"]) if r["slippage_bps"] else None,
            "commission": float(r["commission"]) if r["commission"] else None,
            "stamp_tax": float(r["stamp_tax"]) if r["stamp_tax"] else None,
            "total_cost": float(r["total_cost"]) if r["total_cost"] else None,
            "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None,
            "status": "rejected" if r["reject_reason"] else ("executed" if r["executed_at"] else "pending"),
            "reject_reason": r["reject_reason"],
            "executed_at": r["executed_at"].isoformat() if r["executed_at"] else None,
        }
        for r in rows
    ]


@router.get("/algo-config")
async def get_algo_config(
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """获取当前策略执行算法配置。

    从 strategy_configs 读取最新版本的 config JSON，
    返回执行相关的算法参数。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。

    Returns:
        算法配置字典，含 execution_mode/slippage_model/order_type/
        top_n/rebalance_freq/turnover_cap 等。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        SELECT sc.config, sc.version, sc.created_at, s.name AS strategy_name
        FROM strategy_configs sc
        JOIN strategy s ON s.id = sc.strategy_id
        WHERE sc.strategy_id = CAST(:sid AS uuid)
        ORDER BY sc.version DESC
        LIMIT 1
    """)

    try:
        result = await session.execute(sql, {"sid": sid})
        row = result.mappings().first()
    except Exception:
        logger.exception("查询算法配置失败")
        row = None

    if not row:
        return _default_algo_config()

    cfg = row["config"] or {}
    return {
        "strategy_name": row["strategy_name"],
        "version": row["version"],
        "updated_at": row["created_at"].isoformat() if row["created_at"] else None,
        "execution_mode": cfg.get("execution_mode", "paper"),
        "slippage_model": cfg.get("slippage_model", "fixed_bps"),
        "slippage_bps": cfg.get("slippage_bps", 10),
        "order_type": cfg.get("order_type", "market_open"),
        "top_n": cfg.get("top_n", 15),
        "rebalance_freq": cfg.get("rebalance_freq", "monthly"),
        "turnover_cap": cfg.get("turnover_cap", 0.5),
        "cash_buffer": cfg.get("cash_buffer", 0.03),
        "max_single_weight": cfg.get("max_single_weight", 0.1),
        "max_industry_weight": cfg.get("max_industry_weight", 0.25),
    }


def _default_algo_config() -> dict[str, Any]:
    """返回v1.1默认算法配置（strategy_configs无记录时使用）。"""
    return {
        "strategy_name": "v1.1",
        "version": 1,
        "updated_at": None,
        "execution_mode": "paper",
        "slippage_model": "fixed_bps",
        "slippage_bps": 10,
        "order_type": "market_open",
        "top_n": 15,
        "rebalance_freq": "monthly",
        "turnover_cap": 0.5,
        "cash_buffer": 0.03,
        "max_single_weight": 0.10,
        "max_industry_weight": 0.25,
    }
