# Governance Batch 13 — Market API-Layer Closure

Date: 2026-06-01
Branch: `codex/runtime-governance-followup`

## Scope

Close the next code-backed frontend/API governance gap after Batch 12:
`MarketData.tsx` consumed implemented market endpoints directly from the page,
while the API coverage matrix still marked `/api/market/*` as unconsumed.

## Finding

`frontend/src/pages/MarketData.tsx` imported `apiClient` directly for:

- `/market/indices`
- `/market/sectors`
- `/market/top-movers?direction=up&limit=5`
- `/market/top-movers?direction=down&limit=5`

Risk: this hid real market-page usage from the `frontend/src/api/*.ts`
coverage methodology and spread the top-mover query contract across UI code.

Evidence:
- `frontend/src/pages/MarketData.tsx:61` / §MarketData queries now uses
  `fetchMarketIndices`; fresh verify 2026-06-01 14:51 Asia/Shanghai.
- `frontend/src/pages/MarketData.tsx:67` / §MarketData queries now uses
  `fetchMarketSectors`; fresh verify 2026-06-01 14:51 Asia/Shanghai.
- `frontend/src/pages/MarketData.tsx:73` and `:79` / §MarketData queries now
  call `fetchMarketTopMovers`; fresh verify 2026-06-01 14:51 Asia/Shanghai.
- `frontend/src/api/market.ts:33-47` / §Market wrappers defines the three typed
  `/market/*` API functions; fresh verify 2026-06-01 14:51 Asia/Shanghai.
- `docs/API_COVERAGE.md:1040` / §14 records this closure and updates rows
  75–77; fresh verify 2026-06-01 14:51 Asia/Shanghai.

## Fix

- Added `frontend/src/api/market.ts` with typed wrappers:
  `fetchMarketIndices`, `fetchMarketSectors`, and `fetchMarketTopMovers`.
- Refactored `MarketData.tsx` off direct `apiClient` usage for market data.
- Added `frontend/src/__tests__/market-api-contract.test.ts` to lock wrapper
  endpoints, top-mover params, and the page boundary.
- Updated `docs/API_COVERAGE.md` rows 75–77 and removed `/api/market/*` from
  the backend-implemented/not-wired backlog.

## Verification

- RED: `npx vitest --run src/__tests__/market-api-contract.test.ts` failed
  before the fix because `src/api/market.ts` did not exist and `MarketData.tsx`
  imported `apiClient` directly.
- GREEN targeted: `npx vitest --run src/__tests__/market-api-contract.test.ts`
  -> 3 passed.
- Broader frontend/API:
  `npx vitest --run src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 27 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend: `npx vitest --run` -> 113 passed.
- Build: `npm run build` -> exit 0 with the existing Vite vendor chunk-size
  warning only.
- API discipline: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: `http://127.0.0.1:5173/market` rendered heading `行情数据`
  and tab `行情概览`; console error list was empty. Temporary Vite dev server
  was stopped after the smoke.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Redline Check

No broker API calls, `.env` edits, production YAML edits, DB row mutations,
Servy configuration changes, Task Scheduler mutations, QMT service startup, or
backend production-code changes were performed.

## Backlog

Remaining direct page/component API imports after this batch:
`PTGraduation.tsx`, `RiskManagement.tsx`, `ReportCenter.tsx`,
`SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`. Contract them only when
current code shows response conversion, coverage blindness, or a broken
workflow.
