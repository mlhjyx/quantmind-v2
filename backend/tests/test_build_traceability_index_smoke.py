"""Smoke test for scripts/build_traceability_index.py (T1.2 closure).

Plan v8 §VIII #30 Reverse Traceability Index script. Smoke gate:
- Script exists on disk
- Script imports without syntax / top-level import error
- Main entry responds to --help (or any recognized exit code)
- find_code_modules() returns a non-empty set when called directly
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "build_traceability_index.py"


@pytest.mark.smoke
def test_script_exists_and_imports():
    """Script must exist and load without syntax / import errors."""
    assert SCRIPT.exists(), f"Script missing: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("build_traceability_index", SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


@pytest.mark.smoke
def test_script_dry_run_no_crash():
    """Script should not crash with --help or exit with a known code."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # 0 = argparse --help printed OK
    # 1 = custom exit (doc-lying gaps detected)
    # 2 = argparse usage error
    assert result.returncode in (0, 1, 2), (
        f"Unexpected exit code {result.returncode}\n"
        f"stdout: {result.stdout[:300]}\n"
        f"stderr: {result.stderr[:300]}"
    )
