# STATUS REPORT - 2026-06-01 Governance Batch 17

## Scope

QMTStatusBadge health API-layer closure for PR #523 on branch
`codex/runtime-governance-followup`.

## Finding

`frontend/src/components/shared/QMTStatusBadge.tsx` directly called
`/api/health/qmt`, while `docs/API_COVERAGE.md` row 74 still marked that
endpoint as backend-only. Fresh grep found the badge is exported but not mounted
by current frontend routes, so the risk was governance drift and future
wrapper-boundary leakage rather than an active visible page bug.

## Closure

- Added `QmtAccountAsset` and `QmtHealth` types to `frontend/src/api/system.ts`.
- Added `fetchQmtHealth()` as the typed `/health/qmt` wrapper.
- Refactored `QMTStatusBadge.tsx` to consume `fetchQmtHealth` and remove direct
  `apiClient` usage.
- Added `frontend/src/__tests__/health-api-contract.test.ts` with endpoint and
  component-boundary assertions.
- Updated `docs/API_COVERAGE.md` row 74 and clarified the health endpoint
  backlog note.

## Verification

- RED:
  `npx vitest --run src/__tests__/health-api-contract.test.ts` failed before the
  fix on missing `fetchQmtHealth` and direct `QMTStatusBadge` `apiClient` usage.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/health-api-contract.test.ts` -> 2 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/health-api-contract.test.ts src/__tests__/system-api-scheduler.test.ts src/__tests__/system-api-paper-sid.test.ts src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 44 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite: `npx vitest --run` -> 128 passed across 24 files.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Remaining Backlog

- `PTGraduation.tsx` is the only direct page/component `apiClient` import found
  by fresh grep after this batch.
- `QMTStatusBadge` is not mounted by current routes, so no route-specific browser
  smoke was used for this batch.
- Ops deployment remains separate: reload `worker`, `slow-worker`, and `beat`
  from an elevated/admin shell, then verify the next `realtime_risk_tick`
  skip reason. This batch did not perform runtime mutations.
