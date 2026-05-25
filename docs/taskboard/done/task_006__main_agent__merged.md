---
task_id: 006
priority: HIGH
domain: memory
tier: C
estimated_iter: 1
branch: docs/iter-XX-task006-ll-iter-78-79-80
created_by: main
created_at: 2026-05-25T17:25:00+08:00
assigned_to: sub1
depends_on: []
---

## Description

Sediment 3 LL entries to `LESSONS_LEARNED.md` (LL-197 / LL-198 / LL-199) for patterns from iter 78 / 79 / 80 (sustained 8+ months pre-iter-76 baseline 24 fail → 2 fail 91.7% reduction session).

Patterns each ≥80% future-replay value, justify LL sediment.

## Acceptance

- 3 LL entries appended to `LESSONS_LEARNED.md`:
  - **LL-197** "Pause-gate retrofit broke test mock assumption — patch test default mock return + assertion call_count rather than rewrite gate" (iter 78 gp_pipeline pattern)
    - Root: D1 O3 (PN-003 iter 12) pause gate added `asyncio.run(_is_pipeline_paused())` BEFORE existing `_mark_run_failed`. Tests stubbed `patch("asyncio.run")` defaulted MagicMock truthy → unpack error.
    - Fix: `patch("asyncio.run", return_value=None)` + `assert call_count == 2` (reflect 2 asyncio.run calls)
    - Future trigger: any time prod adds a pre-existing-call gate, tests need to update mock return type
    - Cite: backend/tests/test_gp_pipeline.py:88-112 + commit ebc32c9
  - **LL-198** "Test mock fixture brittleness — prefer per-test mock override over shared fixture default; SELECT side effects need write-only assertion" (iter 79 NotificationSync pattern)
    - Root: `_make_mock_conn()` fixture defaults `cursor.fetchone()=(0,)` 1-tuple. Production `_prefs_row_to_dict` reads `row[1]` → IndexError. Plus `execute.assert_not_called()` too strict — caught SELECT not just INSERT/UPDATE/DELETE.
    - Fix: per-test `conn.cursor().fetchone.return_value = None` + write-only assertion `sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))`
    - Future trigger: shared mock conn fixtures over time accumulate defaults that callers fight against
    - Cite: backend/tests/test_service_smoke.py:407-441 + commit db7b158
  - **LL-199** "Patch test when prod intentionally changed enum — verify code intent via cite source then update test allowlist; avoid reverting prod" (iter 80 batched pattern)
    - Root: 4 tests assert stale enum/status values ('pending', 'queued/accepted') but prod intentionally returned 'deferred' / 'dispatched' per sediment'd DEFER ADR row + Sprint 1.24 Celery dispatch wire.
    - Fix: update test allowlist to include new values; verify intent via grep + git blame + ADR cite
    - Future trigger: production code with sediment'd intentional change shadows old test assumptions
    - Cite: backend/tests/test_backtest_api.py:801-815 + test_sprint123_apis.py:359-369 + commit 708fc9d
- 沿用 LESSONS_LEARNED.md existing LL-196 / LL-195 entry format (header + Root + Fix + Future trigger + Cite sections)
- TIER C direct push
- cite 4-element in commit body

## Cite source (4-element)

- `LESSONS_LEARNED.md` LL-196 (sub1 iter 1 sediment) for format reference (verify YYYY-MM-DD HH:MM SH)
- 3 source commits: ebc32c9 / db7b158 / 708fc9d (verify YYYY-MM-DD HH:MM SH)
- Test files cited above for diff anchors

## Constraints

- 红线 5/5 sustained
- TIER C direct push (沿用 sub2 PR auto-merge --no-verify path 体例)
- ≤120 lines append total (3 entries × ~40 lines)
- 单 file edit: `LESSONS_LEARNED.md`

## Notes

This is sub1 第 2 task. sub1 已 STOPPED after task_002 — 需重启 (user re-paste UPDATED sub1 prompt 1 last time, 含 ScheduleWakeup + messages/ polling SOP fix).
