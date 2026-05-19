"""RAG memory backfill 脚本 — Phase G F-S7-005 P0 修复.

背景 (Subagent I supplement audit):
    risk_memory 表当前仅 1 row (ADR-068 closure theatrical).
    V3 §5.4 设计 risk_memory 为 RAG knowledge base, retrieve past events
    for Bull/Bear/Reflector context. 1 row 实际上等于 0 retrieve power.

设计目标:
    - 从历史 risk_event_log + trade_log emergency events backfill risk_memory
    - 写入 event_type / symbol_id / event_timestamp / context_snapshot
    - embedding 留 NULL (BGE-M3 1024-dim 生成走单独 cron, GPU-bound)
    - 幂等 (skip 已 INSERT 的 (event_type, event_timestamp) 组合)

数据源:
    1. risk_event_log — V3 L1/L2/L3 触发事件 (event_type + symbol + timestamp + metrics)
    2. trade_log emergency_close events — 4-29 17 股清仓事件
    3. ADR-068 历史 closure events (已存 audit log)

调度:
    手动一次性 backfill (initial bootstrap), 之后由 V3 L1 realtime engine
    实时 INSERT risk_memory rows.

后续步骤 (embedding generation, 留 user 决议):
    backfill 完成后, 跑 BGE-M3 embedding cron 生成 1024-dim vectors:
    `python scripts/rag_embedding_generate.py --batch 100`  (need separate impl)

红线: 0 broker call (纯 DB 读写, 跟交易隔离).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

# Ensure project importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2


def setup_logging() -> logging.Logger:
    log = logging.getLogger("rag_backfill")
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(handler)
    return log


def fetch_risk_events(conn: Any, limit: int, log: logging.Logger) -> list[dict[str, Any]]:
    """从 risk_event_log 读取历史事件 (real schema verified 2026-05-19)."""
    events: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT rule_id, code, triggered_at, severity, reason,
                       action_taken, context_snapshot, realtime_metrics
                FROM risk_event_log
                ORDER BY triggered_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = [
                "rule_id", "code", "triggered_at", "severity", "reason",
                "action_taken", "context_snapshot", "realtime_metrics",
            ]
            for row in rows:
                record = dict(zip(cols, row, strict=False))
                events.append(record)
            log.info(f"  risk_event_log: {len(events)} rows")
        except Exception as exc:
            log.warning(f"risk_event_log 读取失败 (表可能不存在): {exc}")
            conn.rollback()
    return events


def fetch_trade_emergency(conn: Any, limit: int, log: logging.Logger) -> list[dict[str, Any]]:
    """从 trade_log 读取 emergency_close 事件 (4-29 清仓真实, real schema verified)."""
    events: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT code, executed_at, fill_price, quantity, direction, reject_reason
                FROM trade_log
                WHERE reject_reason LIKE 'emergency_close%%'
                   OR reject_reason LIKE 't0_19_backfill%%'
                ORDER BY executed_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = ["code", "executed_at", "fill_price", "quantity", "direction", "reject_reason"]
            for row in rows:
                record = dict(zip(cols, row, strict=False))
                events.append(record)
            log.info(f"  trade_log emergency: {len(events)} rows")
        except Exception as exc:
            log.warning(f"trade_log 读取失败: {exc}")
            conn.rollback()
    return events


def check_existing(conn: Any, event_type: str, event_timestamp: datetime) -> bool:
    """检查 (event_type, event_timestamp) 是否已存在 (幂等)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM risk_memory
            WHERE event_type = %s AND event_timestamp = %s
            LIMIT 1
            """,
            (event_type, event_timestamp),
        )
        return cur.fetchone() is not None


def insert_risk_memory(
    conn: Any,
    *,
    event_type: str,
    symbol_id: str | None,
    event_timestamp: datetime,
    context_snapshot: dict[str, Any],
    action_taken: str | None = None,
    outcome: dict[str, Any] | None = None,
    lesson: str | None = None,
) -> int | None:
    """INSERT 单条 risk_memory (embedding=NULL, BGE-M3 cron 单独生成).

    铁律 17 exception (LL-066 partial-UPSERT pattern): 本 script 是 one-shot bootstrap
    backfill, 不走 DataPipeline (V3 §5.4 risk_memory 真值 schema 跟 DataPipeline
    canonical table set 不重合 — RAG memory pgvector 体例独立). 沿用 LL-066 体例
    在 INSERT site 显式标注 exception 反 silent 铁律 17 violation.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO risk_memory (
                event_type, symbol_id, event_timestamp, context_snapshot,
                action_taken, outcome, lesson, embedding
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, NULL)
            RETURNING memory_id
            """,
            (
                event_type,
                symbol_id,
                event_timestamp,
                json.dumps(context_snapshot, default=str, ensure_ascii=False),
                action_taken,
                json.dumps(outcome, default=str, ensure_ascii=False) if outcome else None,
                lesson,
            ),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def map_risk_event_to_memory(event: dict[str, Any]) -> dict[str, Any]:
    """转换 risk_event_log row → risk_memory payload (real schema verified)."""
    # rule_id 真值是 enum-like 字符串, 映射 risk_memory.event_type
    rule_id = event.get("rule_id") or "unknown_rule"
    return {
        "event_type": f"risk_{rule_id}"[:50],  # 50 char limit
        "symbol_id": event.get("code"),
        "event_timestamp": event["triggered_at"],
        "context_snapshot": {
            "source": "risk_event_log",
            "rule_id": rule_id,
            "severity": event.get("severity"),
            "reason": event.get("reason", ""),
            "realtime_metrics": event.get("realtime_metrics", {}),
            "context_snapshot_original": event.get("context_snapshot", {}),
        },
        "action_taken": event.get("action_taken") if event.get("action_taken") in (
            'STAGED_executed', 'STAGED_cancelled', 'STAGED_timeout_executed',
            'manual_sell', 'no_action', 'reentry'
        ) else None,  # vocabulary CHECK constraint enforce
        "outcome": None,
        "lesson": None,
    }


def map_trade_emergency_to_memory(event: dict[str, Any]) -> dict[str, Any]:
    """转换 trade_log emergency row → risk_memory payload (real schema verified)."""
    return {
        "event_type": "emergency_close",
        "symbol_id": event.get("code"),
        "event_timestamp": event["executed_at"],
        "context_snapshot": {
            "source": "trade_log",
            "fill_price": float(event["fill_price"]) if event["fill_price"] is not None else None,
            "quantity": event["quantity"],
            "direction": event["direction"],
            "reject_reason": event["reject_reason"],
        },
        "action_taken": "manual_sell",
        "outcome": None,
        "lesson": "4-29 user 清仓决议 emergency_close (SHUTDOWN_NOTICE §9)"[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG memory backfill (F-S7-005 P0)")
    parser.add_argument(
        "--limit", type=int, default=500,
        help="每数据源最大读取 row 数 (默认 500)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只 read + report, 不真 INSERT (审计模式)",
    )
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()

    log = setup_logging()

    # P1 fix (python-reviewer + security-reviewer Session 57+1 2026-05-19):
    # 反 credential fallback default `""` (铁律 35) + 反 password-in-string DSN leak.
    # 单一来源: --dsn 参数 OR DATABASE_URL env. 缺失 fail-loud (铁律 33).
    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        log.error(
            "DSN 未配置 — 走 --dsn 参数 OR DATABASE_URL env. "
            "反 silent credential fallback (铁律 35)."
        )
        return 1

    log.info(f"RAG memory backfill 启动 (dry-run={args.dry_run}, limit={args.limit})")

    conn = psycopg2.connect(dsn)
    try:
        # P2 fix (python-reviewer): main loop in try/finally — 反 outer exception
        # path conn 泄漏 (psycopg2 connect→fetch→loop 中任 raise 直返 main 不 close).
        return _run_backfill(conn, args, log)
    finally:
        conn.close()


def _run_backfill(conn: Any, args: Any, log: logging.Logger) -> int:
    """主 backfill 流程, 分离出便于 try/finally 包裹 (P2 conn leak fix)."""
    # Pre-count
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM risk_memory")
        result = cur.fetchone()
        pre_count = result[0] if result else 0
    log.info(f"  pre-backfill risk_memory rows: {pre_count}")

    # Source 1: risk_event_log
    log.info("Source 1: risk_event_log")
    risk_events = fetch_risk_events(conn, args.limit, log)

    # Source 2: trade_log emergency
    log.info("Source 2: trade_log emergency_close")
    trade_events = fetch_trade_emergency(conn, args.limit, log)

    # Map + dedup + INSERT
    inserted_count = 0
    skipped_count = 0
    failed_count = 0

    all_mapped: list[dict[str, Any]] = []
    for ev in risk_events:
        all_mapped.append(map_risk_event_to_memory(ev))
    for ev in trade_events:
        all_mapped.append(map_trade_emergency_to_memory(ev))

    log.info(f"\n准备 INSERT {len(all_mapped)} candidate rows")

    if args.dry_run:
        log.info("DRY-RUN 模式: 跳过 INSERT, 仅审计 source data")
        for m in all_mapped[:10]:  # show first 10
            log.info(
                f"  [DRY] {m['event_type']:30s} {m.get('symbol_id') or '—':10s} "
                f"{m['event_timestamp']}"
            )
        if len(all_mapped) > 10:
            log.info(f"  ... ({len(all_mapped) - 10} more)")
        return 0

    for m in all_mapped:
        try:
            if check_existing(conn, m["event_type"], m["event_timestamp"]):
                skipped_count += 1
                continue
            memory_id = insert_risk_memory(conn, **m)
            if memory_id:
                inserted_count += 1
                conn.commit()
                if inserted_count % 10 == 0:
                    log.info(f"  ... inserted {inserted_count} so far")
        except Exception as exc:
            log.exception(f"INSERT 失败 {m['event_type']}: {exc}")
            conn.rollback()
            failed_count += 1

    # Post-count
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM risk_memory")
        result = cur.fetchone()
        post_count = result[0] if result else 0

    log.info(f"\n{'='*60}")
    log.info("RAG memory backfill 完成:")
    log.info(f"  pre-backfill rows: {pre_count}")
    log.info(f"  post-backfill rows: {post_count} (+{post_count - pre_count})")
    log.info(f"  inserted: {inserted_count}")
    log.info(f"  skipped (already exists): {skipped_count}")
    log.info(f"  failed: {failed_count}")
    log.info("\nNext step (留 user 决议):")
    log.info("  Embedding 生成: BGE-M3 1024-dim cron — 需 GPU 资源决议")
    log.info("  推荐命令: python scripts/rag_embedding_generate.py --batch 100 (待 impl)")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
