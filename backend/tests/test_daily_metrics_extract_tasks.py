"""Unit tests for daily_metrics_extract_tasks — V3 §S10 operational wire (PR #319).

Coverage:
- Task registered with celery_app under canonical name
- Task module in celery_app imports list (反 Beat → unregistered error)
- Beat schedule entry `risk-metrics-daily-extract-16-30` exists with correct
  cron (30 16 * * 1-5) + queue + expires
- Task body happy path: get_sync_conn → aggregate → upsert → commit + close
- Task body exception path: rollback + close + re-raise
- 铁律 32 sustained: PURE modules don't commit; task body owns boundary

Mocks: get_sync_conn + aggregate_daily_metrics + upsert_daily_metrics — pure
boundary tests without touching real PG. Per-call DB integration is covered
by test_daily_aggregator.py (PR #315).

关联铁律: 22 / 32 / 33 / 41 / 44 X9
关联 ADR: ADR-062 (S10 setup) + S10 operational wire closure
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.tasks import daily_metrics_extract_tasks as dmt
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app

# §1 Task registration


def test_task_registered_in_celery_app() -> None:
    """extract_daily_metrics is registered under canonical task name."""
    assert "app.tasks.daily_metrics_extract_tasks.extract_daily_metrics" in celery_app.tasks


def test_task_module_in_celery_imports() -> None:
    """celery_app.conf.imports contains the module (反 Beat → unregistered error)."""
    imports = celery_app.conf.get("imports") or []
    assert "app.tasks.daily_metrics_extract_tasks" in imports


# §2 Beat schedule entry


def test_beat_schedule_entry_exists() -> None:
    """risk-metrics-daily-extract-16-30 entry exists in CELERY_BEAT_SCHEDULE."""
    assert "risk-metrics-daily-extract-16-30" in CELERY_BEAT_SCHEDULE


def test_beat_schedule_entry_correct() -> None:
    """Beat entry points to canonical task name with queue+expires."""
    entry = CELERY_BEAT_SCHEDULE["risk-metrics-daily-extract-16-30"]
    assert entry["task"] == "app.tasks.daily_metrics_extract_tasks.extract_daily_metrics"
    assert entry["options"]["queue"] == "default"
    # expires=300 (5min within next 24h cycle, 反 stale retry on Mon)
    assert entry["options"]["expires"] == 300


def test_beat_schedule_cron_16_30_mon_fri() -> None:
    """cron: 16:30, Mon-Fri."""
    schedule = CELERY_BEAT_SCHEDULE["risk-metrics-daily-extract-16-30"]["schedule"]
    assert schedule.minute == {30}
    assert schedule.hour == {16}
    # Mon-Fri (day_of_week 1-5)
    assert schedule.day_of_week == {1, 2, 3, 4, 5}


# §3 Task body happy path


def test_extract_happy_path_commits_and_closes() -> None:
    """get_sync_conn → aggregate → upsert → commit + close. Returns summary."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.alerts_p0_count = 5
    mock_result.staged_plans_count = 2
    mock_result.llm_cost_total = 1.5

    with (
        patch.object(dmt, "get_sync_conn", return_value=mock_conn),
        patch.object(dmt, "aggregate_daily_metrics", return_value=mock_result),
        patch.object(dmt, "upsert_daily_metrics", return_value=1),
    ):
        result = dmt.extract_daily_metrics()

    assert result["ok"] is True
    assert result["rowcount"] == 1
    assert result["alerts_p0"] == 5
    assert result["staged_plans"] == 2
    assert result["llm_cost"] == 1.5
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()
    mock_conn.rollback.assert_not_called()


def test_extract_exception_rolls_back_and_re_raises() -> None:
    """Aggregate raises → rollback + close + re-raise (Celery retry)."""
    mock_conn = MagicMock()

    with (
        patch.object(dmt, "get_sync_conn", return_value=mock_conn),
        patch.object(dmt, "aggregate_daily_metrics", side_effect=RuntimeError("pg down")),
        patch.object(dmt, "upsert_daily_metrics") as mock_upsert,
    ):
        try:
            dmt.extract_daily_metrics()
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "pg down" in str(e)

    mock_conn.commit.assert_not_called()
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()
    mock_upsert.assert_not_called()


def test_extract_conn_failure_no_unbound_local() -> None:
    """get_sync_conn raises → no UnboundLocalError in finally (反 mask original)."""
    with (
        patch.object(dmt, "get_sync_conn", side_effect=ConnectionError("pg unreachable")),
    ):
        try:
            dmt.extract_daily_metrics()
            raise AssertionError("expected ConnectionError")
        except ConnectionError as e:
            # Original exception surfaces (not UnboundLocalError from finally)
            assert "pg unreachable" in str(e)


# §4 target_date computation


def test_today_shanghai_returns_tz_aware() -> None:
    """_today_shanghai returns Asia/Shanghai tz-aware datetime."""
    now = dmt._today_shanghai()
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Asia/Shanghai"


def test_today_shanghai_close_to_utc_now() -> None:
    """_today_shanghai is within 1 minute of current UTC (tz conversion sanity)."""
    sh = dmt._today_shanghai()
    utc_now = datetime.now(UTC)
    delta = abs((sh.astimezone(UTC) - utc_now).total_seconds())
    assert delta < 60.0, f"sh={sh.isoformat()} utc={utc_now.isoformat()}"
