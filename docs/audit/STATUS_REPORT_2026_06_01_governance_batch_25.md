# STATUS REPORT — 2026-06-01 Governance Batch 25

## Scope

Close notification detail API coverage and reclassify the standalone unread
count endpoint.

## Finding

`docs/API_COVERAGE.md` §5D grouped rows 88-89 as a single notification backlog.
Fresh code review split that into two cases:

- Row 88 `GET /api/notifications/unread-count` is redundant for the current
  panel because `GET /api/notifications` already returns `unread_count`.
- Row 89 `GET /api/notifications/{notification_id}` was a real frontend
  integration gap: the panel could list and mark notifications, but could not
  fetch the backend detail row.

Active discovery also found a UI state bug while implementing the detail view:
closing the dropdown via outside click preserved the prior detail payload, so a
reopened panel skipped the list and showed stale detail content.

## Changes

- Added `fetchNotificationDetail()` to
  `frontend/src/api/notifications.ts`.
- Wired no-link notification rows in
  `frontend/src/components/ui/NotificationPanel.tsx` to fetch and render the
  backend detail endpoint.
- Added loading, error, back-to-list, and close-reset states for the detail
  panel.
- Added API and UI contract tests for the detail endpoint and a regression test
  for closing/reopening the dropdown.
- Updated `docs/API_COVERAGE.md` row 88, row 89, §5A, §5D, §11, and new §26.
- Updated `memory/project_sprint_state.md` top handoff.

## Verification

- RED detail contract:
  `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx`
  failed before implementation because `fetchNotificationDetail` was missing
  and the panel did not call the detail endpoint.
- RED close-state regression:
  `npx vitest --run src/__tests__/notifications-ui-contract.test.tsx -t "returns to the list"`
  failed before the close-path fix because the prior detail body remained after
  close/reopen.
- Targeted notification contracts:
  `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx`
  -> 13 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 149 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected;
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.

## Redline / Scope

No broker calls, `.env` edits, production YAML edits, DB row mutations, Servy
changes, Task Scheduler mutations, or QMT runtime starts were performed. This
batch is limited to frontend notification consumption, tests, and governance
sediment.

## Remaining Risk

- Remote PR checks must pass after push before this batch is treated as
  merge-ready; this report records the local verification gate.
- Notification cleanup, preferences, and admin test endpoints remain
  backend/admin workflow candidates, not current operator panel blockers.
- Remaining §5D backlog after this batch: backtest sensitivity, execution
  pending-orders/log/algo-config, execution alert-config PUT, legacy
  paper-trading status/graduation endpoints, and strategy versions/factors/
  backtest endpoints.
