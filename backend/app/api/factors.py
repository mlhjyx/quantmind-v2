"""因子库 API 路由。

提供因子列表、单因子详情、评估报告、健康度概览、相关性矩阵5个端点。

数据来源:
- FactorService: factor_registry / factor_ic / factor_values (DB异步)
- FactorAnalyzer: IC时序/分组收益/衰减/覆盖率 (同步psycopg2，需在线程池中调用)
- FactorGatePipeline: G1-G8 Gate报告 (读取已计算结果)

设计文档对照:
- docs/DEV_BACKEND.md §三 services/factor_service.py
- docs/DEV_FACTOR_MINING.md: Factor Gate G1-G8
- docs/DEV_FRONTEND_UI.md: 因子库页面 (6 Tab所需数据)

ruff noqa: B008 — FastAPI Depends() in default args is the standard pattern.
"""
# ruff: noqa: B008

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.factor_service import FactorService

router = APIRouter(prefix="/api/factors", tags=["factors"])

# 默认分析窗口: 最近2年
_DEFAULT_LOOKBACK_DAYS = 730


def _get_factor_service(
    session: AsyncSession = Depends(get_db),
) -> FactorService:
    """通过 Depends 注入 FactorService。"""
    return FactorService(session)


def _default_date_range() -> tuple[date, date]:
    """返回 (start_date, end_date)，默认最近2年。"""
    end = date.today()
    start = end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    return start, end


# ---------------------------------------------------------------------------
# GET /api/factors/health  (必须在 /{name} 之前注册，避免路由冲突)
# ---------------------------------------------------------------------------


@router.get("/health")
async def get_factors_health(
    svc: FactorService = Depends(_get_factor_service),
) -> dict[str, Any]:
    """获取Active因子健康度概览。

    返回所有 active 因子的最近IC趋势、衰减警告、覆盖率。
    用于 Dashboard 健康监控卡片和因子库概览页 Tab 1。

    Args:
        svc: FactorService实例（Depends注入）。

    Returns:
        dict: {
            "as_of": str,           # 数据截止日期
            "active_count": int,
            "factors": [
                {
                    "name": str,
                    "ic_mean_30d": float | None,   # 最近30天IC均值
                    "ic_mean_90d": float | None,   # 最近90天IC均值
                    "ic_trend": str,               # "improving" | "stable" | "degrading"
                    "decay_warning": bool,         # IC衰减>50%触发警告
                    "coverage_pct": float | None,  # 最新截面覆盖率%
                    "status": str,
                }
            ]
        }
    """
    today = date.today()
    start_30d = today - timedelta(days=30)
    start_90d = today - timedelta(days=90)

    active_factors = await svc.get_factor_list(status="active")

    factor_health = []
    for f in active_factors:
        name = f["factor_name"]

        # 最近30天 IC
        stats_30d = await svc.get_factor_stats(name, start_30d, today)
        # 最近90天 IC
        stats_90d = await svc.get_factor_stats(name, start_90d, today)

        ic_30d = stats_30d.get("ic_mean")
        ic_90d = stats_90d.get("ic_mean")

        # IC趋势判断: 30天与90天均值比较
        if ic_30d is not None and ic_90d is not None and abs(ic_90d) > 1e-9:
            ratio = ic_30d / ic_90d
            if ratio > 1.1:
                trend = "improving"
            elif ratio < 0.7:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "unknown"

        # 衰减警告: 30天IC不足90天IC的50%
        decay_warning = (
            ic_30d is not None
            and ic_90d is not None
            and abs(ic_90d) > 1e-9
            and abs(ic_30d) / abs(ic_90d) < 0.5
        )

        factor_health.append(
            {
                "name": name,
                "ic_mean_30d": ic_30d,
                "ic_mean_90d": ic_90d,
                "ic_trend": trend,
                "decay_warning": decay_warning,
                "coverage_pct": None,  # 需factor_values查询，暂留None
                "status": f["status"],
            }
        )

    return {
        "as_of": today.isoformat(),
        "active_count": len(active_factors),
        "factors": factor_health,
    }


