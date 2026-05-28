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
| B2 | Runtime route drift for `/api/system/beat-schedule` | Servy runtime ops | Completed: FastAPI/Worker/Beat restarted; route returns 200 and canonical alias join populates existing `last_fire_*`. |
| B3 | `/api/system/health` timeout / session concurrency | Backend code | Completed: bounded health checks, sequential datasource reads, Windows Celery fallback, available-RAM memory threshold. |
| B4 | `daily_attribution` 0 rows | Runtime/data evidence | Completed: task apply writes row for configured `PAPER_STRATEGY_ID`; API returns latest row. |
| B5 | Scheduler failures | Ops triage | Partially closed: disabled-task false positive fixed, DailyBackup DR risk repaired, ICMonitor API/UI reclassified as alert signal. |
| B6 | `.agents/skills` policy | Agent governance | Completed: active project skills are versioned; `.claude/skills` kept historical. |
| B7 | Full-project governance objective | Governance control | Completed: objective and completion criteria captured in `docs/audit/PROJECT_GOVERNANCE_OBJECTIVE_2026_05_28.md`. |
| B8 | API/status document drift | Doc governance | Completed: `docs/API_COVERAGE.md` header now points to §9 current counts; `SYSTEM_STATUS.md` risk-design row now reflects redirect stub state. |
| B9 | API O7 pipeline logs orphan | Backend/API closure | Completed: `GET /api/pipeline/{run_id}/logs` Redis HTTP backfill implemented and tested; PN-005 writer/WS remain enhancement backlog. |
| B10 | GitHub Actions Node 20 runtime deprecation | CI governance | Completed: workflow uses Node 24-native action major versions. |
| B11 | GitHub checkout submodule metadata warning | Git governance | Completed: `.gitmodules` restored for the existing mattpocock skills gitlink. |
| B12 | Advisory CI red annotation noise | CI governance | Completed: `--advisory` mode logs structured failures as `ADVISORY_FAIL` with exit 0; runner exceptions still fail. |
| B13 | Frontend raw axios scanner precision | Frontend governance | Completed: comment-aware scanner added and wired into local pre-commit + CI pre_commit. |
| B14 | Attribution NAV input stub | Eval/Beat closure | Completed: Beat wrapper now reads exact-date `performance_series.daily_return` / NAV fallback instead of hardcoded `0.0`; regression tests cover daily_return, derived-NAV, and paused-day no-op paths. |
| B15 | Agent cost/log read stubs | AI governance | Completed: `/api/agent/cost-summary` and `/api/agent/{name}/logs` now read `llm_call_log`; frontend cost dashboard now displays USD truth instead of synthetic CNY. |

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
- Follow-up fix: `/api/system/beat-schedule` now maps Celery dotted task names to canonical `scheduler_task_log` aliases, so existing rows populate `last_fire_*`.
- Backup Beat tasks now write `scheduler_task_log` rows for `daily_backup_run` and `weekly_backup_verify`.

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
- Memory health now follows the project resource floor: ok when `available_gb >= 8`, instead of false-critical around 16GB used on a 32GB host.
- Added regression tests for Celery timeout behavior and Windows process fallback.

## B4 — Attribution Evidence Policy

Evidence:
- `daily_attribution` table exists.
- Audited row count was zero.
- Beat schedule includes `daily-attribution-compute` in code.

Result:
- Fixed runtime import root setup so `backend.qm_platform.*` resolves from Celery/FastAPI/manual task contexts.
- Changed attribution task `strategy_id` from a hard-coded placeholder to `settings.PAPER_STRATEGY_ID`, aligning write and read paths.
- Replaced the Beat wrapper's hardcoded NAV-change stub with exact-date `performance_series` input. It prefers `daily_return`, derives from current/previous NAV when needed, and only returns `0.0` when no exact-date NAV row exists.
- Manual task apply wrote `daily_attribution.id=2` for `28fc37e5-2d32-4ada-92e0-41c11a5103d0`.
- `GET /api/attribution/latest`: 200 with that row.
- Deleted the earlier manual-test noise row `daily_attribution.id=1` for `paper-strategy-default`; kept scheduler logs as audit trail.

## B5 — Scheduler Failure Triage

