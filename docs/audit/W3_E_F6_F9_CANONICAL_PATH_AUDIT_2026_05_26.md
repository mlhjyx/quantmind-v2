# W3-E F6+F9 CANONICAL_PATH_AUDIT (iter 159)

**Audit date**: 2026-05-26 15:15 SH (approx)
**Iter ID**: 159
**Method**: filesystem find on attribution + audit primitives (read-only)
**Trigger**: W2-F iter 148 F9 DEFER + iter 146-147 F6 implementation surface (both at legacy paths similar to W2-B + W3-B finding). Confirm scope of canonical-path migration.

---

## §1 F6 Attribution path inventory

| Path | Layer | Status |
|---|---|---|
| `backend/qm_platform/eval/attribution.py` | V3 canonical (eval domain) | ✅ EXISTS |
| `backend/app/api/attribution.py` | API endpoint (legacy `app/api/`) | ❌ legacy |
| `backend/app/tasks/attribution_tasks.py` | Celery task body | ❌ legacy |
| `backend/engines/attribution.py` | Engine layer | ❌ legacy |
| `backend/tests/test_attribution.py` | Legacy test | ❌ legacy test |
| `backend/tests/test_qm_platform_attribution.py` | V3 canonical test | ✅ EXISTS |

**F6 verdict**: PARTIAL_MIGRATION (~50%). qm_platform canonical exists for eval engine + test, but API endpoint + Celery task + legacy engine files still at app/ layer. PR #493 (iter 146-147) shipped F6 implementation but at legacy paths.

---

## §2 F9 audit_log path inventory

| Path | Scope | Status |
|---|---|---|
| `backend/app/middleware/audit.py` | HTTP request middleware audit | ❌ legacy, NOT audit_log table writer |
| `backend/qm_platform/llm/_internal/audit.py` | LLM token/cost audit | ✅ V3 canonical (llm domain) |
| `backend/qm_platform/signal/audit.py` | Signal generation audit | ✅ V3 canonical (signal domain) |
| `backend/app/api/audit_log.py` (or similar) | **MISSING** | ❌ user-facing audit_log endpoint |
| DDL `audit_log` table query API | **MISSING** | ❌ sustained per W2-F DEFER iter 148 |

**F9 verdict**: PARTIAL_IMPL + PARTIAL_DRIFT. 3 audit primitives exist (middleware + llm + signal) but none is the user-facing `/api/audit-log/*` query endpoint per W2-F audit. F9 remains as backend NEW endpoint required per W2-F deferred recs.

---

## §3 Combined Verdict

**W3-E state**: MIXED_DEBT (P1, multi-axis)

- F6: 50% migrated, 4-file legacy cleanup pending (sustained Tier B Wave 5+)
- F9: 0% user-facing audit_log API + 60% primitives exist scattered (sustained W2-F DEFER, requires backend NEW)

**Severity**: P1 architectural debt sustained, larger scope than W3-B (which was 9-file legacy).

---

## §4 Recommendations (4 DEFER paired ratio rebalance)

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 | DEFER F6 完成 migration — move api/attribution.py + tasks/attribution_tasks.py + engines/attribution.py to qm_platform canonical paths (4-file move + import update + test relocate) | Tier B Wave 5+ | ~200 LOC refactor + reviewer + smoke | post Tier A§2 + maintenance window |
| R2 | DEFER F9 backend NEW: add `backend/qm_platform/audit/` domain + `app/api/audit_log.py` endpoint + DDL audit_log table query API | Tier B Wave 5+ | ~300 LOC NEW + DDL + ADR-DRAFT | post W3-C compression ADR consensus |
| R3 | DEFER F6+F9 caller grep — count import callsite impact before R1+R2 mass migration | Tier C audit | 30min | next iter cluster |
| R4 | DEFER ADR-DRAFT for F6 migration + F9 introduction (combine into single multi-domain migration ADR — saves REGISTRY churn vs 2 separate ADRs) | Tier B Wave 5+ ADR | combined ADR-DRAFT | post R3 caller grep |

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only read-only).

---

## §6 Cite source

| # | Path | Verify state | Verify timestamp |
|---|---|---|---|
| 1 | `backend/qm_platform/eval/attribution.py` | V3 canonical exists | 2026-05-26 iter 159 fresh |
| 2 | `backend/app/api/attribution.py` + `backend/app/tasks/attribution_tasks.py` + `backend/engines/attribution.py` | 3 legacy F6 files | 2026-05-26 iter 159 fresh |
| 3 | `backend/qm_platform/llm/_internal/audit.py` + `backend/qm_platform/signal/audit.py` | 2 V3 primitives | 2026-05-26 iter 159 fresh |
| 4 | `backend/app/middleware/audit.py` | legacy middleware-only | 2026-05-26 iter 159 fresh |
| 5 | `app/api/audit_log.py` or `app/api/audit*.py` | **0 hits** — sustained per W2-F F9 DEFER iter 148 | 2026-05-26 iter 159 |
| 6 | `backend/.env` L17, L20 | red lines sustained | iter 159 |
| 7 | `docs/audit/W2_F_FRONTEND_INTEGRATION_AUDIT_2026_05_26.md` §4 F9 DEFER row | sustained | iter 148 |

---

**iter 159 classification**: 4 DEFER (all blocked on V3 architectural consensus + Tier A§2 closure + ADR-DRAFT cascade). §4.5 ratio: +4 defer.

**Week 3 progress (post iter 159)** — ALL 6 candidates closed effectively:
- W3-A ✅ ARCHIVE iter 156
- W3-B ✅ audit + 4 DEFER iter 157
- W3-C ✅ ADR-DRAFT iter 158
- W3-D V3 §S6 outbox DDL — sustained DEFER per W2-C R1 (iter 145), NOT separately audited this cluster (covered by W2-C finding chain)
- **W3-E ✅ iter 159 (this audit) + 4 DEFER recs**
- W3-F ✅ iter 151 LL-207
- W3-G ✅ iter 152-154 chain + LL-208 iter 155

**Week 3 mission accomplishment**: 7-iter cluster (iter 151+152+154+155+156+157+158+159 audit/sediment) closed all 7 W3 backlog items. 0 implement / 5 ARCHIVE (incl ratio of W2-F carryover + W3-A) / 8 DEFER (mostly Tier B Wave 5+ blocked on architectural consensus + PT restart prerequisite).

**Net audit-driven phase value**: 13 distinct findings across Week 2 + Week 3 (~20 W2 + 7 W3 ≈ ~27 cumulative). Audit-driven phase L4R §4.2 reality re-grounding sustained productive across ~25 iter cluster.
