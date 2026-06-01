from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit import check_mutating_api_auth as scanner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "audit" / "check_mutating_api_auth.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.smoke
def test_current_repo_mutating_routes_are_classified() -> None:
    result = scanner.audit_repo()

    assert result.missing == []
    assert result.stale == []
    assert result.invalid == []
    assert result.total_mutating >= 58
    assert result.admin_gated >= 20
    assert result.no_admin_dependency >= 38


def test_missing_classification_blocks_no_admin_mutating_route(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "api" / "sample.py",
        """
from fastapi import APIRouter

router = APIRouter(prefix="/api/sample")


@router.post("/run")
def run_sample():
    return {"ok": True}
""",
    )
    classification = tmp_path / "classifications.json"
    classification.write_text("{}", encoding="utf-8")

    result = scanner.audit_repo(tmp_path, classification)

    assert result.missing == ["backend/app/api/sample.py|POST|/api/sample/run|run_sample"]
    assert result.stale == []
    assert result.invalid == []


def test_admin_dependency_does_not_need_exception_classification(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "api" / "sample.py",
        """
from fastapi import APIRouter, Depends
from app.core.auth import verify_admin_token

router = APIRouter(prefix="/api/sample")


@router.post("/run")
def run_sample(_: None = Depends(verify_admin_token)):
    return {"ok": True}
""",
    )
    classification = tmp_path / "classifications.json"
    classification.write_text("{}", encoding="utf-8")

    result = scanner.audit_repo(tmp_path, classification)

    assert result.missing == []
    assert result.admin_gated == 1
    assert result.no_admin_dependency == 0


def test_cli_returns_nonzero_for_missing_classification(tmp_path: Path) -> None:
    _write(
        tmp_path / "backend" / "app" / "api" / "sample.py",
        """
from fastapi import APIRouter

router = APIRouter(prefix="/api/sample")


@router.delete("/{item_id}")
def delete_sample(item_id: str):
    return {"deleted": item_id}
""",
    )
    classification = tmp_path / "classifications.json"
    classification.write_text(json.dumps({}), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--classification",
            str(classification),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 1
    assert "BLOCK" in proc.stdout
    assert "/api/sample/{item_id}" in proc.stdout