Evidence:
- `QM-ICMonitor` had latest failure code `1`.
- `QM-SmokeTest` had latest failure code `3221225786`.
- Follow-up `GET /api/system/scheduler` found `QM-DailyBackup` active/Ready with latest failure code `3221225786`.
- `logs/ic_monitor.log` shows the 2026-05-24 `QM-ICMonitor` code `1` corresponds to one P1 IC decay alert, not a traceback or scheduler infrastructure failure.
- `docs/SCHEDULING_LAYOUT.md` and `SYSTEM_STATUS.md` already classify `QM-SmokeTest` as disabled/one-time completed.
- `logs/backup.log` showed the 2026-05-28 backup started then stopped after writing only about 222MB; recent healthy dumps are 11-15GB.

Result:
- `backend/app/api/system.py` now maps disabled Windows tasks to `status='disabled'` and exposes `task_state` / `enabled`.
- Frontend scheduler consumers now preserve disabled status and exclude disabled tasks from overdue counts.
- `QM-ICMonitor` `alert` rows now include factor-quality disposition metadata and the System Settings scheduler row links operators to `/factors/monitoring`.
- `scripts/pg_backup.py` now writes to `.dump.tmp`, rejects undersized dumps before final replacement, verifies file size before `pg_restore --list`, and updates Parquet snapshot SQL to current column names.
- Controlled recovery run: `python scripts/pg_backup.py --skip-parquet` completed on 2026-05-28, produced `quantmind_v2_20260528.dump` at 14,480.2MB, and `pg_restore --list` passed with 712 tables / 2,359 objects.
- FastAPI was restarted; `GET /api/system/scheduler` now reports `QM-SmokeTest` as `task_state='Disabled'`, `enabled=false`, `status='disabled'`.

Remaining:
- The next scheduled `QM-DailyBackup` first-fire result still needs observation because Task Scheduler LastResult remains the failed 02:00 run until the task fires again; the manual rerun restored today's DR artifact.

## B6 — Skills Version Policy

Evidence:
- `.agents/skills` is the active Codex project skill layer.
- Many `.agents/skills/...` files are untracked.
- `.claude/skills` remains tracked historical state.

Decision:
- Track active `.agents/skills` files as project governance assets.
- Keep `.claude/skills` historical and unchanged.
- Add `.agents/skills/README.md` as the local policy file.
- Remove the empty root `nul` file as runtime/generated noise.

Audit artifact:
- `docs/audit/SKILLS_GOVERNANCE_AUDIT_2026_05_28.md`.

## B7 — Full-Project Governance Objective

Evidence:
- User clarified the durable objective: full project closure review, code/doc/module
  inventory, drift remediation, hooks/skills/agents governance, CI/PR auditability,
  and active fixing rather than passive backlog accumulation.

Result:
- Added `docs/audit/PROJECT_GOVERNANCE_OBJECTIVE_2026_05_28.md`.
- The new artifact defines scope, working loop, redline boundary, and completion
  evidence criteria for the continuing governance goal.

## B8 — API/Status Document Drift

Evidence:
- `docs/API_COVERAGE.md` top summary still said 148 backend endpoints and 10
  frontend-only orphans, while its own §9 fresh verify records 161 endpoints and
  1 sustained orphan.
- `SYSTEM_STATUS.md` §13 still described `RISK_CONTROL_SERVICE_DESIGN.md` as a
  678-line partially deprecated document, while the current file is a redirect stub
  to the archived historical body.

Result:
- Updated the API coverage header and executive summary to point readers to §9 as
  the current count baseline and to keep the old matrix body as historical evidence.
- Updated `SYSTEM_STATUS.md` §13 to describe the risk-control design file as a
  retired redirect stub with the archive path.

## B9 — Pipeline Logs HTTP Backfill

Evidence:
- `frontend/src/api/pipeline.ts::getPipelineLogs()` called
  `GET /api/pipeline/{run_id}/logs`.
- `docs/API_COVERAGE.md` and `docs/design/PN_005_pipeline_log_history_subsystem.md`
  classified this as the last sustained frontend-only orphan.

Result:
- Added `PipelineLogEntry` response model and
  `GET /api/pipeline/{run_id}/logs` in `backend/app/api/pipeline.py`.
