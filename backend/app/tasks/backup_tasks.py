"""MVP 4.4 sub-iter 7 (iter 75 batch) — Backup Celery Beat task wrappers.

Wires qm_platform.backup orchestrators behind Celery tasks:
  - daily_backup_run_task — invokes DB + Filesystem + Config orchestrators @ 02:30 SH
  - weekly_backup_verify_task — restore verification + RPO/RTO alert @ Sunday 04:00 SH

Beat schedule registered via beat_schedule.py entries:
  - "daily-backup-run" (crontab hour=2 minute=30 — avoids 03:00 SH VACUUM schtask)
  - "weekly-backup-verify" (crontab hour=4 minute=0 day_of_week=0 — Sunday after FS retention)

铁律 44 X9 post-merge ops: Servy restart QuantMind-CeleryBeat AND QuantMind-Celery
(沿用 attribution_tasks.py iter 65 体例 — new task module + Beat entries must restart).

铁律 32 transaction boundary — Celery task is the commit owner.
铁律 33 fail-soft tier-2 — top-level try/except ensures Beat survival.
"""

from __future__ import annotations

import logging
import time

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.backup_tasks.daily_backup_run_task")
def daily_backup_run_task(self) -> dict:
    """Daily orchestrated backup — runs DB + Filesystem + Config in canonical order.

    Beat trigger: 02:30 SH (after midnight; before 03:00 VACUUM schtask).

    Returns:
        dict — per-target summary {target, passed, bytes_written, duration_ms}.
    """
    try:
        from backend.qm_platform.backup import (
            ConfigBackupOrchestrator,
            DBBackupOrchestrator,
            FilesystemBackupOrchestrator,
            all_targets_passed,
            total_bytes_written,
        )

        start = time.monotonic()
        results = []
        for orch in (
            DBBackupOrchestrator(),
            FilesystemBackupOrchestrator(),
            ConfigBackupOrchestrator(),
        ):
            results.extend(orch.run_all())

        total_elapsed_ms = int((time.monotonic() - start) * 1000)
        summary = {
            "passed": all_targets_passed(results),
            "total_bytes_written": total_bytes_written(results),
            "total_duration_ms": total_elapsed_ms,
            "per_target": [
                {
                    "target": r.target.value,
                    "passed": r.passed,
                    "bytes_written": r.bytes_written,
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ],
        }
        logger.info("[Backup] daily run summary: %s", summary)
        return summary
    except Exception as e:  # noqa: BLE001 — 铁律 33 tier-2 (Beat survival)
        logger.error("[Backup] daily_backup_run_task failed: %s", e, exc_info=True)
        return {"error": str(e)}


@celery_app.task(bind=True, name="app.tasks.backup_tasks.weekly_backup_verify_task")
def weekly_backup_verify_task(self) -> dict:
    """Weekly restore verification + RPO/RTO breach check + alert dispatch.

    Beat trigger: Sunday 04:00 SH (after 03:00 VACUUM; low-activity window).

    Returns:
        dict — verification result + snapshot + alert_fired flag.
    """
    try:
        from backend.qm_platform.backup import (
            DBBackupOrchestrator,
        )
        from backend.qm_platform.backup.orchestrator import BackupTarget
        from backend.qm_platform.backup.restore_verification import (
            RestoreVerificationOrchestrator,
        )
        from backend.qm_platform.backup.rpo_rto import (
            compute_rpo_rto_snapshot,
            fire_rpo_rto_alert,
        )

        start = time.monotonic()

        # Step 1: restore verification (pg_restore --list on latest artifact)
        verifier = RestoreVerificationOrchestrator()
        verify_results = verifier.run_all()
        verify_passed = all(r.passed for r in verify_results)
        verify_duration_ms = sum(r.duration_ms for r in verify_results)

        # Step 2: RPO/RTO snapshot using DB backup spec artifact_dir
        db_spec = DBBackupOrchestrator().spec
        snapshot = compute_rpo_rto_snapshot(
            artifact_dir=db_spec.artifact_dir,
            last_restore_duration_seconds=verify_duration_ms / 1000.0,
        )

        # Step 3: fire alert if breach (fail-soft inside)
        alert_fired = fire_rpo_rto_alert(snapshot)

        total_elapsed_ms = int((time.monotonic() - start) * 1000)
        summary = {
            "verify_passed": verify_passed,
            "rpo_hours_actual": snapshot.rpo_hours_actual,
            "rto_hours_actual": snapshot.rto_hours_actual,
            "rpo_breached": snapshot.rpo_breached,
            "rto_breached": snapshot.rto_breached,
            "alert_fired": alert_fired,
            "total_duration_ms": total_elapsed_ms,
            "target": str(BackupTarget.DB.value),
        }
        logger.info("[Backup] weekly verify summary: %s", summary)
        return summary
    except Exception as e:  # noqa: BLE001 — 铁律 33 tier-2 (Beat survival)
        logger.error("[Backup] weekly_backup_verify_task failed: %s", e, exc_info=True)
        return {"error": str(e)}
