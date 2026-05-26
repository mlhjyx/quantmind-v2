"""Realtime risk tick task — Phase J §1.1 Chunk 2 (iter 154).

L1 RealtimeRiskEngine production wire entry point. Beat schedule:
  "realtime-risk-tick" — crontab(minute="*/1", hour="9-14", day_of_week="1-5")
  Trading-hours-only (9:00-14:59 SH), 1min cadence (matches risk-l4-sweep-1min
  precedent). expires=45 (within next 60s cycle, 反 overlap on slow ctx build).

Design: docs/mvp/MVP_4_5_l1_realtime_risk_wire.md §3 Chunk 2.

Wire chain (MVP — Chunks 3+4+5 layer on top):
  Beat fire → instantiate RealtimeRiskEngine (10 rules via register_all_realtime_rules)
            → RealtimeRiskContextBuilder.build_context (Chunk 1)
            → engine.on_tick(context) → list[RuleResult]
            → engine.on_5min_beat(context) → list[RuleResult] (when minute % 5 == 0)
            → log + scheduler_task_log audit row (this chunk stops here)

Subsequent chunks:
  Chunk 3: DynamicThreshold cache wire (engine.set_threshold_cache)
  Chunk 4: AlertDispatcher P0/P1/P2 wire (dingtalk_alert.send_with_retry)
  Chunk 5: L4 ExecutionPlanner wire (planner.generate_plan + execution_plans INSERT)
  Chunk 6: Smoke test + calendar gate (is_trading_day_today_or_skip)

铁律 alignment:
  31 — qm_platform Engine 纯计算 (this task is Application layer per §3 architecture)
  32 — Celery task = transaction owner (post-Chunk-5 when DB writes wire)
  33 — fail-loud (PositionSourceError propagates; engine errors raise)
  41 — Asia/Shanghai timezone via celery_app.py; datetime.now(UTC) internal
  44 X9 — post-merge ops `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`

Sibling canonical: backend/app/tasks/meta_monitor_tasks.py (iter 132 LL-204).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.risk.realtime_context_builder import (
    PositionSourceError,
    RealtimeRiskContextBuilder,
)
from app.tasks.celery_app import celery_app
from backend.qm_platform.risk.dynamic_threshold.cache import RedisThresholdCache
from backend.qm_platform.risk.realtime.engine import RealtimeRiskEngine
from backend.qm_platform.risk.realtime.rule_registry import register_all_realtime_rules

logger = logging.getLogger("celery.realtime_risk_tasks")

# Module-level lazy singleton (sustains startup cost; same pattern as
# meta_monitor_tasks._service). Engine instantiation includes 10 rule
# registration (cheap, < 10ms).
_engine: RealtimeRiskEngine | None = None
_context_builder: RealtimeRiskContextBuilder | None = None


def _get_engine() -> RealtimeRiskEngine:
    """Lazy singleton RealtimeRiskEngine with 10 rules + DynamicThreshold cache.

    iter 155 Chunk 3 — wire RedisThresholdCache into engine. The cache is
    populated by existing `risk-dynamic-threshold-5min` Beat task
    (DynamicThresholdEngine writes per-rule per-code thresholds, 5min TTL).
    Engine `_apply_dynamic_thresholds` (engine.py:98-99) reads via cache.get()
    and calls rule.update_threshold(); when cache is None or returns None,
    engine gracefully skips threshold update (rule uses static fallback).

    Sustained MVP 4.5 §3 Chunk 3 spec — RedisThresholdCache constructed lazy
    (no Redis client injected → cache._ensure_redis() lazy-connects).
    """
    global _engine
    if _engine is None:
        _engine = RealtimeRiskEngine()
        register_all_realtime_rules(_engine)
        # iter 155 Chunk 3: wire DynamicThreshold cache (S7→S5 sustained)
        threshold_cache = RedisThresholdCache()  # lazy redis init, DI-compatible
        _engine.set_threshold_cache(threshold_cache)
        logger.info(
            "[realtime-risk-beat] Engine bootstrapped: 10 rules + RedisThresholdCache wired"
        )
    return _engine


def _get_context_builder() -> RealtimeRiskContextBuilder:
    """Lazy singleton context builder."""
    global _context_builder
    if _context_builder is None:
        _context_builder = RealtimeRiskContextBuilder()
    return _context_builder


# ════════════════════════════════════════════════════════════
# scheduler_task_log helper (iter 132 LL-204 canonical sibling pattern)
# ════════════════════════════════════════════════════════════


def _write_scheduler_log_safe(
    task_name: str,
    start_time: datetime,
    status: str,
    result_json: dict | None,
) -> None:
    """Best-effort scheduler_task_log INSERT (silent_ok on failure).

    Sibling pattern from meta_monitor_tasks._write_scheduler_log_safe.
    Module-local copy per LL-206 (promote to shared service when 5+ callers).
    """
    import psycopg2.extras  # noqa: PLC0415

    from app.services.db import get_sync_conn  # noqa: PLC0415

    end_time = datetime.now(UTC)
    duration_sec = int((end_time - start_time).total_seconds())
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scheduler_task_log
                   (task_name, market, schedule_time, start_time, end_time,
                    duration_sec, status, result_json)
                   VALUES (%s, 'astock', %s, %s, %s, %s, %s, %s)""",
                (
                    task_name,
                    start_time,
                    start_time,
                    end_time,
                    duration_sec,
                    status,
                    psycopg2.extras.Json(result_json or {}),
                ),
            )
    except Exception as e:  # noqa: BLE001
        # silent_ok: scheduler_task_log 失败不阻断主流程 audit/alert action 已完成.
        logger.warning(
            "[scheduler_task_log] write failed task=%s: %s: %s",
            task_name,
            type(e).__name__,
            e,
        )


