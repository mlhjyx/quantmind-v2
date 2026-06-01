# Governance Batch 19 Status Report — ApprovalQueue Coverage Drift Closure

Date: 2026-06-01 16:21 +08
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 19 closed a documentation-governance drift in the API coverage matrix:

- `frontend/src/api/approval.ts`
- `frontend/src/pages/ApprovalQueue.tsx`
- `frontend/src/__tests__/approval-api-contract.test.ts`
- `docs/API_COVERAGE.md`

No broker APIs, `.env`, production YAML, database rows, Servy config, Task
Scheduler config, or QMT runtime state were changed. No approval action was
clicked in the browser.

## Finding

`docs/API_COVERAGE.md` rows 12-16 still marked approval detail, approve,
reject, hold, and history as unwired, and §5D still described the approval
workflow as incomplete. Fresh code review showed the implementation already
exists: `frontend/src/api/approval.ts` owns all six approval endpoints,
`ApprovalQueue.tsx` consumes them, and `/approval-queue` is mounted in the
router and sidebar.

Evidence:

- `backend/app/api/approval.py:205` — GET `/approval/queue`.
- `backend/app/api/approval.py:234` — GET `/approval/queue/{item_id}`.
- `backend/app/api/approval.py:259` — POST `/approval/queue/{item_id}/approve`.
- `backend/app/api/approval.py:290` — POST `/approval/queue/{item_id}/reject`.
- `backend/app/api/approval.py:321` — POST `/approval/queue/{item_id}/hold`.
- `backend/app/api/approval.py:353` — GET `/approval/history`.
- `frontend/src/api/approval.ts:84`, `:92`, `:98`, `:110`, `:122`, `:134` —
  approval API wrappers.
- `frontend/src/pages/ApprovalQueue.tsx:279`, `:450`, `:601`, `:607`, `:619`,
  `:631` — page consumers.
- `frontend/src/router.tsx:82` and
  `frontend/src/components/layout/Sidebar.tsx:82` — route and navigation.

## Closure

- Added `frontend/src/__tests__/approval-api-contract.test.ts`.
- Updated `docs/API_COVERAGE.md` rows 12-16 to covered.
- Removed the stale approval workflow row from §5D.
- Added `docs/API_COVERAGE.md` §20 with evidence and verification.

## Verification

- `npx vitest --run src/__tests__/approval-api-contract.test.ts src/__tests__/ApprovalQueue.test.tsx`
  -> 9 passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest --run` -> 132 passed across 26 files.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- `python scripts/audit/check_frontend_api_discipline.py` -> PASS.
- Browser smoke: `http://127.0.0.1:5173/approval-queue` loaded the page
  heading, pending/history tabs, empty-state backend data, and no console
  errors. No approval actions were clicked.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7013
  deselected.

## Backlog

- No approval API coverage backlog remains in §5D.
- Browser smoke for approve/reject/hold remains out of scope unless a
  separately scoped non-production fixture is created; those actions are admin
  mutations.
