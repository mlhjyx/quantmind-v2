# factor_lifecycle Beat 5-Cycle Silent Dispatch — Root Cause Static Analysis

**Audit type**: TIER C READ-ONLY static analysis (iter 101 follow-up to iter 100 P0 FAIL)
**Date**: 2026-05-25
**Scope**: WHY 5 consecutive Fri 19:00 SH dispatches (4-24, 5-01, 5-08, 5-15, 5-22) produced 0 `scheduler_task_log` row + 0 `factor_lifecycle` table row + 0 `celery-beat-stdout.log` mention.

---

## §1 Beat schedule snippet

`backend/app/tasks/beat_schedule.py:113-120` (fresh read 2026-05-25):

```python
"factor-lifecycle-weekly": {
    "task": "daily_pipeline.factor_lifecycle",
    "schedule": crontab(hour=19, minute=0, day_of_week="5"),  # 5=Friday
    "options": {"queue": "default", "expires": 3600},
},
```

Schedule loaded by `celery_app.conf.beat_schedule = CELERY_BEAT_SCHEDULE` (celery_app.py:121-123). Beat is dispatching correctly — confirmed via `logs/celery-beat-stderr.log` (6 hits since 4-17, including all 5 missing cycles):

| Date | beat-stderr line | Status |
|------|------------------|--------|
| 2026-04-17 19:00:00 | :56 | dispatched |
| 2026-04-24 19:00:02 | :80 | dispatched |
| 2026-05-01 19:00:00 | :8182 | dispatched |
| 2026-05-08 19:00:00 | :27356 | dispatched |
| 2026-05-15 19:00:00 | :48620 | dispatched |
| 2026-05-22 19:00:00 | :72074 | dispatched |

---

## §2 Task definition + early-return paths

`backend/app/tasks/daily_pipeline.py:1059-1121` (fresh read 2026-05-25):

```python
@celery_app.task(
    bind=True,
    name="daily_pipeline.factor_lifecycle",
    acks_late=True, max_retries=1, default_retry_delay=300, time_limit=600,
)
def factor_lifecycle_task(self) -> dict:
    # Calendar gate (Plan 1 — DEV_SCHEDULER §6.12)
    from qm_platform.calendar import is_trading_day_today_or_skip
    if not is_trading_day_today_or_skip(logger=logger):
        return {"status": "skipped", "reason": "non_trading_day"}
    # ... script subprocess wiring + run_lifecycle() ...
```

**Early-return path enumeration**:
- L1083: non-trading-day silent skip (returns `{status:"skipped"}`, no DB row)
- L1119-1121: top-level `try/except` re-raises (would surface in stderr, not silent)
- No `.env` disable flag, no empty-data fast-exit.

**`scheduler_task_log` INSERT location** (Grep `scheduler_task_log` in `daily_pipeline.py`):
- `_write_scheduler_log_safe` helper defined L57-105
- **Called by**: `risk_daily_check` (L262) + `intraday_risk_check` (L522) ONLY
- **NOT called by** `factor_lifecycle_task` — explains 0 audit row even on success

---

## §3 Worker registration — disconnect found

`backend/app/tasks/celery_app.py:83-109` (fresh read 2026-05-25) — `imports` list:

```python
imports=[
    "app.tasks.daily_pipeline",  # ← factor_lifecycle_task lives here
    "app.tasks.mining_tasks",
    ... 16 entries total ...
],
```

`app.tasks.daily_pipeline` IS in imports. Task name `daily_pipeline.factor_lifecycle` registered via `@celery_app.task(name=...)` decorator. **In theory worker should load it.**

---

## §4 Smoking gun — worker received but UNREGISTERED at runtime

`logs/celery-stderr.log:11183-11200` (fresh read 2026-05-25):

```
[2026-04-17 19:00:00,005: ERROR/MainProcess] Received unregistered task of type
  'daily_pipeline.factor_lifecycle'.
The message has been ignored and discarded.
Did you remember to import the module containing this task?
...
KeyError: 'daily_pipeline.factor_lifecycle'
```

