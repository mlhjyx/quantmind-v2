# Governance Batch 31 Status — SSE risk-events matrix closure

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage row 131, SSE EventSource contract coverage, stale matrix
cleanup.

## Summary

Batch 31 closed a false backend-only marker for
`GET /api/sse/risk-events`. The route is intentionally consumed through native
`EventSource`, not `apiClient`, so the previous API-wrapper grep missed it.
`RiskManagement.tsx` already mounts `useRiskEventsSSE()` for the live
risk-events tab.

## Changes

- Added `frontend/src/__tests__/risk-events-sse-hook.test.tsx`.
- Locked SSE URL derivation, `withCredentials`, connection state, risk-event
  buffering, heartbeat parsing, server-error surfacing, and cleanup.
- Updated `docs/API_COVERAGE.md` row 131 to the actual hook line anchor.
- Added `docs/API_COVERAGE.md` §32 evidence.

## Active Discovery

1. Row 131 was stale because it is not an axios wrapper path.
2. The current frontend consumer is `RiskManagement.tsx` -> `useRiskEventsSSE()`
   -> native `EventSource`.
3. This is a documentation/matrix classification gap, not a missing integration.

## Verification

- Targeted hook contract:
  `npx vitest --run src/__tests__/risk-events-sse-hook.test.tsx` -> 1 passed.
- TypeScript:
  `npx tsc -b --pretty false` -> exit 0.
- API discipline:
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Full frontend regression:
  `npx vitest --run` -> 34 files passed, 161 tests passed.
- Production build:
  `npm run build` -> exit 0 with the existing large `vendor-echarts` warning.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 scan clean, LLM import guard clean,
  smoke 91 passed, 2 skipped, 6976 deselected.

## Remaining Work

- Rows 72-73 and 116-117 remain external monitoring endpoints.
- Row 130 remains a DingTalk webhook receiver.
- Rows 83-86, 91, 98-99, and 101 still need fresh code-backed classification
  or implementation decisions.
- Rows 135-136 remain strategy version mutation workflow backlog.
- Row 141 remains superseded by the backtest config-confirmation flow.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
