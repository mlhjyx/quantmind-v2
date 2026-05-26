"""Tests for RealtimeRiskContextBuilder (iter 153 Phase J §1.1 Chunk 1).

Closes MVP 4.5 §3 Chunk 1 test plan: mock Redis, verify RiskContext with
0/1/5 positions + stale-data exception path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.risk.realtime_context_builder import (
    PositionSourceError,
    RealtimeRiskContextBuilder,
)
from backend.qm_platform.risk.interface import Position, RiskContext


def _make_qmt_mock(
    positions: dict[str, int] | None = None,
    nav: dict | None = None,
    prices: dict[str, float] | None = None,
) -> MagicMock:
    """Construct mocked QMTClient with parametrized responses."""
    qmt = MagicMock()
    qmt.get_positions.return_value = positions or {}
    qmt.get_nav.return_value = nav
    qmt.get_prices.return_value = prices or {}
    return qmt


class TestContextBuilder:
    """Verify RiskContext construction across 0/1/5 position states."""

    def test_empty_portfolio_returns_empty_positions(self):
        """0 positions + nav cash = valid post-清仓 state (sustained 27+ days)."""
        qmt = _make_qmt_mock(
            positions={},
            nav={"cash": 993520.66, "total_value": 993520.66, "position_count": 0},
        )
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        ctx = builder.build_context(strategy_id="test-uuid", execution_mode="paper")

        assert isinstance(ctx, RiskContext)
        assert ctx.strategy_id == "test-uuid"
        assert ctx.execution_mode == "paper"
        assert ctx.positions == ()
        assert ctx.portfolio_nav == 993520.66

    def test_single_position_context(self):
        """1-position portfolio produces Position tuple of length 1."""
        qmt = _make_qmt_mock(
            positions={"600519.SH": 100},
            nav={"cash": 50000.0, "total_value": 250000.0, "position_count": 1},
            prices={"600519.SH": 2000.0},
        )
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        ctx = builder.build_context()

        assert len(ctx.positions) == 1
        pos = ctx.positions[0]
        assert isinstance(pos, Position)
        assert pos.code == "600519.SH"
        assert pos.shares == 100
        assert pos.current_price == 2000.0
        assert pos.entry_price == 0.0  # MVP Chunk 1 placeholder
        assert pos.peak_price == 0.0
        assert pos.entry_date is None
        assert ctx.portfolio_nav == 250000.0

    def test_five_position_context(self):
        """5-position portfolio: all codes get prices + tuple is frozen."""
        positions_in = {
            "600519.SH": 100,
            "000001.SZ": 200,
            "688041.SH": 50,
            "300750.SZ": 75,
            "600036.SH": 300,
        }
        prices_in = {code: 100.0 + i * 10 for i, code in enumerate(positions_in)}
        qmt = _make_qmt_mock(
            positions=positions_in,
            nav={"cash": 100000.0, "total_value": 500000.0, "position_count": 5},
            prices=prices_in,
        )
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        ctx = builder.build_context()

        assert len(ctx.positions) == 5
        codes_out = {p.code for p in ctx.positions}
        assert codes_out == set(positions_in.keys())

        # Verify frozen tuple immutability
        with pytest.raises(TypeError):
            ctx.positions[0] = Position(  # type: ignore[index]
                code="X", shares=1, entry_price=0, peak_price=0, current_price=1.0
            )

    def test_invalid_execution_mode_defaults_paper(self):
        """Invalid execution_mode → defaults to 'paper' + logs warning."""
        qmt = _make_qmt_mock(positions={}, nav={"cash": 100.0, "total_value": 100.0})
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        ctx = builder.build_context(execution_mode="invalid-mode")
        assert ctx.execution_mode == "paper"


class TestStaleDataRaises:
    """Stale Redis market data → PositionSourceError per Chunk 1 spec."""

    def test_no_prices_raises(self):
        """When positions exist but ALL prices missing (QMT Data Service down)."""
        qmt = _make_qmt_mock(
            positions={"600519.SH": 100, "000001.SZ": 200},
            nav={"cash": 50000.0, "total_value": 250000.0},
            prices={},  # No prices for any code
        )
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)

        with pytest.raises(PositionSourceError) as exc:
            builder.build_context()
        assert "No market:latest:* prices" in str(exc.value)
        assert "QMT Data Service may be down" in str(exc.value)


class TestRealtimeDict:
    """build_realtime_dict — Chunk 2 placeholder (returns None)."""

    def test_returns_none_in_chunk_1(self):
        """Chunk 1 MVP returns None; Chunk 2 will populate from ring buffer."""
        qmt = _make_qmt_mock()
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        result = builder.build_realtime_dict(positions=())
        assert result is None


class TestNAVFallback:
    """Portfolio NAV computation when nav dict missing total_value."""

    def test_fallback_from_positions_when_nav_missing_total(self):
        """When NAV dict has no total_value, compute from positions × current_price + cash."""
        qmt = _make_qmt_mock(
            positions={"600519.SH": 100, "000001.SZ": 200},
            nav={"cash": 50000.0},  # No total_value key
            prices={"600519.SH": 2000.0, "000001.SZ": 15.0},
        )
        builder = RealtimeRiskContextBuilder(qmt_client=qmt)
        ctx = builder.build_context()

        # 100×2000 + 200×15 + 50000 = 200000 + 3000 + 50000 = 253000
        assert ctx.portfolio_nav == 253000.0
