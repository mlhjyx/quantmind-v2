---
description: Codex remediation handoff updated after 2026-06-01 governance batch 16.
date: 2026-06-01 +08:00
status: governance_batch_16_safety_control_api_layer_verified
source_report: docs/audit/STATUS_REPORT_2026_06_01_governance_batch_16.md
---

# Project Sprint State

## Current Handoff - 2026-06-01 Batch 16

Mode: full-project closure/governance remediation, batch 16 SafetyControlPanel L4 API-layer closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Latest pushed head before this batch is `4057c34a` (`close risk management api layer contract`), and PR #523 was fresh-verified CLEAN with all GitHub checks passing before Batch 16 edits.
- This handoff records the Batch 16 local verification set. For post-push state, fresh-read git and PR #523 rather than inferring from this file.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Active discovery:
- SessionStart hook reported "未找到当前 handoff", but this file has a `Current Handoff` section. Treat hook detection as stale/fragile, not as source of truth.
- Previous Batch 15 handoff still said commit/push/CI were open, but fresh git + PR state showed Batch 15 was already pushed and CI-clean at `4057c34a`. Use git/PR state for branch truth after every push.
- `SafetyControlPanel.tsx` directly posted L4 recovery/approve mutations even though the rest of the risk surface had moved behind `frontend/src/api/risk.ts`; `docs/API_COVERAGE.md` rows 124-125 were still red.

Closed in this batch:
- Audited `SafetyControlPanel.tsx`, backend `risk.py`, `frontend/src/api/risk.ts`, existing safety panel tests, and `docs/API_COVERAGE.md`.
- Added `requestL4Recovery()` and `approveL4Recovery()` wrappers plus typed L4 responses to `frontend/src/api/risk.ts`.
- Removed direct `apiClient` import and direct L4 mutation calls from `SafetyControlPanel.tsx`.
- Extended `frontend/src/__tests__/risk-management-api-contract.test.ts` with L4 wrapper endpoint assertions and a SafetyControlPanel boundary guard.
- Updated `frontend/src/__tests__/SafetyControlPanel.test.tsx` mocks so existing L4 UI flow tests still exercise wrapper-shaped calls.
- Updated `docs/API_COVERAGE.md` §17 and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_16.md`.

Verification:
- RED: `npx vitest --run src/__tests__/risk-management-api-contract.test.ts` failed before the fix because the L4 wrappers were missing and `SafetyControlPanel.tsx` imported `apiClient` directly.
- GREEN targeted risk-management/safety contract -> 17 passed.
- Focused frontend/API pack -> 47 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest --run` -> 126 tests passed across 23 files.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Browser smoke opened `http://127.0.0.1:5173/risk`, clicked `紧急控制`, and found `熔断状态`, `紧急操作`, and `ENV: paper`; console errors were empty. Existing dev server on port 5173 was reused and not stopped.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013 deselected.

Still open:
- After this batch is pushed, fresh-read PR #523 checks and merge state before continuing.
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Remaining direct `apiClient` page/component imports: `PTGraduation.tsx` and `QMTStatusBadge.tsx`; contract only when current code proves a response conversion, coverage, or workflow gap.

Next safe step:
- If these Batch 16 edits are not yet on PR #523, stage/commit/push them and wait for GitHub checks. If they are already pushed and checks are clean, continue with the next evidence-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 14

Mode: full-project closure/governance remediation, batch 14 Report Center API-layer closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Latest pushed head before this batch is `0e628bc0` (`close market api layer contract`), and PR #523 was fresh-verified CLEAN with all GitHub checks passing before Batch 14 edits.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Active discovery:
- SessionStart hook reported "未找到当前 handoff", but this file has a `Current Handoff` section. Treat hook detection as stale/fragile, not as source of truth.
- Previous Batch 13 handoff still said commit/push/CI were open, but fresh git + PR state showed Batch 13 was already pushed and CI-clean at `0e628bc0`. This Batch 14 handoff corrects the top-level current state.