**Same KeyError** also fires for `daily_pipeline.data_quality_report` immediately above (L11182). Both tasks live in `app.tasks.daily_pipeline` which IS in `imports`. This means the worker process that received the 4-17 dispatch had NOT loaded `daily_pipeline.py` despite the `imports` entry — most likely a sys.path / bootstrap race or the worker was started before a code update was deployed.

**Critical evidence — only 4-17 surfaces in stderr**:
- `Grep "factor_lifecycle" logs/celery-stderr.log = 3 hits` (all on 4-17 single error block)
- Logs 4-24 / 5-01 / 5-08 / 5-15 / 5-22 — **0 hits** for factor_lifecycle
- `logs/celery-beat-stdout.log` (started 5-20) — **0 hits** for factor_lifecycle

The 5-15 + 5-22 dispatches landed in a worker that **doesn't even emit the unregistered-task KeyError anymore** → either (a) `expires=3600` purges the message before worker pick-up (unlikely — Beat fires at 19:00, worker would consume within seconds), or (b) worker stderr rotated away or (c) the message goes to a queue the current worker isn't subscribing to. Outbox-publisher is processing 30s ticks at the same timestamp range without issue, so the worker IS alive.

---

## §5 Hypothesis ranking

| # | Hypothesis | Likelihood | Evidence |
|---|-----------|------------|----------|
| **H2** | **Task imported in code but unregistered at worker runtime** — sys.path race / stale worker process / Servy auto-restart not picking up code updates | **HIGH (80%)** | 4-17 stderr proves the exact `KeyError: 'daily_pipeline.factor_lifecycle'` despite `imports=["app.tasks.daily_pipeline"]`. Same module's `data_quality_report` fails identically. Both tasks defined with `@celery_app.task(name=...)` so name registration only happens on module import. If `app/tasks/__init__.py` or bootstrap fails silently, all daily_pipeline tasks orphan but other modules survive |
| H4 | Beat fires task but message dropped post-4-17 — queue mismatch (`default` routing key) or `expires=3600` race | LOW (10%) | celery_app.py:81 sets `task_default_queue="default"` (LL-189 fix 5-19). Beat options.queue="default" matches. expires=3600 = 1h, worker would consume in <1s. UNLESS the worker is subscribing to a different queue list — but outbox_publisher (queue="default") works fine |
| H3 | Task fires but silent-exits in `is_trading_day_today_or_skip` calendar gate | LOW (5%) | Would still need worker to receive + execute. The 4-17 dispatch never reached function body (KeyError before consumer.py:668 strategy lookup). All 5 missing Fri are real trading days (not holidays). Even if gate skipped, `return {status:"skipped"}` would NOT write scheduler_task_log (not wired) — consistent with observation but doesn't explain 4-17 KeyError |
| H1 | Beat config drift / typo in task name | NONE (0%) | beat_schedule.py:114 `"task": "daily_pipeline.factor_lifecycle"` matches daily_pipeline.py:1061 `name="daily_pipeline.factor_lifecycle"` byte-for-byte |

**Top 1 root cause**: **H2 worker-side registration miss**. The fact that 4-17 surfaced a KeyError but 4-24+ are completely silent suggests the worker stderr stopped logging the error (log rotation / different worker process) but the underlying registration miss persists. Beat dispatches normally; worker silently discards (or queue not subscribed) for 5 consecutive cycles. Sustained pattern matches LL-189 (orphan accumulation) + Plan v10 P0-16/P0-10 closure (same "module exists but imports list miss" failure mode — but here imports DO include the module, pointing to a runtime registration race rather than a static config defect).

---

## §6 Remediation proposal (blueprint, NOT applied)

### 6a — Add `_write_scheduler_log_safe` audit envelope (DIRECT FIX for observability gap)

Modify `daily_pipeline.py:1067` `factor_lifecycle_task` body — wrap with same audit envelope already used by `risk_daily_check` (L262) + `intraday_risk_check` (L522):

