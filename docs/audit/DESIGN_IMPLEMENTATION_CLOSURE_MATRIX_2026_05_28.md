# Design Implementation Closure Matrix — 2026-05-28

> Scope: full-project closure audit across frontend/operator UI, factor/strategy/backtest, risk/scheduler/runtime, hooks, and skills.
> Method: three read-only explorer agents + local `rg` verification on 2026-05-28 Asia/Shanghai. This report records implementation status and the next governance backlog; it does not claim runtime proof where only static code/test evidence exists.

## Executive Verdict

| Area | Verdict | Summary |
|---|---|---|
| Operator UI Wave 5 | IMPLEMENTED_INTEGRATED | Routes, sidebar entries, `src/api` adapters, backend endpoints, and backend tests exist for PT status, IC monitoring, backtest compare, scheduler dashboard, and risk event trace. Main remaining gap is frontend page-level test depth. |
| Pipeline API closure | MOSTLY_IMPLEMENTED | PN-001/002/003/004 are implemented. PN-005 HTTP log backfill and first writer call sites are implemented; WebSocket live tailing, broader task instrumentation, and durable retention remain backlog. |
| Factor registry/onboarding | IMPLEMENTED_INTEGRATED | Registry and onboarding enforce G9/G10 with tests. Lifecycle defaults do not mean G1-G10 are all automatic for every caller. |
| GP/mining closed loop | PARTIAL_IMPLEMENT | Engine, orchestrator, script, API, and tests exist. Automatic scheduling plus approval feedback into next-round seed/blacklist are not closed. |
| Backtest platform | PARTIAL_IMPLEMENT | `PlatformBacktestRunner` and CLI integration exist, but `/api/backtest/run` is still a submission/status placeholder and many research scripts keep legacy paths. |
| Strategy framework | PARTIAL_IMPLEMENT | Registry/S1/S2/bootstrap exist with tests. Production signal phase still routes through the existing PT signal path instead of a registry-driven `Strategy.generate_signals` loop. |
| Risk realtime / scheduler | PARTIAL_RUNTIME_PROOF | L1 realtime tasks and several Beat-backed features are wired and tested. Runtime first-fire proof remains pending for Servy/Beat-backed paths. |
| Governance hooks/skills | PARTIAL_GOVERNED | `.codex` hooks and `.agents/skills` are governed. Some tests still reference `.claude/hooks`; no lightweight skill inventory test exists yet. |

## Findings