Closed in this batch:
- Audited `ReportCenter.tsx`, backend `report.py`, `frontend/src/api/reports.ts`, and `docs/API_COVERAGE.md`.
- Confirmed `/api/reports/list` and `/api/reports/quick-stats` were implemented and consumed by the report page, but the page bypassed `frontend/src/api/*.ts` and the matrix still marked report rows 118-120 as unwired.
- Added `listReportHistory` and `fetchReportQuickStats` wrappers to `frontend/src/api/reports.ts`.
- Removed direct `apiClient` import and usage from `ReportCenter.tsx` for report history and quick-stats endpoints.
- Added `frontend/src/__tests__/report-center-api-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` §15 and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_14.md`.

Verification:
- RED: `npx vitest --run src/__tests__/report-center-api-contract.test.ts` failed before the fix because wrappers were missing and `ReportCenter.tsx` imported `apiClient` directly.
- GREEN targeted report-center contract -> 3 passed.
- Focused compatibility suite -> 19 passed.
- Broader frontend/API pack -> 38 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest --run` -> 116 tests passed across 22 files.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Browser smoke opened `http://127.0.0.1:5173/reports`; the `报告中心` heading and `报告列表` tab text were visible and console errors were empty. Existing dev server on port 5173 was reused and not stopped.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013 deselected.
- V3 banned-word diff scan -> no new hits; `git diff --check` -> exit 0 with Git line-ending warnings only.

Still open:
- Commit/push Batch 14 into PR #523, update PR body, and wait for CI.
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Remaining direct `apiClient` page/component imports: `PTGraduation.tsx`, `RiskManagement.tsx`, `SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`; contract only when current code proves a response conversion, coverage, or workflow gap.

Next safe step:
- Commit/push Batch 14, update PR #523 body, and wait for GitHub checks.

---

## Previous Handoff - 2026-06-01 Batch 13

Mode: full-project closure/governance remediation, batch 13 Market API-layer closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited `MarketData.tsx` against backend `market.py` and `docs/API_COVERAGE.md`.
- Confirmed `/api/market/indices`, `/api/market/sectors`, and `/api/market/top-movers` were implemented and consumed by the market page, but the page bypassed `frontend/src/api/*.ts` and the matrix still marked rows 75-77 as unconsumed.
- Added `frontend/src/api/market.ts` wrappers: `fetchMarketIndices`, `fetchMarketSectors`, and `fetchMarketTopMovers`.
- Removed direct `apiClient` import and usage from `MarketData.tsx` for market endpoints.
- Added `frontend/src/__tests__/market-api-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` §14 and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_13.md`.

Verified so far:
- RED: `npx vitest --run src/__tests__/market-api-contract.test.ts` failed before the fix because `src/api/market.ts` did not exist and `MarketData.tsx` imported `apiClient` directly.
- GREEN targeted market contract -> 3 passed.
- Broader frontend/API suite -> 27 passed.
- `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite -> 113 passed.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Browser smoke opened `/market`; heading `行情数据` and tab `行情概览` were visible and console errors were empty. Temporary Vite dev server was stopped after verification.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013 deselected.

Still open:
- Commit/push Batch 13 into PR #523 and wait for CI.
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Remaining direct `apiClient` page/component imports: `PTGraduation.tsx`, `RiskManagement.tsx`, `ReportCenter.tsx`, `SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`; contract only when current code proves a response conversion, coverage, or workflow gap.

Next safe step:
- Run final diff/check hygiene, commit/push Batch 13 into PR #523, wait for CI, then continue with the next evidence-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 12

