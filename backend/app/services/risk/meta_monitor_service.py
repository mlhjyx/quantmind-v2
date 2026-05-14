"""V3 §13.3 + §14 元告警 (alert-on-alert) — Application orchestration (HC-1b + HC-2b3).

3-layer (沿用 risk_reflector_agent / market_regime_service 体例):
  - qm_platform/risk/metrics/meta_alert_* = Engine PURE (HC-1a + HC-2b3: interface + 7 rules)
  - 本 module = Application orchestration — 7 snapshot 采集 + run 7 PURE rules + DingTalk push
  - app/tasks/meta_monitor_tasks = Beat dispatch (5min cadence)

Collector status (post-HC-2b3 — 6 real + 1 no-signal):
  - LiteLLM 失败率: real query `llm_call_log` (error_class NULL=success) ✅ HC-1b
  - STAGED overdue: real query `execution_plans` (status='PENDING_CONFIRM') ✅ HC-1b
  - DingTalk push status: real query `alert_dedup.last_push_ok` ✅ HC-1b3
  - News 全源 timeout: real read Redis `qm:news:last_run_stats` ✅ HC-1b3
  - PG OOM/lock: real query `pg_stat_activity` (idle-in-transaction count) ✅ HC-2b3 G3
  - 千股跌停极端 regime: real query `index_daily` + `klines_daily` via
    market_indicators_query (V3 §14 mode 9) ✅ HC-2b3 G4
  - L1 心跳: no-signal (last_tick_at=None) — DEFERRED per HC-1b3 Finding (no
    production XtQuantTickSubscriber runner exists to instrument; instrumenting
    would never fire — see `_collect_l1_heartbeat`). 不是 "not yet wired", 是
    "源在 production 尚不存在" — 留 realtime engine production-wiring (Plan v0.4
    cutover scope 候选). HC-1a PURE rule 优雅处理 no-signal input → not triggered.

Channel fallback chain (V3 §13.3, HC-1b2): 主 DingTalk → 备 email → 极端 log-P0
  (`_push_via_channel_chain`). DingTalk unreachable / configured-but-undeliverable
  → escalate email; email not-delivered / failed → escalate log-P0 (元告警 never
  silently vanishes).

铁律 31: qm_platform meta_alert_* PURE; 本 service = Application (DB read via
  injected conn, 0 commit).
铁律 32: 0 conn.commit — Beat task (meta_monitor_tasks) owns transaction boundary.
  send_with_dedup 传入 conn → 不自行 commit (caller owns).
铁律 33: fail-loud — DB error / MetaAlertError propagate.
铁律 41: tz-aware throughout — datetime.now(UTC).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.services.risk.market_indicators_query import (
    query_index_return,
    query_limit_down_count,
)
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    LITELLM_FAILURE_RATE_WINDOW_S,
    NEWS_RUN_STATS_REDIS_KEY,
    NEWS_SOURCE_TIMEOUT_WINDOW_S,
    DingTalkPushSnapshot,
    L1HeartbeatSnapshot,
    LiteLLMCallWindowSnapshot,
    MarketCrisisSnapshot,
    MetaAlert,
    NewsSourceWindowSnapshot,
    PGHealthSnapshot,
    StagedPlanState,
    StagedPlanWindowSnapshot,
)
from backend.qm_platform.risk.metrics.meta_alert_rules import (
    evaluate_dingtalk_push,
    evaluate_l1_heartbeat,
    evaluate_litellm_failure_rate,
    evaluate_market_crisis,
    evaluate_news_sources_timeout,
    evaluate_pg_health,
    evaluate_staged_overdue,
)

logger = logging.getLogger(__name__)

_PENDING_CONFIRM_STATUS = "PENDING_CONFIRM"

# HC-1b3: NEWS_RUN_STATS_REDIS_KEY imported from meta_alert_interface (SSOT — single
# definition shared by the News-ingest Beat writer + this collector reader).
# Fallback total_sources when the News run-stats key is absent (key expired / news
# Beat never ran). Only used for the no-signal NewsSourceWindowSnapshot — rule
# triggers only when timed_out == total, and timed_out=0 in that path → not triggered.
_NEWS_SOURCE_COUNT_FALLBACK: int = 6


class MetaMonitorService:
    """V3 §13.3 + §14 元告警 orchestration — collect 7 snapshots, run 7 PURE rules, push.

    conn injected per call; optional redis_client injected at construction (DI
    体例 sustained IntradayAlertDedup) — used by the News collector.
    """

    def __init__(self, *, redis_client: Any = None) -> None:
        """Args:
        redis_client: optional injected Redis client (tests inject a mock).
            None → lazy-created from settings.REDIS_URL on first News-collector
            call (沿用 IntradayAlertDedup redis.from_url 体例).
        """
        self._redis = redis_client

    def _get_redis(self) -> Any:
        """Lazy Redis client (沿用 IntradayAlertDedup — decode_responses=True)."""
        if self._redis is None:
            import redis as redis_lib  # noqa: PLC0415

            from app.config import settings  # noqa: PLC0415

            self._redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def collect_and_evaluate(self, conn: Any, *, now: datetime | None = None) -> list[MetaAlert]:
        """Collect 7 snapshots + run 7 PURE polled rules → list of 7 MetaAlert.

        Returns ALL 7 MetaAlert (triggered True 和 False) — caller filters
        `.triggered` for push; non-triggered kept for logging / future
        risk_metrics_daily 元告警-count aggregation. Event-emitted rules
        (RISK_REFLECTOR_FAILED / BROKER_PLAN_STUCK) are NOT polled here — the
        failure-source tasks emit those directly (see MetaAlertRuleId docstring).

        Args:
            conn: psycopg2 connection (read-only here; caller owns commit).
            now: injectable clock for tests (default datetime.now(UTC)).

        Returns:
            list[MetaAlert] — 7 items, one per V3 §13.3 + §14 polled 元告警 rule.

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
            evaluate_dingtalk_push(self._collect_dingtalk(conn, at)),
            evaluate_news_sources_timeout(self._collect_news(at)),
            evaluate_pg_health(self._collect_pg_health(conn, at)),
            evaluate_market_crisis(self._collect_market_crisis(conn, at)),
        ]
        triggered = [a for a in alerts if a.triggered]
        logger.info(
            "[meta-monitor] evaluated 7 rules @ %s — %d triggered: %s",
            at.isoformat(),
            len(triggered),
            [a.rule_id.value for a in triggered] or "none",
        )
        return alerts

    def push_triggered(self, alerts: list[MetaAlert], *, conn: Any) -> list[dict[str, Any]]:
        """Push triggered MetaAlert via V3 §13.3 channel fallback chain (HC-1b2).

        Channel fallback chain: 主 DingTalk → 备 email → 极端 log-P0. Per-alert
        chain is `_push_via_channel_chain`.

        Args:
            alerts: list from collect_and_evaluate (this method filters .triggered).
            conn: psycopg2 connection — passed to send_with_dedup so the
                alert_dedup write joins the caller's transaction (铁律 32 — Beat
                task owns commit).

        Returns:
            list of channel-result dicts (one per triggered alert; each has a
            `channel` key ∈ "dingtalk"/"email"/"log_p0" + `rule_id` + the
            underlying helper's result fields).

        Raises:
            psycopg2.Error: alert_dedup write failure inside send_with_dedup —
                propagates (DB transaction is borked; Beat task rolls back +
                Celery retries). NOT escalated to email — DB error is a
                different failure class than "DingTalk unreachable".

        Retry-atomicity trade-off (documented known behavior): if alert #1 sends
        OK (alert_dedup row written) then alert #2's chain hits a psycopg2.Error,
        the Beat task rolls back the whole transaction → alert #1's dedup row is
        also rolled back. On Celery retry alert #1 is re-sent; the alert_dedup
        suppression window then handles duplicate suppression after the
        successful re-send. All-or-nothing is the intended design (反 per-alert
        commit which would violate the single-transaction-boundary 铁律 32).
        """
        results: list[dict[str, Any]] = []
        for alert in alerts:
            if not alert.triggered:
                continue
            results.append(self._push_via_channel_chain(alert, conn=conn))
        return results

    @staticmethod
    def _push_via_channel_chain(alert: MetaAlert, *, conn: Any) -> dict[str, Any]:
        """V3 §13.3 元告警 channel fallback chain — 主 DingTalk → 备 email → 极端 log-P0.

        - 主 DingTalk (send_with_dedup): terminal when delivered OR by-design-skip
          (dedup_suppressed / alerts_disabled — paper-mode audit-only). httpx.HTTPError
          (DingTalk unreachable) OR reason=no_webhook (config gap, can't deliver) →
          escalate to email.
        - 备 email (send_email_alert): terminal when sent. Not-delivered (disabled /
          no_smtp_config) OR send failure → escalate to log-P0.
        - 极端 log-P0: last-resort logger.critical — 元告警 never silently vanishes
          (V3 §13.3 "DingTalk 不可用 → 系统弹窗 + log P0"; 系统弹窗 N/A on headless
          server → log P0 is the realized last resort).

        psycopg2.Error from send_with_dedup's alert_dedup write is NOT caught —
        propagates to the Beat task (different failure class than channel-down).
        """
        import psycopg2  # noqa: PLC0415

        from app.services.dingtalk_alert import send_with_dedup  # noqa: PLC0415

        rule = alert.rule_id.value
        severity = alert.severity.value  # MetaAlertSeverity "p0"/"p1"
        title = f"元告警 {rule}"

        # Step 1: 主 DingTalk
        try:
            dt = send_with_dedup(
                dedup_key=f"meta_alert:{rule}",
                severity=severity,
                source="meta_monitor",
                title=title,
                body=alert.detail,
                conn=conn,
            )
            if dt.get("sent") or dt.get("reason") in ("dedup_suppressed", "alerts_disabled"):
                logger.warning(
                    "[meta-monitor] 元告警 rule=%s severity=%s channel=dingtalk reason=%s",
                    rule,
                    severity,
                    dt.get("reason"),
                )
                return {"channel": "dingtalk", "rule_id": rule, **dt}
            # reason == no_webhook → DingTalk configured-but-cannot-deliver, escalate
            logger.warning(
                "[meta-monitor] DingTalk channel cannot deliver rule=%s reason=%s "
                "— escalate to email",
                rule,
                dt.get("reason"),
            )
        except psycopg2.Error:
            # alert_dedup write failure = borked transaction, different failure class
            # than channel-down — propagate for Beat task rollback + Celery retry.
            raise
        except Exception as e:  # noqa: BLE001 — channel chain resilience: any non-DB
            # DingTalk-side failure (httpx.HTTPError / future validation error /
            # unexpected) must still fall through to email so the 元告警 never silently
            # vanishes (sustained "never vanish" invariant, symmetric with email step).
            logger.warning(
                "[meta-monitor] DingTalk channel failed rule=%s: %s — escalate to email",
                rule,
                e,
            )

        # Step 2: 备 email
        from app.services.email_alert import send_email_alert  # noqa: PLC0415

        try:
            em = send_email_alert(
                subject=f"[元告警] {title}", body=alert.detail, source="meta_monitor"
            )
            if em.get("sent"):
                logger.warning(
                    "[meta-monitor] 元告警 rule=%s severity=%s channel=email (DingTalk escalated)",
                    rule,
                    severity,
                )
                return {"channel": "email", "rule_id": rule, **em}
            logger.warning(
                "[meta-monitor] email channel did not deliver rule=%s reason=%s "
                "— escalate to log-P0",
                rule,
                em.get("reason"),
            )
        except Exception as e:  # noqa: BLE001 — channel chain must stay resilient; any
            # email-side failure (smtplib.SMTPException / OSError / unexpected) must still
            # fall through to log-P0 so the 元告警 never silently vanishes.
            logger.warning(
                "[meta-monitor] email channel failed rule=%s: %s — escalate to log-P0",
                rule,
                e,
            )

        # Step 3: 极端 log-P0 (last resort — 元告警 never silently vanishes)
        logger.critical(
            "[meta-monitor] P0 元告警 — ALL CHANNELS FAILED rule=%s severity=%s detail=%s",
            rule,
            severity,
            alert.detail,
        )
        return {
            "channel": "log_p0",
            "rule_id": rule,
            "sent": False,
            "reason": "all_channels_failed",
        }

    # ── Collectors — 6 real (LiteLLM / STAGED / DingTalk / News / PG / Crisis)
    #    + 1 no-signal (L1) ──
    # HC-1b3 wired DingTalk-push-status (alert_dedup.last_push_ok) + News per-run
    # stats (Redis qm:news:last_run_stats). HC-2b3 wired PG health (pg_stat_activity)
    # + 千股跌停极端 regime (index_daily + klines_daily). L1-heartbeat stays
    # no-signal — DEFERRED per HC-1b3 Finding (no production XtQuantTickSubscriber
    # runner exists to instrument; instrumenting it would never fire — see
    # _collect_l1_heartbeat).

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
        """No-signal collector — DEFERRED per HC-1b3 Finding (NOT just "not yet wired").

        HC-1b3 precondition 核 真值: XtQuantTickSubscriber + RealtimeRiskEngine are
        instantiated ONLY in tests + the replay runner — there is NO production
        runner wiring the realtime subscriber into a live tick flow (S5/Tier A
        built the components; production wiring deferred, consistent with
        paper-mode 红线 0 持仓 / LIVE_TRADING_DISABLED=true). Instrumenting a
        heartbeat now would never fire (no production subscriber). last_tick_at=None
        → PURE rule not triggered + detail "no heartbeat data" — this is the
        *correct* state until the realtime engine gets production-wired (likely
        Plan v0.4 cutover scope — touches live xtquant). See HC-1b3 PR / ADR-073.
        """
        logger.debug(
            "[meta-monitor] L1 heartbeat collector = no-signal (DEFERRED — no prod "
            "realtime subscriber, HC-1b3 Finding)"
        )
        return L1HeartbeatSnapshot(last_tick_at=None, now=now)

    @staticmethod
    def _collect_dingtalk(conn: Any, now: datetime) -> DingTalkPushSnapshot:
        """Real collector (HC-1b3) — alert_dedup.last_push_ok most-recent real POST.

        send_with_dedup (dingtalk_alert.py) records every real DingTalk POST outcome
        into alert_dedup.last_push_ok / last_push_status (HC-1b3 DDL +2 cols). Rows
        with last_push_ok IS NULL never had a real POST (alerts_disabled / no_webhook
        / dedup_suppressed) — excluded. Most recent real-POST row (by last_fired_at,
        which on a real-fire row ≈ the POST time) is the operative DingTalk health
        signal. No real-POST row at all → last_push_attempted=False → not triggered.
        """
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT last_push_ok, last_push_status
                FROM alert_dedup
                WHERE last_push_ok IS NOT NULL
                ORDER BY last_fired_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return DingTalkPushSnapshot(
                last_push_attempted=False,
                last_push_ok=False,
                last_push_status="",
                now=now,
            )
        return DingTalkPushSnapshot(
            last_push_attempted=True,
            last_push_ok=bool(row[0]),
            last_push_status=str(row[1]) if row[1] else "",
            now=now,
        )

    def _collect_news(self, now: datetime) -> NewsSourceWindowSnapshot:
        """Real collector (HC-1b3) — Redis qm:news:last_run_stats from News-ingest Beat.

        The News-ingest Beat task (news_ingest_5_sources) persists each DataPipeline
        run's per-source aggregate to Redis after `ingest()`. This collector reads
        the most recent run: `success_count == 0` → all sources failed/timed-out →
        timed_out_sources = total_sources (rule triggers). Any success → not triggered.

        Cadence-mismatch Finding (HC-1b3): V3 §13.3 says "5min", but the News Beat
        runs every 4h (`3,7,11,15,19,23`) — the 5min window does NOT apply to a
        4h-cadence pipeline. The operative signal is "the last news run got 0
        successes", not "all sources timed out in the last 5min". window_seconds is
        passed nominal (NEWS_SOURCE_TIMEOUT_WINDOW_S, detail-string only). Redis key
        absent (expired / Beat never ran) → no-signal (timed_out_sources=0); a
        completely-dead News Beat is a separate "Beat health" concern, not this rule.

        Fail-soft on Redis/JSON error → no-signal (反 Redis 故障 crash the whole
        meta_monitor tick; the other 3 real collectors still run).
        """
        total = _NEWS_SOURCE_COUNT_FALLBACK
        timed_out = 0
        try:
            raw = self._get_redis().get(NEWS_RUN_STATS_REDIS_KEY)
            if raw is not None:
                stats = json.loads(raw)
                total = int(stats.get("total_sources", _NEWS_SOURCE_COUNT_FALLBACK))
                success = int(stats.get("success_count", 0))
                timed_out = total if success == 0 else 0
        except Exception as e:  # noqa: BLE001 — fail-soft, News collector 旁路 (反
            # Redis/JSON error crash 整个 meta_monitor tick; 其余 3 real collector 仍跑)
            logger.warning(
                "[meta-monitor] News collector Redis read failed (fail-soft, no-signal): %s",
                e,
            )
            total, timed_out = _NEWS_SOURCE_COUNT_FALLBACK, 0
        return NewsSourceWindowSnapshot(
            total_sources=total,
            timed_out_sources=timed_out,
            window_seconds=NEWS_SOURCE_TIMEOUT_WINDOW_S,
            now=now,
        )

    @staticmethod
    def _collect_pg_health(conn: Any, now: datetime) -> PGHealthSnapshot:
        """Real collector (HC-2b3 G3) — pg_stat_activity idle-in-transaction + total.

        V3 §14 mode 3 检测: idle-in-transaction 连接堆积 = connection pool 耗尽 /
        lock 堆积前兆.
        - `COUNT(*) FILTER (WHERE state = 'idle in transaction')` = idle-in-tx 计数.
          state IS NULL (后台 worker / 本查询自身连接) 被 FILTER 隐式排除 (NULL =
          'idle in transaction' → NULL → falsy), 无需显式 IS NOT NULL guard.
        - `COUNT(*) FILTER (WHERE backend_type = 'client backend')` = client 连接数.
          反 background worker (autovacuum / walsender / bgwriter / checkpointer /
          本查询连接) 虚高 total_connections (reviewer LOW — db-reviewer post-merge).

        Instance-wide (NOT filtered by current_database) — `max_connections` 是
        cluster 级资源, 其他 database 的 idle-in-tx 连接同样占用全局 slot 并可触发
        "PG OOM / lock"; 且 V3 §14 mode 3 spec "pg_stat_activity > 50 idle in tx"
        无 per-database 限定. idle-in-transaction 只由真实 client 事务产生 (后台 /
        replication 连接不会进此状态), 故 instance-wide 计数即真实信号.

        psycopg2.Error propagate (fail-loud 沿用 _collect_litellm / _collect_staged
        体例 — 铁律 33; PG query 失败 caller 决定 rollback). 注: PG 自身故障时本
        collector 可能 raise — 这正是 V3 §14 mode 3 "PG OOM / lock" 的失败信号本体,
        propagate 让 Beat task fail-loud 比 silent no-signal 更符合 P0 语义.
        """
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,
                    COUNT(*) FILTER (WHERE backend_type = 'client backend') AS total
                FROM pg_stat_activity
                """
            )
            row = cur.fetchone()
        finally:
            cur.close()
        idle_in_tx = int(row[0]) if row and row[0] is not None else 0
        total = int(row[1]) if row and row[1] is not None else 0
        return PGHealthSnapshot(
            idle_in_transaction=idle_in_tx,
            total_connections=total,
            now=now,
        )

    @staticmethod
    def _collect_market_crisis(conn: Any, now: datetime) -> MarketCrisisSnapshot:
        """Real collector (HC-2b3 G4) — index_daily + klines_daily via market_indicators_query.

        V3 §14 mode 9 检测: 大盘 -7% (index_daily 000300.SH 最新交易日 pct_change)
        OR 跌停家数 > 500 (klines_daily 最新交易日 pct_change <= -9.9). 共用
        market_indicators_query helper (铁律 34 — 与 dynamic_threshold_tasks.
        _build_market_indicators 单源, 反 limit_down_count / index_return 口径漂移).

        psycopg2.Error propagate (fail-loud 沿用 collector 体例 — 铁律 33).
        无数据 (index_daily 无 000300.SH row / klines_daily 空) → None leg
        (无信号, 非 error — PURE rule 优雅处理).
        """
        return MarketCrisisSnapshot(
            index_return=query_index_return(conn),
            limit_down_count=query_limit_down_count(conn),
            now=now,
        )


__all__ = ["MetaMonitorService"]
