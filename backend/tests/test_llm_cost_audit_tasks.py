"""Unit tests for llm_cost_audit_tasks — monthly LLM cost audit Beat wire (Plan v10).

Coverage:
- Task registered with celery_app under canonical name
- Task module in celery_app imports list (反 Beat → unregistered error 真根因)
- Beat schedule entry `llm-cost-monthly-audit` task field == registered name
- Beat cron: 0 8 1 * * (monthly, 1st, 08:00)
- Task body happy path: subprocess OK → ok=True, status parsed
- Task body CAP_EXCEEDED: returncode 1 → ok=True (finding, NOT task failure —
  反旧版 returncode!=0 一律 raise 的 retry 风暴 bug)
- Task body no completion marker → RuntimeError (铁律 33 fail-loud)
- Task body missing script → FileNotFoundError
- _parse_status parses OK / WARN / CAP_EXCEEDED / UNKNOWN

Mocks: subprocess.run — pure boundary tests without launching the real script.
Real script subprocess launch covered by smoke (test_plan_v10_beat_task_wire_live).

关联铁律: 22 / 33 / 41 / 44 X9
关联: Plan v8 Master P0-16 / Plan v9 matrix §3.3 closure
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tasks import llm_cost_audit_tasks as lct
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app

_TASK_NAME = "app.tasks.llm_cost_audit_tasks.monthly_audit"


def _completed(returncode: int, stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a fake CompletedProcess for subprocess.run mocking."""
    return subprocess.CompletedProcess(
        args=["python", "scripts/llm_cost_monthly_audit.py"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# §1 Task registration


def test_task_registered_in_celery_app() -> None:
    """monthly_audit is registered under canonical task name."""
    assert _TASK_NAME in celery_app.tasks


def test_task_module_in_celery_imports() -> None:
    """celery_app.conf.imports contains the module (反 Beat → unregistered error)."""
    imports = celery_app.conf.get("imports") or []
    assert "app.tasks.llm_cost_audit_tasks" in imports


# §2 Beat schedule entry


def test_beat_schedule_entry_exists() -> None:
    """llm-cost-monthly-audit entry exists in CELERY_BEAT_SCHEDULE."""
    assert "llm-cost-monthly-audit" in CELERY_BEAT_SCHEDULE


def test_beat_schedule_entry_task_matches_registered() -> None:
    """Beat entry task field == the registered task name (反 unregistered)."""
    entry = CELERY_BEAT_SCHEDULE["llm-cost-monthly-audit"]
    assert entry["task"] == _TASK_NAME
    assert entry["task"] in celery_app.tasks
    assert entry["options"]["queue"] == "data_fetch"
    assert entry["options"]["expires"] == 3600


def test_beat_schedule_cron_monthly_1st_0800() -> None:
    """cron: 08:00, day-of-month 1 (monthly)."""
    schedule = CELERY_BEAT_SCHEDULE["llm-cost-monthly-audit"]["schedule"]
    assert schedule.minute == {0}
    assert schedule.hour == {8}
    assert schedule.day_of_month == {1}


# §3 Task body


def test_monthly_audit_happy_path_ok() -> None:
    """subprocess returncode 0 + OK marker → ok=True, status=OK."""
    stdout = "[Config] Monthly budget: $50.00\n=== Audit COMPLETE — status=OK ===\n"
    with patch.object(lct.subprocess, "run", return_value=_completed(0, stdout)):
        result = lct.monthly_audit()
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["status"] == "OK"


def test_monthly_audit_cap_exceeded_is_finding_not_failure() -> None:
    """returncode 1 (CAP_EXCEEDED) is a finding, NOT a task failure — no raise.

    反旧版 wrapper `returncode != 0 → raise RuntimeError` 的 retry 风暴 bug:
    预算超标是合法发现, 不应触发 Celery retry.
    """
    stdout = "[ALERT] CAP THRESHOLD EXCEEDED\n=== Audit COMPLETE — status=CAP_EXCEEDED ===\n"
    with patch.object(lct.subprocess, "run", return_value=_completed(1, stdout)):
        result = lct.monthly_audit()
    assert result["ok"] is True
    assert result["returncode"] == 1
    assert result["status"] == "CAP_EXCEEDED"


def test_monthly_audit_no_marker_raises() -> None:
    """No completion marker → RuntimeError (铁律 33 fail-loud)."""
    fake = _completed(1, "Traceback (most recent call last):\n", "psycopg2 OperationalError")
    with (
        patch.object(lct.subprocess, "run", return_value=fake),
        pytest.raises(RuntimeError, match="completion marker"),
    ):
        lct.monthly_audit()


def test_monthly_audit_missing_script_raises() -> None:
    """Missing audit script → FileNotFoundError (deployment integrity)."""
    with (
        patch.object(lct, "_SCRIPT", Path("D:/nonexistent/llm_cost_monthly_audit.py")),
        pytest.raises(FileNotFoundError, match="missing"),
    ):
        lct.monthly_audit()


# §4 _parse_status unit


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("=== Audit COMPLETE — status=OK ===", "OK"),
        ("=== Audit COMPLETE — status=WARN ===", "WARN"),
        ("=== Audit COMPLETE — status=CAP_EXCEEDED ===", "CAP_EXCEEDED"),
        ("no marker here", "UNKNOWN"),
        ("", "UNKNOWN"),
    ],
)
def test_parse_status(line: str, expected: str) -> None:
    """_parse_status extracts the status token from the completion marker line."""
    assert lct._parse_status(line) == expected
