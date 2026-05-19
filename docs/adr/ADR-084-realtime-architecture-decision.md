# ADR-084: Real-time Data Push Architecture Decision (4 mechanisms → recommended subset)

> **Date**: 2026-05-19 (Session 58 round-3)
> **Status**: Proposed (留 user 决议 final approve)
> **Triggers**: ISSUES_PENDING_REGISTRY §4 A2 ("三套 real-time 并行")
> **Author**: CC autonomous batch 收口 Session 58
> **Backref**: ADR-003 (StreamBus event sourcing), ADR-012 (Wave 5 Operator UI), Frontend Design v3 §2.5 (real-time strategy)

---

## 1. Context

Current frontend uses **4 distinct real-time data push mechanisms** in parallel:

| Mechanism | Where | Cadence | Use case |
|---|---|---|---|
| **react-query refetchInterval** | most pages (Dashboard / Execution / Portfolio / RiskManagement) | 5-30s polling | NAV / positions / orders / drift |
| **setInterval direct** | SafetyControlPanel (10s) / EnvStateBanner (5s) / etc | 5-15s | Light status indicators |
| **socket.io WebSocket** | `app/websocket/` 全双工 server + `hooks/useWebSocket.ts` client | event-driven | Mining/backtest progress, signal updates |
| **SSE EventSource (NEW Session 58 round-2)** | `backend/app/api/sse.py` + frontend wire pending | event-driven server push | risk_event_log streaming |

This 4-way fragmentation creates:
- **Maintenance burden** — 4 different reconnection / error / lifecycle patterns
- **Inconsistent UX** — some data 5s stale, some real-time, some only on poll
- **Server load 不必要** — react-query repolling 等价信息 socket.io 可推
- **Debug complexity** — failure mode 各异 (poll fails silently / WS reconnect storms / SSE proxy buffering)

## 2. Decision Required

Pick a forward-looking architecture for real-time data:

### Option A: Consolidate to socket.io (full WebSocket)
- **Pros**: Full duplex (server push + client emit), mature ecosystem, fallback transports built-in
- **Cons**: Heavier protocol overhead, sticky-session 复杂 in horizontal scale, harder caching layer
- **Cost**: ~3-5 days migration (frontend hooks + backend event publish chain)

### Option B: Consolidate to SSE (server-sent events)
- **Pros**: Simple HTTP/1.1, native EventSource API, auto-reconnect built-in, easy to cache (HTTP)
- **Cons**: Server→Client only (no client emit), one-way limits some flows (mining progress 需 fallback)
- **Cost**: ~2-3 days migration

### Option C: Hybrid — react-query polling + SSE for true real-time + WS for full-duplex
- **Pros**: Use right tool per job. polling=stable for CRUD-like data, SSE=events, WS=interactive
- **Cons**: Still 3 mechanisms (better than 4 but not 1)
- **Cost**: ~1-2 days (formalize boundaries + drop setInterval direct + drop unnecessary react-query refetch for SSE-covered data)

### Option D: Status quo
- **Pros**: 0 cost
- **Cons**: 4-way fragmentation continues, debt compounds

## 3. Recommendation

**Option C (Hybrid with 3 explicit roles)** — pragmatic, lowest risk, biggest near-term ROI:

| Data type | Mechanism | Rationale |
|---|---|---|
| CRUD-like (orders, drift items, positions, daily summary) | react-query polling | Stable cadence, easy cache, easy revalidate-on-action |
| Event streams (risk_event_log inserts, system alerts, audit log) | SSE EventSource | Server push, no client emit needed |
| Interactive (mining progress, backtest live log, debug terminal) | socket.io WebSocket | Full duplex, client can emit control commands |
| **DROP** | `setInterval` direct | Replace with react-query for 5-15s polls (lifecycle consistency) |

### Migration scope (incremental, per page)

**Phase 1 (immediate, ~4h autonomous)**:
- SafetyControlPanel / EnvStateBanner / ShutdownBanner: setInterval → react-query (uniform lifecycle)
- Add SSE subscriber for risk_event_log (consumes ADR-085 future P4 scaffold currently MVP)

**Phase 2 (1-2 days)**:
- Identify all react-query `refetchInterval: <5s` calls → audit if SSE could replace
- Migrate /api/dashboard/alerts to SSE (currently 10s poll)
- Add SSE for execution_audit_log

**Phase 3 (留 future)**:
- Evaluate dropping socket.io for mining progress (replace with SSE + REST POST for control)
- Reduce to 2 mechanisms (react-query + SSE)

## 4. Constraints

- **Backward compat**: Existing react-query callers MUST continue working during migration (no big-bang)
- **Auth**: All SSE endpoints require `verify_admin_token` (sustained S1 cookie auth model)
- **Proxy compat**: SSE requires `X-Accel-Buffering: no` header (nginx) — verified in sse.py
- **Single-worker simplification**: Multi-worker SSE / WS需 sticky session OR Redis-pubsub fan-out (留 future scale-out)

## 5. Out of scope (留 follow-up ADRs)

- Backend event publish chain unification (currently StreamBus + Redis Streams + DB triggers fragmented — own ADR候选)
- Frontend store layer unification (Zustand + react-query + Context — see ADR-085 candidate)
- Mobile push-notification path (Phase H frontend redesign defer)

## 6. Rollout

After user approves this ADR:
1. Phase 1 autonomous (CC) — replace setInterval → react-query (4 components)
2. Wire SSE subscriber for risk_event_log in RiskManagement page
3. Phase 2-3 sustained sprint backlog

## 7. Related

- **ADR-003** (StreamBus event sourcing — server-side event publish foundation)
- **ADR-012** (Wave 5 Operator UI — Vue migration deferred, current React keeps real-time stack)
- **Frontend Design v3 §2.5** (Real-time strategy 是 architect 决议过, ADR-084 是 formalize)
- **ISSUES_PENDING_REGISTRY §4 A2** (4-way fragmentation surface)
- **Session 58 round-2 P4** (`backend/app/api/sse.py` scaffold — Option C 第一块拼图)
- **`backend/app/api/realtime.py`** (REST polling fallback — sustained per ADR-008 namespace contract)

---

**End ADR-084.**
