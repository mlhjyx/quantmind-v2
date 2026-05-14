"""V3 §13.2 元监控 KPI 聚合 + §13.3 元告警 (alert on alert) + §15.4 verify report.

PURE module (qm_platform/ layer): caller injects psycopg2 conn / data snapshots.
  - daily_aggregator / verify_report — §13.2 KPI 日聚合 + §15.4 5d acceptance (S10)
  - meta_alert_interface / meta_alert_rules — §13.3 + §14 元告警 7 polled rule PURE
    eval (HC-1a: 5 rule; HC-2b3: +PG health + 千股跌停 regime)
"""

from backend.qm_platform.risk.metrics.daily_aggregator import (
    DailyMetricsResult,
    DailyMetricsSpec,
    aggregate_daily_metrics,
    upsert_daily_metrics,
)
from backend.qm_platform.risk.metrics.meta_alert_interface import (
    L1_HEARTBEAT_STALE_THRESHOLD_S,
    LITELLM_FAILURE_RATE_THRESHOLD,
    LITELLM_FAILURE_RATE_WINDOW_S,
    MARKET_CRISIS_INDEX_RETURN_THRESHOLD,
    MARKET_CRISIS_LIMIT_DOWN_THRESHOLD,
    NEWS_SOURCE_TIMEOUT_WINDOW_S,
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
from backend.qm_platform.risk.metrics.verify_report import (
    AcceptanceItem,
    AcceptanceReport,
    generate_verify_report,
)

__all__ = [
    "LITELLM_FAILURE_RATE_THRESHOLD",
    "LITELLM_FAILURE_RATE_WINDOW_S",
    "L1_HEARTBEAT_STALE_THRESHOLD_S",
    "MARKET_CRISIS_INDEX_RETURN_THRESHOLD",
    "MARKET_CRISIS_LIMIT_DOWN_THRESHOLD",
    "NEWS_SOURCE_TIMEOUT_WINDOW_S",
    "PG_IDLE_IN_TX_THRESHOLD",
    "RULE_SEVERITY",
    "STAGED_PENDING_CONFIRM_OVERDUE_THRESHOLD_S",
    "AcceptanceItem",
    "AcceptanceReport",
    "DailyMetricsResult",
    "DailyMetricsSpec",
    "DingTalkPushSnapshot",
    "L1HeartbeatSnapshot",
    "LiteLLMCallWindowSnapshot",
    "MarketCrisisSnapshot",
    "MetaAlert",
    "MetaAlertError",
    "MetaAlertRuleId",
    "MetaAlertSeverity",
    "NewsSourceWindowSnapshot",
    "PGHealthSnapshot",
    "StagedPlanState",
    "StagedPlanWindowSnapshot",
    "aggregate_daily_metrics",
    "evaluate_dingtalk_push",
    "evaluate_l1_heartbeat",
    "evaluate_litellm_failure_rate",
    "evaluate_market_crisis",
    "evaluate_news_sources_timeout",
    "evaluate_pg_health",
    "evaluate_staged_overdue",
    "generate_verify_report",
    "upsert_daily_metrics",
]
