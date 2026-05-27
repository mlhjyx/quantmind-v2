# PN-005: Pipeline Log History Subsystem (D1 O7) — Design + Scope Assessment

> **Status**: DRAFT (iter 21, 2026-05-24)
> **Status addendum 2026-05-28**: HTTP backfill + first writer instrumentation implemented. Remaining scope: broader pipeline task instrumentation, optional WebSocket live tailing, and durable-retention decision.
> **Verdict**: **PARTIAL IMPLEMENT** — O7 frontend-only orphan closed; PN-005 subsystem still has enhancement backlog.
> **Scope**: D1 O7 "log-history endpoint" final remaining frontend orphan per F-XS-1 sediment (iter 17). On scope-honest investigation surfaced as a 4-component subsystem, not a single missing endpoint.
> **Author**: L4+R loop CC (Inner-loop-B design step 3)
> **Related**: ADR-087 (PN-001 automation_level) / ADR-088 (PN-002 correlation-prune) / ADR-089 (PN-003 pipeline pause) / ADR-090 (PN-004 /status contract). ADR-091 candidate slot reserved for this PN if/when user approves IMPLEMENT.

---

## §1 Background — Current State (verified by code-grep, iter 21)

Frontend `PipelineConsole.tsx` shows an "AI决策日志" tab (line 47, tab #4 of 5) that consumes pipeline log entries. As of 2026-05-28, the HTTP backfill interface exists; WebSocket live tailing remains missing:

| Frontend reference | Backend reality |
|---|---|
| `getPipelineLogs(runId)` calling `GET /pipeline/{runId}/logs` (api/pipeline.ts) | **Implemented 2026-05-28** in `backend/app/api/pipeline.py` as Redis-list HTTP backfill. |
| `new WebSocket('/ws/pipeline/${status.run_id}')` (PipelineConsole.tsx:174) | **No `/ws/pipeline/{run_id}` endpoint in any FastAPI WebSocket route. Backend `websocket/manager.py` only handles `backtest:{run_id}` rooms.** |

Beyond the 2 missing read-side endpoints, **no write-side emission exists either**:
- No `pipeline_run_logs` table (verified `migrations/`).
- No `pipeline_runs.logs` JSONB column (DDL `pipeline_runs` at QUANTMIND_V2_DDL_FINAL.sql:777).
- No `qm:pipeline:*` Redis Streams or list publishing path (grep `qm:pipeline` → 0 hits).
- Partial instrumentation exists for manual trigger / approve / reject decision events via `backend/app/services/pipeline_log.py`. Broader mining task instrumentation in `run_gp_mining` / `run_bruteforce_mining` remains open.

In other words, the "AI决策日志" tab is no longer a pure frontend skeleton: it has a backend HTTP reader and first decision-event writer call sites. The previous F-XS-1 sediment iter 17 line "still receives live logs via ws/pipeline/{run_id} WebSocket during an active run" remains aspirational for WebSocket live tailing — verified false by code-grep iter 21. **META-finding repeat of RN-001 §6**: code-grep-verify before any IMPLEMENT verdict.

## §2 Use Case (assumed, requires product confirmation)

User opens PipelineConsole → "AI决策日志" tab → expects to see a list of timestamped, agent-tagged, level-classified, content-bearing log entries from the most recent (or selected) pipeline run. Live updates during an active run, historical backfill for completed runs.

Frontend `PipelineLogEntry` contract (api/pipeline.ts:95-102):
```typescript
{ id: string, run_id: string, timestamp: string,
  agent: string,  // who emitted the line — agent name
  level: "info" | "warning" | "error" | "decision",
  content: string }
```

The `level: "decision"` enum value suggests the use case isn't generic application logging but **agent decision events** — the L0-L3 automation levels making auditable judgment calls. This is more aligned with the V3 AI risk reflection / Bull-Bear / RAG decision pipeline than with general infrastructure logging.

## §3 Scope Inventory (4-component subsystem)

A complete D1 O7 closure requires all four:

| # | Component | Backend file | Complexity | Notes |
|---|---|---|---|---|
| C1 | Storage schema | Redis list `pipeline:logs:{run_id}` | ✅ implemented | DB history remains future option |
| C2 | Emission path | Trigger / approve / reject now emit; broader run_gp_mining / run_bruteforce_mining / Phase 3 LLM agent tasks remain | partial | needs to find every "decision event" call site |
| C3 | WebSocket live-stream | `backend/app/websocket/manager.py` extension or new pipeline_ws.py module | small once C1+C2 land | live consumption during active run |
| C4 | HTTP backfill | `@router.get('/pipeline/{run_id}/logs')` in `api/pipeline.py` | ✅ implemented | Redis recent-log replay |

Total: probably 200-400 lines of code + 1 migration + frontend type alignment verification.

## §4 Storage Option Trade-offs (C1)

| Option | Persistence | Query | Retention | Cost | Notes |
|---|---|---|---|---|---|
| **(a) File rotating** | survives restart | grep / cat / line-scan | manual rotation policy | low | doesn't index by run_id efficiently; harder to query from API |
| **(b) DB events table** `pipeline_run_logs(run_id UUID FK, ts TIMESTAMPTZ, agent VARCHAR, level VARCHAR, content TEXT)` | persistent | indexed by run_id + ts | partition by week, drop old partitions | medium | sticks well with铁律 17 DataPipeline path; allows analytics |
| **(c) Redis list** `pipeline:logs:{run_id}` LRANGE + maxlen=10000 LPUSH | ephemeral (lost on Redis restart) | fast LRANGE per run_id | implicit via maxlen | low | matches the "live + recent only" use case if no historical replay needed |
| **(d) Event-sourced stream** `qm:pipeline:run_log` Redis Streams XADD/XRANGE | bounded (maxlen) | XRANGE by ID + filter run_id | implicit via maxlen | low | replay-able; integrates with existing StreamBus pattern |

**Recommendation** (subject to product confirmation in §6): start with **(c) Redis list per run_id** for MVP — simplest, matches use case if retention need is "current + recent runs only", no schema migration overhead. If/when user requests historical-replay-for-debugging beyond ~10 most recent runs OR requires analytics over decision events, **promote to (b) DB events table** as Phase 2.

## §5 MVP Design Sketch (if user picks IMPLEMENT)

Smallest-first MVP using option (c):

1. **Storage** (C1): Redis list `pipeline:logs:{run_id}` with `LPUSH` + `LTRIM 0 9999` (maxlen 10K lines per run). Lines are JSON-encoded `PipelineLogEntry` objects.
2. **Emission helper** (`backend/app/services/pipeline_log.py`) — **implemented 2026-05-28**:
   ```python
   def emit_pipeline_log(*, run_id: str, agent: str, level: Literal["info","warning","error","decision"], content: str) -> None:
       """LPUSH JSON-encoded log entry + LTRIM maxlen. Fail-safe (silent on Redis down per 铁律 33 silent_ok marker)."""
   ```
   This is the contract that pipeline tasks call. Single function signature, no Service-layer.
3. **WebSocket live-stream** (C3, `/ws/pipeline/{run_id}`): pub/sub or per-connection LRANGE polling at 1s cadence. Simpler: client opens WS, server reads recent + tails new via Redis Pub/Sub on `qm:pipeline:logs:{run_id}` channel.
4. **HTTP backfill** (C4, `GET /pipeline/{run_id}/logs?limit=1000`): LRANGE the Redis list, JSON-decode, return as `PipelineLogEntry[]`. Pydantic model + endpoint in `api/pipeline.py` — **implemented 2026-05-28**.
5. **Instrumentation** (C2): trigger / approve / reject decision events implemented 2026-05-28. Next pass should grep `pipeline_runs` callers (mining_tasks.py / run_gp_mining etc) and add `emit_pipeline_log(...)` at remaining decision points.

Estimated LOC: ~300 backend + ~50 test + 0 frontend (already wired).

## §6 Open Product Questions (gate to IMPLEMENT)

1. **Retention**: Is "recent runs only via Redis list" sufficient, or does user need historical replay of completed runs from N days ago for debugging?
2. **Semantics**: What constitutes a "log line"? Every node entry/exit? Only decision-level agent events? Errors only?
3. **Scope of `agent`**: Are agents named entities (NewsClassifier / BullBear / RiskReflector) or generic ("orchestrator" / "scheduler")?
4. **PT-paused state coupling**: Pipeline tasks are largely dormant during PT pause (0 trades since 4-29). Is post-PT-restart the right time to instrument? Or do we want logs for paper-mode rehearsal runs too?
5. **AI evolution overlap**: DEV_AI_EVOLUTION V2.1 (Layer 3-4 Q3-Q4 trigger per ADR-028) defines its own "decision event" semantics. Does this PN-005 subsume that or coexist?

## §7 §6 8-Trigger STOP Self-Check on this design

| # | Trigger | Verdict |
|---|---------|---------|
| 1 | Framework 新加 | NEGATIVE — no new Framework, builds within existing pipeline + StreamBus + WebSocket layers |
| 2 | Architecture 大改 | NEGATIVE — feature subsystem within existing 5+1 layer, doesn't change boundaries |
| 3 | Strategy 改动 | NEGATIVE |
| 4 | 红线 5/5 触碰 | NEGATIVE |
| 5 | PT 重启 gate | NEGATIVE in design; IMPLEMENT phase may want to coordinate with PT restart sequencing per Q4 above |
| 6 | 新引擎 | NEGATIVE — no new factor/risk/backtest engine |
| 7 | Beat schedule 改 | NEGATIVE |
| 8 | Self-protection (loop spec) | NEGATIVE |

All NEGATIVE → design itself is loop-permissible. The 2026-05-28 implementation
lands the Redis MVP path without touching redline surfaces; §6 remains useful
for future DB retention / WebSocket scope decisions.

## §8 Verdict + Sediment

**Verdict: PARTIAL IMPLEMENT + enhancement backlog**.

Rationale:
1. Honest scope: this is a 4-component feature subsystem, not a 1-endpoint orphan.
   The Redis MVP closes the API orphan and provides first real decision events
   without forcing a DB retention decision.
2. Broader instrumentation should still be sequenced with the AI evolution
   pipeline rollout, because "decision event" semantics should not fork across
   mining, LLM, and operator flows.
3. Frontend impact is now better than graceful empty-state handling: the tab can
   call a real backend route and show trigger / approve / reject events when they
   exist.

**Why not ARCHIVE**: feature has genuine value (debugging pipeline runs, audit trail for L0-L3 automation decisions). Not dead code.

**Why not stop at C4 only**: stub-only would close the orphan visually but provide 0 product value. The 2026-05-28 implementation therefore includes the Redis writer helper and first trigger / approve / reject writer call sites.

**Sediment locations**:
- This document (PN-005 draft).
- `.omc/state/l4r_loop_state.md` iter 21 entry (DEFER verdict).
- `docs/API_COVERAGE.md` §10 now records O7 HTTP backfill closure and remaining enhancement backlog.
- META-finding (RN-001 §6 repeat): "AI决策日志 ws/pipeline live-stream" claim in iter 17 F-XS-1 sediment was aspirational copy, verified false iter 21. Sustained anti-pattern reminder: code-grep-verify before sediment.

**Ratio impact**: O7 no longer counts as frontend-only orphan. Remaining PN-005
items count as enhancement backlog.

**Next decision surface**: if durable historical replay is needed, promote Redis
recent logs to the DB option in §4(b). If live tailing becomes operationally
important, add `/ws/pipeline/{run_id}` on top of the same Redis event contract.
