"""Pytest configuration guards for repo-local test discovery."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pytest_testpaths_points_at_backend_tests() -> None:
    """Bare pytest must use the real test root instead of fallback discovery."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    testpaths = config["tool"]["pytest"]["ini_options"]["testpaths"]

    assert testpaths == ["backend/tests"]
    assert (REPO_ROOT / "backend" / "tests").is_dir()
