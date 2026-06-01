# Governance Batch 14 — Report Center API-Layer Closure

Date: 2026-06-01
Branch: `codex/runtime-governance-followup`

## Scope

Close the next code-backed frontend/API governance gap after Batch 13:
`ReportCenter.tsx` still consumed implemented report endpoints directly from
the page, while the API coverage matrix marked report endpoints unwired.

## Finding

`frontend/src/pages/ReportCenter.tsx` imported `apiClient` directly for:

- `/reports/list`
- `/reports/quick-stats`

`frontend/src/api/reports.ts` already wrapped `/reports/generate`,
`/reports/{strategy_id}/latest`, and `/reports/{strategy_id}/list`, but its
header comment explicitly kept the legacy report history endpoint inline.

Risk: real report-page usage was hidden from the `frontend/src/api/*.ts`
coverage methodology, and route params remained split across page code and API
wrappers.

Active discovery:
- `memory/project_sprint_state.md` / §Current Handoff still said Batch 13
  needed commit/push/CI, while fresh `git log` and PR #523 showed head
  `0e628bc0` clean with all GitHub checks passing. This report and the new
  top handoff correct that drift.

Evidence:
- `frontend/src/api/reports.ts:142-150` / §Report wrappers defines
  `listReportHistory` and `fetchReportQuickStats`; fresh verify 2026-06-01
  15:08 Asia/Shanghai.
- `frontend/src/pages/ReportCenter.tsx:64-70` / §ReportCenter queries now calls
  the two wrappers; fresh verify 2026-06-01 15:08 Asia/Shanghai.
- `docs/API_COVERAGE.md:611-613` / §Coverage rows 118–120 now maps all three
  base report endpoints to `reports.ts`; fresh verify 2026-06-01 15:08
  Asia/Shanghai.

## Fix

- Added `listReportHistory()` and `fetchReportQuickStats()` to
  `frontend/src/api/reports.ts`.
- Exported typed report history / quick-stats contracts from the API layer.
- Refactored `ReportCenter.tsx` off direct `apiClient` usage for the report
  history and quick-stats tabs.
- Added `frontend/src/__tests__/report-center-api-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` rows 118–120 and removed `/api/reports/*`
  from the backend-implemented/not-wired backlog.

## Verification

- RED: `npx vitest --run src/__tests__/report-center-api-contract.test.ts`
  failed before the fix because `listReportHistory` /
  `fetchReportQuickStats` were missing and `ReportCenter.tsx` imported
  `apiClient` directly.
- GREEN targeted: `npx vitest --run src/__tests__/report-center-api-contract.test.ts`
  -> 3 passed.
- Focused compatibility:
  `npx vitest --run src/__tests__/report-center-api-contract.test.ts src/__tests__/reports-api.test.ts src/__tests__/pages.test.tsx`
  -> 19 passed.
- Broader frontend/API pack:
  `npx vitest --run src/__tests__/report-center-api-contract.test.ts src/__tests__/reports-api.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 38 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 116 tests passed across 22 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/reports`;
  heading `报告中心` and tab text `报告列表` were visible; console errors were
  empty. Existing dev server on port 5173 was reused and not stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.
- Governance guards: V3 banned-word diff scan -> no new hits;
  `git diff --check` -> exit 0 with Git line-ending warnings only.

## Redline Check

No broker API calls, `.env` edits, production YAML edits, DB row mutations,
Servy configuration changes, Task Scheduler mutations, QMT service startup, or
backend production-code changes were performed.

## Backlog

Remaining direct page/component API imports after this batch:
`PTGraduation.tsx`, `RiskManagement.tsx`, `SafetyControlPanel.tsx`, and
`QMTStatusBadge.tsx`. Contract them only when current code shows response
conversion, coverage blindness, or a broken workflow.
