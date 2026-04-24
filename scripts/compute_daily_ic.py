"""每日增量 IC 计算 + factor_ic_history 入库 (铁律 11 + 17 + 19 合规).

**Session 21 加时 (2026-04-21)**: 诊断 factor_ic_history MAX(trade_date) = 2026-04-07,
14 天零入库 (铁律 11 违反). 根因: 仅有 `fast_ic_recompute.py` (12 年全量, 无 daily
入口 + 违 铁律 17 裸 INSERT), 无 daily 增量工具 + 无 Celery/schtasks wire.

本脚本是**每日增量**入口:
- 直读 DB (不依赖 cache/backtest 可能过期, 如 Session 21 实测 cache 4-15 stale)
- 近 N 天 (default 30) 滚动窗口, 每跑一次 upsert 该窗口所有 factor × date
- HORIZONS = (5, 10, 20), 对应 factor_ic_history.ic_{5,10,20}d + ic_abs_5d
  (ic_1d 跳过: ic_calculator horizon=1 退化 entry==exit 全 0 IC, 写入无意义, reviewer P2)
- 走 DataPipeline.ingest(FACTOR_IC_HISTORY) 铁律 17 合规
- 调用 engines.ic_calculator 统一口径 (铁律 19: neutral_value_T1_excess_spearman)

**Scope (v1)**: 只写 ic_5d/10d/20d + ic_abs_5d. 不写 ic_ma20/ic_ma60/decay_level
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
import contextlib
import logging
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
import psycopg2.extensions  # noqa: E402
from engines.ic_calculator import (  # noqa: E402
    IC_CALCULATOR_ID,
    IC_CALCULATOR_VERSION,
    compute_forward_excess_returns,
    compute_ic_series,
)

from app.data_fetcher.contracts import FACTOR_IC_HISTORY  # noqa: E402
from app.data_fetcher.pipeline import DataPipeline  # noqa: E402
from app.services.db import get_sync_conn  # noqa: E402
from app.services.trading_calendar import is_trading_day  # noqa: E402

logger = logging.getLogger(__name__)

LOG_DIR = PROJECT_ROOT / "logs"


def _configure_logging() -> None:
    """延迟 logging 配置 (reviewer P3 采纳: 避免 import-time 副作用).

    import 时 LOG_DIR.mkdir + FileHandler 会在 pytest collect 阶段就创建目录.
    本 helper 只在 main() 运行时 (真跑, 非测试 import) 才调.
    """
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            # Session 26 LL-068 扩散: delay=True 防 Windows zombie 文件锁 (4-23 DataQualityCheck
            # 0-log 事故根因同类防御).
            logging.FileHandler(LOG_DIR / "compute_daily_ic.log", encoding="utf-8", delay=True),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


CORE_FACTORS = ("turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm")
# HORIZONS reviewer P2 采纳: 移除 1 (ic_calculator.compute_forward_excess_returns
# 用 entry=shift(-1) / exit=shift(-horizon), horizon=1 时 entry==exit 导致 stock_ret
# 全 0 → spearmanr 退化为 NaN, 写入 factor_ic_history.ic_1d 全 NULL 无意义. 保留
# 5/10/20 是 factor_ic_history schema 实际有语义的列.
HORIZONS = (5, 10, 20)
BENCHMARK_CODE = "000300.SH"  # CSI300
# IC 计算需 T+1..T+horizon 未来价. reviewer P2 采纳: horizon=20 trading days ≈ 28-30
# calendar days + 假期 buffer → 40 (max horizon × 2 安全边际).
FUTURE_BUFFER_DAYS = 40


def _fetch_active_factors(conn: psycopg2.extensions.connection) -> list[str]:
    """从 factor_registry 读 active/warning 因子.

    retired 因子跳过 (不再计算 IC). status 未在 ('active', 'warning') 的也跳过.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM factor_registry WHERE status IN ('active', 'warning') ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]


def _load_prices(
    conn: psycopg2.extensions.connection, start_date: date, end_date: date
) -> pd.DataFrame:
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


