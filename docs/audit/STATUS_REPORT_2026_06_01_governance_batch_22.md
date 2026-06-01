# STATUS REPORT — 2026-06-01 Governance Batch 22

## Scope

BacktestResults deep-dive frontend closure after Batch 21 backend detail
endpoint hardening.

## Finding

`BacktestResults.tsx` still consumed only sparse
`/backtest/{run_id}/result` data. Rows 26-32 and 35 in `docs/API_COVERAGE.md`
were backend-implemented, but holdings, annual/monthly slices, attribution,
market-state, cost-sensitivity, report download, and live-compare had no
frontend API wrapper/page consumption.

During runtime verification, the existing Servy FastAPI listener on port 8000
also showed it had not loaded Batch 21 backend SQL fixes yet. A temporary
uvicorn process on port 8011 using current source returned successfully.

## Changes

- Added typed detail wrappers to `frontend/src/api/backtest.ts`:
  monthly returns, holdings summary/detail/latest holdings, trades-for-result,
  annual risk metrics, Brinson attribution, cost sensitivity, market-state,
  live-compare, and report URL helper.
- Updated `frontend/src/pages/BacktestResults.tsx` to merge detail data into
  the existing result view and add industry attribution, cost sensitivity,
  market-state, and live-compare tabs.
- Added `frontend/src/__tests__/backtest-results-detail-contract.test.ts`.
- Added `frontend/src/__tests__/backtest-results-page-render.test.tsx`.
- Updated `docs/API_COVERAGE.md` rows 26-32 and 35 to consumed and moved row
  34 sensitivity into the remaining backtest backlog.

## Verification

- RED:
  `npx vitest --run src/__tests__/backtest-results-detail-contract.test.ts`
  failed before implementation because wrappers/page wiring were absent.
- Targeted:
  `npx vitest --run src/__tests__/backtest-results-detail-contract.test.ts src/__tests__/backtest-compare-trade-contract.test.ts`
  -> 9 passed.
- Render:
  `npx vitest --run src/__tests__/backtest-results-page-render.test.tsx src/__tests__/backtest-results-detail-contract.test.ts`
  -> 7 passed.
- Type/build/frontend:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 142 passed;
  `npm run build` -> exit 0 with existing Vite vendor-echarts chunk warning.
- Backend compatibility:
  `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q` -> 7
  passed.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected; `bash config/hooks/pre-push` -> X10 clean, LLM import guard
  clean, smoke 91 passed, 2 skipped, 6976 deselected.
- Runtime current-source probe:
  temporary uvicorn on `127.0.0.1:8011` returned monthly=4,
  holdings_summary=0, holdings_detail=0, annual=1,
  attribution_industries=0, market_states=0, cost_rows=4, and
  live_compare_has_backtest=true for run
  `2c91bd92-ee0f-4f52-9244-795365cc1037`; the process was stopped.

## Remaining Risk

- Port 8000 FastAPI is running an older loaded code version until Servy
  FastAPI is reloaded. This batch intentionally did not mutate Servy runtime.
- Row 34 `/api/backtest/{run_id}/sensitivity` remains deferred/backlog.
- Non-backtest row-level API coverage still needs a dedicated refresh against
  the 170-route / 18-frontend-module aggregate surfaced in Batch 21.
