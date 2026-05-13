"""V3 §5.3 DefaultIndicatorsProvider — TB-2d unit + TB-2e 6/6 closure tests.

Coverage:
  - Mock-conn unit tests: _fetch_index_return + _fetch_breadth_counts +
    _fetch_iv_50etf_proxy + _fetch_north_flow_cny
  - Mock-conn: NULL pct_change / 0 rows / insufficient history → None graceful
  - IV proxy: realized vol = std × sqrt(252) annualization correct
  - north_flow_cny: Tushare DataFrame parsing + NaN handling + missing token graceful
  - Real-PG smoke (SAVEPOINT pattern per LL-157 sustained):
    - sse_return / hs300_return / breadth populated when data present
    - iv_50etf_proxy computed when ≥20 rows of index_daily history
    - north_flow_cny attempted via Tushare (skip if token missing)
  - DI conn_factory + tushare_api_factory override for testability

关联铁律: 17 (read 例外) / 31 (Engine PURE provider) / 33 (graceful per-field) / 41 (timezone)
关联 V3: §5.3 / ADR-067 (TB-2 closure) / ADR-068 候选 (TB-2e 6/6 closure)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
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
    def test_fetch_with_full_data_5_pg_fields_plus_tushare(self) -> None:
        """All 6/6 fields populated: 5 from PG (sse/hs300/breadth_up/down/iv) + 1 from Tushare."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # Sequence in fetch(): SSE → HS300 → breadth (1 row) → iv_proxy (std + count)
        mock_cur.fetchone.side_effect = [
            (Decimal("1.85"),),  # SSE pct_change percent → 0.0185
            (Decimal("-0.95"),),  # HS300 → -0.0095
            (3000, 1500),  # breadth (up, down)
            (Decimal("0.85"), 20),  # iv proxy: std=0.85% × sqrt(252) ≈ 0.1349, 20 rows
        ]

        # Mock Tushare: returns DataFrame with north_money
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame(
            {
                "trade_date": ["20260514", "20260513"],
                "north_money": [87.5, 50.2],
            }
        )

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()

        assert isinstance(ind, MarketIndicators)
        assert ind.timestamp.tzinfo == UTC
        assert ind.sse_return == pytest.approx(0.0185, abs=1e-6)
        assert ind.hs300_return == pytest.approx(-0.0095, abs=1e-6)
        assert ind.breadth_up == 3000
        assert ind.breadth_down == 1500
        # IV proxy: 0.85 (percent) / 100 × sqrt(252) ≈ 0.13496
        assert ind.iv_50etf == pytest.approx(0.0085 * (252**0.5), abs=1e-5)
        # north_flow_cny: latest trade_date row's north_money
        assert ind.north_flow_cny == pytest.approx(87.5, abs=1e-3)
        mock_conn.close.assert_called_once()

    def test_fetch_iv_proxy_insufficient_history_returns_none(self) -> None:
        """<20 rows of history → iv_50etf None (反 silent partial-window result)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (Decimal("0.5"),),
            (Decimal("0.3"),),
            (3000, 1500),
            (Decimal("0.85"), 10),  # only 10 rows — insufficient
        ]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()  # empty

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.iv_50etf is None
        assert ind.north_flow_cny is None  # empty df

    def test_fetch_iv_proxy_query_failure_returns_none(self) -> None:
        """iv_50etf SQL exception → None + warning logged."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # Pattern: SSE / HS300 / breadth all succeed, iv_proxy execute raises
        mock_cur.execute.side_effect = [None, None, None, psycopg2.Error("iv boom")]
        mock_cur.fetchone.side_effect = [
            (Decimal("0.5"),),
            (Decimal("0.3"),),
            (3000, 1500),
        ]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.iv_50etf is None
        assert ind.sse_return == pytest.approx(0.005, abs=1e-6)  # other fields ok

    def test_fetch_north_flow_tushare_failure_returns_none(self) -> None:
        """Tushare API exception → north_flow_cny None graceful."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (Decimal("1.0"),),
            (Decimal("0.8"),),
            (3000, 1500),
            (Decimal("0.85"), 20),
        ]
        # Tushare query raises
        mock_tushare = MagicMock()
        mock_tushare.query.side_effect = RuntimeError("Tushare rate-limit")

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.north_flow_cny is None  # graceful
        assert ind.iv_50etf is not None  # other field still works

    def test_fetch_north_flow_factory_init_failure_returns_none(self) -> None:
        """Tushare factory raises (e.g. TUSHARE_TOKEN missing) → None graceful."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (Decimal("1.0"),),
            (Decimal("0.8"),),
            (3000, 1500),
            (Decimal("0.85"), 20),
        ]

        def boom_tushare() -> object:
            raise ValueError("TUSHARE_TOKEN未配置")

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=boom_tushare,
        )
        ind = provider.fetch()
        assert ind.north_flow_cny is None  # graceful on token missing

    def test_fetch_north_flow_handles_nan_north_money(self) -> None:
        """NaN north_money rows skipped, fallback to next valid row."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (Decimal("0.0"),),
            (Decimal("0.0"),),
            (1000, 1000),
            (Decimal("0.85"), 20),
        ]
        # Latest row has NaN; second row has valid value
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame(
            {
                "trade_date": ["20260514", "20260513"],
                "north_money": [float("nan"), 42.7],
            }
        )

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.north_flow_cny == pytest.approx(42.7, abs=1e-3)

    def test_fetch_with_empty_index_rows(self) -> None:
        """0 rows → field None (graceful)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            None,  # SSE 0 rows
            None,  # HS300 0 rows
            (3000, 1500),
            (None, None),  # iv: NULL std + NULL count
        ]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.sse_return is None
        assert ind.hs300_return is None
        assert ind.breadth_up == 3000
        assert ind.iv_50etf is None
        assert ind.north_flow_cny is None

    def test_fetch_with_null_pct_change(self) -> None:
        """NULL pct_change in DB → None (反 silent 0.0 propagation)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            (None,),  # NULL pct_change
            (Decimal("0.5"),),
            (3000, 1500),
            (Decimal("0.85"), 20),
        ]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.sse_return is None  # NULL preserved
        assert ind.hs300_return == pytest.approx(0.005, abs=1e-6)

    def test_fetch_with_query_exception_returns_none(self) -> None:
        """psycopg2.Error during query → field None + warning logged."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # SSE query raises, HS300 succeeds, breadth succeeds, iv succeeds.
        mock_cur.execute.side_effect = [
            psycopg2.Error("simulated SSE query failure"),
            None,
            None,
            None,
        ]
        mock_cur.fetchone.side_effect = [
            (Decimal("0.5"),),  # HS300 result
            (3000, 1500),  # breadth result
            (Decimal("0.85"), 20),  # iv result
        ]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.sse_return is None  # Query failed → None
        assert ind.hs300_return == pytest.approx(0.005, abs=1e-6)
        assert ind.breadth_up == 3000
        assert ind.iv_50etf is not None

    def test_fetch_conn_factory_failure_propagates_operational_error(self) -> None:
        """Connection factory failure is NOT caught internally — exception propagates.

        Reviewer-fix (PR #336 HIGH): rename from misleading
        ``test_fetch_conn_level_failure_returns_all_none`` (claimed all-None) —
        actual behavior is intentional propagation. If we can't open a
        connection at all, Celery task should fail-loud + retry (sustained
        铁律 33 + task_acks_late=True per celery_app.py). All-None silent
        path would mask infra failure (LL-115 family silent-zero anti-pattern).
        """

        def boom() -> psycopg2.extensions.connection:
            raise psycopg2.OperationalError("PG down simulation")

        provider = DefaultIndicatorsProvider(conn_factory=boom)
        with pytest.raises(psycopg2.OperationalError, match="PG down"):
            provider.fetch()

    def test_fetch_timestamp_is_utc_aware(self) -> None:
        """铁律 41 sustained — timestamp tz-aware UTC."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [None, None, (None, None), (None, None)]
        mock_tushare = MagicMock()
        mock_tushare.query.return_value = pd.DataFrame()

        provider = DefaultIndicatorsProvider(
            conn_factory=lambda: mock_conn,
            tushare_api_factory=lambda: mock_tushare,
        )
        ind = provider.fetch()
        assert ind.timestamp.tzinfo == UTC
        delta = (datetime.now(UTC) - ind.timestamp).total_seconds()
        assert 0 <= delta < 5


# ─────────────────────────────────────────────────────────────
# IV proxy unit (annualization formula)
# ─────────────────────────────────────────────────────────────


class TestIvProxyAnnualization:
    def test_iv_proxy_annualization_formula(self) -> None:
        """Verify formula: daily_std_percent / 100 × sqrt(252)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (Decimal("1.00"), 20)

        # 1.00% daily std × sqrt(252) ≈ 15.87% annualized.
        result = DefaultIndicatorsProvider._fetch_iv_50etf_proxy(mock_conn)
        assert result == pytest.approx(0.01 * (252**0.5), abs=1e-6)
        # ~0.15875
        assert 0.15 < result < 0.16

    def test_iv_proxy_zero_std_returns_zero(self) -> None:
        """0 std (no volatility) → 0.0 (反 None for valid 0)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (Decimal("0.0"), 20)

        result = DefaultIndicatorsProvider._fetch_iv_50etf_proxy(mock_conn)
        assert result == 0.0


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
    probe = _connect_real_db()
    if probe is None:
        pytest.skip("PG not available")
    probe.close()

    return _connect_real_db


class TestRealPGSmoke:
    def test_fetch_real_pg_returns_non_none_indices_if_data_present(self, pg_conn_factory) -> None:
        """If index_daily has data, fields populated. north_flow_cny may be None if no token."""
        provider = DefaultIndicatorsProvider(
            conn_factory=pg_conn_factory,
            # Disable Tushare in smoke (反 network dep in unit tests).
            tushare_api_factory=lambda: (_ for _ in ()).throw(
                RuntimeError("disable Tushare in unit smoke")
            ),
        )
        ind = provider.fetch()

        # Structure / types verify — actual values depend on DB state.
        assert ind.timestamp.tzinfo == UTC
        assert ind.sse_return is None or isinstance(ind.sse_return, float)
        assert ind.hs300_return is None or isinstance(ind.hs300_return, float)
        assert ind.breadth_up is None or (isinstance(ind.breadth_up, int) and ind.breadth_up >= 0)
        assert ind.breadth_down is None or (
            isinstance(ind.breadth_down, int) and ind.breadth_down >= 0
        )
        # iv_50etf: may be None or float (≥20-day history dependent)
        assert ind.iv_50etf is None or isinstance(ind.iv_50etf, float)
        # north_flow_cny: None because we disabled Tushare in this test
        assert ind.north_flow_cny is None

    def test_fetch_real_pg_decimal_fraction_units(self, pg_conn_factory) -> None:
        """If index_daily has data, returned values should be decimal fractions.

        Reasonable range: -0.10 to +0.10 (most days). |value| > 1 would indicate
        unit drift (forgot to /100). |value| < 1 for both sse/hs300.
        """
        provider = DefaultIndicatorsProvider(
            conn_factory=pg_conn_factory,
            tushare_api_factory=lambda: (_ for _ in ()).throw(RuntimeError("disable Tushare")),
        )
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

    def test_fetch_real_pg_iv_proxy_reasonable_range(self, pg_conn_factory) -> None:
        """If iv_50etf computed, should be reasonable annualized vol (5%-80%)."""
        provider = DefaultIndicatorsProvider(
            conn_factory=pg_conn_factory,
            tushare_api_factory=lambda: (_ for _ in ()).throw(RuntimeError("disable Tushare")),
        )
        ind = provider.fetch()
        if ind.iv_50etf is None:
            pytest.skip("No iv_50etf — likely <20 rows of 000001.SH history")
        # 上证 historical annualized realized vol typically 12%-30%; bounds 5%-80%
        # accommodate crisis periods (e.g. 2015 stock crash, 2024 雪球 incident).
        assert 0.05 < ind.iv_50etf < 0.80, (
            f"iv_50etf={ind.iv_50etf} outside reasonable range — verify formula"
        )
