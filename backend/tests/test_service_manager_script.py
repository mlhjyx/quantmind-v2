"""Static regression tests for the Servy service manager script."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "service_manager.ps1"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_documented_service_aliases_are_accepted() -> None:
    """Documented service names should not drift from the PowerShell ValidateSet."""
    text = _script_text()
    match = re.search(r"\[ValidateSet\((?P<items>.*?)\)\]\s*\[string\]\$Service", text, re.S)
    assert match is not None

    accepted = set(re.findall(r'"([^"]+)"', match.group("items")))

    assert {"celery", "celery-beat", "celerybeat", "qmt", "qmt-data", "qmtdata"}.issubset(accepted)
    assert "$ServiceAliases" in text
    assert re.search(r'"celery"\s*=\s*"worker"', text)
    assert re.search(r'"celery-beat"\s*=\s*"beat"', text)
    assert re.search(r'"celerybeat"\s*=\s*"beat"', text)
    assert re.search(r'"qmt-data"\s*=\s*"qmt"', text)
    assert re.search(r'"qmtdata"\s*=\s*"qmt"', text)


def test_all_action_does_not_implicitly_manage_qmtdata() -> None:
    """QMTData should require an explicit qmt/qmt-data key during PT pause."""
    text = _script_text()

    assert '@("fastapi", "worker", "slow-worker", "beat")' in text
    assert '@("fastapi", "worker", "slow-worker", "worker", "fastapi")' not in text
    assert '@("fastapi", "worker", "slow-worker", "beat", "qmt")' not in text


def test_servy_cli_failures_are_not_silenced() -> None:
    """Service control failures need to surface CLI output for ops diagnosis."""
    text = _script_text()

    assert "function Write-ServiceCliOutput" in text
    assert "| Out-Null" not in text


def test_service_action_failures_exit_nonzero() -> None:
    """Runbooks checking LASTEXITCODE must see failed service actions."""
    text = _script_text()

    assert "$script:HadServiceActionFailure" in text
    assert "$script:HadServiceActionFailure = $true" in text
    assert "exit 1" in text
