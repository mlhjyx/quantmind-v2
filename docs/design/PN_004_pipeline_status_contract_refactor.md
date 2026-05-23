# PN-004 — `/api/pipeline/status` Contract Refactor (D1 finishing)

> Iter 15 Inner-loop-B step 3 design doc — L4+R loop. 铁律 24 (≤2 pages).
> SSOT: docs/L4R_LOOP_SPEC.md §10. Predecessors: PN-001 (O8 automation-level),
> PN-002 (O10 correlation prune), PN-003 (O3 pipeline pause gate).

## §1 Scope & Intent

**Problem**: `API_COVERAGE.md §6.1` NEW finding (Phase K reconciliation 2026-05-22):
`GET /api/pipeline/status` is consumed by frontend (`pipeline.ts` + `PipelineConsole.tsx`)
but the backend response shape does **NOT match** the frontend `PipelineStatus` type. The
frontend feeds `undefined` to many fields (FlowChart `nodes[]`, automation-level display,
schedule-cron card, next-run / last-run displays).

**Frontend consumes these fields** (verified via `grep -n status\. PipelineConsole.tsx`):
`run_id`, `is_running`, `is_paused`, `automation_level`, `current_node`, `nodes[]`,
`schedule_cron`, `next_run_at`, `last_run_at`, plus `paused_at` + `paused_reason`
(added in PN-003).

**Backend currently returns** (pipeline.py:271-419 — post PN-001/003):
`active_run_id`, `active_engine`, `status`, `current_node`, `node_statuses` (dict),
`progress`, `started_at`, `finished_at`, `error`, `paused_at`, `paused_reason`,
`config_summary`.

**Gap**: 5 fields frontend expects but backend doesn't provide: `run_id` (rename of
`active_run_id`), `is_running`, `is_paused`, `automation_level`, `nodes[]` (array shape
of `node_statuses`), `schedule_cron`, `next_run_at`, `last_run_at`.

**Goal**: align response shape — compute / map / look up the missing fields. Keep old
keys as backward-compat aliases for 1 sprint (low cost — dict response with both keys).

## §2 Refactor Plan

### §2.1 Field mapping table

| Frontend key | Backend source | Computation |
|---|---|---|
| `run_id` | `pipeline_runs.run_id` | Alias of existing `active_run_id` |
| `is_running` | `pipeline_runs.status` | `status == 'running'` |
| `is_paused` | `pipeline_settings.paused_at` | `paused_at IS NOT NULL` (PN-003) |
| `automation_level` | `pipeline_settings.automation_level` | SELECT (PN-001 helper); default `L0` |
| `current_node` | `pipeline_runs.stats.current_node` | Existing (no change) |
| `nodes[]` | `pipeline_runs.stats.node_statuses` (dict) | Map `{name: status} → [{name, status}]` ordered |
| `schedule_cron` | `app.tasks.beat_schedule` | Hardcode `0 22 * * 0` for `gp-weekly-mining` (only Beat-driven pipeline task post-PMS removal) |
| `next_run_at` | computed | Next Sunday 22:00 SH from `datetime.now()` (stdlib only; 0 deps) |
| `last_run_at` | `pipeline_runs` | `finished_at ?? started_at` of latest run |

### §2.2 Backward compatibility

Keep all old keys in response. Frontend already tolerates extra keys
(`Partial<PipelineStatus>` in WebSocket merge). Old API consumers (if any — none
identified) still work for 1 sprint.

### §2.3 Pydantic model (optional, conservative)

The current `/status` endpoint uses `response_model=dict[str, Any]` — keep that to avoid
breaking the WS partial-merge pattern (`Partial<PipelineStatus>` is structurally typed).
Pydantic model migration deferred to a later iter.

## §3 Implementation Plan

`backend/app/api/pipeline.py::get_pipeline_status` body:

```python
async def get_pipeline_status(session) -> dict[str, Any]:
    row = await _fetch_latest_run(session, status_filter="running")
    if row is None:
        row = await _fetch_latest_run(session, status_filter=None)

    paused_at, paused_reason = await _read_pause_state(session)
    automation_level = await _read_automation_level(session)
    paused_at_iso = paused_at.isoformat() if paused_at else None
    schedule_cron, next_run_at = _gp_weekly_schedule_next()

    if row is None:
        return {
            # NEW frontend-aligned keys
            "run_id": None, "is_running": False, "is_paused": paused_at is not None,
            "automation_level": automation_level, "nodes": [],
            "schedule_cron": schedule_cron, "next_run_at": next_run_at, "last_run_at": None,
            "current_node": None, "paused_at": paused_at_iso, "paused_reason": paused_reason,
            # LEGACY aliases (deprecated, 1-sprint retention)
            "active_run_id": None, "active_engine": None, "status": "idle",
            "node_statuses": {}, "progress": {}, "started_at": None, "error": None,
            "message": "无Pipeline运行记录",
        }

    stats = row["stats"] or {}
    nodes = [{"name": k, "status": v} for k, v in (stats.get("node_statuses") or {}).items()]
    last_run = row["finished_at"] or row["started_at"]
    is_running = row["status"] == "running"

    return {
        # NEW frontend-aligned keys
        "run_id": row["run_id"], "is_running": is_running,
        "is_paused": paused_at is not None, "automation_level": automation_level,
        "current_node": stats.get("current_node"), "nodes": nodes,
        "schedule_cron": schedule_cron, "next_run_at": next_run_at,
        "last_run_at": last_run.isoformat() if last_run else None,
        "paused_at": paused_at_iso, "paused_reason": paused_reason,
        # LEGACY aliases (deprecated, 1-sprint retention)
        "active_run_id": row["run_id"], "active_engine": row["engine"],
        "status": row["status"], "node_statuses": stats.get("node_statuses", {}),
        "progress": {...as today...}, "started_at": row["started_at"].isoformat() if ...,
        "finished_at": row["finished_at"].isoformat() if ..., "error": row["error_message"],
        "config_summary": {...as today...},
    }
```

