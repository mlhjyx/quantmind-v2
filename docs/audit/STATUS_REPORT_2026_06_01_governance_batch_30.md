# Governance Batch 30 Status — Dashboard coverage matrix reconciliation

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 36-43, Dashboard market ticker UI wiring, stale
matrix cleanup.

## Summary

Batch 30 reconciled the Dashboard rows in `docs/API_COVERAGE.md`. Rows 36-38
and 40-43 were already consumed by `frontend/src/api/dashboard.ts`; the matrix
was stale. Row 39 `/api/dashboard/market-ticker` was the only missing dashboard
consumer, so this batch added a typed wrapper and a compact read-only ticker
strip on the Dashboard page.

## Changes

- Added `MarketTickerItem` in `frontend/src/types/dashboard.ts`.
- Added `fetchMarketTicker()` in `frontend/src/api/dashboard.ts`.
- Wired `Dashboard/index.tsx` to load and render market ticker rows when the
  backend returns them.
- Added dashboard API contract coverage for the market ticker wrapper and page
  boundary.
- Updated `pages.test.tsx` dashboard mock so the full page suite matches the
  expanded API surface.
- Updated `docs/API_COVERAGE.md` rows 36-43 and added §31 evidence.

## Active Discovery

1. The dashboard matrix had stale negatives for seven already-wrapped rows.
2. The actual gap was row 39 only: backend route and service existed, frontend
   wrapper and page consumer did not.
3. The full frontend suite initially surfaced a total-mock drift in
   `pages.test.tsx`; adding the new mock export fixed the root cause and removed
   the unhandled rejection.

## Verification

- RED:
  `npx vitest --run src/__tests__/dashboard-api-contract.test.ts` failed before
  implementation on missing `fetchMarketTicker()` and Dashboard page refs.
- Targeted GREEN:
  `npx vitest --run src/__tests__/dashboard-api-contract.test.ts` -> 7 passed.
- TypeScript:
  `npx tsc -b --pretty false` -> exit 0.
- API discipline:
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Full frontend regression:
  `npx vitest --run` -> 33 files passed, 160 tests passed.
- Production build:
  `npm run build` -> exit 0 with the existing large `vendor-echarts` warning.
- Browser smoke:
  `http://127.0.0.1:5173/dashboard?smoke=batch30` rendered `驾驶舱`, showed
  ticker content including `沪深300`, and reported 0 console errors.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 scan clean, LLM import guard clean,
  smoke 91 passed, 2 skipped, 6976 deselected.

## Remaining Work

- No dashboard rows remain classified as backend-implemented/frontend-unwired in
  the API matrix.
- Row 34 remains in §5E until sensitivity architecture is designed.
- Rows 135-136 remain in §5E until strategy version mutation workflow semantics
  are designed.
- Row 62 remains in §5E until alert-config persistence and reload semantics are
  designed.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
