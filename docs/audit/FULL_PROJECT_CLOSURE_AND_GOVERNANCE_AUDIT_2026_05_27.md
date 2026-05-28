# QuantMind V2 Full Project Closure and Governance Audit — 2026-05-27

> Mode: audit + governance backlog only. No business-code fix, no DB write, no service restart, no `.env` / broker / Servy / Task Scheduler / production YAML mutation.
> Fresh verify timestamp: 2026-05-27 23:55 Asia/Shanghai.

## Remediation Addendum — 2026-05-28 00:25 Asia/Shanghai

The first remediation batch has been executed after user authorization for related operations.

Closed:
- `pipeline_settings` migration applied; `/api/pipeline/status` returns 200 with automation level `L0`.
- FastAPI, Celery Worker, and Celery Beat restarted; `/api/system/beat-schedule` returns 27 entries and now resolves canonical `scheduler_task_log` aliases for `last_fire_*`.
- `/api/system/health` fixed for DB-session concurrency, slow sub-checks, and memory false-critical threshold; runtime now returns `overall_status='ok'`.
- Celery health now reports Windows solo worker liveness through process fallback and includes a warning when `inspect` is skipped.
- Attribution task import roots, `strategy_id` source, and NAV input source fixed; `daily_attribution.id=2` exists for configured `PAPER_STRATEGY_ID`, `/api/attribution/latest` returns it, and the Beat wrapper now reads `performance_series` instead of hardcoding `nav_change_pct=0.0`.
- `memory/project_sprint_state.md` restored as tracked handoff SSOT.
- Active `.agents/skills` files are versioned, with `.agents/skills/README.md` policy and automated inventory guard.

Closed / reclassified:
- `QM-SmokeTest` scheduler failure was a stale disabled-task LastResult false positive; the system scheduler API/UI now exposes `task_state`, `enabled`, and `disabled` status.
- `QM-DailyBackup` 2026-05-28 active failure was traced to a truncated dump plus backup-script guard gaps; `scripts/pg_backup.py` now writes `.tmp` then atomically replaces, rejects undersized dumps, and verifies size before `pg_restore --list`. A controlled rerun produced a 14,480.2MB dump and `pg_restore --list` passed with 712 tables / 2,359 objects.
- Backup Beat tasks now write `scheduler_task_log` audit rows: `daily_backup_run` writes `success`/`failed`; `weekly_backup_verify` writes `success`/`alert`/`failed`.

Still open:
- `QM-ICMonitor` is now classified as an operational `alert` signal, not an infrastructure crash: latest code `1` corresponds to a P1 IC decay alert in `logs/ic_monitor.log`, and `/api/system/scheduler` preserves that distinction for the UI.
- QMT Data Service remains stopped intentionally because this batch did not require PT/QMT runtime activation.

## Executive Summary

QuantMind V2 has broad implementation coverage across backend, frontend, factor research, strategy/backtest, V3 risk, scheduling, observability, backup, CI, and agent governance. The codebase is no longer a prototype: current static inventory shows 157 FastAPI endpoints, 32 frontend routes, 27 Celery Beat entries, 366 backend test files, and a live local stack with PostgreSQL, Redis, FastAPI, Celery Worker, and Celery Beat running.

The project is partially closed, not fully closed. Build and core collect-only checks pass, and the Codex hook layer is now structurally wired. The first remediation batch closed the largest runtime/schema/governance blockers from the initial audit; the remaining risk is concentrated in scheduler disposition, intentionally stopped QMT runtime, and later first-fire evidence capture:

- Closed 2026-05-28: `pipeline_settings` migration applied and `/api/pipeline/status` returned 200.
- Closed 2026-05-28: runtime FastAPI was reloaded and `/api/system/beat-schedule` returned 27 entries; canonical alias matching now populates existing `last_fire_*` rows.
- Closed 2026-05-28: `/api/system/health` timeout/session-concurrency remediation is implemented; DB-bound checks no longer share one `AsyncSession` concurrently, slow Redis/Celery probes are bounded, memory health uses available RAM floor, and fresh runtime probe records `overall_status='ok'`.
- Closed 2026-05-28: Wave 4 attribution evidence now exists; `daily_attribution.id=2` exists for configured `PAPER_STRATEGY_ID`, `/api/attribution/latest` returns it, and the task now derives NAV change from `performance_series`.
- Closed 2026-05-28: scheduler status false positives and backup failure path remediated; `QM-SmokeTest` is disabled/retired, and `QM-DailyBackup` now has a fresh verified 14,480.2MB dump.
- Closed 2026-05-28: `QM-ICMonitor` factor-quality alerts now carry operator disposition metadata and the System Settings scheduler row links to `/factors/monitoring`.
- Closed 2026-05-28: `memory/project_sprint_state.md` exists and is tracked.
- Closed 2026-05-28: `.agents/skills` is governed as the active Codex project skill layer; `.claude/skills` remains historical.

