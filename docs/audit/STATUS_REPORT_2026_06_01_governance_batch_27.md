# STATUS REPORT - 2026-06-01 Governance Batch 27

## Scope

Close paper-trading status row 92 and reclassify the older parameterized
graduation endpoint row 93.

## Finding

Rows 92-93 were grouped as legacy paper-trading backlog, but fresh code review
showed two different cases:

- Row 92 `GET /api/paper-trading/status` is a read-only status endpoint that
  returns PT NAV, position count, running days, Sharpe, MDD, total return,
  latest data date, and minimum-day readiness. `PtStatus.tsx` already had an S2
  trading-state card, but only showed env/config state.
- Row 93 `GET /api/paper-trading/graduation` is an older parameterized criteria
  endpoint that requires caller-supplied backtest baselines. Current operator
  gate UI uses fixed-standard `GET /api/paper-trading/graduation-status`, which
  is already wrapped and consumed.

## Changes

- Added `PaperTradingStatus` and `fetchPaperTradingStatus()` to
  `frontend/src/api/dashboard.ts`.
- Wired `PtStatus.tsx` S2 trading-state card to query and render the PT status
  payload.
- Extended `pt-graduation-api-contract.test.ts` with status wrapper and
  `PtStatus` source-guard coverage.
- Updated `docs/API_COVERAGE.md` row 92, row 93, §3.4, §5C, §5D, and new §28.
- Updated `memory/project_sprint_state.md` top handoff.

## Verification

- RED contract:
  `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts` failed
  before implementation because `fetchPaperTradingStatus()` and `PtStatus`
  usage were missing.
- Targeted frontend:
  `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts` -> 4
  passed.
- Backend route compatibility:
  `pytest backend/tests/test_api_routes.py::TestPaperTradingAPI -q` -> 7 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 154 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Browser smoke:
  `http://127.0.0.1:5173/pt-status?smoke=batch27` loaded in the in-app browser;
  `PT 状态` rendered; S2 showed PT NAV, holdings count, running days, Sharpe,
  MDD, cumulative return, and graduation-day readiness; timestamped
  console-error window after `2026-06-01T10:35:15.523Z` had 0 new errors.
- Live read-only endpoint probe:
  `GET http://127.0.0.1:8000/api/paper-trading/status` -> 200 with the expected
  status payload shape.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected;
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.

## Redline / Scope

No broker calls, `.env` edits, production YAML edits, DB row mutations, Servy
changes, Task Scheduler mutations, or QMT runtime starts were performed. This
batch is limited to read-only PT status visibility, tests, and governance
sediment.

## Remaining Risk

- Remote PR checks must pass after push before this batch is treated as
  merge-ready; this report records the local verification gate.
- `GET /api/paper-trading/graduation` should remain outside current operator UI
  unless caller-supplied backtest baselines become a product requirement again.
- Remaining §5D backlog after this batch: backtest sensitivity and strategy
  versions/factors/backtest endpoints.
