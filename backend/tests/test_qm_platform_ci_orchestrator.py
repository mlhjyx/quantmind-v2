"""MVP 4.3 sub-iter 1 (iter 66) — qm_platform.ci.orchestrator shape tests.

Covers CIPhase enum + CIResult frozen dataclass + CIOrchestrator Protocol +
helper functions (all_phases_passed / total_duration_ms / phases_in_canonical_order).

Sub-iter 2+ adds implementation tests (PreCommitOrchestrator etc).
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.qm_platform.ci.orchestrator import (
    CIOrchestrator,
    CIPhase,
    CIResult,
    all_phases_passed,
    phases_in_canonical_order,
    total_duration_ms,
)


def test_ciphase_enum_has_five_phases():
    """CIPhase enum exposes exactly 5 phases per spec §2."""
    values = {p.value for p in CIPhase}
    assert values == {"pre_commit", "pre_push", "ci_matrix", "regression", "review"}


def test_ciphase_str_inheritance():
    """CIPhase inherits from str for ergonomic comparison + serialization."""
    assert CIPhase.PRE_COMMIT == "pre_commit"
    assert str(CIPhase.PRE_PUSH) in {"pre_push", "CIPhase.PRE_PUSH"}


def test_ciresult_minimal_construction():
    """CIResult constructs with required fields + details defaults to empty dict."""
    r = CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=1234)
    assert r.phase == CIPhase.PRE_COMMIT
    assert r.passed is True
    assert r.duration_ms == 1234
    assert r.details == {}


def test_ciresult_with_details():
    """CIResult details dict captures phase-specific output."""
    r = CIResult(
        phase=CIPhase.PRE_PUSH,
        passed=False,
        duration_ms=45_000,
        details={"smoke_summary": "60 PASS 1 FAIL", "failed_test": "test_X"},
    )
    assert r.details["smoke_summary"] == "60 PASS 1 FAIL"
    assert r.passed is False


def test_ciresult_frozen():
    """CIResult frozen — 反 silent mutation."""
    r = CIResult(phase=CIPhase.REGRESSION, passed=True, duration_ms=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.passed = False  # type: ignore[misc]


def test_ciresult_details_is_independent_per_instance():
    """default_factory=dict ensures details dict is not shared across instances."""
    r1 = CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=0)
    r2 = CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=0)
    # Construct fresh dict references; mutate r1.details should not leak.
    # (frozen dataclass does not prevent dict mutation, but identity differs.)
    assert r1.details is not r2.details


def test_all_phases_passed_all_true():
    """all_phases_passed returns True when every result.passed is True."""
    results = [
        CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=100),
        CIResult(phase=CIPhase.PRE_PUSH, passed=True, duration_ms=200),
    ]
    assert all_phases_passed(results) is True


def test_all_phases_passed_one_false():
    """all_phases_passed returns False if any result.passed is False."""
    results = [
        CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=100),
        CIResult(phase=CIPhase.PRE_PUSH, passed=False, duration_ms=200),
        CIResult(phase=CIPhase.CI_MATRIX, passed=True, duration_ms=300),
    ]
    assert all_phases_passed(results) is False


def test_all_phases_passed_empty_list_vacuous_true():
    """Empty list → vacuous True (caller handles 0-result edge separately)."""
    assert all_phases_passed([]) is True


def test_total_duration_ms_sum():
    """total_duration_ms sums duration across results."""
    results = [
        CIResult(phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=100),
        CIResult(phase=CIPhase.PRE_PUSH, passed=True, duration_ms=250),
        CIResult(phase=CIPhase.CI_MATRIX, passed=False, duration_ms=1000),
    ]
    assert total_duration_ms(results) == 1350


def test_total_duration_ms_empty_zero():
    """total_duration_ms of empty list = 0."""
    assert total_duration_ms([]) == 0


def test_phases_in_canonical_order():
    """Canonical phase order: pre_commit → pre_push → ci_matrix → regression → review."""
    order = phases_in_canonical_order()
    assert order == [
        CIPhase.PRE_COMMIT,
        CIPhase.PRE_PUSH,
        CIPhase.CI_MATRIX,
        CIPhase.REGRESSION,
        CIPhase.REVIEW,
    ]


def test_ciorchestrator_protocol_structural_typing():
    """Any class with run_phase + run_all matches CIOrchestrator structurally."""

    class StubOrchestrator:
        def run_phase(self, phase: CIPhase) -> CIResult:
            return CIResult(phase=phase, passed=True, duration_ms=0)

        def run_all(self) -> list[CIResult]:
            return [self.run_phase(p) for p in phases_in_canonical_order()]

    o: CIOrchestrator = StubOrchestrator()
    result = o.run_phase(CIPhase.PRE_COMMIT)
    assert isinstance(result, CIResult)
    assert result.passed is True

    results = o.run_all()
    assert len(results) == 5
    assert all_phases_passed(results) is True
