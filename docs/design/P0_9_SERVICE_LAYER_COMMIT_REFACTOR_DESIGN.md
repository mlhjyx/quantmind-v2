# P0-9 Service-Layer Commit() Refactor Design

> **Plan v8 P0-9 closure prep** — design only, high-risk Phase J+ implementation.
> **Source**: Plan v8 §13 Code Health audit — 30 service-layer `commit()` calls violate Iron Law 32
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P0-9)**:
- 30+ `conn.commit()` calls inside `backend/app/services/*` violate Iron Law 32
- Iron Law 32: Service-layer 不 commit — transaction boundary 由调用方 (Router / Celery / Test) 管理
- Risk: Service commits silently inside an outer transaction → can break transactional integrity
- Why P0: Phase B-2 live trading 启动后 race conditions / partial rollback / orphan rows surface

**Current de-facto behavior**:
- Many services run autocommit=True (psycopg2 default ≠ Iron Law 32)
- Test suite passes (each test gets fresh connection)
- Production: each Router/Celery task creates a new conn → commit is "safe" but architecturally wrong
- Risk: 重构期间 batch operations across services 引入 partial state visibility

---

## §2 Scope Analysis

### §2.1 Affected files (audit candidate list)

(Run `rg "conn\.commit\(\)" backend/app/services/` for actual list)

Expected categories:
- **Hot services** (signal / execution / risk): 8-10 files, high blast radius
- **Cold services** (factor lifecycle / IC rolling / reconciliation): 12-15 files, medium risk
- **Utility services** (audit / notification / cache): 5-7 files, low risk

### §2.2 Per-service migration steps

For each service with `conn.commit()`:

1. Identify all callers (`rg "<ServiceName>" backend/app/`)
2. Determine: which caller layer owns transaction?
   - **Router** (FastAPI endpoint) → caller owns
   - **Celery task** → task body owns
   - **Test** → fixture-controlled
3. Remove `conn.commit()` from service
4. Verify caller has explicit commit
5. Run service-specific tests + integration tests
6. Verify no rollback regression

### §2.3 Discovery + categorization phase

Phase 0 — Inventory (1 day):
- Grep all `conn.commit()` in services/
- Build spreadsheet: service / method / callers / risk tier
- Decision: which services to migrate in batch 1 vs defer

---

## §3 Migration Strategy

### §3.1 Strategy A: Big bang (rejected)
- Remove all `conn.commit()` in one PR
- High risk: any caller missing explicit commit → silent data loss
- Decision: REJECT

### §3.2 Strategy B: Per-service incremental (preferred)
- Tier 3 (Utility) → Tier 2 (Cold) → Tier 1 (Hot) ordering
- 1 service per PR
- AI review + test coverage gate
- Risk-bounded rollout

### §3.3 Strategy C: Transactional wrapper decorator
- New `@transactional` decorator at Router/task level
- Service unchanged
- Decorator handles begin/commit/rollback
- **Pros**: Less invasive
- **Cons**: Hidden control flow, harder to debug

**Decision**: Strategy B (incremental) — explicit caller boundaries beat decorator magic.

---

## §4 Pre-Phase J Preparation

### §4.1 Pre-flight (Phase B-1 现在做的)

1. **Inventory** (✅ partial — Plan v8 §13 audit found 30+ violations)
2. **Per-service caller map** — tooling needed:
   - `scripts/audit_service_commit_violations.py` (Phase 0)
3. **Test coverage assessment** — current coverage on affected services?

### §4.2 Initial migration batch (Phase J 1st week, post 5-27)

Pick 3 LOW-RISK utility services:
- `notification_service.py` (DingTalk push, no critical data)
- `audit_service.py` (audit_log INSERT only)
- `cache_service.py` (Redis read/write, no PG)

PR per service, AI review, manual smoke test, merge.

### §4.3 Iterative rollout

| Tier | Services | Risk | Effort | Phase |
|---|---|---|---|---|
| Utility (5-7) | notification / audit / cache | LOW | 1-2 days each | Phase J Week 1 |
| Cold (12-15) | factor lifecycle / IC / reconciliation | MEDIUM | 2-3 days each | Phase J Week 2-3 |
| Hot (8-10) | signal / execution / risk | HIGH | 3-5 days each | Phase J Week 4-6 |

**Total migration**: ~6-8 weeks if 1 service/day average

---

## §5 Risk Mitigations

### §5.1 Per-PR safeguards
- AI code review (mandatory)
- Test coverage delta visible
- Integration test scenarios:
  - Successful flow (commit happens)
  - Error mid-flow (rollback happens)
  - Concurrent caller (no partial state visible)
- Manual smoke test on dev DB

### §5.2 Rollback per service
- Git revert per PR
- DB unaffected (no schema changes)
- Servy restart sufficient

### §5.3 Pre-Phase B-2 timing
- Start migration ONLY after Phase B-2 (5-27 Wed) stable for 1 week
- Live trading observation reveals which services have hot paths
- Frozen state during 5-27 → 6-3 first live week

---

## §6 Iron Law Compliance

- Iron Law 32: Service-layer 不 commit (THIS IS THE TARGET)
- Iron Law 25: 代码变更前必读当前代码 (per-service inventory mandatory)
- Iron Law 36: 代码变更前必核 precondition (依赖 / 老路径 / 测试数据)
- Iron Law 40: 测试债务不得增长 (baseline 24, must hold)
- Iron Law 42: PR分级 — every service refactor MUST go through PR + reviewer

---

## §7 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (high risk during frozen state)
- Phase B-2 (5-27 Wed): NOT prerequisite, NOT during first week
- Phase J Week 2+ (post 5-27 stable): Phase 0 inventory tooling
- Phase J Week 3+: First Tier 3 utility migration
- Phase J Week 8: Mid-point review
- Phase K: Hot services migration complete

---

## §8 Effort Estimate

| Phase | Effort | Risk |
|---|---|---|
| 0 Inventory + tooling | 1 day | LOW |
| 1 Tier 3 utility (5-7 services) | 5-10 days | LOW |
| 2 Tier 2 cold (12-15 services) | 24-45 days | MEDIUM |
| 3 Tier 1 hot (8-10 services) | 24-50 days | HIGH |

**Total**: ~10-15 weeks for full closure
**Reduced scope**: ~3-4 weeks for top 10 critical services (60% closure)

---

**Maintained by**: CC autonomous (Plan v8 P0-9 design sediment, 2026-05-20 Day 1)
**Status**: Design sediment + Phase J Week 2+ first action
**Cross-ref**:
- Iron Law 32 (Service no commit)
- Plan v8 §13 Code Health audit
- ADR-027 (transaction boundary precedent in L4 STAGED)
- LL-066 (DataPipeline subset-column UPSERT 例外 — read-only via UPDATE, no transactional risk)