@celery_app.task(
    name="app.tasks.realtime_risk_tasks.realtime_risk_tick",
    soft_time_limit=30,  # Cheap eval (10 rules × ~20 positions, < 5s typical)
    time_limit=45,  # Beat expires=45 alignment
)
def realtime_risk_tick() -> dict[str, Any]:
    """L1 RealtimeRiskEngine production wire — Phase J §1.1 Chunk 2.

    Beat 入口 `realtime-risk-tick` 1min trading-hours-only.

    iter 154 MVP scope: instantiate + register rules + evaluate. NO alert
    dispatch (Chunk 3+) + NO plan persist (Chunk 5). Returns RuleResult counts
    + audit log row for verifiability.

    Returns:
        dict — {ok, evaluated_tick, evaluated_5min, triggered, at}.
        Stale data path: {ok: False, reason: 'stale_market_data', at}.

    Raises:
        Engine errors propagate (per 铁律 33 fail-loud, no silent suppression).
    """
    _audit_start = datetime.now(UTC)
    _audit_status = "error"
    _audit_summary: dict = {}
    try:
        engine = _get_engine()
        builder = _get_context_builder()

        try:
            ctx = builder.build_context()
        except PositionSourceError as e:
            # Stale Redis market data — log + skip this tick (no false fire)
            logger.warning("[realtime-risk-beat] stale data, skip tick: %s", e)
            result: dict[str, Any] = {
                "ok": False,
                "reason": "stale_market_data",
                "error": str(e),
                "at": _audit_start.isoformat(),
            }
            _audit_summary = result
            _audit_status = "skipped"  # not 'error' — expected fail-soft path
            return result

        # tick cadence — every fire (1min)
        tick_results = engine.on_tick(ctx)

        # 5min cadence — when minute boundary aligned (Beat fires at :00, :05, ...)
        five_min_results: list = []
        if _audit_start.minute % 5 == 0:
            five_min_results = engine.on_5min_beat(ctx)

        # 15min cadence — Chunk 2 MVP defers (Chunk 6 add when needed)
        # if _audit_start.minute % 15 == 0:
        #     fifteen_min_results = engine.on_15min_beat(ctx)

        all_results = tick_results + five_min_results
        triggered = [r for r in all_results if r is not None]

        result = {
            "ok": True,
            "evaluated_tick": len(tick_results),
            "evaluated_5min": len(five_min_results),
            "triggered": len(triggered),
            "triggered_rules": [r.rule_id for r in triggered][:10],  # cap display
            "positions": len(ctx.positions),
            "portfolio_nav": ctx.portfolio_nav,
            "at": _audit_start.isoformat(),
        }
        logger.info("[realtime-risk-beat] tick complete: %s", result)
        _audit_summary = result
        _audit_status = "success"
        return result
    except Exception as e:
        if _audit_status == "error":
            _audit_summary = {
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "at": _audit_start.isoformat(),
            }
        raise
    finally:
        _write_scheduler_log_safe(
            "realtime_risk_tick",
            _audit_start,
            _audit_status,
            _audit_summary,
        )
