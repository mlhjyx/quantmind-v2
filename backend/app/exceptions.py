"""Application-level custom exceptions.

集中放置 application 层 typed exceptions, 便于 catch / log / monitoring.

铁律 33 (fail-loud): 类型化 exception 让上游能精确判定原因, 区别于裸 RuntimeError.
"""
from __future__ import annotations


class LiveTradingDisabledError(RuntimeError):
    """Live trading is disabled — real broker calls (xtquant.order_stock /
    xtquant.cancel_order_stock) are blocked.

    Raised by ``app.security.live_trading_guard.assert_live_trading_allowed``
    when ``settings.LIVE_TRADING_DISABLED=True`` and OVERRIDE 双因素 不全设.

    Bypass requires both:
        LIVE_TRADING_FORCE_OVERRIDE=1
        LIVE_TRADING_OVERRIDE_REASON='<explicit non-empty reason>'

    历史: T1 sprint 链路停止 PR (2026-04-29) 沉淀, 防真金风险 + 防钉钉刷屏.
    撤销: docs/audit/link_paused_2026_04_29.md.

    Application 层而非 Engine 层: paper_broker 物理隔离 (不 import guard).
    """
