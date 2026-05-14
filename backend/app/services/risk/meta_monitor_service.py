"""V3 §13.3 元告警 (alert-on-alert) — Application orchestration (HC-1b).

3-layer (沿用 risk_reflector_agent / market_regime_service 体例):
  - qm_platform/risk/metrics/meta_alert_* = Engine PURE (HC-1a: interface + 5 rules)
  - 本 module = Application orchestration — 5 snapshot 采集 + run 5 PURE rules + DingTalk push
  - app/tasks/meta_monitor_tasks = Beat dispatch (5min cadence)

HC-1b scope (precondition 核 真值 — 2 real collector + 3 no-signal):
  - LiteLLM 失败率: real query `llm_call_log` (error_class NULL=success) ✅
  - STAGED overdue: real query `execution_plans` (status='PENDING_CONFIRM') ✅
  - L1 心跳 / News 全源 timeout / DingTalk push status: 暂 "no signal" 优雅降级 —
    无 clean queryable 源, 需 instrumentation (RealtimeRiskEngine last-tick 暴露 /
    news per-source status 持久化 / DingTalk push outcome 持久化) → HC-1b2 wire real 源.
    HC-1a PURE rule 已优雅处理 no-signal input (last_tick_at=None /
    timed_out_sources=0 / last_push_attempted=False → not triggered) — 这是显式
    设计降级 (logged + documented), 非 silent failure (铁律 33).

HC-1b channel scope: DingTalk only (send_with_dedup). 完整 channel fallback chain
  (主 DingTalk → 备 email → 极端 log-P0) 留 HC-1b2.

铁律 31: qm_platform meta_alert_* PURE; 本 service = Application (DB read via
  injected conn, 0 commit).
铁律 32: 0 conn.commit — Beat task (meta_monitor_tasks) owns transaction boundary.
  send_with_dedup 传入 conn → 不自行 commit (caller owns).
铁律 33: fail-loud — DB error / MetaAlertError propagate.
铁律 41: tz-aware throughout — datetime.now(UTC).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.qm_platform.risk.metrics.meta_alert_interface import (
    LITELLM_FAILURE_RATE_WINDOW_S,
    NEWS_SOURCE_TIMEOUT_WINDOW_S,
    DingTalkPushSnapshot,
    L1HeartbeatSnapshot,
    LiteLLMCallWindowSnapshot,
    MetaAlert,
    NewsSourceWindowSnapshot,
    StagedPlanState,
    StagedPlanWindowSnapshot,
)
from backend.qm_platform.risk.metrics.meta_alert_rules import (
    evaluate_dingtalk_push,
    evaluate_l1_heartbeat,
    evaluate_litellm_failure_rate,
    evaluate_news_sources_timeout,
    evaluate_staged_overdue,
)

logger = logging.getLogger(__name__)

# V3 §13.3 "News 6 源" — placeholder source count for the no-signal News snapshot.
# HC-1b2 wires the real per-source status; until then timed_out_sources=0 → not
# triggered regardless of this count (rule triggers only when timed_out == total).
_NEWS_SOURCE_COUNT_PLACEHOLDER: int = 6

_PENDING_CONFIRM_STATUS = "PENDING_CONFIRM"


class MetaMonitorService:
    """V3 §13.3 元告警 orchestration — collect 5 snapshots, run 5 PURE rules, push.

    Stateless — conn injected per call (沿用 DingTalkWebhookService 体例).
    """

    def __init__(self) -> None:
        pass

    def collect_and_evaluate(self, conn: Any, *, now: datetime | None = None) -> list[MetaAlert]:
        """Collect 5 snapshots + run 5 PURE rules → list of 5 MetaAlert.

        Returns ALL 5 MetaAlert (triggered True 和 False) — caller filters
        `.triggered` for push; non-triggered kept for logging / future
        risk_metrics_daily 元告警-count aggregation.

        Args:
            conn: psycopg2 connection (read-only here; caller owns commit).
            now: injectable clock for tests (default datetime.now(UTC)).

        Returns:
            list[MetaAlert] — 5 items, one per V3 §13.3 元告警 rule.

        Raises:
            psycopg2.Error: DB query failure (caller decides rollback).
            MetaAlertError: snapshot contract violation (e.g. PG returns naive
                datetime — fail-loud per 铁律 33).
        """
        at = now or datetime.now(UTC)

        alerts = [
            evaluate_litellm_failure_rate(self._collect_litellm(conn, at)),
            evaluate_staged_overdue(self._collect_staged(conn, at)),
            evaluate_l1_heartbeat(self._collect_l1_heartbeat(at)),
            evaluate_dingtalk_push(self._collect_dingtalk(at)),
            evaluate_news_sources_timeout(self._collect_news(at)),
        ]
        triggered = [a for a in alerts if a.triggered]
        logger.info(
            "[meta-monitor] evaluated 5 rules @ %s — %d triggered: %s",
            at.isoformat(),
            len(triggered),
            [a.rule_id.value for a in triggered] or "none",
        )
        return alerts

    def push_triggered(self, alerts: list[MetaAlert], *, conn: Any) -> list[dict[str, Any]]:
        """Push triggered MetaAlert via DingTalk (send_with_dedup, conn injected).

        HC-1b channel scope = DingTalk only. 完整 channel fallback chain
        (主 DingTalk → 备 email → 极端 log-P0) 留 HC-1b2.

        Args:
            alerts: list from collect_and_evaluate (this method filters .triggered).
            conn: psycopg2 connection — passed to send_with_dedup so the
                alert_dedup write joins the caller's transaction (铁律 32 — Beat
                task owns commit).

        Returns:
            list of send_with_dedup result dicts (one per triggered alert).

        Raises:
            httpx.HTTPError: DingTalk POST failure when DINGTALK_ALERTS_ENABLED
                (fail-loud per 铁律 33; HC-1b2 email backup will catch this path).

        Retry-atomicity trade-off (reviewer LOW, documented known behavior): if
        alert #1 sends OK (alert_dedup row written) then alert #2's POST raises,
        the Beat task rolls back the whole transaction → alert #1's dedup row is
        also rolled back. On Celery retry alert #1 is re-sent; the alert_dedup
        suppression window then handles duplicate suppression after the
        successful re-send. All-or-nothing is the intended design (反 per-alert
        commit which would violate the single-transaction-boundary 铁律 32).
        """
        from app.services.dingtalk_alert import send_with_dedup  # noqa: PLC0415

        results: list[dict[str, Any]] = []
        for alert in alerts:
            if not alert.triggered:
                continue
            result = send_with_dedup(
                dedup_key=f"meta_alert:{alert.rule_id.value}",
                severity=alert.severity.value,  # MetaAlertSeverity "p0"/"p1"
                source="meta_monitor",
                title=f"元告警 {alert.rule_id.value}",
                body=alert.detail,
                conn=conn,
            )
            results.append(result)
            logger.warning(
                "[meta-monitor] 元告警 triggered rule=%s severity=%s sent=%s reason=%s",
                alert.rule_id.value,
                alert.severity.value,
                result.get("sent"),
                result.get("reason"),
            )
        return results

    # ── Collectors — 2 real (LiteLLM / STAGED) + 3 no-signal (L1 / DingTalk / News) ──

    @staticmethod
    def _collect_litellm(conn: Any, now: datetime) -> LiteLLMCallWindowSnapshot:
        """Real collector — llm_call_log 5min window total + failed (error_class NOT NULL).

        `COUNT(error_class)` counts non-NULL rows = failures (llm_call_log DDL:
        error_class NULL on success / class name on failure). Window is bounded
        both ends [window_start, now] — upper bound 反 clock-skew / injected-past
        `now` in tests (reviewer MEDIUM).
        """
        window_start = now - timedelta(seconds=LITELLM_FAILURE_RATE_WINDOW_S)
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS total, COUNT(error_class) AS failed
                FROM llm_call_log
                WHERE triggered_at >= %s AND triggered_at <= %s
                """,
                (window_start, now),
            )
            row = cur.fetchone()
            total = int(row[0]) if row and row[0] is not None else 0
            failed = int(row[1]) if row and row[1] is not None else 0
        finally:
            cur.close()
        return LiteLLMCallWindowSnapshot(
            total_calls=total,
            failed_calls=failed,
            window_seconds=LITELLM_FAILURE_RATE_WINDOW_S,
            now=now,
        )

    @staticmethod
    def _collect_staged(conn: Any, now: datetime) -> StagedPlanWindowSnapshot:
        """Real collector — execution_plans status='PENDING_CONFIRM'.

        pending_since = created_at (plan 创建即进 PENDING_CONFIRM per L4 flow —
        execution_plans 无独立 status-transition timestamp column, created_at 是
        直接 proxy; HC-1b precondition 核 verified migration schema).

        tz-aware invariant: created_at is TIMESTAMPTZ → psycopg2 returns tz-aware
        datetime by default. If this invariant is ever violated (naive datetime),
        StagedPlanState.__post_init__ fails loud with MetaAlertError (铁律 33 —
        反 silent-coerce, NOT replace(tzinfo=UTC) which could mask wrong-tz data).
        """
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT plan_id::text, status, created_at
                FROM execution_plans
                WHERE status = %s
                """,
                (_PENDING_CONFIRM_STATUS,),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        plans = tuple(
            StagedPlanState(plan_id=str(r[0]), status=str(r[1]), pending_since=r[2]) for r in rows
        )
        return StagedPlanWindowSnapshot(plans=plans, now=now)

    @staticmethod
    def _collect_l1_heartbeat(now: datetime) -> L1HeartbeatSnapshot:
        """No-signal collector (HC-1b2 wires real source).

        RealtimeRiskEngine 不暴露 last-tick timestamp + 无 clean queryable 源
        (precondition 核 真值). last_tick_at=None → PURE rule not triggered +
        detail "no heartbeat data". HC-1b2 instruments the engine / Redis
        market-data freshness as the real source.
        """
        logger.debug("[meta-monitor] L1 heartbeat collector = no-signal (HC-1b2 wires real source)")
        return L1HeartbeatSnapshot(last_tick_at=None, now=now)

    @staticmethod
    def _collect_dingtalk(now: datetime) -> DingTalkPushSnapshot:
        """No-signal collector (HC-1b2 wires real source).

        DingTalk push outcome 无持久化 (alert_dedup 只追踪 fire_count, 不含
        success/failure; send_with_dedup 只返回瞬时结果). last_push_attempted=False
        → PURE rule not triggered. HC-1b2 adds push-outcome persistence.
        """
        logger.debug(
            "[meta-monitor] DingTalk push collector = no-signal (HC-1b2 wires real source)"
        )
        return DingTalkPushSnapshot(
            last_push_attempted=False,
            last_push_ok=False,
            last_push_status="",
            now=now,
        )

    @staticmethod
    def _collect_news(now: datetime) -> NewsSourceWindowSnapshot:
        """No-signal collector (HC-1b2 wires real source).

        NewsIngestionService.ingest() 不暴露 per-source timeout status —
        IngestionStats 只含 fetched/ingested/classified counts (precondition 核
        真值). timed_out_sources=0 → PURE rule not triggered. HC-1b2 instruments
        per-source status persistence as the real source.
        """
        logger.debug("[meta-monitor] News source collector = no-signal (HC-1b2 wires real source)")
        return NewsSourceWindowSnapshot(
            total_sources=_NEWS_SOURCE_COUNT_PLACEHOLDER,
            timed_out_sources=0,
            window_seconds=NEWS_SOURCE_TIMEOUT_WINDOW_S,
            now=now,
        )


__all__ = ["MetaMonitorService"]
