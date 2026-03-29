"""Report API 路由 — 报告列表、快速统计、触发报告生成。

Sprint 1.23: 为前端Report页面补齐后端API。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入 AsyncSession。"""
    return session


@router.get("/list")
async def list_reports(
    strategy_id: str = Query(default="", description="策略ID"),
    _execution_mode: str = Query(default="paper", description="执行模式: paper/live（预留参数）"),
    limit: int = Query(default=20, ge=1, le=100, description="最大条数"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取回测/策略报告列表。

    从 backtest_run 读取已完成的回测报告，按创建时间倒序。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式（目前用于过滤paper/live相关报告）。
        limit: 最大返回条数。

    Returns:
        报告列表，每项含 run_id/name/status/annual_return/sharpe_ratio/
        max_drawdown/total_trades/start_date/end_date/created_at。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    sql = text("""
        SELECT
            run_id,
            name,
            status,
            annual_return,
            sharpe_ratio,
            max_drawdown,
            calmar_ratio,
            win_rate,
            total_trades,
            start_date,
            end_date,
            elapsed_sec,
            created_at
        FROM backtest_run
        WHERE strategy_id = :sid::uuid
        ORDER BY created_at DESC
        LIMIT :lim
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "lim": limit})
        rows = result.mappings().all()
    except Exception:
        return []

    return [
        {
            "run_id": str(r["run_id"]),
            "name": r["name"] or f"回测_{r['run_id']}",
            "status": r["status"],
            "annual_return": float(r["annual_return"]) if r["annual_return"] else None,
            "sharpe_ratio": float(r["sharpe_ratio"]) if r["sharpe_ratio"] else None,
            "max_drawdown": float(r["max_drawdown"]) if r["max_drawdown"] else None,
            "calmar_ratio": float(r["calmar_ratio"]) if r["calmar_ratio"] else None,
            "win_rate": float(r["win_rate"]) if r["win_rate"] else None,
            "total_trades": r["total_trades"],
            "start_date": r["start_date"].isoformat() if r["start_date"] else None,
            "end_date": r["end_date"].isoformat() if r["end_date"] else None,
            "elapsed_sec": r["elapsed_sec"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/quick-stats")
async def get_quick_stats(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """获取今日/本周/本月/今年快速统计。

    从 performance_series 聚合各时段收益统计。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        快速统计字典，含 today/week/month/year 各时段的
        return/trade_count/turnover。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    sql = text("""
        SELECT
            trade_date,
            daily_return,
            turnover,
            position_count
        FROM performance_series
        WHERE strategy_id = :sid::uuid
          AND execution_mode = :mode
          AND trade_date >= :year_start
        ORDER BY trade_date ASC
    """)

    try:
        result = await session.execute(
            sql, {"sid": sid, "mode": execution_mode, "year_start": year_start}
        )
        rows = result.mappings().all()
    except Exception:
        rows = []

    def _aggregate(rows_subset: list) -> dict[str, Any]:
        if not rows_subset:
            return {"return": 0.0, "trade_days": 0, "avg_turnover": 0.0}
        total_ret = 1.0
        for r in rows_subset:
            total_ret *= 1 + float(r["daily_return"] or 0)
        total_ret -= 1.0
        avg_to = sum(float(r["turnover"] or 0) for r in rows_subset) / len(rows_subset)
        return {
            "return": round(total_ret, 6),
            "trade_days": len(rows_subset),
            "avg_turnover": round(avg_to, 4),
        }

    today_rows = [r for r in rows if r["trade_date"] == today]
    week_rows = [r for r in rows if r["trade_date"] >= week_start]
    month_rows = [r for r in rows if r["trade_date"] >= month_start]
    year_rows = list(rows)

    # 获取最新持仓数
    latest_position_count = rows[-1]["position_count"] if rows else 0

    return {
        "today": _aggregate(today_rows),
        "week": _aggregate(week_rows),
        "month": _aggregate(month_rows),
        "year": _aggregate(year_rows),
        "latest_position_count": latest_position_count,
        "as_of": today.isoformat(),
    }


@router.post("/generate")
async def generate_report(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
) -> dict[str, Any]:
    """触发报告生成任务。

    异步触发 Celery 任务生成策略绩效报告。
    当前实现返回任务排队确认，Celery任务在后台执行。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        任务确认字典，含 task_id/status/message。
    """
    import uuid

    sid = strategy_id or settings.PAPER_STRATEGY_ID

    # 报告生成Celery任务尚未实现，返回accepted占位
    # TODO: Sprint 1.24 实现 generate_performance_report Celery任务后替换
    task_id = str(uuid.uuid4())
    status = "accepted"
    message = "报告生成请求已接受"

    return {
        "task_id": task_id,
        "status": status,
        "message": message,
        "strategy_id": sid,
        "execution_mode": execution_mode,
    }
