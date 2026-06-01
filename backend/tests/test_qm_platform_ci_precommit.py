"""MVP 4.3 sub-iter 2 (iter 67) — PreCommitOrchestrator tests.

Covers default checks + timeout + structural typing + non-PRE_COMMIT
phase skip semantics. 沿用 batch 3.x mock subprocess pattern.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.ci.orchestrator import CIOrchestrator, CIPhase, CIResult
from backend.qm_platform.ci.precommit import (
    DEFAULT_TIMEOUT_SECONDS,
    PYTEST_COLLECT_TARGETS,
    PYTEST_COLLECT_TIMEOUT_SECONDS,
    PreCommitCheck,
    PreCommitOrchestrator,
    default_checks,
)


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a CompletedProcess-like MagicMock for runner stub."""
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_default_checks_returns_canonical_checks():
    """Default checks include all canonical pre-commit governance checks."""
    checks = default_checks()
    names = [c.name for c in checks]
    assert names == [
        "ruff_check",
        "ruff_format",
        "pytest_collect",
        "check_llm_imports",
        "frontend_api_discipline",
        "backtest_runner_bypass",
    ]


def test_default_timeout_constant():
    """DEFAULT_TIMEOUT_SECONDS is 30 (per spec §4 sub-iter 2)."""
    assert DEFAULT_TIMEOUT_SECONDS == 30
    assert PYTEST_COLLECT_TIMEOUT_SECONDS == 300


def test_pytest_collect_uses_lightweight_targets():
    """Collect gate stays bounded to CI/platform contract tests."""
    pytest_check = next(c for c in default_checks() if c.name == "pytest_collect")
    assert pytest_check.cmd[:3] == ["pytest", "--collect-only", "-q"]
    assert pytest_check.cmd[3:] == PYTEST_COLLECT_TARGETS


def test_pytest_collect_includes_active_governance_inventory_and_hooks():
    """Blocking collect must include active Codex governance inventory + hook behavior tests."""
    required = {
        "backend/tests/test_codex_governance_inventory.py",
        "backend/tests/test_iron_law_enforce_hook.py",
        "backend/tests/test_protect_critical_files_hook.py",
        "backend/tests/test_cite_drift_stop_pretool_hook.py",
        "backend/tests/test_redline_pretool_block_hook.py",
        "backend/tests/test_sediment_poststop_hook.py",
        "backend/tests/test_verify_completion_hook.py",
        "backend/tests/test_session_context_inject_hook.py",
    }

    assert required.issubset(set(PYTEST_COLLECT_TARGETS))


def test_precommit_check_frozen():
    """PreCommitCheck frozen — 反 silent mutation."""
    import dataclasses

    c = PreCommitCheck(name="x", cmd=["ruff", "check"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.name = "y"  # type: ignore[misc]


def test_all_checks_pass_aggregate_passed_true():
    """All checks return rc=0 → CIResult.passed=True."""
    runner = MagicMock(return_value=_mk_completed(returncode=0, stdout="ok"))
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is True
    assert result.phase == CIPhase.PRE_COMMIT
    assert runner.call_count == 6  # 6 default checks


def test_one_check_fails_aggregate_passed_false():
    """If any single check returns nonzero rc, aggregate passed=False."""
    # ruff_check (1st invocation) fails, others pass
    returns = [
        _mk_completed(returncode=1, stderr="ruff lint error"),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=1" in result.details["ruff_check"]


def test_ruff_format_fail():
    """ruff_format failure captured in details."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=1, stderr="format diff"),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=1" in result.details["ruff_format"]


def test_pytest_collect_fail():
    """pytest collect failure captured."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=2, stderr="collection error"),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=2" in result.details["pytest_collect"]


def test_check_llm_imports_fail():
    """check_llm_imports failure captured."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=1, stderr="LLM_IMPORT_VIOLATION"),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=1" in result.details["check_llm_imports"]


def test_frontend_api_discipline_fail():
    """frontend_api_discipline failure captured."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=1, stderr="raw axios"),
        _mk_completed(returncode=0),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=1" in result.details["frontend_api_discipline"]


def test_backtest_runner_bypass_fail():
    """backtest_runner_bypass failure captured."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=0),
        _mk_completed(returncode=1, stderr="direct engine call"),
    ]
    runner = MagicMock(side_effect=returns)
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "rc=1" in result.details["backtest_runner_bypass"]


def test_subprocess_timeout_captured_not_raised():
    """TimeoutExpired → details captures, aggregate passed=False, no raise."""
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["ruff"], timeout=30))
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    # First check (ruff_check) records TIMEOUT
    assert "TIMEOUT after 30s" in result.details["ruff_check"]


def test_oserror_captured_not_raised():
    """OSError (e.g. cmd not found) → details captures, aggregate passed=False."""
    runner = MagicMock(side_effect=FileNotFoundError("ruff not on PATH"))
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is False
    assert "OSError" in result.details["ruff_check"]


def test_duration_ms_recorded():
    """duration_ms is non-negative int (mock fast => ≥ 0)."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0


def test_per_check_duration_ms_in_details():
    """Each check has its own *_duration_ms in details dict."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert "ruff_check_duration_ms" in result.details
    assert "pytest_collect_duration_ms" in result.details


def test_non_pre_commit_phase_skipped():
    """Calling run_phase with non-PRE_COMMIT returns skip result, runner not called."""
    runner = MagicMock()
    orch = PreCommitOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_PUSH)
    assert result.passed is True
    assert result.duration_ms == 0
    assert result.details == {"skipped": "pre_push"}
    runner.assert_not_called()


def test_run_all_returns_single_phase_list():
    """Single-phase orchestrator: run_all returns list of length 1."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PreCommitOrchestrator(runner=runner)
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].phase == CIPhase.PRE_COMMIT


def test_custom_checks_override_defaults():
    """Custom checks list bypasses default_checks."""
    custom = [PreCommitCheck(name="custom_x", cmd=["echo", "hi"], timeout_seconds=5)]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = PreCommitOrchestrator(checks=custom, runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert runner.call_count == 1
    runner.assert_called_with(["echo", "hi"], 5)
    assert "custom_x" in result.details


def test_structural_typing_satisfies_ci_orchestrator_protocol():
    """PreCommitOrchestrator structurally satisfies CIOrchestrator Protocol."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    o: CIOrchestrator = PreCommitOrchestrator(runner=runner)
    assert isinstance(o.run_phase(CIPhase.PRE_COMMIT), CIResult)
    assert isinstance(o.run_all(), list)
