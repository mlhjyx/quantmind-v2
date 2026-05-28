---
description: Codex remediation handoff updated after scheduler and backup remediation.
date: 2026-05-28 04:30 +08:00
status: scheduler_backup_remediation_in_progress
source_report: docs/audit/FULL_PROJECT_CLOSURE_AND_GOVERNANCE_AUDIT_2026_05_27.md
---

# Project Sprint State

## Current Handoff — 2026-05-28

Mode: remediation batch after full project closure and governance audit.

Current scope:
- Preserve the staged Codex governance package as the working baseline.
- Do not commit, unstage, or revert unrelated staged changes.
- First repair batch completed for pipeline settings, runtime route refresh, system health, import-root setup, and attribution evidence.
- User authorized related remediation operations on 2026-05-28.
- Still avoid broker calls, `.env` edits, Servy config edits, Task Scheduler changes, and production YAML changes unless the action is specifically required.

Fresh-read / grounding status:
- `AGENTS.md`, `IRONLAWS.md`, `LESSONS_LEARNED.md`, `SYSTEM_STATUS.md`, `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`, `docs/V3_IMPLEMENTATION_CONSTITUTION.md`, `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`, `docs/adr/REGISTRY.md`, and `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` were read on 2026-05-27.
- The previous handoff path was missing: `memory/project_sprint_state.md` and the parent `memory/` directory did not exist in the repo checkout.
- Redline read-only account verification was attempted with `python scripts/_verify_account_oneshot.py`; it stopped at miniQMT connect return code `-1`, so full account-state verification is not complete in this shell.

Closed in this batch:
- Applied `backend/migrations/pipeline_settings.sql`; `/api/pipeline/status` now returns 200.
- Restarted FastAPI, Celery Worker, and Celery Beat; `/api/system/beat-schedule` now returns 27 entries.
- Fixed `/api/system/health`: bounded checks, sequential datasource reads, and Windows Celery solo-worker process fallback; runtime returns `overall_status=ok`.
- Fixed Beat schedule `last_fire_*` alias drift: Celery dotted task names now match canonical `scheduler_task_log` rows such as `meta_monitor`, `daily_attribution_compute`, `news_ingest_*`, and `factor_lifecycle`.
- Added scheduler audit envelope to backup Beat tasks: `daily_backup_run` writes `success`/`failed`; `weekly_backup_verify` writes `success`/`alert`/`failed`.
- Fixed `/api/system/health` memory false critical by using available RAM floor (`available_gb >= 8`) instead of used RAM <16GB.
- Fixed attribution task import roots and strategy id source; manual task apply wrote `daily_attribution.id=2`; `/api/attribution/latest` returns that row.
- Removed the manual-test attribution noise row for the old placeholder strategy.
- Reclassified `QM-SmokeTest` scheduler failure as a disabled-task stale LastResult false positive; scheduler API/UI now carries disabled status.
- Repaired `QM-DailyBackup` guardrails: backup writes to `.dump.tmp`, rejects undersized dumps, verifies size before restore-list, and uses current Parquet snapshot columns.
- Recovered today's DR artifact with `python scripts/pg_backup.py --skip-parquet`: `quantmind_v2_20260528.dump` is 14,480.2MB and `pg_restore --list` passed with 712 tables / 2,359 objects.
- Restarted FastAPI; `/api/system/scheduler` now returns `QM-SmokeTest` as `status=disabled`, `enabled=false`.

Still open:
- `QM-ICMonitor` latest code `1` is an IC P1 alert signal, not a scheduler crash; API/UI now expose it as `alert` with a `/factors/monitoring` operator action.
- GitHub Actions workflow now uses `actions/checkout@v6` and `actions/setup-python@v6` to clear the near-term Node 20 runtime warning.
- Existing `.claude/external-skills/mattpocock-skills` gitlink now has matching `.gitmodules` metadata; no `.claude/` historical content was edited.
- `QM-DailyBackup` Task Scheduler LastResult remains the failed 02:00 run until next scheduled first-fire, but today's DR artifact has been recovered manually.
- Backup Beat entries still need their next scheduled first-fire observed after the new audit envelope.
- QMT Data Service remains stopped by design; do not start it without an explicit PT/QMT ops reason.

Next safe step:
- Observe the next scheduled `QM-DailyBackup` first-fire after the backup audit envelope; otherwise continue P2 CI/scanner precision governance.
