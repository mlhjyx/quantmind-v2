"""MVP 4.3 sub-iter 6 (iter 71) — ReviewOrchestrator tests.

Covers SEVERITY_LEVELS + ReviewFinding + format_findings_as_comment +
ReviewOrchestrator behavior (severity-gating / gh subprocess wrapping /
fail-soft / structural typing). 沿用 precommit/prepush/ci_matrix/regression 体例.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.ci.orchestrator import CIOrchestrator, CIPhase, CIResult
from backend.qm_platform.ci.review import (
    DEFAULT_GH_TIMEOUT_SECONDS,
    SEVERITY_LEVELS,
    SEVERITY_ORDER,
    ReviewFinding,
    ReviewOrchestrator,
    format_findings_as_comment,
)


def _mk_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ────────────────────────────────────────────────────────────
# Constants + frozen dataclass + formatter
# ────────────────────────────────────────────────────────────


def test_severity_levels_ordered():
    """SEVERITY_LEVELS is P0 → P3 in severity descending order."""
    assert SEVERITY_LEVELS == ("P0", "P1", "P2", "P3")


def test_severity_order_p0_lowest_index():
    """SEVERITY_ORDER maps P0→0 (most severe = lowest index)."""
    assert SEVERITY_ORDER["P0"] == 0
    assert SEVERITY_ORDER["P3"] == 3


def test_default_gh_timeout():
    assert DEFAULT_GH_TIMEOUT_SECONDS == 30


def test_review_finding_frozen():
    """ReviewFinding frozen — 反 silent mutation."""
    import dataclasses

    f = ReviewFinding(severity="P1", file_path="x.py", line=10, message="msg")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.severity = "P0"  # type: ignore[misc]


def test_format_empty_findings():
    """Empty findings → 'No findings.' sentinel."""
    assert format_findings_as_comment([]) == "No findings."


def test_format_single_finding():
    """Single P1 finding produces markdown with header + bullet."""
    findings = [ReviewFinding(severity="P1", file_path="foo.py", line=42, message="leak")]
    out = format_findings_as_comment(findings)
    assert "## CI Review Findings" in out
    assert "### P1 (1)" in out
    assert "`foo.py:42`" in out
    assert "leak" in out


def test_format_multi_severity_groups():
    """Multi-severity findings grouped in P0→P3 order."""
    findings = [
        ReviewFinding(severity="P2", file_path="a.py", line=1, message="x"),
        ReviewFinding(severity="P0", file_path="b.py", line=2, message="y"),
        ReviewFinding(severity="P0", file_path="c.py", line=0, message="file-level"),
    ]
    out = format_findings_as_comment(findings)
    # P0 group should appear before P2 group
    p0_pos = out.find("### P0")
    p2_pos = out.find("### P2")
    assert 0 <= p0_pos < p2_pos
    assert "### P0 (2)" in out
    # line=0 → file-level format (no :0 suffix)
    assert "`c.py`" in out and "`c.py:0`" not in out


# ────────────────────────────────────────────────────────────
# ReviewOrchestrator.run_phase scenarios
# ────────────────────────────────────────────────────────────


def test_no_findings_aggregate_true_runner_skipped():
    """Empty findings + no pr_number → passed=True, runner not called."""
    runner = MagicMock()
    orch = ReviewOrchestrator(findings=[], runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is True
    assert result.details["findings_count"] == "0"
    assert "SKIPPED" in result.details["gh_post"]
    runner.assert_not_called()


def test_all_p3_findings_aggregate_true():
    """All P3 (warnings) findings + block_at=P1 → passed=True."""
    findings = [
        ReviewFinding(severity="P3", file_path="a.py", line=1, message="x"),
        ReviewFinding(severity="P3", file_path="b.py", line=2, message="y"),
    ]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is True
    assert result.details["blocking"] == "False"


def test_any_p0_aggregate_false():
    """Any P0 finding → blocking + passed=False."""
    findings = [
        ReviewFinding(severity="P0", file_path="x.py", line=1, message="leak"),
    ]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False
    assert result.details["blocking"] == "True"


def test_any_p1_aggregate_false():
    """Any P1 finding + default block_at=P1 → blocking."""
    findings = [
        ReviewFinding(severity="P1", file_path="x.py", line=1, message="x"),
        ReviewFinding(severity="P3", file_path="y.py", line=2, message="y"),
    ]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False


def test_custom_block_at_p2_more_strict():
    """block_at='P2' → P2 findings now blocking."""
    findings = [
        ReviewFinding(severity="P2", file_path="x.py", line=1, message="x"),
    ]
    runner = MagicMock(return_value=_mk_completed(returncode=0))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner, block_at="P2")
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False


def test_invalid_block_at_raises():
    """Invalid block_at → ValueError on construction."""
    with pytest.raises(ValueError, match="block_at must be one of"):
        ReviewOrchestrator(block_at="P9")


def test_gh_subprocess_fail_captured():
    """gh subprocess rc != 0 → passed=False + gh_post details."""
    findings = [ReviewFinding(severity="P3", file_path="x.py", line=1, message="x")]
    runner = MagicMock(return_value=_mk_completed(returncode=1, stderr="gh: not authed"))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False
    assert "gh_rc=1" in result.details["gh_post"]


def test_gh_subprocess_timeout():
    """gh timeout → captured + passed=False."""
    findings = [ReviewFinding(severity="P3", file_path="x.py", line=1, message="x")]
    runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False
    assert "TIMEOUT after 30s" in result.details["gh_post"]


def test_gh_oserror_captured():
    """gh not on PATH → OSError captured."""
    findings = [ReviewFinding(severity="P3", file_path="x.py", line=1, message="x")]
    runner = MagicMock(side_effect=FileNotFoundError("gh not on PATH"))
    orch = ReviewOrchestrator(findings=findings, pr_number=123, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is False
    assert "OSError" in result.details["gh_post"]


def test_no_pr_number_skips_gh():
    """findings but no pr_number → gh not invoked, passed depends only on severity."""
    findings = [ReviewFinding(severity="P3", file_path="x.py", line=1, message="x")]
    runner = MagicMock()
    orch = ReviewOrchestrator(findings=findings, pr_number=None, runner=runner)
    result = orch.run_phase(CIPhase.REVIEW)
    assert result.passed is True
    runner.assert_not_called()
    assert "SKIPPED" in result.details["gh_post"]


def test_non_review_phase_skipped():
    """Non-REVIEW phase → skip result."""
    runner = MagicMock()
    orch = ReviewOrchestrator(findings=[], runner=runner)
    result = orch.run_phase(CIPhase.PRE_COMMIT)
    assert result.passed is True
    assert result.details == {"skipped": "pre_commit"}
    runner.assert_not_called()


def test_run_all_returns_single_phase_list():
    """run_all returns list of length 1."""
    orch = ReviewOrchestrator(findings=[])
    results = orch.run_all()
    assert len(results) == 1
    assert results[0].phase == CIPhase.REVIEW


def test_structural_typing_satisfies_ci_orchestrator():
    """ReviewOrchestrator structurally satisfies CIOrchestrator."""
    o: CIOrchestrator = ReviewOrchestrator(findings=[])
    assert isinstance(o.run_phase(CIPhase.REVIEW), CIResult)
    assert isinstance(o.run_all(), list)
