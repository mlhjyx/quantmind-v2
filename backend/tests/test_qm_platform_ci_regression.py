"""MVP 4.3 sub-iter 5 (iter 70) — RegressionOrchestrator tests.

Covers compute_max_diff (numeric flatten + diff) + RegressionOrchestrator
behavior (all-pass / diff-fail / shape mismatch / file missing / structural
typing). 沿用 precommit/prepush/ci_matrix 体例.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.ci.orchestrator import CIOrchestrator, CIPhase, CIResult
from backend.qm_platform.ci.regression import (
    MAX_DIFF_THRESHOLD,
    RegressionOrchestrator,
    RegressionPair,
    compute_max_diff,
    default_pairs,
)

# ────────────────────────────────────────────────────────────
# Constants + frozen dataclass
# ────────────────────────────────────────────────────────────


def test_max_diff_threshold_is_zero():
    """MAX_DIFF_THRESHOLD == 0.0 per 铁律 15 hard."""
    assert MAX_DIFF_THRESHOLD == 0.0


def test_default_pairs_at_least_two():
    """default_pairs returns 5yr + 12yr canonical entries."""
    pairs = default_pairs()
    assert len(pairs) >= 2
    labels = {p.label for p in pairs}
    assert "backtest_5yr" in labels
    assert "backtest_12yr" in labels


def test_default_pairs_use_committed_regression_result_artifacts():
    """Default gate must point at committed max_diff result artifacts that exist in CI."""
    by_label = {pair.label: pair for pair in default_pairs()}
    five_year = by_label["backtest_5yr"]
    twelve_year = by_label["backtest_12yr"]

    assert five_year.baseline_path == Path("cache/baseline/regression_result_5yr.json")
    assert five_year.actual_path == five_year.baseline_path
    assert twelve_year.baseline_path == Path("cache/baseline/regression_result_12yr.json")
    assert twelve_year.actual_path == twelve_year.baseline_path


def test_regression_pair_frozen():
    """RegressionPair frozen — 反 silent mutation."""
    import dataclasses

    p = RegressionPair(label="x", baseline_path=Path("b.json"), actual_path=Path("a.json"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.label = "y"  # type: ignore[misc]


# ────────────────────────────────────────────────────────────
# compute_max_diff scenarios
# ────────────────────────────────────────────────────────────


def test_compute_max_diff_identical_dicts():
    """Identical numeric dicts → max_diff=0, offending=None."""
    a = {"sharpe": 0.8659, "mdd": -0.1391, "trades": 1234}
    b = {"sharpe": 0.8659, "mdd": -0.1391, "trades": 1234}
    diff, off = compute_max_diff(a, b)
    assert diff == 0.0
    assert off is None


def test_compute_max_diff_small_diff_returns_value():
    """1e-6 diff returns positive value + offending key."""
    a = {"sharpe": 0.8659000}
    b = {"sharpe": 0.8659001}
    diff, off = compute_max_diff(a, b)
    assert diff == pytest.approx(1e-7, abs=1e-12)
    assert off == "sharpe"


def test_compute_max_diff_nested_structures():
    """Nested dicts flatten correctly with dotted keys."""
    a = {"folds": [{"sharpe": 0.5}, {"sharpe": 0.7}], "meta": {"n": 10}}
    b = {"folds": [{"sharpe": 0.5}, {"sharpe": 0.8}], "meta": {"n": 10}}
    diff, off = compute_max_diff(a, b)
    assert diff == pytest.approx(0.1)
    assert "folds[1].sharpe" in off


def test_compute_max_diff_shape_mismatch_returns_infinity():
    """Missing key on either side → inf diff."""
    a = {"x": 1.0}
    b = {"x": 1.0, "y": 2.0}
    diff, off = compute_max_diff(a, b)
    assert diff == float("inf")
    assert off == "y"


def test_compute_max_diff_ignores_non_numeric():
    """Non-numeric leaves (strings) are silently dropped."""
    a = {"sharpe": 0.5, "git_commit": "abc123"}
    b = {"sharpe": 0.5, "git_commit": "def456"}
    diff, off = compute_max_diff(a, b)
    assert diff == 0.0
    assert off is None


def test_compute_max_diff_empty_inputs():
    """Both empty → max_diff=0 vacuous match."""
    diff, off = compute_max_diff({}, {})
    assert diff == 0.0
    assert off is None


def test_compute_max_diff_ignores_booleans():
    """bool is subclass of int but not a quant metric — silently dropped."""
    a = {"passed": True, "sharpe": 0.5}
    b = {"passed": False, "sharpe": 0.5}
    diff, off = compute_max_diff(a, b)
    assert diff == 0.0
    assert off is None


# ────────────────────────────────────────────────────────────
# RegressionOrchestrator.run_phase scenarios
# ────────────────────────────────────────────────────────────


def _make_loader(data_by_path: dict[Path, dict]):
    """Build a file_loader closure returning in-memory dicts per path."""

    def loader(path: Path) -> dict:
        if path not in data_by_path:
            raise FileNotFoundError(str(path))
        return data_by_path[path]

    return loader


def test_all_pairs_match_aggregate_true():
    """Both pairs baseline == actual → passed=True."""
    pairs = [
        RegressionPair(label="p1", baseline_path=Path("b1.json"), actual_path=Path("a1.json")),
        RegressionPair(label="p2", baseline_path=Path("b2.json"), actual_path=Path("a2.json")),
    ]
    data = {
        Path("b1.json"): {"sharpe": 0.5},
        Path("a1.json"): {"sharpe": 0.5},
        Path("b2.json"): {"sharpe": 0.7},
        Path("a2.json"): {"sharpe": 0.7},
    }
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data))
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is True
    assert result.details["pair_count"] == "2"
    assert "max_diff=0" in result.details["p1"]


def test_one_pair_diff_aggregate_false():
    """One pair diff > 0 → aggregate False."""
    pairs = [
        RegressionPair(label="p1", baseline_path=Path("b1.json"), actual_path=Path("a1.json")),
    ]
    data = {
        Path("b1.json"): {"sharpe": 0.5},
        Path("a1.json"): {"sharpe": 0.6},
    }
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data))
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is False
    assert "sharpe" in result.details["p1"]


def test_single_artifact_nonzero_max_diff_fails():
    """Committed result artifacts are valid only when their recorded max_diff is zero."""
    pairs = [
        RegressionPair(
            label="p1",
            baseline_path=Path("regression_result.json"),
            actual_path=Path("regression_result.json"),
        )
    ]
    data = {Path("regression_result.json"): {"run1": {"max_diff": 0.0001}}}
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data))

    result = orch.run_phase(CIPhase.REGRESSION)

    assert result.passed is False
    assert "max_diff=0.0001" in result.details["p1"]


def test_default_regression_artifacts_pass_in_current_worktree():
    """Default regression phase is blocking-capable in GitHub Actions now."""
    result = RegressionOrchestrator().run_phase(CIPhase.REGRESSION)

    assert result.passed is True
    assert "max_diff=0.0" in result.details["backtest_5yr"]
    assert "max_diff=0.0" in result.details["backtest_12yr"]


def test_file_missing_captured_as_failure():
    """FileNotFoundError → details capture + aggregate False."""
    pairs = [
        RegressionPair(
            label="missing", baseline_path=Path("nope.json"), actual_path=Path("nope.json")
        ),
    ]
    loader = MagicMock(side_effect=FileNotFoundError("nope.json"))
    orch = RegressionOrchestrator(pairs=pairs, file_loader=loader)
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is False
    assert "FILE_MISSING" in result.details["missing"]


def test_json_decode_error_captured():
    """JSONDecodeError → LOAD_ERROR captured + aggregate False."""
    pairs = [
        RegressionPair(label="bad", baseline_path=Path("bad.json"), actual_path=Path("bad.json")),
    ]
    loader = MagicMock(side_effect=json.JSONDecodeError("bad", "doc", 0))
    orch = RegressionOrchestrator(pairs=pairs, file_loader=loader)
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is False
    assert "LOAD_ERROR" in result.details["bad"]


def test_non_regression_phase_skipped():
    """Non-REGRESSION phase → skip result; loader not called."""
    loader = MagicMock()
    orch = RegressionOrchestrator(file_loader=loader)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is True
    assert result.details == {"skipped": "pre_commit"}
    loader.assert_not_called()


def test_run_all_returns_single_phase_list():
    """run_all returns list of length 1."""
    pairs = [
        RegressionPair(label="p1", baseline_path=Path("b1.json"), actual_path=Path("a1.json")),
    ]
    data = {Path("b1.json"): {"x": 1.0}, Path("a1.json"): {"x": 1.0}}
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data))
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].phase == CIPhase.REGRESSION


def test_structural_typing_satisfies_ci_orchestrator():
    """RegressionOrchestrator structurally satisfies CIOrchestrator."""
    loader = MagicMock(return_value={})
    o: CIOrchestrator = RegressionOrchestrator(pairs=[], file_loader=loader)
    assert isinstance(o.run_phase(CIPhase.REGRESSION), CIResult)
    assert isinstance(o.run_all(), list)


def test_custom_threshold_allows_small_diff():
    """threshold=1e-6 allows tiny diff to pass."""
    pairs = [
        RegressionPair(label="p1", baseline_path=Path("b1.json"), actual_path=Path("a1.json")),
    ]
    data = {
        Path("b1.json"): {"sharpe": 0.50000001},
        Path("a1.json"): {"sharpe": 0.50000002},
    }
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data), threshold=1e-6)
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is True


def test_per_pair_duration_ms_in_details():
    """Per-pair *_duration_ms in details."""
    pairs = [
        RegressionPair(label="p1", baseline_path=Path("b1.json"), actual_path=Path("a1.json")),
    ]
    data = {Path("b1.json"): {"x": 1.0}, Path("a1.json"): {"x": 1.0}}
    orch = RegressionOrchestrator(pairs=pairs, file_loader=_make_loader(data))
    result = orch.run_phase(CIPhase.REGRESSION)
    assert "p1_duration_ms" in result.details


def test_empty_pairs_vacuous_pass():
    """Empty pairs list → aggregate True (vacuous)."""
    loader = MagicMock()
    orch = RegressionOrchestrator(pairs=[], file_loader=loader)
    result = orch.run_phase(CIPhase.REGRESSION)
    assert result.passed is True
    assert result.details["pair_count"] == "0"
    loader.assert_not_called()
