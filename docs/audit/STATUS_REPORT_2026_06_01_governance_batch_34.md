# Governance Batch 34 Status — Params contract drift and taxonomy

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 97-101.

## Summary

Batch 34 fixes an actual frontend/backend contract drift in the notification
settings params wrapper and reclassifies the remaining params endpoints as
audit/read/bootstrap surfaces rather than unresolved frontend wiring gaps.

## Changes

- Added `frontend/src/__tests__/system-api-contract.test.ts`.
- Fixed `frontend/src/api/system.ts::fetchNotificationParams()` to query
  `module=notification` and normalize grouped backend params into the array
  shape consumed by `SystemSettings.tsx`.
- Added route tests in `backend/tests/test_param_system.py` for
  `/api/params/changelog` and `/api/params/init-defaults`.
- Updated `docs/API_COVERAGE.md` rows 97-101 and added §35.

## Active Discovery

1. Row 97 was marked consumed, but the wrapper used `category` while the backend
   expects `module`.
2. The wrapper returned `{modules, params}` as though it were an array, so the
   SystemSettings notification tab could call `.map()` on a non-array response.
3. Rows 98, 99, and 101 are not current operator UI gaps: changelog is audit,
   GET-by-key is redundant with grouped list for current settings, and
   init-defaults is bootstrap/admin behavior.

## Verification

- RED:
  `npx vitest --run src/__tests__/system-api-contract.test.ts` failed on
  `category` vs `module`.
- GREEN:
  `npx vitest --run src/__tests__/system-api-contract.test.ts` -> 1 passed.
- Backend params routes:
  `pytest backend/tests/test_param_system.py::TestParamAPI -q` -> 8 passed.
- Frontend params/system subset:
  `npx vitest --run src/__tests__/system-api-contract.test.ts src/__tests__/system-settings-streams.test.tsx`
  -> 2 files passed, 2 tests passed.
- TypeScript:
  `npx tsc -b --pretty false` -> exit 0.
- Frontend full suite:
  `npx vitest --run` -> 35 files passed, 162 tests passed.
- Frontend build:
  `npm run build` -> exit 0 with existing large `vendor-echarts` warning.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7026
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6982 deselected.

## Remaining Work

- Remaining `❌` rows after this taxonomy cleanup: 34, 135-136, and 141.
- `/api/params/init-defaults` remains an admin/bootstrap endpoint. A separate
  backend security pass should decide whether it needs `verify_admin_token`
  alongside other public params mutation endpoints.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
