# STATUS REPORT - 2026-06-01 Governance Batch 26

## Scope

Close execution read-only DB visibility rows 44-45 and reclassify execution
mutation/display endpoints that should not be wired as operator controls yet.

## Finding

`docs/API_COVERAGE.md` §5D grouped rows 44-46 and row 62 as one frontend
backlog. Fresh code review split them into three classes:

- Rows 44-45 `GET /api/execution/pending-orders` and
  `GET /api/execution/log` are read-only `trade_log` visibility endpoints.
  They are useful as a DB fallback when QMT order/trade snapshots are absent.
- Row 46 `GET /api/execution/algo-config` is legacy display-only behavior from
  the retired `TradeExecution` path. Prior audits already found it can show
  stale `strategy_configs` values and is not in the trading path.
- Row 62 `PUT /api/execution/alert-config` is admin-gated but only writes an
  audit record and echoes the payload. It has no config storage, validation, or
  runtime reload semantics, so wiring UI would imply persistence that does not
  exist.

## Changes

- Added typed `getPendingOrders()` and `getExecutionLog()` wrappers in
  `frontend/src/api/execution.ts`.
- Added query keys and Execution page DB fallback tables for pending orders and
  execution log rows when QMT data is unavailable.
- Added source-guard/API contract tests for the two wrappers and page usage.
- Updated `docs/API_COVERAGE.md` rows 44-46, row 62, §3.5, §5C, §5D, new §5E,
  and new §27.
- Updated `memory/project_sprint_state.md` top handoff.

## Verification

- RED contract:
  `npx vitest --run src/__tests__/execution-api-contract.test.ts` failed before
  implementation because `getPendingOrders()`, `getExecutionLog()`, and page
  usage were missing.
- Targeted frontend:
  `npx vitest --run src/__tests__/execution-api-contract.test.ts` -> 3 passed.
- Backend endpoint compatibility:
  `pytest backend/tests/test_sprint123_apis.py -q` -> 21 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 152 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Browser smoke:
  `http://127.0.0.1:5173/execution?smoke=batch26` loaded in the in-app browser;
  `交易执行 / Execution Control` rendered; `今日委托` showed
  `QMT未连接，暂无待执行记录`; `今日成交` showed `QMT未连接，暂无执行日志`;
  timestamped console-error window after `2026-06-01T10:23:16.466Z` had 0 new
  errors.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected;
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.

## Redline / Scope

No broker calls, `.env` edits, production YAML edits, DB row mutations, Servy
changes, Task Scheduler mutations, or QMT runtime starts were performed. This
batch is limited to frontend read-only DB visibility, tests, and governance
sediment.

## Remaining Risk

- Remote PR checks must pass after push before this batch is treated as
  merge-ready; this report records the local verification gate.
- `PUT /api/execution/alert-config` needs a backend semantics design before UI:
  storage, validation, diff preview, reload behavior, audit payload, and rollback
  path.
- Row 46 should stay out of operator UI unless the legacy display-only endpoint
  is replaced by a current execution configuration source.
- Remaining §5D backlog after this batch: backtest sensitivity, legacy
  paper-trading status/graduation endpoints, and strategy versions/factors/
  backtest endpoints.
