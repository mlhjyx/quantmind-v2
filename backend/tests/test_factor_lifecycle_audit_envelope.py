"""iter 103 — factor_lifecycle_task scheduler_task_log audit envelope tests.

闭 iter 100/101 P0 (FACTOR_LIFECYCLE_BEAT_2026_05_25.md):
- 5 连续 Fri 19:00 dispatch (4-24/5-01/5-08/5-15/5-22) 0 scheduler_task_log row
- audit envelope ensure 每 trigger 都留一行 (success / skipped / error)

也 cover §6b boot-time Beat task registration self-check (celery_app signal).

镜像 risk_daily_check_task 既有 audit envelope pattern (daily_pipeline.py L262-477).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _install_fake_factor_lifecycle_monitor(run_return=None, run_side_effect=None) -> MagicMock:
    """Inject a fake `factor_lifecycle_monitor` module into sys.modules.

    The task body does `from factor_lifecycle_monitor import run as run_lifecycle`
    INSIDE the function after sys.path.insert(scripts_dir). In pytest scripts/ is
    not on sys.path, so we pre-stub via sys.modules to make the import resolve.
    Returns the mock `run` for assertion + call_count tracking.
    """
    fake_mod = types.ModuleType("factor_lifecycle_monitor")
    mock_run = MagicMock(name="run_lifecycle")
    if run_return is not None:
        mock_run.return_value = run_return
    if run_side_effect is not None:
        mock_run.side_effect = run_side_effect
    fake_mod.run = mock_run  # type: ignore[attr-defined]
    sys.modules["factor_lifecycle_monitor"] = fake_mod
    return mock_run


@pytest.fixture
def fake_factor_lifecycle_monitor_success():
    """Yields the mock run() that returns a synthetic OK result."""
    fake_result = {
        "checked": 113,
        "no_data": 2,
        "transitions": [{"factor_name": "x", "from_status": "active", "to_status": "warning"}],
        "composite_mode": "g1_only",
        "composite_synthesized": [],
    }
    mock_run = _install_fake_factor_lifecycle_monitor(run_return=fake_result)
    try:
        yield mock_run, fake_result
    finally:
        sys.modules.pop("factor_lifecycle_monitor", None)


@pytest.fixture
def fake_factor_lifecycle_monitor_error():
    """Yields the mock run() that raises ValueError."""
    mock_run = _install_fake_factor_lifecycle_monitor(
        run_side_effect=ValueError("synthetic test failure")
    )
    try:
        yield mock_run
    finally:
        sys.modules.pop("factor_lifecycle_monitor", None)


# ─────────────────────────────────────────────────────────────
# §6a: audit envelope coverage (skipped / success / error)
# ─────────────────────────────────────────────────────────────


class TestFactorLifecycleAuditEnvelope:
    """Verify factor_lifecycle_task writes scheduler_task_log on every path."""

    def test_writes_skipped_row_on_non_trading_day(self) -> None:
        """Calendar skip path → scheduler_task_log row with status='skipped'."""
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        with (
            patch(
                "qm_platform.calendar.is_trading_day_today_or_skip",
                return_value=False,
            ),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.factor_lifecycle_task.apply(args=[]).get()

        assert result == {"status": "skipped", "reason": "non_trading_day"}
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "factor_lifecycle"  # task_name
        assert call_args[0][2] == "skipped"  # status
        assert call_args[0][3] == {
            "status": "skipped",
            "reason": "non_trading_day",
        }  # result_json

    def test_writes_success_row_on_run_lifecycle_ok(
        self, fake_factor_lifecycle_monitor_success
    ) -> None:
        """Success path → status='success' + result_json containing checked/transitions."""
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        _mock_run, _fake_result = fake_factor_lifecycle_monitor_success

        with (
            patch(
                "qm_platform.calendar.is_trading_day_today_or_skip",
                return_value=True,
            ),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.factor_lifecycle_task.apply(args=[]).get()

        assert result["status"] == "ok"
        assert result["checked"] == 113
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "factor_lifecycle"
        assert call_args[0][2] == "success"
        assert call_args[0][3]["status"] == "ok"
        assert call_args[0][3]["checked"] == 113

    def test_writes_error_row_on_run_lifecycle_raise(
        self, fake_factor_lifecycle_monitor_error
    ) -> None:
        """Exception path → status='error' + result_json containing error msg + re-raise."""
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        with (
            patch(
                "qm_platform.calendar.is_trading_day_today_or_skip",
                return_value=True,
            ),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            # apply() catches the exception internally; check result.failed()
            r = task_mod.factor_lifecycle_task.apply(args=[])
            assert r.failed()

        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "factor_lifecycle"
        assert call_args[0][2] == "error"
        assert call_args[0][3]["status"] == "error"
        assert "ValueError" in call_args[0][3]["error"]
        assert "synthetic test failure" in call_args[0][3]["error"]

    def test_envelope_uses_canonical_helper_name(self) -> None:
        """Mutation guard — audit MUST go through _write_scheduler_log_safe.

        Renaming the helper / inlining the INSERT would silently break sibling
        risk_daily_check/intraday_risk_check pattern. Regression test catches that.
        """
        from app.tasks import daily_pipeline as task_mod  # noqa: PLC0415

        assert hasattr(task_mod, "_write_scheduler_log_safe")
        assert callable(task_mod._write_scheduler_log_safe)


# ─────────────────────────────────────────────────────────────
# §6b: boot-time Beat task registration self-check
# ─────────────────────────────────────────────────────────────


class TestBeatTaskRegistrationCheck:
    """Verify celery_app._verify_beat_task_registration fail-loud behavior."""

    def test_all_beat_tasks_registered_in_production_app(self) -> None:
        """Production celery_app must already have every Beat-scheduled task registered.

        闭 LL-202 (silent worker registration) + FACTOR_LIFECYCLE_BEAT §6b — uses
        canonical helper which forces import_default_modules() so test is robust
        outside worker_init/beat_init signal time (pytest entry).
        """
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415
        from app.tasks.celery_app import (  # noqa: PLC0415
            _verify_beat_task_registration,
            celery_app,
        )

        # Helper raises RuntimeError if any missing → would propagate as test fail.
        _verify_beat_task_registration()

        # Double-check: post-helper run, registered set MUST be a superset of expected.
        expected = {entry["task"] for entry in CELERY_BEAT_SCHEDULE.values()}
        registered = set(celery_app.tasks.keys())
        missing = expected - registered
        assert not missing, f"Beat tasks missing from celery_app: {sorted(missing)}"

    def test_factor_lifecycle_specifically_registered(self) -> None:
        """Direct regression guard for the 5-cycle silent dispatch failure mode."""
        from app.tasks.celery_app import celery_app  # noqa: PLC0415

        assert "daily_pipeline.factor_lifecycle" in celery_app.tasks
        # Same module sibling that also surfaced in 4-17 KeyError trace
        assert "daily_pipeline.data_quality_report" in celery_app.tasks

    def test_verify_helper_raises_on_missing(self) -> None:
        """_verify_beat_task_registration must raise RuntimeError when a task is missing."""
        from app.tasks import celery_app as celery_mod  # noqa: PLC0415

        # Patch CELERY_BEAT_SCHEDULE to inject a fake unregistered task name
        fake_schedule = {
            "fake-entry": {
                "task": "this.task.definitely.does.not.exist",
                "schedule": 60,
            },
        }
        with (
            patch.object(celery_mod, "CELERY_BEAT_SCHEDULE", fake_schedule),
            pytest.raises(RuntimeError, match="not registered"),
        ):
            celery_mod._verify_beat_task_registration()

    def test_verify_helper_passes_when_all_present(self, caplog: pytest.LogCaptureFixture) -> None:
        """Happy path: no missing → info log + no raise."""
        from app.tasks import celery_app as celery_mod  # noqa: PLC0415

        # Use real CELERY_BEAT_SCHEDULE — production app already passes
        with caplog.at_level("INFO", logger="app.tasks.celery_app"):
            celery_mod._verify_beat_task_registration()

        assert any(
            "BeatRegistration" in rec.message and "registered" in rec.message
            for rec in caplog.records
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
