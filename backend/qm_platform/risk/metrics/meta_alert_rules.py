"""V3 §13.3 元告警 (alert on alert) — 5 PURE rule eval functions (HC-1a).

本模块 0 IO / 0 DB / 0 Redis / 0 LiteLLM / 0 HTTP (铁律 31 Platform Engine PURE).
每个 rule = 纯函数: input snapshot (HC-1b Application layer 采集) → MetaAlert.

5 rule 对齐 V3 §13.3 5 风控系统失效场景 (meta_alert_interface.py docstring 详):
  evaluate_l1_heartbeat            — L1 RealtimeRiskEngine 心跳超 5min 无 tick    (P0)
  evaluate_litellm_failure_rate    — LiteLLM API 失败率 > 50% (5min window)       (P0)
  evaluate_dingtalk_push           — DingTalk push 失败 (无 200 response)         (P0)
  evaluate_news_sources_timeout    — L0 News 全源 timeout (5min)                  (P1)
  evaluate_staged_overdue          — L4 STAGED PENDING_CONFIRM 超 35min            (P0)

每个 rule **总是** 返回 MetaAlert (triggered True 或 False) — 沿用 RuleResult
always-return-with-bool 体例; HC-1b meta_monitor_service 据 .triggered 过滤后推
channel fallback chain (主 DingTalk → 备 email → 极端 系统弹窗 + log P0).
"""

from __future__ import annotations

from .meta_alert_interface import (
    L1_HEARTBEAT_STALE_THRESHOLD_S,
    LITELLM_FAILURE_RATE_THRESHOLD,
    RULE_SEVERITY,
    STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S,
    DingTalkPushSnapshot,
    L1HeartbeatSnapshot,
    LiteLLMCallWindowSnapshot,
    MetaAlert,
    MetaAlertRuleId,
    NewsSourceWindowSnapshot,
    StagedPlanWindowSnapshot,
)

_PENDING_CONFIRM_STATUS = "PENDING_CONFIRM"


def evaluate_l1_heartbeat(snapshot: L1HeartbeatSnapshot) -> MetaAlert:
    """Rule 1 — L1 RealtimeRiskEngine 心跳超 5min 无 tick (V3 §13.3, P0).

    triggered iff now - last_tick_at > 300s. last_tick_at is None (engine 尚未
    产生任何 tick) → not triggered + detail 标明 (HC-1b service 仅在 engine
    expected-running 时评估本 rule, "engine never started" 由 service 另行处理).
    """
    rule_id = MetaAlertRuleId.L1_HEARTBEAT_STALE
    severity = RULE_SEVERITY[rule_id]

    if snapshot.last_tick_at is None:
        return MetaAlert(
            rule_id=rule_id,
            severity=severity,
            triggered=False,
            detail="no heartbeat data available (L1 engine may not be started)",
            observed_at=snapshot.now,
        )

    stale_seconds = (snapshot.now - snapshot.last_tick_at).total_seconds()
    triggered = stale_seconds > L1_HEARTBEAT_STALE_THRESHOLD_S
    if triggered:
        detail = (
            f"L1 heartbeat stale {stale_seconds:.0f}s > {L1_HEARTBEAT_STALE_THRESHOLD_S}s "
            f"threshold (last tick {snapshot.last_tick_at.isoformat()}) — xtquant 断连?"
        )
    else:
        detail = (
            f"L1 heartbeat healthy {stale_seconds:.0f}s <= "
            f"{L1_HEARTBEAT_STALE_THRESHOLD_S}s threshold"
        )
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=detail,
        observed_at=snapshot.now,
    )


def evaluate_litellm_failure_rate(snapshot: LiteLLMCallWindowSnapshot) -> MetaAlert:
    """Rule 2 — LiteLLM API 失败率 > 50% (5min window) (V3 §13.3, P0).

    triggered iff total_calls > 0 AND failed_calls / total_calls > 0.50.
    total_calls == 0 (window 内无调用) → not triggered (无信号, 不是失效).
    """
    rule_id = MetaAlertRuleId.LITELLM_FAILURE_RATE
    severity = RULE_SEVERITY[rule_id]

    if snapshot.total_calls == 0:
        return MetaAlert(
            rule_id=rule_id,
            severity=severity,
            triggered=False,
            detail=f"no LiteLLM calls in {snapshot.window_seconds}s window — no signal",
            observed_at=snapshot.now,
        )

    failure_rate = snapshot.failed_calls / snapshot.total_calls
    triggered = failure_rate > LITELLM_FAILURE_RATE_THRESHOLD
    verb = "exceeds" if triggered else "within"
    detail = (
        f"LiteLLM failure rate {failure_rate:.1%} ({snapshot.failed_calls}/"
        f"{snapshot.total_calls}) {verb} {LITELLM_FAILURE_RATE_THRESHOLD:.0%} threshold "
        f"over {snapshot.window_seconds}s window"
    )
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=detail,
        observed_at=snapshot.now,
    )


