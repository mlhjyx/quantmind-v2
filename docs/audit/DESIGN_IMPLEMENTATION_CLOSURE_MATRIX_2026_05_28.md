# Design Implementation Closure Matrix — 2026-05-28

> Scope: full-project closure audit across frontend/operator UI, factor/strategy/backtest, risk/scheduler/runtime, hooks, and skills.
> Method: three read-only explorer agents + local `rg` verification on 2026-05-28 Asia/Shanghai. This report records implementation status and the next governance backlog; it does not claim runtime proof where only static code/test evidence exists.

## Executive Verdict

| Area | Verdict | Summary |
|---|---|---|
| Operator UI Wave 5 | IMPLEMENTED_INTEGRATED | Routes, sidebar entries, `src/api` adapters, backend endpoints, and backend tests exist for PT status, IC monitoring, backtest compare, scheduler dashboard, and risk event trace. Main remaining gap is frontend page-level test depth. |
| Pipeline API closure | MOSTLY_IMPLEMENTED | PN-001/002/003/004 are implemented. PN-005 HTTP log backfill and first writer call sites are implemented; WebSocket live tailing, broader task instrumentation, and durable retention remain backlog. |
| Factor registry/onboarding | IMPLEMENTED_INTEGRATED | Registry and onboarding enforce G9/G10 with tests. Lifecycle defaults do not mean G1-G10 are all automatic for every caller. |
| GP/mining closed loop | MOSTLY_IMPLEMENTED | GP engine/orchestrator/script/API exist. BruteForce API/task is no longer a placeholder and writes `bf_` quick-gate candidates with pending full-review metadata. Mining full-gate wrapper and `/api/mining/evaluate` service path now use the real `FactorGatePipeline.run_gates` contract. The Celery task and CLI script now load previous GP results plus reviewed `gp_approval_queue` decisions, pass approved seeds / rejected blacklist feedback into `GPEngine`, run full Gate with that blacklist, and persist full-Gate rejects for the next run. Remaining gap is controlled end-to-end first-fire evidence. |
| Backtest platform | MOSTLY_IMPLEMENTED_GUARDED | `PlatformBacktestRunner`, CLI integration, `/api/backtest/run` Celery enqueue, and the API worker execution path are now unified on the Platform runner. Remaining direct research-script bypasses are explicitly allowlisted as historical one-off experiments, and pre-commit/CI now blocks new untracked bypasses. Remaining partial scope is controlled runtime evidence and optional historical script migration when reproducibility can be preserved. |
| Strategy framework | PARTIAL_IMPLEMENT_DECISION_LOCKED | Registry/S1/S2/bootstrap exist with tests. Production S1 signal generation already goes through `PlatformSignalPipeline.generate(S1MonthlyRanking)`, but registry-driven multi-strategy signal dispatch is intentionally scoped out by ADR-096 until persistence/execution parity criteria are met. |
| Risk realtime / scheduler | PARTIAL_RUNTIME_PROOF | L1 realtime tasks and several Beat-backed features are wired and tested. Runtime first-fire proof remains pending for Servy/Beat-backed paths. |
| Governance hooks/skills | IMPLEMENTED_GOVERNED | `.codex` hooks and `.agents/skills` are governed. Hook smoke tests target the active Codex layer and the skill inventory now has an automated guard. |

## Findings

