"""MVP 4.3 sub-iter 7 (iter 72) — scripts/ci_run_phase.py entry script tests.

Covers argparse rejection / orchestrator selection / exit code mapping /
top-level fail-soft (铁律 33 tier-2) via stack-trace-to-stderr.

The entry script is a thin orchestrator dispatcher — these tests exercise
the dispatch logic + fail-soft. The 5 phase orchestrators themselves have
their own dedicated tests (test_qm_platform_ci_*.py).
"""

from __future__ import annotations

# Ensure repo root on sys.path so `scripts.ci_run_phase` resolves
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import ci_run_phase  # noqa: E402


def test_phase_choices_constant():
    """PHASE_CHOICES enumerates all 5 phases."""
    assert ci_run_phase.PHASE_CHOICES == (
        "pre_commit",
        "pre_push",
        "ci_matrix",
        "regression",
        "review",
    )


def test_argparse_rejects_invalid_phase(capsys):
    """Invalid --phase value → SystemExit (argparse rejection)."""
    with pytest.raises(SystemExit):
        ci_run_phase.main(["--phase", "invalid_x"])


def test_argparse_requires_phase():
    """Missing --phase → SystemExit."""
    with pytest.raises(SystemExit):
        ci_run_phase.main([])


def test_exit_code_0_when_phase_passes():
    """Orchestrator returns passed=True → exit 0."""
    from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

    fake_result = CIResult(
        phase=CIPhase.PRE_COMMIT, passed=True, duration_ms=10, details={"ok": "1"}
    )
    fake_orch = MagicMock()
    fake_orch.run_phase = MagicMock(return_value=fake_result)

    with patch.object(ci_run_phase, "_build_orchestrator", return_value=fake_orch):
        exit_code = ci_run_phase.main(["--phase", "pre_commit"])
    assert exit_code == 0
    fake_orch.run_phase.assert_called_once()


def test_exit_code_1_when_phase_fails():
    """Orchestrator returns passed=False → exit 1."""
    from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

    fake_result = CIResult(
        phase=CIPhase.PRE_PUSH, passed=False, duration_ms=10, details={"err": "x"}
    )
    fake_orch = MagicMock()
    fake_orch.run_phase = MagicMock(return_value=fake_result)

    with patch.object(ci_run_phase, "_build_orchestrator", return_value=fake_orch):
        exit_code = ci_run_phase.main(["--phase", "pre_push"])
    assert exit_code == 1


def test_advisory_failure_logs_but_exits_0(capsys):
    """--advisory keeps structured phase failures visible without failing CI."""
    from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

    fake_result = CIResult(
        phase=CIPhase.REGRESSION,
        passed=False,
        duration_ms=10,
        details={"baseline": "FILE_MISSING"},
    )
    fake_orch = MagicMock()
    fake_orch.run_phase = MagicMock(return_value=fake_result)

    with patch.object(ci_run_phase, "_build_orchestrator", return_value=fake_orch):
        exit_code = ci_run_phase.main(["--phase", "regression", "--advisory"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "status=ADVISORY_FAIL" in captured.out
    assert "structured failure captured" in captured.out


def test_exit_code_1_on_uncaught_exception(capsys):
    """Uncaught exception in orchestrator → exit 1 + stderr stack trace (铁律 33 tier-2)."""
    with patch.object(ci_run_phase, "_build_orchestrator", side_effect=RuntimeError("boom")):
        exit_code = ci_run_phase.main(["--phase", "regression"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "boom" in captured.err


def test_advisory_does_not_swallow_uncaught_exception(capsys):
    """--advisory only covers structured CIResult failures, not broken runners."""
    with patch.object(ci_run_phase, "_build_orchestrator", side_effect=RuntimeError("boom")):
        exit_code = ci_run_phase.main(["--phase", "regression", "--advisory"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "boom" in captured.err


def test_build_orchestrator_dispatch_per_phase():
    """Each phase string maps to its corresponding orchestrator class."""
    args = MagicMock()
    args.branch = "main"
    args.commit_subjects = []
    args.pr_number = None
    args.findings_json = None

    from backend.qm_platform.ci import (
        CIMatrixOrchestrator,
        PreCommitOrchestrator,
        PrePushOrchestrator,
        RegressionOrchestrator,
        ReviewOrchestrator,
    )

    assert isinstance(ci_run_phase._build_orchestrator("pre_commit", args), PreCommitOrchestrator)
    assert isinstance(ci_run_phase._build_orchestrator("pre_push", args), PrePushOrchestrator)
    assert isinstance(ci_run_phase._build_orchestrator("ci_matrix", args), CIMatrixOrchestrator)
    assert isinstance(ci_run_phase._build_orchestrator("regression", args), RegressionOrchestrator)
    assert isinstance(ci_run_phase._build_orchestrator("review", args), ReviewOrchestrator)


def test_build_orchestrator_unknown_phase_raises():
    """Unknown phase string → ValueError."""
    with pytest.raises(ValueError, match="unknown phase"):
        ci_run_phase._build_orchestrator("nope", MagicMock())
