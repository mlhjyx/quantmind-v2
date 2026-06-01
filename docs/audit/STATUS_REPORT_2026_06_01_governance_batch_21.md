# STATUS_REPORT — 2026-06-01 Governance Batch 21

## Scope

Backtest detail endpoint schema/runtime hardening for PR #523 branch
`codex/runtime-governance-followup`.

## Finding

Batch 20 browser/runtime verification surfaced that several `/api/backtest/*`
detail endpoints were documented as backend-implemented but failed against the
actual DB schema:

- `backtest_daily_nav` stores `benchmark_nav`, not `benchmark_return`.
- `backtest_trades` stores `trade_id`, not `id`, and does not store
  `target_price` or `transfer_fee`.
- `backtest_holdings` stores `shares`, `cost_basis`, and `market_price`, not
  stored `market_value` or `pnl`.
- Decimal/date/UUID values leaked from some detail endpoint payloads.

## Closure

- `backend/app/api/backtest.py`
  - `_safe_query()` now returns empty lists only for missing relation errors;
    undefined-column drift fails loud.
  - NAV and report paths derive `benchmark_return` from `benchmark_nav`.
  - Trades path selects `trade_id AS id` and uses `CAST(NULL AS NUMERIC)` for
    fields not persisted by the writer.
  - Holdings and attribution derive market value and PnL from actual holdings
    columns.
  - Annual, monthly, market-state, cost-sensitivity, live-compare, and row
    payloads normalize Decimal/date/UUID shapes.
- `frontend/src/api/backtest.ts`
  - `BacktestTradeRow.id` now accepts string UUIDs as well as legacy numeric
    IDs.
- `backend/tests/test_backtest_detail_endpoint_contract.py`
  - Added regression tests for schema-error fail-loud behavior, JSON conversion,
    DDL-aligned SQL guards, UUID trade IDs, Decimal cost-sensitivity arithmetic,
    and live-compare metrics.
- `docs/API_COVERAGE.md`
  - Added §22 and clarified that backtest rows 26-32 + 35 are backend-runtime
    hardened but still frontend-unwired.
  - Corrected stale cancel-orphan text: `cancelBacktest()` maps to
    `POST /api/backtest/{run_id}/cancel` in `backtest.py`.
  - Surfaced a broader aggregate-count drift: raw route grep now reports 170
    backend routes across 25 router files and 18 frontend API modules. Header
    counts were updated; full row-level non-backtest remapping remains backlog.

## Verification

- RED: `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q`
  initially failed on the new contract guards.
- GREEN: `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q`
  -> 7 passed.
- Existing compatibility:
  `pytest backend/tests/test_a4_a6.py::TestA6BacktestNavEndpoint backend/tests/test_backtest_api.py -q`
  -> 33 passed.
- Lint/compile:
  `ruff check backend/app/api/backtest.py backend/tests/test_backtest_detail_endpoint_contract.py`
  -> PASS; `python -m py_compile backend/app/api/backtest.py` -> PASS.
- Frontend compatibility:
  `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts`
  -> 3 passed; `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Full frontend suite/build:
  `npx vitest --run` -> 135 passed; `npm run build` -> exit 0 with the
  existing Vite vendor-echarts chunk-size warning.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push guard:
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.
- Real DB read-only runtime:
  direct endpoint calls for run `2c91bd92-ee0f-4f52-9244-795365cc1037` returned
  without runtime errors for nav, trades, holdings summary, annual, monthly,
  attribution, market-state, cost-sensitivity, live-compare, and report. The
  generated report temp file was removed after verification.

## Remaining Backlog

- Rows 26-32 and 35 still need frontend wrappers/deep-dive UI integration before
  the matrix can mark them consumed.
- Row 34 `/api/backtest/{run_id}/sensitivity` remains deferred by existing ADR
  tracking.
- API coverage row-level mappings outside backtest need a dedicated refresh to
  reconcile the newly surfaced 170-route / 18-module aggregate count.
