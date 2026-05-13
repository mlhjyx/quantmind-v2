"""V3 §5.3 DefaultIndicatorsProvider — TB-2d unit + real-PG smoke tests.

Coverage:
  - Mock-conn unit tests: _fetch_index_return + _fetch_breadth_counts construction
  - Mock-conn: NULL pct_change / 0 rows → None graceful
  - Real-PG smoke (SAVEPOINT pattern per LL-157 sustained):
    - sse_return / hs300_return populated when index_daily has rows
    - breadth_up / breadth_down populated when klines_daily has rows
    - north_flow_cny / iv_50etf always None (TB-2d defers to TB-5)
  - DI conn_factory override for testability

关联铁律: 17 (read 例外) / 31 (Engine PURE provider) / 33 (graceful per-field) / 41 (timezone)
关联 V3: §5.3 / ADR-067 (TB-2 closure)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import psycopg2
import pytest

from backend.qm_platform.risk.regime import MarketIndicators
from backend.qm_platform.risk.regime.default_indicators_provider import (
    DefaultIndicatorsProvider,
)

# ─────────────────────────────────────────────────────────────
# Mock-conn unit tests (反 real DB required)
# ─────────────────────────────────────────────────────────────


class TestMockConn:
    def test_fetch_with_full_data(self) -> None:
        """All 4 wired fields populated from mock query results."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # cursor returned in 4 separate calls (sse / hs300 / breadth single)
        # Sequence: SELECT sse → SELECT hs300 → SELECT breadth (1 cursor call total = 3 cursor opens).
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (Decimal("1.85"),),  # SSE pct_change percent — should /100 → 0.0185
            (Decimal("-0.95"),),  # HS300 pct_change percent → -0.0095
            (3000, 1500),  # breadth (up, down)
        ]

        provider = DefaultIndicatorsProvider(conn_factory=lambda: mock_conn)
        ind = provider.fetch()

        assert isinstance(ind, MarketIndicators)
        assert ind.timestamp.tzinfo == UTC
        assert ind.sse_return == pytest.approx(0.0185, abs=1e-6)
        assert ind.hs300_return == pytest.approx(-0.0095, abs=1e-6)
        assert ind.breadth_up == 3000
        assert ind.breadth_down == 1500
        # Deferred fields per TB-2d scope:
        assert ind.north_flow_cny is None
        assert ind.iv_50etf is None
        mock_conn.close.assert_called_once()

    def test_fetch_with_empty_index_rows(self) -> None:
        """0 rows → field None (graceful)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            None,  # SSE 0 rows
            None,  # HS300 0 rows
            (3000, 1500),
        ]

        provider = DefaultIndicatorsProvider(conn_factory=lambda: mock_conn)
        ind = provider.fetch()
        assert ind.sse_return is None
        assert ind.hs300_return is None
        assert ind.breadth_up == 3000

    def test_fetch_with_null_pct_change(self) -> None:
        """NULL pct_change in DB → None (反 silent 0.0 propagation)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (None,),  # NULL pct_change
            (Decimal("0.5"),),
            (3000, 1500),
        ]

        provider = DefaultIndicatorsProvider(conn_factory=lambda: mock_conn)
        ind = provider.fetch()
        assert ind.sse_return is None  # NULL preserved
        assert ind.hs300_return == pytest.approx(0.005, abs=1e-6)

    def test_fetch_with_query_exception_returns_none(self) -> None:
        """psycopg2.Error during query → field None + warning logged."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # SSE query raises, HS300 succeeds, breadth succeeds.
        mock_cur.execute.side_effect = [
            psycopg2.Error("simulated SSE query failure"),
            None,
            None,
        ]
        mock_cur.fetchone.side_effect = [
            (Decimal("0.5"),),  # HS300 result
            (3000, 1500),  # breadth result
        ]

        provider = DefaultIndicatorsProvider(conn_factory=lambda: mock_conn)
        ind = provider.fetch()
        assert ind.sse_return is None  # Query failed → None
        assert ind.hs300_return == pytest.approx(0.005, abs=1e-6)
        assert ind.breadth_up == 3000

    def test_fetch_conn_level_failure_returns_all_none(self) -> None:
        """Conn factory raises → all fields None + None ts not crashed."""

        def boom() -> psycopg2.extensions.connection:
            raise psycopg2.OperationalError("PG down simulation")

        provider = DefaultIndicatorsProvider(conn_factory=boom)
        # The exception is propagated out of self._conn_factory() — not caught
        # internally since we can't even open a connection. Verify the exception
        # type matches expectation (caller responsible for handling).
        with pytest.raises(psycopg2.OperationalError, match="PG down"):
            provider.fetch()

    def test_fetch_timestamp_is_utc_aware(self) -> None:
        """铁律 41 sustained — timestamp tz-aware UTC."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [None, None, (None, None)]

        provider = DefaultIndicatorsProvider(conn_factory=lambda: mock_conn)
        ind = provider.fetch()
        assert ind.timestamp.tzinfo == UTC
        delta = (datetime.now(UTC) - ind.timestamp).total_seconds()
        assert 0 <= delta < 5


