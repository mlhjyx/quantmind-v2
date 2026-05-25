# W2-F FRONTEND_INTEGRATION_AUDIT — V3 风控 + Wave 4 + Approval + PT (iter 135)

**Audit date**: 2026-05-26
**Iter ID**: 135 (L4+R loop, post iter 134 PR #484 closure)
**Method**: Explore subagent (Glob + Grep + Read) read-only enumeration, all 4 scopes very-thorough breadth
**Trigger**: user 5-26 explicit ask "后端的功能没有在前端进行集成" + v9.6 prompt Tier A§2 prerequisite
**Sibling pattern**: W2-A iter 131 OBSERVABILITY MVP 4.1 runtime verify (6 finding catalog)

---

## §1 Audit scope (4 areas)

- **Scope A**: V3 风控 framework (L0-L5 layers + V3 §S5-§S8 backend → RiskManagement.tsx)
- **Scope B**: Wave 4 Observability + Attribution backend → frontend dashboards
- **Scope C**: Approval queue + audit log middleware backend → UI
- **Scope D**: PT operator core (NAV / positions / cash / trade log) → Dashboard

---

## §2 Wire status enumeration

### Scope A: V3 风控 framework

| # | Backend endpoint | Method+Path | Frontend consumer | Status |
|---|---|---|---|---|
| A1 | `backend/app/api/risk.py:93` | GET /api/risk/state/{strategy_id} | `frontend/src/api/dashboard.ts:76` (fetchCircuitBreakerState) | LIVE |
| A2 | `backend/app/api/risk.py:146` | GET /api/risk/history/{strategy_id} | DARK | DARK |
| A3 | `backend/app/api/risk.py:187` | GET /api/risk/summary/{strategy_id} | DARK | DARK |
| A4 | `backend/app/api/risk.py:307` | GET /api/risk/overview | `frontend/src/pages/RiskManagement.tsx:170` | LIVE |
| A5 | `backend/app/api/risk.py:387` | GET /api/risk/limits | `frontend/src/pages/RiskManagement.tsx:171` | LIVE |
| A6 | `backend/app/api/risk.py:486` | GET /api/risk/stress-tests | `frontend/src/pages/RiskManagement.tsx:172` | LIVE |
| A7 | `backend/app/api/risk.py:206` | POST /api/risk/l4-recovery/{strategy_id} | `SafetyControlPanel.tsx:48` (stub) | PARTIAL |
| A8 | `backend/app/api/risk.py:239` | POST /api/risk/l4-approve/{approval_id} | DARK | DARK |
| A9 | `backend/app/api/risk.py:273` | POST /api/risk/force-reset | `SafetyControlPanel.tsx:48` | PARTIAL |
| A10 | `backend/app/api/risk.py:618` | POST /api/risk/dingtalk-webhook | inbound only | LIVE |

**Subtotal**: 10 endpoints — 4 LIVE / 4 DARK / 2 PARTIAL

### Scope B: Wave 4 Observability + Attribution

| # | Backend endpoint | Method+Path | Frontend consumer | Status |
|---|---|---|---|---|
| B1 | `backend/app/api/system.py:258` | GET /api/system/datasources | DARK | DARK |
| B2 | `backend/app/api/system.py:298` | GET /api/system/health | DARK | DARK |
| B3 | `backend/app/api/system.py:346` | GET /api/system/scheduler | DARK | DARK |
| B4 | `backend/qm_platform/eval/attribution.py` | (no /api/* surface) | N/A | DARK (NO API) |
| B5 | `backend/qm_platform/observability/*.py` | (no /api/* surface) | N/A | DARK (NO API) |

**Subtotal**: 5 surface points — 0 LIVE / 5 DARK (3 endpoints + 2 NO_API_SURFACE)

### Scope C: Approval queue + audit log

| # | Backend endpoint | Method+Path | Frontend consumer | Status |
|---|---|---|---|---|
| C1 | `backend/app/api/approval.py:205` | GET /api/approval/queue | DARK (only types in `pipeline.ts:12-27`) | DARK |
| C2 | `backend/app/api/approval.py:234` | GET /api/approval/queue/{item_id} | DARK | DARK |
| C3 | `backend/app/api/approval.py:259` | POST /api/approval/queue/{item_id}/approve | DARK | DARK |
| C4 | `backend/app/api/approval.py:290` | POST /api/approval/queue/{item_id}/reject | DARK | DARK |
| C5 | `backend/app/api/approval.py:321` | POST /api/approval/queue/{item_id}/hold | DARK | DARK |
| C6 | `backend/app/api/approval.py:352` | GET /api/approval/history | DARK | DARK |
| C7 | (no `/api/audit-log/*` endpoint) | N/A | N/A | DARK (NO API) |

**Subtotal**: 7 surface points — 0 LIVE / 7 DARK

### Scope D: PT operator core

| # | Backend endpoint | Method+Path | Frontend consumer | Status |
|---|---|---|---|---|
| D1 | `backend/app/api/paper_trading.py:57` | GET /api/paper-trading/status | DARK | DARK |
| D2 | `backend/app/api/paper_trading.py:76` | GET /api/paper-trading/graduation | `PTGraduation.tsx:26` | LIVE |
| D3 | `backend/app/api/paper_trading.py:101` | GET /api/paper-trading/graduation-status | `PTGraduation.tsx:26` | LIVE |
| D4 | `backend/app/api/paper_trading.py:224` | GET /api/paper-trading/positions | `dashboard.ts:53` | LIVE |
| D5 | `backend/app/api/paper_trading.py:243` | GET /api/paper-trading/trades | DARK | DARK |
| D6 | `backend/app/api/dashboard.py:25` | GET /api/dashboard/summary | `dashboard.ts:15-19` | LIVE |
| D7 | `backend/app/api/dashboard.py:46` | GET /api/dashboard/nav-series | `dashboard.ts:22-29` | LIVE |
| D8 | `backend/app/api/dashboard.py:67` | GET /api/dashboard/pending-actions | DARK | DARK |
| D9 | `backend/app/api/portfolio.py:34` | GET /api/portfolio/holdings | DARK | DARK |
| D10 | `backend/app/api/portfolio.py:105` | GET /api/portfolio/sector-distribution | DARK | DARK |

**Subtotal**: 10 endpoints — 5 LIVE / 5 DARK

---

## §3 Summary

| Metric | Count | % |
|---|---:|---:|
| Total backend surface (A+B+C+D) | 32 | 100% |
| LIVE (frontend renders real backend) | 9 | 28% |
| DARK (0 frontend consumer / NO_API) | 21 | 66% |
| PARTIAL (some flows, critical missing) | 2 | 6% |

**Critical findings**:
- V3 风控 framework backend 6/10 (60%) DARK or PARTIAL — user-facing risk control L4 recovery + approval flow incomplete
- Wave 4 Observability 5/5 (100%) DARK — backend audit envelope (iter 132+134 sediment) lacks UI surface
- Approval queue 6/6 (100%) DARK — 0 frontend page despite V3 §S5/S6/S7/S8 merged main
- audit_log table 0 query endpoint — compliance gap, also blocks future UI
- Attribution + observability lib have NO /api/* surface — must add endpoint layer first

---

## §4 Prioritized gaps for Tier A§2 wire iterations (P0/P1)

| # | Gap | Priority | Backend ready | Frontend work est. | First iter candidate |
|---|---|---|---|---|---|
| F1 | Approval queue UI (V3 §S5/§S6/§S7/§S8 closure) | P0 | ✅ 6 endpoints | ~600 LOC + tests | iter 136 |
| F2 | L4 Recovery completion (l4-approve POST + state display) | P0 | ✅ A7+A8 ready | ~300 LOC | iter 137 |
| F3 | Risk event stream consumer (LiveRiskEventsPanel real data) | ~~P0~~ **ARCHIVED iter 138 2026-05-26** | ✅ shipped Session 58 round-5 (ADR-084 Phase 1) | already done | ~~iter 138~~ |
| F4 | Wave 4 Observability dashboard (Beat tasks + scheduler_task_log) | P1 | ✅ B1-B3 ready | ~400 LOC + new page | iter 139 |
| F5 | Risk history + summary surface (A2+A3 add to RiskManagement.tsx) | P1 | ✅ A2+A3 ready | ~150 LOC | iter 140 |
| F6 | Attribution API + UI (per backend lib) | P1 | ❌ NO API yet | backend ~200 + frontend ~300 | iter 141-142 |
| F7 | PT trade log surface (PTGraduation 增 history tab) | P1 | ✅ D5 ready | ~150 LOC | iter 143 |
| F8 | Pending actions dashboard widget (D8) | P1 | ✅ D8 ready | ~80 LOC | iter 144 |
| F9 | Audit log API + UI (compliance) | P2 | ❌ NO API yet | backend ~150 + frontend ~250 | iter 145-146 |
| F10 | Portfolio analytics (D9+D10) | P2 | ✅ ready | ~200 LOC | iter 147 |

**Cumulative wire estimate**: ~2700 LOC frontend + ~350 LOC backend (attribution + audit_log API) + tests ≈ 10-12 iter cycles to full closure.

**iter 138 ARCHIVE discovery (2026-05-26)**: F3 LiveRiskEventsPanel reality check — fresh grep `frontend/src/pages/RiskManagement.tsx:33-87` shows `LiveRiskEventsPanel` sub-component IS fully wired (uses `useRiskEventsSSE` hook from `frontend/src/hooks/useRiskEventsSSE.ts` + `backend/app/api/sse.py:159` GET /api/sse/risk-events SSE endpoint). Connection status (已连接/未连接 with pulse animation) + heartbeat timestamp + error display + reconnect button + empty state + event list (50 buffer, newest-first reverse). Session 58 round-5 ADR-084 Phase 1 closure commit. **W2-F audit iter 135 misclassified as DARK** — staleness gap (audit Explore subagent enumeration may have missed sub-component grep or scanned older snapshot). LL-194 anti-pattern (claim verify pre-commit): future Explore-driven audits SHOULD grep for sub-component definitions within page files, not just file-level export consumption. **Verdict**: F3 ARCHIVE (no implement needed); Tier A§2 P0 closure 100% (F1+F2 shipped iter 136-137 + F3 already shipped Session 58).

---

## §5 Tier mapping

- **F1+F2+F3**: Tier A§2 (V3 风控 frontend integration, blocks PT restart gate)
- **F4+F5+F6+F7+F8**: Tier B Wave 5 MVP candidates (MVP 5.4 风控 / MVP 5.5 调度 / MVP 5.1 PT 状态)
- **F9+F10**: Tier B Wave 5 MVP 5.x deferred (compliance + portfolio dashboards)

---

## §6 Next iter

iter 136 first action = F1 Approval queue UI per §v9.50 4-stage SOP (backend truth ✅ stage 1 done from this audit; proceed Stage 2 designer agent for wireframe + Stage 3 implement).

---

**Provenance**: Explore subagent Glob + Grep + Read enumeration 2026-05-26 ~02:00 SH. All cited file:line verified at audit time. Doc-vs-reality fresh.

**Refs**:
- W2-A sibling: docs/audit/W2_A_OBSERVABILITY_MVP41_RUNTIME_VERIFY_2026_05_26.md
- Manifest: docs/audit/L4R_AUDIT_WEEK2_MANIFEST_2026_05_26.md (W2-F slot added)
- v9.6 spec Tier A§2: V3 风控 frontend integration audit + wire (user 5-26 显式 ask)