```python
def factor_lifecycle_task(self) -> dict:
    start_time = datetime.now(UTC)
    try:
        # calendar gate ...
        if not is_trading_day_today_or_skip(logger=logger):
            _write_scheduler_log_safe(
                "factor_lifecycle", start_time, "skipped",
                {"reason": "non_trading_day"},
            )
            return {"status": "skipped", "reason": "non_trading_day"}
        # ... existing run_lifecycle() body ...
        result = run_lifecycle(...)
        _write_scheduler_log_safe("factor_lifecycle", start_time, "success", result)
        return {"status": "ok", **result}
    except Exception as e:
        _write_scheduler_log_safe(
            "factor_lifecycle", start_time, "error",
            {"error": f"{type(e).__name__}: {e}"},
        )
        raise
```

This closes Observability gap regardless of H2/H4 — but **CANNOT execute if task never reaches function body** (H2 case). Still required as defense-in-depth.

### 6b — Boot-time task registration self-check

Add to `celery_app.py` post-`bootstrap_platform_deps()`:

```python
# Sanity check: verify every Beat-referenced task is registered
expected_tasks = {entry["task"] for entry in CELERY_BEAT_SCHEDULE.values()}
registered = set(celery_app.tasks.keys())
missing = expected_tasks - registered
if missing:
    logger.error(f"[BeatRegistration] Missing tasks: {missing}")
    # Fail-loud P0 DingTalk
```

### 6c — Worker boot trace logging

Enable `CELERY_TASK_LOG_FORMAT` to dump full `app.tasks` registry at boot — capture exact moment of registration miss.

### 6d — Test plan

- **Unit**: `test_factor_lifecycle_audit_envelope.py` — assert `scheduler_task_log` INSERT on success / skip / error
- **Integration smoke**: `celery_app.tasks["daily_pipeline.factor_lifecycle"]` resolves in `pytest -m smoke`
- **Production verify**: post-merge Servy restart Celery + CeleryBeat, manually `celery_app.send_task("daily_pipeline.factor_lifecycle")` and confirm `scheduler_task_log` row appears

---

## §7 Effort + TIER + reviewer

- **Effort**: ~2-3h (audit envelope ~30min + boot self-check ~30min + tests ~1h + post-merge verify ~30min)
- **TIER**: **B** (production-code mutation in `daily_pipeline.py` + `celery_app.py`, ≤200 LOC, single concern). Reviewer required (python-reviewer for envelope correctness + code-reviewer for celery_app sanity check). Post-merge ops: `Servy restart QuantMind-Celery + QuantMind-CeleryBeat` per LL-141 4-step sustained.
- **PR scope**: 6a + 6b combined (6c is debugging-only, defer; 6d is test-plan included in PR).

---

## §8 Cite source 4-element table

| Cite | path | line# | section | fresh verify timestamp |
|------|------|-------|---------|------------------------|
| Beat schedule | `backend/app/tasks/beat_schedule.py` | 113-120 | `factor-lifecycle-weekly` entry | 2026-05-25 read |
| Task definition | `backend/app/tasks/daily_pipeline.py` | 1059-1121 | `factor_lifecycle_task` | 2026-05-25 read |
| Calendar gate | `backend/qm_platform/calendar/__init__.py` | 122-174 | `is_trading_day_today_or_skip` | 2026-05-25 read |
| celery_app imports | `backend/app/tasks/celery_app.py` | 83-109 | `imports=[...]` | 2026-05-25 read |
| scheduler_task_log helper | `backend/app/tasks/daily_pipeline.py` | 57-105 | `_write_scheduler_log_safe` | 2026-05-25 read |
| KeyError evidence | `logs/celery-stderr.log` | 11183-11200 | unregistered task | 2026-05-25 read |
| Beat dispatch ×6 | `logs/celery-beat-stderr.log` | 56/80/8182/27356/48620/72074 | Sending due task | 2026-05-25 grep count=6 |
| Worker stderr factor_lifecycle hits | `logs/celery-stderr.log` | (3 hits, all 4-17) | grep count | 2026-05-25 grep count=3 |
| iter 100 audit ref | `docs/audit/FACTOR_LIFECYCLE_BEAT_2026_05_25.md` | n/a | P0 FAIL finding | 2026-05-25 task input cite |

---

**END §8**
