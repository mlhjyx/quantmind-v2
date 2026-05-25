"""MVP 4.2 Performance Attribution (qm_platform/eval/attribution.py) shape tests (iter 59).

iter 59 covers dataclass + protocol shape only; iter 60+ adds implementation tests.

Note: test filename `test_qm_platform_attribution.py` to avoid conflict with
existing `test_attribution.py` (research Brinson-Fachler module).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.qm_platform.eval.attribution import (
    AttributionEngine,
    DailyAttribution,
    RegimeInfo,
    compute_by_cost,
    compute_by_factor,
    compute_by_regime,
    compute_by_sector,
    compute_unexplained_residual,
    fire_residual_alert,
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


# ────────────────────────────────────────────────────────────────────
# MVP 4.2 sub-iter 4 (iter 62): compute_by_cost — trade_log aggregation
# ────────────────────────────────────────────────────────────────────


def test_compute_by_cost_empty_trades():
    """Empty trades list → all 4 categories at 0.0."""
    result = compute_by_cost([])
    assert result == {
        "commission": 0.0,
        "slippage": 0.0,
        "impact": 0.0,
        "overnight_gap": 0.0,
    }


def test_compute_by_cost_single_trade_all_fields():
    """Single trade with all 4 cost fields, nav=1.0 → output in yuan (negative)."""
    trades = [{"commission": 5.0, "slippage": 2.0, "impact": 1.0, "overnight_gap": 0.5}]
    result = compute_by_cost(trades, nav=1.0)
    # All costs are negative P&L impact when nav=1.0
    assert result == {
        "commission": -5.0,
        "slippage": -2.0,
        "impact": -1.0,
        "overnight_gap": -0.5,
    }


def test_compute_by_cost_normalization_decimal():
    """nav=100000 → output is decimal fraction (yuan / nav)."""
    trades = [{"commission": 5.0, "slippage": 2.0, "impact": 1.0, "overnight_gap": 0.0}]
    result = compute_by_cost(trades, nav=100000.0)
    assert result["commission"] == pytest.approx(-5.0 / 100000)
    assert result["slippage"] == pytest.approx(-2.0 / 100000)
    assert result["impact"] == pytest.approx(-1.0 / 100000)
    assert result["overnight_gap"] == 0.0


def test_compute_by_cost_multiple_trades_aggregation():
    """Multi-trade aggregation: sums per category before normalization."""
    trades = [
        {"commission": 5.0, "slippage": 2.0, "impact": 1.0, "overnight_gap": 0.0},
        {"commission": 5.0, "slippage": 3.0, "impact": 1.5, "overnight_gap": 0.5},
        {"commission": 10.0, "slippage": 4.0, "impact": 2.0, "overnight_gap": 1.0},
    ]
    result = compute_by_cost(trades, nav=100000.0)
    # commission total = 20, slippage total = 9, impact total = 4.5, overnight_gap total = 1.5
    assert result["commission"] == pytest.approx(-20.0 / 100000)
    assert result["slippage"] == pytest.approx(-9.0 / 100000)
    assert result["impact"] == pytest.approx(-4.5 / 100000)
    assert result["overnight_gap"] == pytest.approx(-1.5 / 100000)


def test_compute_by_cost_missing_field_silent_zero():
    """Trade missing some cost fields → 0 contribution for missing (silent skip per 铁律 33)."""
    trades = [{"commission": 5.0}]  # only commission, others missing
    result = compute_by_cost(trades, nav=1.0)
    assert result == {
        "commission": -5.0,
        "slippage": 0.0,
        "impact": 0.0,
        "overnight_gap": 0.0,
    }


def test_compute_by_cost_negative_slippage_positive_for_portfolio():
    """Negative slippage value (favorable fill) → positive P&L impact."""
    trades = [{"commission": 0.0, "slippage": -2.0, "impact": 0.0, "overnight_gap": 0.0}]
    result = compute_by_cost(trades, nav=1.0)
    # slippage of -2 yuan → P&L = -(-2)/1 = +2 (favorable fill saves money)
    assert result["slippage"] == 2.0


def test_compute_by_cost_zero_nav_raises():
    """nav<=0 → ValueError per 铁律 33 (反 silent zero division)."""
    with pytest.raises(ValueError, match="nav must be positive"):
        compute_by_cost([{"commission": 5.0}], nav=0.0)
    with pytest.raises(ValueError, match="nav must be positive"):
        compute_by_cost([{"commission": 5.0}], nav=-1.0)


def test_compute_by_cost_pt_realistic_pt_topn5_day():
    """PT realistic 5-stock day: ~commission 50 yuan + slippage 30 yuan + impact 20 yuan."""
    # 5 trades, 国金 commission ~10 yuan/trade min, slippage realistic ~6 yuan/trade
    trades = [
        {"commission": 10.0, "slippage": 6.0, "impact": 4.0, "overnight_gap": 0.0},
        {"commission": 10.0, "slippage": 6.0, "impact": 4.0, "overnight_gap": 0.0},
        {"commission": 10.0, "slippage": 6.0, "impact": 4.0, "overnight_gap": 0.0},
        {"commission": 10.0, "slippage": 6.0, "impact": 4.0, "overnight_gap": 0.0},
        {"commission": 10.0, "slippage": 6.0, "impact": 4.0, "overnight_gap": 0.0},
    ]
    nav = 993520.66  # red line cash
    result = compute_by_cost(trades, nav=nav)
    # commission: -50/993520.66 ≈ -5.03e-05 (-0.5 bps)
    assert result["commission"] == pytest.approx(-50.0 / nav)
    assert result["slippage"] == pytest.approx(-30.0 / nav)
    assert result["impact"] == pytest.approx(-20.0 / nav)
    # Total cost as decimal
    total_cost = sum(result.values())
    assert total_cost == pytest.approx(-100.0 / nav)


def test_compute_by_cost_attribution_dataclass_integration():
    """compute_by_cost output integrates with DailyAttribution.by_cost field."""
    trades = [{"commission": 5.0, "slippage": 2.0, "impact": 1.0, "overnight_gap": 0.0}]
    by_cost = compute_by_cost(trades, nav=100000.0)
    a = DailyAttribution(
        trade_date=date(2026, 5, 27),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.005,
        by_cost=by_cost,
    )
    assert "commission" in a.by_cost
    assert a.by_cost["commission"] < 0  # cost is negative P&L impact


# ────────────────────────────────────────────────────────────────────
# MVP 4.2 sub-iter 5 (iter 63): compute_by_regime — HMM 3-state integration
# ────────────────────────────────────────────────────────────────────


def test_compute_by_regime_bull_argmax():
    """Bull dominant probability → detected = bull."""
    probs = {0: 0.7, 1: 0.2, 2: 0.1}
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    info = compute_by_regime(probs, mapping, actual_perf_bps=10.0)
    assert info.detected == "bull"
    # expected = 0.7*12 + 0.2*0 + 0.1*(-8) = 8.4 + 0 - 0.8 = 7.6
    assert info.expected_perf_bps == pytest.approx(7.6)
    assert info.actual_perf_bps == 10.0


def test_compute_by_regime_bear_argmax():
    """Bear dominant probability → detected = bear."""
    probs = {0: 0.1, 1: 0.2, 2: 0.7}
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    info = compute_by_regime(probs, mapping, actual_perf_bps=-5.0)
    assert info.detected == "bear"
    # expected = 0.1*12 + 0.2*0 + 0.7*(-8) = 1.2 - 5.6 = -4.4
    assert info.expected_perf_bps == pytest.approx(-4.4)


def test_compute_by_regime_sideways_argmax():
    """Sideways dominant probability → detected = sideways."""
    probs = {0: 0.2, 1: 0.6, 2: 0.2}
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    info = compute_by_regime(probs, mapping, actual_perf_bps=1.0)
    assert info.detected == "sideways"
    # expected = 0.2*12 + 0.6*0 + 0.2*(-8) = 2.4 + 0 - 1.6 = 0.8
    assert info.expected_perf_bps == pytest.approx(0.8)


def test_compute_by_regime_list_probs():
    """state_probs as list (indexed by position) — alternative input form."""
    probs = [0.5, 0.3, 0.2]  # 0=bull, 1=sideways, 2=bear
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    info = compute_by_regime(probs, mapping, actual_perf_bps=5.0)
    assert info.detected == "bull"
    assert info.expected_perf_bps == pytest.approx(0.5 * 12 + 0.3 * 0 + 0.2 * -8)  # 4.4


def test_compute_by_regime_custom_baseline():
    """Custom baseline_perf_bps override."""
    probs = {0: 0.8, 1: 0.1, 2: 0.1}
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    custom = {"bull": 20.0, "sideways": 0.0, "bear": -15.0}
    info = compute_by_regime(probs, mapping, actual_perf_bps=15.0, baseline_perf_bps=custom)
    # expected = 0.8*20 + 0.1*0 + 0.1*(-15) = 16 - 1.5 = 14.5
    assert info.expected_perf_bps == pytest.approx(14.5)


def test_compute_by_regime_empty_probs_raises():
    """Empty state_probs → ValueError."""
    with pytest.raises(ValueError, match="state_probs is empty"):
        compute_by_regime({}, {0: "bull"}, actual_perf_bps=0.0)
    with pytest.raises(ValueError, match="state_probs is empty"):
        compute_by_regime([], {0: "bull"}, actual_perf_bps=0.0)


def test_compute_by_regime_empty_mapping_raises():
    """Empty state_mapping → ValueError."""
    with pytest.raises(ValueError, match="state_mapping is empty"):
        compute_by_regime({0: 1.0}, {}, actual_perf_bps=0.0)


def test_compute_by_regime_unknown_argmax_raises():
    """state_mapping missing argmax state → ValueError."""
    probs = {0: 0.3, 5: 0.7}  # state 5 not in mapping
    mapping = {0: "bull", 1: "sideways"}
    with pytest.raises(ValueError, match="state_mapping missing argmax index 5"):
        compute_by_regime(probs, mapping, actual_perf_bps=0.0)


def test_compute_by_regime_attribution_dataclass_integration():
    """compute_by_regime output integrates with DailyAttribution.by_regime field."""
    probs = {0: 0.6, 1: 0.3, 2: 0.1}
    mapping = {0: "bull", 1: "sideways", 2: "bear"}
    by_regime = compute_by_regime(probs, mapping, actual_perf_bps=8.0)
    a = DailyAttribution(
        trade_date=date(2026, 5, 27),
        strategy_id="x",
        execution_mode="paper",
        nav_change_pct=0.008,
        by_regime=by_regime,
    )
    assert a.by_regime is not None
    assert a.by_regime.detected == "bull"


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


# ────────────────────────────────────────────────────────────────────
# MVP 4.2 sub-iter 6 (iter 64): compute_unexplained_residual + fire_residual_alert
# ────────────────────────────────────────────────────────────────────


def _make_attribution(
    nav_change_pct: float = 0.012,
    by_factor: dict[str, float] | None = None,
    by_sector: dict[str, float] | None = None,
    by_cost: dict[str, float] | None = None,
    alpha_vs_benchmark: float = 0.0,
) -> DailyAttribution:
    """Test helper — build DailyAttribution with overrides."""
    return DailyAttribution(
        trade_date=date(2026, 5, 25),
        strategy_id="test-strategy",
        execution_mode="paper",
        nav_change_pct=nav_change_pct,
        by_factor=by_factor or {},
        by_sector=by_sector or {},
        by_cost=by_cost or {},
        alpha_vs_benchmark=alpha_vs_benchmark,
    )


def test_compute_unexplained_residual_zero_when_components_match_nav():
    """residual = 0 when nav fully explained by components."""
    a = _make_attribution(
        nav_change_pct=0.010,
        by_factor={"vol_20": 0.004, "bp": 0.003},
        by_sector={"electronics": 0.001, "banking": 0.001},
        by_cost={"commission": -0.0001, "slippage": -0.0001},
        alpha_vs_benchmark=0.0012,
    )
    # residual = 0.010 - (0.004+0.003) - (0.001+0.001) - (-0.0001-0.0001) - 0.0012
    #         = 0.010 - 0.007 - 0.002 - (-0.0002) - 0.0012
    #         = 0.010 - 0.007 - 0.002 + 0.0002 - 0.0012 = 0.0000
    residual = compute_unexplained_residual(a)
    assert residual == pytest.approx(0.0, abs=1e-9)


def test_compute_unexplained_residual_nonzero():
    """residual != 0 when nav not fully explained."""
    a = _make_attribution(
        nav_change_pct=0.010,
        by_factor={"vol_20": 0.003},
        by_sector={"banking": 0.001},
        by_cost={"commission": -0.0002},
        alpha_vs_benchmark=0.002,
    )
    # residual = 0.010 - 0.003 - 0.001 - (-0.0002) - 0.002 = 0.0042
    residual = compute_unexplained_residual(a)
    assert residual == pytest.approx(0.0042)


def test_compute_unexplained_residual_empty_components():
    """Empty dicts → residual = nav_change_pct - alpha."""
    a = _make_attribution(nav_change_pct=0.005, alpha_vs_benchmark=0.001)
    residual = compute_unexplained_residual(a)
    assert residual == pytest.approx(0.004)


def test_fire_residual_alert_below_threshold_no_fire():
    """abs(residual) ≤ threshold → no alert dispatch."""
    # residual = 0.001 = 10 bps, threshold = 20 bps → below
    a = _make_attribution(nav_change_pct=0.001)
    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk"
    ) as mock_sdk:
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is False
    mock_sdk.assert_not_called()


def test_fire_residual_alert_above_threshold_fires_once():
    """abs(residual) > threshold → SDK called once + returns True."""
    # residual = 0.0030 = 30 bps, threshold = 20 bps → fires
    a = _make_attribution(nav_change_pct=0.003)
    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk"
    ) as mock_sdk:
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is True
    mock_sdk.assert_called_once()
    # Verify args: (attribution, residual, threshold_bps)
    call_args = mock_sdk.call_args.args
    assert call_args[0] is a
    assert call_args[1] == pytest.approx(0.003)
    assert call_args[2] == 20.0


def test_fire_residual_alert_negative_residual_above_threshold():
    """Negative residual exceeding threshold also fires (abs check)."""
    # residual = -0.0035 = -35 bps, threshold = 20 bps → fires
    a = _make_attribution(nav_change_pct=-0.0035)
    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk"
    ) as mock_sdk:
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is True
    mock_sdk.assert_called_once()


def test_fire_residual_alert_sdk_dedup_key_shape():
    """SDK path dedup_key = attribution:residual:{trade_date}; suppress_minutes=60."""
    a = _make_attribution(nav_change_pct=0.005)  # 50 bps → above 20 bps
    fake_router = MagicMock()
    with patch.dict(
        "sys.modules",
        {
            "qm_platform._types": MagicMock(
                Severity=MagicMock(P1="P1", side_effect=lambda x: x.lower())
            ),
            "qm_platform.observability": MagicMock(
                Alert=MagicMock(side_effect=lambda **kw: kw),
                get_alert_router=MagicMock(return_value=fake_router),
            ),
        },
    ):
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is True
    fake_router.fire.assert_called_once()
    kwargs = fake_router.fire.call_args.kwargs
    assert kwargs["dedup_key"] == "attribution:residual:2026-05-25"
    assert kwargs["suppress_minutes"] == 60


def test_fire_residual_alert_swallows_alert_dispatch_error():
    """AlertDispatchError → fail-soft tier 1 (铁律 33), returns False."""
    fake_dispatch_error = type("AlertDispatchError", (Exception,), {})
    a = _make_attribution(nav_change_pct=0.005)
    with (
        patch.dict(
            "sys.modules",
            {
                "qm_platform.observability": MagicMock(AlertDispatchError=fake_dispatch_error),
            },
        ),
        patch(
            "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk",
            side_effect=fake_dispatch_error("sink fail"),
        ),
    ):
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is False


def test_fire_residual_alert_swallows_generic_exception():
    """Generic Exception → fail-soft tier 2, returns False."""
    a = _make_attribution(nav_change_pct=0.005)
    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk",
        side_effect=RuntimeError("unexpected"),
    ):
        fired = fire_residual_alert(a, threshold_bps=20.0)
    assert fired is False


def test_fire_residual_alert_custom_threshold():
    """Custom threshold_bps overrides default 20 bps."""
    # residual = 0.0015 = 15 bps; threshold=10 bps → fires; threshold=20 bps → no fire
    a = _make_attribution(nav_change_pct=0.0015)
    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk"
    ) as mock_sdk:
        fired_10 = fire_residual_alert(a, threshold_bps=10.0)
    assert fired_10 is True
    mock_sdk.assert_called_once()

    with patch(
        "backend.qm_platform.eval.attribution._fire_residual_alert_via_platform_sdk"
    ) as mock_sdk2:
        fired_20 = fire_residual_alert(a, threshold_bps=20.0)
    assert fired_20 is False
    mock_sdk2.assert_not_called()
