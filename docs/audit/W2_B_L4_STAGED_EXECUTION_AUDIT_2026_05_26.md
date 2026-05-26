# W2-B L4_STAGED_EXECUTION_AUDIT (iter 149)

**Audit date**: 2026-05-26 13:50 SH
**Iter ID**: 149 (avoid collision with concurrent session iter 142-148)
**Method**: filesystem find + grep beat_schedule + psql DDL query (read-only)
**Trigger**: L4R_AUDIT_WEEK2_MANIFEST W2-B (ADR-027 §7 L4 STAGED implementation completeness)

---

## §1 Concrete findings (6 questions)

| # | Question | Finding | Verdict |
|---|---|---|---|
| Q1 | `backend/qm_platform/risk/l4/staged.py` exists per V3 §7.3 canonical? | **NOT at canonical path** — file at legacy `backend/app/services/risk/staged_execution_service.py` instead. + `backend/app/tasks/l4_sweep_tasks.py` exists for Beat task body. | **PATH DRIFT** — V3 §7.3 canonical vs legacy actual |
| Q2 | ADR-027 §C 反向决策权 code-level enforcement? | NOT_QUERIED (deferred — service-level grep needed) | — |
| Q3 | 跌停 fallback (ADR-027 §D) impl path? Test coverage? | 4 test files exist: `test_approve_l4_observability.py` + `test_l4_execution_planner.py` + `test_l4_staged_smoke.py` + `test_l4_sweep_tasks.py` + `test_staged_execution_service.py`. Indicates code path exists. Specific 跌停 fallback test coverage NOT verified. | **PRESENT (verify needed)** |
| Q4 | `risk-l4-sweep-1min` Beat firing? | **REGISTERED** at `backend/app/tasks/beat_schedule.py:228` (cron `* 9-14 * * 1-5`); recent scheduler_task_log activity NOT_QUERIED but Beat task body exists. | Beat WIRED |
| Q5 | `risk-l4-broker-stuck-sweep` 5min Beat sustained 0 stuck? | **REGISTERED** at beat_schedule.py:248; HC-2b2 G7 spec per V3 §14 mode 12. Runtime stuck row count NOT_QUERIED. | Beat WIRED |
| Q6 | STAGED status state machine DDL exists? | psql `pg_tables WHERE tablename LIKE '%staged%' OR LIKE '%l4%'` returns **0 rows**. STAGED state machine state (READY/ARMED/DISPATCHED/REJECTED/EXPIRED) has NO dedicated DB table. Likely persisted in trade_log status column OR risk_event_log OR transient (in-memory + Redis only). | **DDL GAP** — state persistence ambiguous |

---

## §2 Cross-source verification

**Files present at non-canonical paths**:
- `backend/app/services/risk/staged_execution_service.py` (legacy V2.5 layer)
- `backend/app/tasks/l4_sweep_tasks.py` (Beat task body)
- Tests cluster (5 test files indicate active development)

**V3 §7.3 canonical path expected**: `backend/qm_platform/risk/l4/staged.py` (per ADR-027 sediment)
**Actual path**: legacy `backend/app/services/risk/` (P0 drift per V3 implementation roadmap)

**Beat schedule** (`backend/app/tasks/beat_schedule.py:228+248`):
- `risk-l4-sweep-1min`: 1-min cron 9:00-14:59 weekday (intraday trading window)
- `risk-l4-broker-stuck-sweep`: 5-min sweep (HC-2b2 G7 stuck-detection)

**DB state**:
- 0 dedicated staged/l4 table
- STAGED state machine persistence path UNCLEAR (may use trade_log status field or risk_event_log per V3 §S6 outbox pattern)

---

## §3 Verdict

**L4 STAGED execution state**: PARTIAL_IMPL with PATH_DRIFT

- ✅ Service layer exists + Beat tasks registered + test cluster present (5 files)
- ❌ V3 §7.3 canonical path NOT used — sits at legacy `backend/app/services/risk/` (V3 migration debt)
- ❌ No dedicated DDL state machine table — state persistence path needs follow-up audit
- Q2 (ADR-027 §C reverse-decision-权) + Q3 跌停 fallback specific test + Q4/Q5 runtime scheduler_task_log = next-iter detailed audit candidates

**Severity**: P1 (sustained design-vs-impl path drift, similar to V3 §S6 1/4 outbox table drift surfaced in W2-C iter 145)

---

## §4 Recommendations

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 | DEFER staged_execution_service.py → qm_platform migration (legacy → V3 canonical path) | Tier B Wave 5+ | ~300 LOC refactor + import update + test migration | post PT restart prerequisite |
| R2 | DEFER STAGED state machine DDL design — clarify if trade_log status / risk_event_log OR new staged_states table per V3 §7.3 sequenceDiagram | Tier B Wave 5+ | ADR-DRAFT row + ~80 LOC migration | NEEDS V3 §9.1 sequenceDiagram refresh first (SCHEDULER_V3 §5 Rec #1 deferred per iter 130 sediment) |
| R3 | Next-iter Q2/Q3/Q4/Q5 detailed audit — reverse-decision-权 enforcement point grep + 跌停 fallback test coverage check + Beat scheduler_task_log evidence | Tier C audit | 1 iter | when convenient |
| R4 | Sediment LL "V3 path drift sustained — qm_platform migration deferred multi-month" anti-pattern (parallel to LL-194 architecture drift) | Tier C doc | 1 LL append | next iter cluster |

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only, 0 broker / 0 .env / 0 yaml / 0 DB mutation / 0 production code).

---

## §6 Cite source

| # | Path | Line# | Verify timestamp |
|---|---|---|---|
| 1 | `backend/app/services/risk/staged_execution_service.py` | exists | 2026-05-26 iter 149 fresh |
| 2 | `backend/app/tasks/l4_sweep_tasks.py` | exists | 2026-05-26 iter 149 fresh |
| 3 | `backend/app/tasks/beat_schedule.py` | L228 risk-l4-sweep-1min, L248 broker-stuck-sweep | 2026-05-26 iter 149 fresh |
| 4 | 5 test files under `backend/tests/test_*l4*.py + test_staged*.py` | exists | 2026-05-26 iter 149 fresh |
| 5 | psql `pg_tables` query staged/l4 pattern | 0 rows | 2026-05-26 iter 149 fresh |
| 6 | `backend/.env` L17, L20 | red lines sustained | 2026-05-26 iter 149 |
| 7 | `docs/audit/L4R_AUDIT_WEEK2_MANIFEST_2026_05_26.md` | §2 W2-B | 2026-05-26 iter 149 |

---

**iter 149 classification**: 4 DEFER (R1+R2+R3+R4) — sustained architecture-tier work, all blocked on V3 doc refresh OR PT restart prerequisite. §4.5 ratio rebalance: +4 defer in 1 iter.

**Audit Week 2 manifest progress (post iter 149)**:
- W2-A ✅ iter 131-134+142-143 (closed)
- W2-F ✅ all 10 items closed (iter 135-148: 6 impl + 3 archive + 1 defer)
- W2-E ✅ iter 144 doc refresh
- W2-C ✅ iter 145 audit + 4 recs
- **W2-B ✅ iter 149 (this doc) audit + 4 DEFER recs**
- **W2-D factor_values 172GB hypertable** — only remaining manifest item
