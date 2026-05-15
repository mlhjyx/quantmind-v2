"""Tests for V3 IC-3a — 5y integrated chain replay (Plan v0.4 §A IC-3a).

Scope:
  - Synthetic position construction from minute_bars day-end aggregates.
  - Synthetic RiskContext build (tz-aware UTC per 铁律 41).
  - L3 daily-cadence rule eval wiring (PURE rules, 0 crash assertion).
  - Aggregate + report rendering shape.

Out of scope (sustained HC-4a coverage):
  - L1 RealtimeRiskEngine + L4 STAGED methodology — already covered by
    test_v3_hc_4a_5y_replay_acceptance.py / test_replay_acceptance.py.
  - Real minute_bars DB read — fully synthetic in-memory bars here.

关联铁律: 24 / 31 / 41 (timezone-aware) / 33 (fail-loud on rule crash)
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A IC-3a
关联 LL: LL-098 X10 / LL-172 lesson 1 (multi-dir grep preflight)
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from v3_ic_3a_5y_integrated_replay import (  # noqa: E402
    _aggregate_daily,
    _build_daily_rules,
    _build_synthetic_context,
    _build_synthetic_positions,
    _evaluate_daily_cadence_for_quarter,
    _QuarterDailyMetrics,
    _QuarterIntegratedResult,
    _render_integrated_report,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _mk_bar(
    code: str,
    trade_date: date,
    *,
    hour: int,
    minute: int,
    open_p: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, Any]:
    """Build one minute_bar dict matching TB-5b loader schema (line 159)."""
    return {
        "trade_time": datetime.combine(trade_date, dt_time(hour, minute)),
        "code": code,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
        "amount": 10000.0,
        "prev_close": open_p,
    }


def _make_bars(
    code: str, trade_date: date, *, open_p: float, high: float, close: float
) -> list[dict[str, Any]]:
    """Build a small synthetic intra-day bar stream for one (code, day)."""
    # 3 bars at 09:30 / 10:30 / 14:55 — open at start, peak at mid, close at end.
    return [
        _mk_bar(code, trade_date, hour=9, minute=30, open_p=open_p, high=open_p, low=open_p, close=open_p),
        _mk_bar(code, trade_date, hour=10, minute=30, open_p=open_p, high=high, low=open_p, close=high),
        _mk_bar(code, trade_date, hour=14, minute=55, open_p=high, high=high, low=close, close=close),
    ]


# ─────────────────────────────────────────────────────────────
# _build_synthetic_positions
# ─────────────────────────────────────────────────────────────


class TestBuildSyntheticPositions:
    def test_single_code_single_day_emits_one_position(self) -> None:
        bars = _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.5, close=10.8)
        positions = _build_synthetic_positions(bars)
        assert len(positions) == 1
        p = positions[0]
        assert p.code == "600000.SH"
        assert p.shares == 1
        assert p.entry_price == pytest.approx(10.0)
        assert p.peak_price == pytest.approx(11.5)
        assert p.current_price == pytest.approx(10.8)
        assert p.entry_date == date(2024, 6, 3)

    def test_multi_code_emits_one_position_per_code(self) -> None:
        bars = (
            _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
            + _make_bars("600519.SH", date(2024, 6, 3), open_p=1700.0, high=1720.0, close=1715.0)
        )
        positions = _build_synthetic_positions(bars)
        assert len(positions) == 2
        codes = {p.code for p in positions}
        assert codes == {"600000.SH", "600519.SH"}

    def test_degenerate_peak_below_entry_skipped(self) -> None:
        """If max(high) < open (data corruption), skip rather than feed rule garbage."""
        bars = [
            _mk_bar("BAD.SH", date(2024, 6, 3), hour=9, minute=30, open_p=10.0, high=9.5, low=9.0, close=9.2),
            _mk_bar("BAD.SH", date(2024, 6, 3), hour=10, minute=30, open_p=10.0, high=9.8, low=9.5, close=9.5),
        ]
        positions = _build_synthetic_positions(bars)
        assert positions == []

    def test_zero_price_skipped(self) -> None:
        """Zero open or close = pre-listing garbage, skipped silently."""
        bars = [
            _mk_bar("ZERO.SH", date(2024, 6, 3), hour=9, minute=30, open_p=0.0, high=0.0, low=0.0, close=0.0),
        ]
        positions = _build_synthetic_positions(bars)
        assert positions == []

    def test_empty_bars_returns_empty(self) -> None:
        assert _build_synthetic_positions([]) == []


# ─────────────────────────────────────────────────────────────
# _build_synthetic_context
# ─────────────────────────────────────────────────────────────


class TestBuildSyntheticContext:
    def test_timestamp_is_tz_aware_utc_at_eod_15_00_shanghai(self) -> None:
        """铁律 41: RiskContext.timestamp must be tz-aware UTC at 15:00 Asia/Shanghai = 07:00 UTC."""
        trade_date = date(2024, 6, 3)
        bars = _make_bars("600000.SH", trade_date, open_p=10.0, high=11.0, close=10.5)
        positions = _build_synthetic_positions(bars)
        ctx = _build_synthetic_context(trade_date, positions)
        assert ctx.timestamp.tzinfo is not None
        # 15:00 CST = 07:00 UTC.
        assert ctx.timestamp == datetime(2024, 6, 3, 7, 0, tzinfo=UTC)

    def test_strategy_id_and_execution_mode_sustained(self) -> None:
        bars = _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
        positions = _build_synthetic_positions(bars)
        ctx = _build_synthetic_context(date(2024, 6, 3), positions)
        assert ctx.strategy_id == "ic_3a_synthetic"
        assert ctx.execution_mode == "paper"

    def test_portfolio_nav_is_sum_of_current_prices(self) -> None:
        bars = (
            _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
            + _make_bars("600519.SH", date(2024, 6, 3), open_p=1700.0, high=1720.0, close=1715.0)
        )
        positions = _build_synthetic_positions(bars)
        ctx = _build_synthetic_context(date(2024, 6, 3), positions)
        # 1 share each × close: 10.5 + 1715.0 = 1725.5
        assert ctx.portfolio_nav == pytest.approx(10.5 + 1715.0)

    def test_empty_positions_zero_nav(self) -> None:
        ctx = _build_synthetic_context(date(2024, 6, 3), [])
        assert ctx.portfolio_nav == pytest.approx(0.0)
        assert ctx.positions == ()


# ─────────────────────────────────────────────────────────────
# _build_daily_rules
# ─────────────────────────────────────────────────────────────


class TestBuildDailyRules:
    def test_returns_four_pure_rules(self) -> None:
        rules = _build_daily_rules()
        assert len(rules) == 4
        rule_class_names = {type(r).__name__ for r in rules}
        assert rule_class_names == {
            "PMSRule",
            "PositionHoldingTimeRule",
            "NewPositionVolatilityRule",
            "SingleStockStopLossRule",
        }

    def test_circuit_breaker_rule_NOT_included(self) -> None:
        """CircuitBreakerRule needs DB conn for legacy _check_cb_sync — must NOT be in IC-3a."""
        rules = _build_daily_rules()
        rule_class_names = {type(r).__name__ for r in rules}
        assert "CircuitBreakerRule" not in rule_class_names


# ─────────────────────────────────────────────────────────────
# _evaluate_daily_cadence_for_quarter
# ─────────────────────────────────────────────────────────────


class TestEvaluateDailyCadenceForQuarter:
    def test_empty_bars_returns_zero_metrics(self) -> None:
        rules = _build_daily_rules()
        m = _evaluate_daily_cadence_for_quarter([], rules)
        assert m.trading_days == 0
        assert m.eval_calls == 0
        assert m.crashes == 0

    def test_single_day_single_code_runs_all_rules(self) -> None:
        rules = _build_daily_rules()
        bars = _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
        m = _evaluate_daily_cadence_for_quarter(bars, rules)
        assert m.trading_days == 1
        assert m.synthetic_positions == 1
        # 1 day × 4 rules = 4 eval calls.
        assert m.eval_calls == 4
        assert m.crashes == 0

    def test_multi_day_multi_code_runs_calls_per_day_times_rules(self) -> None:
        rules = _build_daily_rules()
        bars = (
            _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
            + _make_bars("600519.SH", date(2024, 6, 3), open_p=1700.0, high=1720.0, close=1715.0)
            + _make_bars("600000.SH", date(2024, 6, 4), open_p=10.5, high=11.2, close=10.8)
        )
        m = _evaluate_daily_cadence_for_quarter(bars, rules)
        assert m.trading_days == 2
        # day 1: 2 codes, day 2: 1 code → 3 synthetic positions.
        assert m.synthetic_positions == 3
        # 2 days × 4 rules = 8 eval calls (rules evaluate context, not per-position).
        assert m.eval_calls == 8
        assert m.crashes == 0

    def test_crashing_rule_counted_in_crashes_continues_others(self) -> None:
        """Rule.evaluate raise must NOT abort the quarter; crash counted + others continue."""

        class _CrashingRule:
            rule_id = "crash_test"

            def evaluate(self, ctx: Any) -> list[Any]:
                raise RuntimeError("synthetic crash for IC-3a wiring test")

        rules = [_CrashingRule()] + _build_daily_rules()  # crash + 4 pure
        bars = _make_bars("600000.SH", date(2024, 6, 3), open_p=10.0, high=11.0, close=10.5)
        m = _evaluate_daily_cadence_for_quarter(bars, rules)
        # 1 day × 5 rules = 5 eval_calls; 1 crash; remaining 4 rules ran successfully.
        assert m.eval_calls == 5
        assert m.crashes == 1

    def test_skip_day_with_only_degenerate_bars(self) -> None:
        """Day with 0 valid positions doesn't count toward eval_calls."""
        rules = _build_daily_rules()
        bars = [
            _mk_bar("BAD.SH", date(2024, 6, 3), hour=9, minute=30, open_p=0.0, high=0.0, low=0.0, close=0.0),
        ]
        m = _evaluate_daily_cadence_for_quarter(bars, rules)
        # trading_days counts ALL distinct trade_date keys, including degenerate.
        assert m.trading_days == 1
        # but 0 positions = no rule invocation.
        assert m.synthetic_positions == 0
        assert m.eval_calls == 0
        assert m.crashes == 0


