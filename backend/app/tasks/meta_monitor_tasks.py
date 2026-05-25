"""V3 §13.3 + §14 元告警 (alert-on-alert) Celery Beat task — HC-1b sub-PR (5min cadence wire).

V3 §13.3 + §14 元监控: every 5min collect 7 风控系统失效场景 snapshot → run 7 PURE
rules → push triggered 元告警 via DingTalk (HC-2b3 added PG health + 千股跌停 regime).

Beat schedule (beat_schedule.py):
  "meta-monitor-tick" — crontab(minute="*/5")  # every 5min, all hours

  All-hours cadence (不限 trading hours, 区别于 risk-dynamic-threshold-5min `9-14`):
  风控系统失效可发生在任意时刻 — LiteLLM Beat tasks (news 03/07/.../23 / regime
  9:00/14:30/16:00 / reflector) + STAGED plan cancel_deadline 跨夜 都不限交易时段.
  L1 心跳 collector is no-signal (HC-1b3 wires trading-hours-aware real source).

  反 hard collision: outbox 30s + dynamic-threshold/l4-sweep (`9-14`) + news cron
  (minute=0) + regime/reflector + daily-metrics 16:30 — all cadence-different OR
  Beat sequential dispatch + Worker --pool=solo tolerates (cheap 2-query task).

3-layer (沿用 market_regime_tasks / risk_reflector_tasks 体例):
  - qm_platform/risk/metrics/meta_alert_* = Engine PURE (HC-1a)
  - app/services/risk/meta_monitor_service = Application orchestration (HC-1b)
  - 本 module = Beat dispatch + transaction owner

铁律 32: 本 task = transaction owner — explicit conn.commit / rollback.
  MetaMonitorService.collect_and_evaluate + push_triggered 0 commit.
  send_with_dedup alert_dedup write joins 本 task's transaction (conn injected).
铁律 33: fail-loud — DB error / httpx error propagate per Celery retry.
铁律 41: Asia/Shanghai timezone via celery_app.py; datetime.now(UTC) internal.
铁律 44 X9: post-merge ops `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
  per docs/runbook/cc_automation/v3_hc_1b_meta_monitor_beat_wire.md.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.risk.meta_monitor_service import MetaMonitorService
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.meta_monitor_tasks")

# Module-level lazy singleton (沿用 risk_reflector_tasks / market_regime_tasks 体例).
# MetaMonitorService is stateless + cheap, but the singleton 体例 is kept for
# consistency + future (HC-1b3 may add a Redis client to the service for L1 heartbeat).
_service: MetaMonitorService | None = None


def _get_service() -> MetaMonitorService:
    """Lazy singleton MetaMonitorService."""
    global _service
    if _service is None:
        _service = MetaMonitorService()
    return _service


# ════════════════════════════════════════════════════════════
# scheduler_task_log helper (iter 132 — Wave 4 audit envelope, LL-204 canonical)
# ════════════════════════════════════════════════════════════
# 镜像 daily_pipeline.py:_write_scheduler_log_safe (Session 44 Phase 2 Step C, iter 103
# PR #479 LL-204 sediment). Module-local copy per LL-206 sibling pattern; iter 134+
# promotion candidate to shared service when 5+ callers established (meta_monitor +
# attribution + 2x backup + report + factor_lifecycle/risk_daily_check/intraday).
# 铁律 33(c) 读路径 audit 失败 fail-silent + logger.warning, 不阻塞主流程.
# iter 132 (2026-05-26): W2-A F1 P0 closure — silent dispatch gap (0 scheduler_task_log
# row past 7d for meta-monitor-tick despite Beat firing /5min sustained).


def _write_scheduler_log_safe(
    task_name: str,
    start_time: datetime,
    status: str,
    result_json: dict | None,
) -> None:
    """Best-effort scheduler_task_log INSERT (silent_ok on failure).

    Args:
        task_name: Beat schedule entry name (e.g. "meta_monitor")
        start_time: task 进入 timestamp (UTC, 上游捕获)
        status: 'success' | 'skipped' | 'disabled' | 'error' | 'retry'
        result_json: task summary dict (or {"error": str} on exception)
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
                    start_time,  # schedule_time ≈ start_time (Beat 触发时刻)
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
    name="app.tasks.meta_monitor_tasks.meta_monitor_tick",
    soft_time_limit=90,  # 2 DB queries + ≤5 DingTalk push (httpx 5s × retry 3)
    time_limit=180,  # 3min hard kill (反 hung httpx)
)
def meta_monitor_tick() -> dict[str, Any]:
    """V3 §13.3 + §14 元告警 5min tick — collect 7 snapshots, run 7 rules, push triggered.

    铁律 32: 本 task is the transaction owner — explicit commit/rollback around
    the full collect → evaluate → push cycle (send_with_dedup's alert_dedup
    write joins this transaction via the injected conn).

    iter 132 (2026-05-26): wrapped with scheduler_task_log audit envelope per W2-A F1
    P0 closure (sibling daily_pipeline.py factor_lifecycle_task iter 103 LL-204
    canonical). Envelope ensures EVERY tick leaves a proof-of-life row, eliminating
    silent dispatch gap (0 row in 7d audit despite Beat firing 2728+ times sustained).

    Returns:
        Task result dict (ok / evaluated / triggered / pushed / triggered_rules / at).

    Raises:
        psycopg2.Error: DB query / alert_dedup write failure — propagates for
            Celery retry (铁律 33). DingTalk/email channel failures do NOT
            propagate: the channel fallback chain catches them and escalates
            (主 DingTalk → 备 email → 极端 log-P0), so a channel-down does not
            crash the tick — only a borked DB transaction does.
    """
    # iter 132: scheduler_task_log audit envelope (LL-204 canonical sibling pattern).
    _audit_start = datetime.now(UTC)
    _audit_status = "error"  # default if exception escapes try
    _audit_summary: dict = {}
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415

        service = _get_service()
        now = datetime.now(UTC)
        conn = get_sync_conn()
        try:
            alerts = service.collect_and_evaluate(conn, now=now)
            push_results = service.push_triggered(alerts, conn=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        triggered = [a for a in alerts if a.triggered]
        result: dict[str, Any] = {
            "ok": True,
            "evaluated": len(alerts),
            "triggered": len(triggered),
            "pushed": len(push_results),
            "triggered_rules": [a.rule_id.value for a in triggered],
            "at": now.isoformat(),
        }
        logger.info("[meta-monitor-beat] tick complete: %s", result)
        _audit_summary = result
        _audit_status = "success"
        return result
    except Exception as e:
        if _audit_status == "error":
            _audit_summary = {
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            }
        raise
    finally:
        _write_scheduler_log_safe(
            "meta_monitor",
            _audit_start,
            _audit_status,
            _audit_summary,
        )
