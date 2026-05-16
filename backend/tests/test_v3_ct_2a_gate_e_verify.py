"""Tests for V3 Plan v0.4 CT-2a — Gate E charter verify harness.

Scope (PURE / fixture-driven; minimal infra hit):
  - _PrereqResult / _GateEReport dataclass invariants
  - Individual prereq check semantics
  - User decision verify shape
  - Report rendering invariants

Out of scope (integration-only, exercised by `python
scripts/v3_ct_2a_gate_e_charter_verify.py --dry-run` against live sediment):
  - Real file presence checks against actual IC-3a/b/c + CT-1a/b reports
  - Real REGISTRY.md grep

关联铁律: 25 / 33 / 40 / 41
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A CT-2a
关联 LL: LL-098 X10 / LL-164 / LL-174 lesson 2
"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


from v3_ct_2a_gate_e_charter_verify import (
    _TEN_USER_DECISIONS,
    _TIER_A_ADR_MIN,
    _GateEReport,
    _PrereqResult,
    render_report,
)

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_ten_user_decisions_count(self) -> None:
        """V3 §20.1: exactly 10 user 决议."""
        assert len(_TEN_USER_DECISIONS) == 10

    def test_tier_a_adr_min_includes_cutover_path_anchors(self) -> None:
        """Tier A ADR list must include cutover anchor ADRs."""
        assert "ADR-027" in _TIER_A_ADR_MIN  # STAGED
        assert "ADR-028" in _TIER_A_ADR_MIN  # AUTO + V4-Pro
        assert "ADR-033" in _TIER_A_ADR_MIN  # News 6 源
        assert "ADR-063" in _TIER_A_ADR_MIN  # Tier B 真测路径
        assert "ADR-076" in _TIER_A_ADR_MIN  # 横切层 closed
        assert "ADR-078" in _TIER_A_ADR_MIN  # IC-1
        assert "ADR-079" in _TIER_A_ADR_MIN  # IC-2
        assert "ADR-080" in _TIER_A_ADR_MIN  # IC-3
        assert "ADR-081" in _TIER_A_ADR_MIN  # CT-1


# ─────────────────────────────────────────────────────────────
# _PrereqResult + _GateEReport
# ─────────────────────────────────────────────────────────────


class TestPrereqResult:
    def test_default_passed_false(self) -> None:
        r = _PrereqResult(name="test")
        assert r.passed is False
        assert r.detail == ""
        assert r.failures == []

    def test_passed_true_when_set(self) -> None:
        r = _PrereqResult(name="test", passed=True, detail="OK")
        assert r.passed is True
        assert r.detail == "OK"


class TestGateEReport:
    def test_gate_e_ready_requires_all_prereq_AND_all_decisions(self) -> None:
        report = _GateEReport(
            timestamp_utc="x",
            timestamp_shanghai="y",
            prereq_checks=[_PrereqResult(name=f"p{i}", passed=True) for i in range(5)],
            user_decisions_checks=[_PrereqResult(name=f"d{i}", passed=True) for i in range(10)],
        )
        assert report.all_prereq_passed is True
        assert report.all_user_decisions_passed is True
        assert report.gate_e_ready is True

    def test_gate_e_not_ready_if_one_prereq_fails(self) -> None:
        prereq = [_PrereqResult(name=f"p{i}", passed=True) for i in range(5)]
        prereq[2] = _PrereqResult(name="p2", failures=["boom"])
        report = _GateEReport(
            timestamp_utc="x", timestamp_shanghai="y",
            prereq_checks=prereq,
            user_decisions_checks=[_PrereqResult(name=f"d{i}", passed=True) for i in range(10)],
        )
        assert report.all_prereq_passed is False
        assert report.gate_e_ready is False

    def test_gate_e_not_ready_if_one_decision_fails(self) -> None:
        decisions = [_PrereqResult(name=f"d{i}", passed=True) for i in range(10)]
        decisions[5] = _PrereqResult(name="d5", failures=["boom"])
        report = _GateEReport(
            timestamp_utc="x", timestamp_shanghai="y",
            prereq_checks=[_PrereqResult(name=f"p{i}", passed=True) for i in range(5)],
            user_decisions_checks=decisions,
        )
        assert report.all_user_decisions_passed is False
        assert report.gate_e_ready is False

    def test_gate_e_not_ready_if_prereq_count_wrong(self) -> None:
        """Defensive: <5 prereq is unsafe even if all passed."""
        report = _GateEReport(
            timestamp_utc="x", timestamp_shanghai="y",
            prereq_checks=[_PrereqResult(name="p0", passed=True)] * 4,  # only 4
            user_decisions_checks=[_PrereqResult(name=f"d{i}", passed=True) for i in range(10)],
        )
        assert report.all_prereq_passed is False
        assert report.gate_e_ready is False


# ─────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────


class TestRenderReport:
    def _mk_ready_report(self) -> _GateEReport:
        return _GateEReport(
            timestamp_utc="2026-05-17T08:00:00+00:00",
            timestamp_shanghai="2026-05-17T16:00:00+08:00",
            prereq_checks=[
                _PrereqResult(name="paper_mode_5d", passed=True, detail="IC-3a 4/4 ✅"),
                _PrereqResult(name="meta_monitor_0_p0", passed=True, detail="0 P0"),
                _PrereqResult(name="tier_a_adr_full_sediment", passed=True, detail="13 ADRs"),
                _PrereqResult(name="5_sla_satisfied_v3_13_1", passed=True, detail="5 SLA"),
                _PrereqResult(name="10_user_decisions_v3_20_1", passed=True, detail="10 decisions"),
            ],
            user_decisions_checks=[
                _PrereqResult(name=f"d{i}", passed=True, detail="OK")
                for i in range(10)
            ],
        )

    def test_renders_ready_when_gate_e_ready(self) -> None:
        report = render_report(self._mk_ready_report())
        assert "✅ READY" in report
        assert "Gate E ✅ READY for CT-2b transition" in report

    def test_renders_not_ready_when_prereq_fails(self) -> None:
        r = self._mk_ready_report()
        r.prereq_checks[0] = _PrereqResult(name="paper_mode_5d", failures=["boom"])
        rendered = render_report(r)
        assert "❌ NOT READY" in rendered

    def test_renders_5_prereq_table(self) -> None:
        rendered = render_report(self._mk_ready_report())
        assert "§1 5 Prerequisite" in rendered
        assert "paper_mode_5d" in rendered
        assert "meta_monitor_0_p0" in rendered
        assert "tier_a_adr_full_sediment" in rendered
        assert "5_sla_satisfied_v3_13_1" in rendered
        assert "10_user_decisions_v3_20_1" in rendered

    def test_renders_10_user_decisions_table(self) -> None:
        rendered = render_report(self._mk_ready_report())
        assert "§2 10 user 决议" in rendered
        # All 10 decision keywords cited.
        for keyword, _ in _TEN_USER_DECISIONS:
            assert keyword in rendered

    def test_renders_ct_2b_transition_section(self) -> None:
        rendered = render_report(self._mk_ready_report())
        assert "§4 CT-2b prerequisite gate" in rendered
        assert "同意 apply CT-2b" in rendered or "user 显式 trigger" in rendered

    def test_renders_methodology_anchors(self) -> None:
        rendered = render_report(self._mk_ready_report())
        assert "ADR-063" in rendered
        assert "ADR-077" in rendered
        assert "LL-098 X10" in rendered
        assert "LL-164" in rendered
        assert "LL-174" in rendered
        # 红线 sustained.
        assert "LIVE_TRADING_DISABLED=true" in rendered
        assert "EXECUTION_MODE=paper" in rendered

    def test_renders_sediment_cite_section(self) -> None:
        """§3 must list all 5 sediment reports."""
        rendered = render_report(self._mk_ready_report())
        assert "§3 Sediment cite cross-reference" in rendered
        assert "IC-3a" in rendered
        assert "IC-3b" in rendered
        assert "IC-3c" in rendered
        assert "CT-1a" in rendered
        assert "CT-1b" in rendered
