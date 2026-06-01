# Governance Batch 11 — Dashboard API-Layer Closure

Date: 2026-06-01
Branch: `codex/runtime-governance-followup`

## Scope

Close a code-backed frontend/API governance gap found during the post-Batch-10
fresh read: Dashboard secondary panels were using page-level `apiClient` calls,
which made API coverage undercount real consumers and left response conversion
inside the page.

## Finding

`Dashboard/index.tsx` had direct page-level reads for alerts, monthly returns,
industry distribution, factor rows, and pipeline status. This contradicted the
project rule that frontend calls go through `src/api/`, and it made
`docs/API_COVERAGE.md` §3.4 stale because the matrix only greps
`frontend/src/api/*.ts`.

Evidence:
- `frontend/src/pages/Dashboard/index.tsx:9-13` imports the new wrappers after
  the fix; `:86`, `:103`, `:113`, `:137`, and `:154` call them.
- `frontend/src/api/dashboard.ts:43`, `:50`, `:57`, `:118`, and `:154` define
  the five wrappers.
- `frontend/src/__tests__/dashboard-api-contract.test.ts:13` defines the
  focused contract suite.

Fresh verify timestamp: 2026-06-01 14:21 Asia/Shanghai.

## Fix

- Added `fetchAlerts`, `fetchMonthlyReturns`, `fetchIndustryDistribution`,
  `fetchDashboardFactorRows`, and `fetchDashboardPipelineSteps`.
- Moved Dashboard display row types into `frontend/src/types/dashboard.ts`.
- Updated `MonthlyHeatmap` for backend null months.
- Removed direct `apiClient` usage from `Dashboard/index.tsx`.
- Updated the page render mock for the new wrapper exports.
- Updated `docs/API_COVERAGE.md` with §12 and marked §3.4 as historical.

## Verification

- RED: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts` failed
  before the fix on missing wrapper exports and the direct page import.
- GREEN targeted: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts`
  -> 6 passed.
- Broader frontend/API: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 20 passed.
- Full frontend: `npx vitest --run` -> 106 passed.
- Build: `npm run build` -> exit 0, existing vendor chunk warning only.
- API discipline: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: `http://127.0.0.1:5173/dashboard` rendered the Dashboard
  heading and reported no console errors.

## Redline Check

No broker API calls, `.env` edits, production YAML edits, DB row mutations,
Servy configuration changes, Task Scheduler mutations, or QMT service startup
were performed.

## Backlog

Other direct `apiClient` page/component imports remain outside this batch:
`DashboardAstock.tsx`, `PTGraduation.tsx`, `Portfolio.tsx`,
`RiskManagement.tsx`, `ReportCenter.tsx`, `MarketData.tsx`, and selected shared
widgets. They should be handled only when a code-backed page/API contract gap is
confirmed.
