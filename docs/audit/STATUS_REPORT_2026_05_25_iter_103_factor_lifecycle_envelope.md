# iter 103 — factor_lifecycle audit envelope + Beat registration self-check

**Date**: 2026-05-25
**Branch**: `fix/iter-103-factor-lifecycle-audit-envelope`
**TIER**: B (backend production code, single concern)
**Reviewer**: pending Task agent spawn (`oh-my-claudecode:code-reviewer`)
**Sustained**: iter 100 audit P0 FAIL → iter 101 root cause (H2 worker registration)
→ **iter 103 fix** (this PR).

---

## §1 Summary

Close **5 cycle silent dispatch** P0 surfaced iter 100. Root cause iter 101 §5 = H2
(worker-side task registration miss). Two defenses applied:

| Defense | File | LOC | Effect |
|---------|------|-----|--------|
| **§6a audit envelope** | `backend/app/tasks/daily_pipeline.py:1067-1144` | +51/-28 | Every `factor_lifecycle_task` invocation → `scheduler_task_log` row (success / skipped / error). Mirrors `risk_daily_check` L262-477 canonical try/finally. |
| **§6b boot self-check** | `backend/app/tasks/celery_app.py:137-186` | +53 | `worker_init` + `beat_init` signal-time call to `_verify_beat_task_registration()` raises `RuntimeError` if any Beat-scheduled task name unregistered. Calls `import_default_modules()` first for self-sufficiency. |
| **8 tests** | `backend/tests/test_factor_lifecycle_audit_envelope.py` (NEW) | +180 | 4 envelope path tests + 4 boot-check tests. All PASS. |

**Net**: +234 / -28 = **+206 LOC across 3 files** (1 new).

---

## §2 §5 Hard carve-out check

All NEGATIVE — no broker / no `.env` mutation / no DB row direct edit / no governance
SSOT retroactive / no Architecture-level new design. Adds observability + early-fail,
no behavior change to existing successful task path.

## §3 §6 8-trigger Architecture STOP self-check

All 8 NEGATIVE (read-only audit table + signal hook, no boundary mutation). Feature-tier.

## §4 Red lines (sustained pre + post)

- `backend/.env` LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 (verified pre-iter)
- `trade_log` post-2026-04-29 rows = 0 (psql verified iter 103 §1 step 2)
- cash ¥993,520.66 / 0 持仓 (sustained from session summary 5-25 iter 99)

## §5 Tests run

- **New file** `backend/tests/test_factor_lifecycle_audit_envelope.py`: **8 PASS / 0 FAIL** (0.34s)
- **Sibling** `backend/tests/test_calendar_gate.py`: **14 PASS / 0 FAIL** (0.18s, all 22 PASS combined)
- **Mutation guard**: `test_envelope_uses_canonical_helper_name` asserts `_write_scheduler_log_safe` still callable → renaming/inlining surfaces in CI
- **Boot self-check positive**: `test_verify_helper_passes_when_all_present` confirms production app registers all 20 Beat tasks
- **Boot self-check negative**: `test_verify_helper_raises_on_missing` confirms RuntimeError raised on synthetic fake schedule
- **Smoke (pre-push gate)**: pending background completion

## §6 Post-merge ops (LL-141 sustained 4-step)

After merge to main:

1. `powershell -File scripts/service_manager.ps1 restart celery` (graceful 30s)
2. `powershell -File scripts/service_manager.ps1 restart celery-beat`
3. Tail `logs/celery-stdout.log` for `[BeatRegistration] all 20 Beat-scheduled tasks registered`
4. **5-29 Fri 19:00 SH** observe: confirm `scheduler_task_log` 1 new row task_name='factor_lifecycle' (success or skipped per calendar)

If Beat registration check FAILS at restart → worker won't start → Servy AutoRestart loop
→ SignalR / Servy crash-loop notifier surfaces immediately (vs 5-cycle silent drift).

## §7 Cite source (4-element)

| Cite | path | line# | section | fresh verify timestamp |
|------|------|-------|---------|------------------------|
| Audit envelope (new) | `backend/app/tasks/daily_pipeline.py` | 1067-1144 | `factor_lifecycle_task` | 2026-05-25 ~20:15 SH |
| Boot self-check (new) | `backend/app/tasks/celery_app.py` | 137-186 | `_verify_beat_task_registration` | 2026-05-25 ~20:15 SH |
| New tests | `backend/tests/test_factor_lifecycle_audit_envelope.py` | 1-203 | full file | 2026-05-25 ~20:25 SH |
| Canonical pattern source | `backend/app/tasks/daily_pipeline.py` | 262-477 | `risk_daily_check_task` | 2026-05-25 ~20:00 SH |
| `_write_scheduler_log_safe` helper | `backend/app/tasks/daily_pipeline.py` | 57-105 | helper def | 2026-05-25 ~20:00 SH |
| iter 100 P0 surface | `docs/audit/FACTOR_LIFECYCLE_BEAT_2026_05_25.md` | n/a | full doc | 2026-05-25 task input |
| iter 101 root-cause | `docs/audit/FACTOR_LIFECYCLE_ROOT_CAUSE_2026_05_25.md` | 117-170 | §6 remediation | 2026-05-25 ~20:10 SH |
| LL-202 / LL-203 | `LESSONS_LEARNED.md` | (TBD post-LL append) | iter 102 sediment | 2026-05-25 task input |

## §8 Risk + rollback

- **Risk**: Worker startup raise `RuntimeError` on missing task could cause production
  Celery service flap. Mitigation: import_default_modules() FORCES imports first, so
  the check only fires if the module-level import is broken — same failure that today
  surfaces as silent KeyError at Beat dispatch time (worse). Net = surface earlier.
- **Rollback**: 单 commit revert — `git revert <sha>` restores prior behavior.
  scheduler_task_log row INSERTed during the lived window are append-only audit, no
  data corruption risk.

## §9 X10 self-check

- 0 forward-progress offer in commit / PR body
- 0 schedule agent / paper-mode 5d / cutover language
- merge → iter 104 picks next candidate (§v9.4 sustained)
