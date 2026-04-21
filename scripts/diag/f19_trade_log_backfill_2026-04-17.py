#!/usr/bin/env python3
"""F19 trade_log backfill — 2026-04-17 missing fills (4 codes).

## 背景

F19 根因 (PR #39, `qmt_execution_adapter.py:70 QMT_STATUS[55] final→pending`)
已修复未来 trade_log. 历史 2026-04-17 live 模式 4 码缺失 9538 股 (98.7%),
本脚本按 reconciliation 数据补录.

参考:
  - ADR-011 §2 F19 根因定案 + §4 Session 22+ action items
  - docs/audit/f19_reconciliation_2026-04-17.json (scripts/diag/f19_fill_reconciler.py 产出)

## Scope (4 codes, 9538 shares)

| Code       | Direction | Missing Qty | Missing Avg Price |
|------------|-----------|-------------|-------------------|
| 002441.SZ  | sell      | 3600        | 10.14             |
| 300833.SZ  | sell      | 900         | 33.72             |
| 688121.SH  | buy       | 4467        | 10.898            |
| 688739.SH  | sell      | 571         | 24.63             |

Direction 来源: 各码现有 DB trade_log row 的 direction 字段 (前置 `psycopg2` 查询验证).

## Scope Exclusion (2 BJ, 125 shares, 1.3%)

920212.BJ 60 股 @ 11.72 (12:14:53) + 920950.BJ 65 股 @ 15.63 (13:10:03):
  - 发生在 DailyExecute 09:31 窗口之外 (盘中 12-13 点手工 QMT 操作)
  - execution_audit_log 无记录
  - QMT callback log 不含 direction 字段
  - position_snapshot 4-13→4-14 已存在 226 股不一致 (Session 21 Part 1 遗留)

**不盲目 guess direction 入库** (数据错误 > 数据缺失). 2 BJ 保持空白, 留
独立 Session 22+ 调查 (若 user 回忆/截屏可明确, 可手动补 INSERT 2 行).

## Cost Model (per existing 4-17 live row pattern verified)

| 字段        | 公式                          | 来源验证                              |
|-------------|-------------------------------|---------------------------------------|
| commission  | max(0.0000854 × notional, 5.0)| 现 002441 row: 5.0 (notional=12180, ratio=0.0000854 → 1.04, min 5) |
| stamp_tax   | sell → 0.0005 × notional; buy → 0 | 现 002441 sell: 6.09 / 12180 = 0.0005 ✓  |
| transfer_fee| 0.00001 × notional            | 现 002441 total-comm-stamp: 11.2118 - 5 - 6.09 = 0.1218 = 12180×0.00001 ✓ |
| total_cost  | commission + stamp_tax + transfer_fee | |
| swap_cost   | 0 (A 股无 swap)              | |

`transfer_fee` 未单独建列, 并入 `total_cost`. Reviewer 确认与现有行一致.

## Audit Trail

`reject_reason='F19_backfill_2026-04-17'` 作 audit marker — 该列语义允许
非标值 (schema VARCHAR(100)), 永久识别此批补录行; 非 `created_at > 2026-04-21`
可能歧义的时间推断.

## Idempotency

每次运行前 SELECT 检查 (7 列 fingerprint): 若已存在 (code, trade_date,
execution_mode, strategy_id, direction, quantity, fill_price) 精确匹配
backfill fixture 的行, 跳过该码. 防止重复执行导致双倍数据.

## Usage

    python scripts/diag/f19_trade_log_backfill_2026-04-17.py              # dry-run (默认)
    python scripts/diag/f19_trade_log_backfill_2026-04-17.py --apply       # 实际 INSERT
    python scripts/diag/f19_trade_log_backfill_2026-04-17.py --verify      # 查 trade_log 4-17 live 验证

## Safety (铁律 32 / 33 / 40 合规)

  - --dry-run 默认 (不传 --apply 不写库, 不开 DB connection)
  - 单一 transaction (commit 由 caller main() 管理, apply_backfill 内部不 commit)
  - strategy_id pre-flight check (不存在 → abort)
  - INSERT 前 SELECT idempotency 检查 (防重复)
  - try/finally 保证 conn.close() (Ctrl+C / BaseException 不泄漏连接)
  - Decimal 全程 (铁律: 金融金额用 Decimal)
  - 参数化 SQL 全程 (SQLi 防护)
  - ruff check + ruff format clean
"""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger("f19_backfill")

