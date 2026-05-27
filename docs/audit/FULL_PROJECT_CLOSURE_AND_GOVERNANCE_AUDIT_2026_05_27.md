# QuantMind V2 Full Project Closure and Governance Audit — 2026-05-27

> Mode: audit + governance backlog only. No business-code fix, no DB write, no service restart, no `.env` / broker / Servy / Task Scheduler / production YAML mutation.
> Fresh verify timestamp: 2026-05-27 23:55 Asia/Shanghai.

## Remediation Addendum — 2026-05-28 00:25 Asia/Shanghai

The first remediation batch has been executed after user authorization for related operations.

Closed:
- `pipeline_settings` migration applied; `/api/pipeline/status` returns 200 with automation level `L0`.
- FastAPI, Celery Worker, and Celery Beat restarted; `/api/system/beat-schedule` returns 27 entries.
- `/api/system/health` fixed for DB-session concurrency and slow sub-checks; runtime now returns `overall_status='ok'`.
- Celery health now reports Windows solo worker liveness through process fallback and includes a warning when `inspect` is skipped.
- Attribution task import roots and `strategy_id` source fixed; `daily_attribution.id=2` exists for configured `PAPER_STRATEGY_ID`, and `/api/attribution/latest` returns it.

Still open:
- `QM-ICMonitor` and `QM-SmokeTest` scheduler disposition.
- `.agents/skills` version-control policy.
- QMT Data Service remains stopped intentionally because this batch did not require PT/QMT runtime activation.

## Executive Summary

QuantMind V2 has broad implementation coverage across backend, frontend, factor research, strategy/backtest, V3 risk, scheduling, observability, backup, CI, and agent governance. The codebase is no longer a prototype: current static inventory shows 157 FastAPI endpoints, 32 frontend routes, 27 Celery Beat entries, 366 backend test files, and a live local stack with PostgreSQL, Redis, FastAPI, Celery Worker, and Celery Beat running.

The project is partially closed, not fully closed. Build and core collect-only checks pass, and the Codex hook layer is now structurally wired. The remaining risk is concentrated in runtime/data/schema closure and governance source-of-truth drift:

- P0: `pipeline_settings` migration is not applied in the local DB, causing `/api/pipeline/status` to return 500 and breaking PipelineConsole pause/automation closure.
- P1: runtime FastAPI is not aligned with current working-tree routes: code has `/api/system/beat-schedule`, but the running service returns 404.
- P1: `/api/system/health` timed out under runtime probe, and FastAPI logs show async SQLAlchemy session concurrency errors in `system.py`.
- P1: Wave 4 attribution closure is not evidenced by data: `daily_attribution` exists but has 0 rows.
- P1: scheduler state has failed operational tasks (`QM-ICMonitor`, `QM-SmokeTest`) despite high-level health returning pass.
- P1: document governance still points to a missing `memory/project_sprint_state.md`.
- P1: `.agents/skills` is the Codex active skill layer, but many new skill files remain untracked while `.claude/skills` is tracked historical state.

## Evidence Map

| Area | Evidence |
|---|---|
| Worktree baseline | `git status --short --branch`: Codex governance package staged; `.agents/skills/...` and `nul` remain untracked. |
| Backend API | Static scan of `backend/app/api/*.py`: 26 API files, 157 route decorators. |
| Frontend | `frontend/src/router.tsx`: 32 route entries; `frontend/src/pages`: 24 page files; `frontend/src/api`: 15 API wrapper files. |
| Tests | `backend/tests`: 366 `test_*.py` files; selected collect-only run collected 97 tests. |
| Runtime services | `powershell -File scripts/service_manager.ps1 status`: Redis, PostgreSQL16, FastAPI, Celery Worker, Celery Beat running; QMT Data Service stopped. |
| FastAPI health | `GET /api/health`: 200 with `all_pass=true`. |
| DB snapshot | Read-only SQL: `factor_values=841,507,511`, `factor_ic_history=145,942`, `factor_registry=286`, `strategy_registry=2`, `risk_event_log=3`, `event_outbox=6`, `scheduler_task_log=1,651`, `daily_attribution=0`, `pipeline_settings` missing. |
| Build | `npm run build -- --mode development`: passed; only large `vendor-echarts` warning. |
| Git hook | Git Bash `config/hooks/pre-commit`: passed, staged LLM import skipped, 7 staged markdown files warning-only. |
| Codex hooks | `.codex/hooks.json`: 11 referenced hook files; 0 missing; 0 unwired `.py`; smoke from prior Codex governance audit passed. |

## Findings

### P0 — Pipeline runtime closure is broken by missing migration

`backend/app/api/pipeline.py` reads `pipeline_settings` for automation level and pause state (`pipeline.py:219`, `pipeline.py:278`, `pipeline.py:429`). The migration exists at `backend/migrations/pipeline_settings.sql`, but read-only DB verification returned `pipeline_settings: exists=False`.