def _load_benchmark(
    conn: psycopg2.extensions.connection, start_date: date, end_date: date
) -> pd.DataFrame:
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


def _load_factor(
    conn: psycopg2.extensions.connection,
    factor_name: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
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
    """单因子 × 多 horizon → (trade_date, ic_{5,10,20}d).

    缺数据 horizon 列填 NaN. ic_abs_5d 由 abs() 派生 (ic_abs_1d 跳过 — HORIZONS 已去掉 1).
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

    # reviewer P2 采纳: ic_abs_1d 原依赖 ic_1d, 但 HORIZONS 去掉 1 后 ic_1d 不生成.
    # 只派生 ic_abs_5d (schema 保留此列). 其他 ic_abs 列保持 DB 现状 (多数历史 NULL).
    if "ic_5d" in result.columns:
        result["ic_abs_5d"] = result["ic_5d"].abs()
    return result.reset_index()


def compute_and_ingest(
    conn: psycopg2.extensions.connection,
    days: int = 30,
    factors: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """核心: 近 N 天滚动窗口 → 所有 active 因子 → factor_ic_history.

    **Transaction boundary (reviewer P1 铁律 32 采纳)**: 本函数不调 `conn.commit()` /
    `conn.close()`, 由 caller (main) 管理. 失败时 caller 决定 rollback / retry.

    Args:
        conn: sync psycopg2 connection (caller 负责生命周期)
        days: 回溯天数 (包含今日). 近 N 天计算 IC.
        factors: None 时读 factor_registry active/warning. 否则限定列表.
        dry_run: True 不入库, 仅报告. total_rows 返回 "would-write" 行数.

    Returns:
        {processed_factors, total_rows, elapsed_sec, factor_summary}
        dry_run=True 时 total_rows = 预计写入行数 (语义明确化 reviewer P3 采纳).
    """
    # 窗口边界: 因子 IC 需 T+1..T+horizon 未来价, 所以价格/benchmark 多拉 FUTURE_BUFFER_DAYS
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    price_end = end_date + timedelta(days=FUTURE_BUFFER_DAYS)

    t0 = time.time()
    logger.info(
        "[daily_ic] 窗口 [%s, %s], price_end=%s, horizons=%s",
        start_date,
        end_date,
        price_end,
        HORIZONS,
    )
    logger.info("[daily_ic] IC 口径: %s v%s", IC_CALCULATOR_ID, IC_CALCULATOR_VERSION)

    # Step 1: 确定 factor 列表
    if factors is None:
        factors = _fetch_active_factors(conn)
    logger.info("[daily_ic] 目标 factors: %d 个", len(factors))
    if not factors:
        logger.warning("[daily_ic] 无 active factor, 退出")
        return {
            "processed_factors": 0,
            "total_rows": 0,
            "elapsed_sec": 0.0,
            "factor_summary": [],
        }

    # Step 2: 加载 price + benchmark (共享)
    logger.info("[daily_ic] 加载 klines_daily [%s, %s]...", start_date, price_end)
    price_df = _load_prices(conn, start_date, price_end)
    logger.info("[daily_ic]   rows=%d, codes=%d", len(price_df), price_df["code"].nunique())

    logger.info("[daily_ic] 加载 index_daily %s...", BENCHMARK_CODE)
    bench_df = _load_benchmark(conn, start_date, price_end)
    logger.info("[daily_ic]   rows=%d", len(bench_df))

    # Step 3: 预计算 horizons forward excess returns (所有因子复用)
    t_fwd = time.time()
    fwd_rets_by_horizon = {
        h: compute_forward_excess_returns(price_df, bench_df, horizon=h, price_col="adj_close")
        for h in HORIZONS
    }
    logger.info("[daily_ic]   fwd_rets %d horizons 耗时 %.1fs", len(HORIZONS), time.time() - t_fwd)

    # Step 4: 逐因子计算 IC + 累积 DataFrame (reviewer P2 采纳: per-factor try/except 隔离)
    pipeline = DataPipeline(conn=conn)
    all_ic_frames: list[pd.DataFrame] = []
    factor_summary: list[dict[str, object]] = []
    for i, fname in enumerate(factors, 1):
        t_f = time.time()
        try:
            factor_df = _load_factor(conn, fname, start_date, end_date)
            if factor_df.empty:
                logger.info(
                    "[daily_ic] [%d/%d] %s: SKIP (no factor_values)", i, len(factors), fname
                )
                factor_summary.append({"factor": fname, "rows": 0, "status": "no_data"})
                continue
            ic_df = _compute_factor_ic(factor_df, fwd_rets_by_horizon)
            if ic_df.empty:
                logger.info("[daily_ic] [%d/%d] %s: SKIP (empty IC)", i, len(factors), fname)
                factor_summary.append({"factor": fname, "rows": 0, "status": "empty_ic"})
                continue
            ic_df["factor_name"] = fname
            all_ic_frames.append(ic_df)
            # 快速摘要 (最新一行). reviewer P2 采纳: 提出 f-string 到局部变量避免 logger 内部 lazy eval 问题.
            latest = ic_df.iloc[-1]
            latest_ic_20d_str = (
                f"{latest['ic_20d']:.4f}"
                if "ic_20d" in ic_df.columns and pd.notna(latest["ic_20d"])
                else "NaN"
            )
            logger.info(
                "[daily_ic] [%d/%d] %s: rows=%d latest ic_20d=%s (%.2fs)",
                i,
                len(factors),
                fname,
                len(ic_df),
                latest_ic_20d_str,
                time.time() - t_f,
            )
            latest_ic_20d_val = (
                float(latest["ic_20d"])
                if "ic_20d" in ic_df.columns and pd.notna(latest["ic_20d"])
                else None
            )
            factor_summary.append(
                {
                    "factor": fname,
                    "rows": len(ic_df),
                    "latest_ic_20d": latest_ic_20d_val,
                    "status": "ok",
                }
            )
        except Exception as e:
            # 铁律 33 fail-loud: 单因子异常记 error + 继续下一因子 (不阻断全 batch)
            logger.error(
                "[daily_ic] [%d/%d] %s: ERROR %s",
                i,
                len(factors),
                fname,
                str(e)[:200],
                exc_info=True,
            )
            factor_summary.append(
                {"factor": fname, "rows": 0, "status": "error", "error": str(e)[:200]}
            )

    if not all_ic_frames:
        logger.warning("[daily_ic] 0 因子可入库, 退出")
        return {
            "processed_factors": 0,
            "total_rows": 0,
            "elapsed_sec": time.time() - t0,
            "factor_summary": factor_summary,
        }

    combined = pd.concat(all_ic_frames, ignore_index=True)
    logger.info("[daily_ic] 合并 %d 行 across %d 因子", len(combined), len(all_ic_frames))

    # Step 5: 入库 (铁律 17 DataPipeline). commit 由 caller 管理 (铁律 32).
    if dry_run:
        logger.info("[daily_ic] [DRY-RUN] 跳过 ingest, 本应写 %d 行", len(combined))
        total_rows = len(combined)  # reviewer P3 采纳: dry_run 返回 would-write 行数
    else:
        result = pipeline.ingest(combined, FACTOR_IC_HISTORY)
        total_rows = result.upserted_rows
        logger.info(
            "[daily_ic] ingest: total=%d valid=%d upserted=%d rejected=%d",
            result.total_rows,
            result.valid_rows,
            result.upserted_rows,
            result.rejected_rows,
        )
        if result.rejected_rows > 0:
            logger.warning("[daily_ic]   reject_reasons=%s", result.reject_reasons)
        if result.null_ratio_warnings:
            logger.warning("[daily_ic]   null_ratio_warnings=%s", result.null_ratio_warnings)

    elapsed = time.time() - t0
    logger.info("[daily_ic] 完成: %d 因子 / %d 行 / %.1fs", len(all_ic_frames), total_rows, elapsed)
    return {
        "processed_factors": len(all_ic_frames),
        "total_rows": total_rows,
        "elapsed_sec": elapsed,
        "factor_summary": factor_summary,
    }


def _run(args: argparse.Namespace) -> int:
    """主流程 (顶层 try/except 由 main 包裹, LL-068 pattern 扩散)."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.core:
        factors: list[str] | None = list(CORE_FACTORS)
    elif args.factors:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]
    else:
        factors = None

    # Transaction boundary (铁律 32): script 作为 caller 管理 conn + commit + close
    conn = get_sync_conn()
    try:
        # reviewer code-MED-2: SET cursor 移 try 内部, 防 SET raise 时 conn leak
        # (finally 只在 try 进入后 close conn, SET 若在 try 外 raise 会跳过 close).
        # reviewer python-P1: parametrize %s 替 f-string, 风格对齐 pt_watchdog.
        # reviewer python-P3: 变量名 _cur_timeout 下划线误导 (local 非 private 非 unused).
        # LL-068 扩散: session-level statement_timeout 60s, 防 cold-cache / lock hang
        # 被 schtask 5min ExecutionTimeLimit kill (data_quality_check 4-22/4-23 同类).
        with conn.cursor() as cur_timeout:
            cur_timeout.execute("SET statement_timeout = %s", (60_000,))
        # Holiday guard (PR #40 P2.2 follow-up): A 股非交易日提前 exit 0.
        if not args.force:
            # 铁律 41: 用 Asia/Shanghai 避免 date.today() 在 UTC 服务器 18:00 CST
            # 解析为前一日 (reviewer P2.1). 中国无 DST, offset 稳定 +08:00.
            today = datetime.now(tz=ZoneInfo("Asia/Shanghai")).date()
            if not is_trading_day(conn, today):
                logger.info("[daily_ic] %s 非 A 股交易日, skip (use --force 覆盖)", today)
                return 0

        result = compute_and_ingest(
            conn=conn,
            days=args.days,
            factors=factors,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            conn.commit()
        logger.info(
            "[daily_ic] 结果: processed=%d total_rows=%d %.1fs",
            result["processed_factors"],
            result["total_rows"],
            result["elapsed_sec"],
        )
        return 0 if result["processed_factors"] > 0 else 1
    except Exception:
        conn.rollback()
        logger.exception("[daily_ic] 异常, rollback")
        raise
    finally:
        conn.close()


def main() -> int:
    """Script entry: owns connection lifecycle + transaction (铁律 32).

    Session 26 LL-068 pattern 扩散: boot stderr probe + 顶层 try/except → exit(2)
    fail-loud (防 logger 失败 / schtask 无任何告警痕迹).
    """
    # Fail-loud boot 探针 (reviewer python-P2: os 已 module-top import, 删局部 import)
    print(
        f"[compute_daily_ic] boot {datetime.now().isoformat()} pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )
    _configure_logging()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="回溯天数 (default 30)")
    # reviewer P2 采纳: --factors / --core mutually exclusive (原来 if-elif 静默忽略)
    factor_group = parser.add_mutually_exclusive_group()
    factor_group.add_argument("--factors", type=str, help="逗号分隔 factor 列表 (覆盖 registry)")
    factor_group.add_argument(
        "--core", action="store_true", help=f"仅 {len(CORE_FACTORS)} CORE: {CORE_FACTORS}"
    )
    parser.add_argument("--dry-run", action="store_true", help="不入库, 仅报告")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    # PR #40 P2.2 follow-up (Session 22 Part 4): A 股节假日 (5/1 劳动节 / 国庆 / 春节)
    # schtask Mon-Fri 触发会在假日当天空跑. is_trading_day guard 提前退出.
    # trading_calendar.is_trading_day 多层 fallback (本地 DB → Tushare API → 启发式).
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖 is_trading_day guard (default: 非交易日提前 exit 0). 手动 backfill 用.",
    )
    args = parser.parse_args()

    try:
        return _run(args)
    except Exception as e:
        msg = f"[compute_daily_ic] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功 (铁律 33-d).
        # reviewer python-P2: traceback / contextlib 已 module-top import, 删局部.
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
