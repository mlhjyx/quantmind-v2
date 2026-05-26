# W2-C OUTBOX_PUBLISHER_DRIFT — V3 §S6 4-domain audit (iter 145)

**Audit date**: 2026-05-26
**Iter ID**: 145 (L4+R loop, post W2-A/F/E closure cluster)
**Method**: psql query (4 actual tables vs design) + scheduler_task_log evidence + beat_schedule.py grep
**Trigger**: L4R_AUDIT_WEEK2_MANIFEST W2-C (Step C3 1/18 long-tail follow-up per Session 50 handoff)

---

## §1 Concrete findings (6 questions)

| # | Question | Finding | Verdict |
|---|---|---|---|
| Q1 | outbox-publisher-tick 30s Beat firing? | Beat **REGISTERED** at `backend/app/tasks/beat_schedule.py:93` (task=`outbox_publisher.outbox_publisher_tick`); however `scheduler_task_log` returns **0 rows** for any `%outbox%` task_name pattern. Either Beat task doesn't write to scheduler_task_log OR Beat fires but task body silent-skips logging. | **GAP** — observability layer missing for outbox Beat |
| Q2 | 4-domain outbox backlog per table? | psql `pg_tables WHERE tablename LIKE '%outbox%'` returns **only `event_outbox`**. `audit_outbox`/`trade_outbox`/`risk_event_outbox` DON'T EXIST in DB. | **CRITICAL drift** — V3 §S6 design specifies 4 domains; DDL has 1/4 |
| Q3 | Stream consumer PIDs alive? | NOT_QUERIED (Redis check deferred) | — |
| Q4 | PR #169 emergency_close cascade outbox row drained? | Can't query `audit_outbox` (doesn't exist); 4-29 trade rows in trade_log only (not outbox-tracked) | Step C3 audit chain 1/18 long-tail UNDIAGNOSABLE via outbox path |
| Q5 | 30s tick + 4-domain integration test still PASSING? | `test_outbox_4domain_integration.py` exists per manifest cite but tests run against missing tables would FAIL or skip — NOT_QUERIED (smoke green sustained so likely conditional skip) | NEEDS pytest targeted run |
| Q6 | `qm:*` Redis stream maxlen=10000 enforced? | NOT_QUERIED (Redis XLEN check deferred) | — |

---

## §2 Cross-source verification

**event_outbox真实 state** (psql 2026-05-26 iter 145):
- 5 total rows (oldest 2026-05-17 15:22:59, newest 2026-05-22 16:31:20)
- 0 unpublished (`published_at IS NULL`)
- 0 stuck rows >24h

**Beat schedule for `outbox-publisher-tick`** (`backend/app/tasks/beat_schedule.py:89-95` fresh verify):
- task: `app.tasks.outbox_publisher.outbox_publisher_tick`
- schedule: 30s tick per V3 §S6 design
- registered cleanly

**Recent scheduler_task_log activity 5d window** — 10 tasks executing, NONE outbox-related:
- news_ingest_rsshub 22 success / 3 error
- announcement_ingest 21 success
- news_ingest_5_sources 21 success / 4 error
- pending_monthly_rebalance 4 executed / 2 expired
- fundamental_context_ingest 3 success
- pt_audit 3 success
- factor_health_daily 2 warning

---

## §3 Verdict

**Outbox publisher state**: PARTIAL_DRIFT

- ✅ event_outbox single domain operational (no backlog, 0 stuck)
- ❌ 3/4 domains missing (audit_outbox / trade_outbox / risk_event_outbox not in DDL)
- ❌ Observability gap: outbox-publisher-tick has 0 scheduler_task_log rows (Beat fires but no log sink, OR Beat broken silently)

**Severity**: P1 (sustained design-vs-impl drift)

---

## §4 Recommendations (defer pattern per /loop §4.5 honest)

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 | DEFER 3-domain DDL ship (audit/trade/risk_event outbox) — paper mode 0 stuck row sustained so no urgent breach | Tier B Wave 5 | ~150 LOC SQL + service | post PT restart trigger |
| R2 | Add scheduler_task_log writer to `outbox_publisher_tick` (observability gap close) | Tier C | ~30 LOC | next iter (smallest-first) |
| R3 | Sediment LL-XXX "design doc 4-domain ≠ DDL truth; W2-C audit Q2 0/3 missing" anti-pattern | Tier C doc | 1 LL append | next iter cluster |
| R4 | Step C3 1/18 long-tail (PR #169 emergency_close audit chain) — alternative audit path via trade_log direct (audit_outbox can't help since doesn't exist) | Tier C audit | 1 iter | when convenient |

---

## §5 §6 8-trigger STOP check verdict

All NEGATIVE (audit-only, 0 broker / 0 .env / 0 yaml / 0 DB mutation / 0 production code).

---

## §6 Cite source (sustained §v9.7 mandate)

| # | Path | Line# | Verify timestamp |
|---|---|---|---|
| 1 | `backend/app/tasks/beat_schedule.py` | L89-95 | 2026-05-26 iter 145 |
| 2 | `D:\quantmind-v2\backend\.env` | L17, L20 | iter 145 red-line sustained |
| 3 | psql `pg_tables WHERE tablename LIKE '%outbox%'` | runtime | 2026-05-26 iter 145 fresh |
| 4 | psql `event_outbox` COUNT + MIN/MAX created_at | runtime | 2026-05-26 iter 145 fresh |
| 5 | psql `scheduler_task_log` 5d window grouped | runtime | 2026-05-26 iter 145 fresh |
| 6 | `docs/audit/L4R_AUDIT_WEEK2_MANIFEST_2026_05_26.md` | §2 W2-C row | 2026-05-26 iter 145 |
| 7 | `docs/QUANTMIND_V2_DDL_FINAL.sql` + `backend/migrations/` | 0 grep hits for 3 missing outbox | 2026-05-26 iter 145 fresh |

---

**iter 145 ARCHIVE/IMPLEMENT/DEFER classification**: DEFER × 3 (R1+R3+R4) + IMPLEMENT × 1 (R2 small) for next iter cluster planning.