# ─────────────────────────────────────────────────────────────
# Real-PG smoke (SAVEPOINT pattern sustained per LL-157)
# ─────────────────────────────────────────────────────────────


def _connect_real_db() -> psycopg2.extensions.connection | None:
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415

        return get_sync_conn()
    except Exception:
        return None


@pytest.fixture
def pg_conn_factory():
    """Real PG conn factory — skip if unavailable.

    Returns a callable that opens a fresh conn each call (sustained
    DefaultIndicatorsProvider per-fetch lifecycle: factory→fetch→close).
    Teardown: nothing — provider closes each conn it opens.
    """
    # First-call check: verify PG is reachable before yielding factory.
    probe = _connect_real_db()
    if probe is None:
        pytest.skip("PG not available")
    probe.close()  # close probe — provider opens fresh below

    return _connect_real_db


class TestRealPGSmoke:
    def test_fetch_real_pg_returns_non_none_indices_if_data_present(
        self, pg_conn_factory
    ) -> None:
        """If index_daily has data for 000001.SH and 000300.SH, fields populated."""
        provider = DefaultIndicatorsProvider(conn_factory=pg_conn_factory)
        ind = provider.fetch()

        # Just verify the structure / types — actual values depend on DB state.
        assert ind.timestamp.tzinfo == UTC
        # sse_return / hs300_return: either None (no data) or float decimal fraction.
        assert ind.sse_return is None or isinstance(ind.sse_return, float)
        assert ind.hs300_return is None or isinstance(ind.hs300_return, float)
        # breadth_up / breadth_down: either None or non-negative int.
        assert ind.breadth_up is None or (isinstance(ind.breadth_up, int) and ind.breadth_up >= 0)
        assert ind.breadth_down is None or (
            isinstance(ind.breadth_down, int) and ind.breadth_down >= 0
        )
        # Deferred fields always None per TB-2d scope.
        assert ind.north_flow_cny is None
        assert ind.iv_50etf is None

    def test_fetch_real_pg_decimal_fraction_units(self, pg_conn_factory) -> None:
        """If index_daily has data, returned values should be decimal fractions.

        Reasonable range: -0.10 to +0.10 (most days). |value| > 1 would indicate
        unit drift (forgot to /100). |value| < 1 for both sse/hs300.
        """
        provider = DefaultIndicatorsProvider(conn_factory=pg_conn_factory)
        ind = provider.fetch()

        for field_name, value in (
            ("sse_return", ind.sse_return),
            ("hs300_return", ind.hs300_return),
        ):
            if value is None:
                continue
            assert abs(value) < 1.0, (
                f"{field_name}={value} likely percent-not-decimal "
                f"drift (should be e.g. 0.0185 not 1.85). "
                f"Verify DefaultIndicatorsProvider._fetch_index_return /100 division."
            )
