"""iter 182 — market_regime_service.classify compose_query null-guard tests.

TDD: tests written FIRST against not-yet-extracted helper.
Expected fail: AttributeError on missing `_compose_regime_query` module helper.

Background (iter 177 reviewer P2-1 follow-up):
- market_regime_service.py:154-160 _compose() inline lambda uses `:.4f` /
  unguarded format calls. MarketIndicators allows None for any field per
  interface.py:79-84 (source feed timeout tolerance). None → TypeError at
  format time → silent RAG degradation (build_rag_context outer try/except
  catches it, but RAG context lost for that classify call).

Fix: extract `_compose_regime_query(indicators) -> str` module helper that
mirrors `_format_indicators_for_prompt` agents.py:170-184 null-guard pattern
("null" if None else formatted value). Tested directly here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform.risk.regime.interface import MarketIndicators

SHANGHAI_TZ = UTC  # UTC stand-in for unit test scope


def _make_indicators(
    *,
    sse_return=0.0185,
    hs300_return=0.0212,
    breadth_up=2800,
    breadth_down=1500,
    north_flow_cny=87.5,
    iv_50etf=0.185,
):
    return MarketIndicators(
        timestamp=datetime(2026, 5, 26, 14, 30, tzinfo=SHANGHAI_TZ),
        sse_return=sse_return,
        hs300_return=hs300_return,
        breadth_up=breadth_up,
        breadth_down=breadth_down,
        north_flow_cny=north_flow_cny,
        iv_50etf=iv_50etf,
    )


def test_compose_query_handles_none_north_flow():
    """None float field → 'null' string, no TypeError."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators(north_flow_cny=None)
    query = _compose_regime_query(indicators)

    assert "north_flow=null" in query, f"Null north_flow_cny must render as 'null'; got: {query!r}"
    # Other fields still rendered normally
    assert "SSE=0.0185" in query


def test_compose_query_handles_none_breadth_up():
    """None int field → 'null' string, no TypeError."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators(breadth_up=None)
    query = _compose_regime_query(indicators)

    assert "breadth_up=null" in query
    assert "breadth_down=1500" in query  # other int still rendered


def test_compose_query_handles_none_sse_return():
    """None float field with .4f format → 'null' string, no TypeError."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators(sse_return=None)
    query = _compose_regime_query(indicators)

    assert "SSE=null" in query


def test_compose_query_handles_all_none_fields():
    """Degenerate case: ALL numeric fields None → all 'null' substrings, no TypeError."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators(
        sse_return=None,
        hs300_return=None,
        breadth_up=None,
        breadth_down=None,
        north_flow_cny=None,
        iv_50etf=None,
    )
    query = _compose_regime_query(indicators)

    # Should not raise + each field 'null'
    assert "SSE=null" in query
    assert "HS300=null" in query
    assert "breadth_up=null" in query
    assert "breadth_down=null" in query
    assert "north_flow=null" in query
    assert "iv_50etf=null" in query


def test_compose_query_happy_path_uses_real_values():
    """Regression guard: non-None values render formatted (not 'null')."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators()  # default non-None values
    query = _compose_regime_query(indicators)

    assert "SSE=0.0185" in query
    assert "HS300=0.0212" in query
    assert "breadth_up=2800" in query
    assert "breadth_down=1500" in query
    assert "north_flow=87.50" in query  # .2f format
    assert "iv_50etf=0.1850" in query
    # Timestamp included
    assert "2026-05-26" in query


def test_compose_query_returns_string():
    """Helper must return str type (not bytes / not None)."""
    from app.services.risk.market_regime_service import _compose_regime_query

    indicators = _make_indicators()
    result = _compose_regime_query(indicators)
    assert isinstance(result, str)
    assert len(result) > 0
