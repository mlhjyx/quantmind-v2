#!/usr/bin/env python3
"""Multi-date SDK parity scan — MVP 3.3 batch 2 Step 2.5 pre-flip 验证.

跑 N 个历史 trade_date, 每天调一次 PlatformSignalPipeline.generate(s1, ctx)
+ 老 SignalService.generate_signals(dry_run=True), 比对 codes + weight 数值.
N 天全 PASS = production flip SDK_PARITY_STRICT=true 的高置信度证据.

用法:
  python scripts/sdk_parity_scan.py                          # 默认: 过去 14 个交易日
  python scripts/sdk_parity_scan.py --start 2026-04-07 --end 2026-04-24
  python scripts/sdk_parity_scan.py --dates 2026-04-22,2026-04-23,2026-04-24

Exit code:
  0 — 全 PASS (codes 一致 + max_w_diff <= 1e-6 across all dates)
  1 — 任 1 天 DIFF (codes 或 weight)
  2 — 设置/数据加载错误 (factor_values 无数据等)

无 DB 写: SignalService.generate_signals(dry_run=True) + 不调 save_daily_factors.

# TODO(mvp-3-3-stage3): delete this file once SDK_PARITY_STRICT cut-over is complete
# (legacy compose path removed, parity check no longer needed).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 镜像 run_paper_trading.py:32-33 路径设置
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engines.signal_engine import PAPER_TRADING_CONFIG  # noqa: E402
from run_backtest import load_factor_values, load_industry, load_universe  # noqa: E402
from run_paper_trading import _build_sdk_strategy_context  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.db import get_sync_conn  # noqa: E402
from app.services.signal_service import SignalService  # noqa: E402
from app.services.trading_calendar import is_trading_day  # noqa: E402
from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking  # noqa: E402
from backend.qm_platform.signal.pipeline import PlatformSignalPipeline  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,  # 安静模式, 仅 ERROR/WARN 出
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sdk_parity_scan")


# ─── Result types ───────────────────────────────────────────


@dataclass(frozen=True)
class ParityResult:
    """单 trade_date scan 结果. frozen — 写一次读多次, 防 callsite 误改."""
    trade_date: date
    status: Literal["OK", "DIFF", "ERROR"]
    sdk_count: int
    legacy_count: int
    codes_diff_count: int  # symmetric_difference 大小
    max_w_diff: float
    sdk_total_w: float
    legacy_total_w: float
    detail: str  # PASS/DIFF reason 或 error msg


# ─── Single trade_date scan ─────────────────────────────────


def scan_one_date(trade_date: date, conn) -> ParityResult:
    """跑单日 SDK vs legacy parity. 镜像 run_paper_trading._run_sdk_parity_dryrun
    + run_signal_phase 的 Step 3 数据加载. 不写 DB.

    Returns:
        ParityResult 含 status + 比对数字.

    Raises:
        无 — 异常包成 ParityResult(status='ERROR').
    """
    try:
        # Step 3 数据加载 (镜像 run_signal_phase L524-526)
        fv = load_factor_values(trade_date, conn)
        if fv is None or fv.empty:
            return ParityResult(
                trade_date=trade_date,
                status="ERROR",
                sdk_count=0,
                legacy_count=0,
                codes_diff_count=0,
                max_w_diff=0.0,
                sdk_total_w=0.0,
                legacy_total_w=0.0,
                detail=f"factor_values 无数据 (trade_date={trade_date})",
            )
        universe = load_universe(trade_date, conn)
        industry = load_industry(conn)

        # Legacy compose (dry_run=True 不写 DB)
        signal_svc = SignalService()
        signal_result = signal_svc.generate_signals(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            trade_date=trade_date,
            factor_df=fv,
            universe=universe,
            industry=industry,
            config=PAPER_TRADING_CONFIG,
            dry_run=True,
        )
        legacy_target_weights = signal_result.target_weights

        # SDK 路径 (镜像 _run_sdk_parity_dryrun L240-285)
        ln_mcap = None
        if PAPER_TRADING_CONFIG.size_neutral_beta > 0:
            from engines.size_neutral import (
                load_ln_mcap_for_date,  # noqa: PLC0415 — 条件 lazy (gated on size_neutral_beta>0)
            )
            ln_mcap = load_ln_mcap_for_date(trade_date, conn)
        prev_holdings = signal_svc._load_prev_weights(  # noqa: SLF001 — 镜像 production 同源
            conn, settings.PAPER_STRATEGY_ID,
        )

        ctx = _build_sdk_strategy_context(
            trade_date=trade_date,
            factor_df=fv,
            universe=universe,
            industry=industry,
            capital=Decimal(str(settings.PAPER_INITIAL_CAPITAL)),
            ln_mcap=ln_mcap,
            prev_holdings=prev_holdings,
        )
        pipe = PlatformSignalPipeline()
        sdk_signals = pipe.generate(S1MonthlyRanking(), ctx)

        # 比对 (镜像 _run_sdk_parity_dryrun L287-333)
        sdk_weight_map = {s.code: s.target_weight for s in sdk_signals}
        sdk_codes = set(sdk_weight_map.keys())
        legacy_codes = set(legacy_target_weights.keys())
        codes_diff = sdk_codes.symmetric_difference(legacy_codes)
        sdk_total_w = sum(sdk_weight_map.values())
        legacy_total_w = sum(legacy_target_weights.values())

        if codes_diff:
            return ParityResult(
                trade_date=trade_date,
                status="DIFF",
                sdk_count=len(sdk_codes),
                legacy_count=len(legacy_codes),
                codes_diff_count=len(codes_diff),
                max_w_diff=0.0,
                sdk_total_w=sdk_total_w,
                legacy_total_w=legacy_total_w,
                detail=f"codes DIFF sample={sorted(codes_diff)[:10]}",
            )

        common_codes = sdk_codes & legacy_codes
        weight_diffs = [
            abs(sdk_weight_map[code] - legacy_target_weights[code])
            for code in common_codes
        ]
        max_w_diff = max(weight_diffs) if weight_diffs else 0.0

        if max_w_diff > 1e-6:
            return ParityResult(
                trade_date=trade_date,
                status="DIFF",
                sdk_count=len(sdk_codes),
                legacy_count=len(legacy_codes),
                codes_diff_count=0,
                max_w_diff=max_w_diff,
                sdk_total_w=sdk_total_w,
                legacy_total_w=legacy_total_w,
                detail=f"weight DIFF max_w_diff={max_w_diff:.6f}",
            )

        return ParityResult(
            trade_date=trade_date,
            status="OK",
            sdk_count=len(sdk_codes),
            legacy_count=len(legacy_codes),
            codes_diff_count=0,
            max_w_diff=max_w_diff,
            sdk_total_w=sdk_total_w,
            legacy_total_w=legacy_total_w,
            detail=f"PASS codes={len(sdk_codes)} max_w_diff={max_w_diff:.2e}",
        )
    except Exception as e:  # noqa: BLE001 — scan 工具, 单日 fail 不阻其他日
        # P3 reviewer 采纳: 完整 traceback 打 stderr 协助 debug, ParityResult.detail
        # 仍存简洁 type+msg 供表格展示.
        print(
            f"\n[scan_one_date] {trade_date} traceback:\n"
            f"{traceback.format_exc()}",
            file=sys.stderr,
        )
        return ParityResult(
            trade_date=trade_date,
            status="ERROR",
            sdk_count=0,
            legacy_count=0,
            codes_diff_count=0,
            max_w_diff=0.0,
            sdk_total_w=0.0,
            legacy_total_w=0.0,
            detail=f"{type(e).__name__}: {e}",
        )


# ─── Date range expansion ───────────────────────────────────


def expand_trade_dates(start: date, end: date, conn) -> list[date]:
    """[start, end] 闭区间内 is_trading_day 过滤."""
    dates: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(conn, cur):
            dates.append(cur)
        cur += timedelta(days=1)
    return dates


# ─── CLI ────────────────────────────────────────────────────

# 历史 trade_date floor: factor_values 早期数据不完整, 防 last-N 误穿
_LAST_N_FLOOR = date(2024, 1, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        help="起始 trade_date YYYY-MM-DD (含). 与 --end 联用 (单独使用报错).",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        help="终止 trade_date YYYY-MM-DD (含). 与 --start 联用 (单独使用报错).",
    )
    parser.add_argument(
        "--dates",
        help="逗号分隔 trade_dates: 2026-04-22,2026-04-23 "
             "(与 --start/--end 互斥, 同时给报错).",
    )
    parser.add_argument(
        "--last-n",
        type=int,
        default=14,
        help=f"无 --start/--end/--dates 时, 跑过去 N 个交易日 "
             f"(默认 14, floor={_LAST_N_FLOOR.isoformat()}: 早期 factor_values 不完整).",
    )
    args = parser.parse_args()

    # P2 reviewer 采纳: argparse 互斥 + 部分参数显式守卫
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be used together")
    if args.dates and (args.start or args.end):
        parser.error("--dates and --start/--end are mutually exclusive")

    # P2 reviewer 采纳: try/finally 保连接释放, 短时脚本也走纪律
    conn = get_sync_conn()
    try:
        conn.autocommit = True
        return _run_scan(args, conn)
    finally:
        conn.close()


def _run_scan(args: argparse.Namespace, conn) -> int:
    """Resolve trade_dates → loop scan_one_date → 汇总. main() 提取出来便于 try/finally."""
    # Resolve trade_dates
    if args.dates:
        raw_dates = [
            date.fromisoformat(d.strip())
            for d in args.dates.split(",")
            if d.strip()
        ]
        # P3 reviewer 采纳: 非交易日不静默走 ERROR (factor_values 必空), 改 stderr 警告 + skip
        dates = []
        for d in raw_dates:
            if is_trading_day(conn, d):
                dates.append(d)
            else:
                print(f"[scan] {d} 非交易日, skip", file=sys.stderr)
    elif args.start and args.end:
        dates = expand_trade_dates(args.start, args.end, conn)
    else:
        # last-N 模式: 从今天往前找 N 个 is_trading_day
        dates = []
        cur = date.today()
        while len(dates) < args.last_n and cur >= _LAST_N_FLOOR:
            if is_trading_day(conn, cur):
                dates.append(cur)
            cur -= timedelta(days=1)
        if len(dates) < args.last_n:
            print(
                f"[scan] last-n={args.last_n} 但仅找到 {len(dates)} 个交易日 "
                f"(撞 floor {_LAST_N_FLOOR.isoformat()}, 历史扫请用 --start/--end).",
                file=sys.stderr,
            )
        dates.reverse()  # 时间正序

    if not dates:
        print("[scan] 0 trade_dates 待扫, 退出.", file=sys.stderr)
        return 2

    print(f"[scan] {len(dates)} trade_dates: {dates[0]} ~ {dates[-1]}", file=sys.stderr)
    # 表格行 → stdout (可 pipe/grep), 操作消息 → stderr (诊断不污染 stdout pipeline)
    print("=" * 80)
    print(f"{'trade_date':<12} {'status':<6} {'sdk':<5} {'legacy':<7} {'max_w_diff':<12} {'detail'}")
    print("-" * 80)

    results: list[ParityResult] = []
    for d in dates:
        r = scan_one_date(d, conn)
        results.append(r)
        print(
            f"{r.trade_date!s:<12} {r.status:<6} {r.sdk_count:<5} {r.legacy_count:<7} "
            f"{r.max_w_diff:<12.6e} {r.detail}",
        )
        sys.stdout.flush()

    print("-" * 80)
    n_ok = sum(1 for r in results if r.status == "OK")
    n_diff = sum(1 for r in results if r.status == "DIFF")
    n_err = sum(1 for r in results if r.status == "ERROR")
    print(f"[scan] {n_ok}/{len(results)} OK / {n_diff} DIFF / {n_err} ERROR")
    print("=" * 80)

    if n_diff > 0:
        print(
            "\n⚠️  DIFF detected — STRICT flip blocked. Investigate:",
            file=sys.stderr,
        )
        for r in results:
            if r.status == "DIFF":
                print(f"  {r.trade_date}: {r.detail}", file=sys.stderr)
        return 1
    if n_err > 0 and n_ok == 0:
        print(
            "\n⚠️  All-ERROR — env / data / SDK import 可能问题, 不能从此推 parity 结论.",
            file=sys.stderr,
        )
        return 2
    if n_ok > 0:
        print(
            f"\n✅ {n_ok}/{len(results)} PASS — STRICT flip 高置信度证据 "
            f"({n_err} ERROR, 多为节假日 factor_values 缺数据).",
        )
        return 0
    return 2  # all-ERROR fallback


if __name__ == "__main__":
    sys.exit(main())
