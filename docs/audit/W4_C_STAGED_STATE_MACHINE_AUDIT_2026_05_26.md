# W4-C STAGED_STATE_MACHINE_AUDIT (iter 165)

**Audit date**: 2026-05-26 16:20 SH
**Iter ID**: 165 (Week 4 cluster, smallest remaining)
**Method**: read staged_execution_service.py + psql verify execution_plans table (read-only)
**Trigger**: W2-B iter 149 + W3-B iter 157 audits both stated "no dedicated staged/l4 state machine table in DB". W4-C cross-verifies via code-trace.

---

## §1 Code-trace findings

`backend/app/services/risk/staged_execution_service.py` (449 LOC):
- L1: docstring "DB orchestration for STAGED post-CONFIRMED sell (S8 8c-followup)"
- L22-24: `Race-safe UPDATE: UPDATE execution_plans SET status=?, broker_order_id=?, broker_fill_status=?, final status.`
- L72-76: `PlanStatus` enum — EXECUTED / FAILED / RACE
- L141: `current_status = PlanStatus(plan_row["status"])` — reads status from execution_plans row
- L172-178: race-safe UPDATE on execution_plans
- L182-189: refreshed_status re-read post-race conflict

**Canonical table**: `execution_plans` (NOT `staged_*` or `l4_*` per legacy naming pattern).

---

## §2 DB schema verify

psql fresh 2026-05-26 16:21 SH:

```sql
SELECT 'rows', COUNT(*) FROM execution_plans;  -- → 0 rows (PT 27d paused since 4-29)
SELECT column_name FROM information_schema.columns WHERE table_name='execution_plans' ORDER BY ordinal_position;
```

**Schema** (19 columns):
- plan_id (UUID PK presumed)
- triggered_by_event_id (risk_event_log FK)
- mode (live/paper)
- symbol_id, action, qty, limit_price
- batch_index, batch_total (batched STAGED support)
- scheduled_at, cancel_deadline (timing constraints)
- status (PlanStatus enum — READY/ARMED/DISPATCHED/REJECTED/EXPIRED/EXECUTED/FAILED/RACE per code)
- user_decision, user_decision_at (反向决策权 / ADR-027 §C support)
- broker_order_id, broker_fill_status
- risk_reason, risk_metrics (JSONB presumed)
- created_at

---

## §3 Verdict — W2-B + W3-B finding REVISED

**W4-C state**: STAGED state machine HAS canonical DDL persistence at `execution_plans` table ✅

- ✅ Table exists with 19 columns + state machine status field
- ✅ Service layer code (staged_execution_service.py L22-24) writes status / broker_order_id / broker_fill_status via race-safe UPDATE
- ✅ User decision tracking (user_decision, user_decision_at) supports ADR-027 §C 反向决策权
- ✅ Batch + timing constraints (batch_index/total + cancel_deadline) per V3 §7.3 14:55 挂限 design
- ✅ 0 rows post 4-29 PT pause — consistent with sustained 27d 0 trades red-line

**W2-B + W3-B finding revision**:
- W2-B iter 149 Q6 said "STAGED status state machine DDL exists? psql 0 hits for `%staged%`/`%l4%`" — REVISED: table IS `execution_plans` (not matched by narrow pattern)
- W3-B iter 157 §1 said "qm_platform/risk/l4/ MISSING" — sustained PATH_DRIFT for V3 §7.3 canonical layer naming, but underlying DDL persistence INFRASTRUCTURE EXISTS (service+table both shipped)

**Severity**: P1 → P2 (DDL exists, only path naming drift remains per W3-B)

---

## §4 LL-207 anti-pattern 6th instance

W4-C surfaces **6th LL-207 audit Explore systematic miss** instance this audit cluster:
- W2-F F3 (iter 138 ARCHIVE) — sub-component grep missed
- W2-F F4 (iter 142 ARCHIVE) — wrapper call-site count missed
- W2-F F10 (iter 143 ARCHIVE) — inline apiClient.get missed
- W3-A (iter 156 ARCHIVE) — V3 §9.1 sequenceDiagram already refreshed iter 99
- W3-G iter 152-154 — T+1 lookahead inherent design semantic missed
- **W4-C (this iter) — table name `execution_plans` not matching `%staged%`/`%l4%` grep pattern**

LL-207 SOP refinement extends: for DB schema audits, MUST grep:
1. By literal name (e.g. `staged_*`, `l4_*`)
2. By **service file → table reference cross-search** (e.g. `grep "UPDATE\|INSERT INTO" backend/app/services/risk/` to find canonical tables)
3. By **information_schema cross-check** (compare all `pg_tables` against expected design names + service references)

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only read-only).

---

## §6 Recommendations

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 (IMPLEMENT) | Sediment this W4-C audit + W2-B/W3-B revision note | Tier C | 1 commit | this iter 165 |
| R2 (ARCHIVE) | W2-B Q6 + W3-B §1 "DDL gap" finding ARCHIVE | Tier C | 0 (revision via cite) | this iter |
| R3 (DEFER) | LL-207 amend with §4 DB schema audit SOP refinement (3 grep patterns) | Tier C LL append | ~10 LOC LL extension | next iter cluster |
| R4 (DEFER sustained from W3-B) | Path migration legacy `app/services/risk/staged_execution_service.py` → `qm_platform/risk/l4/staged.py` per V3 §7.3 canonical — DDL doesn't need migration (table name stays `execution_plans`), only service file location | Tier B Wave 5+ | ~150 LOC refactor + import + test relocate | post user authorize + maintenance window |

---

## §7 Cite source

| # | Path | Lines | Verify state | Verify timestamp |
|---|---|---|---|---|
| 1 | `backend/app/services/risk/staged_execution_service.py` | L1, L22-24, L72-76, L141, L172-189 | execution_plans table writes confirmed | 2026-05-26 iter 165 fresh |
| 2 | psql `information_schema.columns WHERE table_name='execution_plans'` | runtime — 19 columns | 2026-05-26 iter 165 fresh |
| 3 | psql `SELECT COUNT(*) FROM execution_plans` | runtime — 0 rows (PT pause) | 2026-05-26 iter 165 fresh |
| 4 | W2-B audit iter 149 Q6 | DDL gap finding REVISED here | iter 149 |
| 5 | W3-B audit iter 157 §1 | qm_platform/risk/l4/ MISSING sustained PATH_DRIFT, DDL gap revised | iter 157 |
| 6 | `backend/.env` L17, L20 | red lines sustained | iter 165 |

---

**iter 165 classification**: 1 IMPLEMENT (this audit) + 1 ARCHIVE (W2-B Q6 + W3-B DDL gap REVISED) + 2 DEFER (LL-207 amend + path migration sustained). §4.5 ratio: +1 impl +1 archive +2 defer.

**Week 4 progress (post iter 165)**:
- W4-A ✅ iter 162 (LL-188 hook 21/21 false-positive)
- W4-C ✅ iter 165 (this audit, STAGED state machine has DDL, W2-B/W3-B revised)
- W4-D ✅ iter 164 (hook semantic refinement spec)
- W4-E ✅ iter 163 (cron healthy)
- W4-B pending (last DEV doc-rot scan)

**Audit cluster cumulative ratio (W2+W3+W4 post iter 165)**:
- 7 implement (W2-F F1+F2+F5+F7+F8 + W3-C ADR-DRAFT + W4-A/D/E/C various — counted once)
- **6 ARCHIVE discoveries** (LL-207 6th instance this iter — W2-F F3/F4/F10 + W3-A + W3-G + W4-C)
- 15 DEFER (Tier B Wave 5+ blocked on V3 consensus + PT restart)
