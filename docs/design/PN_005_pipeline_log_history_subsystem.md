# PN-005: Pipeline Log History Subsystem (D1 O7) — Design + Scope Assessment

> **Status**: DRAFT (iter 21, 2026-05-24)
> **Verdict**: **DEFER** pending product input — see §8.
> **Scope**: D1 O7 "log-history endpoint" final remaining frontend orphan per F-XS-1 sediment (iter 17). On scope-honest investigation surfaced as a 4-component subsystem, not a single missing endpoint.
> **Author**: L4+R loop CC (Inner-loop-B design step 3)
> **Related**: ADR-087 (PN-001 automation_level) / ADR-088 (PN-002 correlation-prune) / ADR-089 (PN-003 pipeline pause) / ADR-090 (PN-004 /status contract). ADR-091 candidate slot reserved for this PN if/when user approves IMPLEMENT.

---

## §1 Background — Current State (verified by code-grep, iter 21)

Frontend `PipelineConsole.tsx` shows an "AI决策日志" tab (line 47, tab #4 of 5) that consumes pipeline log entries. The tab is wired against two backend interfaces, **neither of which exists today**:

| Frontend reference | Backend reality |
|---|---|
| `getPipelineLogs(runId)` calling `GET /pipeline/{runId}/logs` (api/pipeline.ts:177-182) | **No `@router.get(...)` for this path in any backend module.** API_COVERAGE.md §6.1 O7 row. |
| `new WebSocket('/ws/pipeline/${status.run_id}')` (PipelineConsole.tsx:174) | **No `/ws/pipeline/{run_id}` endpoint in any FastAPI WebSocket route. Backend `websocket/manager.py` only handles `backtest:{run_id}` rooms.** |

Beyond the 2 missing read-side endpoints, **no write-side emission exists either**:
- No `pipeline_run_logs` table (verified `migrations/`).
- No `pipeline_runs.logs` JSONB column (DDL `pipeline_runs` at QUANTMIND_V2_DDL_FINAL.sql:777).
- No `qm:pipeline:*` Redis Streams or list publishing path (grep `qm:pipeline` → 0 hits).
- No instrumentation in `run_gp_mining` / `run_bruteforce_mining` / pipeline orchestration tasks emitting structured log events.

In other words, the "AI决策日志" tab today is a frontend skeleton with **0 backend infrastructure**. The previous F-XS-1 sediment iter 17 line "still receives live logs via ws/pipeline/{run_id} WebSocket during an active run" was aspirational copy — verified false by code-grep iter 21. **META-finding repeat of RN-001 §6**: candidate that "looked partially built" was actually entirely absent. Code-grep-verify before any IMPLEMENT verdict.

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
| C1 | Storage schema | `migrations/pipeline_run_logs.sql` OR Redis list spec OR file rotation policy | small if Redis, medium if DB | gates everything else |
| C2 | Emission path | Instrumentation in run_gp_mining / run_bruteforce_mining / Phase 3 LLM agent tasks | medium-large | needs to find every "decision event" call site |
| C3 | WebSocket live-stream | `backend/app/websocket/manager.py` extension or new pipeline_ws.py module | small once C1+C2 land | live consumption during active run |
| C4 | HTTP backfill | `@router.get('/pipeline/{run_id}/logs')` in `api/pipeline.py` | small once C1 lands | historical replay for completed runs |

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
2. **Emission helper** (`backend/app/services/pipeline_log.py`):
   ```python
   def emit_pipeline_log(*, run_id: str, agent: str, level: Literal["info","warning","error","decision"], content: str) -> None:
       """LPUSH JSON-encoded log entry + LTRIM maxlen. Fail-safe (silent on Redis down per 铁律 33 silent_ok marker)."""
   ```
   This is the contract that pipeline tasks call. Single function signature, no Service-layer.
3. **WebSocket live-stream** (C3, `/ws/pipeline/{run_id}`): pub/sub or per-connection LRANGE polling at 1s cadence. Simpler: client opens WS, server reads recent + tails new via Redis Pub/Sub on `qm:pipeline:logs:{run_id}` channel.
4. **HTTP backfill** (C4, `GET /pipeline/{run_id}/logs?limit=1000`): LRANGE the Redis list, JSON-decode, return as `PipelineLogEntry[]`. Pydantic model + endpoint in `api/pipeline.py`.
5. **Instrumentation** (C2): grep `pipeline_runs` callers (mining_tasks.py / run_gp_mining etc) and add `emit_pipeline_log(...)` at decision points. Probably 5-15 call sites total. For decision-level emissions specifically, integrate with the AI evolution `dual-write` Celery Beat pattern.

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

All NEGATIVE → design itself is loop-permissible. IMPLEMENT decision requires §6 product input.

## §8 Verdict + Sediment

**Verdict: DEFER pending product input** per Q1-Q5 above.

Rationale:
1. Honest scope: this is a 4-component feature subsystem, not a 1-endpoint orphan. Implementing without product input on retention + semantics risks rework on the storage choice (b vs c is a 2-3x scope swing depending on retention answer).
2. Coupling to PT restart sequencing: Q4 + the AI evolution overlap Q5 suggests this should land coordinated with the broader V3 §3.2/§5.2/§8.4 prompt-driven agent infrastructure rollout, not as a standalone Inner-loop-B cycle.
3. Frontend impact is already graceful (404 silently handled by `try/catch` per F-XS-1 iter 17 sediment); the "AI决策日志" tab shows empty state but doesn't break the UX flow.

**Why not ARCHIVE**: feature has genuine value (debugging pipeline runs, audit trail for L0-L3 automation decisions). Not dead code.

**Why not IMPLEMENT a smaller subset (e.g. only C4 with a stub-empty response)**: stub-only would close the orphan visually but provide 0 product value; would also require maintaining a stub through the eventual real implementation. Cleaner to surface the DEFER with concrete product questions than to ship technical debt.

**Sediment locations**:
- This document (PN-005 draft).
- `.omc/state/l4r_loop_state.md` iter 21 entry (DEFER verdict).
- `docs/API_COVERAGE.md` §6.1 O7 row already accurately reflects "STILL ORPHAN ... gap is the absence of an HTTP log-history backfill" — extend with reference to this PN-005 doc.
- META-finding (RN-001 §6 repeat): "AI决策日志 ws/pipeline live-stream" claim in iter 17 F-XS-1 sediment was aspirational copy, verified false iter 21. Sustained anti-pattern reminder: code-grep-verify before sediment.

**Ratio impact**: iter 21 defer → 11:2:5 = 61.1% (sustained mid-band; §4.5 guard sustained-released).

**User redirect surface** (§4.1 control surface): if user wants D1 O7 IMPLEMENT, please answer Q1-Q5 in §6 + indicate scope preference (MVP Redis-only per §5 vs DB-persistent per §4 option b). Otherwise this defers indefinitely until PT-restart + AI evolution Phase 3 sequencing surfaces a natural integration point.
