"""MVP 4.3 sub-iter 3 (iter 68) — PrePushOrchestrator tests.

Covers X10 cutover-bias scan (pure Python) + smoke / DataPipeline subprocess
checks (mocked) + timeout + structural typing. 沿用 precommit.py test 体例.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.ci.orchestrator import CIOrchestrator, CIPhase, CIResult
from backend.qm_platform.ci.prepush import (
    DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS,
    DEFAULT_SMOKE_TIMEOUT_SECONDS,
    X10_HARD_PATTERNS,
    PrePushCheck,
    PrePushOrchestrator,
    default_subprocess_checks,
    x10_scan,
)


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ────────────────────────────────────────────────────────────
# X10 cutover-bias scan (pure Python)
# ────────────────────────────────────────────────────────────


def test_x10_hard_patterns_constant():
    """X10_HARD_PATTERNS exists and contains expected core patterns."""
    assert isinstance(X10_HARD_PATTERNS, tuple)
    joined = " | ".join(X10_HARD_PATTERNS)
    assert "schedule" in joined
    assert "paper-mode" in joined
    assert "cutover" in joined


def test_x10_scan_clean_branch_and_commits():
    """No cutover patterns → passed=True, evidence=None."""
    passed, evidence = x10_scan("main", ["feat: add user profile", "fix: race condition"])
    assert passed is True
    assert evidence is None


def test_x10_scan_branch_match():
    """Branch name containing 'paper→live' triggers X10."""
    passed, evidence = x10_scan("feat/paper→live-cutover", ["fix: bug"])
    assert passed is False
    assert evidence is not None
    assert "paper" in evidence.lower() or "X10" in evidence


def test_x10_scan_commit_match():
    """Commit subject containing '/schedule agent' triggers X10."""
    passed, evidence = x10_scan("main", ["chore: /schedule agent for 5d dry-run", "fix: x"])
    assert passed is False
    assert "schedule" in evidence.lower() or "X10" in evidence


def test_x10_scan_paper_mode_5d():
    """'paper-mode 5d' pattern triggers."""
    passed, _ = x10_scan("main", ["test: paper-mode 5d dry-run scheduled"])
    assert passed is False


def test_x10_scan_case_insensitive():
    """Pattern match is case-insensitive (per re.IGNORECASE)."""
    passed, _ = x10_scan("main", ["fix: AUTO CUTOVER scheduled for tonight"])
    assert passed is False


# ────────────────────────────────────────────────────────────
# default_subprocess_checks + timeout constants
# ────────────────────────────────────────────────────────────


def test_default_subprocess_checks_two_entries():
    """smoke_test + datapipeline_guard."""
    checks = default_subprocess_checks()
    names = [c.name for c in checks]
    assert names == ["smoke_test", "datapipeline_guard"]


def test_default_smoke_timeout_90s():
    assert DEFAULT_SMOKE_TIMEOUT_SECONDS == 90


def test_default_datapipeline_timeout_30s():
    assert DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS == 30


def test_prepush_check_frozen():
    """PrePushCheck frozen — 反 silent mutation."""
    import dataclasses

    c = PrePushCheck(name="x", cmd=["echo"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.name = "y"  # type: ignore[misc]


# ────────────────────────────────────────────────────────────
# PrePushOrchestrator.run_phase scenarios
# ────────────────────────────────────────────────────────────


def test_all_checks_pass_aggregate_true():
    """Clean branch + commits + both subprocess checks pass → passed=True."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PrePushOrchestrator(
        runner=runner,
        branch_name="main",
        commit_subjects=["feat: add x", "fix: y"],
    )
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is True
    assert result.phase == CIPhase.PRE_PUSH
    assert result.details["x10_scan"] == "PASS"
    assert runner.call_count == 2  # smoke + datapipeline_guard


def test_x10_scan_fail_aggregate_false():
    """X10 trigger from branch name → aggregate False even if subprocess passes."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PrePushOrchestrator(
        runner=runner,
        branch_name="feat/paper→live-cutover",
        commit_subjects=["fix: x"],
    )
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is False
    assert "X10" in result.details["x10_scan"] or "hit" in result.details["x10_scan"].lower()


def test_smoke_test_fail():
    """smoke subprocess fail → aggregate False."""
    returns = [
        _mk_completed(returncode=1, stderr="60 PASS 1 FAIL"),  # smoke
        _mk_completed(returncode=0),  # datapipeline
    ]
    runner = MagicMock(side_effect=returns)
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=["fix: x"])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is False
    assert "rc=1" in result.details["smoke_test"]


def test_datapipeline_guard_fail():
    """datapipeline_guard subprocess fail → aggregate False."""
    returns = [
        _mk_completed(returncode=0),  # smoke
        _mk_completed(returncode=1, stderr="DataPipeline naked INSERT detected"),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=["fix: x"])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is False
    assert "rc=1" in result.details["datapipeline_guard"]


def test_subprocess_timeout_captured_not_raised():
    """TimeoutExpired → details + aggregate False."""
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=90))
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=["fix: x"])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is False
    assert "TIMEOUT after 90s" in result.details["smoke_test"]


def test_oserror_captured_not_raised():
    """FileNotFoundError → details + aggregate False."""
    runner = MagicMock(side_effect=FileNotFoundError("pytest not on PATH"))
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=["fix: x"])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is False
    assert "OSError" in result.details["smoke_test"]


def test_duration_ms_recorded():
    """duration_ms non-negative int."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=[])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0


def test_non_pre_push_phase_skipped():
    """Non-PRE_PUSH phase → skip result, runner not called, X10 not invoked."""
    runner = MagicMock()
    orch = PrePushOrchestrator(runner=runner, branch_name="paper→live", commit_subjects=[])
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is True
    assert result.details == {"skipped": "pre_commit"}
    runner.assert_not_called()


def test_run_all_returns_single_phase_list():
    """Single-phase orchestrator — list length 1."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=[])
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].phase == CIPhase.PRE_PUSH


def test_structural_typing_satisfies_ci_orchestrator():
    """PrePushOrchestrator structurally satisfies CIOrchestrator Protocol."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    o: CIOrchestrator = PrePushOrchestrator(runner=runner, branch_name="main", commit_subjects=[])
    assert isinstance(o.run_phase(CIPhase.PRE_PUSH), CIResult)
    assert isinstance(o.run_all(), list)


def test_custom_subprocess_checks_override():
    """Custom checks list overrides default."""
    custom = [PrePushCheck(name="custom_z", cmd=["echo", "z"], timeout_seconds=5)]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PrePushOrchestrator(checks=custom, runner=runner, branch_name="main", commit_subjects=[])
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert runner.call_count == 1
    runner.assert_called_with(["echo", "z"], 5)
    assert "custom_z" in result.details
