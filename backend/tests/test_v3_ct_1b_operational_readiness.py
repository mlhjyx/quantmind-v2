"""Tests for V3 Plan v0.4 CT-1b — operational readiness harness.

Scope (PURE / fixture-driven; minimal infra hit):
  - _CheckResult / _ReadinessReport dataclass invariants
  - Servy services JSON parsing (enum-as-string vs enum-as-int)
  - Report rendering shape + IC-3 SLA evidence cite invariants
  - Constant integrity (expected services / production tables / streams)

Out of scope (integration-only, exercised by `python
scripts/v3_ct_1b_operational_readiness.py --dry-run` against live services):
  - Real Servy CLI / FastAPI / Redis / PG / DingTalk / RSSHub checks

关联铁律: 25 (改什么读什么) / 33 (fail-loud) / 40 (test debt) / 41
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A CT-1b
关联 LL: LL-098 X10 / LL-159 / LL-173 lesson 1
"""

# ruff: noqa: E402 — sys.path.insert(s) precede imports (necessary path setup)

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from v3_ct_1b_operational_readiness import (
    _EXPECTED_SERVICES,
    _EXPECTED_STREAMS,
    _PROD_TABLES,
    _check_pg_perms,
    _check_servy_services,
    _CheckResult,
    _ReadinessReport,
    render_report,
)

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_expected_5_servy_services(self) -> None:
        """Per CLAUDE.md §部署规则 + Phase 0 verify 2026-05-17."""
        assert len(_EXPECTED_SERVICES) == 5
        assert "QuantMind-FastAPI" in _EXPECTED_SERVICES
        assert "QuantMind-Celery" in _EXPECTED_SERVICES
        assert "QuantMind-CeleryBeat" in _EXPECTED_SERVICES
        assert "QuantMind-QMTData" in _EXPECTED_SERVICES
        assert "QuantMind-RSSHub" in _EXPECTED_SERVICES

    def test_prod_tables_match_ct_1a_cleanup_scope(self) -> None:
        """Tables CT-1a cleaned + downstream cited; 5 production tables."""
        assert "position_snapshot" in _PROD_TABLES
        assert "performance_series" in _PROD_TABLES
        assert "circuit_breaker_state" in _PROD_TABLES
        assert "trade_log" in _PROD_TABLES
        assert "risk_event_log" in _PROD_TABLES

    def test_expected_qm_streams_include_core_wires(self) -> None:
        """qm:* streams that L1 + Health + QMT wire to."""
        assert "qm:signal:generated" in _EXPECTED_STREAMS
        assert "qm:qmt:status" in _EXPECTED_STREAMS
        assert "qm:health:check_result" in _EXPECTED_STREAMS


# ─────────────────────────────────────────────────────────────
# _CheckResult + _ReadinessReport
# ─────────────────────────────────────────────────────────────


class TestCheckResult:
    def test_default_passed_false(self) -> None:
        r = _CheckResult(name="test")
        assert r.passed is False
        assert r.detail == ""
        assert r.failures == []

    def test_pass_with_detail(self) -> None:
        r = _CheckResult(name="test", passed=True, detail="OK")
        assert r.passed is True
        assert r.detail == "OK"

    def test_fail_with_failures_list(self) -> None:
        r = _CheckResult(name="test", failures=["fail-a", "fail-b"])
        assert r.passed is False
        assert len(r.failures) == 2


class TestReadinessReport:
    def test_all_passed_true_only_if_all_checks_pass(self) -> None:
        report = _ReadinessReport(
            timestamp_utc="2026-05-17T00:00:00+00:00",
            timestamp_shanghai="2026-05-17T08:00:00+08:00",
            checks=[
                _CheckResult(name="a", passed=True),
                _CheckResult(name="b", passed=True),
            ],
        )
        assert report.all_passed is True
        assert report.failed_checks == []

    def test_all_passed_false_if_any_fail(self) -> None:
        report = _ReadinessReport(
            timestamp_utc="x",
            timestamp_shanghai="y",
            checks=[
                _CheckResult(name="a", passed=True),
                _CheckResult(name="b", failures=["boom"]),
            ],
        )
        assert report.all_passed is False
        assert len(report.failed_checks) == 1
        assert report.failed_checks[0].name == "b"

    def test_all_passed_false_when_no_checks(self) -> None:
        """Empty checks → no PASS verdict (defensive)."""
        report = _ReadinessReport(timestamp_utc="x", timestamp_shanghai="y")
        assert report.all_passed is False


# ─────────────────────────────────────────────────────────────
# Servy parser — enum-as-string vs enum-as-int (post-fix)
# ─────────────────────────────────────────────────────────────