| ID | Severity | Finding | Evidence | Decision / Fix |
|---|---|---|---|---|
| DCM-001 | P1 | PN-001/002/003/004 design docs still read like current 404/mismatch problems even though implementation exists. | `docs/design/PN_001_automation_level_persistence.md`, `PN_002_factor_correlation_prune.md`, `PN_003_pipeline_pause_gate.md`, `PN_004_pipeline_status_contract_refactor.md`; tests: `backend/tests/test_pipeline_automation_level.py`, `test_factor_correlation_prune.py`, `test_pipeline_pause.py`, `test_pipeline_status_contract.py`. | Fixed in this governance batch by adding 2026-05-28 status addenda. |
| DCM-002 | P1 | `docs/API_COVERAGE.md` had a stale §6 snapshot that still looked like current orphan truth. | Header and §6.1 already said 0 current frontend-only orphans, while §6 rows still said O3/O8/O10 missing. | Fixed in this batch by marking §6 as historical and labeling resolved rows. |
| DCM-003 | P1 | PMSRule 14:30 Beat was still described as current in AGENTS and V3 risk design, but code marks that Beat retired. | `AGENTS.md`; `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`; `backend/app/tasks/beat_schedule.py` retired entry. | Fixed in this batch: PMSRule is now documented as pure-rule/historical semantic anchor; production path is L1 realtime + trailing_stop. |
| DCM-004 | P1 | `/api/backtest/run` is named like an executor but currently writes a `running` row without invoking Runner/Celery. | `backend/app/api/backtest.py`; `backend/tests/test_backtest_api.py` asserts `running` response only. | Backlog B1: either wire Celery/Runner execution or rename/document as submission placeholder. Prefer implementation after focused design. |
| DCM-005 | P1 | Strategy framework is not the production signal phase driver. | `backend/qm_platform/strategy/registry.py`, `backend/app/services/strategy_bootstrap.py`; `backend/app/tasks/daily_pipeline.py` still calls the PT signal phase. | Backlog B2: introduce registry-driven signal loop behind parity tests, or explicitly scope strategy framework to research/risk checks until migrated. |
| DCM-006 | P1 | GP closed loop is not a full self-learning loop. | `backend/engines/mining/gp_engine.py`, `pipeline_orchestrator.py`, `scripts/run_gp_pipeline.py`, `backend/app/api/mining.py`; tests exist. | Backlog B3: schedule runner + approval feedback into seed/blacklist + end-to-end acceptance run. |
| DCM-007 | P2 | Realtime risk, dynamic thresholds, trade-event consumer, and daily reconciliation have code/tests but lack fresh runtime first-fire evidence. | Beat/task files and tests exist; runtime proof is blocked by Servy/Beat activation evidence, not by repository wiring. | Backlog B4: capture process CreationDate, Beat schedule registration, `scheduler_task_log` first-fire rows, and risk/outbox side effects. |
| DCM-008 | P2 | Dynamic threshold audit table exists but operational path is Redis-only. | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` already annotates DB audit write as deferred; `dynamic_threshold_tasks.py` writes Redis cache. | Keep as explicit deferred audit feature unless a delta-flush task is prioritized. |
| DCM-009 | P2 | Governance tests still reference `.claude/hooks` while active hook layer is `.codex/hooks`. | `.codex/hooks.json`; `backend/tests/test_verify_completion_hook.py`; `backend/tests/test_redline_pretool_block_hook.py`. | Backlog B5: migrate tests to `.codex/hooks` or mark `.claude` as mirror-only in test names/docs. |
| DCM-010 | P2 | `.agents/skills` has governance docs but no automated inventory test. | `.agents/skills/README.md`; `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`. | Backlog B6: add a lightweight test that AGENTS/V3 map skill names resolve to `.agents/skills/*/SKILL.md`. |
| DCM-011 | P1 | Backend/migration allow automation level `L4`, but frontend `AutomationLevel` type and selector stopped at `L3`. | `backend/app/api/pipeline.py` defines `Literal["L0", "L1", "L2", "L3", "L4"]`; `backend/migrations/pipeline_settings.sql` CHECK allows `L4`; pre-fix `frontend/src/api/pipeline.ts` omitted `L4`. | Fixed in this batch: frontend type, PipelineConsole selector, and `pipeline-api.test.ts` now include L4. |

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
| GP closed loop is complete. | GP engine/orchestrator/script/API exist. | GP/mining tests exist. | PARTIAL_IMPLEMENT | B3. |
| BacktestRunner is the unified entry. | `backend/qm_platform/backtest/runner.py`, `scripts/run_backtest.py`. | `backend/tests/test_backtest_runner.py`. | PARTIAL_IMPLEMENT | B1 plus research script migration triage. |
| Strategy framework drives production signals. | Registry/S1/S2/bootstrap exist. | Strategy tests exist. | PARTIAL_IMPLEMENT | B2. |

### Risk / Scheduler / Governance

| Claim | Code evidence | Test evidence | Verdict | Next action |
|---|---|---|---|---|
| PMSRule current 14:30 Beat path is live. | Code marks the Beat retired; PMSRule file remains. | `backend/tests/test_risk_rules_pms.py`. | STALE_DOC_FIXED | This batch corrected AGENTS and V3 risk docs. |
| Pipeline automation-level L4 is selectable end-to-end. | Backend API/migration support L4; frontend type and selector now include L4. | `frontend/src/__tests__/pipeline-api.test.ts` includes L4 GET/PUT checks. | IMPLEMENTED_INTEGRATED | Keep CI build/test green. |
| L1 realtime risk has production wire. | `backend/app/tasks/beat_schedule.py`, `backend/app/tasks/celery_app.py`. | `test_realtime_risk_tasks.py`, `test_realtime_risk_engine.py`. | PARTIAL_RUNTIME_PROOF | B4. |
| Dynamic threshold cache is operational. | `backend/app/tasks/dynamic_threshold_tasks.py`, `backend/qm_platform/risk/dynamic_threshold/cache.py`. | `test_dynamic_threshold_tasks.py`. | PARTIAL_IMPLEMENT | Keep Redis-only SSOT unless audit flush is prioritized. |
| Codex hooks are active governance layer. | `.codex/hooks.json`, `.codex/hooks/*.py`. | Hook smoke from earlier PR batch; some tests still point to `.claude`. | PARTIAL_GOVERNED | B5. |
| Project skills are governed. | `.agents/skills/README.md`, `.agents/skills/*/SKILL.md`. | No inventory test. | PARTIAL_GOVERNED | B6. |

## Backlog

| Batch | Scope | Acceptance |
|---|---|---|
| B1 | Backtest execution closure | `POST /api/backtest/run` either starts a real Celery/Runner job and transitions status/result, or is renamed/documented as a non-executing submission placeholder with UI copy aligned. |
| B2 | Strategy signal production integration | A registry-driven signal loop runs selected live strategies with parity tests against the current PT path or an explicit ADR scopes production migration out. |
| B3 | GP closed-loop completion | Scheduled mining run, approval/rejection feedback into next generation seed/blacklist, and one end-to-end test or controlled run evidence. |
| B4 | Runtime first-fire proof | Servy/Beat process timestamp, schedule registration, `scheduler_task_log` first-fire rows, and domain side-effect proof for realtime risk / dynamic threshold / trade-event consumer / daily reconciliation. |
| B5 | Hook path drift cleanup | Tests and docs target `.codex/hooks` as active layer; `.claude/hooks` is either mirror-only or explicitly historical. |
| B6 | Skill inventory guard | Automated check that skill names referenced by AGENTS/V3 map resolve to `.agents/skills/*/SKILL.md`. |

## Verification

| Check | Result |
|---|---|
| Frontend build | PASS — `npm run build -- --mode development` |
| Frontend API unit | PASS — `npm exec vitest -- run src/__tests__/pipeline-api.test.ts` (11 passed) |
| Backend PN contract subset | PASS — `pytest backend/tests/test_pipeline_automation_level.py backend/tests/test_pipeline_pause.py backend/tests/test_pipeline_status_contract.py backend/tests/test_pipeline_logs.py backend/tests/test_factor_correlation_prune.py -q` (26 passed) |
| Static drift grep | PASS — stale PN problem statements are now marked design-time/historical; current API orphan truth is 0 in `docs/API_COVERAGE.md` header and §6.1/§10. |

## Non-Goals For This Batch

- No broker call, order placement, liquidation, or QMT state mutation.
- No `.env`, production YAML, or destructive DB mutation.
- No large strategy/backtest runtime rewrite inside a documentation/governance batch.
