---
description: Codex remediation handoff updated after 2026-06-01 governance batch 2.
date: 2026-06-01 +08:00
status: governance_batch_2_meta_monitor_verified_open_secret_backlog
source_report: docs/audit/STATUS_REPORT_2026_06_01_governance_batch_2.md
---

# Project Sprint State

## Current Handoff — 2026-06-01 Batch 2

Mode: full-project closure/governance remediation, batch 2 verified.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker calls, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT startup unless specifically required.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Diagnosed GB1-B1 `meta_alert:litellm_failure_rate` from runtime evidence rather than the stale-looking `alert_dedup` row alone.
- Confirmed the alert condition cleared after the 2026-06-01 11:15 Asia/Shanghai fire: `meta_monitor` rows at 11:20, 11:25, 11:30, 11:35, and 11:40 all reported `triggered=0`.
- Root cause remains primary DeepSeek authentication rejection in `logs/celery-slow-stderr.log`, followed by LiteLLM fallback to local Qwen; `.env` / secret rotation was not performed.
- Fixed latent meta-monitor noise: `_collect_litellm` now excludes intentional `budget_capped` local fallback from both API-attempt denominator and failure numerator.
- Added regression coverage in `backend/tests/test_meta_monitor_service.py`.

Verified:
- Focused collector regression: 3 passed.
- `ruff check` on touched files: PASS.
- `pytest backend/tests/test_meta_monitor_service.py backend/tests/test_meta_alert_rules.py -q`: 106 passed.
- Read-only live SQL at 11:39-11:40: recent 1-hour API-attempt classification remained 13 failures / 13 attempts / 0 budget-cap rows; latest 5-minute window had 0 calls and 0 failures.

Still open:
- P0 runtime blocker: DeepSeek primary provider credential is rejected; requires user/operator secret rotation or provider-side account fix. Acceptance: controlled primary LiteLLM call succeeds, `llm_call_log` primary rows show `error_class IS NULL`, and `meta_monitor` stays `triggered=0` across at least two 5-minute ticks with LLM traffic.
- P1 observability backlog: fallback-success rows only persist `primary_fail_fallback_engaged`; sanitized provider error category is not durable after logs rotate.
- Batch-1 runtime backlog remains: realtime risk/QMT input path verification is still open and was not touched.

Next safe step:
- Continue with either the realtime risk/QMT runtime-input audit (read-only until an explicit ops touchpoint is chosen) or a frontend/API contract closure batch. Do not mutate secrets autonomously.

## Current Handoff — 2026-06-01

Mode: full-project closure/governance remediation, batch 1 verified.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.
- User authorized autonomous remediation, but continue to avoid broker calls, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT startup unless specifically required.
- Read-only account verification was attempted with `python scripts/_verify_account_oneshot.py`; miniQMT connect returned `-1`, so account-state verification is not complete in this shell.

Closed in this batch:
- Fixed pytest discovery drift: `pyproject.toml` now uses `backend/tests`, with `backend/tests/test_pytest_config.py` guarding the setting.
- Wired local pre-commit collect-only coverage to active governance inventory and hook behavior tests.
- Moved hook behavior tests from stale `.claude` mirror paths to active `.codex/hooks`.
- Extended cite-drift hook V3 path scope to active `.codex/agents` and repo `.agents/skills`.
- Fixed active `iron_law_enforce.py` Windows redirected-stdout crash by emitting ASCII-safe JSON and parsing hook JSON in tests.
- Removed frontend circuit-breaker `/risk/*/default` usage; `SafetyControlPanel` and `RiskManagement` now use configured `PAPER_STRATEGY_ID` through UUID-keyed `src/api/risk.ts` wrappers.

Verified:
- `python scripts/ci_run_phase.py --phase pre_commit` PASS.
- Governance/hook pytest subset: 120 passed.
- Smoke: 91 passed, 2 skipped.
- Frontend risk/API/page Vitest subset: 21 passed.
- `npm run build` PASS, with chunk-size warning only.
- Manual active-hook PT warning probe returned rc=0 JSON.

Still open:
- P0 runtime backlog: active LLM failure-rate meta alert and realtime risk path not exercising portfolio/QMT inputs remain unresolved.
- P1 frontend/API backlog: websocket route mismatch, notification mock seeding, mining selected-ID placeholder, and CI/GitHub governance parity need next batches.
- Backup/GP/backtest first-fire evidence from the 2026-05-29 handoff remains relevant unless superseded by newer runtime proof.

Next safe step:
- Continue with a second remediation batch focused on either runtime meta-monitor/LLM failure-rate diagnosis or frontend/API contract closure. Avoid starting QMT/Servy ops until an explicit runtime touchpoint is chosen.

