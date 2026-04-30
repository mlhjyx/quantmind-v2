"""T0-19 修法: emergency_close post-execution audit + DB sync hook.

T0-19 来源: PR #166 SHUTDOWN_NOTICE_2026_04_30 §6 + STATUS_REPORT_D3_C F-D3C-13.
设计稿: docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md (§2 4 项修法).

4 项修法 (顺序硬性, 任 1 失败 raise + 已写 row 不 rollback, 沿用 audit trail 原则):
    1. trade_log backfill × N rows (per order_id, weighted avg fill_price, NULL commission/tax)
    2. risk_event_log P1 audit row (action_taken='sell', shares=18 — LL-094 验证)
    3. performance_series 当日 row (post-fill nav, trade_date=真成交日 NOT backfill 当日)
    4. position_snapshot 当日 0 行 + circuit_breaker_state reset (hardcoded ¥993,520)

Idempotency (Phase 1 §2.3):
    (a) Hook flag file LOG_DIR/emergency_close_<ts>.DONE.flag — 完整性证据
    (b) trade_log 重入检测 (reject_reason='T0_19_backfill_<date>')

铁律映射:
    - 17 (DataPipeline): 例外 — audit 路径不走 DataPipeline (subset INSERT, 沿用 LL-066 例外)
    - 27 (不 fabricate): commission/stamp_tax NULL (log 无), 沿用 LL-066 partial UPSERT
    - 33 (fail-loud): 任 1 失败 raise, 不 silent
    - X1 (Claude 边界): dry_run_audit=True 模式仅打印 SQL, 不真 INSERT
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.exceptions import (
    T0_19_AlreadyBackfilledError,
    T0_19_AuditCheckError,
    T0_19_LogParseError,
)

logger = logging.getLogger(__name__)

# 4-30 14:54 实测真账户 ground truth (D3-C E6 沿用)
HARDCODED_NAV_2026_04_30 = 993520.16

# Phase 1 design §1 Q3 实测 confirmed CHECK enum (LL-094)
RISK_EVENT_LOG_ACTION_ENUM = {"sell", "alert_only", "bypass"}
RISK_EVENT_LOG_SEVERITY_ENUM = {"p0", "p1", "p2", "info"}
RISK_EVENT_LOG_EXECUTION_MODE_ENUM = {"paper", "live"}

# trade_log reject_reason backfill marker pattern (LL-059 / PR #41 沿用)
BACKFILL_REJECT_REASON_PREFIX = "t0_19_backfill_"

# emergency_close log fill event regex
# 格式: "2026-04-29 10:43:55,153 [INFO] [QMT] 成交回报: order_id=1090551138, code=600028.SH, price=5.39, volume=8600"
FILL_EVENT_REGEX = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d+)\s+"
    r"\[INFO\]\s+\[QMT\]\s+成交回报:\s+"
    r"order_id=(?P<order_id>\d+),\s+"
    r"code=(?P<code>[0-9]{6}\.(SH|SZ|BJ)),\s+"
    r"price=(?P<price>[\d.]+),\s+"
    r"volume=(?P<volume>\d+)"
)


def _collect_chat_authorization(args: Any) -> dict[str, Any]:
    """收集 chat-driven 授权 signature (Phase 1 design §2.4 Q6 schema).

    args 来自 emergency_close_all_positions.py argparse Namespace.
    """
    return {
        "auth": {
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": "chat-driven" if getattr(args, "confirm_yes", False) else "interactive",
            "delegate": "Claude (claude-opus-4-7)",
            "boundary_check": {
                "live_trading_disabled": True,
                "execution_mode": "live",
            },
        },
        "execution": {
            "script": "scripts/emergency_close_all_positions.py",
            "args": {
                "execute": getattr(args, "execute", False),
                "confirm_yes": getattr(args, "confirm_yes", False),
            },
            "started_at": datetime.now(UTC).isoformat(),
        },
    }


def _check_idempotency(conn: Any, trade_date: str, log_file: Path) -> None:
    """重入检测 — 双保险 (a) trade_log + (b) flag file.

    Raises:
        T0_19_AlreadyBackfilledError: 任 1 重入命中.
    """
    # (a) trade_log 重入检测
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM trade_log
        WHERE trade_date = %s
          AND execution_mode = 'live'
          AND reject_reason LIKE %s
        """,
        (trade_date, f"{BACKFILL_REJECT_REASON_PREFIX}%"),
    )
    count = cur.fetchone()[0]
    cur.close()

    if count > 0:
        raise T0_19_AlreadyBackfilledError(
            f"trade_log 已有 {count} 行 reject_reason='{BACKFILL_REJECT_REASON_PREFIX}*' "
            f"for trade_date={trade_date}. 重入检测命中, skip."
        )

    # (b) Hook flag 文件
    flag_path = log_file.with_suffix(".DONE.flag")
    if flag_path.exists():
        raise T0_19_AlreadyBackfilledError(
            f"Hook flag 已存在: {flag_path}. 完整性证据存在, skip."
        )


