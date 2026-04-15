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

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.factor_service import FactorService

logger = structlog.get_logger(__name__)

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
    try:
        factors = await svc.get_factor_list(status=filter_status)
    except Exception as exc:
        err_msg = str(exc).lower()
        if "does not exist" in err_msg or "relation" in err_msg:
            logger.warning("factor_registry表可能不存在: %s", err_msg[:200])
            factors = []
        else:
            raise
    factor_names = [f["factor_name"] for f in factors]

    if not factor_names:
        return {
            "factor_names": [],
            "matrix": [],
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        }

    # 收集每个因子的IC序列（过滤None/NaN，转float避免Decimal问题）
    ic_map: dict[str, list[float]] = {}
    for name in factor_names:
        ic_df = await svc.get_factor_ic(name, start_date, end_date, forward_days=20)
        if not ic_df.empty:
            values = [
                float(v) for v in ic_df["ic_value"].tolist()
                if v is not None
            ]
            if values:
                ic_map[name] = values

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
        t = _calc_t_stat(stats)
        ic_mean = stats.get("ic_mean") or 0
        ic_ir = stats.get("ic_ir") or 0
        data_pts = stats.get("data_points", 0)

        # FDR t-stat: 用BH校正后的等效t值
        # 简化: fdr_t = t_stat（原始值，前端对比BH阈值判断显著性）
        fdr_t = t

        # Gate得分: 简化版8项Gate评估（百分制）
        gates_passed = 0
        gates_total = 5
        if t and abs(t) > 2.5:
            gates_passed += 1  # G1: |t| > 2.5
        if ic_ir and ic_ir > 0.5:
            gates_passed += 1  # G2: IC_IR > 0.5
        if ic_mean and abs(ic_mean) > 0.02:
            gates_passed += 1  # G3: |IC| > 2%
        if data_pts and data_pts >= 120:
            gates_passed += 1  # G4: 数据点 >= 120（半年）
        if f.get("status") == "active":
            gates_passed += 1  # G5: 已激活状态
        gate = round(gates_passed / gates_total * 100, 1)

        result.append(
            {
                "name": name,
                "category": f.get("category"),
                "direction": f.get("direction"),
                "status": f.get("status"),
                "description": f.get("description"),
                "ic_mean": ic_mean,
                "ic_ir": ic_ir,
                "t_stat": t,
                "fdr_t_stat": fdr_t,
                "gate_score": gate,
                "data_points": data_pts,
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
    # 尝试从 factor_ic_history 读取多周期IC
    ic_decay = {}
    for fwd in [1, 5, 10, 20]:
        try:
            fwd_df = await svc.get_factor_ic(name, start_date, end_date, forward_days=fwd)
            if not fwd_df.empty:
                valid = [
                    float(v) for v in fwd_df["ic_value"].tolist() if v is not None
                ]
                if valid:
                    fwd_mean = sum(valid) / len(valid)
                    fwd_std = (sum((x - fwd_mean) ** 2 for x in valid) / max(len(valid) - 1, 1)) ** 0.5
                    ic_decay[f"{fwd}d"] = {
                        "ic_mean": fwd_mean,
                        "ic_std": fwd_std,
                        "ic_ir": fwd_mean / fwd_std if fwd_std > 1e-12 else 0,
                        "data_points": len(valid),
                    }
                    continue
        except Exception as e:
            # S3 F81 修复: IC decay 计算失败记录可追溯
            logger.warning(
                "[factors] ic_decay fwd=%s 计算失败 factor=%s err=%s",
                fwd, name, e, exc_info=True,
            )
        ic_decay[f"{fwd}d"] = {"ic_mean": None, "ic_std": None, "ic_ir": None, "data_points": 0}

    # 计算高级指标
    t_stat = _calc_t_stat(stats)
    ic_values = [
        float(row["ic_value"])
        for _, row in ic_df.iterrows()
        if row["ic_value"] is not None
    ] if not ic_df.empty else []

    fdr_t = _calc_fdr_t_stat(t_stat, m_tests=69)
    nw_t = _calc_newey_west_t(ic_values)
    half_life = _calc_ic_half_life(ic_values)
    rec_freq = _recommend_rebalance_freq(ic_decay)

    # Gate得分: 从factor_registry读取gate_ic/gate_ir/gate_t
    gate_info: dict[str, Any] = {}
    try:
        gate_row = await svc.get_factor_gate_fields(name)
        if isinstance(gate_row, dict):
            gate_info = gate_row
    except Exception as e:
        # S3 F81 修复: gate_info 读取失败记录可追溯
        logger.warning(
            "[factors] gate_info 读取失败 factor=%s err=%s",
            name, e, exc_info=True,
        )
    gate_score = _calc_gate_score(gate_info)

    # 相关性: 从factor_ic_history计算当前因子与其他Active因子的IC相关
    correlations: list[dict[str, Any]] = []
    try:
        all_factors = await svc.get_factor_list(status="active")
        other_names = [f["factor_name"] for f in all_factors if f["factor_name"] != name]
        if ic_values and other_names:
            from scipy import stats as sp_stats
            for other in other_names:
                other_df = await svc.get_factor_ic(other, start_date, end_date, forward_days=20)
                if not other_df.empty:
                    other_vals = [
                        float(v) for v in other_df["ic_value"].tolist() if v is not None
                    ]
                    min_len = min(len(ic_values), len(other_vals))
                    if min_len >= 10:
                        corr, _ = sp_stats.spearmanr(
                            ic_values[-min_len:], other_vals[-min_len:]
                        )
                        correlations.append({
                            "name": other,
                            "corr": round(float(corr), 4) if corr is not None else 0.0,
                        })
    except Exception as exc:
        logger.warning("因子相关性计算失败: %s", exc)

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
                "t_stat": t_stat,
                "fdr_t_stat": fdr_t,
                "newey_west_t": nw_t,
                "half_life_days": half_life,
                "gate_score": gate_score,
                "recommended_freq": rec_freq,
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
        # Tab: 相关性（与其他Active因子的IC Spearman相关）
        "correlations": correlations,
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


def _calc_fdr_t_stat(t_stat: float | None, m_tests: int = 69) -> float | None:
    """BH-FDR校正后的等效t值（Harvey Liu Zhu 2016）。

    方法: 将t统计量转为p值 → BH校正 → 转回等效t值。
    保守近似: FDR_t ≈ t * sqrt(1 - log(rank/M)) 简化为
    对单因子: p_adj = min(p * M / rank, 1.0), rank假设为中位=M/2。

    Args:
        t_stat: 原始t统计量。
        m_tests: 累积测试总数（FACTOR_TEST_REGISTRY.md M值）。

    Returns:
        FDR校正后等效t值。
    """
    import math

    from scipy import stats as sp_stats

    if t_stat is None or m_tests < 1:
        return None

    # 双尾p值
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=max(100, 481 - 1)))
    # BH校正: 假设该因子在排序中的rank为中位
    rank = max(m_tests // 2, 1)
    p_adj = min(p_val * m_tests / rank, 1.0)
    # 转回等效t值
    if p_adj >= 1.0:
        return 0.0
    fdr_t = float(sp_stats.t.ppf(1 - p_adj / 2, df=max(100, 481 - 1)))
    # 对极显著因子(t>15)校正后仍极显著,cap到原始t避免inf
    if math.isinf(fdr_t) or fdr_t > abs(t_stat):
        fdr_t = abs(t_stat)
    return fdr_t


def _calc_newey_west_t(ic_values: list[float]) -> float | None:
    """Newey-West HAC t统计量（自相关稳健）。

    使用Bartlett核，带宽 = floor(4*(N/100)^(2/9))。

    Args:
        ic_values: IC时序数据。

    Returns:
        Newey-West t统计量。
    """
    import math

    import numpy as np

    if len(ic_values) < 10:
        return None

    arr = np.array(ic_values, dtype=float)
    n = len(arr)
    mean = arr.mean()
    demean = arr - mean

    # Bartlett核带宽
    bandwidth = int(math.floor(4 * (n / 100) ** (2 / 9)))
    bandwidth = max(bandwidth, 1)

    # HAC方差估计
    gamma0 = float(np.dot(demean, demean) / n)
    hac_var = gamma0
    for lag in range(1, bandwidth + 1):
        weight = 1 - lag / (bandwidth + 1)  # Bartlett核
        gamma_lag = float(np.dot(demean[lag:], demean[:-lag]) / n)
        hac_var += 2 * weight * gamma_lag

    if hac_var <= 0:
        return None

    se = math.sqrt(hac_var / n)
    if se < 1e-12:
        return None

    return float(mean / se)


def _calc_ic_half_life(ic_values: list[float]) -> float | None:
    """IC自相关半衰期（指数衰减拟合）。

    对IC序列的自相关函数拟合 ACF(k) = exp(-k/τ)，半衰期 = τ * ln(2)。

    Args:
        ic_values: IC时序数据。

    Returns:
        半衰期（天数），无法拟合时返回None。
    """
    import math

    import numpy as np

    if len(ic_values) < 20:
        return None

    arr = np.array(ic_values, dtype=float)
    n = len(arr)
    mean = arr.mean()
    demean = arr - mean
    var = float(np.dot(demean, demean))
    if var < 1e-12:
        return None

    # 计算前10个lag的ACF
    max_lag = min(10, n // 5)
    acf_vals = []
    for lag in range(1, max_lag + 1):
        acf_k = float(np.dot(demean[lag:], demean[:-lag])) / var
        if acf_k <= 0:
            break  # ACF变负，停止
        acf_vals.append((lag, acf_k))

    if len(acf_vals) < 2:
        return None

    # 对 ln(ACF) = -k/τ 做线性回归
    lags = np.array([x[0] for x in acf_vals], dtype=float)
    ln_acf = np.log(np.array([x[1] for x in acf_vals], dtype=float))

    # OLS: ln_acf = a + b*lags, τ = -1/b, half_life = τ*ln(2)
    len(lags)
    mean_x = lags.mean()
    mean_y = ln_acf.mean()
    b = float(np.dot(lags - mean_x, ln_acf - mean_y) / np.dot(lags - mean_x, lags - mean_x))

    if b >= 0:
        return None  # ACF不衰减

    tau = -1.0 / b
    half_life = tau * math.log(2)

    return round(half_life, 1) if half_life > 0 else None


def _calc_gate_score(factor_info: dict[str, Any]) -> float | None:
    """从factor_registry计算Gate综合得分。

    综合 gate_ic / gate_ir / gate_t 的标准化得分。
    满分100: IC权重30 + IR权重30 + t值权重40。

    Args:
        factor_info: factor_registry行数据。

    Returns:
        0-100的Gate得分。
    """
    gate_ic = factor_info.get("gate_ic")
    gate_ir = factor_info.get("gate_ir")
    gate_t = factor_info.get("gate_t")

    if gate_ic is None and gate_ir is None and gate_t is None:
        return None

    score = 0.0
    # IC得分: |IC|>=0.05 满分30, 线性缩放
    if gate_ic is not None:
        ic_abs = abs(float(gate_ic))
        score += min(ic_abs / 0.05, 1.0) * 30
    # IR得分: |IR|>=1.0 满分30
    if gate_ir is not None:
        ir_abs = abs(float(gate_ir))
        score += min(ir_abs / 1.0, 1.0) * 30
    # t值得分: |t|>=5.0 满分40
    if gate_t is not None:
        t_abs = abs(float(gate_t))
        score += min(t_abs / 5.0, 1.0) * 40

    return round(score, 1)


def _recommend_rebalance_freq(ic_decay: dict[str, Any]) -> str | None:
    """基于IC衰减推荐调仓频率。

    规则:
    - 如果1d IC最高 → 日度
    - 如果5d IC最高 → 周度
    - 如果10d IC最高 → 双周
    - 如果20d IC最高 → 月度
    - 数据不足 → None

    Args:
        ic_decay: {1d: {ic_mean, data_points}, 5d: ..., 10d: ..., 20d: ...}

    Returns:
        推荐频率字符串。
    """
    freq_map = {"1d": "日度", "5d": "周度", "10d": "双周", "20d": "月度"}
    best_key = None
    best_ic = -1.0

    for key in ["1d", "5d", "10d", "20d"]:
        entry = ic_decay.get(key, {})
        if isinstance(entry, dict) and entry.get("ic_mean") is not None and entry.get("data_points", 0) > 0:
            ic_abs = abs(float(entry["ic_mean"]))
            if ic_abs > best_ic:
                best_ic = ic_abs
                best_key = key

    if best_key is None:
        return None

    return freq_map.get(best_key, "月度")
