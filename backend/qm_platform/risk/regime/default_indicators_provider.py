"""V3 §5.3 DefaultIndicatorsProvider — TB-2d real data source wire.

Replaces TB-2c StubIndicatorsProvider (all-None) with real PG queries:
  - sse_return: index_daily WHERE index_code = '000001.SH' (上证综指, pct_change → /100)
  - hs300_return: index_daily WHERE index_code = '000300.SH' (沪深 300, pct_change → /100)
  - breadth_up / breadth_down: COUNT klines_daily WHERE pct_change > 0 / < 0 + is_suspended=false
  - north_flow_cny: None (留 TB-5 — no moneyflow_hsgt table in current DB schema)
  - iv_50etf: None (留 TB-5 — no 50ETF IV data source decision)

Graceful degradation per field — if any individual query fails / returns 0 rows,
that field returns None (sustained TB-2a design codification: all-None tolerated).

DI 体例 (sustained IndicatorsProvider Protocol):
    from backend.qm_platform.risk.regime.default_indicators_provider import DefaultIndicatorsProvider

    provider = DefaultIndicatorsProvider()  # default uses get_sync_conn factory
    indicators = provider.fetch()  # tz-aware UTC ts + real numeric fields

Caller (TB-2c market_regime_tasks._get_provider) can swap StubIndicatorsProvider →
DefaultIndicatorsProvider via simple constructor change.

关联 V3: §5.3 (Bull/Bear regime input 6 dimensions)
关联 ADR: ADR-022 / ADR-029 / ADR-036 / ADR-064 / ADR-066 / ADR-067 (TB-2 closure cumulative)
关联 铁律: 17 (DataPipeline read 例外 — pure SELECT, no INSERT) / 31 (Engine PURE)
  / 33 (fail-loud per-field with caller-visible None) / 41 (timezone)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg2.extensions

    from .interface import MarketIndicators

logger = logging.getLogger(__name__)

# Index codes per V3 §5.3 line 658 — 上证综指 + 沪深 300.
_SSE_INDEX_CODE: str = "000001.SH"
_HS300_INDEX_CODE: str = "000300.SH"


class DefaultIndicatorsProvider:
    """V3 §5.3 real-data IndicatorsProvider — queries index_daily + klines_daily.

    TB-2d real wire replacing TB-2c StubIndicatorsProvider.

    Fields wired (4/6):
      - sse_return: index_daily['000001.SH'].pct_change / 100
      - hs300_return: index_daily['000300.SH'].pct_change / 100
      - breadth_up: COUNT klines_daily WHERE pct_change > 0 AND is_suspended=false
      - breadth_down: COUNT klines_daily WHERE pct_change < 0 AND is_suspended=false

    Fields deferred (2/6) per V3 §5.3 — 留 TB-5 batch:
      - north_flow_cny: no moneyflow_hsgt table (only moneyflow_daily per-stock)
      - iv_50etf: no 50ETF option IV data source decision

    Per-field graceful degradation: query failure / 0 rows → None (沿用 TB-2a
    design: all-None acceptable, prompts handle "data unavailable" path).
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg2.extensions.connection] | None = None,
    ) -> None:
        """Initialize provider with optional conn factory DI for testability.

        Args:
            conn_factory: callable returning psycopg2 connection. If None,
                uses app.services.db.get_sync_conn (production default).
        """
        if conn_factory is None:
            from app.services.db import get_sync_conn  # noqa: PLC0415

            conn_factory = get_sync_conn
        self._conn_factory = conn_factory

    def fetch(self) -> MarketIndicators:
        """Query PG for current market state + build MarketIndicators.

        Returns:
            MarketIndicators with 4/6 numeric fields wired + UTC timestamp.
            Failed-field path returns None for that field (沿用 graceful degradation).
        """
        from .interface import MarketIndicators  # noqa: PLC0415

        # Initialize all fields to None — fields stay None on query failure.
        sse_return: float | None = None
        hs300_return: float | None = None
        breadth_up: int | None = None
        breadth_down: int | None = None

        conn = self._conn_factory()
        try:
            sse_return = self._fetch_index_return(conn, _SSE_INDEX_CODE)
            hs300_return = self._fetch_index_return(conn, _HS300_INDEX_CODE)
            breadth_up, breadth_down = self._fetch_breadth_counts(conn)
        except Exception as e:  # noqa: BLE001
            # Catch-all 反 partial corruption — log + return what we have.
            # Individual field methods already trap their own exceptions; this
            # is defense-in-depth for connection-level failures (e.g. PG down).
            logger.warning(
                "[default-indicators] conn-level failure during fetch: %s; "
                "returning partial / all-None indicators",
                e,
            )
        finally:
            with contextlib.suppress(Exception):
                conn.close()

        return MarketIndicators(
            timestamp=datetime.now(UTC),
            sse_return=sse_return,
            hs300_return=hs300_return,
            breadth_up=breadth_up,
            breadth_down=breadth_down,
            north_flow_cny=None,  # 留 TB-5 (no moneyflow_hsgt table)
            iv_50etf=None,  # 留 TB-5 (no 50ETF IV data source)
        )

    @staticmethod
    def _fetch_index_return(conn: psycopg2.extensions.connection, index_code: str) -> float | None:
        """Query latest index_daily.pct_change for the given index code.

        Returns decimal fraction (e.g. 0.0185 for +1.85%) — index_daily stores
        pct_change in percent (1.85), so divide by 100.

        Returns None on query failure / 0 rows / NULL pct_change.
        """
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pct_change FROM index_daily "
                    "WHERE index_code = %s "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (index_code,),
                )
                row = cur.fetchone()
                if row is None or row[0] is None:
                    return None
                # pct_change is NUMERIC; convert Decimal → float decimal fraction.
                return float(row[0]) / 100.0
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[default-indicators] failed to fetch index_return for %s: %s",
                index_code,
                e,
            )
            return None

    @staticmethod
    def _fetch_breadth_counts(
        conn: psycopg2.extensions.connection,
    ) -> tuple[int | None, int | None]:
        """Query breadth_up / breadth_down counts from latest klines_daily trade_date.

        Filter: is_suspended=false (suspended stocks have 0 pct_change → noise).
        Note: is_st=true stocks ARE included (V3 §5.3 全市场 sustained — ST stocks
        contribute to crisis breadth signals).

        Returns (breadth_up, breadth_down). Either may be None on query failure.
        """
        try:
            with conn.cursor() as cur:
                # Use latest trade_date as anchor (反 stale partial-day breadth).
                cur.execute(
                    """
                    WITH latest AS (
                        SELECT MAX(trade_date) AS d FROM klines_daily
                    )
                    SELECT
                        SUM(CASE WHEN pct_change > 0 THEN 1 ELSE 0 END) AS up,
                        SUM(CASE WHEN pct_change < 0 THEN 1 ELSE 0 END) AS down
                      FROM klines_daily k, latest
                     WHERE k.trade_date = latest.d
                       AND k.is_suspended = false
                       AND k.pct_change IS NOT NULL
                    """
                )
                row = cur.fetchone()
                if row is None:
                    return None, None
                up = int(row[0]) if row[0] is not None else None
                down = int(row[1]) if row[1] is not None else None
                return up, down
        except Exception as e:  # noqa: BLE001
            logger.warning("[default-indicators] failed to fetch breadth counts: %s", e)
            return None, None
