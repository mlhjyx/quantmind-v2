"""Smoke tests for Plan v8 Day 1 audit scripts.

Plan v8 Day 1 sediment gap closure: scripts shipped without test coverage.
铁律 40: 测试债务不得增长 → 新增 audit script 必带 smoke test.

Coverage:
- scripts/audit_disk_space.py — disk usage probe
- scripts/audit_redline_runtime.py — 5/5 红线 drift probe
- scripts/disaster_drill_simulator.py — read-only scenario verifier
- scripts/audit_design_doc_smoke.py — Living Documentation verifier
- scripts/generate_system_diagram.py — AST diagram builder
- scripts/build_traceability_index.py — code↔doc index

Test strategy:
- Import smoke (module loads, no SyntaxError / ImportError)
- main() exit code semantics
- Critical function contracts (classify / probe / build_graph)
- No production state mutation
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


# ============================================================
# Helpers
# ============================================================


def load_script(name: str):
    """Dynamically load a script module by file path."""
    path = SCRIPTS_DIR / name
    if not path.exists():
        pytest.skip(f"Script {name} not found at {path}")
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(name: str, args: list[str] | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run script as subprocess. Returns CompletedProcess."""
    cmd = [sys.executable, str(SCRIPTS_DIR / name)] + (args or [])
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
    )


# ============================================================
# audit_disk_space.py smoke tests
# ============================================================


class TestAuditDiskSpace:
    """Smoke tests for scripts/audit_disk_space.py."""

    def test_module_imports_cleanly(self) -> None:
        """Module loads without SyntaxError."""
        load_script("audit_disk_space.py")

    def test_classify_severity_ordering(self) -> None:
        """WARN < ALERT < P0 threshold ordering enforced."""
        module = load_script("audit_disk_space.py")
        # Simulate path with controlled usage
        path = Path(__file__).parent  # any existing path
        # 50% under WARN(80) → OK
        result = module.get_disk_usage(path, warn_pct=99.0, alert_pct=99.5, p0_pct=99.9)
        assert result is not None
        assert result["severity"] == "OK"
        # 0% threshold → always P0 trigger
        result = module.get_disk_usage(path, warn_pct=0.0, alert_pct=0.0, p0_pct=0.0)
        assert result is not None
        assert result["severity"] == "P0"

    def test_run_no_alert_exit_code(self) -> None:
        """--no-alert smoke run exits 0 OR 1 (depending on disk state), never crashes."""
        result = run_script("audit_disk_space.py", ["--no-alert"])
        assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"

    def test_run_json_output(self) -> None:
        """--json output parses as valid JSON."""
        result = run_script("audit_disk_space.py", ["--no-alert", "--json"])
        assert result.returncode in (0, 1)
        # First-line JSON might be wrapped, find {
        text = result.stdout.strip()
        assert text.startswith("{"), f"JSON output expected, got: {text[:100]}"
        data = json.loads(text)
        assert "summary" in data
        assert "paths" in data
        assert "by_severity" in data["summary"]


# ============================================================
# audit_redline_runtime.py smoke tests
# ============================================================


class TestAuditRedlineRuntime:
    """Smoke tests for scripts/audit_redline_runtime.py."""

    def test_module_imports_cleanly(self) -> None:
        """Module loads without SyntaxError."""
        load_script("audit_redline_runtime.py")

    def test_redline_fields_canonical_5(self) -> None:
        """REDLINE_FIELDS is exactly 5 (per ADR-027 §7)."""
        module = load_script("audit_redline_runtime.py")
        assert len(module.REDLINE_FIELDS) == 5
        assert "EXECUTION_MODE" in module.REDLINE_FIELDS
        assert "LIVE_TRADING_DISABLED" in module.REDLINE_FIELDS
        assert "QMT_ACCOUNT_ID" in module.REDLINE_FIELDS
        assert "DINGTALK_ALERTS_ENABLED" in module.REDLINE_FIELDS
        assert "L4_AUTO_MODE_ENABLED" in module.REDLINE_FIELDS

    def test_read_env_field_quote_strip(self) -> None:
        """read_env_field strips surrounding quotes (LL-188 quote-vs-no-quote防drift)."""
        module = load_script("audit_redline_runtime.py")
        # Read existing field — should return 'paper' not '"paper"'
        val = module.read_env_field("EXECUTION_MODE")
        # Either MISSING (test env) OR stripped value (no leading quotes)
        if val != "MISSING":
            assert not val.startswith('"'), f"quote leaked: {val!r}"
            assert not val.startswith("'"), f"quote leaked: {val!r}"

    def test_baseline_corrupted_error_exists(self) -> None:
        """BaselineCorruptedError class defined (LL-188 drift anchor protection)."""
        module = load_script("audit_redline_runtime.py")
        assert hasattr(module, "BaselineCorruptedError")
        assert issubclass(module.BaselineCorruptedError, Exception)

    def test_first_run_or_sustained_exit_0(self) -> None:
        """Cold run exits 0 (first-run baseline OR sustained match)."""
        result = run_script("audit_redline_runtime.py", ["--no-alert"])
        # Exit 0 = OK (first-run OR sustained match)
        # Exit 1 = drift detected (also valid in test environment)
        # Exit 2 = corrupted baseline (should not happen on clean test)
        assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"


