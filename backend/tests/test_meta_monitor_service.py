"""Unit tests for MetaMonitorService — V3 §13.3 + §14 元告警 Application orchestration (HC-1b + HC-2b3).

覆盖:
  - collect_and_evaluate: 7 polled rules always evaluated; healthy system → 0 triggered
  - _collect_litellm: real query → LiteLLMCallWindowSnapshot (window param + counts)
  - _collect_staged: real query → StagedPlanWindowSnapshot (plan_id str, pending_since)
  - _collect_dingtalk (HC-1b3): real alert_dedup.last_push_ok query — failed/ok/no-row
  - _collect_news (HC-1b3): real Redis qm:news:last_run_stats — 0-success/success/
    absent/Redis-error fail-soft
  - _collect_pg_health (HC-2b3 G3): real pg_stat_activity query — healthy/idle-堆积/null-row
  - _collect_market_crisis (HC-2b3 G4): real index_daily + klines_daily query — crisis/calm/no-data
  - _collect_l1_heartbeat (IC-1c WU-3, 2026-05-15): real Redis read of
    `risk:l1_heartbeat` written by realtime_risk_engine_service.py (WU-2 runner) —
    fresh/stale/absent/malformed/redis-down fail-soft paths covered
  - LiteLLM failure / STAGED overdue / PG idle 堆积 / Crisis regime → respective rule triggered
  - push_triggered + _push_via_channel_chain (V3 §13.3 channel fallback chain):
    主 DingTalk terminal (sent/dedup_suppressed/alerts_disabled) → no escalation;
    no_webhook / httpx.HTTPError → escalate email; email not-delivered/raises →
    escalate log-P0; non-httpx error (psycopg2.Error class) propagates
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
import psycopg2
import pytest

from backend.app.services.risk.meta_monitor_service import MetaMonitorService
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    LITELLM_FAILURE_RATE_WINDOW_S,
    STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S,
    MetaAlert,
    MetaAlertRuleId,
    MetaAlertSeverity,
)
from backend.qm_platform.risk.realtime.runtime_keys import CACHE_L1_HEARTBEAT

_NOW = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)


# ── Mock conn + Redis ──


class _MockCursor:
    def __init__(self, conn: _MockConn) -> None:
        self._conn = conn
        self._last_sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._last_sql = sql
        self._conn.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if "llm_call_log" in self._last_sql:
            return self._conn.litellm_row
        if "alert_dedup" in self._last_sql:
            return self._conn.dingtalk_row
        if "pg_stat_activity" in self._last_sql:
            return self._conn.pg_health_row
        if "index_daily" in self._last_sql:
            return self._conn.index_return_row
        if "klines_daily" in self._last_sql:
            return self._conn.limit_down_row
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "execution_plans" in self._last_sql:
            return self._conn.staged_rows
        return []

    def close(self) -> None:
        pass

    # context-manager support for `with conn.cursor() as cur:` (market_indicators_query
    # uses plain cur.close() in finally; this is harmless extra surface for safety).
    def __enter__(self) -> _MockCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _MockConn:
    """Mock conn: litellm_row (llm_call_log) + staged_rows (execution_plans) +
    dingtalk_row (alert_dedup) + pg_health_row (pg_stat_activity) +
    index_return_row (index_daily) + limit_down_row (klines_daily)."""

    def __init__(
        self,
        *,
        litellm_row: tuple[int, int] = (0, 0),
        staged_rows: list[tuple[Any, ...]] | None = None,
        dingtalk_row: tuple[Any, ...] | None = None,
        pg_health_row: tuple[int, int] | None = (0, 0),
        index_return_row: tuple[Any, ...] | None = None,
        limit_down_row: tuple[Any, ...] | None = None,
    ) -> None:
        self.litellm_row = litellm_row
        self.staged_rows = staged_rows or []
        self.dingtalk_row = dingtalk_row  # None = no real-POST row → not triggered
        # pg_health_row: (idle_in_tx, total); default (0,0) = healthy PG
        self.pg_health_row = pg_health_row
        # index_return_row: (pct_change,) in % units; None = no index_daily row → no signal
        self.index_return_row = index_return_row
        # limit_down_row: (count,); None = no klines_daily data → no signal
        self.limit_down_row = limit_down_row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _MockCursor:
        return _MockCursor(self)


class _MockRedis:
    """Mock Redis — .get() returns the configured news-stats JSON string or None.

    raise_on_get=True simulates a Redis failure (fail-soft path test).

    WU-3 extension (2026-05-15): also responds to `risk:l1_heartbeat` so the
    L1 heartbeat collector tests can inject fresh / stale / absent / malformed
    timestamps via the same mock surface.
    """

    def __init__(
        self,
        *,
        news_stats_json: str | None = None,
        l1_heartbeat: str | None = None,
        raise_on_get: bool = False,
    ) -> None:
        self._news_stats_json = news_stats_json
        self._l1_heartbeat = l1_heartbeat
        self._raise_on_get = raise_on_get

    def get(self, key: str) -> str | None:
        if self._raise_on_get:
            raise ConnectionError("simulated Redis failure")
        if key == "qm:news:last_run_stats":
            return self._news_stats_json
        if key == CACHE_L1_HEARTBEAT:
            # WU-3 SSOT (python-reviewer P2 fix): reference the shared constant
            # rather than inlining the string — silent-drift guard.
            return self._l1_heartbeat
        return None


def _make_svc(redis: _MockRedis | None = None) -> MetaMonitorService:
    """MetaMonitorService with an injected mock Redis (default empty → News no-signal)."""
    return MetaMonitorService(redis_client=redis if redis is not None else _MockRedis())


def _by_rule(alerts: list[MetaAlert], rule_id: MetaAlertRuleId) -> MetaAlert:
    return next(a for a in alerts if a.rule_id is rule_id)


# ── collect_and_evaluate ──


def test_collect_and_evaluate_returns_7_alerts_one_per_rule() -> None:
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    assert len(alerts) == 7
    # collect_and_evaluate runs the 7 POLLED rules; RISK_REFLECTOR_FAILED and
    # BROKER_PLAN_STUCK are event-emitted (HC-2b G5 / HC-2b2 G7 — not polled, no
    # evaluate_* fn) so correctly absent.
    assert {a.rule_id for a in alerts} == {
        MetaAlertRuleId.L1_HEARTBEAT_STALE,
        MetaAlertRuleId.LITELLM_FAILURE_RATE,
        MetaAlertRuleId.DINGTALK_PUSH_FAILED,
        MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT,
        MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE,
        MetaAlertRuleId.PG_POOL_EXHAUSTED,
        MetaAlertRuleId.MARKET_CRISIS_REGIME,
    }


def test_collect_and_evaluate_healthy_system_zero_triggered() -> None:
    # all signals empty/healthy (0 LiteLLM calls, 0 STAGED, no DingTalk push row,
    # no News Redis stats, L1 no-signal) → all 5 rules not triggered
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(litellm_row=(0, 0), staged_rows=[]), now=_NOW)
    assert all(not a.triggered for a in alerts)


def test_collect_and_evaluate_litellm_failure_triggers_rule() -> None:
    # 10 calls, 8 failed = 80% > 50% threshold
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(litellm_row=(10, 8)), now=_NOW)
    litellm_alert = _by_rule(alerts, MetaAlertRuleId.LITELLM_FAILURE_RATE)
    assert litellm_alert.triggered is True
    assert litellm_alert.severity is MetaAlertSeverity.P0


def test_collect_and_evaluate_staged_overdue_triggers_rule() -> None:
    overdue_created = _NOW - timedelta(seconds=STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 60)
    rows = [("uuid-aaaa-1111", "PENDING_CONFIRM", overdue_created)]
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(staged_rows=rows), now=_NOW)
    staged_alert = _by_rule(alerts, MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE)
    assert staged_alert.triggered is True
    assert "uuid-aaaa-1111" in staged_alert.detail


def test_collect_and_evaluate_l1_heartbeat_absent_key_no_signal() -> None:
    """IC-1c WU-3 (2026-05-15): replaces previous "always-no-signal" test.

    L1 heartbeat key absent (TTL expired post-crash beyond 3600s, OR service
    never started) → last_tick_at=None → rule emits "no heartbeat data"
    (not triggered). This is the explicit "engine not started" silent state
    per evaluate_l1_heartbeat docstring.
    """
    svc = _make_svc(_MockRedis(l1_heartbeat=None))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "no heartbeat data" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_fresh_healthy() -> None:
    """Fresh heartbeat (< 300s old) → rule not triggered, detail "healthy"."""
    fresh_ts = (_NOW - timedelta(seconds=10)).isoformat()
    svc = _make_svc(_MockRedis(l1_heartbeat=fresh_ts))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "healthy" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_stale_triggers_p0() -> None:
    """Stale heartbeat (> 300s old) → P0 rule fires — closes ADR-073 D3 dormant alert.

    WU-3 sediment: post-IC-1c WU-2 runner crash, heartbeat key persists with
    last_tick_at = crash_time (TTL 3600s), meta_monitor reads timestamp,
    rule fires P0 because (now - last_tick_at) > 300s threshold.
    """
    stale_ts = (_NOW - timedelta(seconds=400)).isoformat()  # 400s > 300s threshold
    svc = _make_svc(_MockRedis(l1_heartbeat=stale_ts))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is True
    assert l1.severity is MetaAlertSeverity.P0
    assert "stale" in l1.detail.lower() or "断连" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_malformed_iso_fails_soft() -> None:
    """Malformed ISO timestamp → fail-soft (no-signal), no exception propagation.

    WU-3 Finding #11: Redis returns garbage / corrupted value → collector
    logs warning + returns last_tick_at=None → rule "no heartbeat data".
    Sustained _collect_news fail-soft 体例.

    python-reviewer P2 fix: explicit detail assertion (was missing) — parity
    with naive/future tests; regression guard if fail-soft path changes.
    """
    svc = _make_svc(_MockRedis(l1_heartbeat="not-a-timestamp"))
    # Must not raise
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "no heartbeat data" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_z_suffix_parsed_correctly() -> None:
    """ISO timestamp with `Z` suffix (UTC shorthand) → parsed as tz-aware.

    python-reviewer P2 fix (2026-05-15): the `_collect_l1_heartbeat` docstring
    documents Python 3.11+ "Z" suffix support, but no test exercised the path.
    Future producers (Go sidecar / monitoring exporter writing to the same
    Redis key) may emit "Z" — this test pins the contract.
    """
    z_ts = "2026-05-14T09:59:50Z"  # 10s before _NOW = 10:00:00 → healthy
    svc = _make_svc(_MockRedis(l1_heartbeat=z_ts))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "healthy" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_naive_datetime_fails_soft() -> None:
    """ISO timestamp without tz → fail-soft (铁律 41 violation caught, no-signal)."""
    # Naive ISO (no timezone suffix)
    naive_ts = datetime(2026, 5, 14, 9, 55, 0).isoformat()
    svc = _make_svc(_MockRedis(l1_heartbeat=naive_ts))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False


def test_collect_and_evaluate_l1_heartbeat_future_tick_fails_soft() -> None:
    """Future last_tick_at (clock skew between hosts) → fail-soft (no-signal).

    Avoids cascading clock-skew into a P0 L1 alert — Redis return is
    treated as garbage and the rule silently no-signals.
    """
    future_ts = (_NOW + timedelta(seconds=60)).isoformat()
    svc = _make_svc(_MockRedis(l1_heartbeat=future_ts))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "no heartbeat data" in l1.detail


def test_collect_and_evaluate_l1_heartbeat_redis_failure_fails_soft() -> None:
    """Redis connection error → fail-soft (no-signal), other collectors still run.

    WU-3 Finding #11 sediment: Redis-down already surfaces via PG-health /
    DingTalk-push collectors; cascading to a P0 L1 alert would be misleading
    double-fire. Sustained _collect_news fail-soft 体例.
    """
    svc = _make_svc(_MockRedis(raise_on_get=True))
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    # 7 alerts still returned despite Redis error in L1 + News collectors
    assert len(alerts) == 7
    l1 = _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE)
    assert l1.triggered is False
    assert "no heartbeat data" in l1.detail


def test_collect_and_evaluate_dingtalk_and_news_real_triggers() -> None:
    # HC-1b3: DingTalk-status + News are real collectors now — verify a failed
    # DingTalk push row + a 0-success News run both surface as triggered.
    import json as _json

    svc = _make_svc(
        _MockRedis(news_stats_json=_json.dumps({"success_count": 0, "total_sources": 6}))
    )
    conn = _MockConn(dingtalk_row=(False, "HTTPError"))
    alerts = svc.collect_and_evaluate(conn, now=_NOW)
    assert _by_rule(alerts, MetaAlertRuleId.DINGTALK_PUSH_FAILED).triggered is True
    assert _by_rule(alerts, MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT).triggered is True


def test_collect_and_evaluate_pg_idle_buildup_triggers_rule() -> None:
    # HC-2b3 G3: pg_stat_activity 60 idle-in-tx > 50 threshold → PG_POOL_EXHAUSTED triggers
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(pg_health_row=(60, 90)), now=_NOW)
    pg_alert = _by_rule(alerts, MetaAlertRuleId.PG_POOL_EXHAUSTED)
    assert pg_alert.triggered is True
    assert pg_alert.severity is MetaAlertSeverity.P0


def test_collect_and_evaluate_market_crisis_triggers_rule() -> None:
    # HC-2b3 G4: index_daily -8% (pct_change -8.0 → -0.08) → MARKET_CRISIS_REGIME triggers
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(index_return_row=(-8.0,)), now=_NOW)
    crisis_alert = _by_rule(alerts, MetaAlertRuleId.MARKET_CRISIS_REGIME)
    assert crisis_alert.triggered is True
    assert crisis_alert.severity is MetaAlertSeverity.P0


# ── _collect_litellm ──


def test_collect_litellm_window_param_and_counts() -> None:
    conn = _MockConn(litellm_row=(20, 3))
    snapshot = MetaMonitorService._collect_litellm(conn, _NOW)
    assert snapshot.total_calls == 20
    assert snapshot.failed_calls == 3
    assert snapshot.window_seconds == LITELLM_FAILURE_RATE_WINDOW_S
    assert snapshot.now == _NOW
    # window is bounded both ends: [now - WINDOW, now]
    _sql, params = conn.executed[0]
    assert params == (_NOW - timedelta(seconds=LITELLM_FAILURE_RATE_WINDOW_S), _NOW)


def test_collect_litellm_null_row_defaults_zero() -> None:
    # fetchone returns None-ish — defensive default to 0/0
    conn = _MockConn(litellm_row=(None, None))  # type: ignore[arg-type]
    snapshot = MetaMonitorService._collect_litellm(conn, _NOW)
    assert snapshot.total_calls == 0
    assert snapshot.failed_calls == 0


# ── _collect_staged ──


def test_collect_staged_builds_snapshot_from_rows() -> None:
    c1 = _NOW - timedelta(seconds=100)
    c2 = _NOW - timedelta(seconds=5000)
    rows = [
        ("uuid-1", "PENDING_CONFIRM", c1),
        ("uuid-2", "PENDING_CONFIRM", c2),
    ]
    snapshot = MetaMonitorService._collect_staged(_MockConn(staged_rows=rows), _NOW)
    assert len(snapshot.plans) == 2
    assert snapshot.plans[0].plan_id == "uuid-1"
    assert isinstance(snapshot.plans[0].plan_id, str)
    assert snapshot.plans[0].pending_since == c1
    assert snapshot.plans[1].plan_id == "uuid-2"


def test_collect_staged_empty_rows() -> None:
    snapshot = MetaMonitorService._collect_staged(_MockConn(staged_rows=[]), _NOW)
    assert snapshot.plans == ()


# ── _collect_dingtalk (HC-1b3 — real alert_dedup.last_push_ok query) ──


def test_collect_dingtalk_no_row_not_attempted() -> None:
    # no alert_dedup row with last_push_ok IS NOT NULL → last_push_attempted=False
    snapshot = MetaMonitorService._collect_dingtalk(_MockConn(dingtalk_row=None), _NOW)
    assert snapshot.last_push_attempted is False
    assert snapshot.now == _NOW


def test_collect_dingtalk_last_push_ok() -> None:
    snapshot = MetaMonitorService._collect_dingtalk(_MockConn(dingtalk_row=(True, "200")), _NOW)
    assert snapshot.last_push_attempted is True
    assert snapshot.last_push_ok is True
    assert snapshot.last_push_status == "200"


def test_collect_dingtalk_last_push_failed() -> None:
    snapshot = MetaMonitorService._collect_dingtalk(
        _MockConn(dingtalk_row=(False, "ConnectTimeout")), _NOW
    )
    assert snapshot.last_push_attempted is True
    assert snapshot.last_push_ok is False
    assert snapshot.last_push_status == "ConnectTimeout"


# ── _collect_news (HC-1b3 — real Redis qm:news:last_run_stats read) ──


def test_collect_news_zero_success_triggers() -> None:
    import json as _json

    svc = _make_svc(
        _MockRedis(news_stats_json=_json.dumps({"success_count": 0, "total_sources": 6}))
    )
    snapshot = svc._collect_news(_NOW)
    # success_count == 0 → all sources failed → timed_out == total → rule triggers
    assert snapshot.total_sources == 6
    assert snapshot.timed_out_sources == 6


def test_collect_news_some_success_not_triggered() -> None:
    import json as _json

    svc = _make_svc(
        _MockRedis(news_stats_json=_json.dumps({"success_count": 3, "total_sources": 6}))
    )
    snapshot = svc._collect_news(_NOW)
    assert snapshot.timed_out_sources == 0  # any success → not all-timeout


def test_collect_news_key_absent_no_signal() -> None:
    # Redis key absent (expired / Beat never ran) → no-signal (timed_out=0)
    svc = _make_svc(_MockRedis(news_stats_json=None))
    snapshot = svc._collect_news(_NOW)
    assert snapshot.timed_out_sources == 0
    assert snapshot.total_sources >= 1  # fallback count, valid for the rule contract


def test_collect_news_redis_error_fail_soft() -> None:
    # Redis failure → fail-soft no-signal (反 crash the whole meta_monitor tick)
    svc = _make_svc(_MockRedis(raise_on_get=True))
    snapshot = svc._collect_news(_NOW)
    assert snapshot.timed_out_sources == 0


# ── _collect_pg_health (HC-2b3 G3 — real pg_stat_activity query) ──


def test_collect_pg_health_healthy() -> None:
    snapshot = MetaMonitorService._collect_pg_health(_MockConn(pg_health_row=(2, 8)), _NOW)
    assert snapshot.idle_in_transaction == 2
    assert snapshot.total_connections == 8
    assert snapshot.now == _NOW


def test_collect_pg_health_idle_buildup() -> None:
    snapshot = MetaMonitorService._collect_pg_health(_MockConn(pg_health_row=(75, 100)), _NOW)
    assert snapshot.idle_in_transaction == 75
    assert snapshot.total_connections == 100


def test_collect_pg_health_null_row_defaults_zero() -> None:
    # fetchone returns None → defensive default 0/0 (healthy)
    snapshot = MetaMonitorService._collect_pg_health(_MockConn(pg_health_row=None), _NOW)
    assert snapshot.idle_in_transaction == 0
    assert snapshot.total_connections == 0


def test_collect_pg_health_partial_none_tuple_zero_idle_defaults_zero() -> None:
    # defensive: (0, None) partial-None tuple — COUNT(*) FILTER never returns NULL
    # in PG, but the collector guards each column → None total defaults to 0.
    # idle=0 <= total=0 holds → valid snapshot.
    conn = _MockConn(pg_health_row=(0, None))  # type: ignore[arg-type]
    snapshot = MetaMonitorService._collect_pg_health(conn, _NOW)
    assert snapshot.idle_in_transaction == 0
    assert snapshot.total_connections == 0


def test_collect_pg_health_contradictory_partial_none_fails_loud() -> None:
    # defensive edge: (3, None) → idle=3, total defaults to 0 → idle > total
    # contradictory → PGHealthSnapshot.__post_init__ fail-loud MetaAlertError
    # (铁律 33 — contradictory data is NOT silently coerced). This tuple shape
    # is impossible from the real SQL (COUNT(*) FILTER never NULLs), but the
    # fail-loud path is the correct response if it ever occurred.
    from backend.qm_platform.risk.metrics.meta_alert_interface import MetaAlertError

    conn = _MockConn(pg_health_row=(3, None))  # type: ignore[arg-type]
    with pytest.raises(MetaAlertError, match="cannot exceed"):
        MetaMonitorService._collect_pg_health(conn, _NOW)


# ── _collect_market_crisis (HC-2b3 G4 — real index_daily + klines_daily query) ──


def test_collect_market_crisis_no_data_both_none() -> None:
    # no index_daily / klines_daily rows → both legs None → snapshot all-None
    snapshot = MetaMonitorService._collect_market_crisis(_MockConn(), _NOW)
    assert snapshot.index_return is None
    assert snapshot.limit_down_count is None
    assert snapshot.now == _NOW


def test_collect_market_crisis_index_return_converted_to_fraction() -> None:
    # index_daily.pct_change -7.5 (% units) → index_return -0.075 (fraction)
    snapshot = MetaMonitorService._collect_market_crisis(_MockConn(index_return_row=(-7.5,)), _NOW)
    assert snapshot.index_return == pytest.approx(-0.075)


def test_collect_market_crisis_limit_down_count() -> None:
    snapshot = MetaMonitorService._collect_market_crisis(_MockConn(limit_down_row=(623,)), _NOW)
    assert snapshot.limit_down_count == 623


def test_collect_market_crisis_both_legs_populated() -> None:
    snapshot = MetaMonitorService._collect_market_crisis(
        _MockConn(index_return_row=(-8.2,), limit_down_row=(710,)), _NOW
    )
    assert snapshot.index_return == pytest.approx(-0.082)
    assert snapshot.limit_down_count == 710


# ── push_triggered / _push_via_channel_chain (V3 §13.3 channel fallback chain) ──


def _alert(
    rule_id: MetaAlertRuleId = MetaAlertRuleId.LITELLM_FAILURE_RATE,
    *,
    severity: MetaAlertSeverity = MetaAlertSeverity.P0,
    triggered: bool = True,
) -> MetaAlert:
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=f"synthetic {rule_id.value}",
        observed_at=_NOW,
    )


def test_push_triggered_only_triggered_filtered() -> None:
    svc = _make_svc()
    alerts = [_alert(triggered=True), _alert(MetaAlertRuleId.L1_HEARTBEAT_STALE, triggered=False)]
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        mock_send.return_value = {"sent": False, "reason": "alerts_disabled"}
        results = svc.push_triggered(alerts, conn=_MockConn())
    assert len(results) == 1  # only the triggered one
    assert mock_send.call_count == 1


def test_push_triggered_zero_triggered_empty_list() -> None:
    svc = _make_svc()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)  # healthy → 0 triggered
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        results = svc.push_triggered(alerts, conn=_MockConn())
    assert results == []
    assert mock_send.call_count == 0


def test_chain_dingtalk_terminal_alerts_disabled_no_email() -> None:
    # alerts_disabled (paper-mode audit-only) is a by-design terminal — NOT escalated
    svc = _make_svc()
    conn = _MockConn()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.return_value = {"sent": False, "reason": "alerts_disabled"}
        results = svc.push_triggered([_alert()], conn=conn)
    assert results[0]["channel"] == "dingtalk"
    assert results[0]["rule_id"] == "litellm_failure_rate"
    mock_email.assert_not_called()
    # send_with_dedup got the right args incl injected conn
    kw = mock_dt.call_args.kwargs
    assert kw["dedup_key"] == "meta_alert:litellm_failure_rate"
    assert kw["severity"] == "p0"
    assert kw["source"] == "meta_monitor"
    assert kw["conn"] is conn


def test_chain_dingtalk_terminal_sent_no_email() -> None:
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.return_value = {"sent": True, "reason": "sent"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "dingtalk"
    mock_email.assert_not_called()


def test_chain_dingtalk_dedup_suppressed_terminal_no_email() -> None:
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.return_value = {"sent": False, "reason": "dedup_suppressed"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "dingtalk"
    mock_email.assert_not_called()


def test_chain_dingtalk_no_webhook_escalates_to_email() -> None:
    # no_webhook = configured-but-cannot-deliver → escalate to email
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.return_value = {"sent": False, "reason": "no_webhook"}
        mock_email.return_value = {"sent": True, "reason": "sent"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "email"
    mock_email.assert_called_once()


def test_chain_dingtalk_httperror_escalates_to_email() -> None:
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.side_effect = httpx.HTTPError("dingtalk unreachable")
        mock_email.return_value = {"sent": True, "reason": "sent"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "email"
    assert results[0]["rule_id"] == "litellm_failure_rate"
    mock_email.assert_called_once()


def test_chain_email_not_delivered_escalates_to_log_p0() -> None:
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.side_effect = httpx.HTTPError("dingtalk unreachable")
        mock_email.return_value = {"sent": False, "reason": "email_alerts_disabled"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "log_p0"
    assert results[0]["sent"] is False
    assert results[0]["reason"] == "all_channels_failed"


def test_chain_email_raises_escalates_to_log_p0() -> None:
    import smtplib

    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.side_effect = httpx.HTTPError("dingtalk unreachable")
        mock_email.side_effect = smtplib.SMTPException("smtp down")
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "log_p0"


def test_chain_dingtalk_psycopg2error_propagates() -> None:
    # psycopg2.Error (alert_dedup write failure) is NOT caught — propagates (borked txn,
    # different failure class than channel-down; Beat task rolls back + Celery retries)
    svc = _make_svc()
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt:
        mock_dt.side_effect = psycopg2.OperationalError("simulated DB failure")
        with pytest.raises(psycopg2.OperationalError, match="simulated DB failure"):
            svc.push_triggered([_alert()], conn=_MockConn())


def test_chain_dingtalk_unexpected_error_escalates_to_email() -> None:
    # non-psycopg2, non-httpx error from send_with_dedup (e.g. future validation error)
    # escalates to email — "元告警 never silently vanishes" invariant (reviewer HIGH fix)
    svc = _make_svc()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.side_effect = ValueError("unexpected validation error")
        mock_email.return_value = {"sent": True, "reason": "sent"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "email"
    mock_email.assert_called_once()


def test_chain_severity_passed_through() -> None:
    svc = _make_svc()
    p1_alert = _alert(MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT, severity=MetaAlertSeverity.P1)
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt:
        mock_dt.return_value = {"sent": False, "reason": "alerts_disabled"}
        svc.push_triggered([p1_alert], conn=_MockConn())
    assert mock_dt.call_args.kwargs["severity"] == "p1"
