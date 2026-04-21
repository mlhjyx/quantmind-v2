"""每日增量 IC 计算 + factor_ic_history 入库 (铁律 11 + 17 + 19 合规).

**Session 21 加时 (2026-04-21)**: 诊断 factor_ic_history MAX(trade_date) = 2026-04-07,
14 天零入库 (铁律 11 违反). 根因: 仅有 `fast_ic_recompute.py` (12 年全量, 无 daily
入口 + 违 铁律 17 裸 INSERT), 无 daily 增量工具 + 无 Celery/schtasks wire.

本脚本是**每日增量**入口:
- 直读 DB (不依赖 cache/backtest 可能过期, 如 Session 21 实测 cache 4-15 stale)
- 近 N 天 (default 30) 滚动窗口, 每跑一次 upsert 该窗口所有 factor × date
- HORIZONS = [1, 5, 10, 20], 对应 factor_ic_history.ic_{1,5,10,20}d + abs 列
- 走 DataPipeline.ingest(FACTOR_IC_HISTORY) 铁律 17 合规
- 调用 engines.ic_calculator 统一口径 (铁律 19: neutral_value_T1_excess_spearman)

**Scope (v1)**: 只写 ic_1d/5d/10d/20d + ic_abs_{1,5}d. 不计算 ic_ma20/ic_ma60/decay_level
(需跨 60 日 rolling, 独立脚本处理). factor_lifecycle 需 ic_ma20/60, 未来 Phase 2 再补.

Usage:
    python scripts/compute_daily_ic.py                    # 近 30 天 + 所有 active factors
    python scripts/compute_daily_ic.py --days 60          # 自定义窗口 (Session 22 backfill)
    python scripts/compute_daily_ic.py --factors bp_ratio,dv_ttm  # 指定 factors
    python scripts/compute_daily_ic.py --core             # 仅 CORE 3+dv_ttm
    python scripts/compute_daily_ic.py --dry-run          # 不入库
    python scripts/compute_daily_ic.py --verbose          # 详细日志

Cron (Session 22+):
    Windows Task Scheduler daily Mon-Fri 18:00 (after 17:40 quality_report,
    before 20:00 ic_monitor, 留 1h buffer 给周五 19:00 factor_lifecycle).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# .venv/.pth 已把 backend 加入 sys.path. 不用 insert(0) 避免与 stdlib `platform`
# 冲突 (铁律 10b shadow fix: backend/platform/ 会 shadow stdlib platform)
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

import pandas as pd  # noqa: E402
from engines.ic_calculator import (  # noqa: E402
    IC_CALCULATOR_ID,
    IC_CALCULATOR_VERSION,
    compute_forward_excess_returns,
    compute_ic_series,
)

from app.data_fetcher.contracts import FACTOR_IC_HISTORY  # noqa: E402
from app.data_fetcher.pipeline import DataPipeline  # noqa: E402
from app.services.db import get_sync_conn  # noqa: E402

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "compute_daily_ic.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)

CORE_FACTORS = ("turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm")
HORIZONS = (1, 5, 10, 20)
BENCHMARK_CODE = "000300.SH"  # CSI300
# IC 计算需要 T+1..T+horizon 的未来价格, horizon=20 → 额外多拉 25 天 buffer
FUTURE_BUFFER_DAYS = 25


def _fetch_active_factors(conn) -> list[str]:
    """从 factor_registry 读 active/warning 因子.

    retired 因子跳过 (不再计算 IC). status 未在 ('active', 'warning') 的也跳过.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM factor_registry WHERE status IN ('active', 'warning') ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]


def _load_prices(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """klines_daily (code, trade_date, adj_close) 含未来 buffer.

    adj_close = close × adj_factor (前复权).
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT code, trade_date, close, adj_factor
               FROM klines_daily
               WHERE trade_date BETWEEN %s AND %s
                 AND close IS NOT NULL""",
            (start_date, end_date),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["code", "trade_date", "close", "adj_factor"])
    if df.empty:
        return df
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce").fillna(1.0)
    df["adj_close"] = df["close"] * df["adj_factor"]
    return df[["code", "trade_date", "adj_close"]]


