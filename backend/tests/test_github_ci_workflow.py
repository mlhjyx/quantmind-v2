"""GitHub Actions workflow parity tests."""

from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def test_regression_and_matrix_jobs_are_blocking_not_advisory():
    """GitHub CI must not mask regression or matrix failures as advisory passes."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "python scripts/ci_run_phase.py --phase regression --advisory" not in workflow
    assert "python scripts/ci_run_phase.py --phase ci_matrix --advisory" not in workflow
    assert "python scripts/ci_run_phase.py --phase regression" in workflow
    assert "python scripts/ci_run_phase.py --phase ci_matrix" in workflow
