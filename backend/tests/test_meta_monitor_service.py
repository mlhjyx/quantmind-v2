"""Unit tests for MetaMonitorService — V3 §13.3 元告警 Application orchestration (HC-1b).

覆盖:
  - collect_and_evaluate: 5 rules always evaluated; healthy system → 0 triggered
  - _collect_litellm: real query → LiteLLMCallWindowSnapshot (window param + counts)
  - _collect_staged: real query → StagedPlanWindowSnapshot (plan_id str, pending_since)
  - 3 no-signal collectors (L1 / DingTalk / News) → always not triggered
  - LiteLLM failure / STAGED overdue → respective rule triggered
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
    svc = MetaMonitorService()
    alerts = [_alert(triggered=True), _alert(MetaAlertRuleId.L1_HEARTBEAT_STALE, triggered=False)]
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        mock_send.return_value = {"sent": False, "reason": "alerts_disabled"}
        results = svc.push_triggered(alerts, conn=_MockConn())
    assert len(results) == 1  # only the triggered one
    assert mock_send.call_count == 1


def test_push_triggered_zero_triggered_empty_list() -> None:
    svc = MetaMonitorService()
    alerts = svc.collect_and_evaluate(_MockConn(), now=_NOW)  # healthy → 0 triggered
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        results = svc.push_triggered(alerts, conn=_MockConn())
    assert results == []
    assert mock_send.call_count == 0


def test_chain_dingtalk_terminal_alerts_disabled_no_email() -> None:
    # alerts_disabled (paper-mode audit-only) is a by-design terminal — NOT escalated
    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
    with (
        patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt,
        patch("app.services.email_alert.send_email_alert") as mock_email,
    ):
        mock_dt.return_value = {"sent": True, "reason": "sent"}
        results = svc.push_triggered([_alert()], conn=_MockConn())
    assert results[0]["channel"] == "dingtalk"
    mock_email.assert_not_called()


def test_chain_dingtalk_dedup_suppressed_terminal_no_email() -> None:
    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
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

    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt:
        mock_dt.side_effect = psycopg2.OperationalError("simulated DB failure")
        with pytest.raises(psycopg2.OperationalError, match="simulated DB failure"):
            svc.push_triggered([_alert()], conn=_MockConn())


def test_chain_dingtalk_unexpected_error_escalates_to_email() -> None:
    # non-psycopg2, non-httpx error from send_with_dedup (e.g. future validation error)
    # escalates to email — "元告警 never silently vanishes" invariant (reviewer HIGH fix)
    svc = MetaMonitorService()
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
    svc = MetaMonitorService()
    p1_alert = _alert(MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT, severity=MetaAlertSeverity.P1)
    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_dt:
        mock_dt.return_value = {"sent": False, "reason": "alerts_disabled"}
        svc.push_triggered([p1_alert], conn=_MockConn())
    assert mock_dt.call_args.kwargs["severity"] == "p1"
