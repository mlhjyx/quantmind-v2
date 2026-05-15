"""V3 §14 失败模式 灾备演练 ≥1 round synthetic injection (HC-2c — HC-2 sprint closure).

V3 §14.1 line 1463-1472 codifies the disaster-drill methodology. Plan v0.3 §A HC-2c +
§D 真测期 SOP: 灾备演练 ≥1 round = pytest 注入 failure mode 1-12 trigger condition,
instant (0 wall-clock wait — sustained memory feedback_no_observation_periods 反日历式
观察期, NOT V3 §14.1 "每月 1 次" wall-clock drill).

每 mode round (§D SOP): 注入 trigger condition → assert 检测 mechanism fire → assert
降级路径 taken → assert 恢复条件 path → assert 元告警 flag (若 wired).

This drill exercises the cumulative HC-2 enforcement surface end-to-end:
  HC-1   (5 polled meta-alert rules)        — mode 1/2/5/6/8
  HC-2b2 (G7 broker stuck / G8 Redis)       — mode 12/4
  HC-2b3 (G3 PG health / G4 Crisis regime)  — mode 3/9
Deep per-feature unit coverage lives in the respective test files (test_meta_alert_rules
/ test_meta_monitor_service / test_l4_sweep_tasks / etc); this drill is the integrated
round proving the surface responds to synthetic failure injection.

Gap rounds (HC-2a matrix §3 — the drill REVEALING the gap IS its purpose):
  mode 2/11 — evaluate_l1_heartbeat PURE rule works; collector no-signal / no
              production XtQuantTickSubscriber|RealtimeRiskEngine runner (G1/G2 DEFER
              → Plan v0.4 cutover).
  mode 7    — is_rate_limit inline detection + 60s cooldown EXISTS; 元告警 MISSING
              (G10, spec ⚠️ P2 deferred).
  mode 10   — no quantitative 误报率 threshold (G12); qualitative RiskReflector path.

关联: V3 §14 失败模式表 line 1445-1461 / §14.1 灾备演练 line 1463-1472 / §14.2 Crisis
Mode line 1474-1483 / HC-2a matrix docs/audit/v3_hc_2a_failure_mode_enforcement_matrix_
2026_05_14.md / Plan v0.3 §A HC-2c + §D / ADR-074 (HC-2 closure) /
docs/risk_reflections/disaster_drill/2026-05-14.md (本 drill round-1 sediment)
关联铁律: 25 (改什么读什么) / 31 (Engine PURE) / 33 (fail-loud) / 40 (test debt) / 41 (timezone)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.services.risk.meta_monitor_service import MetaMonitorService
from backend.qm_platform.risk import RuleResult
from backend.qm_platform.risk.dynamic_threshold.cache import (
    InMemoryThresholdCache,
    RedisThresholdCache,
)
from backend.qm_platform.risk.execution.batched_planner import (
    BatchedPositionInput,
    compute_batch_count,
    generate_batched_plans,
)
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    ExecutionPlan,
    L4ExecutionPlanner,
    PlanStatus,
)
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    L1_HEARTBEAT_STALE_THRESHOLD_S,
    LITELLM_FAILURE_RATE_WINDOW_S,
    NEWS_SOURCE_TIMEOUT_WINDOW_S,
    PG_IDLE_IN_TX_THRESHOLD,
    STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S,
    DingTalkPushSnapshot,
    L1HeartbeatSnapshot,
    LiteLLMCallWindowSnapshot,
    MarketCrisisSnapshot,
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

# Fixed tz-aware drill anchor (铁律 41 — UTC internal).
_NOW = datetime(2026, 5, 14, 10, 30, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────
# Mode 1 — LiteLLM cloud 全挂
# ─────────────────────────────────────────────────────────────


class TestDrillMode1LiteLLMCloudOutage:
    """V3 §14 mode 1 — LiteLLM cloud 全挂 (6 provider 全 timeout, 失败率 > 50%).

    检测: evaluate_litellm_failure_rate (HC-1 polled rule). 降级: Ollama 本地
    fallback (router FALLBACK_ALIAS). 恢复: provider 任 1 恢复 → 失败率回落.
    元告警: ✅ P0 wired (HC-1).
    """

    def test_inject_failure_rate_over_50pct_triggers_meta_alert(self) -> None:
        # 注入: 100 calls / 80 failed = 80% > 50% threshold.
        snap = LiteLLMCallWindowSnapshot(
            total_calls=100,
            failed_calls=80,
            window_seconds=LITELLM_FAILURE_RATE_WINDOW_S,
            now=_NOW,
        )
        alert = evaluate_litellm_failure_rate(snap)
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P0  # 元告警 wired

    def test_recovery_failure_rate_under_threshold_clears(self) -> None:
        # 恢复: provider 任 1 恢复 → 失败率回落 10% → not triggered.
        snap = LiteLLMCallWindowSnapshot(
            total_calls=100,
            failed_calls=10,
            window_seconds=LITELLM_FAILURE_RATE_WINDOW_S,
            now=_NOW,
        )
        assert evaluate_litellm_failure_rate(snap).triggered is False


# ─────────────────────────────────────────────────────────────
# Mode 2 — xtquant subscribe_quote 断连
# ─────────────────────────────────────────────────────────────


class TestDrillMode2XtquantDisconnect:
    """V3 §14 mode 2 — xtquant subscribe_quote 断连 (5min 无 tick callback).

    检测: evaluate_l1_heartbeat (HC-1 PURE rule). GAP (HC-2a matrix G2): collector
    is no-signal — no production XtQuantTickSubscriber runner exists to instrument;
    DEFERRED to Plan v0.4 cutover. Drill exercises the PURE rule + documents the gap.
    """

    def test_inject_stale_heartbeat_triggers_rule(self) -> None:
        # 注入: last tick 400s ago > 300s threshold.
        snap = L1HeartbeatSnapshot(
            last_tick_at=_NOW - timedelta(seconds=L1_HEARTBEAT_STALE_THRESHOLD_S + 100),
            now=_NOW,
        )
        alert = evaluate_l1_heartbeat(snap)
        assert alert.triggered is True
        assert "xtquant" in alert.detail

    def test_recovery_fresh_heartbeat_clears(self) -> None:
        # 恢复: 重连 success → fresh tick → not triggered.
        snap = L1HeartbeatSnapshot(last_tick_at=_NOW - timedelta(seconds=30), now=_NOW)
        assert evaluate_l1_heartbeat(snap).triggered is False

    def test_gap_collector_no_signal_when_redis_key_absent(self) -> None:
        # IC-1c WU-3 (2026-05-15): _collect_l1_heartbeat is now Redis-backed
        # (was static no-signal stub through HC-2c when this drill was written).
        # When the Redis key `risk:l1_heartbeat` is absent (engine never started
        # / TTL expired post-3600s-after-crash), last_tick_at=None → rule "no
        # signal" — the same "no-signal" assertion still holds, but the
        # mechanism is now real (Redis miss) rather than a static stub.
        from unittest.mock import MagicMock

        empty_redis = MagicMock()
        empty_redis.get.return_value = None
        svc = MetaMonitorService(redis_client=empty_redis)
        snap = svc._collect_l1_heartbeat(_NOW)
        assert snap.last_tick_at is None  # no-signal — Redis key absent


# ─────────────────────────────────────────────────────────────
# Mode 3 — PG OOM / lock
# ─────────────────────────────────────────────────────────────


class TestDrillMode3PGOOMLock:
    """V3 §14 mode 3 — PG OOM / lock (connection pool exhausted / idle-in-tx 堆积).

    检测: evaluate_pg_health (HC-2b3 G3 polled rule). 降级路径 (risk_event_log →
    memory-cache full degrade) DEFERRED — carried to HC-4/Plan v0.4 (HC-2a matrix
    G3 — ~30-file writer surface, sprint-sized). 元告警: ✅ P0 wired (HC-2b3 G3).
    """

    def test_inject_idle_in_tx_over_50_triggers_meta_alert(self) -> None:
        # 注入: 60 idle-in-transaction connections > 50 threshold.
        snap = PGHealthSnapshot(
            idle_in_transaction=PG_IDLE_IN_TX_THRESHOLD + 10,
            total_connections=80,
            now=_NOW,
        )
        alert = evaluate_pg_health(snap)
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P0  # 元告警 wired

    def test_recovery_idle_in_tx_drains_clears(self) -> None:
        # 恢复: PG 恢复 → idle-in-tx drains → not triggered.
        snap = PGHealthSnapshot(idle_in_transaction=2, total_connections=8, now=_NOW)
        assert evaluate_pg_health(snap).triggered is False


# ─────────────────────────────────────────────────────────────
# Mode 4 — Redis 不可用
# ─────────────────────────────────────────────────────────────


class TestDrillMode4RedisUnavailable:
    """V3 §14 mode 4 — Redis 不可用 (ping fail).

    检测: RedisThresholdCache._ensure_redis. 降级: InMemoryThresholdCache fallback
    (get returns None → caller falls back in-memory). 恢复: HC-2b2 G8 auto-reconnect
    — re-inject client → _ensure_redis True, NO process restart. 元告警: MISSING
    (HC-2a matrix G8 — Redis 元告警 rule not added; G8 only did auto-reconnect).
    """

    def test_inject_redis_down_get_returns_none_degrade(self) -> None:
        # 注入: injected client dropped to None (simulates a get-failure that
        # dropped the suspect client per HC-2b2 G8 → next call degrades).
        cache = RedisThresholdCache(redis_client=MagicMock())
        cache._redis = None
        assert cache.get("rapid_drop_5min", "600519.SH") is None  # degrade

    def test_degrade_in_memory_fallback_round_trips(self) -> None:
        # 降级路径: InMemoryThresholdCache is the documented Redis-down fallback.
        mem = InMemoryThresholdCache()
        mem.set_batch({"rapid_drop_5min": {"600519.SH": 0.045}})
        assert mem.get("rapid_drop_5min", "600519.SH") == 0.045

    def test_recovery_reinject_client_no_process_restart(self) -> None:
        # 恢复 (HC-2b2 G8): re-inject a live client → _ensure_redis True again,
        # NO process restart needed (反 原 _connect_attempted 永久阻断 anti-pattern).
        cache = RedisThresholdCache(redis_client=MagicMock())
        cache._redis = None
        assert cache._ensure_redis() is False  # Redis down
        cache._redis = MagicMock()  # Redis recovered, client re-injected
        assert cache._ensure_redis() is True  # recovered, 0 process restart


# ─────────────────────────────────────────────────────────────
# Mode 5 — DingTalk webhook fail
# ─────────────────────────────────────────────────────────────


class TestDrillMode5DingTalkWebhookFail:
    """V3 §14 mode 5 — DingTalk webhook fail (无 200 response).

    检测: evaluate_dingtalk_push (HC-1 polled rule). 降级: channel fallback chain
    主 DingTalk → 备 email → 极端 log-P0 (HC-1b2 — deep coverage in
    test_meta_monitor_service.py _push_via_channel_chain). 元告警: ✅ P0 wired (HC-1).
    """

    def test_inject_dingtalk_push_failed_triggers_meta_alert(self) -> None:
        # 注入: 最近一次 push 无 200 response.
        snap = DingTalkPushSnapshot(
            last_push_attempted=True,
            last_push_ok=False,
            last_push_status="ConnectTimeout",
            now=_NOW,
        )
        alert = evaluate_dingtalk_push(snap)
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P0  # 元告警 wired

    def test_recovery_push_ok_clears(self) -> None:
        # 恢复: DingTalk 恢复 → push 200 → not triggered.
        snap = DingTalkPushSnapshot(
            last_push_attempted=True,
            last_push_ok=True,
            last_push_status="200",
            now=_NOW,
        )
        assert evaluate_dingtalk_push(snap).triggered is False


# ─────────────────────────────────────────────────────────────
# Mode 6 — News 6 源全 timeout
# ─────────────────────────────────────────────────────────────


class TestDrillMode6NewsAllSourcesTimeout:
    """V3 §14 mode 6 — News 6 源全 timeout (30s 内 0 源命中).

    检测: evaluate_news_sources_timeout (HC-1 polled rule). 降级: fail-open (alert
    仍发, 仅缺 sentiment context). 恢复: 任 1 源恢复. 元告警: ✅ P1 wired (HC-1 —
    P1 not P0 per §14 表 per-mode 真值, fail-open = degraded 非系统失效).
    """

    def test_inject_all_sources_timeout_triggers_meta_alert(self) -> None:
        # 注入: 6/6 源 timeout.
        snap = NewsSourceWindowSnapshot(
            total_sources=6,
            timed_out_sources=6,
            window_seconds=NEWS_SOURCE_TIMEOUT_WINDOW_S,
            now=_NOW,
        )
        alert = evaluate_news_sources_timeout(snap)
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P1  # fail-open degraded

    def test_recovery_partial_source_recovery_clears(self) -> None:
        # 恢复: 任 1 源恢复 → 5/6 timeout → not all-source → not triggered (fail-open).
        snap = NewsSourceWindowSnapshot(
            total_sources=6,
            timed_out_sources=5,
            window_seconds=NEWS_SOURCE_TIMEOUT_WINDOW_S,
            now=_NOW,
        )
        assert evaluate_news_sources_timeout(snap).triggered is False


# ─────────────────────────────────────────────────────────────
# Mode 7 — Tushare API 限速
# ─────────────────────────────────────────────────────────────


class TestDrillMode7TushareRateLimit:
    """V3 §14 mode 7 — Tushare API 限速 (429 / 频率限制).

    检测: `tushare_api.is_rate_limit_error` — HC-2c extracted a module-level pure
    helper + `RATE_LIMIT_KEYWORDS` constant from the previously-inline detection
    (铁律 34 single source), so this drill imports + asserts the REAL function, not
    a replicated copy. 降级: rate-limit → 60s 固定冷却 (`_call_with_retry`); 非
    rate-limit → 指数退避. 元告警: MISSING (HC-2a matrix G10 — Tushare 元告警 rule
    not added, spec ⚠️ P2 deferred). Deep verify = HC-2a matrix §2 mode 7 cite.
    """

    def test_inject_rate_limit_error_classified_for_60s_cooldown(self) -> None:
        from backend.app.data_fetcher.tushare_api import is_rate_limit_error

        # 注入: Tushare rate-limit error messages → is_rate_limit_error True
        # → 60s 固定冷却 degrade path.
        assert is_rate_limit_error("抱歉，您每分钟最多访问该接口200次") is True
        assert is_rate_limit_error("Error: too many requests, please slow down") is True

    def test_non_rate_limit_error_takes_exponential_backoff(self) -> None:
        from backend.app.data_fetcher.tushare_api import is_rate_limit_error

        # 非 rate-limit error → 指数退避 path (NOT the 60s fixed cooldown).
        assert is_rate_limit_error("Connection reset by peer") is False


# ─────────────────────────────────────────────────────────────
# Mode 8 — user 离线 (DingTalk 未读) + STAGED 30min timeout
# ─────────────────────────────────────────────────────────────


class TestDrillMode8UserOfflineStagedTimeout:
    """V3 §14 mode 8 — user 离线 (DingTalk 未读), STAGED PENDING_CONFIRM 超 30min.

    检测: cancel_deadline timeout. 降级: STAGED default 执行 (反向决策权 §7.1). 恢复:
    user 重新上线 → cancel. 元告警: ❌ 不元告警 (设计行为 — 30min auto-execute). 注:
    超 35min 仍 PENDING_CONFIRM = cancel_deadline 机制失效 → evaluate_staged_overdue
    (HC-1) 覆盖此失效变体 (区别于正常 30min auto-execute).
    """

    @staticmethod
    def _staged_plan() -> tuple[ExecutionPlan, datetime]:
        result = RuleResult(
            rule_id="trailing_stop",
            code="600519.SH",
            shares=500,
            reason="TrailingStop: 600519.SH 触发动态止盈",
            metrics={"current_price": 200.0},
        )
        planner = L4ExecutionPlanner(staged_enabled=True)
        t0 = _NOW
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=t0)
        assert plan is not None
        return plan, t0

    def test_inject_user_offline_past_window_timeout_executes(self) -> None:
        # 注入: user 离线 4h — well past the 30min cancel window.
        plan, t0 = self._staged_plan()
        offline_until = t0 + timedelta(hours=4)
        assert L4ExecutionPlanner.check_timeout(plan, offline_until) is True
        executed = plan.timeout_execute(offline_until)
        assert executed.status == PlanStatus.TIMEOUT_EXECUTED  # 降级: default 执行

    def test_recovery_user_online_cancels_within_window(self) -> None:
        # 恢复: user 重新上线 within window → cancel.
        plan, t0 = self._staged_plan()
        cancelled = plan.cancel(t0 + timedelta(minutes=10))
        assert cancelled.status == PlanStatus.CANCELLED

    def test_cancel_deadline_failure_variant_triggers_staged_overdue(self) -> None:
        # 超 35min 仍 PENDING_CONFIRM = cancel_deadline 机制失效 → evaluate_staged_overdue.
        plan_state = StagedPlanState(
            plan_id="drill-m8-stuck",
            status="PENDING_CONFIRM",
            pending_since=_NOW - timedelta(seconds=STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S + 60),
        )
        alert = evaluate_staged_overdue(StagedPlanWindowSnapshot(plans=(plan_state,), now=_NOW))
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P0


# ─────────────────────────────────────────────────────────────
# Mode 9 — 千股跌停极端 regime
# ─────────────────────────────────────────────────────────────


class TestDrillMode9CrisisRegime:
    """V3 §14 mode 9 — 千股跌停极端 regime (大盘 -7% / 跌停家数 > 500).

    检测: evaluate_market_crisis (HC-2b3 G4 polled rule). 降级: BatchedPlanner
    分批平仓 (V3 §7.2 — 5min interval, batch 间 re-evaluation, 反流动性冲击).
    恢复: regime 恢复. 元告警: ✅ P0 wired (HC-2b3 G4). 注: §14.2 Crisis Mode 行为
    (alert dedup / portfolio push / News 减频) DEFERRED — carried (HC-2b3 G4 scope).
    """

    def test_inject_market_crash_minus_8pct_triggers_meta_alert(self) -> None:
        # 注入: 大盘 -8% (≤ -7% threshold).
        snap = MarketCrisisSnapshot(index_return=-0.08, limit_down_count=None, now=_NOW)
        alert = evaluate_market_crisis(snap)
        assert alert.triggered is True
        assert alert.severity is MetaAlertSeverity.P0  # 元告警 wired

    def test_inject_thousand_limit_down_triggers_meta_alert(self) -> None:
        # 注入: 跌停家数 600 (> 500 threshold).
        snap = MarketCrisisSnapshot(index_return=-0.01, limit_down_count=600, now=_NOW)
        assert evaluate_market_crisis(snap).triggered is True

    def test_degrade_batched_planner_splits_liquidation(self) -> None:
        # 降级路径: Crisis regime → BatchedPlanner 分 N 批平仓 (V3 §7.2).
        positions = [
            BatchedPositionInput(
                code=f"60000{i}.SH",
                shares=1000,
                current_price=10.0,
                daily_volume=1_000_000.0,
                drop_pct=-0.09,
            )
            for i in range(5)
        ]
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="Crisis regime disaster drill",
            positions=positions,
            mode=ExecutionMode.STAGED,
            at=_NOW,
        )
        # N = max(3, ceil(5 × 0.3)) = 3 batches — tie the produced plans to the
        # computed batch count (反 dead assertion restating compute_batch_count 自身).
        n_batches = compute_batch_count(5)
        assert n_batches == 3
        assert len(plans) > 0
        assert {p.batch_total for p in plans} == {n_batches}
        # batch_index sequenced 1..N (反 all-same-index bug 仍通过 batch_total check).
        assert {p.batch_index for p in plans} == set(range(1, n_batches + 1))

    def test_recovery_regime_normalizes_clears(self) -> None:
        # 恢复: regime 恢复 → 大盘 -1% / 跌停 50 → not triggered.
        snap = MarketCrisisSnapshot(index_return=-0.01, limit_down_count=50, now=_NOW)
        assert evaluate_market_crisis(snap).triggered is False


# ─────────────────────────────────────────────────────────────
# Mode 10 — 误触发 (高 false positive)
# ─────────────────────────────────────────────────────────────


class TestDrillMode10HighFalsePositive:
    """V3 §14 mode 10 — 误触发 (高 false positive, weekly 误报率 > 30%).

    GAP (HC-2a matrix G12): NO quantitative 误报率 threshold — RiskReflector 走
    V4-Pro 定性 5-维反思 (detection/threshold/action/context/strategy), 非 "30%
    rate" 量化触发. 降级: 反思候选阈值调整 + user approve. 元告警: MISSING.
    Drill round = documented gap: the qualitative reflection path exists; the
    quantitative 30%-threshold detection rule does not (whether it is needed = a
    HC-2b3-style scope decision left to a future sprint, HC-2a matrix §3 G12 P2).
    """

    def test_gap_no_quantitative_false_positive_meta_alert_rule(self) -> None:
        # HC-2a matrix G12: 误触发 mode has NO quantitative detection rule + NO
        # 元告警. Confirm meta_alert_rules exposes no evaluate_false_positive_* fn.
        from backend.qm_platform.risk.metrics import meta_alert_rules

        assert not any(name.startswith("evaluate_false_positive") for name in dir(meta_alert_rules))

    def test_qualitative_reflector_path_exists(self) -> None:
        # The handling path is the qualitative RiskReflector V4-Pro 5-维反思 —
        # assert the concrete interface symbols exist (the documented,
        # non-quantitative mode-10 handling path: 5-维 ReflectionDimension +
        # ReflectionInput contract).
        from backend.qm_platform.risk.reflector.interface import (
            ReflectionDimension,
            ReflectionInput,
        )

        # 5 维反思 framework (detection/threshold/action/context/strategy).
        assert len(list(ReflectionDimension)) == 5
        assert hasattr(ReflectionInput, "__dataclass_fields__")


# ─────────────────────────────────────────────────────────────
# Mode 11 — RealtimeRiskEngine crash
# ─────────────────────────────────────────────────────────────


class TestDrillMode11RealtimeRiskEngineCrash:
    """V3 §14 mode 11 — RealtimeRiskEngine crash (Celery worker 退出).

    检测: evaluate_l1_heartbeat covers heartbeat-stale after a crash. GAP (HC-2a
    matrix G1): NO RealtimeRiskEngine-specific Servy heartbeat + NO production
    runner — shares the "no production realtime runner" root cause with mode 2
    (G2). DEFERRED to Plan v0.4 cutover. Drill exercises the PURE rule + documents
    the shared-root-cause gap.
    """

    def test_inject_post_crash_heartbeat_stale_triggers_rule(self) -> None:
        # 注入: after a crash the heartbeat goes stale (10min) → rule fires.
        snap = L1HeartbeatSnapshot(
            last_tick_at=_NOW - timedelta(seconds=L1_HEARTBEAT_STALE_THRESHOLD_S + 600),
            now=_NOW,
        )
        assert evaluate_l1_heartbeat(snap).triggered is True

    def test_gap_no_production_runner_shared_root_cause_with_mode2(self) -> None:
        # IC-1c WU-3 (2026-05-15): _collect_l1_heartbeat is now a real Redis-
        # backed instance method. The previous "static no-signal stub"
        # assertion stays valid as a documentation of the absent-key path —
        # which is what happens when no production runner is wired (no SETEX
        # writes to `risk:l1_heartbeat`). HC-2a matrix G1 root cause closed
        # at code level by IC-1c WU-2 + WU-3; ops still needs Servy register
        # to actually populate the key (Plan v0.4 cutover scope deliverable).
        from unittest.mock import MagicMock

        empty_redis = MagicMock()
        empty_redis.get.return_value = None
        svc = MetaMonitorService(redis_client=empty_redis)
        snap = svc._collect_l1_heartbeat(_NOW)
        assert snap.last_tick_at is None  # no-signal — Redis key absent (no prod runner)


# ─────────────────────────────────────────────────────────────
# Mode 12 — broker_qmt 接口故障
# ─────────────────────────────────────────────────────────────


class TestDrillMode12BrokerInterfaceFault:
    """V3 §14 mode 12 — broker_qmt 接口故障 (sell 单 INSERT 但 status 卡 > 5min).

    检测: sweep_stuck_broker_plans / _sweep_stuck_inner — SELECT plans stuck in
    CONFIRMED/TIMEOUT_EXECUTED > 5min (HC-2b2 G7). 降级: retry execute_plan; 仍卡
    → 汇总 emit BROKER_PLAN_STUCK 元告警. 恢复: broker 恢复 → retry resolves. 元告警:
    ✅ P0 wired (HC-2b2 G7 — BROKER_PLAN_STUCK event-emitted). Deep coverage:
    test_l4_sweep_tasks.py TestSweepStuckInner.
    """

    @staticmethod
    def _stuck_mock_conn(rows: list[tuple]) -> MagicMock:
        """Mock conn for _sweep_stuck_inner (沿用 test_l4_sweep_tasks _make_stuck_mock_conn)."""
        conn = MagicMock()
        cursor = MagicMock()
        desc = [type("Col", (), {"name": n})() for n in ("plan_id", "status", "stuck_since")]

        def _exec(sql: str, params: tuple) -> None:  # noqa: ARG001
            cursor.description = desc
            cursor.fetchall = MagicMock(return_value=rows)

        cursor.execute = MagicMock(side_effect=_exec)
        cursor.close = MagicMock()
        conn.cursor = MagicMock(return_value=cursor)
        return conn

    def test_inject_stuck_plan_retry_fails_emits_meta_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.app.tasks import l4_sweep_tasks as l4t

        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t,
            "_emit_broker_plan_stuck_meta_alert",
            lambda *a, **k: emit_calls.append((a, k)),
        )
        # 注入: 1 plan stuck in CONFIRMED 1h, retry execute_plan raises (broker fault).
        conn = self._stuck_mock_conn([("drill-m12-stuck", "CONFIRMED", _NOW - timedelta(hours=1))])
        staged = MagicMock()
        staged.execute_plan.side_effect = RuntimeError("broker socket timeout")

        result = l4t._sweep_stuck_inner(conn=conn, staged_service=staged, now=_NOW)

        assert result["scanned"] == 1
        assert result["still_stuck"] == 1  # retry failed → still stuck
        assert len(emit_calls) == 1  # 元告警 emitted (P0)

    def test_recovery_stuck_plan_retry_resolves_no_meta_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.app.tasks import l4_sweep_tasks as l4t

        emit_calls: list[Any] = []
        monkeypatch.setattr(
            l4t,
            "_emit_broker_plan_stuck_meta_alert",
            lambda *a, **k: emit_calls.append((a, k)),
        )
        # 恢复: broker recovered → retry execute_plan succeeds → resolved.
        conn = self._stuck_mock_conn([("drill-m12-ok", "CONFIRMED", _NOW - timedelta(hours=1))])
        staged = MagicMock()
        staged.execute_plan.return_value = MagicMock(
            outcome=MagicMock(value="EXECUTED"), final_status=None
        )

        result = l4t._sweep_stuck_inner(conn=conn, staged_service=staged, now=_NOW)

        assert result["resolved"] == 1
        assert result["still_stuck"] == 0
        assert len(emit_calls) == 0  # no 元告警 — resolved
