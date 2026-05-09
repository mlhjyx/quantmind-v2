"""Unit tests for FundamentalContextService (sub-PR 14 sediment per ADR-053).

scope (沿用 sub-PR 11b test_announcement_processor + sub-PR 13 体例 precedent):
- ingest() full path with mocked AkshareValuationFetcher + conn
- UPSERT INSERT path verify (sql call_args + JSONB serialization)
- ON CONFLICT preserves 7 other dimensions (反 silent NULL overwrite per ADR-022)
- 0 conn.commit (铁律 32 sustained, caller 真值 事务边界管理者)
- FundamentalFetchError propagates from fetcher (反 silent skip per 铁律 33)
- FundamentalIngestStats schema correct

关联铁律: 17/31/32/33/41/45
关联 ADR: ADR-053 (V3 §S4 (minimal) architecture)
关联 LL: LL-144 (S4 minimal scope sub-PR 14 sediment)
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.app.services.fundamental_context_service import (
    FundamentalContextService,
    FundamentalIngestStats,
)
from backend.qm_platform.data.fundamental.akshare_valuation import (
    FundamentalFetchError,
    ValuationContext,
)


def _make_valuation_context(
    *,
    symbol_id: str = "600519",
    valuation_date: date | None = None,
    pe_ttm: float = 20.79,
) -> ValuationContext:
    return ValuationContext(
        date=valuation_date or date(2026, 5, 8),
        symbol_id=symbol_id,
        valuation={
            "pe_ttm": pe_ttm,
            "pe_static": 20.89,
            "pb": 6.35,
            "peg": -5.02,
            "pcf": 21.59,
            "ps": 9.81,
            "market_cap_total": 1.72e12,
            "market_cap_float": 1.72e12,
        },
        fetch_cost=Decimal("0"),
        fetch_latency_ms=15,
    )


def _make_mock_conn() -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    return conn


# §1 ingest() full success path


class TestFundamentalContextServiceIngest:
    """FundamentalContextService.ingest — full orchestration with mocked fetcher + conn."""

    def test_ingest_valuation_upsert_success(self) -> None:
        ctx = _make_valuation_context()
        fetcher = MagicMock()
        fetcher.fetch = MagicMock(return_value=ctx)
        conn = _make_mock_conn()

        service = FundamentalContextService(fetcher=fetcher)
        stats = service.ingest(symbol_id="600519", conn=conn)

        # Stats correct
        assert stats == FundamentalIngestStats(
            symbol_id="600519",
            date=date(2026, 5, 8),
            valuation_filled=True,
            fetch_latency_ms=15,
        )

        # fetcher called keyword-only
        fetcher.fetch.assert_called_once_with(symbol_id="600519")

        # cursor.execute called once with INSERT ... ON CONFLICT
        cur = conn.cursor()
        assert cur.execute.call_count == 1
        sql_arg, params = cur.execute.call_args[0]
        assert "INSERT INTO fundamental_context_daily" in sql_arg
        assert "ON CONFLICT (symbol_id, date) DO UPDATE" in sql_arg
        # params: (symbol_id, date, valuation_json, fetch_cost, fetch_latency_ms)
        assert params[0] == "600519"
        assert params[1] == date(2026, 5, 8)
        # valuation JSON is dumped string
        valuation_dict = json.loads(params[2])
        assert valuation_dict["pe_ttm"] == 20.79
        assert valuation_dict["pb"] == 6.35
        assert params[3] == Decimal("0")
        assert params[4] == 15

    def test_ingest_zero_conn_commit(self) -> None:
        """Sustained 铁律 32: caller 真值 事务边界 — service NEVER calls conn.commit() / rollback()."""
        ctx = _make_valuation_context()
        fetcher = MagicMock()
        fetcher.fetch = MagicMock(return_value=ctx)
        conn = _make_mock_conn()

        service = FundamentalContextService(fetcher=fetcher)
        service.ingest(symbol_id="600519", conn=conn)

        conn.commit.assert_not_called()
        conn.rollback.assert_not_called()

    def test_ingest_fetcher_error_propagates(self) -> None:
        """Sustained 铁律 33 fail-loud: FundamentalFetchError propagates (反 silent skip)."""
        fetcher = MagicMock()
        fetcher.fetch = MagicMock(
            side_effect=FundamentalFetchError(
                source="akshare_valuation",
                message="HTTP 500 EM backend timeout",
            )
        )
        conn = _make_mock_conn()

        service = FundamentalContextService(fetcher=fetcher)

        with pytest.raises(FundamentalFetchError, match=r"HTTP 500"):
            service.ingest(symbol_id="600519", conn=conn)

        # No INSERT attempted on fetch fail
        cur = conn.cursor()
        cur.execute.assert_not_called()

    def test_ingest_different_symbol_id(self) -> None:
        ctx = _make_valuation_context(symbol_id="000001")
        fetcher = MagicMock()
        fetcher.fetch = MagicMock(return_value=ctx)
        conn = _make_mock_conn()

        service = FundamentalContextService(fetcher=fetcher)
        stats = service.ingest(symbol_id="000001", conn=conn)

        assert stats.symbol_id == "000001"
        fetcher.fetch.assert_called_once_with(symbol_id="000001")


# §2 FundamentalIngestStats dataclass


def test_fundamental_ingest_stats_frozen() -> None:
    stats = FundamentalIngestStats(
        symbol_id="600519",
        date=date(2026, 5, 8),
        valuation_filled=True,
        fetch_latency_ms=15,
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises((FrozenInstanceError, AttributeError)):
        stats.symbol_id = "000001"  # type: ignore[misc]


# §3 SQL UPSERT preserves 7 other dimensions


def test_upsert_only_updates_valuation_dimensions() -> None:
    """Sustained ADR-022 反 silent overwrite: ON CONFLICT updates only valuation/fetch_cost/
    fetch_latency_ms/fetched_at — 7 other JSONB dimensions (growth/earnings/...) preserved."""
    ctx = _make_valuation_context()
    fetcher = MagicMock()
    fetcher.fetch = MagicMock(return_value=ctx)
    conn = _make_mock_conn()

    service = FundamentalContextService(fetcher=fetcher)
    service.ingest(symbol_id="600519", conn=conn)

    cur = conn.cursor()
    sql_arg, _ = cur.execute.call_args[0]

    # SET clause must NOT include growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements
    set_clause_start = sql_arg.find("DO UPDATE SET")
    set_clause = sql_arg[set_clause_start:]
    assert "growth" not in set_clause
    assert "earnings" not in set_clause
    assert "institution" not in set_clause
    assert "capital_flow" not in set_clause
    assert "dragon_tiger" not in set_clause
    assert "boards" not in set_clause
    assert "announcements" not in set_clause
    # SET clause must include valuation + fetch_cost + fetch_latency_ms + fetched_at
    assert "valuation" in set_clause
    assert "fetch_cost" in set_clause
    assert "fetch_latency_ms" in set_clause
    assert "fetched_at" in set_clause
