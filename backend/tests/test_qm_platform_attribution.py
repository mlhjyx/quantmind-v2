"""MVP 4.2 Performance Attribution (qm_platform/eval/attribution.py) shape tests (iter 59).

iter 59 covers dataclass + protocol shape only; iter 60+ adds implementation tests.

Note: test filename `test_qm_platform_attribution.py` to avoid conflict with
existing `test_attribution.py` (research Brinson-Fachler module).
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from backend.qm_platform.eval.attribution import (
    AttributionEngine,
    DailyAttribution,
    RegimeInfo,
    compute_by_factor,
    compute_by_sector,
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
    with pytest.raises(dataclasses.FrozenInstanceError):
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
    with pytest.raises(dataclasses.FrozenInstanceError):
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


# ────────────────────────────────────────────────────────────────────
# MVP 4.2 sub-iter 2 (iter 60): compute_by_factor — Brinson-style cross-sectional
# ────────────────────────────────────────────────────────────────────


def test_compute_by_factor_empty_inputs():
    """Empty portfolio_weights / factor_exposures / factor_returns → empty dict."""
    assert compute_by_factor({}, {}, {}) == {}
    assert compute_by_factor({"x": 1.0}, {}, {}) == {}
    assert compute_by_factor({}, {"f1": {"x": 1.0}}, {}) == {}
    assert compute_by_factor({}, {}, {"f1": 0.001}) == {}


def test_compute_by_factor_single_factor_single_stock():
    """Single stock with weight 1.0, single factor: portfolio_exposure = 1.0 × z_score."""
    weights = {"000001.SZ": 1.0}
    exposures = {"f1": {"000001.SZ": 0.5}}
    returns = {"f1": 0.002}
    result = compute_by_factor(weights, exposures, returns)
    # exposure = 1.0 × 0.5 = 0.5; contribution = 0.5 × 0.002 = 0.001
    assert result == {"f1": 0.001}


def test_compute_by_factor_two_stocks_zero_exposure():
    """Equal weight + opposing z-scores → portfolio exposure = 0 → contribution = 0."""
    weights = {"000001.SZ": 0.5, "600000.SH": 0.5}
    exposures = {"turnover_mean_20": {"000001.SZ": 1.0, "600000.SH": -1.0}}
    returns = {"turnover_mean_20": 0.001}
    result = compute_by_factor(weights, exposures, returns)
    # exposure = 0.5×1.0 + 0.5×(-1.0) = 0; contribution = 0 × 0.001 = 0
    assert result == {"turnover_mean_20": 0.0}


def test_compute_by_factor_two_stocks_aligned_exposure():
    """Equal weight + aligned z-scores → contribution = avg × factor_return."""
    weights = {"000001.SZ": 0.5, "600000.SH": 0.5}
    exposures = {"bp_ratio": {"000001.SZ": 0.5, "600000.SH": 0.5}}
    returns = {"bp_ratio": 0.002}
    result = compute_by_factor(weights, exposures, returns)
    # exposure = 0.5×0.5 + 0.5×0.5 = 0.5; contribution = 0.5 × 0.002 = 0.001
    assert result == pytest.approx({"bp_ratio": 0.001})


def test_compute_by_factor_core3_dv_ttm_4_factors():
    """CORE3+dv_ttm 4-factor attribution (PT live configuration sustained)."""
    weights = {"000001.SZ": 0.4, "600000.SH": 0.3, "000333.SZ": 0.3}
    exposures = {
        "turnover_mean_20": {"000001.SZ": -1.0, "600000.SH": -0.5, "000333.SZ": -1.5},
        "volatility_20": {"000001.SZ": -0.8, "600000.SH": -0.3, "000333.SZ": -1.2},
        "bp_ratio": {"000001.SZ": 1.2, "600000.SH": 0.8, "000333.SZ": 1.5},
        "dv_ttm": {"000001.SZ": 0.5, "600000.SH": 0.7, "000333.SZ": 0.9},
    }
    returns = {
        "turnover_mean_20": -0.0010,  # -10bps (low turnover = positive alpha, direction=-1)
        "volatility_20": -0.0008,  # -8bps (low vol = positive alpha, direction=-1)
        "bp_ratio": 0.0012,  # +12bps (high BP = positive alpha, direction=+1)
        "dv_ttm": 0.0009,  # +9bps (high dividend = positive alpha, direction=+1)
    }
    result = compute_by_factor(weights, exposures, returns)
    assert set(result.keys()) == {"turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"}
    # All 4 factors should have non-zero contributions (positive for low-X with negative factor_return)
    # turnover_mean_20: exposure = 0.4×(-1.0) + 0.3×(-0.5) + 0.3×(-1.5) = -0.4 - 0.15 - 0.45 = -1.0
    # contribution = -1.0 × -0.0010 = 0.0010 (positive: low-turnover portfolio benefits from low-turnover alpha)
    assert result["turnover_mean_20"] == pytest.approx(0.0010)


def test_compute_by_factor_missing_factor_skipped():
    """Factor in returns but not in exposures → silently skipped (no entry)."""
    weights = {"x": 1.0}
    exposures = {"f1": {"x": 1.0}}
    returns = {"f1": 0.001, "f2_missing": 0.005}
    result = compute_by_factor(weights, exposures, returns)
    assert "f1" in result
    assert "f2_missing" not in result


def test_compute_by_factor_missing_stock_skipped():
    """Stock in weights but not in exposure map → skipped for that factor (no contribution)."""
    weights = {"000001.SZ": 0.5, "999999.SZ": 0.5}  # 999999 not in exposures
    exposures = {"f1": {"000001.SZ": 1.0}}
    returns = {"f1": 0.002}
    result = compute_by_factor(weights, exposures, returns)
    # exposure = 0.5 × 1.0 (999999 skipped); contribution = 0.5 × 0.002 = 0.001
    assert result == {"f1": 0.001}


def test_compute_by_factor_attribution_dataclass_integration():
    """compute_by_factor output integrates with DailyAttribution.by_factor field."""
    weights = {"x": 1.0}
    exposures = {"f1": {"x": 2.0}}
    returns = {"f1": 0.001}
    by_factor = compute_by_factor(weights, exposures, returns)

    a = DailyAttribution(
        trade_date=date(2026, 5, 26),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.01,
        by_factor=by_factor,
    )
    assert a.by_factor == {"f1": 0.002}
    assert sum(a.by_factor.values()) == pytest.approx(0.002)


# ────────────────────────────────────────────────────────────────────
# MVP 4.2 sub-iter 3 (iter 61): compute_by_sector — Brinson allocation effect
# ────────────────────────────────────────────────────────────────────


def test_compute_by_sector_empty_inputs():
    """Empty inputs → empty dict."""
    assert compute_by_sector({}, {}, {}) == {}
    assert compute_by_sector({"x": 1.0}, {}, {}) == {}
    assert compute_by_sector({"x": 1.0}, {"x": "银行"}, {}) == {}
    assert compute_by_sector({}, {"x": "银行"}, {"银行": 0.001}) == {}


def test_compute_by_sector_single_industry():
    """Single industry: weight × return."""
    weights = {"000001.SZ": 0.5, "600000.SH": 0.5}
    industry_map = {"000001.SZ": "银行", "600000.SH": "银行"}
    returns = {"银行": 0.002}
    result = compute_by_sector(weights, industry_map, returns)
    # industry_weight = 1.0; contribution = 1.0 × 0.002 = 0.002
    assert result == {"银行": pytest.approx(0.002)}


def test_compute_by_sector_two_industries():
    """Multi-industry breakdown."""
    weights = {"000001.SZ": 0.4, "600000.SH": 0.3, "000333.SZ": 0.3}
    industry_map = {"000001.SZ": "银行", "600000.SH": "银行", "000333.SZ": "家电"}
    returns = {"银行": 0.002, "家电": -0.001}
    result = compute_by_sector(weights, industry_map, returns)
    # 银行 weight = 0.4+0.3 = 0.7; contribution = 0.7 × 0.002 = 0.0014
    # 家电 weight = 0.3; contribution = 0.3 × -0.001 = -0.0003
    assert result["银行"] == pytest.approx(0.0014)
    assert result["家电"] == pytest.approx(-0.0003)
    assert sum(result.values()) == pytest.approx(0.0011)


def test_compute_by_sector_unmapped_stock_bucket():
    """Stock missing from industry_map → "_unmapped" aggregation."""
    weights = {"000001.SZ": 0.5, "999999.SZ": 0.5}  # 999999 not in map
    industry_map = {"000001.SZ": "银行"}
    returns = {"银行": 0.002, "_unmapped": 0.001}
    result = compute_by_sector(weights, industry_map, returns)
    # _unmapped weight = 0.5; contribution = 0.5 × 0.001 = 0.0005
    assert result["_unmapped"] == pytest.approx(0.0005)
    assert result["银行"] == pytest.approx(0.001)


def test_compute_by_sector_unmapped_no_return_silent_skip():
    """_unmapped bucket aggregated but no industry_return → silent skip from output."""
    weights = {"x": 0.5, "y": 0.5}
    industry_map = {"x": "银行"}  # y unmapped
    returns = {"银行": 0.002}  # no _unmapped return
    result = compute_by_sector(weights, industry_map, returns)
    assert "_unmapped" not in result  # silent skip per 铁律 33 # silent_ok annotation
    assert result["银行"] == pytest.approx(0.001)


def test_compute_by_sector_industry_with_no_portfolio_stock():
    """Industry in returns but no portfolio stock → 0 contribution (not in output)."""
    weights = {"x": 1.0}
    industry_map = {"x": "银行"}
    returns = {"银行": 0.002, "家电": 0.005}  # 家电 has no portfolio stock
    result = compute_by_sector(weights, industry_map, returns)
    assert "家电" not in result
    assert result == {"银行": pytest.approx(0.002)}


def test_compute_by_sector_negative_returns():
    """Negative industry returns → negative contribution."""
    weights = {"x": 0.5, "y": 0.5}
    industry_map = {"x": "电子", "y": "电子"}
    returns = {"电子": -0.003}
    result = compute_by_sector(weights, industry_map, returns)
    assert result == {"电子": pytest.approx(-0.003)}


def test_compute_by_sector_attribution_dataclass_integration():
    """compute_by_sector output integrates with DailyAttribution.by_sector field."""
    weights = {"x": 1.0}
    industry_map = {"x": "银行"}
    returns = {"银行": 0.002}
    by_sector = compute_by_sector(weights, industry_map, returns)

    a = DailyAttribution(
        trade_date=date(2026, 5, 27),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.01,
        by_sector=by_sector,
    )
    assert a.by_sector == {"银行": pytest.approx(0.002)}


def test_compute_by_sector_3_industries_sw1_sample():
    """SW1 industry sample with 3 sectors (banking/electronics/consumer)."""
    weights = {
        "000001.SZ": 0.2,
        "600036.SH": 0.2,  # both 银行
        "002475.SZ": 0.2,
        "002241.SZ": 0.2,  # both 电子
        "600519.SH": 0.2,  # 食品饮料
    }
    industry_map = {
        "000001.SZ": "银行",
        "600036.SH": "银行",
        "002475.SZ": "电子",
        "002241.SZ": "电子",
        "600519.SH": "食品饮料",
    }
    returns = {"银行": 0.0010, "电子": 0.0030, "食品饮料": -0.0020}
    result = compute_by_sector(weights, industry_map, returns)
    # 银行 = 0.4 × 0.001 = 0.0004
    # 电子 = 0.4 × 0.003 = 0.0012
    # 食品饮料 = 0.2 × -0.002 = -0.0004
    assert result["银行"] == pytest.approx(0.0004)
    assert result["电子"] == pytest.approx(0.0012)
    assert result["食品饮料"] == pytest.approx(-0.0004)
    assert sum(result.values()) == pytest.approx(0.0012)


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