Mode: full-project closure/governance remediation, batch 12 Portfolio API-layer closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited Portfolio and A-share dashboard frontend/API contracts from code: `Portfolio.tsx` and `DashboardAstock.tsx` used page-level `apiClient` calls for `/portfolio/sector-distribution`, `/portfolio/daily-pnl`, and `/portfolio/holdings`.
- Confirmed the backend portfolio route returns sector `pct` as percentage and `value` as market value, while chart consumers treated `value` as the percentage field.
- Added `frontend/src/api/portfolio.ts` wrappers: `fetchPortfolioSectorDistribution`, `fetchPortfolioDailyPnl`, `fetchPortfolioHoldings`, and `fetchHoldingDaysMap`.
- Normalized sector rows so chart-facing `value` equals backend `pct`, while preserving backend market value as `marketValue` and adding deterministic colors.
- Removed direct `apiClient` import and usage from `Portfolio.tsx` and `DashboardAstock.tsx` for portfolio endpoints.
- Added `frontend/src/__tests__/portfolio-api-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` §13 and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_12.md`.

Verified so far:
- RED: `npx vitest --run src/__tests__/portfolio-api-contract.test.ts` failed before the fix because `@/api/portfolio` did not exist.
- GREEN targeted portfolio contract -> 4 passed.
- Broader frontend/API suite -> 24 passed.
- `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite -> 110 passed.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Browser smoke opened `/portfolio` and `/dashboard/astock`; headings were visible and console errors were empty.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013 deselected.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Remaining direct `apiClient` page/component imports: `PTGraduation.tsx`, `RiskManagement.tsx`, `ReportCenter.tsx`, `MarketData.tsx`, `SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`; contract only when current code proves a response conversion, coverage, or workflow gap.

Next safe step:
- Run full frontend/build/API-discipline/backend-smoke verification, commit/push Batch 12 into PR #523, wait for CI, then continue with the next evidence-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 11

Mode: full-project closure/governance remediation, batch 11 Dashboard API-layer closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited Dashboard frontend/API contract from code: `Dashboard/index.tsx` used page-level `apiClient` calls for alerts, monthly returns, industry distribution, factor rows, and pipeline status.
- Confirmed this made `docs/API_COVERAGE.md` §3.4 stale because its methodology counts `frontend/src/api/*.ts`, while these consumers lived in the page.
- Added typed wrappers in `frontend/src/api/dashboard.ts`: `fetchAlerts`, `fetchMonthlyReturns`, `fetchIndustryDistribution`, `fetchDashboardFactorRows`, and `fetchDashboardPipelineSteps`.
- Centralized Dashboard display types in `frontend/src/types/dashboard.ts`; `MonthlyHeatmap` now accepts backend null months via `MonthlyReturns`.
- Removed direct `apiClient` import and usage from `Dashboard/index.tsx`.
- Added `frontend/src/__tests__/dashboard-api-contract.test.ts` to lock wrapper exports, endpoint params, response normalization, and the page boundary.
- Updated `docs/API_COVERAGE.md` §12 and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_11.md`.

Verified so far:
- RED: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts` failed before the fix on missing wrapper exports and the direct Dashboard page `apiClient` import.
- GREEN targeted Dashboard contract -> 6 passed.
- Broader frontend/API suite -> 20 passed.
- Full frontend suite -> 106 passed.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- In-app browser smoke opened `http://127.0.0.1:5173/dashboard`; the `驾驶舱` heading was visible and console errors were empty.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Other direct `apiClient` page/component imports remain candidates for follow-up only when a code-backed contract gap is confirmed.

Next safe step:
- Run final diff/check hygiene, commit/push Batch 11 into PR #523, wait for CI, then continue with the next evidence-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 10