### §3.1 `_gp_weekly_schedule_next()` helper (stdlib only)

```python
def _gp_weekly_schedule_next() -> tuple[str, str | None]:
    """Return (cron_str, next_run_iso) for the gp-weekly-mining Beat task.

    Hardcoded for the only Beat-driven pipeline task post-PMS removal
    (app/tasks/beat_schedule.py:53 — Sunday 22:00 SH). Returns ISO8601
    UTC for next_run_at. No external deps (no croniter).
    """
    from datetime import datetime, timedelta, timezone
    SH = timezone(timedelta(hours=8))
    now_sh = datetime.now(tz=SH)
    days_ahead = (6 - now_sh.weekday()) % 7  # Sunday = 6
    target = now_sh.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if target <= now_sh:
        target += timedelta(days=7)
    return ("0 22 * * 0", target.astimezone(timezone.utc).isoformat())
```

### §3.2 `_read_automation_level()` helper

Either factor out from `get_automation_level` endpoint, or inline the same 2-line SELECT.

## §4 Test Plan (mock-based, no DB)

4 backend pytest cases in new `backend/tests/test_pipeline_status_contract.py`:

1. **No active run + not paused** → response has `run_id=None`, `is_running=False`,
   `is_paused=False`, `automation_level='L0'`, `nodes=[]`, `schedule_cron='0 22 * * 0'`,
   `next_run_at` is a future ISO timestamp, `last_run_at=None`.
2. **Active running run** → `is_running=True`, `run_id` populated, `last_run_at = started_at`.
3. **Paused state surface** → `is_paused=True`, `paused_at` + `paused_reason` populated.
4. **`_gp_weekly_schedule_next()` unit** → cron string correct + next_run_at always future +
   always lands on a Sunday at 22:00 SH (= 14:00 UTC).

Frontend already consumes new keys; no new vitest needed (existing PipelineConsole tests
suffice for downstream behavior).

## §5 §6 8-trigger STOP self-check

| # | Trigger | Verdict |
|---|---------|---------|
| 1 | Framework 新加 | NEGATIVE (orchestration only) |
| 2 | Architecture 大改 | NEGATIVE (response-shape alignment, 0 new tables) |
| 3 | Strategy 改动 | NEGATIVE |
| 4 | 红线 5/5 触碰 | NEGATIVE (read-only) |
| 5 | PT 重启 gate | NEGATIVE |
| 6 | 新引擎 | NEGATIVE |
| 7 | Beat schedule 改 | NEGATIVE (read schedule, do not mutate) |
| 8 | Self-protection (§1/§4/§5/§6/§9/§14) | NEGATIVE |

All NEGATIVE → Inner-loop-A IMPLEMENT cleared.

## §6 §4.5 Value Verdict — IMPLEMENT

- Scope: smallest remaining D1 (finishes PN-001 + PN-003 status work — most fields
  already shipped; only 5 derived/mapped fields to add).
- 红线: 0 触碰 (read-only).
- 1 new helper function (`_gp_weekly_schedule_next`, ~10 lines) + 4 unit tests.
- Risk: low (response shape backward-compat via key-coexistence; no removals this iter).
- Banned-words clean: 0 真+X outside whitelist in this design.

## §7 Risk & Future Work

**Risk**:
- (R1) Hardcoded cron `0 22 * * 0` will drift if Beat schedule changes. Mitigation:
  the helper docstring cites `beat_schedule.py:53` SSOT; any change triggers grep.
  Long-term fix = Celery beat schedule introspection (out of scope this iter).
- (R2) `_gp_weekly_schedule_next()` doesn't account for SH→UTC DST. China does not
  observe DST → 0 actual drift risk.

**Future work** (not blocked):
- Pydantic `PipelineStatusResponse` model (replaces `dict[str, Any]` response).
- Drop legacy aliases after 1-sprint retention.
- Celery beat schedule introspection helper (replaces hardcoded cron).

## §8 Acceptance Criteria

- 4 new backend pytest pass.
- Existing pipeline tests (automation_level + pause) regression-clean.
- `ruff check && ruff format` clean.
- Smoke gate (`pytest -m smoke`) ≥ 61 passed.
- Frontend `PipelineStatus` interface fields all populated (no `undefined`) when checked
  against a mock backend response per §4 test 1.
- ADR-DRAFT row 14 appended.
- Banned-words self-check: 0 真+X outside whitelist.
