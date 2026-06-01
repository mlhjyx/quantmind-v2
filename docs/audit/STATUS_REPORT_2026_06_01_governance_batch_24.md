# STATUS REPORT — 2026-06-01 Governance Batch 24

## Scope

Close stale API coverage documentation for `GET /api/factors/{name}`.

## Finding

`docs/API_COVERAGE.md` row 69 and §5D marked `/api/factors/{name}` as
backend-only. Fresh code review showed that `frontend/src/api/factors.ts`
already wraps the endpoint as `fetchFactorIcSeries()`, and
`frontend/src/pages/IcMonitoring.tsx` consumes it for the S1 IC time-series
chart.

This batch is therefore a documentation drift closure with an added contract
test, not a production behavior change.

## Changes

- Added `fetchFactorIcSeries()` endpoint mapping coverage to
  `frontend/src/__tests__/factors-api.test.ts`.
- Added a source guard proving `IcMonitoring.tsx` still consumes the wrapper.
- Updated `docs/API_COVERAGE.md` §3.6, row 69, §5D, historical O9, and new §25.
- Updated `memory/project_sprint_state.md` top handoff.

## Verification

- Contract:
  `npx vitest --run src/__tests__/factors-api.test.ts` -> 4 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 146 passed;
  `npm run build` -> exit 0 with existing Vite vendor-echarts chunk-size
  warning.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected;
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.

## Remaining Risk

- Commit, push, and GitHub checks are still pending for this batch.
- Non-backtest row-level API coverage still needs a dedicated refresh against
  the 170-route / 18-frontend-module aggregate surfaced in Batch 21.