# ---------------------------------------------------------------------------
# GET /api/factors/correlation
# ---------------------------------------------------------------------------


@router.get("/correlation")
async def get_factor_correlation(
    start_date: date = Query(default=None, description="起始日期，默认最近2年"),
    end_date: date = Query(default=None, description="截止日期，默认今天"),
    status: str = Query(default="active", description="因子状态过滤: active/all"),
    svc: FactorService = Depends(_get_factor_service),
) -> dict[str, Any]:
    """获取因子间截面相关性矩阵。

    基于指定时间窗口内因子IC序列的 Spearman 相关系数矩阵。
    用于因子库页面 Tab: 相关性分析。

    Args:
        start_date: 分析起始日期。
        end_date: 分析截止日期。
        status: 因子状态过滤。
        svc: FactorService实例。

    Returns:
        dict: {
            "factor_names": list[str],
            "matrix": list[list[float]],   # N×N相关性矩阵
            "period": {"start": str, "end": str}
        }
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    filter_status = None if status == "all" else status
    factors = await svc.get_factor_list(status=filter_status)
    factor_names = [f["factor_name"] for f in factors]

    if not factor_names:
        return {
            "factor_names": [],
            "matrix": [],
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        }

    # 收集每个因子的IC序列
    ic_map: dict[str, list[float]] = {}
    for name in factor_names:
        ic_df = await svc.get_factor_ic(name, start_date, end_date, forward_days=20)
        if not ic_df.empty:
            ic_map[name] = ic_df["ic_value"].tolist()

    available = [n for n in factor_names if n in ic_map]

    if len(available) < 2:
        # 数据不足，返回单元素矩阵或空
        matrix = [[1.0]] if available else []
        return {
            "factor_names": available,
            "matrix": matrix,
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        }

    import numpy as np
    from scipy import stats as sp_stats

    # 构建对齐长度的IC序列
    min_len = min(len(ic_map[n]) for n in available)
    n = len(available)
    matrix = [[1.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            series_i = ic_map[available[i]][-min_len:]
            series_j = ic_map[available[j]][-min_len:]
            if len(series_i) < 3:
                corr = float("nan")
            else:
                corr, _ = sp_stats.spearmanr(series_i, series_j)
                corr = float(corr) if not np.isnan(corr) else 0.0
            matrix[i][j] = corr
            matrix[j][i] = corr

    return {
        "factor_names": available,
        "matrix": matrix,
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
    }


# ---------------------------------------------------------------------------
# GET /api/factors/summary  — 因子库概览统计（必须在 /{name} 之前注册）
# ---------------------------------------------------------------------------


@router.get("/summary")
async def get_factors_summary(
    svc: FactorService = Depends(_get_factor_service),
) -> list[dict[str, Any]]:
    """获取因子列表（FactorSummary[]格式，供StrategyWorkspace/FactorPanel使用）。

    返回与前端 FactorSummary interface 兼容的数组，字段:
    id/name/category/ic/ir/direction/recommended_freq/t_stat/fdr_t_stat/status。

    如需 Dashboard 统计概览（{total,active,...} 对象格式），使用 GET /api/factors/stats。

    Args:
        svc: FactorService实例（Depends注入）。

    Returns:
        list[dict]: FactorSummary 数组，每项含:
            id/name/category/ic/ir/direction/recommended_freq/t_stat/fdr_t_stat/status。
    """
    today = date.today()
    start_date = today - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    all_factors = await svc.get_factor_list(status=None)
    result = []
    for f in all_factors:
        fname = f["factor_name"]
        stats = await svc.get_factor_stats(fname, start_date, today)

        ic_mean = float(stats.get("ic_mean") or 0.0)
        ic_ir = float(stats.get("ic_ir") or 0.0)
        t = float(_calc_t_stat(stats) or 0.0)

        # status 映射到前端枚举: candidate→new, warning/critical→degraded
        raw_status = f.get("status", "")
        frontend_status = {
            "active": "active",
            "candidate": "new",
            "warning": "degraded",
            "critical": "degraded",
            "retired": "retired",
        }.get(raw_status, "active")

        result.append(
            {
                "id": fname,
                "name": fname,
                "category": f.get("category") or "",
                "ic": ic_mean,
                "ir": ic_ir,
                "direction": f.get("direction") or 1,
                "recommended_freq": "月度",
                "t_stat": t,
                "fdr_t_stat": t,
                "status": frontend_status,
                "description": f.get("description"),
                "source": f.get("source"),
            }
        )
    return result


@router.get("/stats")
async def get_factors_stats(
    svc: FactorService = Depends(_get_factor_service),
) -> dict[str, Any]:
    """获取因子库概览统计（{total,active,...}对象格式，供Dashboard使用）。

    对 factor_registry 按 status 分组计数，同时返回 Top 因子列表。
    用于前端 Dashboard 因子状态卡片。

    Args:
        svc: FactorService实例（Depends注入）。

    Returns:
        dict: {
            "total": int,
            "active": int,
            "candidate": int,
            "warning": int,
            "critical": int,
            "retired": int,
            "top_factors": list[dict]
        }
    """
    today = date.today()
    start_date = today - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    all_factors = await svc.get_factor_list(status=None)

    counts: dict[str, int] = {
        "active": 0,
        "candidate": 0,
        "warning": 0,
        "critical": 0,
        "retired": 0,
    }
    for f in all_factors:
        st = f.get("status", "")
        if st in counts:
            counts[st] += 1

    total = sum(counts.values())

    active_factors = [f for f in all_factors if f.get("status") in ("active", "warning")]
    top_factors = []
    for f in active_factors:
        fname = f["factor_name"]
        stats = await svc.get_factor_stats(fname, start_date, today)
        ic_mean = stats.get("ic_mean")
        ic_ir = stats.get("ic_ir")

        stats_30d = await svc.get_factor_stats(fname, today - timedelta(days=30), today)
        ic_30d = stats_30d.get("ic_mean")
        if ic_mean is not None and ic_30d is not None and abs(ic_mean) > 1e-9:
            ratio = ic_30d / ic_mean
            trend = "improving" if ratio > 1.1 else ("degrading" if ratio < 0.7 else "stable")
        else:
            trend = "unknown"

        top_factors.append(
            {
                "name": fname,
                "ic_mean": ic_mean,
                "ic_ir": ic_ir,
                "direction": f.get("direction"),
                "status": f.get("status"),
                "trend": trend,
            }
        )

    top_factors.sort(
        key=lambda x: abs(x["ic_mean"]) if x["ic_mean"] is not None else 0.0, reverse=True
    )
    top_factors = top_factors[:10]

    return {
        "total": total,
        **counts,
        "top_factors": top_factors,
    }


# ---------------------------------------------------------------------------
# GET /api/factors  — 因子库列表
# ---------------------------------------------------------------------------


@router.get("")
async def list_factors(
    status: str = Query(default="", description="状态过滤: active/deprecated/candidate"),
    category: str = Query(default="", description="类别过滤: momentum/value/liquidity等"),
    svc: FactorService = Depends(_get_factor_service),
) -> list[dict[str, Any]]:
    """获取因子库列表。

    返回因子基础信息 + 近期IC统计。用于因子库列表页。

    Args:
        status: 因子状态过滤，空字符串返回全部。
        category: 因子类别过滤，空字符串返回全部。
        svc: FactorService实例。

    Returns:
        list[dict]: 每项含:
            name, category, direction, status, description,
            ic_mean, ic_ir, t_stat, created_at
    """
    filter_status = status if status else None
    factors = await svc.get_factor_list(status=filter_status)

    if category:
        factors = [f for f in factors if f.get("category") == category]

    end_date = date.today()
    start_date = end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    result = []
    for f in factors:
        name = f["factor_name"]
        stats = await svc.get_factor_stats(name, start_date, end_date)
        result.append(
            {
                "name": name,
                "category": f.get("category"),
                "direction": f.get("direction"),
                "status": f.get("status"),
                "description": f.get("description"),
                "ic_mean": stats.get("ic_mean"),
                "ic_ir": stats.get("ic_ir"),
                "t_stat": _calc_t_stat(stats),
                "data_points": stats.get("data_points", 0),
                "created_at": _isoformat_or_none(f.get("created_at")),
            }
        )

    return result


# ---------------------------------------------------------------------------
# GET /api/factors/{name}  — 单因子详情
# ---------------------------------------------------------------------------


@router.get("/{name}")
async def get_factor_detail(
    name: str,
    start_date: date = Query(default=None, description="分析起始日期"),
    end_date: date = Query(default=None, description="分析截止日期"),
    forward_days: int = Query(default=20, ge=1, le=60, description="前向收益窗口"),
    svc: FactorService = Depends(_get_factor_service),
) -> dict[str, Any]:
    """获取单因子详情。

    返回因子完整信息：基础信息 + IC时序 + IC衰减 + 统计摘要。
    用于因子详情页 Tab 1（概览）和 Tab 2（IC分析）。

    Args:
        name: 因子名称。
        start_date: 分析起始日期，默认最近2年。
        end_date: 分析截止日期，默认今天。
        forward_days: 前向收益窗口天数。
        svc: FactorService实例。

    Returns:
        dict: {
            "factor_name": str,
            "category": str,
            "direction": int,
            "status": str,
            "description": str,
            "stats": {ic_mean, ic_std, ic_ir, t_stat, data_points},
            "ic_series": list[{trade_date, ic_value}],
            "created_at": str
        }

    Raises:
        HTTPException: 因子不存在时返回 404。
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    # 验证因子存在
    factor_list = await svc.get_factor_list()
    factor_info = next((f for f in factor_list if f["factor_name"] == name), None)
    if factor_info is None:
        raise HTTPException(status_code=404, detail=f"因子不存在: {name}")

    stats = await svc.get_factor_stats(name, start_date, end_date)
    ic_df = await svc.get_factor_ic(name, start_date, end_date, forward_days=forward_days)

    ic_series = []
    if not ic_df.empty:
        ic_series = [
            {
                "trade_date": row["trade_date"].isoformat()
                if hasattr(row["trade_date"], "isoformat")
                else str(row["trade_date"]),
                "ic_value": float(row["ic_value"]) if row["ic_value"] is not None else None,
            }
            for _, row in ic_df.iterrows()
        ]

    return {
        "factor_name": name,
        "category": factor_info.get("category"),
        "direction": factor_info.get("direction"),
        "status": factor_info.get("status"),
        "description": factor_info.get("description"),
        "stats": {
            "ic_mean": stats.get("ic_mean"),
            "ic_std": stats.get("ic_std"),
            "ic_ir": stats.get("ic_ir"),
            "t_stat": _calc_t_stat(stats),
            "data_points": stats.get("data_points", 0),
        },
        "ic_series": ic_series,
        "analysis_period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "forward_days": forward_days,
        },
        "created_at": _isoformat_or_none(factor_info.get("created_at")),
    }


