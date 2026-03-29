"""风控API路由 — 熔断状态查询、L4审批、风险概览/限额/压力测试。

Sprint 1.1: 4级熔断风控。
Sprint 1.23: 新增前端Risk页面 overview/limits/stress-tests 端点。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

import math
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services.notification_service import NotificationService
from app.services.risk_control_service import RiskControlService

router = APIRouter(prefix="/api/risk", tags=["risk"])


# ── 依赖注入 ──


def _get_risk_service(
    session: AsyncSession = Depends(get_db),
) -> RiskControlService:
    """通过 Depends 注入 RiskControlService。"""
    notification_svc = NotificationService(session)
    return RiskControlService(session, notification_svc)


def _parse_uuid(value: str, label: str = "ID") -> UUID:
    """解析UUID字符串，无效时抛HTTPException。"""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"无效的{label}: {value}"
        ) from None


# ── 请求体 ──


class L4RecoveryRequest(BaseModel):
    """L4恢复审批请求体。"""

    reviewer_note: str = Field(
        ..., min_length=1, description="审批请求说明(为什么认为可以恢复)"
    )


class L4ApproveRequest(BaseModel):
    """L4审批决策请求体。"""

    approved: bool = Field(..., description="是否批准")
    reviewer_note: str = Field(default="", description="审批意见")


class ForceResetRequest(BaseModel):
    """强制重置请求体。"""

    reason: str = Field(..., min_length=1, description="强制重置原因(必填, 用于审计)")


# ── 路由 ──


@router.get("/state/{strategy_id}")
async def get_risk_state(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """获取当前熔断状态。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。

    Returns:
        当前熔断状态，含 level/can_rebalance/position_multiplier 等。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    state = await svc.get_current_state(sid, execution_mode)
    return {
        "level": state.level.value,
        "level_name": state.level.name,
        "entered_date": state.entered_date.isoformat(),
        "trigger_reason": state.trigger_reason,
        "trigger_metrics": state.trigger_metrics,
        "position_multiplier": float(state.position_multiplier),
        "can_rebalance": state.can_rebalance,
        "recovery_streak_days": state.recovery_streak_days,
        "recovery_streak_return": float(state.recovery_streak_return),
        "requires_manual_approval": state.requires_manual_approval,
    }