TRADE_DATE = date(2026, 4, 17)
STRATEGY_ID = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"  # live strategy_id (DB 4-17 verified)
EXECUTION_MODE = "live"
# 与现有 4-17 live 同批 executed_at (09:32:06.985880 UTC+8, 不引入新时间语义).
# 中国无 DST, UTC+8 固定 offset 与 zoneinfo.ZoneInfo("Asia/Shanghai") 等价.
EXECUTED_AT = datetime(2026, 4, 17, 9, 32, 6, 985880, tzinfo=timezone(timedelta(hours=8)))

COMMISSION_RATE = Decimal("0.0000854")
COMMISSION_MIN = Decimal("5.0")
STAMP_TAX_RATE_SELL = Decimal("0.0005")  # post 2023-08-28
TRANSFER_FEE_RATE = Decimal("0.00001")

REJECT_REASON_MARKER = "F19_backfill_2026-04-17"  # reviewer P2 — audit marker


@dataclass(frozen=True)
class BackfillRow:
    code: str
    direction: str  # buy/sell
    quantity: int  # missing shares only
    fill_price: Decimal  # weighted avg of missing fills


# Fixture 来源: docs/audit/f19_reconciliation_2026-04-17.json + DB direction 查询
# avg price 推导:
#   002441: total=4800@10.1425, existing=1200@10.15 → missing=(4800×10.1425 - 1200×10.15)/3600 = 10.14
#   300833: total=1400@33.7414, existing=500@33.78 → missing=(1400×33.7414 - 500×33.78)/900 = 33.72
#   688121: total=4500@10.8976, existing=33@10.88 → missing=(4500×10.8976 - 33×10.88)/4467 = 10.898
#   688739: total=1900@24.6436, existing=1329@24.65 → missing=(1900×24.6436 - 1329×24.65)/571 = 24.63
BACKFILL_FIXTURE: list[BackfillRow] = [
    BackfillRow(code="002441.SZ", direction="sell", quantity=3600, fill_price=Decimal("10.1400")),
    BackfillRow(code="300833.SZ", direction="sell", quantity=900, fill_price=Decimal("33.7200")),
    BackfillRow(code="688121.SH", direction="buy", quantity=4467, fill_price=Decimal("10.8980")),
    BackfillRow(code="688739.SH", direction="sell", quantity=571, fill_price=Decimal("24.6300")),
]