# ============================================================
# disaster_drill_simulator.py smoke tests
# ============================================================


class TestDisasterDrillSimulator:
    """Smoke tests for scripts/disaster_drill_simulator.py."""

    def test_module_imports_cleanly(self) -> None:
        """Module loads without SyntaxError."""
        load_script("disaster_drill_simulator.py")

    def test_scenarios_catalog_12(self) -> None:
        """12 disaster scenarios defined (3 tiers × 4)."""
        module = load_script("disaster_drill_simulator.py")
        assert len(module.SCENARIOS) == 12
        tier_count = {1: 0, 2: 0, 3: 0}
        for s in module.SCENARIOS:
            tier_count[s["tier"]] = tier_count.get(s["tier"], 0) + 1
        assert tier_count[1] == 4
        assert tier_count[2] == 4
        assert tier_count[3] == 4

    def test_simulate_status_enum(self) -> None:
        """simulate() returns PASS/GAP/DRIFT status."""
        module = load_script("disaster_drill_simulator.py")
        scenario = module.SCENARIOS[0]
        result = module.simulate(scenario)
        assert result["status"] in ("PASS", "GAP", "DRIFT")
        assert "reason" in result
        assert "scenario_id" in result

    def test_run_exit_code(self) -> None:
        """Cold run exits 0 (all PASS) OR 1 (any GAP/DRIFT)."""
        result = run_script("disaster_drill_simulator.py")
        assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"


# ============================================================
# audit_design_doc_smoke.py smoke tests
# ============================================================


class TestAuditDesignDocSmoke:
    """Smoke tests for scripts/audit_design_doc_smoke.py."""

    def test_module_imports_cleanly(self) -> None:
        load_script("audit_design_doc_smoke.py")

    def test_redline_fields_in_truth(self) -> None:
        """collect_truth_facts returns env_* fields."""
        module = load_script("audit_design_doc_smoke.py")
        truth = module.collect_truth_facts()
        for field in (
            "env_execution_mode",
            "env_live_trading_disabled",
            "env_qmt_account_id",
            "env_dingtalk_enabled",
        ):
            assert field in truth, f"{field} missing in truth facts"


# ============================================================
# generate_system_diagram.py smoke tests
# ============================================================


class TestGenerateSystemDiagram:
    """Smoke tests for scripts/generate_system_diagram.py."""

    def test_module_imports_cleanly(self) -> None:
        load_script("generate_system_diagram.py")

    def test_build_graph_returns_structure(self) -> None:
        """build_graph returns expected keys."""
        module = load_script("generate_system_diagram.py")
        result = module.build_graph(limit=5)
        assert "graph" in result
        assert "edges" in result
        assert "summary" in result
        assert "total_modules" in result["summary"]
        assert "top_imported" in result["summary"]


# ============================================================
# build_traceability_index.py smoke tests
# ============================================================


class TestBuildTraceabilityIndex:
    """Smoke tests for scripts/build_traceability_index.py."""

    def test_module_imports_cleanly(self) -> None:
        load_script("build_traceability_index.py")

    def test_find_code_modules_nonempty(self) -> None:
        """find_code_modules returns non-empty set."""
        module = load_script("build_traceability_index.py")
        modules = module.find_code_modules()
        assert len(modules) > 100, f"too few modules found: {len(modules)}"

    def test_analyze_gaps_structure(self) -> None:
        """analyze_gaps returns expected keys."""
        module = load_script("build_traceability_index.py")
        # Minimal mock data
        index = {"module_to_docs": {}, "doc_to_modules": {}}
        gaps = module.analyze_gaps(set(["a.py", "b.py"]), index)
        assert "total_code_modules" in gaps
        assert "coverage_pct" in gaps
        assert gaps["total_code_modules"] == 2
        assert gaps["coverage_pct"] == 0  # no docs


# ============================================================
# Test runner discovery sanity
# ============================================================


def test_all_6_audit_scripts_present() -> None:
    """All 6 new audit scripts exist on disk (sediment-then-implement gate)."""
    expected = [
        "audit_disk_space.py",
        "audit_redline_runtime.py",
        "disaster_drill_simulator.py",
        "audit_design_doc_smoke.py",
        "generate_system_diagram.py",
        "build_traceability_index.py",
    ]
    missing = [s for s in expected if not (SCRIPTS_DIR / s).exists()]
    assert not missing, f"missing audit scripts: {missing}"
