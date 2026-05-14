"""V3 §8.3 RiskReflector candidate approve/reject e2e flow tests (TB-4d).

Coverage:
  - webhook_parser.parse_candidate_command — approve/reject/批准/拒绝 + fail-loud
  - ReflectionCandidateService.process_candidate_command — approve/reject
    sediment + idempotency + report-not-found + index-out-of-range + event path
  - _parse_candidate_id / _resolve_report_path / _extract_candidate_text helpers
  - scripts/generate_risk_candidate_pr.py — _redline_self_check (PASS + VIOLATION
    abort) + _scan_pending_approved + _mark_pr_generated + dry-run flow (tmp git repo)

LL-159 4-step preflight sustained — unit tests with tmp_path file sediment +
tmp git repo for script dry-run, 0 LLM / 0 real DingTalk / 0 production git.
Sustained TB-2c/TB-3/TB-4 mock 体例.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.risk.reflection_candidate_service import (
    CandidateOutcome,
    ReflectionCandidateError,
    ReflectionCandidateService,
    _extract_candidate_text,
    _parse_candidate_id,
    _resolve_report_path,
)
from backend.qm_platform.risk.execution.webhook_parser import (
    CandidateCommand,
    ParsedCandidateWebhook,
    WebhookParseError,
    WebhookParseErrorCode,
    parse_candidate_command,
)

_NOW = datetime(2026, 5, 14, 19, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers — build a minimal reflection report markdown
# ---------------------------------------------------------------------------


def _write_report(
    reflections_dir: Path,
    period_label: str,
    *,
    candidates_per_dim: dict[str, list[str]] | None = None,
    event_subdir: bool = False,
) -> Path:
    """Write a minimal reflection report markdown with 改进候选 blocks.

    candidates_per_dim maps dimension → list of candidate strings. The global
    candidate index counts across dimensions in dict insertion order (which
    mirrors ReflectionDimension enum order in production).
    """
    if candidates_per_dim is None:
        candidates_per_dim = {
            "detection": ["detection 候选 1"],
            "threshold": ["RT_RAPID_DROP_5MIN 5% → 5.5%", "threshold 候选 2"],
            "action": ["STAGED default 30min → 45min"],
        }
    lines = [f"# RiskReflector 反思报告 — {period_label}", "", "## 综合摘要", "", "摘要.", ""]
    for dim, cands in candidates_per_dim.items():
        lines.append(f"## {dim.capitalize()}")
        lines.append("")
        lines.append(f"{dim} 摘要.")
        lines.append("")
        if cands:
            lines.append("**改进候选**:")
            lines.extend(f"- {c}" for c in cands)
            lines.append("")
    content = "\n".join(lines)

    if event_subdir:
        target_dir = reflections_dir / "event"
        target_dir.mkdir(parents=True, exist_ok=True)
        # event period_label = event-<date>-<slug> → file event/<date>_<slug>.md
        # parse: event-2026-05-14-limitdown → 2026-05-14_limitdown.md
        rest = period_label[len("event-") :]
        date_str = rest[:10]
        slug = rest[11:]
        path = target_dir / f"{date_str}_{slug}.md"
    else:
        reflections_dir.mkdir(parents=True, exist_ok=True)
        path = reflections_dir / f"{period_label}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_candidate_command
# ---------------------------------------------------------------------------


class TestParseCandidateCommand:
    def test_approve_happy_path(self) -> None:
        result = parse_candidate_command("approve 2026_W19#1")
        assert result.command is CandidateCommand.APPROVE
        assert result.candidate_id == "2026_W19#1"

    def test_reject_happy_path(self) -> None:
        result = parse_candidate_command("reject 2026_05#3")
        assert result.command is CandidateCommand.REJECT
        assert result.candidate_id == "2026_05#3"

    def test_chinese_verbs(self) -> None:
        assert parse_candidate_command("批准 2026_W19#1").command is CandidateCommand.APPROVE
        assert parse_candidate_command("拒绝 2026_W19#2").command is CandidateCommand.REJECT

    def test_case_insensitive_verb(self) -> None:
        assert parse_candidate_command("APPROVE 2026_W19#1").command is CandidateCommand.APPROVE
        assert parse_candidate_command("ReJeCt 2026_W19#1").command is CandidateCommand.REJECT

    def test_event_candidate_id(self) -> None:
        result = parse_candidate_command("approve event-2026-05-14-limitdown#2")
        assert result.candidate_id == "event-2026-05-14-limitdown#2"

    def test_empty_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_candidate_command("")
        assert exc.value.code is WebhookParseErrorCode.MALFORMED_BODY

    def test_unknown_verb_raises(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_candidate_command("confirm 2026_W19#1")
        assert exc.value.code is WebhookParseErrorCode.UNKNOWN_COMMAND

    def test_missing_index_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_candidate_command("approve 2026_W19")
        assert exc.value.code is WebhookParseErrorCode.MALFORMED_BODY

    def test_path_traversal_blocked(self) -> None:
        # '../' contains '/' '.' which \w+\- excludes — regex won't match.
        with pytest.raises(WebhookParseError) as exc:
            parse_candidate_command("approve ../../../etc/passwd#1")
        assert exc.value.code is WebhookParseErrorCode.MALFORMED_BODY


# ---------------------------------------------------------------------------
# _parse_candidate_id / _resolve_report_path / _extract_candidate_text
# ---------------------------------------------------------------------------


class TestParseCandidateId:
    def test_weekly(self) -> None:
        assert _parse_candidate_id("2026_W19#3") == ("2026_W19", 3)

    def test_event_label_with_dashes(self) -> None:
        label, idx = _parse_candidate_id("event-2026-05-14-limitdown#2")
        assert label == "event-2026-05-14-limitdown"
        assert idx == 2

    def test_missing_hash_raises(self) -> None:
        with pytest.raises(ReflectionCandidateError, match="missing '#'"):
            _parse_candidate_id("2026_W19")

    def test_non_integer_index_raises(self) -> None:
        with pytest.raises(ReflectionCandidateError, match="not an integer"):
            _parse_candidate_id("2026_W19#abc")

    def test_zero_index_raises(self) -> None:
        with pytest.raises(ReflectionCandidateError, match="must be ≥ 1"):
            _parse_candidate_id("2026_W19#0")


class TestResolveReportPath:
    def test_weekly_report(self, tmp_path: Path) -> None:
        _write_report(tmp_path, "2026_W19")
        path = _resolve_report_path("2026_W19", tmp_path)
        assert path.name == "2026_W19.md"

    def test_event_report_subdir(self, tmp_path: Path) -> None:
        _write_report(tmp_path, "event-2026-05-14-limitdown", event_subdir=True)
        path = _resolve_report_path("event-2026-05-14-limitdown", tmp_path)
        assert path.parent.name == "event"
        assert path.name == "2026-05-14_limitdown.md"

    def test_report_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ReflectionCandidateError, match="source report not found"):
            _resolve_report_path("2026_W99", tmp_path)


class TestExtractCandidateText:
    def test_extract_global_index(self, tmp_path: Path) -> None:
        # detection:1 / threshold:2 / action:1 → global indices 1,2,3,4
        report = _write_report(tmp_path, "2026_W19")
        assert _extract_candidate_text(report, 1) == "detection 候选 1"
        assert _extract_candidate_text(report, 2) == "RT_RAPID_DROP_5MIN 5% → 5.5%"
        assert _extract_candidate_text(report, 3) == "threshold 候选 2"
        assert _extract_candidate_text(report, 4) == "STAGED default 30min → 45min"

    def test_index_out_of_range_raises(self, tmp_path: Path) -> None:
        report = _write_report(tmp_path, "2026_W19")  # 4 candidates total
        with pytest.raises(ReflectionCandidateError, match="out of range"):
            _extract_candidate_text(report, 5)


# ---------------------------------------------------------------------------
# ReflectionCandidateService.process_candidate_command
# ---------------------------------------------------------------------------


class TestProcessCandidateCommand:
    def _service(self, tmp_path: Path) -> tuple[ReflectionCandidateService, Path, Path]:
        reflections_dir = tmp_path / "risk_reflections"
        risk_findings_dir = tmp_path / "risk_findings"
        svc = ReflectionCandidateService(
            reflections_dir=reflections_dir, risk_findings_dir=risk_findings_dir
        )
        return svc, reflections_dir, risk_findings_dir

    def test_approve_sediments_record(self, tmp_path: Path) -> None:
        svc, reflections_dir, risk_findings_dir = self._service(tmp_path)
        _write_report(reflections_dir, "2026_W19")
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE, candidate_id="2026_W19#2"
        )
        result = svc.process_candidate_command(parsed, now=_NOW)
        assert result.outcome is CandidateOutcome.APPROVED_SEDIMENTED
        assert result.sediment_path is not None
        sediment = Path(result.sediment_path)
        assert sediment.exists()
        content = sediment.read_text(encoding="utf-8")
        assert "status: approved" in content
        assert "candidate_id: 2026_W19#2" in content
        assert "RT_RAPID_DROP_5MIN 5% → 5.5%" in content
        assert "pr_generated: false" in content

    def test_reject_sediments_record(self, tmp_path: Path) -> None:
        svc, reflections_dir, _ = self._service(tmp_path)
        _write_report(reflections_dir, "2026_W19")
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.REJECT, candidate_id="2026_W19#1"
        )
        result = svc.process_candidate_command(parsed, now=_NOW)
        assert result.outcome is CandidateOutcome.REJECTED_SEDIMENTED
        content = Path(result.sediment_path).read_text(encoding="utf-8")
        assert "status: rejected" in content
        assert "长尾留存" in content

    def test_idempotent_re_reply(self, tmp_path: Path) -> None:
        svc, reflections_dir, _ = self._service(tmp_path)
        _write_report(reflections_dir, "2026_W19")
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE, candidate_id="2026_W19#1"
        )
        first = svc.process_candidate_command(parsed, now=_NOW)
        assert first.outcome is CandidateOutcome.APPROVED_SEDIMENTED
        # Re-reply same candidate_id → idempotent, no overwrite.
        second = svc.process_candidate_command(parsed, now=_NOW)
        assert second.outcome is CandidateOutcome.ALREADY_DECIDED
        assert second.sediment_path is None

    def test_event_candidate(self, tmp_path: Path) -> None:
        svc, reflections_dir, _ = self._service(tmp_path)
        _write_report(reflections_dir, "event-2026-05-14-limitdown", event_subdir=True)
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE,
            candidate_id="event-2026-05-14-limitdown#1",
        )
        result = svc.process_candidate_command(parsed, now=_NOW)
        assert result.outcome is CandidateOutcome.APPROVED_SEDIMENTED

    def test_report_not_found_raises(self, tmp_path: Path) -> None:
        svc, _, _ = self._service(tmp_path)
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE, candidate_id="2026_W99#1"
        )
        with pytest.raises(ReflectionCandidateError, match="source report not found"):
            svc.process_candidate_command(parsed, now=_NOW)

    def test_index_out_of_range_raises(self, tmp_path: Path) -> None:
        svc, reflections_dir, _ = self._service(tmp_path)
        _write_report(reflections_dir, "2026_W19")  # 4 candidates
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE, candidate_id="2026_W19#99"
        )
        with pytest.raises(ReflectionCandidateError, match="out of range"):
            svc.process_candidate_command(parsed, now=_NOW)

    def test_naive_now_raises(self, tmp_path: Path) -> None:
        svc, reflections_dir, _ = self._service(tmp_path)
        _write_report(reflections_dir, "2026_W19")
        parsed = ParsedCandidateWebhook(
            command=CandidateCommand.APPROVE, candidate_id="2026_W19#1"
        )
        with pytest.raises(ValueError, match="now must be tz-aware"):
            svc.process_candidate_command(parsed, now=datetime(2026, 5, 14, 19, 0))


# ---------------------------------------------------------------------------
# scripts/generate_risk_candidate_pr.py
# ---------------------------------------------------------------------------


def _load_pr_script():
    """Import scripts/generate_risk_candidate_pr.py as a module."""
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "generate_risk_candidate_pr.py"
    )
    spec = importlib.util.spec_from_file_location("generate_risk_candidate_pr", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_risk_candidate_pr"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPrScriptRedlineSelfCheck:
    def test_redline_pass_risk_findings_only(self) -> None:
        mod = _load_pr_script()
        # Only risk_findings/ paths → PASS (no raise).
        mod._redline_self_check(
            [
                "docs/research-kb/risk_findings/2026-05-14_2026_W19_idx1_approved.md",
                "docs/research-kb/risk_findings/2026-05-14_2026_W19_idx2_approved.md",
            ]
        )

    def test_redline_abort_on_env_mutation(self) -> None:
        mod = _load_pr_script()
        with pytest.raises(RuntimeError, match="RED-LINE SELF-CHECK FAILED"):
            mod._redline_self_check(
                ["docs/research-kb/risk_findings/x.md", "backend/.env"]
            )

    def test_redline_abort_on_backend_production(self) -> None:
        mod = _load_pr_script()
        with pytest.raises(RuntimeError, match="RED-LINE SELF-CHECK FAILED"):
            mod._redline_self_check(["backend/app/services/risk/foo.py"])

    def test_redline_abort_on_configs(self) -> None:
        mod = _load_pr_script()
        with pytest.raises(RuntimeError, match="RED-LINE SELF-CHECK FAILED"):
            mod._redline_self_check(["configs/pt_live.yaml"])

    def test_redline_abort_on_outside_path(self) -> None:
        mod = _load_pr_script()
        with pytest.raises(RuntimeError, match="outside"):
            mod._redline_self_check(["docs/some_other_dir/file.md"])


class TestPrScriptScanAndMark:
    def test_scan_pending_approved(self, tmp_path: Path) -> None:
        mod = _load_pr_script()
        rf_dir = tmp_path / "risk_findings"
        rf_dir.mkdir()
        # approved + pending
        (rf_dir / "2026-05-14_a_approved.md").write_text(
            "---\npr_generated: false\n---\n", encoding="utf-8"
        )
        # approved but already PR'd
        (rf_dir / "2026-05-14_b_approved.md").write_text(
            "---\npr_generated: true\n---\n", encoding="utf-8"
        )
        # rejected — never PR'd
        (rf_dir / "2026-05-14_c_rejected.md").write_text(
            "---\npr_generated: false\n---\n", encoding="utf-8"
        )
        pending = mod._scan_pending_approved(rf_dir)
        assert len(pending) == 1
        assert pending[0].name == "2026-05-14_a_approved.md"

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        mod = _load_pr_script()
        assert mod._scan_pending_approved(tmp_path / "nonexistent") == []

    def test_mark_pr_generated(self, tmp_path: Path) -> None:
        mod = _load_pr_script()
        rec = tmp_path / "rec.md"
        rec.write_text("---\npr_generated: false\n---\nbody", encoding="utf-8")
        mod._mark_pr_generated(rec)
        assert "pr_generated: true" in rec.read_text(encoding="utf-8")

    def test_mark_pr_generated_missing_marker_raises(self, tmp_path: Path) -> None:
        mod = _load_pr_script()
        rec = tmp_path / "rec.md"
        rec.write_text("---\npr_generated: true\n---\nbody", encoding="utf-8")
        with pytest.raises(RuntimeError, match="marker not found"):
            mod._mark_pr_generated(rec)


class TestPrScriptDryRun:
    def test_dry_run_in_tmp_git_repo(self, tmp_path: Path) -> None:
        """Dry-run full flow in a tmp git repo — verifies red-line PASS + 0 push."""
        mod = _load_pr_script()
        # Build a minimal tmp git repo.
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        rf_dir = repo / "docs" / "research-kb" / "risk_findings"
        rf_dir.mkdir(parents=True)
        (rf_dir / "2026-05-14_2026_W19_idx1_approved.md").write_text(
            "---\nstatus: approved\npr_generated: false\n---\nbody",
            encoding="utf-8",
        )
        # Initial commit so working tree is clean.
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
        )

        exit_code = mod.generate_pr(repo_root=repo, dry_run=True)
        assert exit_code == 0
        # Dry-run reverts the pr_generated flip → still false.
        content = (rf_dir / "2026-05-14_2026_W19_idx1_approved.md").read_text(
            encoding="utf-8"
        )
        assert "pr_generated: false" in content
        # No new branch created (dry-run).
        branches = subprocess.run(
            ["git", "branch"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout
        assert "risk-candidate-pr-" not in branches

    def test_dry_run_zero_pending(self, tmp_path: Path) -> None:
        mod = _load_pr_script()
        repo = tmp_path / "repo"
        (repo / "docs" / "research-kb" / "risk_findings").mkdir(parents=True)
        # 0 pending → exit 0, no git ops needed.
        exit_code = mod.generate_pr(repo_root=repo, dry_run=True)
        assert exit_code == 0
