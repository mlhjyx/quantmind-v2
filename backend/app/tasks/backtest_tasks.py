"""回测 Celery 任务 — SimpleBacktester 引擎的异步执行封装。

流程: 读config → 加载数据 → 构建target_portfolios → 引擎回测 → 写结果。
参考 mining_tasks.py 的模式: asyncio.run() + asyncpg。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

# Celery worker 可能缺少 backend/ 在 sys.path 中，导致 engines 模块不可用
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.backtest_tasks")

DB_URL = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

DEFAULT_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20",
    "amihud_20", "bp_ratio",
]


@celery_app.task(
    bind=True,
    name="app.tasks.backtest_tasks.run_backtest",
    acks_late=True,
    max_retries=0,
    soft_time_limit=3600,
    time_limit=3900,
)
def run_backtest(self, run_id: str) -> dict[str, Any]:
    """回测 Celery 任务入口。"""
    logger.info("回测任务启动: run_id=%s", run_id)
    t0 = time.monotonic()
    try:
        result = asyncio.run(_run_async(run_id))
        logger.info(
            "回测任务完成: run_id=%s, %.1fs, %d trades",
            run_id, time.monotonic() - t0, result.get("trade_count", 0),
        )
        return result
    except Exception as exc:
        logger.error("回测任务失败: run_id=%s, %s", run_id, exc, exc_info=True)
        asyncio.run(_mark_failed(run_id, str(exc)[:500]))
        raise


# ---------------------------------------------------------------------------
# Async main logic
# ---------------------------------------------------------------------------

async def _run_async(run_id: str) -> dict[str, Any]:
    import asyncpg
    from engines.backtest_engine import BacktestConfig, SimpleBacktester
    from engines.vectorized_signal import SignalConfig, build_target_portfolios, compute_rebalance_dates

    conn = await asyncpg.connect(DB_URL)
    try:
        rid = uuid.UUID(run_id)

        # 1. Read config
        row = await conn.fetchrow(
            "SELECT config_json, start_date, end_date, factor_list FROM backtest_run WHERE run_id = $1",
            rid,
        )
        if not row:
            raise ValueError(f"backtest_run not found: {run_id}")

        cfg = row["config_json"] if isinstance(row["config_json"], dict) else json.loads(row["config_json"])
        start_dt: date = row["start_date"]
        end_dt: date = row["end_date"]
        factors = row["factor_list"] or DEFAULT_FACTORS

        # 2. Update status → running
        await conn.execute("UPDATE backtest_run SET status = 'running' WHERE run_id = $1", rid)

        # 3. Load data
        price_df = await _load_prices(conn, start_dt, end_dt)
        if price_df.empty:
            raise ValueError("行情数据为空")

        factor_df = await _load_factors(conn, start_dt, end_dt, factors)
        if factor_df.empty:
            raise ValueError(f"因子数据为空 (factors={factors})")

        directions = await _load_directions(conn, factors)
        bench_df = await _load_benchmark(conn, start_dt, end_dt, cfg.get("benchmark", "000300.SH"))

        # 4. Build target portfolios
        top_n = int(cfg.get("holding_count", cfg.get("top_n", 15)))
        rebal_freq = cfg.get("rebalance_freq", "monthly")
        trading_days = sorted(price_df["trade_date"].unique())
        rebal_dates = compute_rebalance_dates(trading_days, rebal_freq)

        sig_config = SignalConfig(top_n=top_n, rebalance_freq=rebal_freq)
        target_portfolios = build_target_portfolios(factor_df, directions, rebal_dates, sig_config)
        if not target_portfolios:
            raise ValueError("target_portfolios 为空，检查因子数据覆盖")

        # 5. Run engine
        bt_config = BacktestConfig(
            initial_capital=float(cfg.get("initial_capital", 1_000_000)),
            top_n=top_n,
            rebalance_freq=rebal_freq,
            slippage_mode=cfg.get("slippage_model", "volume_impact"),
            benchmark_code=cfg.get("benchmark", "000300.SH"),
        )
        t0 = time.monotonic()
        tester = SimpleBacktester(bt_config)
        result = tester.run(target_portfolios, price_df, bench_df)
        elapsed = int(time.monotonic() - t0)

        # 6. Calc metrics & write results
        metrics = _calc_metrics(result)
        await _write_results(conn, rid, metrics, result, elapsed, start_dt, end_dt, factors)

        return {
            "run_id": run_id,
            "status": "completed",
            "trade_count": len(result.trades),
            "metrics": metrics,
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

async def _load_prices(conn, start_dt: date, end_dt: date) -> pd.DataFrame:
    """加载 klines_daily 行情数据。"""
    rows = await conn.fetch(
        """
        SELECT k.code, k.trade_date, k.open, k.close, k.volume, k.amount,
               k.up_limit, k.down_limit, k.turnover_rate, k.pre_close
        FROM klines_daily k
        WHERE k.trade_date BETWEEN $1 AND $2
          AND k.is_suspended = false AND k.is_st = false
        ORDER BY k.trade_date, k.code
        """,
        start_dt, end_dt,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    for col in ["open", "close", "volume", "amount", "up_limit", "down_limit",
                "turnover_rate", "pre_close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


async def _load_factors(conn, start_dt: date, end_dt: date, factors: list[str]) -> pd.DataFrame:
    """加载 factor_values 因子截面数据。"""
    rows = await conn.fetch(
        """
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE trade_date BETWEEN $1 AND $2
          AND factor_name = ANY($3)
        """,
        start_dt, end_dt, factors,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["raw_value"] = pd.to_numeric(df["raw_value"], errors="coerce")
    return df


async def _load_directions(conn, factors: list[str]) -> dict[str, int]:
    """加载因子方向: +1正向, -1反向。"""
    rows = await conn.fetch(
        "SELECT name, direction FROM factor_registry WHERE name = ANY($1)",
        factors,
    )
    return {r["name"]: int(r["direction"]) for r in rows}


async def _load_benchmark(conn, start_dt: date, end_dt: date, code: str) -> pd.DataFrame:
    """加载基准指数日线。"""
    rows = await conn.fetch(
        """
        SELECT trade_date, close
        FROM index_daily
        WHERE index_code = $1 AND trade_date BETWEEN $2 AND $3
        ORDER BY trade_date
        """,
        code, start_dt, end_dt,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Portfolio construction
# ---------------------------------------------------------------------------

def _rebalance_dates(trading_days: list, freq: str) -> list[date]:
    """从交易日列表计算调仓日期。"""
    if not trading_days:
        return []

    td_series = pd.Series(trading_days)

    if freq == "daily":
        return list(trading_days)
    elif freq == "weekly":
        return list(td_series.groupby(td_series.apply(lambda d: (d.year, d.isocalendar()[1]))).last())
    elif freq == "biweekly":
        weekly = list(td_series.groupby(td_series.apply(lambda d: (d.year, d.isocalendar()[1]))).last())
        return weekly[::2]
    elif freq == "monthly":
        return list(td_series.groupby(td_series.apply(lambda d: (d.year, d.month))).last())
    else:
        return list(td_series.groupby(td_series.apply(lambda d: (d.year, d.month))).last())


def _build_targets(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    rebal_dates: list[date],
    top_n: int,
) -> dict[date, dict[str, float]]:
    """构建 target_portfolios: {signal_date: {code: weight}}。

    每个调仓日:
    1. 取当日各因子截面 raw_value
    2. 每个因子 z-score 标准化，乘以 direction
    3. 等权平均 → alpha_score
    4. 降序取 Top-N
    5. 等权分配 (1/N)
    """
    targets: dict[date, dict[str, float]] = {}
    factor_names = list(directions.keys())

    for rd in rebal_dates:
        # 取调仓日当天或之前最近一天的因子数据
        day_data = factor_df[factor_df["trade_date"] <= rd]
        if day_data.empty:
            continue

        # 取每只股票每个因子的最新值
        latest_date = day_data["trade_date"].max()
        day_data = day_data[day_data["trade_date"] == latest_date]

        # pivot: code × factor_name → raw_value
        pivot = pd.DataFrame(day_data).pivot_table(
            index="code", columns="factor_name", values="raw_value", aggfunc="first",
        )

        available_factors = [f for f in factor_names if f in pivot.columns]
        if not available_factors:
            continue

        min_factors = len(available_factors) // 2 + 1
        pivot = pivot[available_factors].dropna(thresh=min_factors)
        if len(pivot) < top_n:
            continue

        # z-score + direction
        scores = pd.DataFrame(index=pivot.index)
        for f in available_factors:
            col = pivot[f]
            std = col.std()
            if std > 0:
                z = (col - col.mean()) / std
            else:
                z = col * 0.0
            direction = directions.get(f, 1)
            scores[f] = z * direction

        # 等权平均
        alpha = scores.mean(axis=1).dropna()
        if len(alpha) < top_n:
            continue

        # Top-N 等权
        top_codes: list[str] = alpha.nlargest(top_n).index.tolist()
        weight = 1.0 / len(top_codes)
        targets[rd] = {c: weight for c in top_codes}

    return targets


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _calc_metrics(result) -> dict[str, Any]:
    """从 BacktestResult 计算核心指标。"""
    nav = result.daily_nav
    rets = result.daily_returns

    if rets is None or len(rets) < 2:
        return {"sharpe_ratio": 0, "annual_return": 0, "max_drawdown": 0}

    trading_days = len(rets)
    ann_factor = 252

    # Annual return
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1) if nav.iloc[0] > 0 else 0
    years = trading_days / ann_factor
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # Sharpe
    mean_ret = float(rets.mean())
    std_ret = float(rets.std())
    sharpe = (mean_ret / std_ret * math.sqrt(ann_factor)) if std_ret > 0 else 0

    # MDD
    cummax = nav.cummax()
    dd = (nav - cummax) / cummax
    mdd = float(dd.min())

    # Win rate
    win_rate = float((rets > 0).sum() / len(rets)) if len(rets) > 0 else 0

    # Turnover
    avg_turnover = float(result.turnover_series.mean()) if result.turnover_series is not None and len(result.turnover_series) > 0 else 0

    # Calmar
    calmar = annual_return / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = rets[rets < 0]
    downside_std = float(downside.std()) if len(downside) > 0 else 0
    sortino = (mean_ret / downside_std * math.sqrt(ann_factor)) if downside_std > 0 else 0

    return {
        "annual_return": round(annual_return, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "calmar_ratio": round(calmar, 4),
        "sortino_ratio": round(sortino, 4),
        "win_rate": round(win_rate, 4),
        "annual_turnover": round(avg_turnover * ann_factor / trading_days * len(result.turnover_series), 4) if result.turnover_series is not None and len(result.turnover_series) > 0 else 0,
        "total_trades": len(result.trades),
    }


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

async def _write_results(conn, rid: uuid.UUID, metrics: dict, result, elapsed: int, start_dt: date, end_dt: date, factors: list[str]) -> None:
    """写入 backtest_run + backtest_trades + backtest_daily_nav。"""
    # 1. Update backtest_run
    await conn.execute(
        """
        UPDATE backtest_run SET
            status = 'completed',
            annual_return = $1, sharpe_ratio = $2, max_drawdown = $3,
            calmar_ratio = $4, sortino_ratio = $5, win_rate = $6,
            annual_turnover = $7, total_trades = $8,
            start_date = $9, end_date = $10, elapsed_sec = $11,
            factor_list = $12
        WHERE run_id = $13
        """,
        metrics.get("annual_return"), metrics.get("sharpe_ratio"),
        metrics.get("max_drawdown"), metrics.get("calmar_ratio"),
        metrics.get("sortino_ratio"), metrics.get("win_rate"),
        metrics.get("annual_turnover"), metrics.get("total_trades"),
        start_dt, end_dt, elapsed, factors, rid,
    )

    # 2. Insert backtest_trades
    if result.trades:
        trade_rows = []
        for fill in result.trades:
            slippage_bps = round(fill.slippage / fill.amount * 10000, 2) if fill.amount > 0 else 0
            trade_rows.append((
                rid, fill.trade_date, fill.trade_date, fill.code,
                fill.direction, fill.shares, round(fill.price, 4),
                slippage_bps, round(fill.commission, 4),
                round(fill.tax, 4), round(fill.total_cost, 4),
            ))
        await conn.executemany(
            """
            INSERT INTO backtest_trades
                (run_id, signal_date, exec_date, stock_code, side, shares,
                 exec_price, slippage_bps, commission, stamp_tax, total_cost)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            trade_rows,
        )

    # 3. Insert backtest_daily_nav
    nav = result.daily_nav
    bench_nav = result.benchmark_nav
    daily_rets = result.daily_returns
    if nav is not None and len(nav) > 0:
        nav_rows = []
        cummax = nav.cummax()
        dd = (nav - cummax) / cummax
        for dt in nav.index:
            n = float(nav[dt])
            dr = float(daily_rets[dt]) if dt in daily_rets.index else 0
            bn = float(bench_nav[dt]) if bench_nav is not None and dt in bench_nav.index else 1.0
            nav_rows.append((rid, dt, round(n, 2), round(dr, 6), round(bn, 4), round(float(dd[dt]), 6)))
        await conn.executemany(
            """
            INSERT INTO backtest_daily_nav (run_id, trade_date, nav, daily_return, benchmark_nav, drawdown)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (run_id, trade_date) DO NOTHING
            """,
            nav_rows,
        )

    logger.info("回测结果写入完成: %s, %d trades, %d nav points", rid, len(result.trades), len(nav) if nav is not None else 0)


async def _mark_failed(run_id: str, error_msg: str) -> None:
    """标记回测失败。"""
    import asyncpg
    try:
        conn = await asyncpg.connect(DB_URL)
        await conn.execute(
            "UPDATE backtest_run SET status = 'failed', error_message = $1 WHERE run_id = $2",
            error_msg, uuid.UUID(run_id),
        )
        await conn.close()
    except Exception as exc:
        logger.error("_mark_failed error: %s", exc)