# ─────────────────────────────────────────────────────────────
# _aggregate_daily
# ─────────────────────────────────────────────────────────────


def _mk_quarter(name: str, td: int, calls: int, crashes: int, triggers: dict[str, int]) -> _QuarterIntegratedResult:
    """Build a minimal _QuarterIntegratedResult test fixture."""
    from v3_hc_4a_5y_replay_acceptance import _QuarterResult

    l1 = _QuarterResult(name=name)
    daily = _QuarterDailyMetrics(
        trading_days=td,
        synthetic_positions=td * 10,
        eval_calls=calls,
        crashes=crashes,
        triggers_by_rule=dict(triggers),
    )
    return _QuarterIntegratedResult(l1=l1, daily=daily)


class TestAggregateDaily:
    def test_aggregates_counts_across_quarters(self) -> None:
        quarters = [
            _mk_quarter("2024Q1", td=63, calls=63 * 4, crashes=0, triggers={"pms_l3": 2}),
            _mk_quarter("2024Q2", td=60, calls=60 * 4, crashes=0, triggers={"pms_l3": 1, "single_stock_stop_loss": 5}),
        ]
        agg = _aggregate_daily(quarters)
        assert agg["total_trading_days"] == 123
        assert agg["total_eval_calls"] == (63 + 60) * 4
        assert agg["total_crashes"] == 0
        assert agg["triggers_by_rule"] == {"pms_l3": 3, "single_stock_stop_loss": 5}
        assert agg["pass_l3_wiring"] is True

    def test_any_crash_fails_wiring_verdict(self) -> None:
        quarters = [_mk_quarter("2024Q1", td=63, calls=252, crashes=1, triggers={})]
        agg = _aggregate_daily(quarters)
        assert agg["total_crashes"] == 1
        assert agg["pass_l3_wiring"] is False

    def test_zero_eval_calls_fails_wiring_verdict(self) -> None:
        """0 eval_calls = test never ran; must NOT silently pass."""
        quarters = [_mk_quarter("2024Q1", td=0, calls=0, crashes=0, triggers={})]
        agg = _aggregate_daily(quarters)
        assert agg["total_eval_calls"] == 0
        assert agg["pass_l3_wiring"] is False


