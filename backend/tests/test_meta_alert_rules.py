"""Unit tests for meta_alert_rules + meta_alert_interface — V3 §13.3 + §14 元告警 (HC-1a + HC-2b3).

覆盖 7 PURE polled rule eval + interface 契约校验:
  - evaluate_l1_heartbeat: None / 边界 300s / stale / healthy / future-tick error
  - evaluate_litellm_failure_rate: 0-call / 边界 50% / >50% / <50% / 计数校验 error
  - evaluate_dingtalk_push: not-attempted / ok / failed
  - evaluate_news_sources_timeout: all-timeout / partial / none / 计数校验 error
  - evaluate_staged_overdue: empty / 边界 2100s / overdue / non-PENDING ignored / worst-pick
  - evaluate_pg_health (HC-2b3 G3): 边界 50 / >50 / 0 / 计数校验 error (V3 §14 mode 3)
  - evaluate_market_crisis (HC-2b3 G4): both-None / index 边界 -7% / limit_down 边界 500 /
    both-leg / one-None / 计数校验 error (V3 §14 mode 9)
  - interface: tz-aware enforce (铁律 41) / RULE_SEVERITY SSOT / MetaAlert.to_jsonable
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.qm_platform.risk.metrics.meta_alert_interface import (
    L1_HEARTBEAT_STALE_THRESHOLD_S,
    LITELLM_FAILURE_RATE_THRESHOLD,
    MARKET_CRISIS_INDEX_RETURN_THRESHOLD,
    MARKET_CRISIS_LIMIT_DOWN_THRESHOLD,
    PG_IDLE_IN_TX_THRESHOLD,
    RULE_SEVERITY,
    STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S,
    DingTalkPushSnapshot,
    L1HeartbeatSnapshot,
    LiteLLMCallWindowSnapshot,
    MarketCrisisSnapshot,
    MetaAlert,
    MetaAlertError,
    MetaAlertRuleId,
    MetaAlertSeverity,
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

_NOW = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)


# ── Rule 1: evaluate_l1_heartbeat ──


def test_l1_heartbeat_none_not_triggered() -> None:
    alert = evaluate_l1_heartbeat(L1HeartbeatSnapshot(last_tick_at=None, now=_NOW))
    assert alert.triggered is False
    assert alert.rule_id is MetaAlertRuleId.L1_HEARTBEAT_STALE
    assert alert.severity is MetaAlertSeverity.P0
    assert "no heartbeat data" in alert.detail
    assert alert.observed_at == _NOW


def test_l1_heartbeat_boundary_exactly_threshold_not_triggered() -> None:
    # exactly 300s stale → NOT triggered (rule uses strict >)
    last_tick = _NOW - timedelta(seconds=L1_HEARTBEAT_STALE_THRESHOLD_S)
    alert = evaluate_l1_heartbeat(L1HeartbeatSnapshot(last_tick_at=last_tick, now=_NOW))
    assert alert.triggered is False
    assert "healthy" in alert.detail


def test_l1_heartbeat_just_over_threshold_triggered() -> None:
    last_tick = _NOW - timedelta(seconds=L1_HEARTBEAT_STALE_THRESHOLD_S + 1)
    alert = evaluate_l1_heartbeat(L1HeartbeatSnapshot(last_tick_at=last_tick, now=_NOW))
    assert alert.triggered is True
    assert "stale" in alert.detail
    assert "xtquant" in alert.detail


def test_l1_heartbeat_fresh_not_triggered() -> None:
    last_tick = _NOW - timedelta(seconds=30)
    alert = evaluate_l1_heartbeat(L1HeartbeatSnapshot(last_tick_at=last_tick, now=_NOW))
    assert alert.triggered is False


def test_l1_heartbeat_future_tick_raises() -> None:
    with pytest.raises(MetaAlertError, match="future"):
        L1HeartbeatSnapshot(last_tick_at=_NOW + timedelta(seconds=10), now=_NOW)


def test_l1_heartbeat_naive_now_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        L1HeartbeatSnapshot(last_tick_at=None, now=datetime(2026, 5, 14, 10, 0, 0))


def test_l1_heartbeat_naive_last_tick_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        L1HeartbeatSnapshot(last_tick_at=datetime(2026, 5, 14, 9, 0, 0), now=_NOW)


# ── Rule 2: evaluate_litellm_failure_rate ──


def test_litellm_zero_calls_not_triggered() -> None:
    alert = evaluate_litellm_failure_rate(
        LiteLLMCallWindowSnapshot(total_calls=0, failed_calls=0, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is False
    assert alert.severity is MetaAlertSeverity.P0
    assert "no signal" in alert.detail


def test_litellm_boundary_exactly_50pct_not_triggered() -> None:
    # exactly 50% → NOT triggered (rule uses strict >)
    alert = evaluate_litellm_failure_rate(
        LiteLLMCallWindowSnapshot(total_calls=10, failed_calls=5, window_seconds=300, now=_NOW)
    )
    assert LITELLM_FAILURE_RATE_THRESHOLD == 0.50
    assert alert.triggered is False
    assert "within" in alert.detail


def test_litellm_just_over_50pct_triggered() -> None:
    alert = evaluate_litellm_failure_rate(
        LiteLLMCallWindowSnapshot(total_calls=100, failed_calls=51, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is True
    assert "exceeds" in alert.detail


def test_litellm_under_50pct_not_triggered() -> None:
    alert = evaluate_litellm_failure_rate(
        LiteLLMCallWindowSnapshot(total_calls=100, failed_calls=49, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is False


def test_litellm_all_failed_triggered() -> None:
    alert = evaluate_litellm_failure_rate(
        LiteLLMCallWindowSnapshot(total_calls=8, failed_calls=8, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is True


def test_litellm_failed_exceeds_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="cannot exceed"):
        LiteLLMCallWindowSnapshot(total_calls=5, failed_calls=6, window_seconds=300, now=_NOW)


def test_litellm_negative_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="total_calls"):
        LiteLLMCallWindowSnapshot(total_calls=-1, failed_calls=0, window_seconds=300, now=_NOW)


def test_litellm_negative_failed_raises() -> None:
    with pytest.raises(MetaAlertError, match="failed_calls"):
        LiteLLMCallWindowSnapshot(total_calls=5, failed_calls=-1, window_seconds=300, now=_NOW)


def test_litellm_nonpositive_window_raises() -> None:
    with pytest.raises(MetaAlertError, match="window_seconds"):
        LiteLLMCallWindowSnapshot(total_calls=5, failed_calls=1, window_seconds=0, now=_NOW)


# ── Rule 3: evaluate_dingtalk_push ──


def test_dingtalk_not_attempted_not_triggered() -> None:
    alert = evaluate_dingtalk_push(
        DingTalkPushSnapshot(
            last_push_attempted=False, last_push_ok=False, last_push_status="", now=_NOW
        )
    )
    assert alert.triggered is False
    assert "no DingTalk push attempted" in alert.detail


def test_dingtalk_ok_not_triggered() -> None:
    alert = evaluate_dingtalk_push(
        DingTalkPushSnapshot(
            last_push_attempted=True, last_push_ok=True, last_push_status="200", now=_NOW
        )
    )
    assert alert.triggered is False
    assert "healthy" in alert.detail


def test_dingtalk_failed_triggered() -> None:
    alert = evaluate_dingtalk_push(
        DingTalkPushSnapshot(
            last_push_attempted=True, last_push_ok=False, last_push_status="timeout", now=_NOW
        )
    )
    assert alert.triggered is True
    assert alert.severity is MetaAlertSeverity.P0
    assert "timeout" in alert.detail


def test_dingtalk_contradictory_state_raises() -> None:
    # last_push_ok=True with last_push_attempted=False is logically impossible
    with pytest.raises(MetaAlertError, match="contradictory"):
        DingTalkPushSnapshot(
            last_push_attempted=False, last_push_ok=True, last_push_status="200", now=_NOW
        )


def test_dingtalk_naive_now_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        DingTalkPushSnapshot(
            last_push_attempted=True,
            last_push_ok=True,
            last_push_status="200",
            now=datetime(2026, 5, 14, 10, 0, 0),
        )


# ── Rule 4: evaluate_news_sources_timeout ──


def test_news_all_timeout_triggered_p1() -> None:
    alert = evaluate_news_sources_timeout(
        NewsSourceWindowSnapshot(total_sources=6, timed_out_sources=6, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is True
    # §13.3-vs-§14 reconciliation: News all-timeout is P1 (fail-open degraded)
    assert alert.severity is MetaAlertSeverity.P1
    assert "all 6 News sources" in alert.detail


def test_news_partial_timeout_not_triggered() -> None:
    alert = evaluate_news_sources_timeout(
        NewsSourceWindowSnapshot(total_sources=6, timed_out_sources=5, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is False
    assert "partial" in alert.detail


def test_news_zero_timeout_not_triggered() -> None:
    alert = evaluate_news_sources_timeout(
        NewsSourceWindowSnapshot(total_sources=6, timed_out_sources=0, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is False


def test_news_single_source_all_timeout_triggered() -> None:
    alert = evaluate_news_sources_timeout(
        NewsSourceWindowSnapshot(total_sources=1, timed_out_sources=1, window_seconds=300, now=_NOW)
    )
    assert alert.triggered is True


def test_news_timed_out_exceeds_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="cannot exceed"):
        NewsSourceWindowSnapshot(total_sources=6, timed_out_sources=7, window_seconds=300, now=_NOW)


def test_news_zero_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="total_sources"):
        NewsSourceWindowSnapshot(total_sources=0, timed_out_sources=0, window_seconds=300, now=_NOW)


# ── Rule 5: evaluate_staged_overdue ──


def _staged(plan_id: str, status: str, age_seconds: int) -> StagedPlanState:
    return StagedPlanState(
        plan_id=plan_id,
        status=status,
        pending_since=_NOW - timedelta(seconds=age_seconds),
    )


def test_staged_empty_not_triggered() -> None:
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(), now=_NOW))
    assert alert.triggered is False


def test_staged_boundary_exactly_threshold_not_triggered() -> None:
    # exactly 2100s pending → NOT triggered (rule uses strict >)
    plan = _staged("plan-1", "PENDING_CONFIRM", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S)
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(plan,), now=_NOW))
    assert alert.triggered is False


def test_staged_just_over_threshold_triggered() -> None:
    plan = _staged("plan-42", "PENDING_CONFIRM", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 1)
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(plan,), now=_NOW))
    assert alert.triggered is True
    assert alert.severity is MetaAlertSeverity.P0
    assert "plan_id=plan-42" in alert.detail
    assert "cancel_deadline" in alert.detail


def test_staged_under_threshold_not_triggered() -> None:
    plan = _staged("plan-1", "PENDING_CONFIRM", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S - 1)
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(plan,), now=_NOW))
    assert alert.triggered is False
    assert "none over" in alert.detail


def test_staged_non_pending_status_ignored_even_if_old() -> None:
    # an EXECUTED plan that's very old must NOT trigger — only PENDING_CONFIRM counts
    plan = _staged("plan-1", "EXECUTED", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S * 10)
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(plan,), now=_NOW))
    assert alert.triggered is False


def test_staged_multiple_overdue_picks_worst() -> None:
    plans = (
        _staged("plan-1", "PENDING_CONFIRM", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 100),
        _staged("plan-2", "PENDING_CONFIRM", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 5000),
        _staged("plan-3", "CONFIRMED", STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 9999),
        _staged("plan-4", "PENDING_CONFIRM", 10),
    )
    alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=plans, now=_NOW))
    assert alert.triggered is True
    # 2 overdue (plan-1 + plan-2); plan-3 is CONFIRMED (ignored), plan-4 fresh
    assert "2 STAGED plan(s)" in alert.detail
    assert "plan_id=plan-2" in alert.detail  # worst


def test_staged_naive_pending_since_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        StagedPlanState(
            plan_id="plan-1", status="PENDING_CONFIRM", pending_since=datetime(2026, 5, 14)
        )


# ── Rule 6: evaluate_pg_health (HC-2b3 G3 — V3 §14 mode 3 PG OOM / lock) ──


def test_pg_health_boundary_exactly_threshold_not_triggered() -> None:
    # exactly 50 idle-in-tx → NOT triggered (rule uses strict >)
    alert = evaluate_pg_health(
        PGHealthSnapshot(
            idle_in_transaction=PG_IDLE_IN_TX_THRESHOLD, total_connections=60, now=_NOW
        )
    )
    assert PG_IDLE_IN_TX_THRESHOLD == 50
    assert alert.triggered is False
    assert alert.rule_id is MetaAlertRuleId.PG_POOL_EXHAUSTED
    assert alert.severity is MetaAlertSeverity.P0
    assert "healthy" in alert.detail


def test_pg_health_just_over_threshold_triggered() -> None:
    alert = evaluate_pg_health(
        PGHealthSnapshot(
            idle_in_transaction=PG_IDLE_IN_TX_THRESHOLD + 1, total_connections=80, now=_NOW
        )
    )
    assert alert.triggered is True
    assert alert.severity is MetaAlertSeverity.P0
    assert "connection pool" in alert.detail
    assert alert.observed_at == _NOW


def test_pg_health_zero_idle_not_triggered() -> None:
    alert = evaluate_pg_health(
        PGHealthSnapshot(idle_in_transaction=0, total_connections=5, now=_NOW)
    )
    assert alert.triggered is False


def test_pg_health_many_idle_triggered() -> None:
    alert = evaluate_pg_health(
        PGHealthSnapshot(idle_in_transaction=100, total_connections=120, now=_NOW)
    )
    assert alert.triggered is True
    assert "100" in alert.detail


def test_pg_health_negative_idle_raises() -> None:
    with pytest.raises(MetaAlertError, match="idle_in_transaction"):
        PGHealthSnapshot(idle_in_transaction=-1, total_connections=5, now=_NOW)


def test_pg_health_negative_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="total_connections"):
        PGHealthSnapshot(idle_in_transaction=0, total_connections=-1, now=_NOW)


def test_pg_health_idle_exceeds_total_raises() -> None:
    with pytest.raises(MetaAlertError, match="cannot exceed"):
        PGHealthSnapshot(idle_in_transaction=10, total_connections=5, now=_NOW)


def test_pg_health_naive_now_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        PGHealthSnapshot(
            idle_in_transaction=0, total_connections=5, now=datetime(2026, 5, 14, 10, 0, 0)
        )


# ── Rule 7: evaluate_market_crisis (HC-2b3 G4 — V3 §14 mode 9 千股跌停极端 regime) ──


def test_market_crisis_both_none_not_triggered() -> None:
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=None, limit_down_count=None, now=_NOW)
    )
    assert alert.triggered is False
    assert alert.rule_id is MetaAlertRuleId.MARKET_CRISIS_REGIME
    assert alert.severity is MetaAlertSeverity.P0
    assert "no signal" in alert.detail


def test_market_crisis_index_boundary_exactly_threshold_triggered() -> None:
    # exactly -7% → triggered (rule uses <=)
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(
            index_return=MARKET_CRISIS_INDEX_RETURN_THRESHOLD, limit_down_count=10, now=_NOW
        )
    )
    assert MARKET_CRISIS_INDEX_RETURN_THRESHOLD == -0.07
    assert alert.triggered is True
    assert "大盘" in alert.detail


def test_market_crisis_index_just_above_threshold_not_triggered() -> None:
    # -6.99% → NOT triggered (above the -7% threshold)
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=-0.0699, limit_down_count=10, now=_NOW)
    )
    assert alert.triggered is False
    assert "within bounds" in alert.detail
    # both legs present → detail shows both numeric values, no "n/a" placeholder
    assert "n/a" not in alert.detail


def test_market_crisis_index_deep_drop_triggered() -> None:
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=-0.09, limit_down_count=None, now=_NOW)
    )
    assert alert.triggered is True
    assert "Crisis Mode" in alert.detail


def test_market_crisis_limit_down_boundary_exactly_threshold_not_triggered() -> None:
    # exactly 500 跌停 → NOT triggered (rule uses strict >)
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(
            index_return=-0.01, limit_down_count=MARKET_CRISIS_LIMIT_DOWN_THRESHOLD, now=_NOW
        )
    )
    assert MARKET_CRISIS_LIMIT_DOWN_THRESHOLD == 500
    assert alert.triggered is False


def test_market_crisis_limit_down_just_over_threshold_triggered() -> None:
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(
            index_return=-0.01, limit_down_count=MARKET_CRISIS_LIMIT_DOWN_THRESHOLD + 1, now=_NOW
        )
    )
    assert alert.triggered is True
    assert "跌停家数 501" in alert.detail


def test_market_crisis_zero_limit_down_not_triggered() -> None:
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=0.01, limit_down_count=0, now=_NOW)
    )
    assert alert.triggered is False


def test_market_crisis_both_legs_hit_detail_has_and() -> None:
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=-0.08, limit_down_count=600, now=_NOW)
    )
    assert alert.triggered is True
    assert " AND " in alert.detail
    assert "大盘" in alert.detail
    assert "跌停家数" in alert.detail


def test_market_crisis_one_leg_none_other_hit_triggered() -> None:
    # index None, limit_down over threshold → still triggered (OR semantics)
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=None, limit_down_count=700, now=_NOW)
    )
    assert alert.triggered is True


def test_market_crisis_one_leg_none_other_safe_not_triggered() -> None:
    # index None, limit_down safe → not triggered; detail shows n/a for missing leg
    alert = evaluate_market_crisis(
        MarketCrisisSnapshot(index_return=None, limit_down_count=10, now=_NOW)
    )
    assert alert.triggered is False
    assert "n/a" in alert.detail


def test_market_crisis_negative_limit_down_raises() -> None:
    with pytest.raises(MetaAlertError, match="limit_down_count"):
        MarketCrisisSnapshot(index_return=-0.01, limit_down_count=-1, now=_NOW)


def test_market_crisis_naive_now_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        MarketCrisisSnapshot(
            index_return=-0.08, limit_down_count=600, now=datetime(2026, 5, 14, 10, 0, 0)
        )


# ── interface: RULE_SEVERITY SSOT + MetaAlert contract ──


def test_rule_severity_ssot_news_is_p1_others_p0() -> None:
    assert RULE_SEVERITY[MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT] is MetaAlertSeverity.P1
    assert RULE_SEVERITY[MetaAlertRuleId.L1_HEARTBEAT_STALE] is MetaAlertSeverity.P0
    assert RULE_SEVERITY[MetaAlertRuleId.LITELLM_FAILURE_RATE] is MetaAlertSeverity.P0
    assert RULE_SEVERITY[MetaAlertRuleId.DINGTALK_PUSH_FAILED] is MetaAlertSeverity.P0
    assert RULE_SEVERITY[MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE] is MetaAlertSeverity.P0
    # HC-2b3 G3/G4 — both P0 per V3 §14 mode 3 / mode 9
    assert RULE_SEVERITY[MetaAlertRuleId.PG_POOL_EXHAUSTED] is MetaAlertSeverity.P0
    assert RULE_SEVERITY[MetaAlertRuleId.MARKET_CRISIS_REGIME] is MetaAlertSeverity.P0
    # every rule id has a severity mapping
    assert set(RULE_SEVERITY) == set(MetaAlertRuleId)


def test_meta_alert_naive_observed_at_raises() -> None:
    with pytest.raises(MetaAlertError, match="tz-aware"):
        MetaAlert(
            rule_id=MetaAlertRuleId.L1_HEARTBEAT_STALE,
            severity=MetaAlertSeverity.P0,
            triggered=False,
            detail="x",
            observed_at=datetime(2026, 5, 14, 10, 0, 0),
        )


def test_meta_alert_to_jsonable_shape() -> None:
    alert = evaluate_dingtalk_push(
        DingTalkPushSnapshot(
            last_push_attempted=True, last_push_ok=False, last_push_status="500", now=_NOW
        )
    )
    js = alert.to_jsonable()
    assert js == {
        "rule_id": "dingtalk_push_failed",
        "severity": "p0",
        "triggered": True,
        "detail": alert.detail,
        "observed_at": _NOW.isoformat(),
    }
    # str enums serialize as plain str (JSON-safe)
    assert isinstance(js["rule_id"], str)
    assert isinstance(js["severity"], str)


def test_str_enum_serialization() -> None:
    # StrEnum members compare equal to their str value (sustained RegimeLabel 体例)
    assert MetaAlertSeverity.P0 == "p0"
    assert MetaAlertRuleId.L1_HEARTBEAT_STALE == "l1_heartbeat_stale"
