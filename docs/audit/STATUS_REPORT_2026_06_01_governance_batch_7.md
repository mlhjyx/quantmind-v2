# Governance Batch 7 - Mining Candidate Normalization and Gate Payload Closure

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 7 closes the mining frontend/API backlog opened in Batch 6:

- Normalize backend task-detail candidate rows before frontend rendering.
- Ensure candidate Gate submission uses DSL expressions, not selected row IDs.

This was a frontend/API adapter fix only. No backend route, broker, QMT, `.env`, production YAML, scheduler, Servy, or database mutation was performed.

## Finding

Backend task detail returns candidates shaped as `factor_name`, `factor_expr`, `status`, and `gate_report`, with task counters under `stats`. The frontend mining table expects `CandidateFactor` fields such as `name`, `expression`, `gate_status`, `ic_mean`, `t_stat`, `ic_ir`, and `coverage`.

Before this batch:

- `getMiningTaskDetail()` returned the backend payload directly, so backend-shaped candidates could render as missing table fields.
- `MiningTaskCenter` converted selected candidate IDs into `{ expr: id }` for `/api/mining/evaluate`, which could submit a row ID as `factor_expr`.
- `FactorLab` had a separate local filter/map path for Gate payloads, so the two mining screens could drift again.

Active discovery:

- The task-list adapter also carried raw status/progress values; Batch 7 normalized list and detail data through one adapter path.
- No backend mining API change was needed because `/api/mining/tasks/{task_id}` already provides enough data to resolve selected IDs to factor expressions.

## Fixes

- Added mining API normalization helpers in `frontend/src/api/mining.ts`.
- `getMiningTasks()` now normalizes raw task rows into `MiningTaskSummary`.
- `getMiningTaskDetail()` now normalizes backend-shaped detail rows into `MiningTaskDetail`, including candidate names, expressions, metrics, Gate status, task counters, and progress.
- Added `buildCandidateGatePayloads()` as a shared fail-loud helper that resolves selected IDs to candidate expressions and names.
- Updated `FactorLab` to use the shared Gate payload helper.
- Updated `MiningTaskCenter` detail modal to submit selected IDs with the loaded detail candidates, then build expression-based Gate payloads.
- Added `frontend/src/__tests__/mining-api-contract.test.ts`.

## Verification

Red phase:

- `npx vitest run src/__tests__/mining-api-contract.test.ts` failed before the fix:
  - task detail lacked normalized progress/candidate fields;
  - `buildCandidateGatePayloads` did not exist;
  - missing-expression fail-loud behavior did not exist.

Green phase:

- `npx vitest run src/__tests__/mining-api-contract.test.ts` -> 3 tests passed.
- `npx vitest run src/__tests__/mining-websocket-contract.test.tsx src/__tests__/mining-api-contract.test.ts` -> 5 tests passed.
- `npx tsc -b --pretty false` -> exit 0.
- `npx vitest run src/__tests__` -> 90 tests passed.
- `npm run build` -> exit 0; Vite reported the existing large chunk warning only.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.

## Open Backlog

- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the new `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
