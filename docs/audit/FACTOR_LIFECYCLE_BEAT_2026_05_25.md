# Factor Lifecycle Beat Audit — 2026-05-25 (iter 100 TIER C)

**Verdict**: FAIL (Beat fires but writes 0 observable output)
**Audit window**: 2026-04-17 first scheduled fire → 2026-05-22 last Fri 19:00 (last expected fire before today 2026-05-25)
**Read-only**, no mutation. 红线 5/5 sustained (cash ¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / 0 trades since 4-29).

---

## §1 Beat schedule cite

- **File**: `backend/app/tasks/beat_schedule.py:113-120` (verified fresh 2026-05-25 19:24 SH)
- **Crontab**: `crontab(hour=19, minute=0, day_of_week="5")` → Fri 19:00 Asia/Shanghai
- **Task name**: `daily_pipeline.factor_lifecycle`
- **Last expected fire**: 2026-05-22 19:00 SH (last Fri)
- **Comment cite** (line 110-112): "Phase 3 MVP A / DEV_AI_EVOLUTION V2.1 §3.1: active↔warning / warning→critical"

## §2 Task implementation locate

- **Celery task definition**: `backend/app/tasks/daily_pipeline.py:1059-1109` (`factor_lifecycle_task`, fresh verify 2026-05-25 19:24)
- **Body delegates to**: `scripts/factor_lifecycle_monitor.py::run()` (lazy sys.path inject `scripts/` + `backend/`)
- **Engine layer (pure rules)**: `backend/engines/factor_lifecycle.py:60-127` (`evaluate_transition`)
- **Output destination** (per V2.1 §3.1 spec): UPDATE `factor_registry.status` + INSERT/UPDATE `factor_lifecycle` table
- **Schema-level evidence — factor_lifecycle table**: 6 rows, last `updated_at=2026-04-16 20:18:09` (39 days stale as of 2026-05-25 19:24)
- **celery_app.py imports list** includes `app.tasks.daily_pipeline` (line 84) — task IS registered now (post 4-17 KeyError fix)

## §3 Logs evidence

- **celery-stdout.log** (start 2026-04-03 17:32, last write 2026-05-24 23:08):
  - `daily_pipeline.factor_lifecycle` mention: **only** 2026-04-17 19:00 fire → `ERROR Received unregistered task of type 'daily_pipeline.factor_lifecycle'` + KeyError (cite `logs/celery-stdout.log:11183, 11193, 11200`)
  - **0 subsequent fires logged** (after register fix, no Beat-dispatch trace; expected ~5-6 fires 2026-04-24 / 5-01 / 5-08 / 5-15 / 5-22 within retention window)
- **celery-beat-stdout.log** (start **2026-05-20 17:54**, covers 5-22 fire window): 0 `factor_lifecycle` / `factor-lifecycle-weekly` mention
- **logs/factor_lifecycle.log** (last write 2026-05-25 10:53): misnamed sink — contains pytest output + live_trading_guard + llm_cost_audit log, **NO Beat task output**
- **5-22 19:00 fire**: zero log evidence in beat or worker stdout

## §4 DB evidence

```
scheduler_task_log task_name DISTINCT (ILIKE %lifecycle% OR %factor_health%):
  → only 'factor_health_daily' (Mon-Fri 17:30, DIFFERENT task — from scripts/factor_health_check.py)
  → 0 row with task_name in {factor_lifecycle, daily_pipeline.factor_lifecycle, factor-lifecycle-weekly}

factor_lifecycle table: 6 rows, last updated 2026-04-16 (39 days stale)
  reversal_20=retired / amihud_20=retired / dv_ttm=active / volatility_20=active / turnover_mean_20=active / bp_ratio=active

factor_health_log: 5 rows ALL on 2026-04-05 (DEAD table 50 days stale, separate orphan)
```

(Cite: `psql -U xin -d quantmind_v2`, fresh query 2026-05-25 19:25 SH)

## §5 Findings

**P0** — Beat fires but produces ZERO output for 5+ scheduled cycles (4-24, 5-01, 5-08, 5-15, 5-22):
  - No row in scheduler_task_log for task_name='daily_pipeline.factor_lifecycle' (and no alias variant)
  - No mutation to factor_lifecycle table since 4-16 (39 days)
  - No log trace in celery-stdout.log post 4-17 register fix
  - Either: (a) Beat schedule entry not loaded by current Beat process; OR (b) task runs but writes nowhere observable; OR (c) early-exit branch (non-trading-day guard) consumes silently
  - **Cite**: scheduler_task_log query + factor_lifecycle.updated_at + celery-stdout.log:11183

**P1** — factor_health_log orphan dead table (5 rows, all 2026-04-05): leftover from earlier Phase 3 prototype not pruned, distinct from factor_lifecycle. ADR-094 PMS retirement style sunset candidate.

**P2** — logs/factor_lifecycle.log filename misleading: actually a generic logger sink for pytest + live_trading_guard + llm_cost output, NOT the Beat task log. Naming confusion blocks ops triage.

## §6 Recommendations

1. **Immediate (next iter)**: Manual fire `celery -A app.tasks.celery_app call daily_pipeline.factor_lifecycle` and inspect return + DB diff. If task succeeds but writes nothing → run() function path defect. If task fails → exception in factor_lifecycle_monitor.py.
2. **Verify Beat process loaded post 4-17 schedule patch**: `celery -A app.tasks.celery_app inspect scheduled` to confirm factor-lifecycle-weekly is registered in active Beat schedule (LL-097 X9 sustained — schedule edits w/o Beat restart leave stale schedule).
3. **Wire scheduler_task_log audit row** inside `factor_lifecycle_task` body (sustained pattern from `factor_health_daily`) — current task has no audit trail, making P0 detection silent.
4. **Sunset factor_health_log dead table** via ADR or comment + DROP per ADR-094 PMS pattern.
5. **Rename logs/factor_lifecycle.log** to logs/general-pytest.log (or split sinks) to free the canonical name for true Beat output.

## §7 Cite sources (4-element)

| Claim | Path | Line# | Section | Fresh verify |
|---|---|---|---|---|
| Beat crontab Fri 19:00 | `backend/app/tasks/beat_schedule.py` | 113-120 | "factor-lifecycle-weekly" entry | 2026-05-25 19:24 SH |
| Task body delegates to monitor | `backend/app/tasks/daily_pipeline.py` | 1059-1109 | `factor_lifecycle_task` def | 2026-05-25 19:24 SH |
| 4-17 KeyError unregistered | `logs/celery-stdout.log` | 11183, 11193, 11200 | First fire | 2026-05-25 19:24 SH grep |
| factor_lifecycle 39d stale | psql scheduler_task_log + factor_lifecycle | n/a (DB) | MAX(updated_at)=2026-04-16 | 2026-05-25 19:25 SH |
| Beat-stdout 5-20 onwards 0 hit | `logs/celery-beat-stdout.log` | start line 1 ts | LocalTime → 2026-05-20 17:54 | 2026-05-25 19:25 SH |
| celery_app imports daily_pipeline | `backend/app/tasks/celery_app.py` | 84 | imports list | 2026-05-25 19:24 SH |
| Engine layer pure rules | `backend/engines/factor_lifecycle.py` | 60-127 | `evaluate_transition` | 2026-05-25 19:24 SH |