def evaluate_dingtalk_push(snapshot: DingTalkPushSnapshot) -> MetaAlert:
    """Rule 3 — DingTalk push 失败 (无 200 response) (V3 §13.3, P0).

    triggered iff last_push_attempted AND NOT last_push_ok. 无 push 历史
    (last_push_attempted False) → not triggered (无信号).
    """
    rule_id = MetaAlertRuleId.DINGTALK_PUSH_FAILED
    severity = RULE_SEVERITY[rule_id]

    if not snapshot.last_push_attempted:
        return MetaAlert(
            rule_id=rule_id,
            severity=severity,
            triggered=False,
            detail="no DingTalk push attempted yet — no signal",
            observed_at=snapshot.now,
        )

    triggered = not snapshot.last_push_ok
    if triggered:
        detail = (
            f"DingTalk push failed (last status: {snapshot.last_push_status!r}, "
            f"no 200 response) — 元告警 channel 降级 email/弹窗"
        )
    else:
        detail = f"DingTalk push healthy (last status: {snapshot.last_push_status!r})"
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=detail,
        observed_at=snapshot.now,
    )


def evaluate_news_sources_timeout(snapshot: NewsSourceWindowSnapshot) -> MetaAlert:
    """Rule 4 — L0 News 全源 timeout (5min window) (V3 §13.3, P1).

    triggered iff timed_out_sources == total_sources (全部源 timeout). 部分源
    timeout → not triggered (fail-open: alert 仍发, 仅缺 sentiment context —
    V3 §14 mode 6 ⚠️ P1, 降级非系统失效, 故 severity P1 见 interface docstring).
    """
    rule_id = MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT
    severity = RULE_SEVERITY[rule_id]

    triggered = snapshot.timed_out_sources == snapshot.total_sources
    if triggered:
        detail = (
            f"all {snapshot.total_sources} News sources timed out over "
            f"{snapshot.window_seconds}s window — fail-open (alert 仍发, 缺 sentiment context)"
        )
    else:
        detail = (
            f"{snapshot.timed_out_sources}/{snapshot.total_sources} News sources timed out "
            f"over {snapshot.window_seconds}s window — partial, not all-source failure"
        )
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=detail,
        observed_at=snapshot.now,
    )


def evaluate_staged_overdue(snapshot: StagedPlanWindowSnapshot) -> MetaAlert:
    """Rule 5 — L4 STAGED PENDING_CONFIRM 超 35min (cancel_deadline 机制失效) (V3 §13.3, P0).

    triggered iff 任一 plan status == PENDING_CONFIRM AND now - pending_since > 2100s.
    区别于 V3 §14 mode 8 的正常 30min auto-execute (设计行为, 不元告警) — 超 35min
    仍 PENDING_CONFIRM = plan 应在 30min 被 auto-resolve 却未被处理 = 机制失效 P0.
    空 plans tuple OR 无 PENDING_CONFIRM plan → not triggered.
    """
    rule_id = MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE
    severity = RULE_SEVERITY[rule_id]

    overdue: list[tuple[int, float]] = []
    for plan in snapshot.plans:
        if plan.status != _PENDING_CONFIRM_STATUS:
            continue
        pending_seconds = (snapshot.now - plan.pending_since).total_seconds()
        if pending_seconds > STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S:
            overdue.append((plan.plan_id, pending_seconds))

    triggered = len(overdue) > 0
    if triggered:
        worst = max(overdue, key=lambda x: x[1])
        detail = (
            f"{len(overdue)} STAGED plan(s) PENDING_CONFIRM > "
            f"{STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S}s (worst: plan_id={worst[0]} "
            f"@ {worst[1]:.0f}s) — cancel_deadline 机制失效?"
        )
    else:
        pending_count = sum(1 for p in snapshot.plans if p.status == _PENDING_CONFIRM_STATUS)
        detail = (
            f"{pending_count} STAGED plan(s) PENDING_CONFIRM, none over "
            f"{STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S}s threshold"
        )
    return MetaAlert(
        rule_id=rule_id,
        severity=severity,
        triggered=triggered,
        detail=detail,
        observed_at=snapshot.now,
    )


__all__ = [
    "evaluate_dingtalk_push",
    "evaluate_l1_heartbeat",
    "evaluate_litellm_failure_rate",
    "evaluate_news_sources_timeout",
    "evaluate_staged_overdue",
]