def _parse_emergency_close_log(log_file: Path) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """解析 emergency_close log 提取 fill events.

    Returns:
        dict[(code, order_id), list[fill_event]]: 聚合 partial fills per order_id.

    Raises:
        T0_19_LogParseError: 文件不存在 / size 0 / 0 fills 解析.
    """
    if not log_file.exists():
        raise T0_19_LogParseError(f"log 文件不存在: {log_file}")
    if log_file.stat().st_size == 0:
        raise T0_19_LogParseError(f"log 文件 size=0: {log_file}")

    fills_by_order: dict[tuple[str, int], list[dict[str, Any]]] = {}
    content = log_file.read_text(encoding="utf-8")

    for match in FILL_EVENT_REGEX.finditer(content):
        ts_str = match.group("ts").replace(",", ".")
        order_id = int(match.group("order_id"))
        code = match.group("code")
        price = float(match.group("price"))
        volume = int(match.group("volume"))

        key = (code, order_id)
        fills_by_order.setdefault(key, []).append(
            {"timestamp": ts_str, "price": price, "volume": volume}
        )

    if not fills_by_order:
        raise T0_19_LogParseError(
            f"0 fill events 解析自 {log_file} (regex 不匹配 — 检查 log 格式)"
        )

    return fills_by_order


