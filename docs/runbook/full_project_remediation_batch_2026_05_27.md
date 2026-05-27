# Full Project Remediation Batch Runbook — 2026-05-27

> Scope: follow-up to `docs/audit/FULL_PROJECT_CLOSURE_AND_GOVERNANCE_AUDIT_2026_05_27.md`.
> This runbook started as a control document. On 2026-05-28 the user explicitly unlocked related remediation operations; DB migration, service restart, and backend-code remediation results are recorded below.

## Guardrails

- Keep the staged Codex governance package intact.
- Keep the full audit report uncommitted unless the user asks to stage it.
- DB mutation and Servy restart were unlocked by the user on 2026-05-28 for the findings in this batch.
- Do not run broker mutation calls.
- Because `python scripts/_verify_account_oneshot.py` stopped at miniQMT connect return code `-1`, backend production-code edits remain redline-gated in this batch.

## Batch Map

| Batch | Finding | Action type | Status |
|---|---|---|---|
| B0 | Missing `memory/project_sprint_state.md` | Doc governance | Completed: minimal handoff restored and updated. |
| B1 | `pipeline_settings` missing | DB migration | Completed: migration applied, singleton row verified. |
| B2 | Runtime route drift for `/api/system/beat-schedule` | Servy runtime ops | Completed: FastAPI/Worker/Beat restarted; route returns 200. |
| B3 | `/api/system/health` timeout / session concurrency | Backend code | Completed: bounded health checks, sequential datasource reads, Windows Celery fallback. |
| B4 | `daily_attribution` 0 rows | Runtime/data evidence | Completed: task apply writes row for configured `PAPER_STRATEGY_ID`; API returns latest row. |
| B5 | Scheduler failures | Ops triage | Read-only diagnostics allowed; mutation/toggle requires unlock. |
| B6 | `.agents/skills` policy | Agent governance | Needs explicit track-vs-local-only decision. |

## B1 — Pipeline Settings Migration

Evidence:
- Migration exists: `backend/migrations/pipeline_settings.sql`.
- Rollback exists: `backend/migrations/pipeline_settings_rollback.sql`.
- Audit DB probe found the table missing.
- `backend/app/api/pipeline.py` reads `pipeline_settings` in `/automation-level`, `/pause`, `/resume`, and `/status`.

Result:
- Applied `backend/migrations/pipeline_settings.sql` on 2026-05-28.
- Verified singleton row: `id=1`, `automation_level='L0'`, `paused_at=NULL`, `paused_reason=NULL`.
- Re-probed `GET /api/pipeline/status`: 200, active run `gp_2026w16_000147e8`, `automation_level='L0'`.

Rollback boundary:
- Use `backend/migrations/pipeline_settings_rollback.sql` only if the apply causes a runtime regression.
- Capture before/after SQL output in a dated audit note.

## B2 — Servy Runtime Route Refresh

Evidence:
- Working-tree code defines `GET /api/system/beat-schedule`.
- Runtime returned 404 before service reload.

Result:
- Restarted FastAPI, Celery Worker, and Celery Beat through `scripts/service_manager.ps1`.
- Left QMT Data Service stopped because it is manual and outside this remediation.
- `GET /api/system/beat-schedule`: 200 with 27 Beat entries.
- `GET /api/system/health`: 200 with `overall_status='ok'` after the Windows solo-worker fallback fix.

## B3 — System API Health Fix Candidate

Root-cause evidence gathered:
- `backend/app/api/system.py` currently uses `asyncio.gather()` with one injected `AsyncSession` for datasource queries.
- SQLAlchemy async sessions are not safe for concurrent operations on the same session.
- Logs showed concurrent-operation errors in `system.py`.
- `/api/system/health` also waits on Celery inspect and can consume most of the endpoint timeout budget.

Result:
- `/api/system/datasources` now queries sequentially on the request `AsyncSession`.
- `/api/system/health` now bounds PG/Redis/Celery sub-checks and degrades instead of hanging.
- Windows Celery solo-pool health now uses process fallback first and exposes a warning that `inspect` was skipped.
- Added regression tests for Celery timeout behavior and Windows process fallback.

## B4 — Attribution Evidence Policy

Evidence:
- `daily_attribution` table exists.
- Audited row count was zero.
- Beat schedule includes `daily-attribution-compute` in code.

Result:
- Fixed runtime import root setup so `backend.qm_platform.*` resolves from Celery/FastAPI/manual task contexts.
- Changed attribution task `strategy_id` from a hard-coded placeholder to `settings.PAPER_STRATEGY_ID`, aligning write and read paths.
- Manual task apply wrote `daily_attribution.id=2` for `28fc37e5-2d32-4ada-92e0-41c11a5103d0`.
- `GET /api/attribution/latest`: 200 with that row.
- Deleted the earlier manual-test noise row `daily_attribution.id=1` for `paper-strategy-default`; kept scheduler logs as audit trail.

## B5 — Scheduler Failure Triage

Evidence:
- `QM-ICMonitor` had latest failure code `1`.
- `QM-SmokeTest` had latest failure code `3221225786`.

Allowed read-only diagnostics:
- Inspect task definitions.
- Inspect last-run output/log files.
- Compare against docs that already mention these tasks.

Blocked actions without unlock:
- Enable, disable, re-register, or modify any Task Scheduler task.
- Edit scripts that would affect scheduled production behavior.

## B6 — Skills Version Policy

Evidence:
- `.agents/skills` is the active Codex project skill layer.
- Many `.agents/skills/...` files are untracked.
- `.claude/skills` remains tracked historical state.

Decision options:
- Track active `.agents/skills` files as project governance assets.
- Keep them local-only and update docs/hooks to treat missing project skills as non-fatal.

Recommended next audit artifact:
- A skill inventory table: skill name, path, tracked state, duplicate historical source, active trigger, keep/remove/local-only decision.