| ID | Severity | Finding | Evidence | Decision / Fix |
|---|---|---|---|---|
| DCM-001 | P1 | PN-001/002/003/004 design docs still read like current 404/mismatch problems even though implementation exists. | `docs/design/PN_001_automation_level_persistence.md`, `PN_002_factor_correlation_prune.md`, `PN_003_pipeline_pause_gate.md`, `PN_004_pipeline_status_contract_refactor.md`; tests: `backend/tests/test_pipeline_automation_level.py`, `test_factor_correlation_prune.py`, `test_pipeline_pause.py`, `test_pipeline_status_contract.py`. | Fixed in this governance batch by adding 2026-05-28 status addenda. |
| DCM-002 | P1 | `docs/API_COVERAGE.md` had a stale §6 snapshot that still looked like current orphan truth. | Header and §6.1 already said 0 current frontend-only orphans, while §6 rows still said O3/O8/O10 missing. | Fixed in this batch by marking §6 as historical and labeling resolved rows. |
| DCM-003 | P1 | PMSRule 14:30 Beat was still described as current in AGENTS and V3 risk design, but code marks that Beat retired. | `AGENTS.md`; `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`; `backend/app/tasks/beat_schedule.py` retired entry. | Fixed in this batch: PMSRule is now documented as pure-rule/historical semantic anchor; production path is L1 realtime + trailing_stop. |
| DCM-004 | P1 | Backtest submit closure was misclassified: backend already enqueues Celery, but frontend `BacktestConfig` posted a UI-only `{market,time_range,...}` body that did not satisfy backend `BacktestRunRequest`. | `backend/app/api/backtest.py`; `backend/app/tasks/backtest_tasks.py`; pre-fix `frontend/src/pages/BacktestConfig.tsx`; `frontend/src/api/backtest.ts`. | Fixed 2026-05-28 follow-up: frontend now builds backend schema, API adapter type matches backend, and tests assert Celery enqueue + frontend payload shape. |
| DCM-005 | P1 | Registry-driven multi-strategy signal dispatch is not the production signal phase driver. | `backend/app/tasks/daily_pipeline.py` delegates to `run_signal_phase`; `backend/app/services/signal_service.py` already calls `PlatformSignalPipeline.generate(S1MonthlyRanking)`, while `strategy_bootstrap.py` is wired for risk checks. | Fixed 2026-05-28 follow-up as a boundary decision: ADR-096 scopes registry-driven production signal migration out until S1 parity, S2 metadata loaders, and per-strategy persistence/execution contracts exist. Added `test_strategy_signal_boundary.py`. |
| DCM-006 | P1 | GP closed loop was not a full self-learning loop. | `backend/engines/mining/gp_engine.py`, `backend/app/tasks/mining_tasks.py`, `scripts/run_gp_pipeline.py`, `backend/app/api/mining.py`; tests exist. | Code closure 2026-05-29: scheduled Celery path and CLI path now feed previous-run + human approval/rejection seed/blacklist into the next generation and persist full-Gate rejects. Remaining B3 is controlled end-to-end first-fire evidence. |
| DCM-007 | P2 | Realtime risk, dynamic thresholds, trade-event consumer, and daily reconciliation have code/tests but lack fresh runtime first-fire evidence. | Beat/task files and tests exist; runtime proof is blocked by Servy/Beat activation evidence, not by repository wiring. | Backlog B4: capture process CreationDate, Beat schedule registration, `scheduler_task_log` first-fire rows, and risk/outbox side effects. |
| DCM-008 | P2 | Dynamic threshold audit table exists but operational path is Redis-only. | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` already annotates DB audit write as deferred; `dynamic_threshold_tasks.py` writes Redis cache. | Keep as explicit deferred audit feature unless a delta-flush task is prioritized. |
| DCM-009 | P2 | Governance tests still referenced `.claude/hooks` while active hook layer is `.codex/hooks`. | `.codex/hooks.json`; hook smoke tests under `backend/tests/test_*hook.py`. | Fixed 2026-05-28 follow-up: hook smoke tests now target `.codex/hooks`; SessionEnd handoff test asserts Codex retirement decision. |
| DCM-010 | P2 | `.agents/skills` had governance docs but no automated inventory test. | `.agents/skills/README.md`; `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`. | Fixed 2026-05-28 follow-up: `backend/tests/test_codex_governance_inventory.py` verifies hook wiring and skill path resolution. |
| DCM-011 | P1 | Backend/migration allow automation level `L4`, but frontend `AutomationLevel` type and selector stopped at `L3`. | `backend/app/api/pipeline.py` defines `Literal["L0", "L1", "L2", "L3", "L4"]`; `backend/migrations/pipeline_settings.sql` CHECK allows `L4`; pre-fix `frontend/src/api/pipeline.ts` omitted `L4`. | Fixed in this batch: frontend type, PipelineConsole selector, and `pipeline-api.test.ts` now include L4. |
| DCM-012 | P2 | Frontend page smoke tests still asserted old Dashboard component test ids after the page had moved to the DashboardOverview module layout. | `frontend/src/__tests__/pages.test.tsx`; current Dashboard renders `驾驶舱`, `净值曲线`, and `A股策略 v1.1` directly. | Fixed 2026-05-28 follow-up: page smoke tests now assert current user-visible anchors and mock current dashboard API/chart dependencies. |
| DCM-013 | P1 | `/api/mining/evaluate` service path still used the stale non-existent `FactorGatePipeline.run` / `run_quick` API even after the batch fixed the GP full-gate wrapper. | `backend/app/services/mining_service.py`; current gate contract is `FactorGatePipeline.run_gates` returning `GateReport.gates` / `overall_status`. | Fixed 2026-05-29 follow-up: service computes an IC series, calls `run_gates`, and adapts `GateReport` to the legacy API response fields. Added `test_mining_service.py`. |
| DCM-014 | P2 | Codex SessionStart hook still preferred historical Claude memory and could misreport repo-local `memory/project_sprint_state.md` frontmatter as missing. | `.codex/hooks/session_context_inject.py`; repo-local `memory/project_sprint_state.md` has a `description` frontmatter field. | Fixed 2026-05-29 follow-up: hook now prefers repo-local `memory/` and falls back to historical Claude memory only when repo memory is absent. Added hook regression coverage. |

## Domain Matrix

### Frontend / Operator UI

| Claim | Code evidence | Test evidence | Verdict | Next action |
|---|---|---|---|---|
| MVP 5.1 PT status page and scheduler task log are wired. | `frontend/src/router.tsx`, `frontend/src/pages/PtStatus.tsx`, `frontend/src/api/system.ts`, `backend/app/api/system.py`. | `backend/tests/test_scheduler_task_log_endpoint.py`. | IMPLEMENTED_INTEGRATED | Add frontend render tests later. |
| MVP 5.2 IC monitoring is wired. | `frontend/src/pages/IcMonitoring.tsx`, `frontend/src/api/factors.ts`, `backend/app/api/factors.py`. | `backend/tests/test_factors_ic_monitoring_endpoint.py`. | IMPLEMENTED_INTEGRATED | Add chart/error/loading frontend tests later. |
| MVP 5.3 backtest compare is wired. | `frontend/src/pages/BacktestCompare.tsx`, `frontend/src/api/backtest.ts`, `backend/app/api/backtest.py`. | `backend/tests/test_backtest_api.py`. | IMPLEMENTED_INTEGRATED | Update any old docs that still say NAV/trades are unconnected if encountered. |
| MVP 5.4 risk event trace is wired. | `frontend/src/pages/RiskManagement.tsx`, `frontend/src/components/risk/RiskEventTracePanel.tsx`, `frontend/src/api/risk.ts`, `backend/app/api/risk.py`. | `backend/tests/test_risk_events_endpoint.py`. | IMPLEMENTED_INTEGRATED | Add frontend query-param mapping test later. |
| MVP 5.5 scheduler dashboard is wired. | `frontend/src/pages/SchedulerDashboard.tsx`, `frontend/src/api/system.ts`, `backend/app/api/system.py`. | `backend/tests/test_beat_schedule_endpoint.py`, `test_scheduler_task_log_endpoint.py`. | IMPLEMENTED_INTEGRATED | Runtime schedule evidence still belongs to B4. |

### Factor / Strategy / Backtest

| Claim | Code evidence | Test evidence | Verdict | Next action |
|---|---|---|---|---|
| Factor registry/onboarding gates enforce G9/G10. | `backend/qm_platform/factor/registry.py`, `backend/app/services/factor_onboarding.py`. | `backend/tests/test_factor_registry.py`, `test_factor_onboarding_gates.py`. | IMPLEMENTED_INTEGRATED | Clarify docs if any claim says every gate is automatic everywhere. |
| Platform evaluation pipeline exists. | `backend/qm_platform/eval/pipeline.py`, `backend/engines/factor_lifecycle.py`. | `backend/tests/test_evaluation_pipeline.py`, `test_factor_lifecycle_eval_integration.py`. | PARTIAL_IMPLEMENT | Document lifecycle default G1+G10 boundary where needed. |
| GP closed loop is complete. | GP engine/orchestrator/script/API exist; BruteForce task now reaches executable engine logic; full-gate wrapper and evaluate endpoint service use the current GateReport contract; GP Celery and CLI paths now preserve previous-run plus human approval/rejection seed/blacklist feedback. | GP/mining tests exist, including BruteForce task runner, full-gate contract coverage, evaluate service contract coverage, and cross-round feedback helper coverage. | MOSTLY_IMPLEMENTED | B3 is now first-fire / controlled run evidence, not missing repository wiring. |
| BacktestRunner is the unified entry. | `backend/qm_platform/backtest/runner.py`, `scripts/run_backtest.py`; API submit path enqueues `app.tasks.backtest_tasks.run_backtest`, whose worker delegates execution through `PlatformBacktestRunner` before writing the existing API result tables. Historical `scripts/research/` bypasses are tracked in `scripts/audit/backtest_runner_bypass_allowlist.txt`; `scripts/audit/check_backtest_runner_bypass.py` prevents new untracked bypasses. | `backend/tests/test_backtest_runner.py`; `backend/tests/test_backtest_api.py`; `backend/tests/test_backtest_tasks.py`; `backend/tests/test_backtest_runner_bypass_audit.py`; `frontend/src/__tests__/backtest-api.test.ts`. | MOSTLY_IMPLEMENTED_GUARDED | Controlled API worker first-fire evidence remains B1 follow-up. Optional migration of historical research scripts should be batched only when old experiment reproducibility is verified. |
| Strategy framework drives production signals. | S1 production path is `SignalService -> PlatformSignalPipeline.generate(S1MonthlyRanking)`; registry bootstrap is risk-check-only. | Strategy tests plus `test_strategy_signal_boundary.py`. | PARTIAL_IMPLEMENT_DECISION_LOCKED | ADR-096 scopes registry-driven multi-strategy signal loop out of this batch. |

### Risk / Scheduler / Governance

| Claim | Code evidence | Test evidence | Verdict | Next action |
|---|---|---|---|---|
| PMSRule current 14:30 Beat path is live. | Code marks the Beat retired; PMSRule file remains. | `backend/tests/test_risk_rules_pms.py`. | STALE_DOC_FIXED | This batch corrected AGENTS and V3 risk docs. |
| Pipeline automation-level L4 is selectable end-to-end. | Backend API/migration support L4; frontend type and selector now include L4. | `frontend/src/__tests__/pipeline-api.test.ts` includes L4 GET/PUT checks. | IMPLEMENTED_INTEGRATED | Keep CI build/test green. |
| L1 realtime risk has production wire. | `backend/app/tasks/beat_schedule.py`, `backend/app/tasks/celery_app.py`. | `test_realtime_risk_tasks.py`, `test_realtime_risk_engine.py`. | PARTIAL_RUNTIME_PROOF | B4. |
| Dynamic threshold cache is operational. | `backend/app/tasks/dynamic_threshold_tasks.py`, `backend/qm_platform/risk/dynamic_threshold/cache.py`. | `test_dynamic_threshold_tasks.py`. | PARTIAL_IMPLEMENT | Keep Redis-only SSOT unless audit flush is prioritized. |
| Codex hooks are active governance layer. | `.codex/hooks.json`, `.codex/hooks/*.py`. | Hook smoke tests now target `.codex`; inventory test checks all wired Python hooks exist and no 0-wire Python hook remains. | IMPLEMENTED_GOVERNED | Continue smoke coverage as hook semantics change. |
| Project skills are governed. | `.agents/skills/README.md`, `.agents/skills/*/SKILL.md`. | Inventory test checks every skill directory has `SKILL.md` and AGENTS/V3 explicit skill references resolve. | IMPLEMENTED_GOVERNED | Extend test only when new skill reference styles are introduced. |

## Backlog

| Batch | Scope | Acceptance |
|---|---|---|
| B1 | Backtest execution closure | **MOSTLY DONE + GUARDED 2026-05-29 follow-up.** API submit has tested Celery enqueue and UI payload alignment; the Celery worker now executes via `PlatformBacktestRunner` with `InMemoryBacktestRegistry` while preserving the existing API result persistence contract. Non-archive research bypasses are triaged as historical one-off experiments and guarded by an allowlist scanner wired into pre-commit/CI. Remaining acceptance: collect controlled API worker first-fire evidence; optionally migrate allowlisted research scripts in batches with reproducibility checks. |
| B2 | Strategy signal production integration | **DONE 2026-05-28 follow-up for audit closure.** ADR-096 explicitly scopes registry-driven production signal migration out. Future implementation acceptance is S1 parity, S2 metadata loaders, and per-strategy persistence/execution contracts. |
| B3 | GP closed-loop completion | **PARTIAL DONE 2026-05-29 follow-up.** Scheduled Celery path and CLI path now wire previous-run results plus reviewed approval/rejection decisions into `GPEngine` and persist full-Gate rejects for the next run. `/api/mining/evaluate` now also uses the current GateReport contract. Remaining acceptance: one controlled end-to-end run or scheduled first-fire evidence proving the persisted feedback is consumed on the following run. |
| B4 | Runtime first-fire proof | Servy/Beat process timestamp, schedule registration, `scheduler_task_log` first-fire rows, and domain side-effect proof for realtime risk / dynamic threshold / trade-event consumer / daily reconciliation. |
| B5 | Hook path drift cleanup | **DONE 2026-05-29 follow-up.** Tests/docs target `.codex/hooks` as active layer; `.claude/hooks` is mirror-only / historical. SessionStart now prefers repo-local `memory/` before historical Claude memory. |
| B6 | Skill inventory guard | **DONE 2026-05-28 follow-up.** Automated check verifies `.agents/skills/*/SKILL.md` and AGENTS/V3 explicit skill references. |

## Verification

| Check | Result |
|---|---|
| Frontend build | PASS — `npm run build -- --mode development` |
| Frontend API unit | PASS — `npm exec vitest -- run src/__tests__/pipeline-api.test.ts` (11 passed) |
| Backend PN contract subset | PASS — `pytest backend/tests/test_pipeline_automation_level.py backend/tests/test_pipeline_pause.py backend/tests/test_pipeline_status_contract.py backend/tests/test_pipeline_logs.py backend/tests/test_factor_correlation_prune.py -q` (26 passed) |
| Codex hook / skill governance subset | PASS — `pytest backend/tests/test_codex_governance_inventory.py backend/tests/test_block_dangerous_git_hook.py backend/tests/test_cite_drift_stop_pretool_hook.py backend/tests/test_redline_pretool_block_hook.py backend/tests/test_sediment_poststop_hook.py backend/tests/test_session_context_inject_hook.py backend/tests/test_verify_completion_hook.py backend/tests/test_handoff_sessionend_hook.py -q` (164 passed) |
| Backtest submit contract subset | PASS — `pytest backend/tests/test_backtest_api.py -q` (31 passed); `npm exec vitest -- run src/__tests__/pages.test.tsx src/__tests__/backtest-api.test.ts` (11 passed); `npm run build -- --mode development` |
| Strategy signal boundary subset | PASS — `pytest backend/tests/test_strategy_signal_boundary.py -q` (2 passed); `ruff check` and `ruff format --check` pass for the new test. |
| Mining evaluate service contract subset | PASS — `pytest backend/tests/test_mining_service.py backend/tests/test_mining_api.py -q` (23 passed) |
| SessionStart memory path subset | PASS — `pytest backend/tests/test_session_context_inject_hook.py backend/tests/test_codex_governance_inventory.py -q` (14 passed) |
| Static drift grep | PASS — stale PN problem statements are now marked design-time/historical; current API orphan truth is 0 in `docs/API_COVERAGE.md` header and §6.1/§10. |

## Non-Goals For This Batch

- No broker call, order placement, liquidation, or QMT state mutation.
- No `.env`, production YAML, or destructive DB mutation.
- No large strategy/backtest runtime rewrite inside a documentation/governance batch.
