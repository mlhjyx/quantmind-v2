# STATUS REPORT - 2026-06-01 Governance Batch 16

## Scope

SafetyControlPanel L4 API-layer closure for PR #523 on branch
`codex/runtime-governance-followup`.

## Finding

`frontend/src/components/safety/SafetyControlPanel.tsx` still owned two direct
admin risk mutations:

- POST `/api/risk/l4-recovery/{strategy_id}`
- POST `/api/risk/l4-approve/{approval_id}`

The backend endpoints were implemented in `backend/app/api/risk.py:206` and
`backend/app/api/risk.py:239`, but `docs/API_COVERAGE.md` rows 124-125 still
marked them as unwired and there was no `frontend/src/api/risk.ts` wrapper
contract. This was a governance gap on a privileged L4 recovery flow.

## Closure

- Added typed `requestL4Recovery()` and `approveL4Recovery()` wrappers to
  `frontend/src/api/risk.ts`.
- Refactored `SafetyControlPanel.tsx` so L4 request and approve/reject actions
  call the risk API layer instead of importing `apiClient` directly.
- Extended `frontend/src/__tests__/risk-management-api-contract.test.ts` with
  L4 wrapper endpoint assertions and a SafetyControlPanel source-boundary
  guard.
- Updated `frontend/src/__tests__/SafetyControlPanel.test.tsx` mocks to keep the
  existing L4 UI flow tests passing through wrapper-shaped calls.
- Updated `docs/API_COVERAGE.md` rows 124-125 and removed the L4 row from the
  backend-implemented-but-unwired backlog.

## Verification

- RED:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  failed before the fix on missing wrapper exports and direct component
  `apiClient` usage.
- GREEN targeted contract/UI:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx`
  -> 17 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx src/__tests__/report-center-api-contract.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 47 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite: `npx vitest --run` -> 126 passed across 23 files.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/risk`, clicked
  the emergency-control tab, and found the expected safety panel sections with
  zero console errors. Existing dev server on port 5173 was reused and not
  stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Remaining Backlog

- `PTGraduation.tsx` and `QMTStatusBadge.tsx` remain the only direct
  page/component `apiClient` import candidates found by fresh grep.
- `/api/risk/dingtalk-webhook` remains a webhook/ops endpoint, not a frontend
  wrapper target without a UI workflow.
- Ops deployment remains separate: reload `worker`, `slow-worker`, and `beat`
  from an elevated/admin shell, then verify the next `realtime_risk_tick`
  skip reason. This batch did not perform runtime mutations.