- The endpoint reads Redis list `pipeline:logs:{run_id}`, decodes JSON entries,
  normalizes `warn` to `warning`, skips malformed rows with a warning, and returns
  `[]` on Redis transport failure because this is observability-only UI.
- Removed the stale frontend comment that said the backend endpoint did not exist.
- Updated API coverage and PN-005 design notes to mark HTTP backfill closed.

Remaining enhancement backlog:
- Add writer instrumentation in pipeline tasks/services.
- Add optional `/ws/pipeline/{run_id}` live tailing.
- Decide whether durable DB history is needed beyond Redis recent logs.

## B10 — GitHub Actions Node Runtime

Evidence:
- The PR CI run emitted GitHub's Node 20 JavaScript action runtime deprecation warning.
- The warning recommended opting into Node 24 before the default switch.

Result:
- GitHub release probes verified `actions/checkout` latest tag `v6.0.2` and `actions/setup-python` latest tag `v6.2.0`.
- `.github/workflows/ci.yml` now uses `actions/checkout@v6` and `actions/setup-python@v6`.

## B11 — Gitlink Metadata

Evidence:
- CI checkout cleanup warned: `No url found for submodule path '.claude/external-skills/mattpocock-skills' in .gitmodules`.
- `git ls-files -s` showed that path is already tracked as mode `160000`.
- Local gitlink remote is `https://github.com/mattpocock/skills.git`.

Result:
- Added `.gitmodules` entry for the existing `.claude/external-skills/mattpocock-skills` gitlink.
- Did not edit or migrate `.claude/` historical content.

## B12 — Advisory CI Annotation Noise

Evidence:
- After B10/B11, the remaining PR annotations came from `regression` and `ci_matrix`
  steps that intentionally failed internally under `continue-on-error: true`.
- The jobs passed overall, but GitHub still displayed red `Process completed with
  exit code 1` annotations.

Result:
- Added `scripts/ci_run_phase.py --advisory`.
- Structured orchestrator failures now print `status=ADVISORY_FAIL`, include the
  phase details, and exit 0.
- Uncaught exceptions still exit 1, so broken runners are not hidden.
- `.github/workflows/ci.yml` now uses `--advisory` for `regression` and `ci_matrix`
  and no longer relies on `continue-on-error`.

## B13 — Frontend Raw Axios Scanner Precision

Evidence:
- The audit backlog still had a P2 scanner precision item because naive grep found
  `axios` in comments/prose, including the Zustand notification store note.
- Production policy remains: only `frontend/src/api/client.ts` imports axios;
  feature/page code should use `apiClient` via the `src/api` layer.

Result:
- Added `scripts/audit/check_frontend_api_discipline.py`.
- The scanner strips TS/JS comments while preserving line numbers, detects real
  `axios` import/require/dynamic import usage, excludes tests by default, and
  allows only `frontend/src/api/client.ts` in production.
- Wired the scanner into `config/hooks/pre-commit` and the CI `pre_commit`
  orchestrator.
- Added regression tests proving comment-only mentions do not fail while real
  imports outside the allowlist do fail.

## B15 — Agent LLM Observability Read Paths

Evidence:
- `backend/app/api/agent.py` still returned hardcoded zero values from
  `/api/agent/cost-summary` and `[]` from `/api/agent/{name}/logs`.
- The repository already has `llm_call_log` DDL, LLM audit insertion code, and
  frontend AgentConfig cost/log panels.
- The frontend cost dashboard labeled values as CNY even though the persisted
  audit column is `cost_usd`.

Result:
- `/api/agent/cost-summary` now aggregates `llm_call_log` for the requested
  month: total tokens, total `cost_usd`, by-agent task buckets, by-model buckets,
  and daily usage rows.
- `/api/agent/{name}/logs` now returns recent `llm_call_log` rows for the mapped
  agent task family with severity derived from `error_class`, fallback, budget
  state, and decision id.
- Frontend `CostSummary` and `CostDashboard` now use/display USD fields.
- Regression tests cover monthly aggregation, invalid month rejection, and
  per-agent log rows.

Remaining:
- `/api/agent/model-health` is still a static health view until a periodic model
  ping source is implemented; this is a separate ops probe, not cost/log closure.
