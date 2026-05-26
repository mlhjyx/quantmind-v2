# W3-B QM_PLATFORM_MIGRATION_AUDIT (iter 157)

**Audit date**: 2026-05-26 15:00 SH (approx, network fetch SSL transient fail)
**Iter ID**: 157
**Method**: filesystem find on `backend/qm_platform/risk/` + `backend/app/services/risk/` (read-only)
**Trigger**: W2-B iter 149 R1 sustained — legacy staged_execution_service.py NOT at V3 §7.3 canonical path. Confirm broader migration debt scope.

---

## §1 V3 §7.3 canonical path inventory

`backend/qm_platform/risk/` actual sub-directory state (fresh 2026-05-26):

| Subdir | Status | V3 §7.3 mapping |
|---|---|---|
| `dynamic_threshold/` | ✅ EXISTS | V3 §S5 dynamic threshold cache |
| `execution/` | ✅ EXISTS | V3 §S5 execution layer |
| `memory/` | ✅ EXISTS | V3 §S7 memory + RAG |
| `metrics/` | ✅ EXISTS | V3 §13 元监控 |
| `realtime/` | ✅ EXISTS | V3 §S5 realtime risk engine |
| **`l4/`** | ❌ **MISSING** | V3 §7.3 L4 STAGED execution |

`backend/qm_platform/` grep `staged*` / `l4*` returns **0 files**.

## §2 Legacy V2.5 path inventory

`backend/app/services/risk/` (9 .py files + __init__):

| File | V3 canonical mapping | Migration status |
|---|---|---|
| `staged_execution_service.py` | qm_platform/risk/l4/staged.py | ❌ NOT MIGRATED |
| `dingtalk_webhook_service.py` | qm_platform/risk/notify/ (?) | ❌ legacy |
| `market_indicators_query.py` | qm_platform/risk/context/ (?) | ❌ legacy |
| `market_regime_service.py` | qm_platform/risk/regime/ (?) | ❌ legacy |
| `meta_monitor_service.py` | qm_platform/risk/metrics/ | ❌ legacy (sibling to qm_platform/risk/metrics/) |
| `qmt_sell_adapter.py` | qm_platform/risk/broker/ (?) | ❌ legacy |
| `reflection_candidate_service.py` | qm_platform/risk/memory/ | ❌ legacy (sibling to qm_platform/risk/memory/) |
| `risk_memory_rag.py` | qm_platform/risk/memory/ | ❌ legacy (sibling to qm_platform/risk/memory/) |
| `risk_reflector_agent.py` | qm_platform/risk/reflector/ (?) | ❌ legacy |

**9/9 files NOT migrated** to qm_platform canonical paths. Multiple cases have parallel qm_platform subdirectory siblings (memory, metrics) suggesting partial path migration already happened but service-level files still at legacy location.

---

## §3 Verdict

**qm_platform migration state**: SIGNIFICANT_DEBT (P1 architectural)

Unlike W3-A (V3 §9.1 doc refresh already done) + W3-G (false alarm), W3-B is **real outstanding architectural work**:
- 9 legacy files need migration to qm_platform canonical paths
- Some subdirs (memory, metrics) already exist in qm_platform — service-level entry points not yet moved
- Multi-iter refactor (~ 9 file moves + import update + test migration + smoke verify)

**Severity**: P1 (sustained design-vs-impl path drift, similar to V3 §S6 1/4 outbox table drift W2-C finding)

---

## §4 Recommendations (4 DEFER — all blocked on V3 architectural consensus + offline rehearsal)

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 | DEFER full qm_platform migration ADR-DRAFT — 9 file mapping + import callsite count + test relocation strategy | Tier B Wave 5+ | ADR-DRAFT row + ~30 LOC analysis sketch | post Tier A§2 closure + maintenance window |
| R2 | DEFER incremental migration plan — start with smallest file (e.g. risk_memory_rag.py since qm_platform/risk/memory/ already exists, sibling path) | Tier B Wave 5+ | 1 iter per file + reviewer cycle | post R1 ADR consensus |
| R3 | DEFER 9-file caller grep — `grep -r "from backend.app.services.risk\." backend/ scripts/ tests/` to count import callsite impact per file | Tier C audit | 1 iter (30min) | next iter cluster |
| R4 | DEFER test migration mapping — backend/tests/test_staged_*.py + test_risk_*.py to relocate alongside if file moves | Tier C | mapping table | post R3 |

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only read-only, 0 broker / 0 .env / 0 yaml / 0 DDL / 0 production code).

---

## §6 Cite source

| # | Path | Verify state | Verify timestamp |
|---|---|---|---|
| 1 | `backend/qm_platform/risk/` | 5 subdirs (dynamic_threshold/execution/memory/metrics/realtime), 0 l4/ subdir | 2026-05-26 iter 157 fresh |
| 2 | `backend/app/services/risk/` | 9 .py files all NOT migrated | 2026-05-26 iter 157 fresh |
| 3 | `backend/.env` L17, L20 | red lines sustained | iter 157 |
| 4 | `docs/audit/W2_B_L4_STAGED_EXECUTION_AUDIT_2026_05_26.md` | sibling audit, R1 sustained | 2026-05-26 iter 149 |

---

**iter 157 classification**: 4 DEFER (all blocked on V3 architectural consensus + offline rehearsal). §4.5 ratio: +4 defer.

**Week 3 progress (post iter 157)**:
- W3-A ✅ ARCHIVE iter 156 (V3 §9.1 already done)
- W3-B ✅ iter 157 (this audit) — confirms 9-file migration debt sustained
- W3-F ✅ iter 151 LL-207
- W3-G ✅ chain iter 152-154 + LL-208
- W3-C/D/E pending

**Distinguishing characteristic**: iter 157 W3-B is **NOT ARCHIVE** (unlike 4 prior W2/W3 ARCHIVE discoveries). Real architectural debt confirmed. Sustained as Tier B Wave 5+ candidate per ADR consensus needed.

**5-ARCHIVE streak broken** — W3-B is first real-finding audit in this campaign sequence (good — proves audit Explore SOP refinement (LL-207) doesn't mean "all audits become ARCHIVE", actual gaps still get caught).
