# P1-36 Risk Subservice Cluster API Design

> **Plan v8 P1-36 closure prep** — design only, multi-week implementation deferred.
> **Source**: Plan v8 audit §16 Observability — Risk Framework has 7+ subservices, 0 API surface
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P1-36)**:
- backend/qm_platform/risk/ contains 7+ subservices:
  - `realtime/` (S5 RealtimeRiskEngine + S6 AlertDispatcher)
  - `dynamic_threshold/` (S7 ThresholdEngine)
  - `execution/` (L4 ExecutionPlanner)
  - `replay/` (S15 historical replay)
  - `metrics/` (元监控 alert-on-alert)
  - `circuit_breaker/` (止损熔断)
  - `pms/` (3-layer profit保护)
- 0 公开 API for status query / control / debug
- Operators (CC + user) currently inspect via:
  - DB SELECT (risk_event_log / risk_metrics_daily / circuit_breaker_state)
  - Servy log tail
  - Direct DingTalk subscription

**Why API**:
- Frontend control plane (§XI) needs read access
- User dashboard "Risk Health" panel needs structured queries
- Phase B-2 + live trading exposes operator visibility gap

---

## §2 API Surface Design

### §2.1 Read-only endpoints (Phase 1, low risk)

```
GET /api/risk/health
  Response: {
    overall_severity: "ok" | "warn" | "p1" | "p0",
    subservices: {
      realtime_engine: {status, last_tick, rules_evaluated_today},
      alert_dispatcher: {buffer_size_p1, buffer_size_p2, flushes_today},
      threshold_engine: {active_rules_count, last_update},
      execution_planner: {pending_plans, executed_today},
      pms: {active_protection_level, last_trigger},
      circuit_breaker: {state, daily_loss, threshold},
    }
  }

GET /api/risk/events?date=&severity=&rule_id=
  Response: paginated risk_event_log rows

GET /api/risk/metrics/daily?date=
  Response: risk_metrics_daily row

GET /api/risk/threshold-rules
  Response: current rule_id → threshold mapping

GET /api/risk/circuit-breaker/state
  Response: CB state machine current state + history

GET /api/risk/pms/protection-level
  Response: current PMS L1/L2/L3 status
```

### §2.2 Write endpoints (Phase 2, gated)

```
POST /api/risk/threshold-rules/{rule_id}/proposal
  Body: {proposed_threshold, rationale}
  Auth: admin token
  Side effect: INSERT risk_threshold_proposals (status=pending)

POST /api/risk/circuit-breaker/manual-trigger
  Body: {reason}
  Auth: admin token + double confirm (Phase B-1 = 0 broker effect)
  Side effect: emit CB.MANUAL state, halt all execution

POST /api/risk/circuit-breaker/clear
  Body: {confirmation_token}
  Auth: admin token + extra guardrail
  Side effect: CB → NORMAL state

POST /api/risk/pms/override
  Body: {protection_level, reason, expiry}
  Auth: admin token + expiry mandatory
  Side effect: temporary PMS override (e.g. 1h fire-drill)
```

### §2.3 Debug endpoints (Phase 3, dev-only)

```
POST /api/risk/replay/dry-run
  Body: {start_date, end_date, rules_filter}
  Side effect: replay historical scenarios w/o impact

GET /api/risk/meta-monitor/last-tick
  Response: 元监控 last evaluation result (V3 §13.3)
```

---

## §3 Auth + Rate Limit

### §3.1 Auth tiers

- **Read**: admin_token httpOnly cookie OR ADMIN_TOKEN header
- **Write (proposal)**: admin_token + body validation
- **Write (manual trigger)**: admin_token + double confirm + audit_log INSERT
- **Write (CB clear)**: admin_token + 30s cooldown after trigger

### §3.2 Rate limits

- Read: 60 req/min/IP
- Write: 10 req/min/IP
- Replay dry-run: 1 req/min/IP (expensive)

---

## §4 Schema Dependencies

### §4.1 Existing tables (sustained)

- `risk_event_log` — every rule trigger sediment
- `risk_metrics_daily` — daily aggregates (V3 §13)
- `circuit_breaker_state` — state machine history

### §4.2 New tables (P1-36 + P0-4 共享)

- `risk_threshold_proposals` (from P0-4 design) — write endpoint feeds this
- `risk_audit_log` (new) — every API write action sediment
  - columns: timestamp / endpoint / actor / payload / outcome

---

## §5 Implementation Phases

### §5.1 Phase 1 (Week 1): Read-only API

- New `backend/app/api/risk.py` router
- 7 read endpoints
- Test: e2e curl smoke test
- Frontend: surface in Risk Health dashboard (Phase H Frontend redesign)

### §5.2 Phase 2 (Week 2): Write endpoints + audit_log

- 4 write endpoints
- New `risk_audit_log` table migration
- DingTalk push on every write
- Test: idempotency + auth gating

### §5.3 Phase 3 (Week 3): Debug + replay

- 2 debug endpoints
- Replay dry-run rate-limited

### §5.4 Phase 4 (Week 4+): Frontend integration

- Phase H W7+ candidate
- Risk Health page + threshold proposals approval flow

---

## §6 Alternatives Considered

### Alt 1: Direct DB query (current state)
- User runs `psql` ad-hoc
- No API needed
- **Limitation**: Frontend can't query, no rate limit, no audit trail

### Alt 2: gRPC instead of REST
- Better type safety
- Phase 5+ candidate (frontend currently REST)

### Alt 3: GraphQL aggregate
- Single endpoint with rich filters
- Over-engineering for 7 subservices

### Alt 4: WebSocket streaming
- Real-time push instead of poll
- Phase J — currently no real-time consumers

---

## §7 Effort Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Read-only API | 3-5 days | None |
| 2 Write + audit | 4-6 days | Phase 1 + P0-4 proposal table |
| 3 Debug + replay | 3-4 days | Phase 2 |
| 4 Frontend integration | 5-7 days | Phase 1+2 + Frontend Phase H |

**Total Phase 1-3**: ~2 weeks
**Total Phase 1-4 (full UX)**: ~4 weeks

---

## §8 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed live): not prerequisite, but desirable for live trading visibility
- Phase J (post 5-27): Phase 1 priority — operator visibility critical for live ops
- Phase J+1: Phase 2+3
- Phase J+2: Phase 4 (frontend)

---

## §9 Iron Law Compliance

- Iron Law 32: Routers don't commit (use service-layer transaction)
- Iron Law 33: Fail-loud on write endpoint validation
- Iron Law 34: Threshold rules SSOT in DB, not config
- Iron Law 42: PR分级 — `backend/app/api/risk.py` MUST go through PR (not direct push)

---

**Maintained by**: CC autonomous (Plan v8 P1-36 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- V3 §S5/S6/S7 risk subservice architecture
- Plan v8 §XI UX Control Plane design
- P0-4 design (shares risk_threshold_proposals table)
- backend/qm_platform/risk/ (current subservice modules)
