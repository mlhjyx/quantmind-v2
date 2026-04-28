"""Framework #7 Observability — Platform SDK sub-package."""
from .alert import (
    AlertDispatchError,
    DingTalkChannel,
    PostgresAlertRouter,
    get_alert_router,
    reset_alert_router,
)
from .interface import (
    Alert,
    AlertFireResult,
    AlertRouter,
    EventBus,
    Metric,
    MetricExporter,
)
from .metric import (
    MetricExportError,
    PostgresMetricExporter,
    get_metric_exporter,
    reset_metric_exporter,
)
from .outbox import OutboxWriter

# `Channel` Protocol 不导出: 设计稿 (Part 1 line 222-227) 禁 Application 自实现 channel
# 旁路 Platform. 内部扩展 (e.g. SMS / Slack) 走 Platform 评审, 经 alert.py 直接添加.
__all__ = [
    # interface (ABC + dataclass)
    "MetricExporter",
    "AlertRouter",
    "AlertFireResult",
    "EventBus",
    "Metric",
    "Alert",
    # MVP 3.4 outbox
    "OutboxWriter",
    # MVP 4.1 batch 1 — alert
    "PostgresAlertRouter",
    "AlertDispatchError",
    "DingTalkChannel",
    "get_alert_router",
    "reset_alert_router",
    # MVP 4.1 batch 2.1 — metric
    "PostgresMetricExporter",
    "MetricExportError",
    "get_metric_exporter",
    "reset_metric_exporter",
]