# ─────────────────────────────────────────────────────────────
# _render_integrated_report
# ─────────────────────────────────────────────────────────────


class TestRenderIntegratedReport:
    def _l1_agg(self, *, pass_all: bool = True) -> dict[str, Any]:
        return {
            "fp_rate": 0.05,
            "total_false_positives": 50,
            "total_true_positives": 950,
            "total_classified": 1000,
            "pass_fp_rate": pass_all,
            "max_quarter_p99_ms": 1.5,
            "pass_latency": pass_all,
            "total_staged_failed": 0 if pass_all else 5,
            "pass_staged": pass_all,
            "pass_meta": pass_all,
            "total_minute_bars": 190_000_000,
            "total_events": 12_345,
            "total_raw_p0": 200,
            "total_deduped_p0": 100,
            "total_staged_actionable": 30,
            "total_staged_closed_ok": 30,
        }

    def _daily_agg(self, *, pass_wiring: bool = True) -> dict[str, Any]:
        return {
            "total_trading_days": 1260,
            "total_synthetic_positions": 1_500_000,
            "total_eval_calls": 5040,
            "total_crashes": 0 if pass_wiring else 3,
            "triggers_by_rule": {"pms_l3": 12, "single_stock_stop_loss": 47},
            "pass_l3_wiring": pass_wiring,
        }

    def test_overall_pass_renders_pass_verdict(self) -> None:
        report = _render_integrated_report(
            quarters=[_mk_quarter("2024Q1", td=63, calls=252, crashes=0, triggers={})],
            l1_agg=self._l1_agg(pass_all=True),
            daily_agg=self._daily_agg(pass_wiring=True),
        )
        assert "✅ PASS" in report
        assert "❌" not in report.replace("❌'", "").split("Overall verdict")[1].split("\n")[0]

    def test_l3_crash_failure_propagates_overall(self) -> None:
        report = _render_integrated_report(
            quarters=[_mk_quarter("2024Q1", td=63, calls=252, crashes=3, triggers={})],
            l1_agg=self._l1_agg(pass_all=True),
            daily_agg=self._daily_agg(pass_wiring=False),
        )
        # Overall verdict line should show FAIL.
        verdict_line = [l for l in report.splitlines() if "Overall verdict" in l][0]
        assert "FAIL" in verdict_line

    def test_report_includes_l3_section(self) -> None:
        report = _render_integrated_report(
            quarters=[_mk_quarter("2024Q1", td=63, calls=252, crashes=0, triggers={"pms_l3": 1})],
            l1_agg=self._l1_agg(pass_all=True),
            daily_agg=self._daily_agg(pass_wiring=True),
        )
        assert "§2 L3 daily-cadence" in report
        assert "Trading days evaluated" in report
        assert "pms_l3" in report

    def test_report_cites_methodology_anchors(self) -> None:
        """Sediment-quality assertion: report must cite V3 / ADR / Plan / 铁律 / LL."""
        report = _render_integrated_report(
            quarters=[_mk_quarter("2024Q1", td=63, calls=252, crashes=0, triggers={})],
            l1_agg=self._l1_agg(),
            daily_agg=self._daily_agg(),
        )
        # V3 spec sections
        assert "§15.4" in report
        assert "§13.1" in report
        # ADR anchors
        assert "ADR-063" in report
        assert "ADR-070" in report
        # Plan + LL
        assert "Plan v0.4 §A IC-3a" in report
        assert "LL-098 X10" in report
        # 红线 5/5 sustained signature
        assert "LIVE_TRADING_DISABLED=true" in report
        assert "EXECUTION_MODE=paper" in report