def _load_benchmark(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """index_daily CSI300 (trade_date, close)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT trade_date, close FROM index_daily
               WHERE index_code = %s AND trade_date BETWEEN %s AND %s""",
            (BENCHMARK_CODE, start_date, end_date),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["trade_date", "close"])
    if df.empty:
        raise RuntimeError(
            f"index_daily 无 {BENCHMARK_CODE} 数据 in [{start_date}, {end_date}] — "
            "IC 计算需 benchmark, 请先补 index_daily"
        )
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


def _load_factor(conn, factor_name: str, start_date: date, end_date: date) -> pd.DataFrame:
    """factor_values.neutral_value 单因子窗口数据."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT code, trade_date, neutral_value
               FROM factor_values
               WHERE factor_name = %s
                 AND trade_date BETWEEN %s AND %s
                 AND neutral_value IS NOT NULL""",
            (factor_name, start_date, end_date),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["code", "trade_date", "neutral_value"])
    if df.empty:
        return df
    df["neutral_value"] = pd.to_numeric(df["neutral_value"], errors="coerce")
    return df.dropna(subset=["neutral_value"])


def _compute_factor_ic(
    factor_df: pd.DataFrame, fwd_rets_by_horizon: dict[int, pd.DataFrame]
) -> pd.DataFrame:
    """单因子 × 多 horizon → (trade_date, ic_1d, ic_5d, ic_10d, ic_20d).

    缺数据 horizon 列填 NaN. ic_abs_{1,5}d 由 abs() 派生.
    """
    if factor_df.empty:
        return pd.DataFrame()

    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values="neutral_value", aggfunc="last"
    ).sort_index()

    result = pd.DataFrame(index=factor_wide.index)
    for h in HORIZONS:
        ic_series = compute_ic_series(factor_wide, fwd_rets_by_horizon[h])
        result[f"ic_{h}d"] = ic_series

    result["ic_abs_1d"] = result["ic_1d"].abs()
    result["ic_abs_5d"] = result["ic_5d"].abs()
    return result.reset_index()


