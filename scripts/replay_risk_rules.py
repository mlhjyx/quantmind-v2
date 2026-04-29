#!/usr/bin/env python3
"""Risk Rules 历史回放验证 (Phase 0, MVP 3.1b verification, 2026-04-29 Session 44).

为什么需要本脚本:
  Session 44 真生产事件 (卓然 -29% / 南玻 -10%) 暴露 MVP 3.1 Risk Framework
  对"买入即跌"场景设计上失效, 30 天 risk_event_log 0 行. PR #139 Phase 1
  补 SingleStockStopLossRule (4 档止损), 但**没有任何回放验证证明它真生效**.

  本脚本是 Phase 0 验收门: 不跑 = 不允许 PT 重启 (CLAUDE.md 风险闭环 PR #139 留档).

设计原则 (与铁律 31 对齐):
  - 数据加载层 (DAL): 从 position_snapshot + klines_daily 读历史数据 (走 sync psycopg2)
  - 计算层 (rule): 直接用 SingleStockStopLossRule (纯计算, 无副作用)
  - 输出层: stdout 表格 + 可选 CSV (--out-csv) 供后续 audit

对比维度:
  1. 回放结果 vs 实际 risk_event_log (期望: 回放有 N 触发, 实际 0 → 漏告警 N 次)
  2. 单股按级别分布 (L1/L2/L3/L4 各几次)
  3. 每日 triggered 列表 (date / code / loss% / level)

铁律: 22 / 24 / 25 / 31 / 33 / 41

用法:
    # 默认: 4-15 ~ 今日 - 1, live mode, 所有 strategy
    python scripts/replay_risk_rules.py

    # 自定义窗口
    python scripts/replay_risk_rules.py --start 2026-04-15 --end 2026-04-28

    # 单股 filter
    python scripts/replay_risk_rules.py --codes 688121.SH,000012.SZ

    # CI-style assertion: 期望至少 1 次 trigger
    python scripts/replay_risk_rules.py --assert-min-triggers 1
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))


@dataclass
class TriggerRow:
    """单条历史触发记录 (供 stdout 表格 + CSV 输出)."""

    trade_date: date
    strategy_id: str
    execution_mode: str
    code: str
    rule_id: str
    loss_pct: float
    entry_price: float
    current_price: float
    shares: int
    severity: str  # P0/P1/P2 (从 metrics 反查)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Replay risk rules over historical position_snapshot + klines_daily."
    )
    today = date.today()
    p.add_argument(
        "--start",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=today - timedelta(days=30),
        help="开始日期 (含, 默认 today-30d)",
    )
    p.add_argument(
        "--end",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=today - timedelta(days=1),
        help="结束日期 (含, 默认 today-1, 防今日 klines_daily 未入库)",
    )
    p.add_argument(
        "--mode", choices=("live", "paper"), default="live",
        help="execution_mode 过滤 (默认 live)",
    )
    p.add_argument(
        "--strategy-id", default=None,
        help="strategy_id UUID 过滤 (默认全部 strategy)",
    )
    p.add_argument(
        "--codes", default=None,
        help="逗号分隔股票码过滤 (e.g. 688121.SH,000012.SZ)",
    )
    p.add_argument(
        "--out-csv", default=None,
        help="可选 CSV 输出路径 (默认 stdout 表格仅)",
    )
    p.add_argument(
        "--assert-min-triggers", type=int, default=0,
        help="若总触发 < N, exit 1 (CI gate, 默认 0 = 不 assert)",
    )
    return p


def _load_snapshots(
    conn, start: date, end: date, mode: str,
    strategy_id: str | None, codes: list[str] | None,
) -> dict:
    """加载 position_snapshot + klines_daily (close) JOIN.

    Returns:
        dict 按 (trade_date, strategy_id) 分组, 值 = list of position dicts.
        每 position dict: {code, shares, avg_cost, current_price}
    """
    cur = conn.cursor()
    sql_parts = ["""
        SELECT ps.trade_date, ps.strategy_id::text, ps.code,
               ps.quantity, ps.avg_cost, k.close
          FROM position_snapshot ps
          JOIN klines_daily k
            ON k.code = ps.code AND k.trade_date = ps.trade_date
         WHERE ps.execution_mode = %s
           AND ps.trade_date BETWEEN %s AND %s
           AND ps.avg_cost IS NOT NULL
           AND ps.quantity > 0
           AND ps.avg_cost > 0
    """]
    params: list = [mode, start, end]
    if strategy_id:
        sql_parts.append("AND ps.strategy_id::text = %s")
        params.append(strategy_id)
    if codes:
        sql_parts.append("AND ps.code = ANY(%s)")
        params.append(codes)
    sql_parts.append("ORDER BY ps.trade_date, ps.strategy_id, ps.code")

    cur.execute("\n".join(sql_parts), tuple(params))

    grouped: dict[tuple[date, str], list[dict]] = {}
    for row in cur.fetchall():
        td, sid, code, qty, avg_cost, close = row
        key = (td, sid)
        grouped.setdefault(key, []).append({
            "code": code,
            "shares": int(qty),
            "avg_cost": float(avg_cost),
            "current_price": float(close),
        })
    cur.close()
    return grouped


def _count_actual_alerts(conn, start: date, end: date, mode: str) -> int:
    """实际 risk_event_log 同窗口告警条数 (对比用)."""
    cur = conn.cursor()
    try:
        # 字段名: triggered_at (实测 schema 2026-04-29, NOT event_time)
        cur.execute("""
            SELECT COUNT(*) FROM risk_event_log
             WHERE triggered_at::date BETWEEN %s AND %s
               AND execution_mode = %s
        """, (start, end, mode))
        return int(cur.fetchone()[0])
    except Exception as e:
        # 表可能不存在或字段不一致 (Phase 2 修复 audit log 之前)
        print(f"  [warn] risk_event_log query 失败: {e}", file=sys.stderr)
        return -1
    finally:
        cur.close()


def _replay(
    grouped: dict, rule, mode: str,
) -> list[TriggerRow]:
    """对每 (trade_date, strategy_id) 跑 rule.evaluate, 收集 triggers."""
    from backend.qm_platform.risk.interface import Position, RiskContext

    triggers: list[TriggerRow] = []
    # severity_level_p (int 0/1/2/3) 在 RuleResult.metrics, single_stock 写在 evaluate()
    # 末尾. 反查映射回 P0/P1/P2/INFO 字符串供 stdout 表格 + CSV.
    sev_p_to_str = {0: "P0", 1: "P1", 2: "P2", 3: "INFO"}

    for (td, sid), pos_list in sorted(grouped.items()):
        positions = tuple(
            Position(
                code=p["code"],
                shares=p["shares"],
                entry_price=p["avg_cost"],
                # peak_price 占位 (single_stock 不用), 给 max(close, avg_cost) 防 PMS 误判
                peak_price=max(p["avg_cost"], p["current_price"]),
                current_price=p["current_price"],
            )
            for p in pos_list
        )
        ctx = RiskContext(
            strategy_id=sid,
            execution_mode=mode,
            timestamp=datetime.combine(td, datetime.min.time()),
            positions=positions,
            portfolio_nav=sum(p["shares"] * p["current_price"] for p in pos_list),
            prev_close_nav=None,
        )
        results = rule.evaluate(ctx)
        for r in results:
            entry = next(p["avg_cost"] for p in pos_list if p["code"] == r.code)
            current = next(p["current_price"] for p in pos_list if p["code"] == r.code)
            shares = next(p["shares"] for p in pos_list if p["code"] == r.code)
            loss_pct = (current - entry) / entry
            sev_p = int(r.metrics.get("severity_level_p", 99))
            triggers.append(TriggerRow(
                trade_date=td,
                strategy_id=sid,
                execution_mode=mode,
                code=r.code,
                rule_id=r.rule_id,
                loss_pct=loss_pct,
                entry_price=entry,
                current_price=current,
                shares=shares,
                severity=sev_p_to_str.get(sev_p, "?"),
            ))
    return triggers


def _print_summary(
    triggers: list[TriggerRow],
    actual_alerts: int,
    start: date, end: date, mode: str,
) -> None:
    """stdout 友好打印."""
    print("\n" + "=" * 80)
    print("  Risk Rules Historical Replay — SingleStockStopLossRule")
    print(f"  Window: {start} .. {end} ({mode} mode)")
    print("=" * 80)

    if not triggers:
        print("  ⚠️  0 triggers 回放 → 规则在窗口内不会触发 (检查窗口/数据)")
        return

    # 按级别统计
    by_level: dict[str, int] = {}
    for t in triggers:
        by_level[t.rule_id] = by_level.get(t.rule_id, 0) + 1
    print(f"\n  Total triggers: {len(triggers)}")
    print("  By level:")
    for rid, cnt in sorted(by_level.items()):
        print(f"    {rid:35} {cnt:>4}")

    # 实际 vs 回放对比
    print(f"\n  Actual risk_event_log in window: {actual_alerts}")
    if actual_alerts == -1:
        print("  → 表查询失败 (Phase 2 audit log 修复前 expected)")
    else:
        gap = len(triggers) - actual_alerts
        if gap > 0:
            print(f"  → ⚠️  GAP: {gap} 个告警**应触发但未记录** (Phase 2 audit 修复前 expected)")
        elif gap == 0:
            print("  → ✅ MATCH: 回放与实际告警数一致")
        else:
            print("  → ⚠️  实际多于回放 (unexpected, 可能其他 rule 也在写)")

    # 详表
    print("\n  Per-trigger detail:")
    print(f"  {'date':12} {'code':12} {'rule':30} {'loss%':>8} "
          f"{'entry':>10} {'current':>10} {'shares':>8} {'sev':>4}")
    print(f"  {'-' * 78}")
    for t in triggers:
        print(
            f"  {str(t.trade_date):12} {t.code:12} {t.rule_id:30} "
            f"{t.loss_pct * 100:>7.2f}% {t.entry_price:>10.4f} "
            f"{t.current_price:>10.4f} {t.shares:>8} {t.severity:>4}"
        )
    print("=" * 80 + "\n")


def _write_csv(path: Path, triggers: list[TriggerRow]) -> None:
    """可选 CSV 持久化 audit."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "trade_date", "strategy_id", "execution_mode", "code",
            "rule_id", "loss_pct", "entry_price", "current_price",
            "shares", "severity",
        ])
        for t in triggers:
            w.writerow([
                t.trade_date, t.strategy_id, t.execution_mode, t.code,
                t.rule_id, f"{t.loss_pct:.6f}", f"{t.entry_price:.6f}",
                f"{t.current_price:.6f}", t.shares, t.severity,
            ])
    print(f"  CSV written: {path}")


def main() -> int:
    args = _build_arg_parser().parse_args()
    codes = args.codes.split(",") if args.codes else None

    # 延迟 import (单测可不依赖 SDK + 加快错参 fail-fast)
    from app.services.db import get_sync_conn
    from backend.qm_platform.risk.rules.single_stock import SingleStockStopLossRule

    rule = SingleStockStopLossRule()
    conn = get_sync_conn()
    try:
        grouped = _load_snapshots(
            conn, args.start, args.end, args.mode,
            args.strategy_id, codes,
        )
        triggers = _replay(grouped, rule, args.mode)
        actual = _count_actual_alerts(conn, args.start, args.end, args.mode)
    finally:
        conn.close()

    _print_summary(triggers, actual, args.start, args.end, args.mode)

    if args.out_csv:
        _write_csv(Path(args.out_csv), triggers)

    if args.assert_min_triggers > 0 and len(triggers) < args.assert_min_triggers:
        print(
            f"❌ FAIL: triggers={len(triggers)} < required {args.assert_min_triggers}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
