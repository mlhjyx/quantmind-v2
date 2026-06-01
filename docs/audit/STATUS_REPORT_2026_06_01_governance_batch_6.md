# Governance Batch 6 - Mining WebSocket Contract Closure

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 6 closed the remaining mining WebSocket contract drift from the Batch 5 backlog.

Backend mining routes document and implement REST polling through `/api/mining/tasks` and `/api/mining/tasks/{task_id}`. The backend Socket.IO app only exposes the backtest room contract at `/ws/socket.io`; no mining namespace or native `/ws/factor-mine/{id}` route is implemented.

## Finding

- `frontend/src/pages/FactorLab.tsx` opened Socket.IO through `useWebSocket` with `/ws/factor-mine/{activeTaskId}`.
- `frontend/src/pages/MiningTaskCenter.tsx` opened the same unsupported `/ws/factor-mine/{primaryRunningId}` route for the first running task.
- `frontend/src/hooks/useWebSocket.ts` had no remaining production callers after removing those mining usages, and its namespace-based connection behavior would make the same drift easy to reintroduce.

Active discovery:
- While tracing the mining path, the task-center batch Gate action still mapped selected candidate IDs into `factor_expr`. That was already listed as a mining selected-ID placeholder backlog item and remains separate from this transport fix.
- The backend task-detail candidate shape uses `factor_name` / `factor_expr`, while the frontend candidate table expects `name` / `expression`. That candidate-normalization gap needs its own regression because it can affect displayed candidate rows and Gate submission payloads.

## Fixes

- Removed unsupported mining Socket.IO usage from `FactorLab`.
- Added supported task-detail polling in `FactorLab` while the active task is running or paused.
- Removed unsupported mining Socket.IO usage from `MiningTaskCenter`; its existing `/api/mining/tasks` polling path remains the task-list update source.
- Deleted the now-unused generic `frontend/src/hooks/useWebSocket.ts` helper and removed its stale test mock.
- Added `frontend/src/__tests__/mining-websocket-contract.test.tsx` to prove both mining pages do not open `/ws/factor-mine/{id}`.

## Verification

Red phase:
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx` failed before the fix because both `FactorLab` and `MiningTaskCenter` called Socket.IO with `/ws/factor-mine/task-running-1`.

Green phase so far:
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx` -> 2 tests passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx src/__tests__/websocket-contract.test.tsx src/__tests__/pages.test.tsx src/__tests__/api.test.ts` -> 18 tests passed.
- `npm run build` -> exit 0; Vite reported the existing large chunk warning only.
- `rg -n "/ws/factor-mine|factor-mine|useWebSocket" frontend\src backend\app backend\tests -S` -> only the new regression test references `/ws/factor-mine`; no production caller of `useWebSocket` remains.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.
- `git diff --check` -> exit 0; Git reported CRLF normalization warnings only.
- Banned-word sediment scan on this report and the new handoff section -> no hits.

## Open Backlog

- **GB6-B1 [P1 frontend/API]** Normalize mining task-detail candidates from backend `factor_name` / `factor_expr` / `gate_report` / `status` into frontend `CandidateFactor` fields before rendering and Gate submission. Acceptance: candidate table renders backend-shaped detail rows without `undefined` fields, and Gate submit sends actual DSL expressions.
- **GB6-B2 [P1 frontend/API]** Replace `MiningTaskCenter` batch Gate selected-ID placeholder with task-detail candidate lookup. Acceptance: selected IDs are resolved to candidate expressions and names; submitting selected rows never sends a raw ID as `factor_expr`.
- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the new `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
