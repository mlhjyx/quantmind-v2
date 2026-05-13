"""V3 §5.3 MarketIndicators provider — TB-2c sub-PR foundation.

Provides MarketIndicators inputs to MarketRegimeService.classify via Celery Beat:
  - IndicatorsProvider Protocol (duck typing, sustained DI 体例)
  - StubIndicatorsProvider (TB-2c scope — returns all-None, sustained TB-2a design
    codification: all-None acceptable, prompts handle "data unavailable")

Real data source wire — see `default_indicators_provider.DefaultIndicatorsProvider`
for actual TB-2d + TB-2e 6/6 implementation. Per-field source mapping:
  - sse_return / hs300_return: SELECT pct_change FROM index_daily WHERE index_code IN
    ('000001.SH', '000300.SH') ORDER BY trade_date DESC LIMIT 1, then / 100 to convert
    percent → decimal fraction (TB-2d sediment)
  - breadth_up / breadth_down: SUM(CASE WHEN pct_change > 0 / < 0) FROM klines_daily
    WHERE trade_date = latest AND is_suspended = false (TB-2d sediment)
  - north_flow_cny: Tushare moneyflow_hsgt API .north_money (亿 CNY, latest trade_date,
    NaN-skipped); no local moneyflow_hsgt table in current DB schema (TB-2e sediment)
  - iv_50etf: 上证 20-day realized volatility × sqrt(252) annualized as proxy for V3
    §5.3 line 658 "恐慌指数 proxy" (TB-2e sediment); true 50ETF BS-IV pipeline 留 TB-5
    if needed beyond realized vol proxy

Sustains 3-layer pattern (反 hidden coupling):
  - 本模块 = Engine PURE side (provider Protocol + StubIndicatorsProvider for tests / fallback)
  - default_indicators_provider.py = Concrete real-data implementation (TB-2d + TB-2e)
  - app/tasks/market_regime_tasks.py = Beat orchestration (calls provider + service)

关联 V3: §5.3 line 658 (5 input dimensions) / §11.2 (provider location TBD)
关联 ADR: ADR-022 / ADR-029 / ADR-036 / ADR-064 / ADR-066
关联 铁律: 31 (Engine PURE) / 33 (fail-loud) / 41 (timezone-aware)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .interface import MarketIndicators

logger = logging.getLogger(__name__)


class IndicatorsProvider(Protocol):
    """Duck typing protocol — fetch current MarketIndicators snapshot.

    Implementations:
      - StubIndicatorsProvider (TB-2c): all-None data fields, stub for Beat wire-only PR.
      - DefaultIndicatorsProvider (TB-2d/5): real klines_daily + Tushare data source wire.
      - MockIndicatorsProvider (tests): pre-built MarketIndicators via constructor.
    """

    def fetch(self) -> MarketIndicators:
        """Fetch current MarketIndicators (tz-aware timestamp per 铁律 41)."""
        ...


class StubIndicatorsProvider:
    """TB-2c stub — returns all-None numeric fields with tz-aware timestamp.

    Sustains TB-2a design codification (PR #333 MEDIUM 1):
      All-None indicators IS allowed; Bull/Bear/Judge V4-Pro prompts handle
      "data unavailable" path via user_template note. confidence will be
      reduced + regime tends toward Neutral / Transitioning.

    Production fire with this stub WILL surface degenerate baseline 0-data
    inputs in market_regime_log — operator review reflects "wire pending
    real DefaultIndicatorsProvider 留 TB-2d/5".

    沿用 dynamic_threshold_tasks._build_market_indicators stub 体例
    (PR #306, S7 audit fix, sub-PR S7-Beat-wire minimal scope).
    """

    _stub_warned: bool = False

    def fetch(self) -> MarketIndicators:
        """Return MarketIndicators with all numeric fields None + UTC timestamp."""
        from .interface import MarketIndicators  # noqa: PLC0415

        # One-time warning per worker process (反 per-tick log noise).
        if not StubIndicatorsProvider._stub_warned:
            logger.warning(
                "[market-regime] STUB IndicatorsProvider active — all 6 numeric "
                "fields (sse_return / hs300_return / breadth_up / breadth_down / "
                "north_flow_cny / iv_50etf) will be None until DefaultIndicatorsProvider "
                "wired (TB-2d/5). Bull/Bear/Judge V4-Pro prompts handle data-unavailable "
                "path; regime will tend toward Neutral / Transitioning + low confidence."
            )
            StubIndicatorsProvider._stub_warned = True

        return MarketIndicators(timestamp=datetime.now(UTC))