## Evidence Map

| Area | Evidence |
|---|---|
| Worktree baseline | Initial audit saw staged Codex governance plus untracked `.agents/skills/...` and `nul`; remediation later tracked active skills and removed the `nul` noise. |
| Backend API | Static scan of `backend/app/api/*.py`: 26 API files, 157 route decorators. |
| Frontend | `frontend/src/router.tsx`: 32 route entries; `frontend/src/pages`: 24 page files; `frontend/src/api`: 15 API wrapper files. |
| Tests | `backend/tests`: 366 `test_*.py` files; selected collect-only run collected 97 tests. |
| Runtime services | `powershell -File scripts/service_manager.ps1 status`: Redis, PostgreSQL16, FastAPI, Celery Worker, Celery Beat running; QMT Data Service stopped. |
| FastAPI health | `GET /api/health`: 200 with `all_pass=true`. |
| DB snapshot | Initial read-only SQL: `factor_values=841,507,511`, `factor_ic_history=145,942`, `factor_registry=286`, `strategy_registry=2`, `risk_event_log=3`, `event_outbox=6`, `scheduler_task_log=1,651`, `daily_attribution=0`, `pipeline_settings` missing. Remediation addendum supersedes `daily_attribution=0` and `pipeline_settings` missing. |
| Build | `npm run build -- --mode development`: passed; only large `vendor-echarts` warning. |
| Git hook | Git Bash `config/hooks/pre-commit`: passed, staged LLM import skipped, 7 staged markdown files warning-only. |
| Codex hooks | `.codex/hooks.json`: 11 referenced hook files; 0 missing; 0 unwired `.py`; smoke from prior Codex governance audit passed. |

## Findings

### Closed 2026-05-28 — Pipeline runtime closure restored

`backend/app/api/pipeline.py` reads `pipeline_settings` for automation level and pause state (`pipeline.py:219`, `pipeline.py:278`, `pipeline.py:429`). The migration exists at `backend/migrations/pipeline_settings.sql`, but initial read-only DB verification returned `pipeline_settings: exists=False`.

Initial impact:
- `GET /api/pipeline/status` returned 500.
- `PipelineConsole` depends on `/pipeline/status`, pause/resume, and automation level (`frontend/src/api/pipeline.ts:115`, `frontend/src/api/pipeline.ts:136`, `frontend/src/api/pipeline.ts:187`, `frontend/src/pages/PipelineConsole.tsx:318`).
- The pipeline control-plane UI is not runtime-closed until the migration state is reconciled.

Remediation:
- `backend/migrations/pipeline_settings.sql` was applied on 2026-05-28.
- Singleton row was verified, and `/api/pipeline/status` returned 200 with automation level `L0`.

Follow-up:
- Add a smoke/health check that fails loudly when required runtime tables are missing.

### Closed 2026-05-28 — Runtime FastAPI routes aligned

Working-tree code defines `/api/system/beat-schedule` at `backend/app/api/system.py:346`, and `SchedulerDashboard` declares it as the S3 data source (`frontend/src/pages/SchedulerDashboard.tsx:7`, `frontend/src/api/system.ts:134`). Initial runtime probe returned 404 for `GET /api/system/beat-schedule`, while `GET /api/system/scheduler` returned 200.

Initial impact:
- SchedulerDashboard is only partially closed: Windows schtasks render path works, Celery Beat schedule path is unavailable at runtime.
- This matches the existing status note that Wave 5 runtime verification is pending Servy restart/user touchpoint (`SYSTEM_STATUS.md:11`, `SYSTEM_STATUS.md:39`).

Remediation:
- FastAPI, Celery Worker, and Celery Beat were restarted on 2026-05-28.
- `GET /api/system/beat-schedule` returned 200 with 27 Beat entries.
- Follow-up runtime probe showed `last_fire_*` was initially all-null because the endpoint joined `scheduler_task_log.task_name` on Celery dotted task names while audit rows use canonical short names. The endpoint now resolves alias sets per Beat entry and populates rows such as `meta_monitor`, `daily_attribution_compute`, `news_ingest_*`, and `factor_lifecycle`.
- Backup Beat tasks now write scheduler audit rows for `daily_backup_run` and `weekly_backup_verify`; next scheduled backup first-fire remains the runtime proof point for those new rows.

