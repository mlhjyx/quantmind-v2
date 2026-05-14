"""V3 §13.3 元告警 (alert on alert) — PURE dataclass + Enum contract (HC-1a foundation).

本模块 0 IO / 0 DB / 0 Redis / 0 LiteLLM / 0 HTTP (铁律 31 Platform Engine PURE).
所有数据采集 (心跳读取 / LiteLLM 调用窗口聚合 / DingTalk push 状态 / News 源 timeout
计数 / STAGED plan 状态查询) 由 HC-1b Application layer (meta_monitor_service) 承担;
本模块定义 5 polled rule 的 input snapshot 契约 + MetaAlert 结果契约 + 阈值 SSOT
+ event-emitted rule id (HC-2b G5 RISK_REFLECTOR_FAILED — 见 MetaAlertRuleId docstring).

对齐 V3 §13.3 元告警 (alert on alert) — 5 风控系统失效场景:
  1. L1 RealtimeRiskEngine 心跳超 5min 无 tick (xtquant 断连)        → P0
  2. LiteLLM API 失败率 > 50% (5min window)                          → P0
  3. DingTalk push 失败 (无 200 response)                            → P0
  4. L0 News 6 源全 timeout (5min)                                   → P1
  5. L4 STAGED 单 status PENDING_CONFIRM 超 35min (cancel_deadline 失效) → P0

**§13.3-vs-§14 severity 真值 reconciliation** (HC-1a Phase 0 Finding):
V3 §13.3 把 5 场景全列在 "P0 元告警" header 下, 但 V3 §14 失败模式表 (更细粒度,
per-mode 元告警 column) 对 News 6 源全 timeout (mode 6) 标 ⚠️ **P1** — 因 News
全 timeout 是 fail-open (alert 仍发, 仅缺 sentiment context), 属降级非系统失效.
本模块 News rule severity = P1 (follow §14 表 per-mode 更细粒度真值), 其余 4 = P0.
注: §13.3 的 STAGED **>35min** 与 §14 mode 8 的 STAGED **30min user 离线 auto-execute**
是不同场景 — 后者是设计行为 (反向决策权, ❌ 不元告警), 前者是 cancel_deadline 机制
本身失效 (plan 应在 30min 被 auto-resolve 却 35min 仍 PENDING_CONFIRM) = 系统失效 P0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

# ── V3 §13.3 阈值 SSOT (single source of truth — rules.py + HC-1b service import 本处) ──

# 1. L1 心跳 stale 阈值: 超 5min 无 tick → 元告警 (V3 §13.3 line 1420)
L1_HEARTBEAT_STALE_THRESHOLD_S: int = 300

# 2. LiteLLM 失败率阈值: 5min window 内失败率 > 50% → 元告警 (V3 §13.3 line 1421)
LITELLM_FAILURE_RATE_THRESHOLD: float = 0.50
LITELLM_FAILURE_RATE_WINDOW_S: int = 300

# 4. News 6 源全 timeout window (V3 §13.3 line 1423 "5min")
NEWS_SOURCE_TIMEOUT_WINDOW_S: int = 300

# HC-1b3: Redis key SSOT — the News-ingest Beat task (news_ingest_tasks) persists
# DataPipeline per-run stats here; meta_monitor_service._collect_news reads it.
# Single definition (反 cross-module string-equality drift, reviewer MEDIUM).
NEWS_RUN_STATS_REDIS_KEY: str = "qm:news:last_run_stats"

# 5. STAGED PENDING_CONFIRM overdue 阈值: 超 35min → cancel_deadline 机制失效
#    (V3 §13.3 line 1424; 区别于 §14 mode 8 的正常 30min auto-execute)
STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S: int = 2100


class MetaAlertSeverity(StrEnum):
    """元告警 severity — 对齐 V3 §13.3 + §14 失败模式表 per-mode 真值.

    str subclass for natural JSON / SQL serialization (sustained RegimeLabel /
    ActionTaken 体例 from TB-2a / TB-3a).
    """

    P0 = "p0"
    P1 = "p1"


class MetaAlertRuleId(StrEnum):
    """元告警 rule id — V3 §13.3 5 polled rule + V3 §14 event-emitted rule.

    **Polled rules (5)** — 对齐 V3 §13.3 5 风控系统失效场景. HC-1b meta_monitor_service
    每 5min 采集 snapshot → 跑 meta_alert_rules.py 对应 `evaluate_*` 纯函数:
      L1_HEARTBEAT_STALE / LITELLM_FAILURE_RATE / DINGTALK_PUSH_FAILED /
      NEWS_ALL_SOURCES_TIMEOUT / STAGED_PENDING_CONFIRM_OVERDUE

    **Event-emitted rules** — V3 §14 失败模式表 per-mode 元告警, 由失败源头任务在
    捕获自身失败时直接构造 MetaAlert + 走 channel fallback chain (NOT polled — 无
    对应 `evaluate_*` 纯函数 / 无 snapshot 契约; 失败是 event-driven 不是可轮询的
    持续状态):
      RISK_REFLECTOR_FAILED — V3 §14 mode 14: L5 RiskReflector V4-Pro weekly/
        monthly run 重试一次仍失败 (HC-2b G5, risk_reflector_tasks 自 emit)
    """

    L1_HEARTBEAT_STALE = "l1_heartbeat_stale"
    LITELLM_FAILURE_RATE = "litellm_failure_rate"
    DINGTALK_PUSH_FAILED = "dingtalk_push_failed"
    NEWS_ALL_SOURCES_TIMEOUT = "news_all_sources_timeout"
    STAGED_PENDING_CONFIRM_OVERDUE = "staged_pending_confirm_overdue"
    # Event-emitted (HC-2b G5) — see class docstring.
    RISK_REFLECTOR_FAILED = "risk_reflector_failed"


# Per-rule severity SSOT (§13.3-vs-§14 reconciliation — News=P1, 其余 polled=P0;
# RISK_REFLECTOR_FAILED=P1 per V3 §14 mode 14 ⚠️ P1 — 反思失败 = degraded
# (跳过本周/本月反思, alert 仍发, 仅缺 lessons), 非系统失效).
RULE_SEVERITY: dict[MetaAlertRuleId, MetaAlertSeverity] = {
    MetaAlertRuleId.L1_HEARTBEAT_STALE: MetaAlertSeverity.P0,
    MetaAlertRuleId.LITELLM_FAILURE_RATE: MetaAlertSeverity.P0,
    MetaAlertRuleId.DINGTALK_PUSH_FAILED: MetaAlertSeverity.P0,
    MetaAlertRuleId.NEWS_ALL_SOURCES_TIMEOUT: MetaAlertSeverity.P1,
    MetaAlertRuleId.STAGED_PENDING_CONFIRM_OVERDUE: MetaAlertSeverity.P0,
    MetaAlertRuleId.RISK_REFLECTOR_FAILED: MetaAlertSeverity.P1,
}


class MetaAlertError(RuntimeError):
    """元告警 evaluation 契约违反 (snapshot 非 tz-aware / 负计数 / etc).

    rules.py raises this for fail-loud 路径 (铁律 33).
    """


def _require_tz_aware(value: datetime, field_name: str) -> None:
    """Raise MetaAlertError if datetime is naive (铁律 41 sustained)."""
    if value.tzinfo is None:
        raise MetaAlertError(
            f"{field_name} must be tz-aware (铁律 41 sustained), got naive datetime"
        )


# ── 5 rule input snapshot 契约 (HC-1b Application layer 负责采集填充) ──


@dataclass(frozen=True)
class L1HeartbeatSnapshot:
    """Rule 1 input — L1 RealtimeRiskEngine 心跳快照.

    Args:
      last_tick_at: 最近一次 tick callback 的 tz-aware 时间戳. None = engine 尚未
        产生任何 tick (HC-1b service 仅在 engine expected-running 时评估本 rule;
        None → 本 rule not triggered + detail 标明 "no heartbeat data").
      now: 评估时刻 (tz-aware, 铁律 41).
    """

    last_tick_at: datetime | None
    now: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.now, "L1HeartbeatSnapshot.now")
        if self.last_tick_at is not None:
            _require_tz_aware(self.last_tick_at, "L1HeartbeatSnapshot.last_tick_at")
            if self.last_tick_at > self.now:
                raise MetaAlertError(
                    f"L1HeartbeatSnapshot.last_tick_at ({self.last_tick_at.isoformat()}) "
                    f"is in the future relative to now ({self.now.isoformat()})"
                )


@dataclass(frozen=True)
class LiteLLMCallWindowSnapshot:
    """Rule 2 input — LiteLLM API 调用窗口聚合快照 (HC-1b 5min window pre-aggregate).

    Args:
      total_calls: window 内 LiteLLM API 调用总数 (≥ 0).
      failed_calls: window 内失败调用数 (0 ≤ failed_calls ≤ total_calls).
      window_seconds: 聚合 window 长度秒 (HC-1b 传 LITELLM_FAILURE_RATE_WINDOW_S).
      now: 评估时刻 (tz-aware).
    """

    total_calls: int
    failed_calls: int
    window_seconds: int
    now: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.now, "LiteLLMCallWindowSnapshot.now")
        if self.total_calls < 0:
            raise MetaAlertError(f"total_calls must be >= 0, got {self.total_calls}")
        if self.failed_calls < 0:
            raise MetaAlertError(f"failed_calls must be >= 0, got {self.failed_calls}")
        if self.failed_calls > self.total_calls:
            raise MetaAlertError(
                f"failed_calls ({self.failed_calls}) cannot exceed total_calls ({self.total_calls})"
            )
        if self.window_seconds <= 0:
            raise MetaAlertError(f"window_seconds must be > 0, got {self.window_seconds}")


@dataclass(frozen=True)
class DingTalkPushSnapshot:
    """Rule 3 input — DingTalk push 最近一次结果快照.

    Args:
      last_push_attempted: 是否有过 push 尝试 (False = 无 push 历史 → not triggered).
      last_push_ok: 最近一次 push 是否收到 200 response.
      last_push_status: 最近一次 push 状态文本 (e.g. "200" / "timeout" / "500" /
        "connection_error") — 仅用于 MetaAlert.detail, 不参与判定.
      now: 评估时刻 (tz-aware).
    """

    last_push_attempted: bool
    last_push_ok: bool
    last_push_status: str
    now: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.now, "DingTalkPushSnapshot.now")
        if not self.last_push_attempted and self.last_push_ok:
            raise MetaAlertError(
                "DingTalkPushSnapshot.last_push_ok cannot be True when "
                "last_push_attempted is False (contradictory state)"
            )


@dataclass(frozen=True)
class NewsSourceWindowSnapshot:
    """Rule 4 input — L0 News 多源 timeout 窗口快照 (V3 §13.3 "6 源全 timeout").

    Args:
      total_sources: 配置的 News 源总数 (V3 §3.5 当前 6 源; ≥ 1).
      timed_out_sources: window 内 timeout 的源数 (0 ≤ timed_out ≤ total).
      window_seconds: 聚合 window 长度秒 (HC-1b 传 NEWS_SOURCE_TIMEOUT_WINDOW_S).
      now: 评估时刻 (tz-aware).
    """

    total_sources: int
    timed_out_sources: int
    window_seconds: int
    now: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.now, "NewsSourceWindowSnapshot.now")
        if self.total_sources < 1:
            raise MetaAlertError(f"total_sources must be >= 1, got {self.total_sources}")
        if self.timed_out_sources < 0:
            raise MetaAlertError(f"timed_out_sources must be >= 0, got {self.timed_out_sources}")
        if self.timed_out_sources > self.total_sources:
            raise MetaAlertError(
                f"timed_out_sources ({self.timed_out_sources}) cannot exceed "
                f"total_sources ({self.total_sources})"
            )
        if self.window_seconds <= 0:
            raise MetaAlertError(f"window_seconds must be > 0, got {self.window_seconds}")


@dataclass(frozen=True)
class StagedPlanState:
    """One STAGED execution_plan 的相关状态 (StagedPlanWindowSnapshot 的 member).

    Args:
      plan_id: execution_plans.plan_id — UUID text (HC-1b precondition 核 surface:
        execution_plans.plan_id 是 UUID NOT BIGSERIAL, HC-1a `int` 假设修正为 str).
      status: plan status (PENDING_CONFIRM / CONFIRMED / EXECUTED / CANCELLED / ...).
      pending_since: 进入 PENDING_CONFIRM 状态的 tz-aware 时间戳.
    """

    plan_id: str
    status: str
    pending_since: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.pending_since, "StagedPlanState.pending_since")


@dataclass(frozen=True)
class StagedPlanWindowSnapshot:
    """Rule 5 input — 当前所有 STAGED plan 状态快照.

    Args:
      plans: 当前关注的 STAGED plan 状态 tuple (HC-1b 查 execution_plans
        status='PENDING_CONFIRM' 的 plan; 空 tuple = 无 pending plan → not triggered).
      now: 评估时刻 (tz-aware).
    """

    plans: tuple[StagedPlanState, ...]
    now: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.now, "StagedPlanWindowSnapshot.now")


# ── MetaAlert 结果契约 ──


@dataclass(frozen=True)
class MetaAlert:
    """One 元告警 evaluation 结果 — 风控系统失效场景检测结果.

    每个 rule 总是返回一个 MetaAlert (triggered True 或 False) — 沿用 RuleResult
    always-return-with-bool 体例, caller 据 .triggered 过滤. HC-1b service 把
    triggered=True 的 MetaAlert 推 channel fallback chain (DingTalk → email → 弹窗).

    Args:
      rule_id: 5 MetaAlertRuleId 之一.
      severity: P0 / P1 (RULE_SEVERITY SSOT, §13.3-vs-§14 reconciliation).
      triggered: True = 风控系统失效场景命中.
      detail: human-readable 判定依据 (e.g. "L1 heartbeat stale 412s > 300s").
      observed_at: 评估时刻 (tz-aware, 铁律 41 — 取自 input snapshot.now).

    Frozen + immutable per Platform Engine 体例.
    """

    rule_id: MetaAlertRuleId
    severity: MetaAlertSeverity
    triggered: bool
    detail: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_tz_aware(self.observed_at, "MetaAlert.observed_at")

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict (HC-1b 入库 / channel push payload 用)."""
        return {
            "rule_id": self.rule_id.value,
            "severity": self.severity.value,
            "triggered": self.triggered,
            "detail": self.detail,
            "observed_at": self.observed_at.isoformat(),
        }


__all__ = [
    "LITELLM_FAILURE_RATE_THRESHOLD",
    "LITELLM_FAILURE_RATE_WINDOW_S",
    "L1_HEARTBEAT_STALE_THRESHOLD_S",
    "NEWS_RUN_STATS_REDIS_KEY",
    "NEWS_SOURCE_TIMEOUT_WINDOW_S",
    "RULE_SEVERITY",
    "STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S",
    "DingTalkPushSnapshot",
    "L1HeartbeatSnapshot",
    "LiteLLMCallWindowSnapshot",
    "MetaAlert",
    "MetaAlertError",
    "MetaAlertRuleId",
    "MetaAlertSeverity",
    "NewsSourceWindowSnapshot",
    "StagedPlanState",
    "StagedPlanWindowSnapshot",
]
