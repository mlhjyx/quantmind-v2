"""V3 §13.3 元告警 (alert-on-alert) Celery Beat task — HC-1b sub-PR (5min cadence wire).

V3 §13.3 元监控: every 5min collect 5 风控系统失效场景 snapshot → run 5 PURE rules
→ push triggered 元告警 via DingTalk.

Beat schedule (beat_schedule.py):
  "meta-monitor-tick" — crontab(minute="*/5")  # every 5min, all hours

  All-hours cadence (不限 trading hours, 区别于 risk-dynamic-threshold-5min `9-14`):
  风控系统失效可发生在任意时刻 — LiteLLM Beat tasks (news 03/07/.../23 / regime
  9:00/14:30/16:00 / reflector) + STAGED plan cancel_deadline 跨夜 都不限交易时段.
  L1 心跳 collector is HC-1b no-signal (HC-1b2 wires trading-hours-aware real source).

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
# consistency + future (HC-1b2 may add a Redis client / email client to the service).
_service: MetaMonitorService | None = None


def _get_service() -> MetaMonitorService:
    """Lazy singleton MetaMonitorService."""
    global _service
    if _service is None:
        _service = MetaMonitorService()
    return _service


@celery_app.task(
    name="app.tasks.meta_monitor_tasks.meta_monitor_tick",
    soft_time_limit=90,  # 2 DB queries + ≤5 DingTalk push (httpx 5s × retry 3)
    time_limit=180,  # 3min hard kill (反 hung httpx)
)
def meta_monitor_tick() -> dict[str, Any]:
    """V3 §13.3 元告警 5min tick — collect 5 snapshots, run 5 rules, push triggered.

    铁律 32: 本 task is the transaction owner — explicit commit/rollback around
    the full collect → evaluate → push cycle (send_with_dedup's alert_dedup
    write joins this transaction via the injected conn).

    Returns:
        Task result dict (ok / evaluated / triggered / pushed / triggered_rules / at).

    Raises:
        psycopg2.Error: DB query failure (Celery retry per task policy).
        httpx.HTTPError: DingTalk POST failure when DINGTALK_ALERTS_ENABLED
            (fail-loud 铁律 33; HC-1b2 email backup will catch this path).
    """
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
    return result
