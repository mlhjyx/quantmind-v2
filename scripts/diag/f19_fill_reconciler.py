"""F19 Fill Reconciler — 对比 qmt-data-stderr.log QMT 实时回调 vs trade_log DB 入库.

Session 21 加时 Part 3 (2026-04-21 晚): F19 "phantom 5 码" 最终定案工具.

**背景**:
- Session 20 17:35 pt_audit 报 `db_drift: expected=24 vs snapshot=19` (5 phantom)
- Session 21 加时 Part 1 交叉查确认 trade_log 20/20 完整 — 但这是**入库行数完整**, 未查**每行 volume 完整**
- Session 21 加时 Part 3 查 qmt-data-stderr.log 93K 行 QMT 实时回调, 发现:
  - 4-17 002441 QMT 实际卖 4800 (1200 + 3600), trade_log 只记 1200 → 丢 3600
  - 4-17 300833 QMT 实卖 1400 (500 + 900), trade_log 只记 500 → 丢 900
  - 4-17 688739 QMT 实卖 1900 (1329+500+71), trade_log 只记 1329 → 丢 571
  - 4-17 12:14 920212 补卖 60 / 13:10 920950 补卖 65 → trade_log 完全没有
- F19 根因实为 `execution_service.on_stock_trade` **部分成交回调聚合 bug** (55 → 56 的多批 fill 只入第一次)
- 非 "phantom"/"蒸发"/"周末 OTC"

**本脚本**:
1. 扫 qmt-data-stderr.log 所有 "成交回报" 行 (status=55/56 的 fill) → 按 order_id 聚合
2. 按日查 DB trade_log (live mode)
3. 以 (code, direction) 为 key diff, 输出 JSON reconciliation 报告
4. 成交粒度: 每订单 QMT 实际成交数 vs trade_log 入库数, 差 = 丢失

Usage:
    python scripts/diag/f19_fill_reconciler.py --date 2026-04-17
    python scripts/diag/f19_fill_reconciler.py --date-range 2026-04-14 2026-04-21 --output docs/audit/f19_reconciliation.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

import psycopg2.extensions  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

QMT_STDERR_LOG = PROJECT_ROOT / "logs" / "qmt-data-stderr.log"

# "2026-04-17 09:31:08,000 [qmt_broker] INFO [QMT] 成交回报: order_id=1090520670, code=688739.SH, price=24.65, volume=1329"
FILL_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[qmt_broker\].*成交回报:\s*"
    r"order_id=(?P<order_id>\d+), code=(?P<code>\S+), price=(?P<price>[\d.]+), volume=(?P<volume>\d+)"
)

# "status=50 已报 / 55 部分成交 / 56 已成 / 53 部分撤 / 54 已撤"
ORDER_STATUS_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[qmt_broker\].*委托回报:\s*"
    r"order_id=(?P<order_id>\d+), code=(?P<code>\S+), status=(?P<status>\d+), traded=(?P<traded>\d+)/(?P<total>\d+)"
)


def parse_qmt_fills(log_path: Path, target_date: date) -> dict:
    """扫 QMT stderr log, 抽目标日所有 fill callback, 按 order_id 聚合.

    Returns:
        {order_id: {
            "code": str, "fill_count": int, "total_volume": int,
            "avg_price": float, "first_ts": str, "last_ts": str,
            "fills": [(ts, price, volume)],
            "final_status": int | None,  # 50/55/56/53/54/...
            "final_traded": int, "final_total": int,  # 最终 traded / 委托总量
        }}
    """
    if not log_path.exists():
        raise FileNotFoundError(f"QMT log 不存在: {log_path}")

    target_prefix = target_date.strftime("%Y-%m-%d")
    orders: dict[str, dict] = defaultdict(lambda: {
        "code": None, "fills": [], "fill_count": 0, "total_volume": 0,
        "first_ts": None, "last_ts": None, "final_status": None,
        "final_traded": 0, "final_total": 0,
    })

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if target_prefix not in line[:20]:
                continue
            # 成交回报
            m = FILL_PATTERN.search(line)
            if m:
                oid = m.group("order_id")
                entry = orders[oid]
                entry["code"] = m.group("code")
                entry["fills"].append({
                    "ts": m.group("ts"),
                    "price": float(m.group("price")),
                    "volume": int(m.group("volume")),
                })
                entry["fill_count"] += 1
                entry["total_volume"] += int(m.group("volume"))
                if entry["first_ts"] is None:
                    entry["first_ts"] = m.group("ts")
                entry["last_ts"] = m.group("ts")
                continue
            # 委托回报 (status 追踪最终状态)
            m2 = ORDER_STATUS_PATTERN.search(line)
            if m2:
                oid = m2.group("order_id")
                entry = orders[oid]
                if entry["code"] is None:
                    entry["code"] = m2.group("code")
                entry["final_status"] = int(m2.group("status"))
                entry["final_traded"] = int(m2.group("traded"))
                entry["final_total"] = int(m2.group("total"))

    # avg_price
    for oid, entry in orders.items():
        if entry["total_volume"] > 0:
            total_amount = sum(f["price"] * f["volume"] for f in entry["fills"])
            entry["avg_price"] = round(total_amount / entry["total_volume"], 4)
        else:
            entry["avg_price"] = None
    return dict(orders)


def load_trade_log(conn: psycopg2.extensions.connection, target_date: date) -> list[dict]:
    """查 trade_log live mode 当日记录. 含 order_qty (委托量)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT code, direction, quantity, order_qty, fill_price, executed_at
               FROM trade_log
               WHERE trade_date = %s AND execution_mode = 'live'
               ORDER BY code, executed_at""",
            (target_date,),
        )
        rows = cur.fetchall()
    return [
        {
            "code": r[0], "direction": r[1], "quantity": int(r[2]),
            "order_qty": int(r[3]) if r[3] is not None else None,
            "fill_price": float(r[4]) if r[4] is not None else None,
            "executed_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


def reconcile(target_date: date, output_path: Path | None = None) -> dict:
    """QMT 实际成交 vs trade_log 入库, 生成 reconciliation 报告."""
    print(f"[reconciler] {target_date}: 扫 QMT stderr log...")
    qmt_orders = parse_qmt_fills(QMT_STDERR_LOG, target_date)
    print(f"[reconciler]   QMT: {len(qmt_orders)} 个 order_id 有 fill callback")

    print(f"[reconciler] {target_date}: 查 trade_log live mode...")
    conn = get_sync_conn()
    try:
        db_trades = load_trade_log(conn, target_date)
    finally:
        conn.close()
    print(f"[reconciler]   DB: {len(db_trades)} 行 trade_log 入库")

    # 按 code 聚合 QMT 实际成交总量
    qmt_by_code: dict[str, dict] = defaultdict(lambda: {
        "qmt_total_volume": 0, "qmt_fill_count": 0, "qmt_orders": [],
    })
    for oid, entry in qmt_orders.items():
        c = entry["code"]
        qmt_by_code[c]["qmt_total_volume"] += entry["total_volume"]
        qmt_by_code[c]["qmt_fill_count"] += entry["fill_count"]
        qmt_by_code[c]["qmt_orders"].append({
            "order_id": oid,
            "fill_count": entry["fill_count"],
            "total_volume": entry["total_volume"],
            "final_status": entry["final_status"],
            "final_traded": entry["final_traded"],
            "final_total": entry["final_total"],
            "avg_price": entry["avg_price"],
            "first_ts": entry["first_ts"],
            "last_ts": entry["last_ts"],
        })

    # 按 code 聚合 DB trade_log 入库总量
    db_by_code: dict[str, dict] = defaultdict(lambda: {
        "db_total_volume": 0, "db_row_count": 0, "db_rows": [],
    })
    for r in db_trades:
        c = r["code"]
        db_by_code[c]["db_total_volume"] += r["quantity"]
        db_by_code[c]["db_row_count"] += 1
        db_by_code[c]["db_rows"].append(r)

    # Diff (union of codes)
    all_codes = set(qmt_by_code.keys()) | set(db_by_code.keys())
    code_diff = []
    total_loss = 0
    for c in sorted(all_codes):
        qmt = qmt_by_code.get(c, {"qmt_total_volume": 0, "qmt_fill_count": 0, "qmt_orders": []})
        db = db_by_code.get(c, {"db_total_volume": 0, "db_row_count": 0, "db_rows": []})
        loss = qmt["qmt_total_volume"] - db["db_total_volume"]
        total_loss += max(0, loss)  # 只算 QMT > DB 的丢失 (反向 = DB 多入不算丢失)
        verdict = (
            "EQUAL" if loss == 0 else
            "DB_LEAKS_QMT" if loss > 0 else
            "DB_EXCESS_QMT"
        )
        code_diff.append({
            "code": c,
            "qmt_total_volume": qmt["qmt_total_volume"],
            "qmt_fill_count": qmt["qmt_fill_count"],
            "db_total_volume": db["db_total_volume"],
            "db_row_count": db["db_row_count"],
            "diff_qmt_minus_db": loss,
            "verdict": verdict,
            "qmt_orders": qmt.get("qmt_orders", []),
            "db_rows": db.get("db_rows", []),
        })

    report = {
        "trade_date": target_date.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "total_qmt_orders": len(qmt_orders),
        "total_db_rows": len(db_trades),
        "total_volume_loss_qmt_minus_db": total_loss,
        "codes_with_discrepancy": sum(1 for c in code_diff if c["verdict"] != "EQUAL"),
        "code_diff": code_diff,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[reconciler] 报告写 → {output_path}")

    # stdout 摘要
    print(f"\n=== {target_date} Reconciliation Summary ===")
    print(f"QMT orders: {len(qmt_orders)} | DB rows: {len(db_trades)}")
    print(f"Total volume loss (QMT > DB): {total_loss} 股")
    print(f"Codes with discrepancy: {report['codes_with_discrepancy']} / {len(code_diff)}")
    for c in code_diff:
        if c["verdict"] != "EQUAL":
            print(
                f"  [{c['verdict']:<15}] {c['code']:<12} "
                f"QMT={c['qmt_total_volume']:>6} ({c['qmt_fill_count']} fills) "
                f"DB={c['db_total_volume']:>6} ({c['db_row_count']} rows) "
                f"diff={c['diff_qmt_minus_db']:+d}"
            )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=str, help="单日 YYYY-MM-DD (default=2026-04-17)")
    parser.add_argument(
        "--date-range", nargs=2, metavar=("START", "END"),
        help="日期范围 start end (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output", type=str,
        help="JSON 输出路径 (default=docs/audit/f19_reconciliation_{date}.json)",
    )
    args = parser.parse_args()

    if args.date_range:
        start_d = date.fromisoformat(args.date_range[0])
        end_d = date.fromisoformat(args.date_range[1])
        dates = []
        d = start_d
        while d <= end_d:
            dates.append(d)
            d = date.fromordinal(d.toordinal() + 1)
    else:
        d_str = args.date or "2026-04-17"
        dates = [date.fromisoformat(d_str)]

    total_loss = 0
    for d in dates:
        out = Path(args.output) if args.output and len(dates) == 1 else (
            PROJECT_ROOT / "docs" / "audit" / f"f19_reconciliation_{d.isoformat()}.json"
        )
        rpt = reconcile(d, out)
        total_loss += rpt["total_volume_loss_qmt_minus_db"]

    return 0 if total_loss == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
