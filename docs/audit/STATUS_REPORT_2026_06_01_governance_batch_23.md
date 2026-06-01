# STATUS REPORT — 2026-06-01 Governance Batch 23

## Scope

Close the read-only Redis Streams observability gap in `SystemSettings`.

## Finding

`GET /api/system/streams` was implemented in the backend but stayed
frontend-unwired in `docs/API_COVERAGE.md` row 144 and §5D. Operators had to
query Redis Streams status outside the UI even though the SystemSettings health
tab already presented PostgreSQL, Redis, Celery, disk, memory, and data
freshness.

Backend shape verified from code:

- `backend/app/api/system.py:567` returns `{"streams": bus.all_streams_status()}`.
- `backend/app/core/stream_bus.py:191` returns rows with `stream`, `length`,
  and `last_published_at`.

## Changes

- Added `SystemStreamStatus`, `SystemStreamsResponse`, and `fetchSystemStreams`
  to `frontend/src/api/system.ts`.
- Added a read-only Redis Streams panel to `frontend/src/pages/SystemSettings.tsx`
  under the system health tab. It auto-refreshes every 30 seconds, displays
  registered stream count, active stream count, total messages, per-stream
  length, and last publish time.
- Added `frontend/src/__tests__/system-api-streams.test.ts`.
- Added `frontend/src/__tests__/system-settings-streams.test.tsx`.
- Updated `docs/API_COVERAGE.md` row 144, §3.11, §5D, and drift sample D6.

## Verification

- RED:
  `npx vitest --run src/__tests__/system-api-streams.test.ts src/__tests__/system-settings-streams.test.tsx`
  failed before implementation because `fetchSystemStreams` and the UI panel
  were absent.
- GREEN targeted:
  `npx vitest --run src/__tests__/system-api-streams.test.ts src/__tests__/system-settings-streams.test.tsx`
  -> 2 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 144 passed;
  `npm run build` -> exit 0 with existing Vite vendor-echarts chunk-size
  warning.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected;
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6976 deselected.

## Remaining Risk

- Commit, push, and GitHub checks are still pending for this batch.
- Port 8000 FastAPI still needs a separate Servy reload before prior backend
  endpoint fixes can be claimed against the running service.
- Non-backtest row-level API coverage still needs a dedicated refresh against
  the 170-route / 18-frontend-module aggregate surfaced in Batch 21.
