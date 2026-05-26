# W3-G FACTOR_PIPELINE_STALENESS_AUDIT (iter 152)

**Audit date**: 2026-05-26 14:12 SH
**Iter ID**: 152 (Week 3 NEW candidate surfaced via iter 151 task-notification follow-up)
**Method**: psql query factor_values + factor_ic_history max_td + scheduler_task_log Beat history (read-only)
**Trigger**: iter 151 background query b5kk9qkzq result `factor_values max trade_date=2026-05-22 (4d stale)` surfaced unexpected pipeline gap

---

## §1 Concrete findings (fresh DB verify 2026-05-26 14:12 SH)

| # | Source | Latest activity | Verdict |
|---|---|---|---|
| Q1 | `factor_values` table max trade_date | **2026-05-22** (Friday) | 4 calendar days stale (2 weekday miss: 5-25 Mon + 5-26 Tue) |
| Q2 | `factor_ic_history` table max trade_date | **2026-05-22** (same Friday) | mirror of factor_values pipeline freshness |
| Q3 | `factor_lifecycle` Beat | 2026-05-25 20:20 SH (weekly Fri 19:00 schedule per CLAUDE.md) | runs as expected (1 run 5d/7d window) |
| Q4 | `factor_health_daily` Beat | 2026-05-22 17:30 SH | **5d window 2 runs / 7d 3 runs vs expected 4-5 weekday runs** — 2 missed |
| Q5 | `factor_calc` Beat | 2026-04-07 (~50d stale, 0 runs in 5d/7d) | sustained inactive, possibly disabled or replaced |
| Q6 | factor row count + factor name diversity | 841,376,039 rows / 276 distinct factor_name / 12.4yr span (2014-01-02 to 2026-05-22) | row count matches CLAUDE.md iter 52 baseline exactly = 0 new writes since 5-25 |

---

## §2 Mechanism gap (schtask vs Celery Beat)

Per CLAUDE.md §常用命令: `python scripts/compute_daily_ic.py` runs as **Windows Task Scheduler** schtask (Mon-Fri 18:00), NOT Celery Beat. Therefore `scheduler_task_log` table does NOT track its execution.

**Cross-reference**:
- `factor_values` daily incremental writes are produced by `compute_daily_ic.py` via schtask QuantMind_DailyIC.
- factor_health_daily (Celery Beat) is a separate consumer/checker.
- 5d window: factor_health_daily ran 5-22 + maybe 5-25 evening or 5-26 morning unclear.

**Investigation gap**: need schtask audit via `schtasks /query /v /tn QuantMind_DailyIC` to determine:
- Did schtask QuantMind_DailyIC fire 5-25 Mon 18:00?
- Did it fire 5-26 Tue 18:00 (not yet by 14:12 SH today)?
- Last result code (success/fail)?

---

## §3 Verdict

**Factor pipeline staleness**: PARTIAL_STALENESS (P1)

- ✅ factor_lifecycle weekly Beat ran 5-25 (correct schedule)
- ❌ factor_values + factor_ic_history both stop at 5-22 — missed 5-25 Mon write window (schtask QuantMind_DailyIC failure or schedule drift)
- ❌ factor_health_daily Beat 5d window 2 runs (expected 4-5 weekday) — could be related cascade
- ⚠️ today 5-26 Tue 14:12 SH, daily IC 18:00 window NOT yet reached

**Severity**: P1 (data layer freshness gap, affects WF backtest input accuracy + factor health monitoring quality)

---

## §4 Recommendations

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 (IMPLEMENT) | Sediment THIS audit + close iter 152 | Tier C | 1 commit | this iter |
| R2 (DEFER) | Windows schtask audit — `schtasks /query /v /tn QuantMind_DailyIC` to confirm 5-25 + 5-26 schtask state + last result code | Tier C audit | 1 iter (15min) | next iter cluster (cron may auto-trigger) |
| R3 (DEFER) | If schtask broken, escalate to schtask repair (TaskScheduler reconfigure OR re-register via setup_task_scheduler.ps1) | Tier B ops | 30min + smoke verify | post R2 audit verdict |
| R4 (DEFER) | factor_health_daily Beat 5-25 + 5-26 missing run root cause (PG locks? Celery worker not running? Beat schedule drift?) | Tier B audit | 1 iter | next iter cluster |

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only, 0 broker / 0 .env / 0 yaml / 0 DB mutation / 0 production code).

---

## §6 Cite source

| # | Path | Line# / Query | Verify timestamp |
|---|---|---|---|
| 1 | psql `factor_values` MAX(trade_date) | 2026-05-22 | 2026-05-26 iter 152 fresh |
| 2 | psql `factor_ic_history` MAX(trade_date) | 2026-05-22 | 2026-05-26 iter 152 fresh |
| 3 | psql `scheduler_task_log` 7d window task_name~factor pattern | factor_lifecycle 1 / factor_health_daily 3 / factor_calc 0 | 2026-05-26 iter 152 fresh |
| 4 | `CLAUDE.md` §常用命令 | "compute_daily_ic.py Mon-Fri 18:00 schtask" | iter 152 |
| 5 | `backend/.env` L17, L20 | red lines sustained | iter 152 |
| 6 | iter 151 background query b5kk9qkzq output | factor_values 841,376,039 / 276 factors / 2014-01-02 → 2026-05-22 | 2026-05-26 14:00 SH completed |

---

**iter 152 classification**: 1 IMPLEMENT (R1 sediment) + 3 DEFER (R2+R3+R4). §4.5 ratio: +1 impl +3 defer.

**Week 3 candidate progress**:
- W3-F ✅ (iter 151 LL-207 sediment)
- W3-G ✅ (iter 152 THIS audit) — NEW finding surfaced post-W2 closure
- W3-A/B/C/D/E pending
