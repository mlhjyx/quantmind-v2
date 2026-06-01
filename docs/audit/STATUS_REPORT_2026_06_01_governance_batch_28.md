# Governance Batch 28 Status — Strategy edit route + metadata

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 134-136 and 140-141, strategy workspace edit-route behavior, strategy API request-shape drift.

## Summary

Batch 28 closed the read-only strategy metadata gap and fixed a route-level UI
break: `/strategy/:id` existed but the workspace did not load the selected
strategy. The batch also corrected the strategy create/update API wrappers so
the frontend sends the backend request shapes instead of the old editor model.

Rows 134 and 140 are now consumed. Rows 135-136 remain mutation workflow
backlog, and row 141 is classified as superseded by the existing backtest
configuration confirmation path.

## Changes

- Added typed `getStrategyDetail()`, `getStrategy()`, `getStrategyVersions()`,
  and `getStrategyFactors()` wrappers in `frontend/src/api/strategies.ts`.
- Added backend-shape normalization for strategy detail responses and adapted
  create/update wrappers to backend `market/config/factor_names` and
  `factor_config/backtest_config` request bodies.
- Added `strategyVersions()` and `strategyFactors()` query keys.
- Wired `StrategyWorkspace.tsx` to read the route id, fetch the selected
  strategy, display versions/factors metadata, and route backtests through
  `/backtest/config?strategy_id=...`.
- Added `frontend/src/__tests__/strategy-api-contract.test.ts`.
- Added a partial-update regression so name-only updates do not send empty
  config blocks to the backend.
- Updated `docs/API_COVERAGE.md` §3.10, rows 132-141, §5C, §5D, §5E, and new
  §29.

## Active Discovery

1. The backend strategy endpoints are not one class of gap. Versions GET and
   factors GET are read-only and useful in the edit workspace; version create
   and rollback are real mutations and need a diff/confirm/audit workflow.
2. The direct strategy backtest endpoint should stay out of the workspace
   because the current safer path is the config-confirmation page followed by
   `/api/backtest/run`.
3. The existing create/update wrappers were marked consumed but still sent the
   old UI payload. The batch fixed this request-shape drift rather than only
   adding the missing read-only wrappers.

## Verification

- RED:
  `npx vitest --run src/__tests__/strategy-api-contract.test.ts` failed before
  implementation on detail normalization, missing versions/factors wrappers,
  create/update request-shape adaptation, and workspace route-id wiring.
- Targeted GREEN:
  `npx vitest --run src/__tests__/strategy-api-contract.test.ts` -> 5 passed.
- TypeScript:
  `npx tsc -b --pretty false` -> exit 0.
- Backend route compatibility:
  `pytest backend/tests/test_api_routes.py::TestStrategiesAPI -q` -> 11
  passed.
- API discipline:
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Frontend regression:
  `npx vitest --run` -> 159 passed.
- Production build:
  `npm run build` -> exit 0, with the existing large `vendor-echarts` chunk
  warning.
- Browser smoke:
  `http://127.0.0.1:5173/strategy/28fc37e5-2d32-4ada-92e0-41c11a5103d0?smoke=batch28`
  rendered the saved strategy name, the versions/factors panel, and the run
  backtest button with 0 new console errors. Clicking run backtest navigated to
  `/backtest/config?strategy_id=28fc37e5-2d32-4ada-92e0-41c11a5103d0` with 0
  new console errors.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 scan clean, LLM import guard clean,
  smoke 91 passed, 2 skipped, 6976 deselected.

## Remaining Work

- Rows 135-136 need a small version-management design before implementation:
  version diff preview, required changelog, rollback confirmation, audit record
  display, post-mutation reload, and rollback refresh regression coverage.
- Row 141 should remain outside the strategy workspace unless a later product
  decision explicitly replaces the confirmation-page flow.
- Row 34 `/api/backtest/{run_id}/sensitivity` remains the only item in §5D.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