Impact:
- `GET /api/pipeline/status` returned 500.
- `PipelineConsole` depends on `/pipeline/status`, pause/resume, and automation level (`frontend/src/api/pipeline.ts:115`, `frontend/src/api/pipeline.ts:136`, `frontend/src/api/pipeline.ts:187`, `frontend/src/pages/PipelineConsole.tsx:318`).
- The pipeline control-plane UI is not runtime-closed until the migration state is reconciled.

Backlog:
- Apply or reconcile `backend/migrations/pipeline_settings.sql` in a separate DB-mutation plan.
- Add a smoke/health check that fails loudly when required runtime tables are missing.
- Add an API-level regression for `/api/pipeline/status` against a DB with the singleton row present.

### P1 — Runtime FastAPI routes lag working-tree code

Working-tree code defines `/api/system/beat-schedule` at `backend/app/api/system.py:346`, and `SchedulerDashboard` declares it as the S3 data source (`frontend/src/pages/SchedulerDashboard.tsx:7`, `frontend/src/api/system.ts:134`). Runtime probe returned 404 for `GET /api/system/beat-schedule`, while `GET /api/system/scheduler` returned 200.

Impact:
- SchedulerDashboard is only partially closed: Windows schtasks render path works, Celery Beat schedule path is unavailable at runtime.
- This matches the existing status note that Wave 5 runtime verification is pending Servy restart/user touchpoint (`SYSTEM_STATUS.md:11`, `SYSTEM_STATUS.md:39`).

Backlog:
- After current governance package is committed, run the planned elevated Servy restart walkthrough.
- Re-probe `/api/system/beat-schedule`, `/api/system/scheduler-task-log`, and SchedulerDashboard after restart.
- Add a small runtime route snapshot check so future route additions cannot be claimed closed before service reload.

### P1 — `/api/system/health` can hang and logs show async session concurrency errors

Runtime probe of `GET /api/system/health` timed out after 8 seconds. The function concurrently checks PG/Redis/Celery (`backend/app/api/system.py:298-330`). FastAPI logs show SQLAlchemy async session concurrency errors in `system.py` and `pipeline.py`, including "This session is provisioning a new connection; concurrent operations are not permitted".

Impact:
- Service manager status currently prints an incomplete health section even though `/api/health` passes.
- Operator-facing detailed health is not reliable enough as a closure gate.

Backlog:
- Split DB-bound checks so a single `AsyncSession` is not used concurrently.
- Add timeout/fail-loud wrappers per sub-check and surface partial status instead of hanging.
- Add a runtime smoke for `/api/system/health` with a hard timeout.

### P1 — Attribution pipeline exists but has no persisted rows

`daily_attribution` table exists, and Beat has `daily-attribution-compute` in code (`backend/app/tasks/beat_schedule.py:507`, `backend/app/tasks/attribution_tasks.py:120`). Read-only DB verification returned `daily_attribution: count=0`.

Impact:
- Wave 4 attribution has code and scheduling artifacts but no runtime persistence evidence in this DB.
- `/api/attribution/latest` returned 404, so Operator UI attribution views can only be considered code-closed, not data-closed.

Backlog:
- Inspect recent `scheduler_task_log` rows for `daily_attribution_compute` after a service restart and next eligible trading window.
- Add a backfill/dry-run report path that can prove attribution computation without mutating production tables.
- Define "0 rows acceptable" conditions explicitly if PT pause means no attribution should be produced.

### P1 — Scheduler operational status is mixed

`GET /api/system/scheduler` returned 7 Windows tasks. Two have failed latest status: `QM-ICMonitor` (`last_result_code=1`) and `QM-SmokeTest` (`last_result_code=3221225786`). Service status also shows QMT Data Service stopped, consistent with PT paused.

Impact:
- High-level `/api/health` pass is not enough to claim schedule closure.
- Operator UI should distinguish "platform services up" from "scheduled operations healthy".

Backlog:
- Treat scheduler failures as a separate operational health dimension.
- Add a clear stale/failing task policy in docs and UI.
- Decide whether `QM-SmokeTest` is retired, broken, or should be re-registered.

### P1 — Sprint handoff SSOT path is missing

`AGENTS.md` names `memory/project_sprint_state.md` as current handoff SSOT (`AGENTS.md:5`, `AGENTS.md:19`, `AGENTS.md:30`, `AGENTS.md:372`). Repository search found no such file. Multiple docs still reference it.

Impact:
- Session-start SOP cannot be followed as written.
- Audit and implementation agents may anchor to a non-existent handoff source.

Backlog:
- Decide whether the active handoff source is external, archived, or should be recreated in repo.
- If external, update AGENTS and fresh-read SOP to say so explicitly.
- Add a lightweight doc-path existence check to governance hooks or CI.

### P1 — Skills/agents governance is split across three layers

Tracked historical state includes `.claude/skills` and `.claude/agents`. Codex active state is staged under `.codex/agents` and currently reads project skills from `.agents/skills`. `git status` shows many `.agents/skills/...` files untracked, while `AGENTS.md` now points to `.agents/skills` as the Codex current layer (`AGENTS.md:174`, `AGENTS.md:508`).