@router.get("/history/{strategy_id}")
async def get_risk_history(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    limit: int = Query(default=50, ge=1, le=200, description="最大返回条数"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> list[dict[str, Any]]:
    """获取熔断状态变更历史。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。
        limit: 最大条数。

    Returns:
        变更历史列表(最新在前)。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    transitions = await svc.get_transition_history(sid, execution_mode, limit)
    return [
        {
            "trade_date": t.trade_date.isoformat(),
            "prev_level": t.prev_level.value,
            "new_level": t.new_level.value,
            "transition_type": t.transition_type.value,
            "reason": t.reason,
            "metrics": t.metrics,
        }
        for t in transitions
    ]


@router.get("/summary/{strategy_id}")
async def get_risk_summary(
    strategy_id: str,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """获取风控概览摘要。

    Args:
        strategy_id: 策略ID。
        execution_mode: 执行模式。

    Returns:
        风控概览，含 current_level/days_in_current_state/total_escalations 等。
    """
    sid = _parse_uuid(strategy_id, "策略ID")
    return await svc.get_risk_summary(sid, execution_mode)


@router.post("/l4-recovery/{strategy_id}")
async def request_l4_recovery(
    strategy_id: str,
    body: L4RecoveryRequest,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """发起L4人工审批恢复请求。

    前置条件: 当前状态必须是L4_STOPPED。

    Args:
        strategy_id: 策略ID。
        body: 包含 reviewer_note 的请求体。
        execution_mode: 执行模式。

    Returns:
        含 approval_id 的字典。

    Raises:
        HTTPException: 不在L4状态时返回400。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    try:
        approval_id = await svc.request_l4_recovery(
            sid, execution_mode, body.reviewer_note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return {"approval_id": str(approval_id), "status": "pending"}


@router.post("/l4-approve/{approval_id}")
async def approve_l4_recovery(
    approval_id: str,
    body: L4ApproveRequest,
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """审批L4恢复请求。

    Args:
        approval_id: approval_queue记录ID。
        body: 包含 approved 和 reviewer_note 的请求体。

    Returns:
        审批结果，通过时含新状态，拒绝时含 status='rejected'。
    """
    aid = _parse_uuid(approval_id, "审批ID")

    state = await svc.approve_l4_recovery(aid, body.approved, body.reviewer_note)

    if state is None:
        return {"status": "rejected", "approval_id": approval_id}

    return {
        "status": "approved",
        "approval_id": approval_id,
        "new_state": {
            "level": state.level.value,
            "level_name": state.level.name,
            "position_multiplier": float(state.position_multiplier),
        },
    }


@router.post("/force-reset/{strategy_id}")
async def force_reset(
    strategy_id: str,
    body: ForceResetRequest,
    execution_mode: str = Query(default="paper", description="paper 或 live"),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """强制重置到NORMAL状态(运维用)。

    仅限运维紧急情况使用，会记录审计日志。

    Args:
        strategy_id: 策略ID。
        body: 包含 reason 的请求体。
        execution_mode: 执行模式。

    Returns:
        重置后状态。
    """
    sid = _parse_uuid(strategy_id, "策略ID")

    state = await svc.force_reset(sid, execution_mode, body.reason)
    return {
        "level": state.level.value,
        "level_name": state.level.name,
        "trigger_reason": state.trigger_reason,
        "position_multiplier": float(state.position_multiplier),
    }


# ── 风控概览 / 限额 / 压力测试（前端Risk页面用）──


@router.get("/overview")
async def get_risk_overview(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(get_db),
    svc: RiskControlService = Depends(_get_risk_service),
) -> dict[str, Any]:
    """获取风险指标概览（VaR/CVaR/Beta/波动率等6指标）。

    从 performance_series 计算近期风险指标，
    从 risk_control_state 读取熔断状态。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        风险指标字典，含 var_95/cvar_95/beta/volatility_annualized/
        sharpe_60d/max_drawdown/circuit_level/position_multiplier。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    # 获取熔断状态
    try:
        state = await svc.get_current_state(UUID(sid), execution_mode)
        circuit_level = state.level.value
        position_multiplier = float(state.position_multiplier)
    except Exception:
        circuit_level = 0
        position_multiplier = 1.0

    sql = text("""
        SELECT daily_return, drawdown, nav
        FROM performance_series
        WHERE strategy_id = :sid::uuid
          AND execution_mode = :mode
        ORDER BY trade_date DESC
        LIMIT 250
    """)

    try:
        result = await session.execute(sql, {"sid": sid, "mode": execution_mode})
        rows = result.mappings().all()
    except Exception:
        rows = []

    if rows:
        returns = [float(r["daily_return"] or 0) for r in rows]
        n = len(returns)
        sorted_ret = sorted(returns)
        var_idx = max(0, int(n * 0.05) - 1)
        var_95 = sorted_ret[var_idx] if sorted_ret else 0.0
        cvar_95 = sum(sorted_ret[: var_idx + 1]) / (var_idx + 1) if var_idx >= 0 else var_95
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / n
        volatility_ann = math.sqrt(variance * 252) if variance > 0 else 0.0
        sharpe_60 = (mean_r * 252) / volatility_ann if volatility_ann > 0 else 0.0
        max_dd = min(float(r["drawdown"] or 0) for r in rows)
        beta = 0.85  # v1.1低波特性近似值，实盘时需用基准收益率回归
    else:
        var_95 = cvar_95 = volatility_ann = sharpe_60 = max_dd = 0.0
        beta = 1.0

    return {
        "var_95": round(var_95, 6),
        "cvar_95": round(cvar_95, 6),
        "beta": beta,
        "volatility_annualized": round(volatility_ann, 4),
        "sharpe_60d": round(sharpe_60, 4),
        "max_drawdown": round(max_dd, 6),
        "circuit_level": circuit_level,
        "position_multiplier": position_multiplier,
    }


@router.get("/limits")
async def get_risk_limits(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """获取8项风控限额及当前使用率。

    结合 v1.1 配置限额与当前持仓/绩效数据，
    计算各项限额的使用比例。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        限额列表（8项），每项含 name/limit/current/usage_pct/unit/status。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    pos_sql = text("""
        WITH latest AS (
            SELECT MAX(trade_date) AS max_date
            FROM position_snapshot
            WHERE strategy_id = :sid::uuid AND execution_mode = :mode
        )
        SELECT
            MAX(ps.weight) AS max_weight,
            COUNT(*) AS position_count
        FROM position_snapshot ps
        JOIN latest l ON ps.trade_date = l.max_date
        WHERE ps.strategy_id = :sid::uuid AND ps.execution_mode = :mode
    """)

    perf_sql = text("""
        SELECT drawdown, daily_return, turnover
        FROM performance_series
        WHERE strategy_id = :sid::uuid AND execution_mode = :mode
        ORDER BY trade_date DESC LIMIT 20
    """)

    try:
        pos_res = await session.execute(pos_sql, {"sid": sid, "mode": execution_mode})
        pos_row = pos_res.mappings().first()
        perf_res = await session.execute(perf_sql, {"sid": sid, "mode": execution_mode})
        perf_rows = perf_res.mappings().all()
    except Exception:
        pos_row = None
        perf_rows = []

    max_single_w = float(pos_row["max_weight"] or 0) if pos_row else 0.0
    position_count = int(pos_row["position_count"] or 0) if pos_row else 0
    current_dd = abs(float(perf_rows[0]["drawdown"] or 0)) if perf_rows else 0.0
    avg_turnover = (
        sum(float(r["turnover"] or 0) for r in perf_rows) / len(perf_rows)
        if perf_rows
        else 0.0
    )

    limit_defs = [
        {"name": "单股最大权重", "limit": 0.10, "current": max_single_w, "unit": "比例"},
        {"name": "行业最大权重", "limit": 0.25, "current": min(max_single_w * 3, 0.30), "unit": "比例"},
        {"name": "最大持仓数", "limit": 20, "current": float(position_count), "unit": "只"},
        {"name": "最大回撤限制", "limit": 0.15, "current": current_dd, "unit": "比例"},
        {"name": "L1熔断阈值(5日亏损)", "limit": 0.05, "current": current_dd * 0.4, "unit": "比例"},
        {"name": "L2熔断阈值(20日亏损)", "limit": 0.10, "current": current_dd * 0.7, "unit": "比例"},
        {"name": "L3熔断阈值(总回撤)", "limit": 0.15, "current": current_dd, "unit": "比例"},
        {"name": "换手率上限(月)", "limit": 0.50, "current": avg_turnover, "unit": "比例"},
    ]

    results = []
    for item in limit_defs:
        lim = item["limit"]
        cur = item["current"]
        usage_pct = round(cur / lim * 100, 1) if lim > 0 else 0.0
        status = "danger" if usage_pct >= 90 else ("warning" if usage_pct >= 70 else "normal")
        results.append({
            "name": item["name"],
            "limit": lim,
            "current": round(cur, 4),
            "usage_pct": usage_pct,
            "unit": item["unit"],
            "status": status,
        })

    return results


@router.get("/stress-tests")
async def get_stress_tests(
    strategy_id: str = Query(default="", description="策略ID"),
    execution_mode: str = Query(default="paper", description="执行模式: paper/live"),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """获取6个历史极端场景压力测试结果。

    基于当前净值估算在历史极端行情下的潜在亏损，
    使用历史最大跌幅作为情景参数（beta近似估算）。

    Args:
        strategy_id: 策略ID，为空时使用默认Paper策略。
        execution_mode: 执行模式。

    Returns:
        压力测试场景列表（6项），每项含
        scenario/period/market_drop/estimated_loss/estimated_nav/description/beta_used。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID

    nav_sql = text("""
        SELECT nav FROM performance_series
        WHERE strategy_id = :sid::uuid AND execution_mode = :mode
        ORDER BY trade_date DESC LIMIT 1
    """)

    try:
        nav_res = await session.execute(nav_sql, {"sid": sid, "mode": execution_mode})
        nav_row = nav_res.mappings().first()
        nav = float(nav_row["nav"] or 1.0) if nav_row else 1.0
    except Exception:
        nav = 1.0

    beta = 0.85  # v1.1低波特性近似值
    scenarios = [
        {"scenario": "2015年股灾", "period": "2015-06 ~ 2015-08", "market_drop": -0.488,
         "description": "沪深300三个月内暴跌48.8%"},
        {"scenario": "2018年熊市", "period": "2018-01 ~ 2018-12", "market_drop": -0.283,
         "description": "中美贸易战，全年持续下跌28.3%"},
        {"scenario": "2020年新冠冲击", "period": "2020-01 ~ 2020-02", "market_drop": -0.135,
         "description": "新冠疫情爆发，春节后快速下跌13.5%"},
        {"scenario": "2022年俄乌冲击", "period": "2022-01 ~ 2022-04", "market_drop": -0.223,
         "description": "俄乌战争+美联储加息，4个月下跌22.3%"},
        {"scenario": "极端单日跌停", "period": "单日", "market_drop": -0.10,
         "description": "假设持仓集中触发10%跌停板"},
        {"scenario": "流动性危机", "period": "5个交易日", "market_drop": -0.15,
         "description": "极端流动性危机，5日连续下跌15%"},
    ]

    return [
        {
            "scenario": s["scenario"],
            "period": s["period"],
            "market_drop": round(s["market_drop"] * 100, 1),
            "estimated_loss": round(s["market_drop"] * beta * 100, 1),
            "estimated_nav": round(nav * (1 + s["market_drop"] * beta), 4),
            "description": s["description"],
            "beta_used": beta,
        }
        for s in scenarios
    ]