## Current Handoff — 2026-05-29

Mode: remediation batch after full project closure and governance audit.

Current scope:
- Current PR branch is `codex/governance-runtime-remediation`; local `.codex/config.toml` permission settings are user-owned and should remain unstaged unless explicitly requested.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.
- First repair batch completed for pipeline settings, runtime route refresh, system health, import-root setup, and attribution evidence.
- User authorized related remediation operations on 2026-05-28.
- Still avoid broker calls, `.env` edits, Servy config edits, Task Scheduler changes, and production YAML changes unless the action is specifically required.

Fresh-read / grounding status:
- `AGENTS.md`, `IRONLAWS.md`, `LESSONS_LEARNED.md`, `SYSTEM_STATUS.md`, `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`, `docs/V3_IMPLEMENTATION_CONSTITUTION.md`, `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`, `docs/adr/REGISTRY.md`, and `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` were re-read on 2026-05-29.
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
- Closed attribution NAV input stub: `daily_attribution_compute_task` now reads exact-date `performance_series.daily_return` / NAV fallback instead of hardcoding `nav_change_pct=0.0`; paused-day missing rows remain explicit no-op.
- Closed Agent LLM observability read stubs: `/api/agent/cost-summary` and `/api/agent/{name}/logs` now read `llm_call_log`, and the frontend cost dashboard displays USD truth instead of synthetic CNY.
- Closed Agent model-health static stub: `/api/agent/model-health` now reports observed health from recent `llm_call_log` rows with explicit missing/stale/error states; live provider ping remains future ops enhancement.
- Closed CI pre-push smoke timeout drift: direct smoke passed in 123s, so the pre-push orchestrator wrapper timeout is now 180s while preserving per-test `--timeout=60`.
- Closed attribution contributor empty-dict stub: `daily_attribution_compute_task` now feeds existing factor/sector/cost attribution engines from read-only portfolio, factor, IC, price, industry, and trade-log inputs; Dashboard empty state now means no attributable latest-row inputs, not unimplemented wiring.
- Closed BruteForce mining placeholder: `run_bruteforce_mining` now executes the existing BruteForce engine, writes `bf_` quick-gate candidates with explicit pending full-review metadata, and `BruteForceEngine._compute_ic_series` delegates to `engines.ic_calculator.compute_ic_series`.
- Closed mining full-gate contract drift: `run_full_gate` now calls `FactorGatePipeline.run_gates` and reads `GateReport.gates` / `overall_status`, replacing the stale non-existent `run` contract.
- Code-closed GP cross-round feedback: the scheduled Celery GP task and manual CLI runner now load previous results plus reviewed approval/rejection decisions, inject approved seed / rejected blacklist feedback into `GPEngine`, run full Gate with that blacklist, and persist full-Gate rejects for the next run.
- Closed mining evaluate service contract drift: `/api/mining/evaluate` now computes an IC series, calls `FactorGatePipeline.run_gates`, and adapts `GateReport.gates` / `overall_status` into the API response.
- Closed SessionStart memory path drift: `.codex/hooks/session_context_inject.py` now reads repo-local `memory/project_sprint_state.md` first and only falls back to historical Claude memory when repo memory is absent.
- Closed Backtest API worker runner drift: `app.tasks.backtest_tasks.run_backtest` now executes via `PlatformBacktestRunner` + `InMemoryBacktestRegistry` before writing the existing API result tables; direct worker calls to `run_hybrid_backtest` are removed.
- Closed Backtest research-script bypass regrowth risk: historical one-off `scripts/research/` direct engine calls are explicitly allowlisted, and `check_backtest_runner_bypass.py` is wired into pre-commit/CI to block new untracked bypasses.
- Closed Task Scheduler running-state false failure: runtime probe found `QM-HealthCheck` LastResult `267009` misclassified as `failed`; `/api/system/scheduler` now maps it to `running`.
- Closed Pipeline stale-running runtime blockage: `/api/pipeline/status` now surfaces `is_stale_running` / `stale_reason`, localhost-only `POST /api/pipeline/runs/{run_id}/cancel` is wired to `MiningService.cancel_task`, Pipeline Console exposes cancel and correct pause/resume semantics, and stale rows `gp_2026w16_000147e8` / `gp_2026w15_000147e8` were explicitly cancelled.
- Closed GP dependency gap for scheduled mining: `deap>=1.4.1` is declared in `pyproject.toml`, installed in `.venv`, and GP engine/cross-round tests now run instead of skipping.
- Closed 2026-05-29 `signal_phase` data-gap runtime failure: Tushare later had same-day data; controlled fetch wrote 5,477 `klines_daily` / 5,477 `daily_basic` / 5,477 `stock_status_daily` rows, rerun wrote 131,448 `factor_values` rows and 5 paper `signals`, and latest `scheduler_task_log.signal_phase` is `success`.
- Added a T-day data readiness guard in `scripts/run_paper_trading.py` so future same-day data outages fail at `klines_daily` / `daily_basic` readiness instead of misleadingly surfacing as empty factor generation.
- Closed Celery backup PG CLI precondition drift: Platform backup tasks now resolve `pg_dump.exe` / `pg_restore.exe` from `PG_BIN` or known Windows install paths, pass `PGPASSWORD` into subprocesses, and runtime probe resolves both tools under `D:\pgsql\bin`.
- Closed Celery fake-alive / queue-stall runtime defect: `/api/system/health` now checks Redis queue backlog, `scripts/ops/celery_queue_hygiene.py` safely purges expired Redis Celery messages, Windows Workers disable gossip/mingle/heartbeat, `QuantMind-Celery` consumes only `default`, new `QuantMind-CelerySlow` consumes `data_fetch,factor_calc`, slow Beat entries are routed off core queue, and `consume_fill_events` no longer sends Redis `BLOCK 0`.
- Runtime recovery applied on 2026-05-29: installed/imported `QuantMind-CelerySlow`, imported updated Worker/Beat Servy configs, restarted Worker/Slow/Beat/FastAPI, and verified 125s of Beat operation with `default=0`, `data_fetch=0`, `factor_calc=0`; `/api/system/health` reports `worker_count=2` and `queue_status.max_depth=0`.
- Removed the manual-test attribution noise row for the old placeholder strategy.
- Reclassified `QM-SmokeTest` scheduler failure as a disabled-task stale LastResult false positive; scheduler API/UI now carries disabled status.
- Repaired `QM-DailyBackup` guardrails: backup writes to `.dump.tmp`, rejects undersized dumps, verifies size before restore-list, and uses current Parquet snapshot columns.
- Recovered today's DR artifact with `python scripts/pg_backup.py --skip-parquet`: `quantmind_v2_20260528.dump` is 14,480.2MB and `pg_restore --list` passed with 712 tables / 2,359 objects.
- Restarted FastAPI; `/api/system/scheduler` now returns `QM-SmokeTest` as `status=disabled`, `enabled=false`.