Mode: full-project closure/governance remediation, batch 10 blocking CI regression parity verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited GitHub CI from code and workflow: `regression` and `ci_matrix` still used `scripts/ci_run_phase.py --advisory`, so workflow failures could be masked as advisory output.
- Reproduced the underlying regression issue: default regression pairs pointed at nonexistent `cache/baseline/backtest_*_{baseline,actual}.json` files, while committed artifacts are `cache/baseline/regression_result_5yr.json` and `cache/baseline/regression_result_12yr.json`.
- Updated `RegressionOrchestrator.default_pairs()` to use the committed regression result artifacts.
- Added recorded `max_diff` validation for same-file committed artifacts while preserving baseline-vs-actual pair comparison for custom callers.
- Removed advisory masking from GitHub `regression` and `ci_matrix` jobs.
- Added `backend/tests/test_github_ci_workflow.py` and included it in bounded pre-commit collect coverage.
- Followed the first GitHub blocking failure: `ci_matrix` failed while `regression`, `pre_commit`, and `pre_push` passed, exposing that matrix smoke used a bare pytest command and hid the pytest tail.
- Aligned `CIMatrixOrchestrator` smoke execution with the passing pre-push smoke scope and added bounded stdout-tail detail for failed matrix cells.
- Followed the second GitHub blocking failure: the tail showed selected smoke tests ended with `3 errors` on GitHub-hosted runners, which matches the workflow's documented no-local-runtime constraint.
- Added `QM_CI_SMOKE_COLLECT_ONLY=1` support to `CIMatrixOrchestrator` and set the hosted `ci_matrix` job to the same blocking collect/wiring contract as pre-push; local matrix still runs full smoke when the env var is absent.
- Updated `docs/mvp/MVP_4_3_cicd.md` and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_10.md`.

Verified so far:
- RED: focused regression/workflow tests failed before the fix on nonexistent default paths, same-artifact nonzero `max_diff` passing, default regression failing, and workflow `--advisory` usage.
- GREEN focused contract tests -> 4 passed.
- CI regression/test pack -> 54 passed.
- `python scripts/ci_run_phase.py --phase regression` -> PASS, both default artifacts reported `max_diff=0.0`.
- `python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.
- `python scripts/ci_run_phase.py --phase pre_commit` -> PASS.
- GitHub first blocking run: `regression`, `pre_commit`, and `pre_push` passed; `ci_matrix` failed and was fixed in the follow-up commit.
- Matrix command/tail RED tests failed before the follow-up fix; full matrix orchestrator tests -> 18 passed after the fix.
- `ruff check backend/qm_platform/ci/ci_matrix.py backend/tests/test_qm_platform_ci_matrix.py` -> PASS.
- Follow-up `python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.
- Hosted collect-only RED test failed before env support; full matrix orchestrator tests -> 19 passed after the fix.
- Hosted collect-only `python scripts/ci_run_phase.py --phase ci_matrix` with `QM_CI_SMOKE_COLLECT_ONLY=1` -> PASS.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Notification detail, cleanup, and preferences endpoints remain backend/admin-only unless they become explicit operator workflows.

Next safe step:
- Run final smoke/diff checks, commit/push Batch 10 into PR #523, wait for CI, then continue with the next code-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 9

Mode: full-project closure/governance remediation, batch 9 notification panel API closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited the notification UI/backend contract from code: backend `/api/notifications` routes existed, but `NotificationProvider` seeded local mock notifications and never called the backend.
- Added `frontend/src/api/notifications.ts` wrappers for list, per-row read, and read-all endpoints with response normalization.
- Refactored `NotificationProvider` to load backend rows, expose loading/error state, keep toast behavior, update unread counts, and avoid backend calls for already-read rows.
- Updated `NotificationPanel` loading/empty/error/data states.
- Removed the nested provider/toast mount from `Layout.tsx`; `main.tsx` remains the single app-level notification provider.
- Updated `docs/API_COVERAGE.md` and added `docs/audit/STATUS_REPORT_2026_06_01_governance_batch_9.md`.

Verified so far:
- RED: `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx` failed before the fix on missing API module, zero backend fetch calls, seeded mock rows, missing backend states, and missing backend mark-all call.
- RED edge: `npx vitest --run src/__tests__/notifications-ui-contract.test.tsx -t "already-read"` failed before the guard because read rows still called the mark-read endpoint.
- GREEN targeted notification contracts -> 10 passed.
- `npx vitest --run` -> 100 passed.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7005 deselected.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.
- Notification detail, cleanup, and preferences endpoints remain backend/admin-only unless they become explicit operator workflows.

Next safe step:
- Run final diff/check hygiene, commit/push Batch 9 into PR #523, wait for CI, then continue with the next code-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 8

Mode: full-project closure/governance remediation, batch 8 LLM fallback audit category durability verified locally before final smoke/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited the LLM fallback audit path from code: `LiteLLMRouter` detected fallback, but `LLMResponse` did not expose a sanitized primary-provider failure category.
- Confirmed `BudgetAwareRouter._audit_log()` persisted only the broad `primary_fail_fallback_engaged` label for non-capped fallback success rows.
- Added `LLMResponse.fallback_error_class` with fixed category-only values.
- Added LiteLLM metadata extraction from `previous_models` containers without persisting raw provider error strings.
- Updated audit row construction to write the sanitized category for primary-fail fallback rows while keeping `budget_capped` and `budget_capped_routing_anomaly` behavior unchanged.
- Added router/audit regression tests for authentication fallback metadata and no raw key-fragment persistence.

Verified so far:
- RED: `pytest backend/tests/test_litellm_router_core.py::test_fallback_response_records_sanitized_provider_error_class backend/tests/test_litellm_audit.py::test_aware_router_audit_persists_sanitized_primary_error_category -q` failed before the fix on missing `fallback_error_class` and broad audit labeling.
- GREEN targeted tests -> 2 passed.
- `pytest backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py -q` -> 52 passed.
- `pytest backend/tests/test_litellm_budget.py backend/tests/test_meta_monitor_service.py -q` -> 61 passed.
- `pytest backend/tests/test_market_regime_service.py backend/tests/test_news_classifier_service.py backend/tests/test_news_classifier_rag_wire.py backend/tests/test_rag_consumer_smoke.py backend/tests/test_regime_rag_wire.py -q` -> 97 passed, 2 skipped.
- `ruff check backend/qm_platform/llm backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py` -> pass.
- `ruff format --check backend/qm_platform/llm backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py` -> pass.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Run final smoke/diff checks, commit/push Batch 8 into PR #523, wait for CI, then continue with the next code-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 7

Mode: full-project closure/governance remediation, batch 7 mining candidate normalization and Gate payload closure verified locally before final commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited current backend mining task-detail output: candidates arrive as `factor_name` / `factor_expr` / `status` / `gate_report`, while the frontend table and Gate submit path expect normalized `CandidateFactor` fields.
- Added normalization in `frontend/src/api/mining.ts` for task summaries and task details, including task counters/progress and candidate metrics/status fields.
- Added shared `buildCandidateGatePayloads()` fail-loud helper to resolve selected IDs to factor expressions and names.
- Updated `FactorLab` to use the shared helper.
- Updated `MiningTaskCenter` detail modal to submit selected IDs together with loaded detail candidates, then send expression-based Gate payloads.
- Added `frontend/src/__tests__/mining-api-contract.test.ts`.

Verified so far:
- RED: `npx vitest run src/__tests__/mining-api-contract.test.ts` failed before the fix on missing normalized fields, missing helper, and missing fail-loud expression guard.
- GREEN: `npx vitest run src/__tests__/mining-api-contract.test.ts` -> 3 passed.
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx src/__tests__/mining-api-contract.test.ts` -> 5 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__` -> 90 passed.
- `npm run build` -> exit 0 with the existing Vite large chunk warning only.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Run final diff checks, commit/push Batch 7 into PR #523, wait for CI, then continue with the next code-backed governance slice.

---

## Previous Handoff - 2026-06-01 Batch 6

Mode: full-project closure/governance remediation, batch 6 mining transport fix verified locally before final smoke/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited the mining transport contract from current code: backend mining exposes REST polling via `/api/mining/tasks` and `/api/mining/tasks/{task_id}`; no backend `/ws/factor-mine/{id}` Socket.IO namespace or native route exists.
- Removed unsupported mining Socket.IO usage from `frontend/src/pages/FactorLab.tsx`.
- Added active-task polling in `FactorLab` while the task is running or paused.
- Removed unsupported mining Socket.IO usage from `frontend/src/pages/MiningTaskCenter.tsx`; its existing task-list polling remains the update source.
- Deleted unused `frontend/src/hooks/useWebSocket.ts` after confirming it had no production callers.
- Added `frontend/src/__tests__/mining-websocket-contract.test.tsx`.

Verified so far:
- RED: `npx vitest run src/__tests__/mining-websocket-contract.test.tsx` failed before the fix on `/ws/factor-mine/task-running-1` calls from both mining pages.
- GREEN: `npx vitest run src/__tests__/mining-websocket-contract.test.tsx` -> 2 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx src/__tests__/websocket-contract.test.tsx src/__tests__/pages.test.tsx src/__tests__/api.test.ts` -> 18 passed.
- `npm run build` -> exit 0 with the existing Vite large chunk warning only.
- `rg -n "/ws/factor-mine|factor-mine|useWebSocket" frontend\src backend\app backend\tests -S` -> only the new regression test references `/ws/factor-mine`; no production caller of `useWebSocket` remains.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.
- `git diff --check` -> exit 0 with CRLF normalization warnings only.
- Banned-word sediment scan on the Batch 6 report and this new handoff section -> no hits.

