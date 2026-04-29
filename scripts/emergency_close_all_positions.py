#!/usr/bin/env python3
"""紧急清仓全部 live 持仓 (Session 44, 2026-04-29).

触发: PT live 风控失效, 卓然 (688121) -29.17% / 南玻 (000012) -9.75% 已用户手工卖.
本脚本清仓剩余 17 股, 暂停 PT 直到风控修补 (MVP 3.1b Phase 1+2).

设计原则 (真金 script 安全规范):
  - 默认 DRY-RUN (无 --execute flag = 仅列清单, 不发单)
  - --execute 显式 flag + 二次 'YES SELL ALL' input prompt 防 typo
  - 走现有 broker_qmt.QMTBroker.place_order (复用生产代码, 不重写 xtquant)
  - 市价单 SH=MARKET_SH_CONVERT_5_CANCEL / SZ=MARKET_SZ_CONVERT_5_CANCEL (清仓最快撮合)
  - 实时从 QMT query_positions (非 DB snapshot, 防 4-28 stale 与 4-29 实时差异)
  - 全程日志 logs/emergency_close_YYYYMMDD_HHMMSS.log

用法:
  # 1. 先 dry-run 看清单
  python scripts/emergency_close_all_positions.py
  # 2. 看清单 OK 后真执行
  python scripts/emergency_close_all_positions.py --execute

Output:
  - 清单 stdout (每股 code/qty/predicted_fill_price)
  - 日志文件 logs/emergency_close_*.log
  - DRY-RUN 模式不发任何单
  - --execute 模式发单后打印 order_id 列表 + summary
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402

# ── 日志 ──
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"emergency_close_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def _resolve_positions_via_qmt() -> list[dict]:
    """实时从 QMT 查 live account 持仓 (非 DB snapshot, 防 stale).

    Returns:
        list of dict: {code, quantity, can_use_quantity, avg_cost, market_value, ...}
    """
    # 关键: xtquant 不在标准 python path, 需走 ensure_xtquant_path() (CLAUDE.md 铁律)
    from app.core.xtquant_path import ensure_xtquant_path

    ensure_xtquant_path()
    from engines.broker_qmt import MiniQMTBroker

    broker = MiniQMTBroker(
        qmt_path=settings.QMT_PATH,
        account_id=settings.QMT_ACCOUNT_ID,
    )
    broker.connect()
    if not broker.is_connected:
        raise RuntimeError("QMTBroker connect 失败 (路径或账户错)")
    logger.info(
        "[QMT] connected: path=%s account=%s",
        settings.QMT_PATH,
        settings.QMT_ACCOUNT_ID,
    )
    positions = broker.query_positions()
    logger.info("[QMT] query_positions: %d 持仓", len(positions))
    return positions, broker


def _classify_market(code: str) -> str:
    """返 'SH' / 'SZ' / 'BJ' / 'UNKNOWN' (清仓必须 SH/SZ, BJ 北交所手工)."""
    if code.endswith(".SH"):
        return "SH"
    if code.endswith(".SZ"):
        return "SZ"
    if code.endswith(".BJ"):
        return "BJ"
    return "UNKNOWN"


def _fetch_market_price(code: str) -> float | None:
    """从 Redis market:latest:{code} 读最新成交价 (无价返 None, 仅做估算用)."""
    try:

        from app.core.qmt_client import _get_redis_client

        client = _get_redis_client()
        raw = client.get(f"market:latest:{code}")
        if raw is None:
            return None
        import json

        data = json.loads(raw)
        return float(data.get("last_price") or data.get("price") or 0.0) or None
    except Exception as e:  # noqa: BLE001
        logger.debug("Redis 读价失败 %s: %s", code, e)
        return None


def _print_plan(positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """打印清单 + 估算成交额, 返 (sellable, skipped) 分类."""
    sellable: list[dict] = []
    skipped: list[dict] = []

    print("\n" + "=" * 80)
    print(f"  Emergency Close-All Plan (account={settings.QMT_ACCOUNT_ID})")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print(
        f"  {'Code':12} {'Qty':>8} {'Avail':>8} {'AvgCost':>10} "
        f"{'Latest':>10} {'EstFillVal':>12} {'Market':6} {'Status':12}"
    )
    print("-" * 80)

    total_est_value = 0.0
    for p in positions:
        # broker_qmt.query_positions 字段名 (从 backend/engines/broker_qmt.py:340 文档):
        #   stock_code / volume / can_use_volume / avg_price / market_value
        code = str(p.get("stock_code") or p.get("code") or "")
        qty = int(p.get("volume") or p.get("quantity") or 0)
        avail = int(p.get("can_use_volume") or p.get("can_use_quantity") or qty)
        avg_cost = float(p.get("avg_price") or p.get("avg_cost") or 0.0)

        if qty <= 0:
            skipped.append({**p, "_reason": "quantity=0"})
            continue

        market = _classify_market(code)
        latest = _fetch_market_price(code)
        est_fill_val = (latest or avg_cost) * qty
        total_est_value += est_fill_val

        # BJ 不卖 (xtquant 五档撮合不支持北交所), 标 skipped 让用户手工 QMT
        if market == "BJ":
            skipped.append({**p, "_reason": "BJ 北交所市价单 xtquant 不撮合, 手工 QMT"})
            status = "SKIP_BJ"
        elif market == "UNKNOWN":
            skipped.append({**p, "_reason": f"unknown market suffix: {code}"})
            status = "SKIP_UNK"
        elif avail < qty:
            # 部分可用 (e.g. T+1 限制), 仅卖 avail
            sellable.append({**p, "code": code, "sellable_qty": avail})
            status = "T+1 PART"
        else:
            sellable.append({**p, "code": code, "sellable_qty": qty})
            status = "OK"

        print(
            f"  {code:12} {qty:>8} {avail:>8} {avg_cost:>10.4f} "
            f"{(latest or 0.0):>10.4f} {est_fill_val:>12,.2f} {market:>6} {status:>12}"
        )

    print("-" * 80)
    print(f"  Sellable: {len(sellable)} stocks  |  Skipped: {len(skipped)} stocks")
    print(f"  Estimated total fill value: {total_est_value:,.2f}")
    print("=" * 80 + "\n")

    return sellable, skipped


def _confirm_execute() -> bool:
    """二次 confirmation prompt 防 typo 误触发真单."""
    print("\n" + "!" * 80)
    print("  ⚠️  REAL ORDER EXECUTION REQUESTED  ⚠️")
    print(f"  Account: {settings.QMT_ACCOUNT_ID} (LIVE)")
    print("  Action: place sell-market orders for all sellable positions")
    print("!" * 80)
    print(
        "\nType exactly 'YES SELL ALL' (no quotes) to confirm execution, "
        "or anything else to abort:"
    )
    try:
        response = input(">>> ").strip()
    except EOFError:
        logger.error("[Abort] EOF on confirmation input — aborting (likely non-tty)")
        return False
    return response == "YES SELL ALL"


def _execute_sells(broker, sellable: list[dict]) -> dict:
    """真发卖单 (market price). 返 summary dict."""
    from time import sleep

    submitted: list[dict] = []
    failed: list[dict] = []

    for item in sellable:
        code = item["code"]
        qty = int(item["sellable_qty"])
        if qty <= 0:
            failed.append({**item, "_error": "sellable_qty=0"})
            continue

        try:
            order_id = broker.place_order(
                code=code,
                direction="sell",
                volume=qty,
                price=None,  # 市价单
                price_type="market",
                remark="emergency_close_s44",
            )
            if order_id is None or order_id < 0:
                failed.append({**item, "_error": f"place_order returned {order_id}"})
                logger.error("[Order] FAILED: %s qty=%d order_id=%s", code, qty, order_id)
            else:
                submitted.append({**item, "order_id": order_id})
                logger.info("[Order] OK: %s sell %d order_id=%d", code, qty, order_id)
        except Exception as e:  # noqa: BLE001
            failed.append({**item, "_error": f"{type(e).__name__}: {e}"})
            logger.error("[Order] EXCEPTION %s qty=%d: %s", code, qty, e, exc_info=True)

        # 节流: QMT 短时间大量下单可能限流
        sleep(0.2)

    return {
        "submitted_count": len(submitted),
        "failed_count": len(failed),
        "submitted": submitted,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emergency close-all live positions (real money sell-market)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真执行卖单 (默认 dry-run 仅打印清单)",
    )
    parser.add_argument(
        "--confirm-yes",
        action="store_true",
        help="跳过交互式 'YES SELL ALL' 确认 (audit trail 保留, 用于 chat-driven 授权)",
    )
    args = parser.parse_args()

    print(
        f"[emergency_close] boot {datetime.now().isoformat()} "
        f"pid={os.getpid()} dry_run={not args.execute}",
        flush=True,
        file=sys.stderr,
    )

    try:
        positions, broker = _resolve_positions_via_qmt()
    except Exception as e:
        logger.error("[FATAL] QMT 查持仓失败: %s", e, exc_info=True)
        print(f"\n❌ FATAL: QMT connect/query failed: {e}", file=sys.stderr)
        return 2

    sellable, skipped = _print_plan(positions)

    if not sellable:
        print("✅ Nothing to sell (sellable list empty). Exiting.")
        return 0

    if not args.execute:
        print("ℹ️  DRY-RUN mode. No orders placed.")
        print("    To execute, re-run with --execute flag.")
        print(f"    Log file: {LOG_FILE}")
        return 0

    # --execute 路径
    if args.confirm_yes:
        logger.warning(
            "[Confirm] --confirm-yes flag bypass interactive prompt (chat-driven 授权)"
        )
        print("⚠️  --confirm-yes 跳过交互确认 (audit trail 已 log)")
    elif not _confirm_execute():
        print("\n❌ Confirmation FAILED — no orders placed. Exiting.")
        return 1

    print("\n🚀 Confirmation OK. Submitting sell orders...\n")
    # P2 reviewer 采纳 (PR #139 fix): hard stderr audit (铁律 43-b 防 FileHandler
    # zombie 锁导致 logger.warning 写不出). schtask LastResult / 审计员调查能直接看
    # 到 bypass 时戳 + pid, 不依赖 file logger.
    print(
        f"[AUDIT] _execute_sells invoked at {datetime.now().isoformat()} "
        f"pid={os.getpid()} sellable_count={len(sellable)} "
        f"confirm_yes={args.confirm_yes}",
        file=sys.stderr,
        flush=True,
    )
    summary = _execute_sells(broker, sellable)

    print("\n" + "=" * 80)
    print("  Execution Summary")
    print("=" * 80)
    print(f"  Submitted: {summary['submitted_count']}")
    print(f"  Failed:    {summary['failed_count']}")
    if summary["submitted"]:
        print("\n  Submitted orders:")
        for s in summary["submitted"]:
            print(f"    {s['code']:12} qty={s['sellable_qty']:>6}  order_id={s['order_id']}")
    if summary["failed"]:
        print("\n  Failed orders:")
        for f in summary["failed"]:
            print(f"    {f.get('code', '?'):12} reason={f.get('_error', '?')}")
    print(f"\n  Log file: {LOG_FILE}")
    print("=" * 80)

    return 0 if summary["failed_count"] == 0 else 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        msg = f"[emergency_close] FATAL: {type(e).__name__}: {e}"
        print(msg, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        sys.exit(2)