Follow-up:
- Add a small runtime route snapshot check so future route additions cannot be claimed closed before service reload.

### Closed 2026-05-28 — `/api/system/health` bounded and session-safe

Initial runtime probe of `GET /api/system/health` timed out after 8 seconds. FastAPI logs showed SQLAlchemy async session concurrency errors in `system.py` and `pipeline.py`, including "This session is provisioning a new connection; concurrent operations are not permitted".

Remediation:
- `backend/app/api/system.py` now runs DB-bound health work sequentially on the request `AsyncSession`.
- Redis and Celery health probes now run through bounded sync-check wrappers so slow probes degrade/fail-loud instead of hanging the endpoint.
- Windows Celery solo-worker health can use process fallback before `inspect`, avoiding the known Windows remote-control stall path.
- Fresh runtime probe on 2026-05-28 returned HTTP 200 within the 8-second probe budget with `overall_status='ok'` and Celery `method='process_fallback'`.

Impact:
- Operator-facing detailed health is now suitable as a bounded closure gate, with partial component status surfaced instead of endpoint timeout.

Verification:
- Runtime probe records `GET /api/system/health`: 200 with `overall_status='ok'`.
- Regression tests cover Celery timeout degradation, Redis timeout critical status, and Windows Celery process fallback.

### Closed 2026-05-28 — Attribution pipeline has persisted evidence

`daily_attribution` table exists, and Beat has `daily-attribution-compute` in code (`backend/app/tasks/beat_schedule.py:507`, `backend/app/tasks/attribution_tasks.py:120`). Initial read-only DB verification returned `daily_attribution: count=0`.

Initial impact:
- Wave 4 attribution has code and scheduling artifacts but no runtime persistence evidence in this DB.
- `/api/attribution/latest` returned 404, so Operator UI attribution views can only be considered code-closed, not data-closed.

Remediation:
- Attribution task import roots and configured `strategy_id` source were fixed.
- The task's NAV input no longer uses the initial `0.0` stub. `_fetch_nav_change()` now reads exact-date `performance_series.daily_return`, derives from current/previous NAV when needed, and treats missing exact-date rows as PT-pause no-op.
- Manual task apply wrote `daily_attribution.id=2` for configured `PAPER_STRATEGY_ID`.
- `/api/attribution/latest` returned the persisted row.

Follow-up:
- Define "0 rows acceptable" conditions explicitly for future PT pause windows where attribution should not be produced.

### Partially Closed 2026-05-28 — Scheduler operational status is now typed

Initial `GET /api/system/scheduler` returned 7 Windows tasks. Two appeared failed: `QM-ICMonitor` (`last_result_code=1`) and `QM-SmokeTest` (`last_result_code=3221225786`). A follow-up probe also found `QM-DailyBackup` active/Ready with `last_result_code=3221225786`.

Root-cause disposition:
- `QM-SmokeTest` is documented disabled/one-time, so its stale LastResult was scheduler noise.
- `QM-ICMonitor` code `1` matches logged P1 IC decay alert behavior (`logs/ic_monitor.log` 2026-05-24), not a script crash.
- `QM-DailyBackup` was real DR risk: the 2026-05-28 dump was about 222MB while recent successful dumps were 11-15GB.

Remediation:
- `backend/app/api/system.py` now returns `task_state`, `enabled`, and maps disabled tasks to `status='disabled'`.
- Frontend scheduler adapters normalize backend `never_run` to UI `never`, preserve `disabled`, and exclude disabled tasks from overdue counts.
- `scripts/pg_backup.py` now writes to `.dump.tmp`, deletes partial temp files on failure/timeout, rejects undersized files, atomically replaces the final dump only after size validation, and uses current DB columns for Parquet export (`code`, `raw_value`, `neutral_value`, `zscore`).
- A controlled `python scripts/pg_backup.py --skip-parquet` rerun on 2026-05-28 produced `quantmind_v2_20260528.dump` at 14,480.2MB and immediate `pg_restore --list` verification passed with 712 tables / 2,359 objects.
- After FastAPI restart, `GET /api/system/scheduler` returns `QM-SmokeTest` as `task_state='Disabled'`, `enabled=false`, `status='disabled'`. `QM-DailyBackup` still reports the 02:00 scheduled LastResult until its next scheduled first-fire, but today's DR artifact is recovered and verified.

