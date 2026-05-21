"""Unit tests for slippage_calibration_tasks — quarterly slippage calibration Beat wire.

Coverage (Plan v10 — orphaned task module closure):
- Task registered with celery_app under canonical name
- Task module in celery_app imports list (反 Beat → unregistered error 真根因)
- Beat schedule entry `slippage-calibration-quarterly` task field == registered name
- Beat cron: 0 2 1 1,4,7,10 * (quarterly, 1st, 02:00)
- Task body happy path: subprocess returncode 0 → ok=True
- Task body data-insufficient graceful degrade (rc 0) → still ok=True
- Task body non-zero returncode → RuntimeError (铁律 33 fail-loud)
- Task body missing script → FileNotFoundError

Mocks: subprocess.run. Real script launch covered by smoke test.

关联铁律: 18 (季度复核) / 22 / 33 / 44 X9
关联: Plan v8 Master P0-10 / Plan v9 matrix §3.3 closure
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tasks import slippage_calibration_tasks as sct
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app

_TASK_NAME = "app.tasks.slippage_calibration_tasks.quarterly_recalibrate"


def _completed(returncode: int, stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a fake CompletedProcess for subprocess.run mocking."""
    return subprocess.CompletedProcess(
        args=["python", "scripts/bayesian_slippage_calibration.py"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# §1 Task registration


def test_task_registered_in_celery_app() -> None:
    """quarterly_recalibrate is registered under canonical task name."""
    assert _TASK_NAME in celery_app.tasks


def test_task_module_in_celery_imports() -> None:
    """celery_app.conf.imports contains the module (反 Beat → unregistered error)."""
    imports = celery_app.conf.get("imports") or []
    assert "app.tasks.slippage_calibration_tasks" in imports


# §2 Beat schedule entry


def test_beat_schedule_entry_exists() -> None:
    """slippage-calibration-quarterly entry exists in CELERY_BEAT_SCHEDULE."""
    assert "slippage-calibration-quarterly" in CELERY_BEAT_SCHEDULE


def test_beat_schedule_entry_task_matches_registered() -> None:
    """Beat entry task field == the registered task name (反 unregistered)."""
    entry = CELERY_BEAT_SCHEDULE["slippage-calibration-quarterly"]
    assert entry["task"] == _TASK_NAME
    assert entry["task"] in celery_app.tasks
    assert entry["options"]["queue"] == "default"
    assert entry["options"]["expires"] == 7200


def test_beat_schedule_cron_quarterly() -> None:
    """cron: 02:00, day-of-month 1, months Jan/Apr/Jul/Oct."""
    schedule = CELERY_BEAT_SCHEDULE["slippage-calibration-quarterly"]["schedule"]
    assert schedule.minute == {0}
    assert schedule.hour == {2}
    assert schedule.day_of_month == {1}
    assert schedule.month_of_year == {1, 4, 7, 10}


# §3 Task body


def test_quarterly_recalibrate_happy_path() -> None:
    """subprocess returncode 0 → ok=True, stdout captured."""
    stdout = "读取到 42 条PT执行记录\n  Bayesian滑点校准报告\n"
    with patch.object(sct.subprocess, "run", return_value=_completed(0, stdout)):
        result = sct.quarterly_recalibrate()
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "校准报告" in result["stdout_tail"]


def test_quarterly_recalibrate_data_insufficient_still_ok() -> None:
    """Data-insufficient graceful degrade (rc 0) is still a successful run.

    脚本在 trade_log paper 记录 <30 条时打印 R4 手工推荐值并 return (rc 0).
    """
    stdout = "数据不足（当前3条，需要>=30条）\n基于R4研究的手动校准建议\n"
    with patch.object(sct.subprocess, "run", return_value=_completed(0, stdout)):
        result = sct.quarterly_recalibrate()
    assert result["ok"] is True
    assert result["returncode"] == 0


def test_quarterly_recalibrate_nonzero_raises() -> None:
    """Non-zero returncode → RuntimeError (铁律 33 fail-loud)."""
    fake = _completed(1, "", "Traceback: scipy LinAlgError")
    with (
        patch.object(sct.subprocess, "run", return_value=fake),
        pytest.raises(RuntimeError, match="失败"),
    ):
        sct.quarterly_recalibrate()


def test_quarterly_recalibrate_missing_script_raises() -> None:
    """Missing calibration script → FileNotFoundError (deployment integrity)."""
    with (
        patch.object(sct, "_SCRIPT", Path("D:/nonexistent/bayesian_slippage_calibration.py")),
        pytest.raises(FileNotFoundError, match="missing"),
    ):
        sct.quarterly_recalibrate()
