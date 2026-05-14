"""Unit tests for MetaMonitorService — V3 §13.3 元告警 Application orchestration (HC-1b).

覆盖:
  - collect_and_evaluate: 5 rules always evaluated; healthy system → 0 triggered
  - _collect_litellm: real query → LiteLLMCallWindowSnapshot (window param + counts)
  - _collect_staged: real query → StagedPlanWindowSnapshot (plan_id str, pending_since)
  - 3 no-signal collectors (L1 / DingTalk / News) → always not triggered
  - LiteLLM failure / STAGED overdue → respective rule triggered
  - push_triggered: only .triggered pushed; send_with_dedup args (dedup_key/severity/
    source/conn); 0 triggered → empty list
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from backend.app.services.risk.meta_monitor_service import MetaMonitorService
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    LITELLM_FAILURE_RATE_WINDOW_S,
    STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S,
    MetaAlert,
    MetaAlertRuleId,
    MetaAlertSeverity,
)

_NOW = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)


# ── Mock conn ──


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
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "execution_plans" in self._last_sql:
            return self._conn.staged_rows
        return []

    def close(self) -> None:
        pass


class _MockConn:
    """Returns staged litellm_row for llm_call_log + staged_rows for execution_plans."""

    def __init__(
        self,
        *,
        litellm_row: tuple[int, int] = (0, 0),
        staged_rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.litellm_row = litellm_row
        self.staged_rows = staged_rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _MockCursor:
        return _MockCursor(self)


def _by_rule(alerts: list[MetaAlert], rule_id: MetaAlertRuleId) -> MetaAlert:
    return next(a for a in alerts if a.rule_id is rule_id)


# ── collect_and_evaluate ──


def test_collect_and_evaluate_returns_5_alerts_one_per_rule() -> None:
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    assert len(alerts) == 5
    assert {a.rule_id for a in alerts} == set(MetaAlertRuleId)


def test_collect_and_evaluate_healthy_system_zero_triggered() -> None:
    # 0 LiteLLM calls, 0 STAGED plans, 3 no-signal collectors → all not triggered
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(litellm_row=(0, 0), staged_rows=[]), now=_NOW)
    assert all(not a.triggered for a in alerts)


def test_collect_and_evaluate_litellm_failure_triggers_rule() -> None:
    # 10 calls, 8 failed = 80% > 50% threshold
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(litellm_row=(10, 8)), now=_NOW)
    litellm_alert = _by_rule(alerts, MetaAlertRuleId.LITELLM_FAILURE_RATE)
    assert litellm_alert.triggered is True
    assert litellm_alert.severity is MetaAlertSeverity.P0


def test_collect_and_evaluate_staged_overdue_triggers_rule() -> None:
    overdue_created = _NOW - timedelta(seconds=STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 60)
    rows = [("uuid-aaaa-1111", "PENDING_CONFIRM", overdue_created)]
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(staged_rows=rows), now=_NOW)
    staged_alert = _by_rule(alerts, MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE)
    assert staged_alert.triggered is True
    assert "uuid-aaaa-1111" in staged_alert.detail


def test_collect_and_evaluate_no_signal_collectors_never_trigger() -> None:
    # L1 heartbeat / DingTalk push / News — HC-1b no-signal collectors, never triggered
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)
    assert _by_rule(alerts, MetaAlertRuleId.L1_HEARTBEAT_STALE).triggered is False
    assert _by_rule(alerts, MetaAlertRuleId.DINGTALK_PUSH_FAILED).triggered is False
    assert _by_rule(alerts, MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT).triggered is False


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


# ── push_triggered ──


def test_push_triggered_only_triggered_pushed() -> None:
    svc = MetaMonitorService()
    # litellm failure (triggered) + healthy rest
    alerts = svc.collect_and_evaluate(_MockConn(litellm_row=(10, 9)), now=_NOW)
    conn = _MockConn()
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        mock_send.return_value = {"sent": False, "reason": "alerts_disabled"}
        results = svc.push_triggered(alerts, conn=conn)
    assert len(results) == 1  # only the 1 triggered litellm alert
    assert mock_send.call_count == 1
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["dedup_key"] == "meta_alert:litellm_failure_rate"
    assert call_kwargs["severity"] == "p0"
    assert call_kwargs["source"] == "meta_monitor"
    assert call_kwargs["conn"] is conn


def test_push_triggered_zero_triggered_empty_list() -> None:
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)  # healthy → 0 triggered
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        results = svc.push_triggered(alerts, conn=_MockConn())
    assert results == []
    assert mock_send.call_count == 0


def test_push_triggered_severity_passed_through() -> None:
    # build a P1 triggered alert (News) — but News is no-signal, so synthesize directly
    svc = MetaMonitorService()
    p1_alert = MetaAlert(
        rule_id=MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT,
        severity=MetaAlertSeverity.P1,
        triggered=True,
        detail="synthetic p1",
        observed_at=_NOW,
    )
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        mock_send.return_value = {"sent": False, "reason": "alerts_disabled"}
        svc.push_triggered([p1_alert], conn=_MockConn())
    assert mock_send.call_args.kwargs["severity"] == "p1"
