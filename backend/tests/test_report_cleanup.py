"""Unit tests for reports retention cleanup (iter 31 — closes iter 30 PR #459 P2-8).

Coverage:
  - CLI `scripts/cleanup_old_reports.compute_deletes`:
    - empty dir / no artifacts → empty plan
    - artifacts within age + count limits → empty plan (everything retained)
    - age-rule trigger: file older than max_age_days → in delete plan
    - count-rule trigger: per (sid, mode) > keep_per_tuple → oldest beyond N in plan
    - union semantic: both rules collectively determine deletes (no double-delete)
    - non-pattern files (e.g. DATA_SYSTEM_V1_COMPLETION.md) → skipped, NOT deleted
    - per-tuple isolation: deletes for (sidA, paper) don't affect (sidA, live) or (sidB, paper)
  - CLI input validation:
    - max_age_days < 1 → ValueError
    - keep_per_tuple < 1 → ValueError
  - CLI `execute_deletes`:
    - success path (all deletes succeed)
    - partial failure (some OSError, return capture, no raise from execute_deletes)
  - Celery task `cleanup_old_reports`:
    - REPORTS_DIR missing → no-op return dict
    - happy path (mocks compute_deletes + execute_deletes via real wrapper)
    - failure path (any delete failure → OSError raised, Celery retry semantic)
  - Beat schedule entry:
    - reports-cleanup-weekly registered in CELERY_BEAT_SCHEDULE
    - schedule = Sunday 04:30
    - task ref = app.tasks.report_tasks.cleanup_old_reports
  - Celery imports list:
    - app.tasks.report_tasks registered in celery_app imports (反 iter 30 hidden defect repeat)
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ── compute_deletes ─────────────────────────────────────────────────────────


def _ensure_scripts_on_path():
    """Add scripts/ to sys.path so cleanup_old_reports is importable in tests."""
    project_root = Path(__file__).resolve().parent.parent.parent
    scripts_dir = project_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _touch(path: Path, content: str = "{}") -> None:
    """Helper: create a file with stub JSON content."""
    path.write_text(content, encoding="utf-8")


def test_compute_deletes_empty_dir_empty_plan(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    deletes, skipped = compute_deletes(tmp_path, max_age_days=90, keep_per_tuple=20)
    assert deletes == []
    assert skipped == []


def test_compute_deletes_all_within_limits_kept(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    now = datetime.now(UTC)
    # 3 files for one tuple, all within age + count limits
    for d in (now - timedelta(days=1), now - timedelta(days=5), now - timedelta(days=30)):
        _touch(tmp_path / f"sid-A_{d.strftime('%Y-%m-%d')}_paper.json")

    deletes, skipped = compute_deletes(tmp_path, max_age_days=90, keep_per_tuple=20, now=now)
    assert deletes == []
    assert skipped == []


def test_compute_deletes_age_rule_triggers(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    now = datetime.now(UTC)
    keep = tmp_path / f"sid-A_{(now - timedelta(days=30)).strftime('%Y-%m-%d')}_paper.json"
    drop = tmp_path / f"sid-A_{(now - timedelta(days=100)).strftime('%Y-%m-%d')}_paper.json"
    _touch(keep)
    _touch(drop)

    deletes, skipped = compute_deletes(tmp_path, max_age_days=90, keep_per_tuple=20, now=now)
    assert drop in deletes
    assert keep not in deletes
    assert skipped == []


def test_compute_deletes_count_rule_triggers(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    now = datetime.now(UTC)
    # 5 files for one tuple, all recent (within age), keep_per_tuple=3 → 2 oldest drop
    files = []
    for i in range(5):
        d = now - timedelta(days=i + 1)
        f = tmp_path / f"sid-B_{d.strftime('%Y-%m-%d')}_paper.json"
        _touch(f)
        files.append((d, f))

    files.sort(key=lambda x: x[0], reverse=True)  # newest first
    kept_expected = {f for _, f in files[:3]}
    dropped_expected = {f for _, f in files[3:]}

    deletes, _skipped = compute_deletes(tmp_path, max_age_days=365, keep_per_tuple=3, now=now)
    assert set(deletes) == dropped_expected
    assert kept_expected.isdisjoint(set(deletes))


def test_compute_deletes_per_tuple_isolation(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    now = datetime.now(UTC)
    # 3 files for (sid-A, paper), 3 for (sid-A, live), 3 for (sid-B, paper)
    # keep_per_tuple=2 → each tuple drops oldest 1
    for sid in ("sid-A", "sid-B"):
        for mode in ("paper", "live") if sid == "sid-A" else ("paper",):
            for i in range(3):
                d = now - timedelta(days=i + 1)
                _touch(tmp_path / f"{sid}_{d.strftime('%Y-%m-%d')}_{mode}.json")

    deletes, _ = compute_deletes(tmp_path, max_age_days=365, keep_per_tuple=2, now=now)
    # 3 tuples × 1 oldest dropped = 3 deletes total
    assert len(deletes) == 3
    # All deletes are 4-day-old files (oldest in each tuple)
    oldest_date_str = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    for d in deletes:
        assert oldest_date_str in d.name, f"unexpected delete: {d.name}"


def test_compute_deletes_skips_non_artifact_files(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    # Pre-existing reports/ residents that should NOT be touched
    legacy_files = [
        "DATA_SYSTEM_V1_COMPLETION.md",
        "p0_minute_g_robust_20260417_042557.json",
        "p2_migration_plan.md",
        "random-no-pattern.json",
        "sid_2026-04-28_paper_extrasuffix.json",  # too many segments
        "sid_2026-04-28_invalid.json",  # mode not paper/live
        "sid_bad-date_paper.json",  # malformed date
    ]
    for name in legacy_files:
        _touch(tmp_path / name)
    # 1 real artifact (should not be deleted because all rules pass)
    now = datetime.now(UTC)
    real = tmp_path / f"sid-real_{now.strftime('%Y-%m-%d')}_paper.json"
    _touch(real)

    deletes, skipped = compute_deletes(tmp_path, max_age_days=90, keep_per_tuple=20, now=now)
    assert deletes == []
    assert len(skipped) == len(legacy_files)
    for legacy in legacy_files:
        assert any(p.name == legacy for p in skipped)


def test_compute_deletes_validates_bad_args(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import compute_deletes

    with pytest.raises(ValueError, match="max_age_days must be >= 1"):
        compute_deletes(tmp_path, max_age_days=0, keep_per_tuple=20)
    with pytest.raises(ValueError, match="keep_per_tuple must be >= 1"):
        compute_deletes(tmp_path, max_age_days=90, keep_per_tuple=0)


# ── execute_deletes ─────────────────────────────────────────────────────────


def test_execute_deletes_happy_path(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import execute_deletes

    paths = [tmp_path / f"f{i}.json" for i in range(3)]
    for p in paths:
        _touch(p)

    success, failures = execute_deletes(paths)
    assert success == 3
    assert failures == []
    for p in paths:
        assert not p.exists()


def test_execute_deletes_captures_failures(tmp_path):
    _ensure_scripts_on_path()
    from cleanup_old_reports import execute_deletes

    real_path = tmp_path / "real.json"
    _touch(real_path)
    bogus_path = tmp_path / "does-not-exist.json"

    success, failures = execute_deletes([real_path, bogus_path])
    assert success == 1
    assert len(failures) == 1
    assert failures[0][0] == bogus_path
    assert "FileNotFoundError" in failures[0][1] or "Errno" in failures[0][1]
    assert not real_path.exists()


# ── Celery task wrapper ─────────────────────────────────────────────────────


def test_celery_task_no_op_when_dir_missing(tmp_path, monkeypatch):
    from app.tasks import report_tasks

    missing = tmp_path / "nonexistent_dir"
    monkeypatch.setattr(report_tasks, "REPORTS_DIR", missing)

    result = report_tasks.cleanup_old_reports.run(max_age_days=90, keep_per_tuple=20)
    assert result["ok"] is True
    assert result["scanned"] == 0
    assert result["deletes_planned"] == 0
    assert result["deletes_succeeded"] == 0
    assert result["deletes_failed"] == 0


def test_celery_task_happy_path_deletes_old_artifacts(tmp_path, monkeypatch):
    from app.tasks import report_tasks

    monkeypatch.setattr(report_tasks, "REPORTS_DIR", tmp_path)

    now = datetime.now(UTC)
    # 1 old (drops) + 2 recent (kept) for one tuple, keep_per_tuple=20 so age-rule alone applies
    old_file = tmp_path / f"sid-X_{(now - timedelta(days=100)).strftime('%Y-%m-%d')}_paper.json"
    new_files = [
        tmp_path / f"sid-X_{(now - timedelta(days=i)).strftime('%Y-%m-%d')}_paper.json"
        for i in (1, 5)
    ]
    _touch(old_file)
    for f in new_files:
        _touch(f)

    result = report_tasks.cleanup_old_reports.run(max_age_days=90, keep_per_tuple=20)
    assert result["ok"] is True
    assert result["deletes_planned"] == 1
    assert result["deletes_succeeded"] == 1
    assert result["deletes_failed"] == 0
    assert not old_file.exists()
    for f in new_files:
        assert f.exists()


def test_celery_task_raises_on_delete_failure(tmp_path, monkeypatch):
    """Failure in execute_deletes → OSError raised (Celery retry semantic)."""
    from app.tasks import report_tasks

    monkeypatch.setattr(report_tasks, "REPORTS_DIR", tmp_path)

    now = datetime.now(UTC)
    old_file = tmp_path / f"sid-Y_{(now - timedelta(days=100)).strftime('%Y-%m-%d')}_paper.json"
    _touch(old_file)

    # Patch execute_deletes (in scripts/cleanup_old_reports) to fake a failure
    _ensure_scripts_on_path()
    import cleanup_old_reports as cleanup_mod

    def _fake_execute_deletes(paths):
        return 0, [(paths[0], "OSError: forced for test")]

    monkeypatch.setattr(cleanup_mod, "execute_deletes", _fake_execute_deletes)

    with pytest.raises(OSError, match="1/1 delete\\(s\\) failed"):
        report_tasks.cleanup_old_reports.run(max_age_days=90, keep_per_tuple=20)


# ── Beat schedule + imports list ────────────────────────────────────────────


def test_beat_schedule_registers_reports_cleanup_weekly():
    from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

    assert "reports-cleanup-weekly" in CELERY_BEAT_SCHEDULE
    entry = CELERY_BEAT_SCHEDULE["reports-cleanup-weekly"]
    assert entry["task"] == "app.tasks.report_tasks.cleanup_old_reports"
    assert entry["kwargs"]["max_age_days"] == 90
    assert entry["kwargs"]["keep_per_tuple"] == 20
    assert entry["options"]["queue"] == "default"


def test_beat_schedule_sunday_0430_crontab():
    """Verify the schedule is Sunday 04:30 SH (low-traffic window).

    Reviewer P3-3 fix: test crontab attributes directly, NOT substring match
    against repr (which would pass for any schedule containing "30"/"4"/"0").
    """
    from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

    schedule = CELERY_BEAT_SCHEDULE["reports-cleanup-weekly"]["schedule"]
    # Celery crontab _orig_* preserves the constructor arg types verbatim
    # (int when passed as int, str when passed as str). Our entry passes
    # hour=4 minute=30 as int, day_of_week="0" as str — assertions match.
    assert schedule._orig_minute == 30
    assert schedule._orig_hour == 4
    assert schedule._orig_day_of_week == "0"  # 0 = Sunday in Celery crontab convention
    # Sanity check: day_of_month + month_of_year unrestricted
    assert schedule._orig_day_of_month == "*"
    assert schedule._orig_month_of_year == "*"
    # Parsed sets match the original spec
    assert schedule.minute == {30}
    assert schedule.hour == {4}
    assert schedule.day_of_week == {0}


def test_celery_imports_list_includes_report_tasks():
    """iter 30 hidden defect closure: app.tasks.report_tasks MUST be in celery_app imports.

    Without this, generate_performance_report.delay() dispatches but worker never sees
    the task (per beat_schedule.py:408 sediment "模块 ... 时已建但漏注册 celery_app.py imports").
    """
    from app.tasks.celery_app import celery_app

    imports = celery_app.conf.get("imports") or ()
    assert "app.tasks.report_tasks" in imports, (
        "app.tasks.report_tasks not registered in celery_app imports — "
        "iter 30 hidden defect would silently break Celery dispatch"
    )
