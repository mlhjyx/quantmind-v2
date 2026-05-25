"""MVP 4.3 sub-iter 4 (iter 69) — CIMatrixOrchestrator tests.

Covers MatrixCell + default_matrix + CIMatrixOrchestrator behavior across
all-pass / cell-fail / timeout / empty / custom / structural-typing scenarios.
沿用 precommit/prepush 体例.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.ci.ci_matrix import (
    DEFAULT_CELL_TIMEOUT_SECONDS,
    CIMatrixOrchestrator,
    MatrixCell,
    default_matrix,
)
from backend.qm_platform.ci.orchestrator import CIOrchestrator, CIPhase, CIResult


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ────────────────────────────────────────────────────────────
# MatrixCell + default_matrix
# ────────────────────────────────────────────────────────────


def test_default_matrix_at_least_one_cell():
    """default_matrix returns at least 1 production cell (py3.11 + pg16.8)."""
    cells = default_matrix()
    assert len(cells) >= 1
    cell = cells[0]
    assert cell.python_version == "3.11"
    assert cell.postgres_version == "16.8"


def test_default_cell_timeout_300s():
    """DEFAULT_CELL_TIMEOUT_SECONDS == 300 (5min per cell smoke + buffer)."""
    assert DEFAULT_CELL_TIMEOUT_SECONDS == 300


def test_matrix_cell_frozen():
    """MatrixCell frozen — 反 silent mutation."""
    import dataclasses

    c = MatrixCell(python_version="3.11", postgres_version="16.8")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.python_version = "3.12"  # type: ignore[misc]


def test_matrix_cell_id_normalizes_dots():
    """cell_id replaces dots with underscores for filesystem-safe keys."""
    c = MatrixCell(python_version="3.11", postgres_version="16.8")
    assert c.cell_id == "py3_11_pg16_8"


def test_matrix_cell_default_tags():
    """Default tags = 'smoke and not live_tushare'."""
    c = MatrixCell(python_version="3.11", postgres_version="16.8")
    assert c.tags == "smoke and not live_tushare"


# ────────────────────────────────────────────────────────────
# CIMatrixOrchestrator.run_phase scenarios
# ────────────────────────────────────────────────────────────


def test_all_cells_pass_aggregate_true():
    """All cells subprocess rc=0 → CIResult.passed=True."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    cells = [
        MatrixCell(python_version="3.11", postgres_version="16.8"),
        MatrixCell(python_version="3.12", postgres_version="16.8"),
    ]
    orch = CIMatrixOrchestrator(matrix=cells, runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert result.passed is True
    assert result.phase == CIPhase.CI_MATRIX
    assert runner.call_count == 2
    assert result.details["matrix_size"] == "2"
    assert "py3_11_pg16_8" in result.details
    assert "py3_12_pg16_8" in result.details


def test_one_cell_fail_aggregate_false():
    """One cell rc=1 → aggregate passed=False."""
    returns = [
        _mk_completed(returncode=0),
        _mk_completed(returncode=1, stderr="pytest failure"),
    ]
    runner = MagicMock(side_effect=returns)
    cells = [
        MatrixCell(python_version="3.11", postgres_version="16.8"),
        MatrixCell(python_version="3.12", postgres_version="16.8"),
    ]
    orch = CIMatrixOrchestrator(matrix=cells, runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert result.passed is False
    assert "rc=1" in result.details["py3_12_pg16_8"]


def test_empty_matrix_vacuous_pass():
    """Empty matrix → aggregate passed=True (vacuous, runner not called)."""
    runner = MagicMock()
    orch = CIMatrixOrchestrator(matrix=[], runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert result.passed is True
    assert result.details["matrix_size"] == "0"
    runner.assert_not_called()


def test_subprocess_timeout_captured():
    """TimeoutExpired → details + aggregate False."""
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=300))
    orch = CIMatrixOrchestrator(matrix=default_matrix(), runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert result.passed is False
    assert "TIMEOUT after 300s" in result.details["py3_11_pg16_8"]


def test_oserror_captured():
    """FileNotFoundError → details + aggregate False."""
    runner = MagicMock(side_effect=FileNotFoundError("pytest not on PATH"))
    orch = CIMatrixOrchestrator(matrix=default_matrix(), runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert result.passed is False
    assert "OSError" in result.details["py3_11_pg16_8"]


def test_duration_ms_recorded_per_cell_and_total():
    """duration_ms total + per-cell *_duration_ms in details."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = CIMatrixOrchestrator(matrix=default_matrix(), runner=runner)
    result = orch.run_phase(CIPhase.CI_MATRIX)
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0
    assert "py3_11_pg16_8_duration_ms" in result.details


def test_non_ci_matrix_phase_skipped():
    """Non-CI_MATRIX phase returns skip result; runner not called."""
    runner = MagicMock()
    orch = CIMatrixOrchestrator(runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is True
    assert result.details == {"skipped": "pre_commit"}
    runner.assert_not_called()


def test_run_all_returns_single_phase_list():
    """run_all returns list of length 1 (single-phase orchestrator)."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = CIMatrixOrchestrator(runner=runner)
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].phase == CIPhase.CI_MATRIX


def test_custom_cmd_builder_overrides():
    """Custom cmd_builder is invoked per cell."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    custom_cmd = ["echo", "custom"]
    cells = [MatrixCell(python_version="3.11", postgres_version="16.8")]
    orch = CIMatrixOrchestrator(matrix=cells, runner=runner, cmd_builder=lambda _c: custom_cmd)
    orch.run_phase(CIPhase.CI_MATRIX)
    runner.assert_called_with(custom_cmd, DEFAULT_CELL_TIMEOUT_SECONDS)


def test_structural_typing_satisfies_ci_orchestrator():
    """CIMatrixOrchestrator structurally satisfies CIOrchestrator Protocol."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    o: CIOrchestrator = CIMatrixOrchestrator(runner=runner)
    assert isinstance(o.run_phase(CIPhase.CI_MATRIX), CIResult)
    assert isinstance(o.run_all(), list)


def test_per_cell_timeout_override_used():
    """Per-cell timeout_seconds is propagated to runner."""
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    custom = [
        MatrixCell(python_version="3.11", postgres_version="16.8", timeout_seconds=120),
    ]
    orch = CIMatrixOrchestrator(matrix=custom, runner=runner)
    orch.run_phase(CIPhase.CI_MATRIX)
    # runner was called once with (cmd, 120) — the per-cell timeout override
    assert runner.call_args.args[1] == 120