def compute_costs(row: BackfillRow) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Returns (commission, stamp_tax, transfer_fee, total_cost)."""
    notional = row.fill_price * Decimal(row.quantity)
    commission = max(notional * COMMISSION_RATE, COMMISSION_MIN).quantize(Decimal("0.0001"))
    stamp_tax = (
        (notional * STAMP_TAX_RATE_SELL).quantize(Decimal("0.0001"))
        if row.direction == "sell"
        else Decimal("0.0000")
    )
    transfer_fee = (notional * TRANSFER_FEE_RATE).quantize(Decimal("0.0001"))
    total_cost = (commission + stamp_tax + transfer_fee).quantize(Decimal("0.0001"))
    return commission, stamp_tax, transfer_fee, total_cost


def get_conn() -> Any:
    """Direct psycopg2 connection via .env DATABASE_URL (urlparse-based robust)."""
    import os

    import psycopg2

    env_path = Path(__file__).resolve().parents[2] / "backend" / ".env"
    db_url: str | None = None
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    if db_url is None:
        db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未设置 (既不在 backend/.env 也不在 env)")

    # 统一处理 postgresql+asyncpg:// → postgresql:// (urlparse 不识别 +asyncpg scheme)
    normalized = db_url
    if normalized.startswith("postgresql+"):
        normalized = "postgresql://" + normalized.split("://", 1)[1]
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"DATABASE_URL scheme 异常: {parsed.scheme!r} (expected postgresql)")
    if not (parsed.username and parsed.hostname and parsed.path):
        raise RuntimeError(f"DATABASE_URL 缺少字段 (user/host/db): {db_url!r}")

    db_name = parsed.path.lstrip("/")
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=db_name,
        user=parsed.username,
        password=parsed.password or "",
    )


def check_strategy_id(cur: Any) -> None:
    """reviewer P2 — strategy_id pre-flight. 不存在 raise."""
    cur.execute(
        """
        SELECT COUNT(*) FROM trade_log
        WHERE strategy_id = %s::uuid AND execution_mode = %s
        """,
        (STRATEGY_ID, EXECUTION_MODE),
    )
    ref_count = int(cur.fetchone()[0])
    if ref_count == 0:
        raise RuntimeError(
            f"strategy_id={STRATEGY_ID!r} (live) 在 trade_log 无任何引用, "
            "backfill 会产生孤儿行. 检查 .env STRATEGY_ID 或 DDL 变更."
        )
    logger.info("strategy_id pre-flight OK: %d 现有 live rows reference %s", ref_count, STRATEGY_ID)


def check_existing(cur: Any, row: BackfillRow) -> int:
    """返回与 fixture 精确匹配的已存在行数 (idempotency check, 7 列 fingerprint)."""
    cur.execute(
        """
        SELECT COUNT(*) FROM trade_log
        WHERE code = %s
          AND trade_date = %s
          AND execution_mode = %s
          AND strategy_id = %s::uuid
          AND direction = %s
          AND quantity = %s
          AND fill_price = %s
        """,
        (
            row.code,
            TRADE_DATE,
            EXECUTION_MODE,
            STRATEGY_ID,
            row.direction,
            row.quantity,
            row.fill_price,
        ),
    )
    return int(cur.fetchone()[0])


def insert_row(cur: Any, row: BackfillRow) -> None:
    """Execute INSERT for one backfill row."""
    commission, stamp_tax, _transfer_fee, total_cost = compute_costs(row)
    # trade_log 无 transfer_fee 列, 合并入 total_cost (reviewer 确认与现有行一致).
    # swap_cost = Decimal("0") (reviewer P2 - 明确类型 vs int 0 隐式 cast).
    cur.execute(
        """
        INSERT INTO trade_log (
            code, trade_date, strategy_id, market, direction, quantity,
            target_price, fill_price, slippage_bps,
            commission, stamp_tax, swap_cost, total_cost,
            execution_mode, reject_reason, executed_at
        ) VALUES (
            %s, %s, %s::uuid, 'astock', %s, %s,
            NULL, %s, NULL,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        """,
        (
            row.code,
            TRADE_DATE,
            STRATEGY_ID,
            row.direction,
            row.quantity,
            row.fill_price,
            commission,
            stamp_tax,
            Decimal("0"),  # swap_cost
            total_cost,
            EXECUTION_MODE,
            REJECT_REASON_MARKER,
            EXECUTED_AT,
        ),
    )


def print_dry_run(rows: list[BackfillRow]) -> None:
    print("=" * 80)
    print("DRY-RUN — will INSERT the following rows into trade_log (no DB write):")
    print("=" * 80)
    total_shares = 0
    total_cost_sum = Decimal("0")
    for row in rows:
        commission, stamp_tax, transfer_fee, total_cost = compute_costs(row)
        notional = row.fill_price * Decimal(row.quantity)
        print(
            f"  {row.code:<11} {row.direction:<4} qty={row.quantity:>5} @ {row.fill_price}"
            f"  notional={notional:>12.2f}  commission={commission}  stamp_tax={stamp_tax}"
            f"  transfer_fee={transfer_fee}  total_cost={total_cost}"
        )
        total_shares += row.quantity
        total_cost_sum += total_cost
    print("-" * 80)
    print(f"Total: {len(rows)} rows, {total_shares} shares, total_cost Σ={total_cost_sum}")
    print(f"reject_reason marker: {REJECT_REASON_MARKER!r}")
    print("Run with --apply to actually INSERT.")


def apply_backfill(conn: Any) -> dict[str, Any]:
    """INSERT rows inside single transaction.

    Transaction boundary: 铁律 32 合规 — 本函数内部不 commit, 由 caller (main) 管理.
    异常时内部 rollback + re-raise, caller 看到异常后可记录 + 退出.
    """
    inserted: list[str] = []
    skipped_idempotent: list[tuple[str, int]] = []
    try:
        with conn.cursor() as cur:
            check_strategy_id(cur)
            for row in BACKFILL_FIXTURE:
                existing = check_existing(cur, row)
                if existing > 0:
                    skipped_idempotent.append((row.code, existing))
                    logger.warning(
                        "IDEMPOTENT SKIP %s: %d 行已存在 (7 列 fingerprint 精确匹配)",
                        row.code,
                        existing,
                    )
                    continue
                insert_row(cur, row)
                inserted.append(row.code)
                logger.info(
                    "INSERTED %s %s %d @ %s",
                    row.code,
                    row.direction,
                    row.quantity,
                    row.fill_price,
                )
    except Exception:
        logger.exception("apply_backfill 失败, 内部 rollback 并 re-raise 给 caller")
        conn.rollback()
        raise
    return {"inserted": inserted, "skipped_idempotent": skipped_idempotent}


def verify_post_apply(conn: Any) -> dict[str, Any]:
    """Post-apply verification: aggregate 4-17 live trade_log."""
    results: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT code,
                   direction,
                   COUNT(*) AS row_count,
                   SUM(quantity) AS total_qty,
                   SUM(total_cost) AS total_cost_sum
            FROM trade_log
            WHERE trade_date = %s AND execution_mode = %s
              AND code IN ('002441.SZ', '300833.SZ', '688121.SH', '688739.SH')
            GROUP BY code, direction
            ORDER BY code
            """,
            (TRADE_DATE, EXECUTION_MODE),
        )
        results["per_code"] = [
            {
                "code": r[0],
                "direction": r[1],
                "row_count": int(r[2]),
                "total_qty": int(r[3]),
                # reviewer P3: 保留 Decimal, 不 float() 丢精度
                "total_cost_sum": (Decimal(str(r[4])) if r[4] is not None else Decimal("0")),
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT COUNT(*), SUM(quantity) FROM trade_log
            WHERE trade_date = %s AND execution_mode = %s
            """,
            (TRADE_DATE, EXECUTION_MODE),
        )
        row = cur.fetchone()
        results["total_rows_4_17_live"] = int(row[0])
        results["total_qty_4_17_live"] = int(row[1]) if row[1] is not None else 0

        # 查 marker rows 识别本批 backfill
        cur.execute(
            """
            SELECT code, quantity, fill_price
            FROM trade_log
            WHERE trade_date = %s AND execution_mode = %s AND reject_reason = %s
            ORDER BY code
            """,
            (TRADE_DATE, EXECUTION_MODE, REJECT_REASON_MARKER),
        )
        results["backfill_marker_rows"] = [
            {"code": r[0], "quantity": int(r[1]), "fill_price": str(r[2])} for r in cur.fetchall()
        ]
    return results


def run_verify() -> int:
    conn = get_conn()
    try:
        result = verify_post_apply(conn)
    finally:
        conn.close()

    print("=" * 80)
    print("VERIFY — trade_log 4-17 live state:")
    print("=" * 80)
    expected = {
        "002441.SZ": ("sell", 4800),
        "300833.SZ": ("sell", 1400),
        "688121.SH": ("buy", 4500),
        "688739.SH": ("sell", 1900),
    }
    for entry in result["per_code"]:
        key = entry["code"]
        exp_dir, exp_qty = expected.get(key, ("?", -1))
        mark = "✓" if (entry["direction"] == exp_dir and entry["total_qty"] == exp_qty) else "✗"
        print(
            f"  {mark} {entry['code']:<11} {entry['direction']:<4}  rows={entry['row_count']}"
            f"  total_qty={entry['total_qty']:>5}  (expected {exp_qty})"
            f"  cost_sum={entry['total_cost_sum']}"
        )
    print("-" * 80)
    print(
        f"Total 4-17 live: {result['total_rows_4_17_live']} rows, "
        f"{result['total_qty_4_17_live']} shares"
    )
    print(f"Backfill marker rows ({REJECT_REASON_MARKER!r}): {len(result['backfill_marker_rows'])}")
    for r in result["backfill_marker_rows"]:
        print(f"    {r['code']:<11} qty={r['quantity']:>5} @ {r['fill_price']}")
    return 0


def run_apply() -> int:
    logger.info("APPLY mode — 准备 INSERT %d rows into trade_log", len(BACKFILL_FIXTURE))
    conn = get_conn()
    try:
        try:
            summary = apply_backfill(conn)
        except Exception:
            # apply_backfill 内部已 rollback + log.exception
            return 1
        conn.commit()  # reviewer P1: commit 由 caller 管理 (铁律 32)
    finally:
        conn.close()

    print("=" * 80)
    print("APPLY COMPLETE")
    print("=" * 80)
    print(f"  Inserted: {len(summary['inserted'])} codes — {summary['inserted']}")
    print(
        f"  Skipped idempotent: {len(summary['skipped_idempotent'])} — "
        f"{summary['skipped_idempotent']}"
    )
    print("\nRun --verify to confirm post-state.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="F19 trade_log backfill for 2026-04-17 (4 missing fill codes).",
        epilog="默认为 dry-run (仅打印 SQL, 不开 DB 连接). 需显式 --apply 才写库; --verify 查已入库状态.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="实际 INSERT (默认 dry-run)")
    group.add_argument("--verify", action="store_true", help="查询 trade_log 4-17 live 验证状态")
    args = parser.parse_args()

    if args.verify:
        return run_verify()
    if args.apply:
        return run_apply()
    print_dry_run(BACKFILL_FIXTURE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