Impact:
- The runtime skill layer can drift from versioned project state.
- A future clone may get `.codex` hooks/agents but not the `.agents` skills they reference.

Backlog:
- Decide the version-control policy for `.agents/skills`: track all active project skills, or document them as local-only installed artifacts.
- Add a skill inventory audit: skill name, path, tracked/untracked, duplicate in `.claude`, active trigger status.
- Keep `.claude` as historical state unless a separate migration plan is approved.

### P2 — CI is useful but not a full closure gate

GitHub Actions has `regression` and `ci_matrix` jobs marked `continue-on-error: true` (`.github/workflows/ci.yml:102`, `.github/workflows/ci.yml:122`). Local Git hooks have stronger pre-push smoke gates (`config/hooks/pre-push:90`), while pre-commit markdown canonical checks are warning-only (`config/hooks/pre-commit:190-199`).

Impact:
- CI/CD is partially enforceable but not equivalent to local governance.
- Closure claims should separate "advisory CI" from "blocking CI".

Backlog:
- Promote one advisory CI job at a time once baselines are committed and self-hosted assumptions are clear.
- Keep README explicit about warning-only checks.
- Add a CI governance matrix to the next audit report.

### P2 — Frontend API discipline is mostly good, with one intentional exception

Static scan found raw axios only in `frontend/src/api/client.ts`, `frontend/src/__tests__/api.test.ts`, and `frontend/src/store/notificationStore.ts`. The store file contains no actual axios import; it only documents why it remains a Zustand notification SSOT.

Impact:
- API wrapper discipline is effectively intact.
- Existing text comments can trigger naive raw-axios scans unless the scanner distinguishes imports from prose.

Backlog:
- Keep `frontend/src/api/client.ts` as the only production axios import.
- Update future scanners to parse imports, not comments.

## Closed / Healthy Areas

- Backend route surface is broad and registered in code: 26 API modules and 157 route decorators.
- Frontend route surface is complete enough for current Operator UI: 32 routes and 24 page files.
- Build passes with Vite/TypeScript.
- Selected backend collect-only run covered pipeline status, risk events, trailing stop, factor registry, and strategy registry: 97 tests collected.
- Codex hook governance from the prior package is structurally clean: 11 wired hooks, no missing hook files, no unwired `.py` residual.
- Git pre-commit runs successfully in the current staged state.

## Governance Backlog

| Priority | Item | Owner surface | Notes |
|---|---|---|---|
| P0 | Apply/reconcile `pipeline_settings` migration | DB + PipelineConsole | Requires separate DB-mutation authorization. |
| P1 | Servy restart + route runtime re-verify | Ops runtime | Needed to flip Wave 5 runtime-verified status. |
| P1 | Fix `/api/system/health` timeout/session concurrency | Backend system API | Add sub-check timeouts and avoid concurrent use of one `AsyncSession`. |
| P1 | Scheduler failure triage | Ops + UI | `QM-ICMonitor` and `QM-SmokeTest` need disposition. |
| P1 | Attribution evidence policy | Eval/Beat/UI | Decide whether 0 rows is acceptable while PT is paused. |
| P1 | Handoff SSOT repair | Docs governance | Resolve missing `memory/project_sprint_state.md`. |
| P1 | `.agents/skills` version policy | Agent governance | Track active skills or mark local-only; avoid hybrid ambiguity. |
| P2 | CI advisory-to-blocking roadmap | CI/CD | Promote after baselines and runner assumptions are stable. |
| P2 | Scanner precision | Frontend governance | Avoid comment-only axios false positives. |

## Verification Log

- `git status --short --branch`: captured current staged Codex governance package and untracked `.agents/skills` / `nul`.
- Static API/page/hook/skill/doc maps: completed with inline Python scripts, no repo writes.
- `powershell -File scripts/service_manager.ps1 status`: completed; service status read-only.
- `GET /api/health`: 200, `all_pass=true`.
- `GET /api/system/health`: timeout after 8 seconds.
- `GET /api/system/beat-schedule`: 404.
- `GET /api/system/scheduler`: 200 with 7 schtasks.
- Read-only SQL table existence/count probe: completed.
- `python -m pytest --collect-only -q backend/tests/test_pipeline_status_contract.py backend/tests/test_risk_events_endpoint.py backend/tests/test_trailing_stop.py backend/tests/test_factor_registry.py backend/tests/test_strategy_registry.py`: 97 tests collected.
- `npm run build -- --mode development`: passed; large ECharts chunk warning only.
- `C:\Program Files\Git\bin\bash.exe config/hooks/pre-commit`: passed.

## Non-Actions

- Did not apply migrations.
- Did not restart services.
- Did not edit `.env`, broker code, Servy config, Task Scheduler, or production YAML.
- Did not stage this audit report.
- Did not alter `.claude`.
- Did not change `.agents/skills` or `nul`.
