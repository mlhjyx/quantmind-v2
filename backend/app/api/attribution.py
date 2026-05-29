"""归因 API 路由 (iter 147 W2-F F6 closure).

提供 daily_attribution 表的查询接口 (read-only). Attribution 引擎在
`backend/qm_platform/eval/attribution.py` (持久化 via persist_attribution).

端点列表:
  GET  /api/attribution/latest          — 最新一行 attribution (单 strategy + execution_mode)
  GET  /api/attribution/history         — 近 N 天 attribution 时间序列

设计文档:
  - docs/mvp/MVP_4_2_attribution.md (DailyAttribution dataclass spec)
  - backend/qm_platform/eval/attribution.py:54 (DailyAttribution frozen dataclass)
  - backend/migrations/daily_attribution.sql (iter 146 applied 2026-05-26)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/attribution", tags=["attribution"])


# ---------------------------------------------------------------------------
# Depends
# ---------------------------------------------------------------------------


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    return session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    """daily_attribution row → JSON serializable dict."""
    return {
        "id": row["id"],
        "trade_date": row["trade_date"].isoformat() if row["trade_date"] else None,
        "strategy_id": row["strategy_id"],
        "execution_mode": row["execution_mode"],
        "nav_change_pct": float(row["nav_change_pct"])
        if row["nav_change_pct"] is not None
        else 0.0,
        "nav_change_bps": float(row["nav_change_pct"]) * 10000.0
        if row["nav_change_pct"] is not None
        else 0.0,
        "by_factor": row["by_factor_json"] or {},
        "by_sector": row["by_sector_json"] or {},
        "by_regime": row["by_regime_json"],  # nullable
        "by_cost": row["by_cost_json"] or {},
        "alpha_vs_benchmark": float(row["alpha_vs_benchmark"])
        if row["alpha_vs_benchmark"] is not None
        else 0.0,
        "alpha_vs_benchmark_bps": float(row["alpha_vs_benchmark"]) * 10000.0
        if row["alpha_vs_benchmark"] is not None
        else 0.0,
        "unexplained_residual": float(row["unexplained_residual"])
        if row["unexplained_residual"] is not None
        else 0.0,
        "unexplained_residual_bps": float(row["unexplained_residual"]) * 10000.0
        if row["unexplained_residual"] is not None
        else 0.0,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ---------------------------------------------------------------------------
# GET /api/attribution/latest
# ---------------------------------------------------------------------------


@router.get("/latest")
async def get_latest_attribution(
    strategy_id: str = Query(default="", description="策略ID; 空则使用 PAPER_STRATEGY_ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any] | None:
    """获取最新一行 attribution.

    Returns:
        attribution dict 或 None (当无数据时).
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        SELECT id, trade_date, strategy_id, execution_mode,
               nav_change_pct, by_factor_json, by_sector_json,
               by_regime_json, by_cost_json,
               alpha_vs_benchmark, unexplained_residual,
               created_at
        FROM daily_attribution
        WHERE strategy_id = :sid AND execution_mode = :mode
        ORDER BY trade_date DESC, id DESC
        LIMIT 1
    """)

    result = await session.execute(sql, {"sid": sid, "mode": execution_mode})
    row = result.mappings().first()
    if row is None:
        return None
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# GET /api/attribution/history
# ---------------------------------------------------------------------------


@router.get("/history")
async def get_attribution_history(
    strategy_id: str = Query(default="", description="策略ID; 空则使用 PAPER_STRATEGY_ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    days: int = Query(default=30, ge=1, le=365, description="回溯天数 (1-365)"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取近 N 天 attribution 时间序列, trade_date 降序.

    Returns:
        attribution dict 列表 (最新在前). 空 list 当无数据.
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        SELECT id, trade_date, strategy_id, execution_mode,
               nav_change_pct, by_factor_json, by_sector_json,
               by_regime_json, by_cost_json,
               alpha_vs_benchmark, unexplained_residual,
               created_at
        FROM daily_attribution
        WHERE strategy_id = :sid AND execution_mode = :mode
          AND trade_date >= (CURRENT_DATE - CAST(:days AS INTEGER))
        ORDER BY trade_date DESC, id DESC
    """)

    result = await session.execute(sql, {"sid": sid, "mode": execution_mode, "days": days})
    rows = result.mappings().all()
    return [_row_to_dict(r) for r in rows]
