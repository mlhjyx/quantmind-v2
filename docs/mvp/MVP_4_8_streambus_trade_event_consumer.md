# MVP 4.8 — Trade Event Risk Consumer Wire (Phase J §1.5)

> **Created**: iter 183 (2026-05-26) via §v9.69 multi-agent fan-out (Explore + oh-my-claudecode:architect parallel, ~7.5min wallclock)
> **Sediment trigger**: §v9.56 pivot ladder — Phase J §1.4 MVP 4.7 closed iter 178; §1.5 next Tier A§1
> **Spec target**: ≤ 2 页 design doc per 铁律 24 + sibling MVP_4_5/4_6/4_7 structure
> **MAJOR reality catch (§v9.49)**: Manifest §1.5 claim "no event publish" is **STALE**. Outbox publisher already wires `qm:fill:executed` stream since MVP 3.4 batch 5 (PR #130 2026-04-28). True gap is subscriber-side, not publisher-side.

---

## §1 Problem Statement (Phase J §1.5 reality re-grounded iter 183)

**Manifest §1.5 claim (2026-05-20)**:
> "trade_log INSERT 后 → 风控流 trigger 隐式 (无显式 publish event). 当前依赖 5min Beat risk-l4-sweep-1min polling. 真后果: 真发单 → tick 级风控介入 ~60s gap, live-mode 不可接受"

**Reality re-grounded iter 183** (per LL-209 §v9.49 + LL-211 4-layer SOP applied at design time):
- `execution_service.py:266-282` (paper) + `execution_service.py:472-488` (live): `OutboxWriter(conn).enqueue(aggregate_type="fill", event_type="executed", ...)` already runs in same tx as trade_log INSERT (MVP 3.4 batch 5, PR #130, 2026-04-28)
- `outbox_publisher_tick` 30s Beat (`outbox_publisher.py:151-153`): picks up event_outbox + publishes to Redis Stream `qm:fill:executed`
- `stream_bus.py:36-42`: `qm:trade:*` prefix DEPRECATED per Plan v8 P1-30; business events MUST use outbox publisher pattern (already in use for fills)
- `realtime_risk_tasks.py:244-397`: 1min Beat builds context from Redis positions/market data but does NOT XREAD from any event stream

**True gap**: NOT "no event publish" but **0 consumer subscribes to `qm:fill:executed` for risk evaluation**. Fill events flow into Redis Streams; nobody reads them on the risk side.

**Net production impact**: same as manifest described (~60s gap), but root cause is subscriber absence, not publisher absence. Manifest claim is partial-stale sibling pattern to iter 164 / iter 175 / iter 179 §v9.49 reality catches.

---

## §2 Design Sketch

Wire path (consumer-only — reuses entire existing outbox/stream infra):
```
trade_log INSERT + OutboxWriter.enqueue (same tx) — ALREADY WIRED
  → outbox_publisher_tick 30s Beat — ALREADY RUNNING
  → Redis Stream qm:fill:executed — ALREADY PUBLISHED
  → [NEW iter 184-188] trade_event_risk_consumer 10s Beat
    → XREADGROUP qm:fill:executed (consumer group: risk-engine-fill-consumer)
    → per fill event: RealtimeRiskContextBuilder.build_context()
    → RealtimeRiskEngine.on_tick(ctx) [reuse MVP 4.5 Chunk 2 singleton]
    → AlertDispatcher.dispatch P0 [reuse MVP 4.5 Chunk 4 singleton]
    → L4ExecutionPlanner.generate_plan → execution_plans + risk_event_log INSERT [reuse MVP 4.5 Chunk 5 persist_plan_with_audit]
    → scheduler_task_log audit envelope row
```

**3 critical design decisions** (validated by architect agent against fresh code reads):

1. **Event source = Option B (Outbox reuse, ALREADY WIRED)**. No new publisher code. `qm:trade:*` deprecation guard at `stream_bus.py:36-42` BLOCKS direct `publish_sync` per Plan v8 P1-30. Manifest's implicit Option A (direct publish) would violate this. Option C (hybrid) adds complexity for 0 benefit.

2. **Subscriber = Option Y (New `trade_event_risk_consumer` Celery Beat, 10s cadence)**. Option X (modify existing 1min Beat with XREAD BLOCK) rejected: blocks solo worker thread; mixes cadence-driven with event-driven concerns. Option Z (Servy daemon) rejected: paper-mode ~5/day + live ~10-50/day throughput doesn't justify dedicated process. XREADGROUP non-blocking + consumer group at-least-once delivery + 10s cadence = ~40s worst-case latency vs current ~60s.

3. **Event schema = existing outbox payload + DB fetch on demand**. Outbox payload already contains `{strategy_id, exec_date, fill_count, nav, mode}` (`execution_service.py:273-281`). Consumer fetches full trade_log rows only when needed (1 DB query / event, cheap at 5-50 trades/day). No schema change.

**Pattern reuse**:
- `realtime_risk_tasks.py` lazy singleton pattern (engine + builder + dispatcher + planner) — MVP 4.5 Chunks 1-5 canonical
- `_write_scheduler_log_safe` audit envelope (LL-204 canonical)
- 铁律 32 (Celery task = transaction owner) + 铁律 33 (fail-soft on XREAD empty) + 铁律 44 X9 (Beat changes → Servy restart documented)

---

## §3 Chunk Decomposition (5 chunks, iter 184→188)

| Chunk | Goal | LOC | Iter | Risk | Dep | Test approach |
|---|---|---|---|---|---|---|
| 1 | XREAD consumer group helper (`trade_event_consumer.py`) | ~80 | 184 | LOW | None | TDD mock Redis XREADGROUP + last_id tracking + consumer group MKSTREAM |
| 2 | Beat task shell + scheduler_task_log audit envelope | ~120 | 185 | LOW | Chunk 1 | TDD task registration + mock XREAD (0/1/3 events) + audit log row |
| 3 | Engine re-evaluation wire (context + on_tick per fill) + idempotency Redis SET | ~100 | 186 | MID (1min Beat double-eval safety) | Chunk 2 | TDD mock context+engine + idempotency replay guard |
| 4 | Alert + L4 Planner wire (reuse MVP 4.5 singletons) | ~80 | 187 | LOW | Chunk 3 | TDD mock dispatcher/planner + P0 fill-triggered breach |
| 5 | Integration smoke + Calendar gate + manifest closure + LL append | ~70 | 188 | LOW | Chunks 1-4 | pytest -m smoke E2E + PHASE_J §1.5 stale-claim sediment |

**Total**: ~450 LOC across 5 chunks. Estimated iter 184-188 (5 iter cumulative) + iter ~189 buffer for reviewer cycles.

**Recommended order**: 1 → 2 → 3 → 4 → 5 strict sequential.

---

## §4 Cross-cutting

### ADR-DRAFT candidates
- **"Trade event risk consumer: outbox reuse vs direct StreamBus"** — Plan v8 P1-30 deprecation guard analysis + sibling MVP 3.4 batch 5 pattern reuse rationale
- **"Consumer group naming convention for Redis Streams"** — first consumer group in codebase; convention `{service}-{stream}-consumer` (e.g. `risk-engine-fill-consumer`)

### Frontend parity (§v9.43)
- Tier B Wave 5 MVP 5.2 Risk Dashboard could visualize fill-triggered risk evaluations via new `scheduler_task_log` rows with `task_name='trade_event_risk_consumer'`. No frontend chunk in this MVP.

### Reality verification (§v9.49 + LL-211 post-deploy)
- SQL Layer 4 check: `SELECT count(*) FROM scheduler_task_log WHERE task_name='trade_event_risk_consumer' AND start_time > NOW() - INTERVAL '1 hour'` → expect ~360 rows (10s × 60min trading window)
- Redis Layer 3 check: `redis-cli XINFO GROUPS qm:fill:executed` → verify consumer group exists + last-delivered-id advancing
- Latency Layer 4 verify: trigger `paper_broker.save_fills_only` → monitor `scheduler_task_log` for `events_processed > 0` within 40s

### LL-211 4-layer SOP application at design time
This MVP applies LL-211 retrospectively — manifest claim "no event publish" was REFUTED by Layer 3 verification (architect read `execution_service.py:266-282` and confirmed outbox enqueue exists). 5-iter chain (164/175/179/164's daily_reconciliation + 175's factor_values + 179's compute_daily_ic + this iter 183 for §1.5) all show same pattern: **design manifest claims systematically lag actual code state**. Future MVP design phase MUST fresh-read code BEFORE accepting manifest claim verbatim.

### Recommended chunk order rationale
Chunk 1 first (XREAD helper foundation). Chunk 2 (Beat shell makes helper observable). Chunk 3 before 4 (engine eval produces results consumed by alert/planner). Chunk 5 last (integration gate + governance closure + manifest correction).

---

## §5 Risk + STOP triggers

- **§6 carve-out**: 0 .env mutation / 0 broker write / 0 production DB row mutation (consumer is read-only; new INSERTs to `scheduler_task_log` + `risk_event_log` + `execution_plans` reuse MVP 4.5 wire — paper-mode dormant).
- **Runtime regression on existing trade_log flow**: NONE across all 5 chunks. Consumer is XREADGROUP-only; 0 mutation to existing outbox/publisher/stream/execution paths.
- **1min Beat double-eval safety**: Both `realtime_risk_tick` (1min) and `trade_event_risk_consumer` (10s on fill events) may evaluate engine.on_tick. Safe because RuleResult is idempotent (pure function of context state); 1min Beat catches any consumer-missed events (defense-in-depth).
- **User authorization gates**:
  - (a) Beat cadence (10s consumer vs 30s outbox) — if 40s latency SLA insufficient for live multi-position, user decides outbox cadence reduction separately (post-MVP closure)
  - (b) Post-merge Servy restart per 铁律 44 X9 (sustained iter 142+143 blocker; LL-210 ship 三态 marker pending)
- **红线 5/5 sustained**: cash ¥993,520.66 / 0 持仓 / paper / true / 81001102 — consumer is read-only, paper-mode safe

---

## §6 Effort estimate

Per Phase J Defer Manifest §1.5: **~1 week**. At 1 chunk per iter (~30-60min), expect **iter 184-188 = 5 iter cumulative** plus iter ~189 buffer.

Post Chunk 5 closure:
- `qm:fill:executed` stream has its first production consumer
- Fill events trigger targeted risk evaluation within ~40s (vs current ~60s, ~33% improvement)
- **Phase J §1.1 + §1.2 + §1.3 + §1.4 + §1.5 ALL closed** (Phase J 5-chain backlog complete after MVP 4.8)
- backend-only ✅ per LL-210; runtime-verified pending Servy unblock (Tier A§5 user touchpoint sustained)

Phase J remaining post §1.5: 0 — Phase J chain complete. Future Tier A scope shifts to Tier B Wave 5 Operator UI / Tier C AI 闭环 / Tier D alpha research per /goal v9.7 4-Tier roadmap (gated on Tier A runtime-verified ship which requires Servy unblock).

---

**Provenance**: iter 183 §v9.69 multi-agent fan-out — Explore agent (141 files read across 12 parallel Glob/Grep/Read passes; surfaced manifest stale claim via Layer 3 code verification) + oh-my-claudecode:architect agent (3 design decisions + 5-chunk decomposition + ADR-DRAFTs + risk + trade-off table, ~7.5min wallclock). All file:line cites verified fresh at 2026-05-26 ~19:30 SH. Sibling pattern: MVP 4.5/4.6/4.7 design structures + MVP 3.4 batch 5 outbox publisher canonical.

**iter 183 ship 三态 per LL-210**: backend-only ✅ doc-sediment scope (design doc only, 0 code change, 0 mutation surface).
