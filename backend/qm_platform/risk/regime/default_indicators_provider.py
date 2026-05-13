"""V3 §5.3 DefaultIndicatorsProvider — TB-2d real data wire + TB-2e 6/6 closure.

Replaces TB-2c StubIndicatorsProvider (all-None) with real PG queries + Tushare API:
  - sse_return: index_daily WHERE index_code = '000001.SH' (上证综指, pct_change → /100)
  - hs300_return: index_daily WHERE index_code = '000300.SH' (沪深 300, pct_change → /100)
  - breadth_up / breadth_down: COUNT klines_daily WHERE pct_change > 0 / < 0 + is_suspended=false
  - north_flow_cny: Tushare moneyflow_hsgt API (TB-2e — net north flow in 亿 CNY)
  - iv_50etf: 上证 20-day realized volatility × sqrt(252) proxy (TB-2e — V3 §5.3 line 658
    explicitly notes "恐慌指数 proxy", realized vol is the conventional fear gauge proxy)

Graceful degradation per field — if any individual query / API call fails / returns 0 rows,
that field returns None (sustained TB-2a design codification: all-None tolerated, prompts
handle "data unavailable" path).

DI 体例 (sustained IndicatorsProvider Protocol):
    from backend.qm_platform.risk.regime.default_indicators_provider import DefaultIndicatorsProvider

    provider = DefaultIndicatorsProvider()  # default uses get_sync_conn + TushareAPI
    indicators = provider.fetch()  # tz-aware UTC ts + 6/6 numeric fields wired

Caller (TB-2c market_regime_tasks._get_provider) swaps StubIndicatorsProvider →
DefaultIndicatorsProvider via simple constructor change.

关联 V3: §5.3 (Bull/Bear regime input 6 dimensions)
关联 ADR: ADR-022 / ADR-029 / ADR-036 / ADR-064 / ADR-066 / ADR-067 (TB-2 closure cumulative)
  / ADR-068 (TB-2e 6/6 fields wire closure)
关联 铁律: 17 (DataPipeline read 例外 — pure SELECT + Tushare read API, no INSERT) /
  31 (Engine PURE side) / 33 (fail-loud per-field with caller-visible None) / 41 (timezone)
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg2.extensions

    from .interface import MarketIndicators

logger = logging.getLogger(__name__)

# Index codes per V3 §5.3 line 658 — 上证综指 + 沪深 300.
_SSE_INDEX_CODE: str = "000001.SH"
_HS300_INDEX_CODE: str = "000300.SH"

# IV 50ETF proxy parameters — 20-day rolling std × sqrt(252) annualized
# realized vol (上证综指 close-to-close). 沿用 V3 §5.3 line 658 explicit
# "恐慌指数 proxy" — realized vol IS the conventional fear gauge proxy
# (反 build BS-IV pipeline for real 50ETF option chain, scope 留 TB-5 future).
_IV_PROXY_WINDOW_DAYS: int = 20
_TRADING_DAYS_PER_YEAR: int = 252


class DefaultIndicatorsProvider:
    """V3 §5.3 real-data IndicatorsProvider — queries index_daily + klines_daily + Tushare hsgt.

    TB-2d initial wire (4/6) + TB-2e closure (6/6).

    Fields wired:
      - sse_return: index_daily['000001.SH'].pct_change / 100
      - hs300_return: index_daily['000300.SH'].pct_change / 100
      - breadth_up: COUNT klines_daily WHERE pct_change > 0 AND is_suspended=false
      - breadth_down: COUNT klines_daily WHERE pct_change < 0 AND is_suspended=false
      - north_flow_cny: Tushare moneyflow_hsgt.north_money (latest trade_date, 亿 CNY)
      - iv_50etf: 上证 20-day realized volatility × sqrt(252) annualized (proxy per V3 §5.3 line 658)

    Per-field graceful degradation: query / API failure → None (沿用 TB-2a
    design: all-None acceptable, prompts handle "data unavailable" path).
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg2.extensions.connection] | None = None,
        tushare_api_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Initialize provider with optional conn + Tushare factory DI for testability.

        Args:
            conn_factory: callable returning psycopg2 connection. If None,
                uses app.services.db.get_sync_conn (production default).
            tushare_api_factory: callable returning TushareAPI instance. If None,
                uses app.data_fetcher.tushare_api.TushareAPI (production default).
                Lazy-init avoids TUSHARE_TOKEN check at import time.
        """
        if conn_factory is None:
            from app.services.db import get_sync_conn  # noqa: PLC0415

            conn_factory = get_sync_conn
        self._conn_factory = conn_factory

        # Tushare factory deferred — TushareAPI() raises if token missing,
        # don't fail provider construction (allow caller to operate w/o Tushare).
        self._tushare_api_factory = tushare_api_factory

    def fetch(self) -> MarketIndicators:
        """Query PG + Tushare for current market state → build MarketIndicators.

        Returns:
            MarketIndicators with 6/6 numeric fields wired + UTC timestamp.
            Failed-field path returns None for that field (graceful degradation).
        """
        from .interface import MarketIndicators  # noqa: PLC0415

        # Initialize all fields to None — fields stay None on query failure.
        sse_return: float | None = None
        hs300_return: float | None = None
        breadth_up: int | None = None
        breadth_down: int | None = None
        iv_50etf: float | None = None

        conn = self._conn_factory()
        try:
            sse_return = self._fetch_index_return(conn, _SSE_INDEX_CODE)
            hs300_return = self._fetch_index_return(conn, _HS300_INDEX_CODE)
            breadth_up, breadth_down = self._fetch_breadth_counts(conn)
            iv_50etf = self._fetch_iv_50etf_proxy(conn)
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

        # Tushare API call separate (independent failure mode from PG)
        north_flow_cny = self._fetch_north_flow_cny()

        return MarketIndicators(
            timestamp=datetime.now(UTC),
            sse_return=sse_return,
            hs300_return=hs300_return,
            breadth_up=breadth_up,
            breadth_down=breadth_down,
            north_flow_cny=north_flow_cny,
            iv_50etf=iv_50etf,
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

    @staticmethod
    def _fetch_iv_50etf_proxy(conn: psycopg2.extensions.connection) -> float | None:
        """Compute 上证 20-day realized volatility × sqrt(252) → IV proxy.

        V3 §5.3 line 658 explicit "50ETF 期权 IV (恐慌指数 proxy)" — realized volatility
        IS the conventional fear gauge proxy (反 build true BS-IV pipeline for option
        chain, that scope 留 TB-5 future when option data feed decided).

        Formula: std_dev(pct_change_decimal, 20-day rolling) × sqrt(252)
                 e.g. 1% daily std → 0.01 × sqrt(252) ≈ 0.159 (= 15.9% annualized IV)

        Note: index_daily.pct_change stored as percent (1.85 = +1.85%), so we divide
        by 100 for decimal fraction before computing std.

        Returns annualized realized vol as decimal fraction (e.g. 0.18 for 18%).
        Returns None on <20 valid rows / query failure.
        """
        try:
            with conn.cursor() as cur:
                # Use SQL window aggregate — stddev_samp over last 20 rows.
                # SAMPLE std (n-1 divisor) is the convention for realized vol estimation.
                cur.execute(
                    """
                    WITH recent AS (
                        SELECT pct_change
                          FROM index_daily
                         WHERE index_code = %s
                           AND pct_change IS NOT NULL
                         ORDER BY trade_date DESC
                         LIMIT %s
                    )
                    SELECT stddev_samp(pct_change), COUNT(*) FROM recent
                    """,
                    (_SSE_INDEX_CODE, _IV_PROXY_WINDOW_DAYS),
                )
                row = cur.fetchone()
                if row is None or row[0] is None or row[1] is None:
                    return None
                std_pct, n = row
                if int(n) < _IV_PROXY_WINDOW_DAYS:
                    # Insufficient history — return None reflects "data unavailable"
                    # 反 silent partial-window result (could misrepresent regime).
                    return None
                # std_pct is percent (e.g. 0.85 = 0.85% daily std) → /100 for decimal.
                # Annualize: × sqrt(252) ≈ 15.87.
                annualized = (float(std_pct) / 100.0) * (_TRADING_DAYS_PER_YEAR**0.5)
                return annualized
        except Exception as e:  # noqa: BLE001
            logger.warning("[default-indicators] failed to compute iv_50etf proxy: %s", e)
            return None

    def _fetch_north_flow_cny(self) -> float | None:
        """Query Tushare moneyflow_hsgt for latest trade_date north flow (亿 CNY).

        Uses TushareAPI wrapper (per-API sleep + retry) when available.
        Returns None on:
          - TUSHARE_TOKEN missing
          - Tushare API failure (network / rate limit / etc)
          - 0 rows returned
          - NULL north_money column

        Tushare schema reference:
          moneyflow_hsgt(start_date, end_date) → DataFrame with columns:
            trade_date, ggt_ss, ggt_sz, hgt, sgt, north_money, south_money
          north_money: 北向资金净流入 in 亿 CNY (positive = inflow, negative = outflow).

        Per-call latency ~0.35s (Tushare API rate limit). Beat fires 3/day = ~1s
        total additional latency — acceptable.
        """
        try:
            if self._tushare_api_factory is not None:
                api = self._tushare_api_factory()
            else:
                # Lazy import — TushareAPI() raises if TUSHARE_TOKEN missing.
                from app.data_fetcher.tushare_api import (  # noqa: PLC0415
                    TushareAPI,
                )

                api = TushareAPI()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[default-indicators] TushareAPI init failed (likely TUSHARE_TOKEN "
                "missing): %s; north_flow_cny → None",
                e,
            )
            return None

        try:
            # Query last 7 days, take latest non-null row. Tushare moneyflow_hsgt
            # returns dates in YYYYMMDD format; sort by trade_date DESC.
            from datetime import date, timedelta  # noqa: PLC0415

            today = date.today()
            start = today - timedelta(days=7)
            df = api.query(
                "moneyflow_hsgt",
                start_date=start.strftime("%Y%m%d"),
                end_date=today.strftime("%Y%m%d"),
            )
            if df is None or df.empty:
                logger.info(
                    "[default-indicators] moneyflow_hsgt returned empty for "
                    "%s~%s; north_flow_cny → None",
                    start,
                    today,
                )
                return None
            # Sort by trade_date DESC to get latest row first.
            df_sorted = df.sort_values("trade_date", ascending=False)
            for _, row in df_sorted.iterrows():
                nm = row.get("north_money")
                if nm is not None and not _is_nan(nm):
                    return float(nm)
            logger.info(
                "[default-indicators] moneyflow_hsgt all rows have NULL north_money; → None"
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[default-indicators] Tushare moneyflow_hsgt fetch failed: %s; "
                "north_flow_cny → None",
                e,
            )
            return None


def _is_nan(x: Any) -> bool:
    """Pandas NaN detection without numpy/pandas import in hot path."""
    try:
        return x != x  # NaN != NaN (float NaN identity check)
    except Exception:  # noqa: BLE001
        return False
