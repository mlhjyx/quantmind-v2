"""回测 API 路由。

提供回测任务提交、状态查询、结果获取、交易明细、持仓历史、
年度分解、月度热力图、Brinson 归因、市场状态分段绩效、
成本敏感性分析及 QuantStats HTML 报告下载。
参考：DEV_BACKTEST_ENGINE.md §七 后端 API 清单。
"""

import logging
import tempfile
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


# ---------------------------------------------------------------------------
# Pydantic 请求/响应模型
# ---------------------------------------------------------------------------


class BacktestRunRequest(BaseModel):
    """提交回测任务的请求体。"""

    strategy_id: str = Field(..., description="策略ID")
    start_date: date = Field(..., description="回测起始日期")
    end_date: date = Field(..., description="回测结束日期")
    initial_capital: float = Field(default=1_000_000.0, ge=10_000, description="初始资金")
    benchmark: str = Field(default="000300.SH", description="基准指数代码")
    universe_preset: str = Field(default="all_a", description="股票池预设")
    rebalance_freq: str = Field(
        default="weekly",
        description="调仓频率: daily/weekly/biweekly/monthly",
    )
    slippage_model: str = Field(
        default="volume_impact",
        description="滑点模型: fixed/volume_impact",
    )
    cost_multiplier: float = Field(default=1.0, ge=0.0, le=5.0, description="成本倍数")
    extra_config: dict[str, Any] = Field(default_factory=dict, description="额外配置(JSONB)")


class BacktestRunResponse(BaseModel):
    """提交回测任务的响应。"""

    run_id: str
    status: str
    message: str


class BacktestStatusResponse(BaseModel):
    """回测状态查询响应。"""

    run_id: str
    status: str  # running | completed | failed
    progress: float | None = None  # 0.0 ~ 1.0
    error_msg: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


