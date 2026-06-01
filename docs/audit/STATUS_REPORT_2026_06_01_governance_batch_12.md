# Governance Batch 12 — Portfolio API-Layer Closure

Date: 2026-06-01
Branch: `codex/runtime-governance-followup`

## Scope

Close the next code-backed frontend/API governance gap after Batch 11:
portfolio endpoints were consumed directly from pages, and sector chart
consumers were relying on a page-level interpretation of backend response
fields.

## Finding

`Portfolio.tsx` and `DashboardAstock.tsx` imported `apiClient` directly for
`/portfolio/sector-distribution`, `/portfolio/daily-pnl`, and
`/portfolio/holdings`.

The backend portfolio route returns sector `pct` as percentage and `value` as
market value. The frontend charts used `value` as the chart percentage field,
so the direct page contract could display market value as a percent and kept
the `/api/portfolio/*` consumers invisible to the coverage matrix.

Evidence:
- `frontend/src/api/portfolio.ts:59` defines `fetchPortfolioSectorDistribution`
  and maps chart-facing `value` from backend `pct`.
- `frontend/src/api/portfolio.ts:78`, `:89`, and `:99` define daily PnL,
  holdings, and holding-days wrappers.
- `frontend/src/pages/Portfolio.tsx:79-81` now calls wrappers instead of
  `apiClient`.
- `frontend/src/pages/DashboardAstock.tsx:516` now calls
  `fetchPortfolioSectorDistribution()`.
- `frontend/src/__tests__/portfolio-api-contract.test.ts:16` defines the
  focused contract suite.

Fresh verify timestamp: 2026-06-01 14:38 Asia/Shanghai.

## Fix

- Added `frontend/src/api/portfolio.ts`.
- Normalized sector rows so chart `value` equals backend `pct`, while
  preserving backend market value as `marketValue`.
- Added deterministic sector colors for chart consumers.
- Refactored `Portfolio.tsx` and `DashboardAstock.tsx` off direct `apiClient`
  usage for the portfolio endpoints.
- Updated `docs/API_COVERAGE.md` with §13 and corrected the coverage rows for
  `/api/portfolio/*`.

## Verification

- RED: `npx vitest --run src/__tests__/portfolio-api-contract.test.ts` failed
  before the fix because `@/api/portfolio` did not exist.
- GREEN targeted: `npx vitest --run src/__tests__/portfolio-api-contract.test.ts`
  -> 4 passed.
- Broader frontend/API:
  `npx vitest --run src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 24 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend: `npx vitest --run` -> 110 passed.
- Build: `npm run build` -> exit 0 with the existing Vite vendor chunk-size
  warning only.
- API discipline: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: `http://127.0.0.1:5173/portfolio` and
  `http://127.0.0.1:5173/dashboard/astock` rendered their page headings with
  empty console error lists.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Redline Check

No broker API calls, `.env` edits, production YAML edits, DB row mutations,
Servy configuration changes, Task Scheduler mutations, or QMT service startup
were performed.

## Backlog

Remaining direct page/component API imports after this batch:
`PTGraduation.tsx`, `RiskManagement.tsx`, `ReportCenter.tsx`,
`MarketData.tsx`, `SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`.
They should be contracted only when current code shows response conversion,
coverage blindness, or a broken workflow.
