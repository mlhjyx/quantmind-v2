"""Report API 路由 — 报告列表、快速统计、触发报告生成、获取最新报告。

Sprint 1.23: 为前端Report页面补齐后端API.
Sprint 1.24 (iter 30): /generate wired to real Celery task
  `app.tasks.report_tasks.generate_performance_report`; added /{sid}/latest GET
  endpoint to read latest filesystem JSON artifact. Closes the line 198 TODO.
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文).
"""

import json
from datetime import date, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.tasks.report_tasks import generate_performance_report, latest_report_path

logger = structlog.get_logger(__name__)

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
        WHERE strategy_id = CAST(:sid AS uuid)
        ORDER BY created_at DESC
        LIMIT :lim
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "lim": limit})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询回测报告列表失败")
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
        WHERE strategy_id = CAST(:sid AS uuid)
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
        logger.exception("查询快速统计数据失败")
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
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    if not sid:
        raise HTTPException(
            status_code=400,
            detail="strategy_id required (no PAPER_STRATEGY_ID default configured)",
        )
    if execution_mode not in ("paper", "live"):
        raise HTTPException(
            status_code=400,
            detail=f"execution_mode must be 'paper' or 'live', got {execution_mode!r}",
        )

    # Sprint 1.24 closure (iter 30): dispatch real Celery task. Returns
    # AsyncResult.id (Celery-tracked task_id); status pollable via standard
    # celery result_backend, artifact readable via GET /{sid}/latest once task
    # finishes (~1-3s typical).
    async_result = generate_performance_report.delay(sid, execution_mode)

    return {
        "task_id": async_result.id,
        "status": "dispatched",
        "message": "报告生成任务已派发到 Celery worker; 完成后通过 GET /{strategy_id}/latest 获取",
        "strategy_id": sid,
        "execution_mode": execution_mode,
    }


@router.get("/{strategy_id}/latest")
async def get_latest_report(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
) -> dict[str, Any]:
    """获取指定策略的最新报告 (filesystem JSON artifact).

    由 POST /generate 派发的 Celery task 写入 reports/{sid}_{date}_{mode}.json.
    本端点按 (strategy_id, execution_mode) 前缀+后缀过滤 reports/ 目录, 返回
    mtime 最新的一份. 0 匹配 → 404 (caller 应先调 /generate 派发任务).

    Args:
        strategy_id: 策略 UUID 字符串. URL path 参数, 不允许空.
        execution_mode: paper / live, query 参数.

    Returns:
        报告 JSON 内容 (schema_version / summary / latest_nav / recent_trades /
        trades_count / target_date_shanghai / generated_at_utc / 等), 由
        report_tasks.generate_performance_report 写入.

    Raises:
        HTTPException 400: execution_mode 非法.
        HTTPException 404: 该 (sid, mode) 没有任何报告 artifact.
        HTTPException 500: 文件存在但 JSON 解析失败 (artifact corruption).
    """
    if execution_mode not in ("paper", "live"):
        raise HTTPException(
            status_code=400,
            detail=f"execution_mode must be 'paper' or 'live', got {execution_mode!r}",
        )

    path = latest_report_path(strategy_id, execution_mode)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no report artifact found for strategy_id={strategy_id} "
                f"execution_mode={execution_mode}; dispatch one via "
                f"POST /api/reports/generate first"
            ),
        )

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.exception("读取最新报告 artifact 失败 path=%s", path)
        raise HTTPException(
            status_code=500,
            detail=f"report artifact unreadable: {type(e).__name__}: {e}",
        ) from e

    payload["_artifact_path"] = str(path)
    return payload