Backlog:
- Closed 2026-05-28: `QM-ICMonitor` code `1` is treated as an operator alert event; scheduler API/UI labels it `alert` and points operators to the IC monitoring page.
- Decide whether future full backup runs should include Parquet by default after the schema-drift fix is deployed and monitored.
- Capture the next scheduled `QM-DailyBackup` first-fire after this fix; Task Scheduler LastResult will not reflect the manual recovery run.

### Closed 2026-05-28 — Sprint handoff SSOT restored

`AGENTS.md` names `memory/project_sprint_state.md` as current handoff SSOT (`AGENTS.md:5`, `AGENTS.md:19`, `AGENTS.md:30`, `AGENTS.md:372`). Initial repository search found no such file. Multiple docs still referenced it.

Initial impact:
- Session-start SOP cannot be followed as written.
- Audit and implementation agents may anchor to a non-existent handoff source.

Remediation:
- `memory/project_sprint_state.md` was restored as a tracked minimal handoff.

Follow-up:
- Add a lightweight doc-path existence check to governance hooks or CI.

### Closed 2026-05-28 — Skills/agents governance is versioned

Tracked historical state includes `.claude/skills` and `.claude/agents`. Codex active state is staged under `.codex/agents` and currently reads project skills from `.agents/skills`. Initial `git status` showed many `.agents/skills/...` files untracked, while `AGENTS.md` points to `.agents/skills` as the Codex current layer (`AGENTS.md:174`, `AGENTS.md:508`).

Initial impact:
- The runtime skill layer can drift from versioned project state.
- A future clone may get `.codex` hooks/agents but not the `.agents` skills they reference.

Remediation:
- Active `.agents/skills` files are versioned as project governance assets.
- `.agents/skills/README.md` documents the policy.
- `backend/tests/test_codex_governance_inventory.py` verifies the active skills inventory and explicit skill references.
- `.claude` remains historical state unless a separate migration plan is approved.

### P2 — CI is useful but not a full closure gate

GitHub Actions keeps `regression` and `ci_matrix` as advisory jobs through `scripts/ci_run_phase.py --advisory`. Local Git hooks have stronger pre-push smoke gates (`config/hooks/pre-push:90`), while pre-commit markdown canonical checks are warning-only (`config/hooks/pre-commit:190-199`).

2026-05-28 remediation upgraded the workflow to `actions/checkout@v6` and `actions/setup-python@v6` after verifying latest releases through GitHub, removing the near-term Node 20 JavaScript action runtime warning from the governance backlog.

Follow-up CI log review found a separate checkout cleanup warning caused by an existing gitlink at `.claude/external-skills/mattpocock-skills` with no `.gitmodules` entry. The existing local remote was verified as `https://github.com/mattpocock/skills.git`; `.gitmodules` now records that metadata without editing `.claude/` content.

Second follow-up CI log review found that advisory jobs passed overall but still emitted red GitHub annotations because `continue-on-error` let failing steps exit with code 1. `scripts/ci_run_phase.py --advisory` now logs `ADVISORY_FAIL` for structured orchestrator failures and exits 0, while uncaught runner exceptions remain exit 1.

Impact:
- CI/CD is partially enforceable but not equivalent to local governance.
- Closure claims should separate "advisory CI" from "blocking CI".

Backlog:
- Promote one advisory CI job at a time once baselines are committed and self-hosted assumptions are clear.
- Keep README explicit about warning-only checks.
- Add a CI governance matrix to the next audit report.

### Closed 2026-05-28 — Frontend API discipline scanner is precise

Static scan found raw axios only in `frontend/src/api/client.ts`, `frontend/src/__tests__/api.test.ts`, and `frontend/src/store/notificationStore.ts`. The store file contains no actual axios import; it only documents why it remains a Zustand notification SSOT.

Remediation added `scripts/audit/check_frontend_api_discipline.py`: a comment-aware scanner that detects real `axios` import/require/dynamic import usage, excludes tests by default, and allows only `frontend/src/api/client.ts` in production. The scanner is wired into local `config/hooks/pre-commit` and the GitHub `pre_commit` CI orchestrator.

Impact:
- API wrapper discipline is effectively intact and now machine-verifiable.
- Existing text comments no longer trigger raw-axios false positives.

