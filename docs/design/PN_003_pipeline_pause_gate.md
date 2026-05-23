# PN-003 — Pipeline Pause Gate (D1 O3)

> Iter 12 Inner-loop-B step 3 design doc — L4+R loop. 铁律 24 (≤2 pages).
> SSOT: docs/L4R_LOOP_SPEC.md §10. Predecessors: PN-001 (O8 automation-level),
> PN-002 (O10 correlation prune).

## §1 Scope & Intent

**Problem**: Frontend `PipelineConsole.tsx:206` calls `pausePipeline()` →
`POST /api/pipeline/pause` (no body). No backend endpoint → 404. Button shows
"暂停操作失败" on every click. UI orphan (API_COVERAGE.md §6).

**Minimum viable semantics**: **gate-at-entry** pause.
- Clicking 暂停 marks the pipeline as paused at the orchestration layer.
- Next scheduled Beat invocation (`run_gp_mining` / `run_bruteforce_mining`)
  and any explicit `POST /pipeline/trigger` SKIP / 409 while paused.
- Currently-running task is NOT interrupted mid-stage (out of scope —
  cooperative mid-run abort would require per-stage checkpoints, larger
  iteration; documented under §6 future work).
- Resume restores normal operation; next Beat fires unchanged.

**Out of scope**:
- Mid-run cooperative abort (defer to D3 BruteForce iter or follow-up).
- Backtest pause (separate path, already has cancel via O1).
- Pause history / audit trail beyond the singleton row's `paused_at`.

## §2 Storage Decision

**Choice**: extend `pipeline_settings` singleton (PN-001).

Reuses existing CHECK (id=1) singleton invariant + GET/PUT endpoint base.
0 new tables. Migration is idempotent ALTER ADD COLUMN IF NOT EXISTS.

```sql
ALTER TABLE pipeline_settings
  ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS paused_reason TEXT NULL;

COMMENT ON COLUMN pipeline_settings.paused_at IS
  'NULL = active; NOT NULL = paused (gate-at-entry, mid-run not aborted)';
COMMENT ON COLUMN pipeline_settings.paused_reason IS
  '可选暂停理由，UI 显示用';
```

Rejected alternatives:
- New `pipeline_pause_state` table → 0 marginal benefit, singleton suffices.
- Bool `paused: boolean` → no audit timestamp; `paused_at TIMESTAMPTZ NULL`
  encodes both state (NULL vs NOT) and pause-since timestamp in 1 column.

## §3 Endpoint Contracts

All localhost-only (`_require_local` per existing pipeline.py pattern).

### `POST /api/pipeline/pause`
- Body: `{ reason: str | null }` (optional, length ≤ 500).
- Behavior: if `paused_at IS NULL` → set to `NOW()` + reason; else idempotent
  (returns current `paused_at` / `paused_reason` unchanged, NOT refreshed —
  prevents reason overwrite by accidental double-click).
- Response 200: `{ paused_at: ISO8601, paused_reason: str | null }`.

### `POST /api/pipeline/resume`
- Body: none.
- Behavior: idempotent SET `paused_at = NULL, paused_reason = NULL` WHERE id=1.
- Response 200: `{ paused_at: null, paused_reason: null }`.

### `GET /api/pipeline/status` (extend existing)
- Add `paused_at: ISO8601 | null` and `paused_reason: str | null` to response.
- Frontend `PipelineStatusResponse` consumer updated to surface paused state.

### `POST /api/pipeline/trigger` (existing — gate at entry)
- BEFORE writing pipeline_runs row: SELECT paused_at FROM pipeline_settings.
- If NOT NULL → raise `HTTPException(409, "Pipeline is paused since {paused_at}")`.
- Existing 409 "already running" check stays — pause check is additional gate.

### Beat tasks `run_gp_mining` / `run_bruteforce_mining` (existing — gate at entry)
- FIRST step of task body: SELECT paused_at FROM pipeline_settings (sync psycopg2).
- If NOT NULL → log `pipeline_skipped_paused` structured event + return early
  (`{"status": "skipped_paused"}`). NO pipeline_runs row written. NO failure
  marked. Next Beat tick reattempts naturally.

## §4 Code Touch Points

