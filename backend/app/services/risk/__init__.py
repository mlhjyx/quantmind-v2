"""S8 risk services — DB-aware orchestration layer over qm_platform.risk pure modules.

Sustains layered architecture (CLAUDE.md §3.1):
  Router (api/) → Service (services/risk/) → Engine (qm_platform/risk/, pure compute)
"""

from backend.app.services.risk.dingtalk_webhook_service import (
    DingTalkWebhookResult,
    DingTalkWebhookService,
    WebhookOutcome,
)
from backend.app.services.risk.market_regime_service import MarketRegimeService
from backend.app.services.risk.meta_monitor_service import MetaMonitorService

__all__ = [
    "DingTalkWebhookResult",
    "DingTalkWebhookService",
    "MarketRegimeService",
    "MetaMonitorService",
    "WebhookOutcome",
]