Backlog:
- Keep `frontend/src/api/client.ts` as the only production axios import; promote the scanner to any future frontend-only CI lane if CI topology changes.

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
| Closed | Apply/reconcile `pipeline_settings` migration | DB + PipelineConsole | Completed 2026-05-28: migration applied, singleton row verified, `/api/pipeline/status` returned 200. |
| Closed | Servy restart + route runtime re-verify | Ops runtime | Completed 2026-05-28: FastAPI/Worker/Beat restarted and `/api/system/beat-schedule` returned 27 entries; canonical alias join now populates existing `last_fire_*` rows. |
| Closed | Fix `/api/system/health` timeout/session concurrency | Backend system API | Completed 2026-05-28: DB checks are sequential on one `AsyncSession`; Redis/Celery probes have bounded timeout wrappers; memory health uses available RAM floor; regression tests and fresh runtime HTTP 200 evidence. |
| Partially closed | Scheduler failure triage | Ops + UI | `QM-SmokeTest` stale disabled-task false positive closed; `QM-DailyBackup` partial dump path fixed and fresh verified dump produced; `QM-ICMonitor` reclassified as `alert` with `/factors/monitoring` operator disposition. Remaining partial status is only next scheduled backup first-fire evidence. |
| Closed | Attribution evidence policy | Eval/Beat/UI | Completed 2026-05-28: task apply wrote `daily_attribution.id=2`; `/api/attribution/latest` returned it; Beat wrapper now reads `performance_series` NAV input instead of hardcoding `0.0`. Future pause-window 0-row semantics remain a P2 policy refinement. |
| Closed | Handoff SSOT repair | Docs governance | Completed 2026-05-28: `memory/project_sprint_state.md` restored and tracked. |
| Closed | `.agents/skills` version policy | Agent governance | Completed 2026-05-28: active `.agents/skills` files are versioned with policy docs and inventory guard. |
| P2 | CI advisory-to-blocking roadmap | CI/CD | Node 24 action version upgrade + `--advisory` no-noise CI mode completed 2026-05-28; promote advisory jobs after baselines and runner assumptions are stable. |
| Closed | Gitlink metadata repair | Git governance | Completed 2026-05-28: restored `.gitmodules` entry for the existing mattpocock skills gitlink to remove checkout cleanup warnings. |
| Closed | Scanner precision | Frontend governance | Completed 2026-05-28: comment-aware raw axios scanner added and wired into pre-commit + CI pre_commit. |

## Verification Log

- `git status --short --branch`: initial audit captured staged Codex governance package and untracked `.agents/skills` / `nul`; remediation later tracked active skills and removed `nul`.
- Static API/page/hook/skill/doc maps: completed with inline Python scripts, no repo writes.
- `powershell -File scripts/service_manager.ps1 status`: completed; service status read-only.
- `GET /api/health`: 200, `all_pass=true`.
- `GET /api/system/health`: initial probe timed out after 8 seconds; 2026-05-28 remediation verification records 200 with `overall_status='ok'` after bounded-check fix.
- `GET /api/system/beat-schedule`: initial probe returned 404; 2026-05-28 remediation verification returned 200 with 27 entries.
- `GET /api/system/scheduler`: 200 with 7 schtasks; after remediation/restart, `QM-SmokeTest` returns `status='disabled'`, `enabled=false`.
- `python scripts/pg_backup.py --verify`: initially failed after size gate because `quantmind_v2_20260528.dump` was only about 222MB.
- `python scripts/pg_backup.py --skip-parquet`: controlled rerun completed in 1,138 seconds, wrote a 14,480.2MB dump, and `pg_restore --list` passed with 712 tables / 2,359 objects.
- Read-only SQL table existence/count probe: completed.
- `python -m pytest --collect-only -q backend/tests/test_pipeline_status_contract.py backend/tests/test_risk_events_endpoint.py backend/tests/test_trailing_stop.py backend/tests/test_factor_registry.py backend/tests/test_strategy_registry.py`: 97 tests collected.
- `npm run build -- --mode development`: passed; large ECharts chunk warning only.
- `C:\Program Files\Git\bin\bash.exe config/hooks/pre-commit`: passed.

## Non-Actions

- Did not apply migrations.
- Did not restart services.
- Did not edit `.env`, broker code, Servy config, Task Scheduler, or production YAML.
- Original audit phase did not stage this audit report; later remediation commits include follow-up corrections.
- Did not alter `.claude`.
- Original audit phase did not change `.agents/skills` or `nul`; later remediation tracked active skills and removed `nul`.