| File | Change |
|------|--------|
| `backend/migrations/pipeline_settings.sql` | append 2 ADD COLUMN IF NOT EXISTS + 2 COMMENT |
| `backend/migrations/pipeline_settings_rollback.sql` | append DROP COLUMN IF EXISTS for both |
| `docs/QUANTMIND_V2_DDL_FINAL.sql` | sync pipeline_settings table block + KEEP-IN-SYNC note |
| `backend/app/api/pipeline.py` | + 2 endpoints (pause/resume) + Pydantic models; extend `PipelineStatusResponse` + status query; gate inside `POST /trigger` |
| `backend/app/services/mining_service.py` | new method `_is_paused()` async; called from `trigger_pipeline_run()` before the engine-running check |
| `backend/app/tasks/mining_tasks.py` | gate at top of `run_gp_mining` + `run_bruteforce_mining` body (sync psycopg2 SELECT) |
| `backend/tests/test_pipeline_pause.py` | new test file (mock-based) — 6 cases |
| `frontend/src/api/pipeline.ts` | implement `pausePipeline()` payload + new `resumePipeline()` + extend `PipelineStatusResponse` type |
| `frontend/src/__tests__/pipeline-api.test.ts` | + pause/resume cases |
| `docs/adr/ADR-DRAFT.md` | append row 13 candidate |
| `docs/API_COVERAGE.md` | mark `/pipeline/pause` & `/pipeline/resume` wired |

## §5 Test Plan (mock-based, no DB)

1. `POST /pipeline/pause` empty body → 200, `paused_at` populated, reason None.
2. `POST /pipeline/pause` with reason → 200, reason persisted.
3. `POST /pipeline/pause` when already paused → 200, `paused_at` unchanged
   (idempotent NO-overwrite).
4. `POST /pipeline/resume` when paused → 200, `paused_at = null`.
5. `POST /pipeline/resume` when not paused → 200 idempotent.
6. `POST /pipeline/trigger` when paused → 409 with reason in detail.

Frontend vitest: pause sends POST with reason payload; resume sends POST no body;
status type accepts paused_at field.

## §6 Risk & Future Work

**Risk**:
- (R1) Mid-run task not aborted by pause — UI users may expect immediate halt.
  Mitigation: surface "暂停: 仅阻止下次启动，当前运行继续" in frontend tooltip.
  Future iter (D3 or follow-up) can add cooperative checkpoints in GP loop.
- (R2) Pause-state visible to Beat workers only at task entry — between pause
  click and next Beat tick (≤ Beat interval) UI may show stale "running" status.
  Acceptable: pause is advisory, next tick honors it; no safety guarantee
  beyond "no new run starts".

**Future work** (not blocked by this iter):
- Cooperative mid-run abort with per-stage `pause_requested` polling.
- Pause-history table for audit (currently only `paused_at` for current state).
- Frontend resume button (UI currently has only 暂停; resume by automation_level
  toggle or new button — out of scope here).

## §7 §6 8-trigger STOP Self-Check

| # | Trigger | Verdict |
|---|---------|---------|
| 1 | Framework 新加 (12 cap) | NEGATIVE (reuses pipeline_settings + pipeline.py) |
| 2 | Architecture 大改 | NEGATIVE (2 cols + 2 endpoints) |
| 3 | Strategy 改动 | NEGATIVE (orchestration only) |
| 4 | 红线 5/5 触碰 | NEGATIVE (no .env / broker / 真账户 / EXECUTION_MODE / LIVE_TRADING_DISABLED touch) |
| 5 | PT 重启 gate | NEGATIVE |
| 6 | 新引擎 | NEGATIVE |
| 7 | Beat schedule 改 | NEGATIVE (gates entry; Beat still fires) |
| 8 | Self-protection (§1/§4/§5/§6/§9/§14) | NEGATIVE (no L4R spec edit) |

All NEGATIVE → Inner-loop-A IMPLEMENT cleared.

## §8 §4.5 Value Verdict — IMPLEMENT

- Scope: small (2 DB cols + 2 endpoints + 2 gates + 6 pytest + 2 vitest).
- 红线: 0 触碰.
- Reuses PN-001 singleton + PN-002 mock-test pattern.
- Unblocks frontend graceful-404 button.
- Risk band: low (advisory pause, mid-run abort explicitly deferred).
- Banned-words clean: 0 真+X outside whitelist in this design.

## §9 Acceptance Criteria

- All 6 backend pytest + 2 frontend vitest pass.
- `ruff check && ruff format` clean.
- Smoke gate (`pytest -m smoke`) ≥ 61 passed (matches PN-002 baseline).
- `POST /pipeline/pause` → DB `paused_at` populated; subsequent `POST /trigger` returns 409.
- `POST /pipeline/resume` clears state; next `POST /trigger` proceeds (subject to other gates).
- Migration applied idempotently (rerun = NO-OP).
- ADR-DRAFT row 13 appended.
- Banned-words self-check: 0 真+X outside whitelist.