def compute_and_ingest(
    days: int = 30,
    factors: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """主入口: 近 N 天滚动窗口 → 所有 active 因子 → factor_ic_history.

    Args:
        days: 回溯天数 (包含今日). 近 N 天计算 IC.
        factors: None 时读 factor_registry active/warning. 否则限定列表.
        dry_run: True 不入库, 仅报告.

    Returns:
        dict(processed_factors, total_rows, elapsed_sec, factor_summary)
    """
    conn = get_sync_conn()
    try:
        # 窗口边界: 因子 IC 需 T+1..T+horizon 未来价, 所以价格/benchmark 多拉 FUTURE_BUFFER_DAYS
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        price_end = end_date + timedelta(days=FUTURE_BUFFER_DAYS)

        t0 = time.time()
        logger.info(
            "[daily_ic] 窗口 [%s, %s], price_end=%s, horizons=%s",
            start_date, end_date, price_end, HORIZONS,
        )
        logger.info("[daily_ic] IC 口径: %s v%s", IC_CALCULATOR_ID, IC_CALCULATOR_VERSION)

        # Step 1: 确定 factor 列表
        if factors is None:
            factors = _fetch_active_factors(conn)
        logger.info("[daily_ic] 目标 factors: %d 个", len(factors))
        if not factors:
            logger.warning("[daily_ic] 无 active factor, 退出")
            return {
                "processed_factors": 0, "total_rows": 0, "elapsed_sec": 0,
                "factor_summary": [],
            }

        # Step 2: 加载 price + benchmark (共享)
        logger.info("[daily_ic] 加载 klines_daily [%s, %s]...", start_date, price_end)
        price_df = _load_prices(conn, start_date, price_end)
        logger.info("[daily_ic]   rows=%d, codes=%d", len(price_df), price_df["code"].nunique())

        logger.info("[daily_ic] 加载 index_daily %s...", BENCHMARK_CODE)
        bench_df = _load_benchmark(conn, start_date, price_end)
        logger.info("[daily_ic]   rows=%d", len(bench_df))

        # Step 3: 预计算 4 horizons forward excess returns (所有因子复用)
        t_fwd = time.time()
        fwd_rets_by_horizon = {
            h: compute_forward_excess_returns(price_df, bench_df, horizon=h, price_col="adj_close")
            for h in HORIZONS
        }
        logger.info("[daily_ic]   fwd_rets 4 horizons 耗时 %.1fs", time.time() - t_fwd)

        # Step 4: 逐因子计算 IC + 累积 DataFrame
        pipeline = DataPipeline(conn=conn)
        all_ic_frames: list[pd.DataFrame] = []
        factor_summary = []
        for i, fname in enumerate(factors, 1):
            t_f = time.time()
            factor_df = _load_factor(conn, fname, start_date, end_date)
            if factor_df.empty:
                logger.info("[daily_ic] [%d/%d] %s: SKIP (no factor_values)", i, len(factors), fname)
                factor_summary.append({"factor": fname, "rows": 0, "status": "no_data"})
                continue
            ic_df = _compute_factor_ic(factor_df, fwd_rets_by_horizon)
            if ic_df.empty:
                logger.info("[daily_ic] [%d/%d] %s: SKIP (empty IC)", i, len(factors), fname)
                factor_summary.append({"factor": fname, "rows": 0, "status": "empty_ic"})
                continue
            ic_df["factor_name"] = fname
            all_ic_frames.append(ic_df)
            # 快速摘要 (最新一行)
            latest = ic_df.iloc[-1]
            logger.info(
                "[daily_ic] [%d/%d] %s: rows=%d latest ic_20d=%s (%.2fs)",
                i, len(factors), fname, len(ic_df),
                f"{latest['ic_20d']:.4f}" if pd.notna(latest["ic_20d"]) else "NaN",
                time.time() - t_f,
            )
            factor_summary.append({
                "factor": fname, "rows": len(ic_df),
                "latest_ic_20d": float(latest["ic_20d"]) if pd.notna(latest["ic_20d"]) else None,
                "status": "ok",
            })

        if not all_ic_frames:
            logger.warning("[daily_ic] 0 因子可入库, 退出")
            return {
                "processed_factors": 0, "total_rows": 0,
                "elapsed_sec": time.time() - t0, "factor_summary": factor_summary,
            }

        combined = pd.concat(all_ic_frames, ignore_index=True)
        logger.info("[daily_ic] 合并 %d 行 across %d 因子", len(combined), len(all_ic_frames))

        # Step 5: 入库 (铁律 17 DataPipeline)
        if dry_run:
            logger.info("[daily_ic] [DRY-RUN] 跳过 ingest, 本应写 %d 行", len(combined))
            total_rows = 0
        else:
            result = pipeline.ingest(combined, FACTOR_IC_HISTORY)
            conn.commit()
            total_rows = result.upserted_rows
            logger.info(
                "[daily_ic] ingest: total=%d valid=%d upserted=%d rejected=%d",
                result.total_rows, result.valid_rows, result.upserted_rows, result.rejected_rows,
            )
            if result.rejected_rows > 0:
                logger.warning("[daily_ic]   reject_reasons=%s", result.reject_reasons)

        elapsed = time.time() - t0
        logger.info("[daily_ic] 完成: %d 因子 / %d 行 / %.1fs", len(all_ic_frames), total_rows, elapsed)
        return {
            "processed_factors": len(all_ic_frames),
            "total_rows": total_rows,
            "elapsed_sec": elapsed,
            "factor_summary": factor_summary,
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="回溯天数 (default 30)")
    parser.add_argument("--factors", type=str, help="逗号分隔 factor 列表 (覆盖 registry)")
    parser.add_argument("--core", action="store_true", help=f"仅 {len(CORE_FACTORS)} CORE: {CORE_FACTORS}")
    parser.add_argument("--dry-run", action="store_true", help="不入库, 仅报告")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.core:
        factors = list(CORE_FACTORS)
    elif args.factors:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]
    else:
        factors = None

    result = compute_and_ingest(days=args.days, factors=factors, dry_run=args.dry_run)
    logger.info(
        "[daily_ic] 结果: processed=%d total_rows=%d %.1fs",
        result["processed_factors"], result["total_rows"], result["elapsed_sec"],
    )
    return 0 if result["processed_factors"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