# ─────────────────────────────────────────────────────────────
# Multi-directory grep sustenance (LL-172 lesson 1 amended preflight)
# ─────────────────────────────────────────────────────────────


class TestPreflightInvariants:
    def test_l1_realtime_engine_has_zero_reflector_imports(self) -> None:
        """LL-172 lesson 1: multi-dir grep verify LLM out-of-band sustained."""
        realtime_dir = PROJECT_ROOT / "backend" / "qm_platform" / "risk" / "realtime"
        offenders: list[str] = []
        for py in realtime_dir.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            # Allow doc-only mentions in docstring/comments via word-boundary check.
            if "import" in text and (
                "from qm_platform.risk.reflector" in text
                or "from qm_platform.risk.regime.agents" in text
            ):
                offenders.append(py.name)
        assert offenders == [], (
            f"LL-172 lesson 1 regression: L1 realtime files importing LLM "
            f"modules → out-of-band assumption broken: {offenders}"
        )

    def test_daily_rules_marked_pure(self) -> None:
        """铁律 31: 4 daily rules consumed by IC-3a must carry 纯计算 / 31 marker."""
        rules_dir = PROJECT_ROOT / "backend" / "qm_platform" / "risk" / "rules"
        for rule_file in ("pms.py", "holding_time.py", "new_position.py", "single_stock.py"):
            text = (rules_dir / rule_file).read_text(encoding="utf-8")
            assert "31" in text and ("纯计算" in text or "PURE" in text.upper()), (
                f"{rule_file} missing 铁律 31 / 纯计算 marker — IC-3a invariant broken"
            )
