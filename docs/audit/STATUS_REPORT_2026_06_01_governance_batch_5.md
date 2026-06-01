# Governance Batch 5 - Frontend WebSocket Contract Closure

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 5 closed the Batch 1 frontend/API backlog item for the backtest and pipeline WebSocket contract drift.

The code-backed contract is Socket.IO mounted by FastAPI at `/ws/socket.io`; backtest clients join per-run rooms through `join_backtest` and leave through `leave_backtest`. There is no backend native WebSocket route for `/ws/pipeline/{run_id}`.

## Finding

- `frontend/src/hooks/useBacktestProgress.ts` connected to `${WS_URL}/ws/backtest` and emitted `subscribe`, which does not match the backend Socket.IO mount or event names.
- `frontend/src/pages/PipelineConsole.tsx` opened `new WebSocket(.../ws/pipeline/{run_id})`, but the backend does not expose that route. The page already has a polling fallback, so this created a broken connection attempt without adding a working live channel.

## Fixes

- Updated `useBacktestProgress` to connect through Socket.IO with `path: "/ws/socket.io"`, a configurable origin, and websocket-plus-polling transports.
- Replaced the unsupported `subscribe` event with `join_backtest` and added `leave_backtest` during cleanup.
- Removed the unsupported native `/ws/pipeline/{run_id}` connection from `PipelineConsole`; the page now relies on the existing status/log polling path until a real backend stream is implemented.
- Added `frontend/src/__tests__/websocket-contract.test.tsx` to lock the frontend to the backend WebSocket contract.

## Verification

Red phase:
- `npx vitest run src/__tests__/websocket-contract.test.tsx` failed before the fix because `io` was called with `/ws/backtest` and `PipelineConsole` constructed `/ws/pipeline/pipeline-run-1`.

Green phase:
- `npx vitest run src/__tests__/websocket-contract.test.tsx` -> 2 tests passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__/websocket-contract.test.tsx src/__tests__/PipelineConsole.test.tsx src/__tests__/backtest-api.test.ts src/__tests__/pages.test.tsx` -> 18 tests passed.
- `npm run build` -> exit 0; Vite reported the existing large chunk warning only.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.
- `git diff --check` -> exit 0; Git reported CRLF normalization warnings only.

## Open Backlog

- **GB5-B1 [P1 frontend/backend]** `FactorLab` and `MiningTaskCenter` still use `useWebSocket` with `/ws/factor-mine/{id}`. Backend support for that route was not found in this batch. Acceptance: either implement a backend Socket.IO/native WebSocket mining stream with regression coverage, or remove the unsupported live connection and rely on explicit polling with tests proving no broken route is opened.
- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the new `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
