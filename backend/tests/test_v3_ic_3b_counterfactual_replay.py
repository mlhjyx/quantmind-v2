"""Tests for V3 IC-3b — Counterfactual replay (Plan v0.4 §A IC-3b).

Scope:
  - Incident definition shape + ADR-080 selection criteria coverage
  - _IncidentResult counterfactual_passed semantics (per-cadence verdict)
  - Report rendering shape + methodology anchors

Out of scope (DB-dependent integration paths covered by run-time execution):
  - _run_tick_incident: requires minute_bars DB (HC-4a infra wraps)
  - _run_daily_incident: requires klines_daily + trade_log DB
  - These are exercised by the full `python scripts/v3_ic_3b_*.py` run
    which produces `docs/audit/v3_ic_3b_counterfactual_replay_report_*.md`

关联铁律: 24 / 31 / 41 / 33
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A IC-3b
关联 LL: LL-098 X10 / LL-172 lesson 1 (Phase 0 data avail verify amended SOP)
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from v3_ic_3b_counterfactual_replay import (
    _INCIDENTS,
    Incident,
    _IncidentResult,
    _render_report,
)

# ─────────────────────────────────────────────────────────────
# Incident definitions
# ─────────────────────────────────────────────────────────────


class TestIncidentDefinitions:
    def test_three_incidents_per_user_decision_i2_b(self) -> None:
        """Q3 (I2) + B path locked exactly 3 incidents."""
        assert len(_INCIDENTS) == 3

    def test_incidents_cover_diversity_criterion(self) -> None:
        """ADR-080 criterion 5: ≥2 distinct shock types."""
        shock_types = {i.shock_type for i in _INCIDENTS}
        assert len(shock_types) >= 2

    def test_2_tick_1_daily_cadence_mix(self) -> None:
        """User 决议 B path: 2 tick (minute_bars) + 1 daily (klines_daily)."""
        tick = [i for i in _INCIDENTS if i.cadence == "tick"]
        daily = [i for i in _INCIDENTS if i.cadence == "daily"]
        assert len(tick) == 2
        assert len(daily) == 1

    def test_4_29_is_the_daily_cadence_one(self) -> None:
        """4-29 falls to daily because minute_bars max=2026-04-13 (Phase 0 finding)."""
        daily_incidents = [i for i in _INCIDENTS if i.cadence == "daily"]
        assert daily_incidents[0].end_date == date(2026, 4, 29)

    def test_2025_04_07_tariff_in_set(self) -> None:
        names = [i.name for i in _INCIDENTS]
        assert any("Tariff" in n or "关税" in n for n in names)

    def test_2024_q1_dma_snowball_in_set(self) -> None:
        names = [i.name for i in _INCIDENTS]
        assert any("DMA" in n or "Snowball" in n or "2024" in n for n in names)


# ─────────────────────────────────────────────────────────────
# _IncidentResult counterfactual_passed semantics
# ─────────────────────────────────────────────────────────────


def _mk_tick_incident() -> Incident:
    return Incident(
        name="test tick",
        start_date=date(2025, 4, 7),
        end_date=date(2025, 4, 7),
        cadence="tick",
        shock_type="macro",
        counterfactual_question="?",
        data_source="minute_bars",
    )


def _mk_daily_incident() -> Incident:
    return Incident(
        name="test daily",
        start_date=date(2026, 4, 28),
        end_date=date(2026, 4, 29),
        cadence="daily",
        shock_type="user liquidation",
        counterfactual_question="?",
        data_source="klines_daily + trade_log",
    )


class TestCounterfactualPassedSemantics:
    def test_tick_with_p0_alerts_passes(self) -> None:
        r = _IncidentResult(incident=_mk_tick_incident(), p0_alert_count=100)
        assert r.counterfactual_passed is True

    def test_tick_with_zero_p0_alerts_fails(self) -> None:
        """Tick PASS requires ≥1 P0 alert (sustained acceptance.py P0 rule_id set)."""
        r = _IncidentResult(incident=_mk_tick_incident(), p0_alert_count=0, p1_alert_count=50)
        assert r.counterfactual_passed is False

    def test_tick_with_error_fails(self) -> None:
        r = _IncidentResult(incident=_mk_tick_incident(), p0_alert_count=100, error="DBError: ...")
        assert r.counterfactual_passed is False

    def test_daily_with_zero_alerts_passes_wiring_health(self) -> None:
        """4-29 Phase 0 meta-finding: 0 alerts on benign data IS correct."""
        r = _IncidentResult(incident=_mk_daily_incident(), p0_alert_count=0, p1_alert_count=0)
        assert r.counterfactual_passed is True

    def test_daily_with_alerts_also_passes(self) -> None:
        """Daily PASS is wiring health regardless of alert count."""
        r = _IncidentResult(incident=_mk_daily_incident(), p1_alert_count=3)
        assert r.counterfactual_passed is True

    def test_daily_with_error_fails(self) -> None:
        r = _IncidentResult(incident=_mk_daily_incident(), error="UndefinedColumn: ...")
        assert r.counterfactual_passed is False


# ─────────────────────────────────────────────────────────────
# _IncidentResult helper properties
# ─────────────────────────────────────────────────────────────


class TestIncidentResultProperties:
    def test_total_alerts_sums_severities(self) -> None:
        r = _IncidentResult(
            incident=_mk_tick_incident(),
            p0_alert_count=10,
            p1_alert_count=5,
            p2_alert_count=2,
        )
        assert r.total_alerts == 17

    def test_default_fields(self) -> None:
        r = _IncidentResult(incident=_mk_tick_incident())
        assert r.total_alerts == 0
        assert r.codes_alerted == set()
        assert r.alerts_by_rule_id == {}
        assert r.earliest_alert_ts is None
        assert r.error is None


# ─────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────


class TestRenderReport:
    def _mk_pass_results(self) -> list[_IncidentResult]:
        tick = _IncidentResult(
            incident=_mk_tick_incident(),
            p0_alert_count=12345,
            p1_alert_count=67,
            minute_bars_replayed=500_000,
            codes_alerted={"600000.SH", "000001.SZ"},
            alerts_by_rule_id={"gap_down_open": 11000, "limit_down_detection": 1000},
            earliest_alert_ts=datetime.fromisoformat("2025-04-07T09:35:00+08:00"),
            wall_clock_s=10.5,
        )
        daily = _IncidentResult(
            incident=_mk_daily_incident(),
            p0_alert_count=0,
            p1_alert_count=0,
            daily_positions_evaluated=17,
            wall_clock_s=0.1,
        )
        return [tick, daily]

    def test_overall_pass_when_all_incidents_pass(self) -> None:
        report = _render_report(self._mk_pass_results())
        verdict_line = next(l for l in report.splitlines() if "Overall verdict" in l)
        assert "✅ PASS" in verdict_line

    def test_overall_fail_when_any_incident_errors(self) -> None:
        results = self._mk_pass_results()
        results[0] = _IncidentResult(incident=_mk_tick_incident(), error="boom")
        report = _render_report(results)
        verdict_line = next(l for l in report.splitlines() if "Overall verdict" in l)
        assert "FAIL" in verdict_line

    def test_report_renders_per_incident_sections(self) -> None:
        report = _render_report(self._mk_pass_results())
        # §1 verdicts table + §2/§3 per-incident sections.
        assert "## §1 Per-incident verdicts" in report
        assert "## §2 " in report
        assert "## §3 " in report

    def test_report_cites_methodology_anchors(self) -> None:
        report = _render_report(self._mk_pass_results())
        assert "V3 §15.5" in report
        assert "ADR-070" in report
        assert "ADR-080" in report
        assert "Plan v0.4 §A IC-3b" in report
        assert "LL-098 X10" in report
        # 红线 cite
        assert "LIVE_TRADING_DISABLED=true" in report
        assert "EXECUTION_MODE=paper" in report

    def test_report_includes_adr_080_selection_criteria(self) -> None:
        """ADR-080 §5 section must enumerate 5 selection criteria."""
        report = _render_report(self._mk_pass_results())
        assert "ADR-080 candidate" in report
        # 5 criteria headers
        for keyword in [
            "Real documented incident",
            "V3 risk-type coverage",
            "Data availability",
            "Counterfactual measurability",
            "Diversity",
        ]:
            assert keyword in report, f"missing ADR-080 criterion: {keyword}"

    def test_report_includes_4_29_meta_finding(self) -> None:
        """Phase 0 meta-finding (4-29 is user-liquidation NOT crash) must be sediment."""
        report = _render_report(self._mk_pass_results())
        assert "user-decision" in report.lower() or "user-initiated" in report.lower()
        assert "NOT" in report  # narrative emphasizes it's NOT a crash

    def test_tick_verdict_phrasing_distinct_from_daily(self) -> None:
        """Tick verdict cites ≥1 P0 alert; daily cites wiring health."""
        report = _render_report(self._mk_pass_results())
        # Both verdicts present
        assert "tick-cadence fired" in report or "L1 tick" in report
        assert "wiring health" in report or "executed cleanly" in report


# ─────────────────────────────────────────────────────────────
# Phase 0 preflight invariants (LL-172 lesson 1 sustained)
# ─────────────────────────────────────────────────────────────


class TestPhase0Invariants:
    def test_4_29_window_uses_klines_daily(self) -> None:
        """user 决议 B path: 4-29 falls to klines_daily (minute_bars max=2026-04-13)."""
        daily_incidents = [i for i in _INCIDENTS if i.cadence == "daily"]
        assert len(daily_incidents) == 1
        assert "klines_daily" in daily_incidents[0].data_source

    def test_tick_incidents_use_minute_bars(self) -> None:
        """Tick path uses minute_bars per HC-4a infra."""
        tick_incidents = [i for i in _INCIDENTS if i.cadence == "tick"]
        assert len(tick_incidents) == 2
        for i in tick_incidents:
            assert "minute_bars" in i.data_source.lower()
