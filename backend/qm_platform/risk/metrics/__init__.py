"""V3 §13.2 元监控 KPI 聚合 + §15.4 paper-mode 5d verify report (S10).

PURE module (qm_platform/ layer): caller injects psycopg2 conn.
"""

from backend.qm_platform.risk.metrics.daily_aggregator import (
    DailyMetricsResult,
    DailyMetricsSpec,
    aggregate_daily_metrics,
    upsert_daily_metrics,
)
from backend.qm_platform.risk.metrics.verify_report import (
    AcceptanceItem,
    AcceptanceReport,
    generate_verify_report,
)

__all__ = [
    "AcceptanceItem",
    "AcceptanceReport",
    "DailyMetricsResult",
    "DailyMetricsSpec",
    "aggregate_daily_metrics",
    "generate_verify_report",
    "upsert_daily_metrics",
]