Still open:
- Mining frontend/API backlog: backend task-detail candidates use `factor_name` / `factor_expr`, while the frontend table expects `name` / `expression`; normalize this before rendering and Gate submission.
- Mining frontend/API backlog: `MiningTaskCenter` batch Gate submit still maps selected IDs into `factor_expr`; fetch detail and submit actual candidate DSL expressions instead.
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Run final diff/smoke verification, commit/push Batch 6 into PR #523, wait for CI, then continue with the mining candidate normalization and selected-ID Gate payload closure.

---

## Previous Handoff - 2026-06-01 Batch 5

Mode: full-project closure/governance remediation, batch 5 frontend contract fix verified locally before commit/CI.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited the backend WebSocket contract from code: Socket.IO is mounted at `/ws/socket.io`, with backtest room events `join_backtest` and `leave_backtest`.
- Fixed `frontend/src/hooks/useBacktestProgress.ts` to connect through the backend Socket.IO path, use runtime/configurable origin, allow websocket plus polling transports, and emit the backend event names.
- Removed the unsupported native `/ws/pipeline/{run_id}` connection from `frontend/src/pages/PipelineConsole.tsx`; the page keeps its existing polling path until a real backend live stream exists.
- Added `frontend/src/__tests__/websocket-contract.test.tsx` to guard the contract.