class TestServyServicesParser:
    @patch("v3_ct_1b_operational_readiness.subprocess.run")
    def test_parses_5_services_all_running_as_string(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                '[{"Name":"QuantMind-FastAPI","Status":"Running"},'
                '{"Name":"QuantMind-Celery","Status":"Running"},'
                '{"Name":"QuantMind-CeleryBeat","Status":"Running"},'
                '{"Name":"QuantMind-QMTData","Status":"Running"},'
                '{"Name":"QuantMind-RSSHub","Status":"Running"}]'
            ),
            stderr="",
        )
        r = _check_servy_services()
        assert r.passed is True
        assert "5 services Running" in r.detail

    @patch("v3_ct_1b_operational_readiness.subprocess.run")
    def test_fails_when_service_stopped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                '[{"Name":"QuantMind-FastAPI","Status":"Stopped"},'
                '{"Name":"QuantMind-Celery","Status":"Running"},'
                '{"Name":"QuantMind-CeleryBeat","Status":"Running"},'
                '{"Name":"QuantMind-QMTData","Status":"Running"},'
                '{"Name":"QuantMind-RSSHub","Status":"Running"}]'
            ),
            stderr="",
        )
        r = _check_servy_services()
        assert r.passed is False
        assert any("QuantMind-FastAPI" in f and "Stopped" in f for f in r.failures)

    @patch("v3_ct_1b_operational_readiness.subprocess.run")
    def test_fails_when_service_missing(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                '[{"Name":"QuantMind-FastAPI","Status":"Running"},'
                '{"Name":"QuantMind-Celery","Status":"Running"}]'
            ),
            stderr="",
        )
        r = _check_servy_services()
        assert r.passed is False
        # 3 missing services (CeleryBeat, QMTData, RSSHub).
        assert sum("not found" in f for f in r.failures) == 3

    @patch("v3_ct_1b_operational_readiness.subprocess.run")
    def test_fails_when_powershell_returncode_nonzero(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Get-Service: error",
        )
        r = _check_servy_services()
        assert r.passed is False
        assert any("exit=1" in f for f in r.failures)


# ─────────────────────────────────────────────────────────────
# PG perms check
# ─────────────────────────────────────────────────────────────


class TestPgPermsCheck:
    def test_passes_when_all_tables_selectable(self) -> None:
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = lambda *a: None
        cur.fetchone.return_value = (0,)
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.close = MagicMock()

        r = _check_pg_perms(conn_factory=lambda: conn)
        assert r.passed is True
        assert "5 tables" in r.detail
        # 5 SELECT queries executed.
        assert cur.execute.call_count == 5
        conn.close.assert_called_once()

    def test_fails_when_select_raises(self) -> None:
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = lambda *a: None
        cur.execute.side_effect = RuntimeError("permission denied")
        conn = MagicMock()
        conn.cursor.return_value = cur

        r = _check_pg_perms(conn_factory=lambda: conn)
        assert r.passed is False
        assert any("permission denied" in f for f in r.failures)


# ─────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────


class TestRenderReport:
    def _mk_pass_report(self) -> _ReadinessReport:
        return _ReadinessReport(
            timestamp_utc="2026-05-17T00:00:00+00:00",
            timestamp_shanghai="2026-05-17T08:00:00+08:00",
            checks=[
                _CheckResult(name="servy_services_running", passed=True, detail="5 services Running"),
                _CheckResult(name="fastapi_health", passed=True, detail="FastAPI /health OK"),
                _CheckResult(name="redis_streams", passed=True, detail="Redis PING + 3 streams"),
                _CheckResult(name="pg_select_perms", passed=True, detail="5 tables verified"),
                _CheckResult(name="dingtalk_endpoint_reachable", passed=True, detail="TCP reachable"),
                _CheckResult(name="news_sources_reachable", passed=True, detail="RSSHub reachable"),
            ],
        )

    def test_renders_overall_ready_when_all_pass(self) -> None:
        report = render_report(self._mk_pass_report())
        assert "✅ READY" in report

    def test_renders_not_ready_when_any_fail(self) -> None:
        r = self._mk_pass_report()
        r.checks[0] = _CheckResult(name="servy_services_running", failures=["boom"])
        report = render_report(r)
        assert "❌ NOT READY" in report

    def test_includes_failed_check_section_when_any_fail(self) -> None:
        r = self._mk_pass_report()
        r.checks[0] = _CheckResult(
            name="servy_services_running", failures=["Service QuantMind-FastAPI Stopped"]
        )
        report = render_report(r)
        assert "Failed checks" in report
        assert "Service QuantMind-FastAPI Stopped" in report

    def test_renders_5_sla_evidence_cite_table(self) -> None:
        """§2 must enumerate 5 V3 §13.1 SLA + cite IC-3 evidence."""
        report = render_report(self._mk_pass_report())
        assert "§2 V3 §13.1 SLA evidence cite" in report
        assert "L1 detection latency P99" in report
        assert "L4 STAGED 30min cancel" in report
        assert "L0 News 6-source 30s timeout" in report
        assert "LiteLLM" in report and "Ollama fallback" in report
        assert "DingTalk push" in report
        # All 5 should show ✅ status (IC-3 sediment evidence).
        sla_section_start = report.index("§2 V3 §13.1 SLA evidence cite")
        sla_section_end = report.index("§3 Methodology")
        sla_section = report[sla_section_start:sla_section_end]
        assert sla_section.count("✅") >= 5

    def test_renders_methodology_anchors(self) -> None:
        report = render_report(self._mk_pass_report())
        assert "ADR-063" in report
        assert "ADR-080" in report
        assert "Plan v0.4 §A CT-1b" in report
        assert "LL-173 lesson 1" in report
        assert "LIVE_TRADING_DISABLED=true" in report
        assert "EXECUTION_MODE=paper" in report

    def test_renders_verify_only_methodology_note(self) -> None:
        """User 决议 (V1) verify-only must be documented in §3."""
        report = render_report(self._mk_pass_report())
        assert "Verify-only" in report or "verify-only" in report
        assert "反日历式观察期" in report