Still open:
- `QM-ICMonitor` latest code `1` is an IC P1 alert signal, not a scheduler crash; API/UI now expose it as `alert` with a `/factors/monitoring` operator action.
- GitHub Actions workflow now uses `actions/checkout@v6` and `actions/setup-python@v6` to clear the near-term Node 20 runtime warning.
- Existing `.claude/external-skills/mattpocock-skills` gitlink now has matching `.gitmodules` metadata; no `.claude/` historical content was edited.
- Advisory `regression` and `ci_matrix` CI jobs now use `scripts/ci_run_phase.py --advisory`: structured failures log `ADVISORY_FAIL` and exit 0, while uncaught runner exceptions still fail.
- Frontend raw axios scanner precision is closed: `scripts/audit/check_frontend_api_discipline.py` ignores comments/tests, blocks production raw axios outside `frontend/src/api/client.ts`, and is wired into local pre-commit + CI pre_commit.
- `QM-DailyBackup` Task Scheduler first-fire is now runtime-verified success on 2026-05-29 02:00 (`last_result_code=0`); Celery Beat `daily-backup-run` / `weekly-backup-verify` still need their own first-fire evidence.
- Backup Beat entries still need their next scheduled first-fire observed after the new audit envelope; the PG binary/env precondition is now closed.
- QMT Data Service remains stopped by design; do not start it without an explicit PT/QMT ops reason.
- 2026-05-29 Tushare `daily_basic` had high `pe_ttm` / `dv_ttm` null-ratio warnings during controlled fetch; DataPipeline logged the warning and still upserted valid rows. Treat as data-quality signal, not a signal-chain blocker after successful factor/signal rerun.
- `/api/system/health` process fallback now reports the new 2-worker topology, but `celery inspect ping` remains skipped on Windows solo Worker by design.

Next safe step:
- Observe the next scheduled backup first-fire evidence, a controlled GP next-run feedback consumption proof after DEAP installation, and a controlled Backtest API worker first-fire; otherwise continue design-doc implementation-gap audit, now focusing on runtime first-fire evidence and optional batched migration of allowlisted historical research scripts with reproducibility checks.
