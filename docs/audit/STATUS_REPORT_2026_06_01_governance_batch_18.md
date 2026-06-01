# Governance Batch 18 Status Report — PTGraduation API Layer Closure

Date: 2026-06-01 16:14 +08
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 18 closed the remaining known production page/component `apiClient`
bypass from the API-governance lane:

- `frontend/src/pages/PTGraduation.tsx`
- `frontend/src/api/dashboard.ts`
- `frontend/src/__tests__/pt-graduation-api-contract.test.ts`
- `docs/API_COVERAGE.md`

No broker APIs, `.env`, production YAML, database rows, Servy config, Task
Scheduler config, or QMT runtime state were changed.

## Finding

Fresh code review found that `PTGraduation.tsx` still called
`/paper-trading/graduation-status` directly through `apiClient`, while
`docs/API_COVERAGE.md` rows 94-96 still marked the paper-trading page endpoints
as not wired. Fresh evidence showed `/paper-trading/trades` and the positions
fallback already lived in `frontend/src/api/dashboard.ts`; only the
graduation-status page request still bypassed the wrapper layer.

Evidence:

- `backend/app/api/paper_trading.py:101` — GET `/graduation-status`.
- `backend/app/api/paper_trading.py:224` — GET `/positions`.
- `backend/app/api/paper_trading.py:243` — GET `/trades`.
- `frontend/src/api/dashboard.ts:67` — `fetchPaperTrades()`.
- `frontend/src/api/dashboard.ts:99` — `fetchPaperGraduationStatus()`.
- `frontend/src/api/dashboard.ts:109` — `fetchPositions()`.
- `frontend/src/pages/PTGraduation.tsx:264` — page calls
  `fetchPaperGraduationStatus("live")`.

## Closure

- Added `PaperGraduationCriterion`, `PaperGraduationStatus`, and
  `fetchPaperGraduationStatus()` to `frontend/src/api/dashboard.ts`.
- Removed the direct `apiClient` import and call from `PTGraduation.tsx`.
- Added `frontend/src/__tests__/pt-graduation-api-contract.test.ts` to lock the
  dashboard wrapper and page boundary.
- Updated `docs/API_COVERAGE.md` rows 94-96 and narrowed the §5D paper-trading
  backlog to rows 92-93.

## Verification

- RED: `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts`
  failed before the fix because `fetchPaperGraduationStatus()` was missing and
  `PTGraduation.tsx` imported `apiClient` directly.
- GREEN targeted: `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts src/__tests__/TradeLogPanel.test.tsx`
  -> 5 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts src/__tests__/TradeLogPanel.test.tsx src/__tests__/dashboard-api-contract.test.ts src/__tests__/health-api-contract.test.ts src/__tests__/risk-management-api-contract.test.ts`
  -> 23 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest --run` -> 130 passed across 25 files.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Production page/component direct `apiClient` grep -> no matches.
- Browser smoke: `http://127.0.0.1:5173/pt-graduation` loaded
  `PT 毕业评估` with backend data and no console errors.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013
  deselected.

## Backlog

- Rows 92-93 (`/api/paper-trading/status`, `/api/paper-trading/graduation`)
  remain unwrapped legacy endpoints until a current frontend workflow needs
  them.
- Ops deployment, QMTData runtime, and DeepSeek credential/account backlog are
  unchanged from prior governance reports.