Verified so far:
- RED: `npx vitest run src/__tests__/websocket-contract.test.tsx` failed before the fix on `/ws/backtest` and `/ws/pipeline/...`.
- GREEN: `npx vitest run src/__tests__/websocket-contract.test.tsx` -> 2 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__/websocket-contract.test.tsx src/__tests__/PipelineConsole.test.tsx src/__tests__/backtest-api.test.ts src/__tests__/pages.test.tsx` -> 18 passed.
- `npm run build` -> exit 0 with the existing Vite large chunk warning only.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.
- `git diff --check` -> exit 0 with CRLF normalization warnings only.

Still open:
- Frontend/backend backlog: `FactorLab` and `MiningTaskCenter` still reference `/ws/factor-mine/{id}` through `useWebSocket`; backend support was not found in this batch.
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Run final diff/smoke verification, commit/push Batch 5 into PR #523, wait for CI, then continue with the remaining `/ws/factor-mine/{id}` contract audit or the elevated ops reload handoff.

---

## Previous Handoff - 2026-06-01 Batch 4

Mode: full-project closure/governance remediation, batch 4 completed code/docs guardrails; runtime reload remains ops-blocked.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Attempted scoped Celery/Beat reload for Batch 3 runtime verification; Servy restart and direct Windows service stop are blocked by current process permissions.
- Confirmed running Celery still uses pre-Batch-3 code: `realtime_risk_tick` rows at `2026-06-01 12:14-12:16 +08` still report `success` with zero positions/nav and no `qmt_cache_unavailable` reason.
- Hardened `scripts/service_manager.ps1`: documented aliases work, `all` no longer implicitly manages QMTData, Servy failure output is printed, and failed service actions exit nonzero.
- Added static regression tests for service-manager behavior.
- Fixed duplicate YAML delimiter at the top of this handoff file.
- Updated `AGENTS.md` service-manager quick reference to document core-services-only `all` plus explicit QMTData management.

Verified:
- `pytest backend/tests/test_service_manager_script.py -q`: 4 passed.
- `pytest -m "smoke and not live_tushare" -q`: 90 passed, 2 skipped, 7003 deselected.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\service_manager.ps1 status`: exit 0, core services running, QMTData stopped/manual.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\service_manager.ps1 restart celery`: exit 1 and surfaces `Failed to restart service.`

Still open:
- Ops deployment: an elevated/admin shell must reload `worker`, `slow-worker`, and `beat`; then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'`.
- QMTData runtime remains intentionally stopped/manual; do not start it implicitly.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Commit/push Batch 4 into PR #523, wait for CI, then continue with either elevated ops handoff verification or another code-only governance closure batch.