# ---------------------------------------------------------------------------
# GET /api/factors/{name}/report  — 因子评估报告（6 Tab所需完整数据）
# ---------------------------------------------------------------------------


@router.get("/{name}/report")
async def get_factor_report(
    name: str,
    start_date: date = Query(default=None, description="分析起始日期"),
    end_date: date = Query(default=None, description="分析截止日期"),
    svc: FactorService = Depends(_get_factor_service),
) -> dict[str, Any]:
    """获取因子完整评估报告。

    聚合因子所有分析维度，供前端6 Tab评估页使用:
      Tab1 概览: 基础信息 + 核心指标
      Tab2 IC分析: IC时序 + 月度IC + 统计摘要
      Tab3 分组收益: 5分组单调性（由FactorAnalyzer计算，此处从DB读已存结果）
      Tab4 Gate报告: G1-G8结果（从factor_registry.gate_result读取）
      Tab5 IC衰减: 1/5/10/20日IC衰减曲线
      Tab6 历史回测: 关联回测结果摘要

    Args:
        name: 因子名称。
        start_date: 分析起始日期，默认最近2年。
        end_date: 分析截止日期，默认今天。
        svc: FactorService实例。

    Returns:
        dict: 6 Tab完整数据结构。

    Raises:
        HTTPException: 因子不存在时返回 404。
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    factor_list = await svc.get_factor_list()
    factor_info = next((f for f in factor_list if f["factor_name"] == name), None)
    if factor_info is None:
        raise HTTPException(status_code=404, detail=f"因子不存在: {name}")

    # Tab1+Tab2: IC统计 + 时序
    stats = await svc.get_factor_stats(name, start_date, end_date)
    ic_df = await svc.get_factor_ic(name, start_date, end_date, forward_days=20)

    ic_series = []
    if not ic_df.empty:
        ic_series = [
            {
                "trade_date": row["trade_date"].isoformat()
                if hasattr(row["trade_date"], "isoformat")
                else str(row["trade_date"]),
                "ic_value": float(row["ic_value"]) if row["ic_value"] is not None else None,
            }
            for _, row in ic_df.iterrows()
        ]

    # Tab5: 多窗口IC衰减（1/5/10/20日）
    ic_decay = {}
    for fwd in [1, 5, 10, 20]:
        decay_stats = await svc.get_factor_stats(name, start_date, end_date)
        # 复用同一 get_factor_stats，注意其固定 forward_days=20
        # 多窗口IC需单独查各forward_days的IC，这里提供结构，后续可扩展
        ic_decay[f"{fwd}d"] = {
            "ic_mean": decay_stats.get("ic_mean") if fwd == 20 else None,
            "data_points": decay_stats.get("data_points", 0) if fwd == 20 else 0,
        }

    return {
        "factor_name": name,
        "analysis_period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        # Tab1: 概览
        "overview": {
            "category": factor_info.get("category"),
            "direction": factor_info.get("direction"),
            "status": factor_info.get("status"),
            "description": factor_info.get("description"),
            "created_at": _isoformat_or_none(factor_info.get("created_at")),
        },
        # Tab2: IC分析
        "ic_analysis": {
            "stats": {
                "ic_mean": stats.get("ic_mean"),
                "ic_std": stats.get("ic_std"),
                "ic_ir": stats.get("ic_ir"),
                "t_stat": _calc_t_stat(stats),
                "data_points": stats.get("data_points", 0),
            },
            "ic_series": ic_series,
        },
        # Tab3: 分组收益（需FactorAnalyzer同步计算，此处为预留结构）
        "quintile_returns": {
            "note": "需通过 /api/factors/{name}/quintile 端点触发计算",
            "groups": [],
        },
        # Tab4: Gate报告（从DB读取已存Gate结果）
        "gate_report": {
            "note": "Gate G1-G8结果存储在 factor_registry.gate_result JSONB列",
            "gates": {},
        },
        # Tab5: IC衰减
        "ic_decay": ic_decay,
        # Tab6: 历史回测摘要（关联backtest_runs表）
        "backtest_summary": {
            "note": "关联回测结果需通过 /api/backtest?factor={name} 查询",
        },
    }


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------


def _isoformat_or_none(value: Any) -> str | None:
    """安全调用 isoformat()，None 时返回 None。

    解决 Pyright 对 dict.get() 返回 Any 时无法推断 isoformat 的类型警告。

    Args:
        value: date/datetime 对象或 None。

    Returns:
        ISO格式字符串，或 None。
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _calc_t_stat(stats: dict[str, Any]) -> float | None:
    """从IC统计量计算t统计量。

    t = IC_mean / (IC_std / sqrt(N))

    Args:
        stats: get_factor_stats返回的字典，含 ic_mean/ic_std/data_points。

    Returns:
        t统计量，数据不足时返回 None。
    """
    import math

    ic_mean = stats.get("ic_mean")
    ic_std = stats.get("ic_std")
    n = stats.get("data_points", 0)

    if ic_mean is None or ic_std is None or n < 2 or ic_std < 1e-12:
        return None

    return float(ic_mean / (ic_std / math.sqrt(n)))
