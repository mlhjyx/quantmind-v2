"""MVP 4.2 Performance Attribution (qm_platform/eval/attribution.py) shape tests (iter 59).

iter 59 covers dataclass + protocol shape only; iter 60+ adds implementation tests.

Note: test filename `test_qm_platform_attribution.py` to avoid conflict with
existing `test_attribution.py` (research Brinson-Fachler module).
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.qm_platform.eval.attribution import (
    AttributionEngine,
    DailyAttribution,
    RegimeInfo,
    residual_exceeds_threshold,
)


def test_regime_info_dataclass_shape():
    """RegimeInfo: detected str + expected/actual perf bps."""
    r = RegimeInfo(detected="bull", expected_perf_bps=15.0, actual_perf_bps=12.5)
    assert r.detected == "bull"
    assert r.expected_perf_bps == 15.0
    assert r.actual_perf_bps == 12.5


def test_regime_info_frozen():
    """RegimeInfo frozen — 反 silent mutation."""
    r = RegimeInfo(detected="sideways", expected_perf_bps=0.0, actual_perf_bps=0.0)
    with pytest.raises(Exception):  # FrozenInstanceError
        r.detected = "bull"  # type: ignore[misc]


def test_daily_attribution_minimal():
    """DailyAttribution minimal constructor with defaults."""
    a = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="paper-strategy-uuid",
        execution_mode="paper",
        nav_change_pct=0.012,
    )
    assert a.trade_date == date(2026, 5, 25)
    assert a.execution_mode == "paper"
    assert a.nav_change_pct == 0.012
    assert a.by_factor == {}
    assert a.by_sector == {}
    assert a.by_regime is None
    assert a.by_cost == {}
    assert a.alpha_vs_benchmark == 0.0
    assert a.unexplained_residual == 0.0


def test_daily_attribution_full():
    """DailyAttribution all fields populated."""
    a = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="paper-strategy-uuid",
        execution_mode="paper",
        nav_change_pct=0.0095,
        by_factor={
            "turnover_mean_20": 0.0030,
            "volatility_20": 0.0020,
            "bp_ratio": 0.0015,
            "dv_ttm": 0.0010,
        },
        by_sector={"electronics": 0.0030, "banking": -0.0010},
        by_regime=RegimeInfo(detected="bull", expected_perf_bps=12.0, actual_perf_bps=9.5),
        by_cost={"commission": -0.0005, "slippage": -0.0008},
        alpha_vs_benchmark=0.0040,
        unexplained_residual=0.0005,
    )
    assert sum(a.by_factor.values()) == pytest.approx(0.0075)
    assert sum(a.by_cost.values()) == pytest.approx(-0.0013)
    assert a.by_regime.detected == "bull"


def test_daily_attribution_frozen():
    """DailyAttribution frozen — 反 silent mutation."""
    a = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.0,
    )
    with pytest.raises(Exception):
        a.nav_change_pct = 0.01  # type: ignore[misc]


def test_residual_exceeds_threshold_default_20bps():
    """Default threshold 20 bps: 21 bps triggers, 19 bps doesn't."""
    a_high = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.0,
        unexplained_residual=0.0021,
    )
    a_low = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.0,
        unexplained_residual=0.0019,
    )
    assert residual_exceeds_threshold(a_high) is True
    assert residual_exceeds_threshold(a_low) is False


def test_residual_exceeds_threshold_negative_residual():
    """Negative residual abs comparison."""
    a = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.0,
        unexplained_residual=-0.0021,
    )
    assert residual_exceeds_threshold(a) is True


def test_residual_exceeds_threshold_custom_threshold():
    """Custom threshold."""
    a = DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.0,
        unexplained_residual=0.0030,
    )
    assert residual_exceeds_threshold(a, threshold_bps=50.0) is False
    assert residual_exceeds_threshold(a, threshold_bps=20.0) is True


def test_attribution_engine_protocol_structural_typing():
    """AttributionEngine Protocol — implementations follow structural typing."""

    class StubEngine:
        def compute(
            self,
            trade_date: date,
            strategy_id: str,
            execution_mode: str = "paper",
        ) -> DailyAttribution:
            return DailyAttribution(
                trade_date=trade_date,
                strategy_id=strategy_id,
                execution_mode=execution_mode,
                nav_change_pct=0.0,
            )

    engine: AttributionEngine = StubEngine()
    result = engine.compute(date(2026, 5, 25), "stub-sid")
    assert isinstance(result, DailyAttribution)
    assert result.trade_date == date(2026, 5, 25)