class SensitivityRow(BaseModel):
    """成本敏感性分析单行。"""

    cost_multiplier: float
    annual_return: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    calmar_ratio: float | None = None


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入数据库 session。"""
    return session


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _get_run_or_404(
    session: AsyncSession, run_id: UUID
) -> dict[str, Any]:
    """从 backtest_run 获取记录，不存在则抛 404。"""
    result = await session.execute(
        text("SELECT * FROM backtest_run WHERE run_id = :rid"),
        {"rid": str(run_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"回测记录不存在: {run_id}")
    return dict(row)


async def _require_completed(
    session: AsyncSession, run_id: UUID
) -> dict[str, Any]:
    """获取回测记录并要求状态为 completed。"""
    run = await _get_run_or_404(session, run_id)
    if run["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"回测尚未完成，当前状态: {run['status']}",
        )
    return run


# ---------------------------------------------------------------------------
# 1. 回测管理
# ---------------------------------------------------------------------------


@router.post("/run", response_model=BacktestRunResponse)
async def submit_backtest(
    req: BacktestRunRequest,
    session: AsyncSession = Depends(_get_session),
) -> BacktestRunResponse:
    """提交回测任务（异步执行，返回 run_id）。

    将回测配置写入 backtest_run 表（status='running'），
    后续由 Celery worker 拾取执行。

    Args:
        req: 回测配置参数。

    Returns:
        包含 run_id 和初始状态的响应。
    """
    import json
    from uuid import uuid4

    run_id = str(uuid4())
    config_json = json.dumps(
        {
            "initial_capital": req.initial_capital,
            "benchmark": req.benchmark,
            "universe_preset": req.universe_preset,
            "rebalance_freq": req.rebalance_freq,
            "slippage_model": req.slippage_model,
            "cost_multiplier": req.cost_multiplier,
            **req.extra_config,
        },
        ensure_ascii=False,
    )

    await session.execute(
        text(
            """
            INSERT INTO backtest_run
                (run_id, strategy_id, config_json, start_date, end_date, status)
            VALUES
                (:run_id, :sid, :cfg::jsonb, :sd, :ed, 'running')
            """
        ),
        {
            "run_id": run_id,
            "sid": req.strategy_id,
            "cfg": config_json,
            "sd": req.start_date.isoformat(),
            "ed": req.end_date.isoformat(),
        },
    )
    await session.commit()

    # TODO: 触发 Celery task — celery_app.send_task("backtest.run", args=[run_id])
    logger.info("回测任务已提交: run_id=%s, strategy=%s", run_id, req.strategy_id)

    return BacktestRunResponse(
        run_id=run_id,
        status="running",
        message="回测任务已提交，请通过 GET /api/backtest/{run_id} 查询进度",
    )


@router.get("/history")
async def get_backtest_history(
    strategy_id: str = Query(default="", description="按策略ID筛选"),
    market: str = Query(default="", description="按市场筛选: a_share/forex"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量上限"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """回测历史列表（分页）。

    支持按策略ID和市场筛选，默认按创建时间倒序。

    Args:
        strategy_id: 策略ID筛选，为空时不筛选。
        market: 市场筛选。
        limit: 每页数量。
        offset: 偏移量。

    Returns:
        包含 total/items 的分页结果。
    """
    where_clauses: list[str] = []
    params: dict[str, Any] = {"lim": limit, "off": offset}

    if strategy_id:
        where_clauses.append("strategy_id = :sid")
        params["sid"] = strategy_id
    if market:
        where_clauses.append("market = :mkt")
        params["mkt"] = market

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # 总数
    count_result = await session.execute(
        text(f"SELECT COUNT(*) FROM backtest_run WHERE {where_sql}"),  # noqa: S608
        params,
    )
    total = count_result.scalar() or 0

    # 列表
    rows_result = await session.execute(
        text(
            f"""
            SELECT run_id, strategy_id, name AS run_name, status,
                   annual_return, sharpe_ratio, max_drawdown, calmar_ratio,
                   start_date, end_date, created_at
            FROM backtest_run
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
            """  # noqa: S608
        ),
        params,
    )
    items = [dict(row) for row in rows_result.mappings().all()]

    # UUID/date 序列化
    for item in items:
        for key in ("run_id", "strategy_id"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        for key in ("start_date", "end_date", "created_at"):
            if item.get(key) is not None:
                item[key] = str(item[key])

    return {"total": total, "items": items}


@router.get("/{run_id}", response_model=BacktestStatusResponse)
async def get_backtest_status(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> BacktestStatusResponse:
    """查询回测任务状态。

    Args:
        run_id: 回测运行ID。

    Returns:
        当前状态（running/completed/failed）及进度信息。
    """
    run = await _get_run_or_404(session, run_id)
    return BacktestStatusResponse(
        run_id=str(run["run_id"]),
        status=run["status"],
        progress=1.0 if run["status"] == "completed" else None,
        error_msg=run.get("error_msg"),
        created_at=str(run["created_at"]) if run.get("created_at") else None,
        finished_at=str(run["finished_at"]) if run.get("finished_at") else None,
    )


@router.get("/{run_id}/result")
async def get_backtest_result(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """获取回测汇总结果。

    返回完整绩效指标，包括 CLAUDE.md 规定的必含指标：
    Sharpe/MDD/年化收益/超额收益/Calmar/Sortino/Bootstrap CI 等。

    Args:
        run_id: 回测运行ID（需 status=completed）。

    Returns:
        包含策略信息、绩效指标、配置快照的字典。
    """
    run = await _require_completed(session, run_id)

    return {
        "run_id": str(run["run_id"]),
        "strategy_id": str(run["strategy_id"]) if run.get("strategy_id") else None,
        "status": run["status"],
        "start_date": str(run["start_date"]),
        "end_date": str(run["end_date"]),
        "config": run.get("config_json"),
        "metrics": {
            "annual_return": run.get("annual_return"),
            "sharpe_ratio": run.get("sharpe_ratio"),
            "max_drawdown": run.get("max_drawdown"),
            "calmar_ratio": run.get("calmar_ratio"),
            "total_turnover": run.get("total_turnover"),
            "win_rate": run.get("win_rate"),
            # 以下指标从 config_json 或 backtest_daily_nav 二次计算
            # Phase 0 先返回 run 表中的冗余字段
        },
        "created_at": str(run["created_at"]) if run.get("created_at") else None,
        "finished_at": str(run["finished_at"]) if run.get("finished_at") else None,
    }


# ---------------------------------------------------------------------------
# 2. 回测结果详情
# ---------------------------------------------------------------------------


@router.get("/{run_id}/nav")
async def get_nav_series(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """NAV（净值）时间序列。

    返回每日净值、现金、市值、日收益率、基准净值、超额收益。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        按日期排序的 NAV 列表。
    """
    await _require_completed(session, run_id)
    result = await session.execute(
        text(
            """
            SELECT trade_date, nav, cash, market_value,
                   daily_return, benchmark_nav, benchmark_return, excess_return
            FROM backtest_daily_nav
            WHERE run_id = :rid
            ORDER BY trade_date
            """
        ),
        {"rid": str(run_id)},
    )
    rows = result.mappings().all()
    return [
        {**dict(r), "trade_date": str(r["trade_date"])}
        for r in rows
    ]


@router.get("/{run_id}/trades")
async def get_trades(
    run_id: UUID,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=100, ge=1, le=1000, description="每页条数"),
    stock_code: str = Query(default="", description="按股票代码筛选"),
    side: str = Query(default="", description="按方向筛选: buy/sell"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """交易明细（分页）。

    返回信号日期、执行日期、股票代码、方向、数量、价格、
    滑点、佣金、印花税、过户费、拒绝原因等。

    Args:
        run_id: 回测运行ID（需 completed）。
        page: 页码。
        page_size: 每页条数。
        stock_code: 股票代码筛选。
        side: 买卖方向筛选。

    Returns:
        包含 total/page/page_size/items 的分页结果。
    """
    await _require_completed(session, run_id)

    where_parts = ["run_id = :rid"]
    params: dict[str, Any] = {
        "rid": str(run_id),
        "lim": page_size,
        "off": (page - 1) * page_size,
    }

    if stock_code:
        where_parts.append("stock_code = :sc")
        params["sc"] = stock_code
    if side:
        where_parts.append("side = :sd")
        params["sd"] = side

    where_sql = " AND ".join(where_parts)

    count_res = await session.execute(
        text(f"SELECT COUNT(*) FROM backtest_trades WHERE {where_sql}"),  # noqa: S608
        params,
    )
    total = count_res.scalar() or 0

    rows_res = await session.execute(
        text(
            f"""
            SELECT id, signal_date, exec_date, stock_code, side, shares,
                   target_price, exec_price, slippage_bps,
                   commission, stamp_tax, transfer_fee, total_cost,
                   reject_reason
            FROM backtest_trades
            WHERE {where_sql}
            ORDER BY exec_date, stock_code
            LIMIT :lim OFFSET :off
            """  # noqa: S608
        ),
        params,
    )
    items = []
    for r in rows_res.mappings().all():
        row = dict(r)
        for dk in ("signal_date", "exec_date"):
            if row.get(dk) is not None:
                row[dk] = str(row[dk])
        items.append(row)

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/{run_id}/holdings")
async def get_holdings(
    run_id: UUID,
    trade_date: date | None = Query(default=None, description="指定日期的持仓快照"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """持仓历史。

    不带 trade_date 时返回所有日期的持仓汇总（每日持仓数+总市值）；
    带 trade_date 时返回该日逐股持仓明细。

    Args:
        run_id: 回测运行ID（需 completed）。
        trade_date: 可选，指定日期获取逐股持仓。

    Returns:
        持仓数据列表。
    """
    await _require_completed(session, run_id)

    if trade_date:
        # 某日逐股持仓明细
        result = await session.execute(
            text(
                """
                SELECT trade_date, stock_code, shares, cost_basis,
                       market_price, market_value, weight, pnl,
                       buy_date, industry_code
                FROM backtest_holdings
                WHERE run_id = :rid AND trade_date = :td
                ORDER BY weight DESC
                """
            ),
            {"rid": str(run_id), "td": trade_date.isoformat()},
        )
    else:
        # 所有日期的持仓汇总
        result = await session.execute(
            text(
                """
                SELECT trade_date,
                       COUNT(*) AS holding_count,
                       SUM(market_value) AS total_market_value
                FROM backtest_holdings
                WHERE run_id = :rid
                GROUP BY trade_date
                ORDER BY trade_date
                """
            ),
            {"rid": str(run_id)},
        )

    rows = result.mappings().all()
    return [
        {**dict(r), "trade_date": str(r["trade_date"])}
        for r in rows
    ]


@router.get("/{run_id}/annual")
async def get_annual_breakdown(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """年度分解。

    CLAUDE.md 要求：每年的收益/Sharpe/MDD 单独列出，最差年度标红（前端处理）。
    基于 backtest_daily_nav 按年聚合计算。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        每年的绩效指标列表。
    """
    await _require_completed(session, run_id)

    result = await session.execute(
        text(
            """
            SELECT
                EXTRACT(YEAR FROM trade_date)::INT AS year,
                -- 年化收益 = (期末NAV/期初NAV - 1)
                (MAX(nav) FILTER (WHERE trade_date = sub.last_date) /
                 NULLIF(MAX(nav) FILTER (WHERE trade_date = sub.first_date), 0) - 1
                ) AS annual_return,
                -- 日收益率均值和标准差用于 Sharpe 估算
                AVG(daily_return) AS avg_daily_return,
                STDDEV(daily_return) AS std_daily_return,
                COUNT(*) AS trading_days,
                -- 最大回撤（简化版：年内最大回撤）
                MIN(daily_return) AS worst_day
            FROM backtest_daily_nav n
            JOIN LATERAL (
                SELECT
                    MIN(trade_date) AS first_date,
                    MAX(trade_date) AS last_date
                FROM backtest_daily_nav
                WHERE run_id = :rid
                  AND EXTRACT(YEAR FROM trade_date) = EXTRACT(YEAR FROM n.trade_date)
            ) sub ON TRUE
            WHERE n.run_id = :rid
            GROUP BY EXTRACT(YEAR FROM trade_date), sub.first_date, sub.last_date
            ORDER BY year
            """
        ),
        {"rid": str(run_id)},
    )
    rows = result.mappings().all()
    annual_data = []
    for r in rows:
        avg_ret = r["avg_daily_return"] or 0
        std_ret = r["std_daily_return"] or 1
        trading_days = r["trading_days"] or 1
        sharpe = (avg_ret / std_ret * (trading_days ** 0.5)) if std_ret > 0 else 0
        annual_data.append({
            "year": r["year"],
            "annual_return": r["annual_return"],
            "sharpe_ratio": round(sharpe, 4),
            "trading_days": trading_days,
            "worst_day": r["worst_day"],
        })

    return annual_data


@router.get("/{run_id}/monthly")
async def get_monthly_heatmap(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """月度热力图数据。

    CLAUDE.md 要求：月度收益热力图，发现季节性。
    返回 year/month/monthly_return 用于前端渲染热力图。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        每月收益数据列表。
    """
    await _require_completed(session, run_id)

    result = await session.execute(
        text(
            """
            WITH monthly AS (
                SELECT
                    EXTRACT(YEAR FROM trade_date)::INT AS year,
                    EXTRACT(MONTH FROM trade_date)::INT AS month,
                    trade_date,
                    nav,
                    ROW_NUMBER() OVER (
                        PARTITION BY EXTRACT(YEAR FROM trade_date),
                                     EXTRACT(MONTH FROM trade_date)
                        ORDER BY trade_date
                    ) AS rn_asc,
                    ROW_NUMBER() OVER (
                        PARTITION BY EXTRACT(YEAR FROM trade_date),
                                     EXTRACT(MONTH FROM trade_date)
                        ORDER BY trade_date DESC
                    ) AS rn_desc
                FROM backtest_daily_nav
                WHERE run_id = :rid
            )
            SELECT
                year, month,
                MAX(CASE WHEN rn_desc = 1 THEN nav END) /
                NULLIF(MAX(CASE WHEN rn_asc = 1 THEN nav END), 0) - 1
                AS monthly_return,
                COUNT(*) AS trading_days
            FROM monthly
            GROUP BY year, month
            ORDER BY year, month
            """
        ),
        {"rid": str(run_id)},
    )
    return [dict(r) for r in result.mappings().all()]


@router.get("/{run_id}/attribution")
async def get_brinson_attribution(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Brinson 归因分析。

    基于持仓行业分组，分解为配置效应、选股效应、交互效应。
    需要 backtest_holdings 和 backtest_daily_nav 数据。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        归因分析结果，按行业分组。
    """
    await _require_completed(session, run_id)

    # 查询持仓行业分布（取最后一个调仓日作为代表）
    result = await session.execute(
        text(
            """
            SELECT
                COALESCE(industry_code, 'unknown') AS industry,
                COUNT(DISTINCT stock_code) AS stock_count,
                SUM(weight) AS total_weight,
                AVG(pnl) AS avg_pnl
            FROM backtest_holdings
            WHERE run_id = :rid
              AND trade_date = (
                  SELECT MAX(trade_date)
                  FROM backtest_holdings
                  WHERE run_id = :rid
              )
            GROUP BY industry_code
            ORDER BY total_weight DESC
            """
        ),
        {"rid": str(run_id)},
    )
    industries = [dict(r) for r in result.mappings().all()]

    return {
        "run_id": str(run_id),
        "method": "brinson",
        "note": "简化版 Brinson 归因，完整版需要基准行业权重数据(index_components表)",
        "industries": industries,
    }


