# Governance Batch 9 - Notification Panel API Closure

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 9 closes the frontend notification mock-seeding backlog tracked from Batch 1:

- Route the sidebar notification panel through backend notification endpoints.
- Remove seeded mock rows from the provider.
- Add loading, empty, error, backend data, mark-all, and already-read click coverage.
- Keep the change frontend/API-layer only.

No broker, QMT, `.env`, production YAML, scheduler, Servy, database mutation, or service-control action was performed.

## Finding

The frontend had a backend notification router, but the visible notification panel never called it. `NotificationProvider` initialized from `makeMockNotifications()`, so operators saw plausible local alerts even when backend state was empty or unavailable.

Active discovery:

- `Layout.tsx` and `main.tsx` both mounted `NotificationProvider` and `ToastContainer`. Once backend fetch was added, that shell shape would have produced duplicate notification API calls and split context state.
- Clicking an already-read row would have called `PUT /api/notifications/{id}/read`; the backend returns 404 for already-read rows, turning a harmless click into a reload/error path.
- `GET /api/notifications/unread-count` is currently redundant because the list endpoint already returns `unread_count`; it remains unwired intentionally rather than as a broken panel dependency.

## Fixes

- Added `frontend/src/api/notifications.ts` with normalized wrappers for:
  - `GET /notifications`
  - `PUT /notifications/{id}/read`
  - `PUT /notifications/read-all`
- Refactored `NotificationProvider` to load backend notifications on mount, expose loading/error state, preserve toast support, and update unread count from backend data.
- Updated `NotificationPanel` to render loading, empty, error, and backend-data states.
- Removed the nested provider/toast container from `Layout.tsx`; `main.tsx` remains the single app-level provider mount.
- Added API and UI contract tests, including a shell guard proving one API-backed provider and an already-read click guard.
- Updated `docs/API_COVERAGE.md` with the 2026-06-01 notification closure addendum.

## Verification

Red phase:

- `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx` failed before the fix:
  - missing `@/api/notifications`;
  - zero backend fetch calls;
  - seeded mock rows still visible;
  - no loading/error backend states;
  - mark-all did not call the backend.
- `npx vitest --run src/__tests__/notifications-ui-contract.test.tsx -t "already-read"` failed before the read-row guard because `markNotificationRead("api-1")` was still called.

Green phase:

- Targeted notification contracts -> 10 passed.
- `npx vitest --run` -> 100 passed.
- `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7005 deselected.

## Open Backlog

- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.
- **GB9-B1 [P2]** Notification detail, cleanup, and preferences endpoints remain backend/admin-only. Revisit only if they become explicit operator workflows.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
