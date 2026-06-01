# Governance Batch 20 Status Report — BacktestCompare S5 Trade Diff Closure

Date: 2026-06-01 16:31 +08
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 20 closed a design-vs-implementation gap in Wave 5 MVP 5.3:

- `frontend/src/api/backtest.ts`
- `frontend/src/pages/BacktestCompare.tsx`
- `frontend/src/__tests__/backtest-compare-trade-contract.test.ts`
- `docs/API_COVERAGE.md`
- `docs/mvp/MVP_5_3_backtest_compare.md`
- `memory/project_sprint_state.md`

No broker APIs, `.env`, production YAML, database rows, Servy config, Task
Scheduler config, or QMT runtime state were changed. The new UI uses read-only
backtest endpoints.

## Finding

MVP 5.3 and the page header promised lazy trade diff via
`GET /api/backtest/{run_id}/trades`, but `BacktestCompare.tsx` only rendered
S1-S4: run selector, metric table, reproducibility seal, NAV overlay, and
drawdown overlay. The coverage matrix also still marked `/nav` and `/trades`
as unwired, although `/nav` was already wrapped by `getNavSeries()`.

Runtime verification also exposed a second API-contract issue: live
`/api/backtest/compare` responses serialize Decimal metrics as strings, but
`MetricRow` rendered them as numbers and crashed before S5 could be exercised.

Evidence:

- `docs/mvp/MVP_5_3_backtest_compare.md:36` and `:74` — S5 trade diff in scope.
- `backend/app/api/backtest.py:429` — GET `/backtest/{run_id}/nav`.
- `backend/app/api/backtest.py:469` — GET `/backtest/{run_id}/trades`.
- `backend/app/api/backtest.py:1081` — POST `/backtest/compare`.
- `frontend/src/api/backtest.ts:340` and `:355` — `compareBacktests()` numeric
  normalization.
- `frontend/src/api/backtest.ts:419` — `getNavSeries()`.
- `frontend/src/api/backtest.ts:427` — `getBacktestTrades()`.
- `frontend/src/pages/BacktestCompare.tsx:334`, `:339`, `:355`, `:645` —
  lazy `TradeListDiff` section.

## Closure

- Added typed paged trades API wrapper: `BacktestTradeRow`,
  `BacktestTradesResponse`, `BacktestTradesParams`, and `getBacktestTrades()`.
- Added S5 `TradeListDiff` to `BacktestCompare.tsx`.
- Kept S5 collapsed by default; it fetches per-run trade pages only after the
  operator expands the section.
- Added per-run trade tables and first-page signed-share divergence summary.
- Normalized compare metric fields in `compareBacktests()` so live Decimal
  strings cannot crash metric rendering.
- Added `frontend/src/__tests__/backtest-compare-trade-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` rows 24-25 and narrowed the backtest §5D
  backlog.
- Updated MVP 5.3 design doc with a governance note.

## Verification

- RED: `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts`
  failed because `getBacktestTrades()` and `TradeListDiff` were missing.
- GREEN: `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts`
  -> 3 passed.
- TypeScript: `npx tsc -b --pretty false` first caught a nullable aggregate
  index; after fixing it, TypeScript exited 0.
- Full frontend suite: `npx vitest --run` -> 135 passed across 27 files.
- Build: `npm run build` -> exit 0 with the existing Vite vendor-echarts
  chunk-size warning.
- API discipline: `python scripts/audit/check_frontend_api_discipline.py` ->
  PASS.
- Browser smoke: opened
  `http://127.0.0.1:5173/backtest/compare?runs=2c91bd92-ee0f-4f52-9244-795365cc1037,3d7ecc84-0536-4d26-ac07-3eca4d53bdc4`,
  verified S5 collapsed, expanded it, saw read-only per-run `无交易记录` states,
  and fresh console errors were empty.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Backlog

- Backtest rows 26-32 and 34-35 remain backend-only until dedicated deep-dive
  views need holdings, annual/monthly slices, attribution, market state, cost
  sensitivity, report, sensitivity, or live-compare endpoints.
- A holdings-based position-diff view remains a separate enhancement; Batch 20
  implements trade-share divergence from the lazy trade endpoint.
