# STATUS REPORT - 2026-06-01 Governance Batch 15

## Scope

Risk Management API-layer closure for PR #523 on branch
`codex/runtime-governance-followup`.

## Finding

`frontend/src/pages/RiskManagement.tsx` was still using direct `apiClient`
calls for implemented risk endpoints while `docs/API_COVERAGE.md` rows 121-129
marked the same endpoints as unwired. Fresh code inspection also found a
response-shape mismatch:

- `/api/risk/overview` returns raw scalar fields, while the page expected
  `metrics`, `var_series`, and `exposure`.
- `/api/risk/limits` returns `normal/warning/danger` and `usage_pct`, while the
  page counted `ok/warn/critical` and rendered `usage`.
- `/api/risk/stress-tests` returns `estimated_loss` and `period`, while the page
  rendered `impact` and `recovery`.

## Closure

- Added typed wrappers and normalization to `frontend/src/api/risk.ts`:
  `fetchRiskHistory`, `fetchRiskSummary`, `fetchRiskOverviewDisplay`,
  `fetchRiskLimits`, and `fetchStressTests`.
- Moved risk display normalization into the API layer.
- Preserved live-to-paper fallback by keeping `data_days <= 0` overview
  responses as empty metric sets.
- Refactored `RiskManagement.tsx` to consume risk wrappers only.
- Added `frontend/src/__tests__/risk-management-api-contract.test.ts` to lock
  wrapper endpoints, normalization, and the page boundary.
- Updated `docs/API_COVERAGE.md` rows 121-129 and narrowed the risk backlog to
  L4 admin mutations.

## Verification

- RED:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  failed before the fix on missing wrapper exports and direct page `apiClient`
  usage.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  -> 7 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/report-center-api-contract.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 37 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite: `npx vitest --run` -> 123 passed across 23 files.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/risk`; heading
  `风控管理`, tab `风控总览`, and tab `限额监控` each resolved once; console error
  list was empty. Existing dev server on port 5173 was reused and not stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

## Remaining Backlog

- `SafetyControlPanel.tsx` still owns direct risk L4 mutation calls for
  `/api/risk/l4-recovery/{strategy_id}` and `/api/risk/l4-approve/{approval_id}`.
  Keep this as a follow-up admin-flow wrapper candidate.
- `PTGraduation.tsx` and `QMTStatusBadge.tsx` remain direct page/component
  imports; contract them only with current code evidence.
- Ops deployment remains separate: reload `worker`, `slow-worker`, and `beat`
  from an elevated/admin shell, then verify the next `realtime_risk_tick`
  skip reason. This batch did not perform runtime mutations.