def _aggregate_fill_per_order(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """每 order_id 聚合 partial fills → weighted avg fill_price + total volume.

    Phase 1 §1 Q7 算法: weighted_avg = SUM(price * volume) / SUM(volume).
    """
    total_volume = sum(f["volume"] for f in fills)
    if total_volume == 0:
        return {"total_volume": 0, "weighted_avg_price": 0.0, "earliest_ts": None}

    weighted_avg = sum(f["price"] * f["volume"] for f in fills) / total_volume
    earliest_ts = min(f["timestamp"] for f in fills)
    return {
        "total_volume": total_volume,
        "weighted_avg_price": round(weighted_avg, 4),
        "earliest_ts": earliest_ts,
    }


def _backfill_trade_log(
    conn: Any,
    fills_by_order: dict[tuple[str, int], list[dict[str, Any]]],
    trade_date: str,
    strategy_id: str,
    *,
    dry_run: bool,
) -> int:
    """Step 1: trade_log backfill × N rows (per order_id).

    沿用铁律 27 (不 fabricate): commission/stamp_tax/total_cost = NULL (log 无).
    沿用 LL-066 例外: subset INSERT 不走 DataPipeline (会 cascade NULL 其他列).
    """
    inserted = 0
    sql = """
        INSERT INTO trade_log (
            code, trade_date, strategy_id, direction, quantity,
            fill_price, executed_at, execution_mode, reject_reason,
            order_qty
        ) VALUES (%s, %s, %s, 'sell', %s, %s, %s::timestamptz, 'live', %s, %s)
    """
    reject_reason = f"{BACKFILL_REJECT_REASON_PREFIX}{trade_date}"

    cur = conn.cursor()
    for (code, order_id), fills in fills_by_order.items():
        agg = _aggregate_fill_per_order(fills)
        params = (
            code,
            trade_date,
            strategy_id,
            agg["total_volume"],
            agg["weighted_avg_price"],
            agg["earliest_ts"],
            reject_reason,
            agg["total_volume"],
        )
        if dry_run:
            print(f"[DRY-RUN trade_log INSERT] code={code} order_id={order_id} "
                  f"qty={agg['total_volume']} avg_price={agg['weighted_avg_price']:.4f} "
                  f"ts={agg['earliest_ts']}")
        else:
            cur.execute(sql, params)
        inserted += 1
    cur.close()

    return inserted


def _write_risk_event_log_audit(
    conn: Any,
    sells_summary: dict[str, Any],
    chat_authorization: dict[str, Any],
    trade_date: str,
    strategy_id: str,
    *,
    dry_run: bool,
) -> str:
    """Step 2: risk_event_log P1 audit row.

    Phase 1 §1 Q3 实测 CHECK enum:
        action_taken IN ('sell', 'alert_only', 'bypass')  — 用 'sell' 真清仓语义
        severity IN ('p0', 'p1', 'p2', 'info')           — T0-19 P1
    """
    # LL-094 验证 enum
    action = "sell"
    severity = "p1"
    if action not in RISK_EVENT_LOG_ACTION_ENUM:
        raise T0_19_AuditCheckError(f"action_taken={action} 不在 CHECK enum")
    if severity not in RISK_EVENT_LOG_SEVERITY_ENUM:
        raise T0_19_AuditCheckError(f"severity={severity} 不在 CHECK enum")

    audit_id = str(uuid4())
    submitted_count = sells_summary.get("submitted_count", 0)
    context = {
        "chat_authorization": chat_authorization,
        "sells_summary": {
            "submitted_count": submitted_count,
            "failed_count": sells_summary.get("failed_count", 0),
        },
        "phase_2_pr": "<待 PR 号>",
    }

    sql = """
        INSERT INTO risk_event_log (
            id, strategy_id, execution_mode, rule_id, severity, triggered_at,
            code, shares, reason, context_snapshot, action_taken, action_result,
            created_at
        ) VALUES (%s, %s, 'live', %s, %s, %s::timestamptz,
                  '', %s, %s, %s::jsonb, %s, %s::jsonb, NOW())
    """
    params = (
        audit_id,
        strategy_id,
        "t0_19_emergency_close_audit",
        severity,
        f"{trade_date} 10:43:54+08",
        submitted_count,
        f"T0-19 emergency_close_all_positions.py {trade_date} 实战清仓 audit. "
        f"沿用 LL-094 CHECK enum 实测 ('sell'/'alert_only'/'bypass').",
        json.dumps(context),
        action,
        json.dumps({"status": "logged_only", "audit_chain": "complete"}),
    )

    if dry_run:
        print(f"[DRY-RUN risk_event_log INSERT] id={audit_id} action={action} "
              f"severity={severity} shares={submitted_count} trade_date={trade_date}")
    else:
        cur = conn.cursor()
        cur.execute(sql, params)
        cur.close()

    return audit_id


def _write_performance_series_row(
    conn: Any,
    trade_date: str,
    strategy_id: str,
    nav: float,
    *,
    dry_run: bool,
) -> str:
    """Step 3: performance_series 当日 row (post-fill nav).

    ⚠️ 修订 1 强制 (Phase 2 prompt §④): trade_date='2026-04-29' (真成交日, 同 trade_log),
    NOT backfill 当日 4-30.
    """
    row_id = str(uuid4())
    sql = """
        INSERT INTO performance_series (
            trade_date, strategy_id, nav, cash, position_count, execution_mode
        ) VALUES (%s, %s, %s, %s, 0, 'live')
        ON CONFLICT (trade_date, strategy_id, execution_mode) DO NOTHING
    """
    params = (trade_date, strategy_id, nav, nav)

    if dry_run:
        print(f"[DRY-RUN performance_series INSERT] trade_date={trade_date} "
              f"strategy_id={strategy_id} nav={nav:,.2f} cash={nav:,.2f} position_count=0")
    else:
        cur = conn.cursor()
        cur.execute(sql, params)
        cur.close()

    return row_id


def _clear_position_snapshot_and_reset_cb_state(
    conn: Any,
    trade_date: str,
    strategy_id: str,
    nav: float,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Step 4: position_snapshot 当日 0 行 + circuit_breaker_state reset.

    Phase 1 §1 Q4: hardcoded ¥993,520 (--realtime flag 不实现, 留 PT 重启 gate).
    Phase 1 §1 Q5: position_snapshot NO FK refs, DELETE 安全.

    本 step **不 DELETE 4-28 stale 19 行** (留 PT 重启 gate user 授权), 仅写
    trade_date=4-29 0 行 sentinel + reset cb_state nav.
    """
    # circuit_breaker_state UPDATE
    cb_sql = """
        UPDATE circuit_breaker_state
        SET trigger_metrics = jsonb_set(
                COALESCE(trigger_metrics, '{}'::jsonb),
                '{nav}',
                to_jsonb(%s::numeric),
                true
            ),
            trigger_reason = %s,
            updated_at = NOW()
        WHERE execution_mode = 'live'
    """
    cb_reason = f"T0-19 post-emergency_close audit reset {trade_date}"
    cb_params = (nav, cb_reason)

    if dry_run:
        print(f"[DRY-RUN circuit_breaker_state UPDATE] execution_mode=live "
              f"nav→{nav:,.2f} reason='{cb_reason}'")
        cb_rows = 1
    else:
        cur = conn.cursor()
        cur.execute(cb_sql, cb_params)
        cb_rows = cur.rowcount
        cur.close()

    # position_snapshot 0-row sentinel for trade_date=4-29 (清仓后真状态)
    # 注: 本 step **不 DELETE 4-28 stale**, 仅 INSERT 4-29 sentinel
    ps_sql = """
        INSERT INTO position_snapshot (
            trade_date, strategy_id, code, quantity, avg_cost, market_value,
            execution_mode
        )
        SELECT %s, %s, '_T0_19_SENTINEL_', 0, 0.0, 0.0, 'live'
        WHERE NOT EXISTS (
            SELECT 1 FROM position_snapshot
            WHERE trade_date = %s AND strategy_id = %s
              AND code = '_T0_19_SENTINEL_' AND execution_mode = 'live'
        )
    """
    ps_params = (trade_date, strategy_id, trade_date, strategy_id)

    if dry_run:
        print(f"[DRY-RUN position_snapshot INSERT sentinel] trade_date={trade_date} "
              f"code='_T0_19_SENTINEL_' qty=0 (4-28 stale 19 行 DELETE 留 PT 重启 gate)")
        ps_rows = 1
    else:
        cur = conn.cursor()
        cur.execute(ps_sql, ps_params)
        ps_rows = cur.rowcount
        cur.close()

    return {"cb_state_rows": cb_rows, "position_snapshot_rows": ps_rows}


def _write_idempotency_flag(log_file: Path, summary: dict[str, Any]) -> Path:
    """Final step: 写 .DONE.flag 标完整性证据."""
    flag_path = log_file.with_suffix(".DONE.flag")
    flag_path.write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "trade_log_inserted": summary.get("trade_log_inserted", 0),
                "risk_event_log_id": str(summary.get("risk_event_log_id", "")),
                "audit_chain_complete": True,
            },
            indent=2,
        )
    )
    return flag_path


def write_post_close_audit(
    broker: Any,
    sells_summary: dict[str, Any],
    log_file: Path,
    chat_authorization: dict[str, Any],
    *,
    db_conn: Any = None,
    strategy_id: str = "28fc37e5-2d32-4ada-92e0-41c11a5103d0",
    trade_date: str | None = None,
    dry_run_audit: bool = False,
) -> dict[str, Any]:
    """T0-19 修法主入口: emergency_close post-execution audit + DB sync.

    See module docstring + Phase 1 design §2.

    Args:
        broker: connected broker (本 Phase 2 不调 trader.query, 留 --realtime flag PT gate)
        sells_summary: _execute_sells return dict
        log_file: emergency_close log path (parse fill detail)
        chat_authorization: signature schema (Phase 1 §2.4)
        db_conn: psycopg2 connection (None → app.services.db.get_conn())
        strategy_id: PT strategy UUID
        trade_date: 真成交日 ISO string ('2026-04-29'), None → log 文件名解析
        dry_run_audit: True=不真 INSERT, 仅 print SQL (self-test 模式)

    Returns:
        summary dict per Phase 1 design §2.2 docstring.
    """
    # 真成交日: prefer arg > log 文件名 emergency_close_YYYYMMDD_HHMMSS.log 解析
    if trade_date is None:
        m = re.search(r"emergency_close_(\d{4})(\d{2})(\d{2})_", log_file.name)
        if not m:
            raise T0_19_LogParseError(
                f"trade_date 未指定且 log 文件名无 YYYYMMDD: {log_file.name}"
            )
        trade_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    logger.info("[T0-19 audit] start trade_date=%s dry_run=%s", trade_date, dry_run_audit)

    # DB connection
    if db_conn is None and not dry_run_audit:
        from app.services.db import get_conn  # type: ignore
        db_conn = get_conn()

    # Step 0: 重入检测 (dry_run 模式跳, 因可能多次 self-test)
    if not dry_run_audit and db_conn is not None:
        _check_idempotency(db_conn, trade_date, log_file)

    # Parse log
    fills_by_order = _parse_emergency_close_log(log_file)
    submitted_count = sells_summary.get("submitted_count", 0)
    if len(fills_by_order) != submitted_count and submitted_count > 0:
        logger.warning(
            "[T0-19 audit] order_id 数 (%d) ≠ submitted_count (%d) — partial fills 或 cancelled",
            len(fills_by_order), submitted_count,
        )

    # Step 1: trade_log backfill
    inserted = _backfill_trade_log(
        db_conn, fills_by_order, trade_date, strategy_id, dry_run=dry_run_audit
    )

    # Step 2: risk_event_log audit
    audit_id = _write_risk_event_log_audit(
        db_conn, sells_summary, chat_authorization, trade_date, strategy_id,
        dry_run=dry_run_audit,
    )

    # Step 3: performance_series 当日 row (trade_date=真成交日, 修订 1)
    nav = HARDCODED_NAV_2026_04_30
    perf_id = _write_performance_series_row(
        db_conn, trade_date, strategy_id, nav, dry_run=dry_run_audit
    )

    # Step 4: position_snapshot + cb_state
    step4_result = _clear_position_snapshot_and_reset_cb_state(
        db_conn, trade_date, strategy_id, nav, dry_run=dry_run_audit
    )

    summary = {
        "trade_log_inserted": inserted,
        "risk_event_log_id": audit_id,
        "performance_series_id": perf_id,
        "position_snapshot_rows": step4_result["position_snapshot_rows"],
        "cb_state_reset_to_nav": nav,
        "trade_date": trade_date,
        "dry_run": dry_run_audit,
    }

    # Final: write idempotency flag (real run only)
    if not dry_run_audit:
        if db_conn is not None:
            db_conn.commit()
        flag_path = _write_idempotency_flag(log_file, summary)
        summary["idempotency_flag_path"] = str(flag_path)

    logger.info("[T0-19 audit] done %s", summary)
    return summary