---

## Previous Handoff — 2026-06-01 Batch 3

Mode: full-project closure/governance remediation, batch 3 verified locally.

Current scope:
- Current PR branch is `codex/runtime-governance-followup`.
- Continue avoiding broker order APIs, `.env` edits, production YAML edits, destructive DB changes, Servy config edits, Task Scheduler mutations, and QMT service startup unless a separate ops step is explicitly chosen.
- Do not commit, stage, unstage, or revert unrelated user-owned changes.

Closed in this batch:
- Audited the L1 realtime risk and QMT cache input chain from code plus read-only service, Redis, and DB evidence.
- Fixed realtime risk context ambiguity: empty positions without `portfolio:nav` now raises `PositionSourceError(reason="qmt_cache_unavailable")` instead of returning a clean empty context.
- Preserved the source error reason in `realtime_risk_tick` audit output so missing QMT cache is visible in `scheduler_task_log.result_json`.
- Wired the existing `QMTFallbackTriggeredRule` into `build_intraday_risk_engine()` with a new read-only `RedisPortfolioCacheHealthReader`.
- Chose `portfolio:*` key counting so a clean empty account with fresh `portfolio:nav` does not false-fire the cache fallback guard.

Runtime evidence:
- `QuantMind-QMTData` was stopped/manual; no service restart was performed.
- Redis `EXISTS portfolio:nav portfolio:current risk:l1_heartbeat qmt:connection_status` returned `0`.
- DB read-only query showed 120 recent `realtime_risk_tick` rows in 2 hours, latest at `2026-06-01 11:56:00+08`, with zero positions/evaluations/triggers.
- `trade_event_risk_consumer` rows were current and successful but consumed/processed 0 events.

Verified:
- `ruff format` on touched Python files.
- `ruff check` on touched Python files: PASS.
- `pytest backend/tests/test_realtime_context_builder.py backend/tests/test_realtime_risk_tasks.py backend/tests/test_risk_wiring.py backend/tests/test_qmt_fallback_rule.py -q`: 56 passed.
- `pytest backend/tests/test_daily_pipeline_multi_strategy.py backend/tests/test_risk_rules_intraday.py -q`: 41 passed.
- `pytest -m "smoke and not live_tushare" -q`: 90 passed, 2 skipped, 6999 deselected.

Still open:
- Ops deployment: FastAPI/Celery/Celery Beat reload is needed before runtime rows reflect the new `qmt_cache_unavailable` path.
- QMTData runtime: `QuantMind-QMTData` remains stopped/manual; restart was intentionally not performed in this code batch.
- Direct miniQMT read-only account probe failed at broker connect return code `-1`; cash/position direct account verification is still blocked by local QMT availability.
- Batch 2 backlog remains: DeepSeek primary provider credential/account failure requires operator secret/provider fix; no secret rotation was performed.

Next safe step:
- Push this batch to PR #523, then continue with either the ops-readiness plan for deploying/rechecking the QMT cache guards or another code-only governance closure batch. Keep service restarts and account-probe remediation as explicit ops work.

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