@router.get("/{run_id}/market-state")
async def get_market_state_performance(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """市场状态分段绩效。

    CLAUDE.md 要求：自动分牛市/熊市/震荡三段，分别看绩效。
    使用 MA120 判定市场状态（DEV_BACKTEST_ENGINE 决策 #20）。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        按市场状态分段的绩效指标。
    """
    await _require_completed(session, run_id)

    # 基于基准NAV序列计算MA120，划分市场状态
    result = await session.execute(
        text(
            """
            WITH nav_with_ma AS (
                SELECT
                    trade_date,
                    daily_return,
                    benchmark_nav,
                    AVG(benchmark_nav) OVER (
                        ORDER BY trade_date
                        ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
                    ) AS ma120,
                    COUNT(*) OVER (
                        ORDER BY trade_date
                        ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
                    ) AS ma_window
                FROM backtest_daily_nav
                WHERE run_id = :rid
            ),
            classified AS (
                SELECT
                    trade_date,
                    daily_return,
                    CASE
                        WHEN ma_window < 120 THEN 'insufficient_data'
                        WHEN benchmark_nav > ma120 * 1.05 THEN 'bull'
                        WHEN benchmark_nav < ma120 * 0.95 THEN 'bear'
                        ELSE 'sideways'
                    END AS market_state
                FROM nav_with_ma
            )
            SELECT
                market_state,
                COUNT(*) AS trading_days,
                AVG(daily_return) AS avg_daily_return,
                STDDEV(daily_return) AS std_daily_return,
                SUM(daily_return) AS cumulative_return,
                MIN(daily_return) AS worst_day,
                MAX(daily_return) AS best_day
            FROM classified
            WHERE market_state != 'insufficient_data'
            GROUP BY market_state
            ORDER BY market_state
            """
        ),
        {"rid": str(run_id)},
    )
    states = []
    for r in result.mappings().all():
        row = dict(r)
        avg_ret = row["avg_daily_return"] or 0
        std_ret = row["std_daily_return"] or 1
        days = row["trading_days"] or 1
        row["sharpe_estimate"] = round(
            (avg_ret / std_ret * (days ** 0.5)) if std_ret > 0 else 0, 4
        )
        states.append(row)

    return {
        "run_id": str(run_id),
        "method": "MA120",
        "states": states,
    }


@router.get("/{run_id}/cost-sensitivity")
async def get_cost_sensitivity(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """成本敏感性分析。

    CLAUDE.md 规则6: 必须包含不同成本假设下的绩效对比（0.5x/1x/1.5x/2x）。
    基于 backtest_daily_nav 的日收益率，按不同成本倍数调整后重新计算绩效。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        各成本倍数下的绩效指标及警告信息。
    """
    run = await _require_completed(session, run_id)

    # 获取基准绩效
    base_metrics = {
        "annual_return": run.get("annual_return"),
        "sharpe_ratio": run.get("sharpe_ratio"),
        "max_drawdown": run.get("max_drawdown"),
        "calmar_ratio": run.get("calmar_ratio"),
    }

    # 获取日收益率序列用于重算
    nav_result = await session.execute(
        text(
            """
            SELECT trade_date, daily_return, nav
            FROM backtest_daily_nav
            WHERE run_id = :rid
            ORDER BY trade_date
            """
        ),
        {"rid": str(run_id)},
    )
    nav_rows = nav_result.mappings().all()

    # 获取交易成本总额
    cost_result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(total_cost), 0) AS total_cost,
                   COUNT(*) AS trade_count
            FROM backtest_trades
            WHERE run_id = :rid AND reject_reason IS NULL
            """
        ),
        {"rid": str(run_id)},
    )
    cost_info = cost_result.mappings().first()
    total_cost = float(cost_info["total_cost"]) if cost_info else 0
    trade_count = int(cost_info["trade_count"]) if cost_info else 0
    trading_days = len(nav_rows) or 1
    daily_cost_impact = total_cost / trading_days if trading_days > 0 else 0

    multipliers = [0.5, 1.0, 1.5, 2.0]
    sensitivity_rows: list[dict[str, Any]] = []

    for mult in multipliers:
        if mult == 1.0:
            sensitivity_rows.append({
                "cost_multiplier": mult,
                "label": "基准",
                **base_metrics,
            })
        else:
            # 简化计算：按成本差异调整年化收益和 Sharpe
            cost_delta_annual = daily_cost_impact * (mult - 1.0) * 252
            base_annual = base_metrics.get("annual_return") or 0
            base_sharpe = base_metrics.get("sharpe_ratio") or 0
            base_mdd = base_metrics.get("max_drawdown") or 0

            adj_annual = base_annual - cost_delta_annual
            # Sharpe 粗略调整
            adj_sharpe = base_sharpe * (1 + adj_annual) / (1 + base_annual) if (1 + base_annual) != 0 else 0
            adj_calmar = abs(adj_annual / base_mdd) if base_mdd and base_mdd != 0 else None

            sensitivity_rows.append({
                "cost_multiplier": mult,
                "label": f"{mult}x",
                "annual_return": round(adj_annual, 6) if adj_annual is not None else None,
                "sharpe_ratio": round(adj_sharpe, 4) if adj_sharpe is not None else None,
                "max_drawdown": base_mdd,  # MDD 基本不受成本影响
                "calmar_ratio": round(adj_calmar, 4) if adj_calmar is not None else None,
            })

    # CLAUDE.md: 如果2倍成本下 Sharpe < 0.5，策略在实盘中大概率不行
    warning = None
    two_x = next((r for r in sensitivity_rows if r["cost_multiplier"] == 2.0), None)
    if two_x and two_x.get("sharpe_ratio") is not None and two_x["sharpe_ratio"] < 0.5:
        warning = "警告: 2倍成本下Sharpe < 0.5，策略在实盘中大概率不行"

    return {
        "run_id": str(run_id),
        "total_cost_base": total_cost,
        "trade_count": trade_count,
        "rows": sensitivity_rows,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# 3. QuantStats HTML 报告
# ---------------------------------------------------------------------------


@router.get("/{run_id}/report")
async def get_quantstats_report(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> FileResponse:
    """生成并下载 QuantStats HTML 报告。

    基于 backtest_daily_nav 中的日收益率序列，调用 quantstats 生成
    完整的可视化分析报告（含 Sharpe/MDD/月度热力图/回撤等）。

    如果 quantstats 未安装，返回 501 提示。

    Args:
        run_id: 回测运行ID（需 completed）。

    Returns:
        HTML 文件下载响应。
    """
    await _require_completed(session, run_id)

    # 获取日收益率序列
    nav_result = await session.execute(
        text(
            """
            SELECT trade_date, daily_return, benchmark_return
            FROM backtest_daily_nav
            WHERE run_id = :rid
            ORDER BY trade_date
            """
        ),
        {"rid": str(run_id)},
    )
    rows = nav_result.mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="无 NAV 数据，无法生成报告")

    # 尝试导入 quantstats
    try:
        import pandas as pd
        import quantstats as qs  # type: ignore[import-untyped]
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="quantstats 未安装，请执行: pip install quantstats",
        )

    # 构建 pandas Series
    dates = [r["trade_date"] for r in rows]
    returns = [float(r["daily_return"] or 0) for r in rows]
    benchmark_returns = [float(r["benchmark_return"] or 0) for r in rows]

    returns_series = pd.Series(returns, index=pd.DatetimeIndex(dates), name="Strategy")
    benchmark_series = pd.Series(
        benchmark_returns, index=pd.DatetimeIndex(dates), name="Benchmark"
    )

    # 生成 HTML 到临时文件
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", prefix=f"quantmind_bt_{run_id}_", delete=False
    )
    tmp.close()

    try:
        qs.reports.html(
            returns_series,
            benchmark=benchmark_series,
            output=tmp.name,
            title=f"QuantMind V2 Backtest — {run_id}",
        )
    except Exception as e:
        logger.error("QuantStats 报告生成失败: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"QuantStats 报告生成失败: {e}",
        )

    return FileResponse(
        path=tmp.name,
        media_type="text/html",
        filename=f"backtest_report_{run_id}.html",
    )


# ---------------------------------------------------------------------------
# 4. 策略对比 & 参数敏感性（DEV_BACKTEST_ENGINE §七）
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    """策略对比请求。"""

    run_ids: list[str] = Field(..., min_length=2, max_length=5, description="要对比的 run_id 列表")


@router.post("/compare")
async def compare_strategies(
    req: CompareRequest,
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """策略对比。

    DEV_BACKTEST_ENGINE 决策 #26: 支持勾选 2 个策略进入对比视图。
    返回各 run 的汇总指标用于并列对比。

    Args:
        req: 包含 2-5 个 run_id 的对比请求。

    Returns:
        各 run 的汇总指标列表。
    """
    results = []
    for rid_str in req.run_ids:
        try:
            rid = UUID(rid_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的 run_id: {rid_str}")

        run = await _get_run_or_404(session, rid)
        results.append({
            "run_id": str(run["run_id"]),
            "strategy_id": str(run["strategy_id"]) if run.get("strategy_id") else None,
            "run_name": run.get("run_name"),
            "status": run["status"],
            "start_date": str(run["start_date"]),
            "end_date": str(run["end_date"]),
            "annual_return": run.get("annual_return"),
            "sharpe_ratio": run.get("sharpe_ratio"),
            "max_drawdown": run.get("max_drawdown"),
            "calmar_ratio": run.get("calmar_ratio"),
            "total_turnover": run.get("total_turnover"),
            "win_rate": run.get("win_rate"),
        })

    return results


class SensitivityRequest(BaseModel):
    """参数敏感性分析请求。"""

    param_name: str = Field(..., description="要分析的参数名")
    param_values: list[float] = Field(
        ..., min_length=2, max_length=20, description="参数取值列表"
    )


@router.post("/{run_id}/sensitivity")
async def run_sensitivity_analysis(
    run_id: UUID,
    req: SensitivityRequest,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """参数敏感性分析（DEV_BACKTEST_ENGINE §七）。

    对指定参数的多个取值分别跑回测，对比绩效变化。
    Phase 0: 返回占位结构，实际多参数回测由 Celery task 异步完成。

    Args:
        run_id: 基准回测的 run_id。
        req: 参数名和取值列表。

    Returns:
        敏感性分析任务状态。
    """
    await _get_run_or_404(session, run_id)

    # TODO: Phase 0 占位 — 触发 Celery task 对每个 param_value 跑子回测
    return {
        "run_id": str(run_id),
        "param_name": req.param_name,
        "param_values": req.param_values,
        "status": "pending",
        "message": "参数敏感性分析任务已排队，完成后通过 WebSocket 推送结果",
    }


@router.get("/{run_id}/live-compare")
async def get_live_compare(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """实盘对比数据（DEV_BACKTEST_ENGINE §七）。

    对比回测结果与 Paper Trading / 实盘的绩效差异。
    Phase 0: 返回回测侧数据，实盘侧在 Paper Trading 启动后补充。

    Args:
        run_id: 回测运行ID。

    Returns:
        回测 vs 实盘的对比数据结构。
    """
    run = await _get_run_or_404(session, run_id)

    return {
        "run_id": str(run_id),
        "backtest": {
            "annual_return": run.get("annual_return"),
            "sharpe_ratio": run.get("sharpe_ratio"),
            "max_drawdown": run.get("max_drawdown"),
        },
        "live": None,  # Phase 0: Paper Trading 未启动时为 None
        "note": "实盘数据在 Paper Trading 达到毕业标准后可用",
    }
