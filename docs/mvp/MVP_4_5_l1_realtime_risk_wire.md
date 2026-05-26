# MVP 4.5 — L1 RealtimeRisk Chain Wire (Phase J §1.1 Option A Beat-driven)

> **Created**: iter 152 (2026-05-26) via §v9.69 multi-agent fan-out (Explore + architect parallel)
> **Sediment trigger**: §v9.56 pivot ladder Tier A§2 done → Tier A§1 Phase J 5 chain decomposition
> **Spec target**: ≤ 2 页 design doc per 铁律 24 + iter-friendly chunk decomposition per §v9.65
> **Provenance**: docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md §1.1 (Option A 3-7d effort estimate)

---

## §1 Problem Statement (Phase J §1.1 verified)

Phase J Defer Manifest §1.1 claims:
- L1 `RealtimeRiskEngine` — **0 production caller** ✅ VERIFIED iter 152
- L4 STAGED `planner.generate_plan` — **0 caller** ✅ VERIFIED iter 152
- L1 + L4 fully implemented + 10 rules registered + execution_plans schema ready, but **disconnected from production Beat schedule**

Production state per iter 152 Explore agent (`backend/qm_platform/risk/`):
- `RealtimeRiskEngine` (`realtime/engine.py:43-158`) — 3 cadences (on_tick / on_5min_beat / on_15min_beat), 10 rules registered via `rule_registry.py:41-97`
- `AlertDispatcher` (`realtime/alert.py:56-60`) — P0 immediate / P1+P2 buffered
- `L4ExecutionPlanner.generate_plan` (`execution/planner.py:208-223`) — returns `ExecutionPlan | None`
- Existing Beat: `risk-l4-sweep-1min` processes already-created PENDING_CONFIRM (empty queue since 0 source); `meta-monitor-tick` reads heartbeat only

**Gap**: No entry point exists to instantiate engine + feed tick data + dispatch alerts + persist plans in production. Result: zero RuleResult → zero ExecutionPlan → l4_sweep runs empty.

---

## §2 Option A Design Sketch

Beat-driven path (per Phase J Defer Manifest §1.1 Option A):
```
realtime-risk-tick Beat (1min, 9-14h)
  → RealtimeRiskContextBuilder (Redis: portfolio:current + market:latest:*)
  → RealtimeRiskEngine.on_tick(ctx) → list[RuleResult]
  → AlertDispatcher.dispatch (P0 immediate DingTalk / P1+P2 buffer)
  → L4ExecutionPlanner.generate_plan(P0 result) → ExecutionPlan
  → execution_plans INSERT + risk_event_log audit row
  → existing risk-l4-sweep-1min picks up PENDING_CONFIRM
```

**Pattern reuse** (sibling iter 132 LL-204 canonical):
- `meta_monitor_tasks.py:116-189` audit envelope template (try/finally `_write_scheduler_log_safe`)
- 铁律 32: Celery task = transaction owner (explicit commit/rollback)
- 铁律 33: fail-loud OR fail-soft with `# silent_ok`
- 铁律 44 X9: Beat schedule change → post-merge Servy restart documented

---

## §3 Chunk Decomposition (6 chunks, iter 152→158)

### Chunk 1 — L1 Context Builder Service (~150 LOC) — iter 153
- **Goal**: Service reads Redis (QMTClient) + builds `RiskContext` from live positions + market ticks.
- **Files**: NEW `backend/app/services/risk/realtime_context_builder.py`
- **New Beat**: No / **New DB**: No
- **Risk**: Redis stale data → mitigation: TTL check on `market:latest:*` keys, raise `PositionSourceError` if stale > 120s
- **Test**: pytest mock Redis, verify RiskContext with 0/1/5 positions + stale-data exception

### Chunk 2 — L1 Beat Task Shell + Engine Bootstrap (~200 LOC) — iter 154
- **Goal**: Celery task `realtime_risk_tick` instantiates RealtimeRiskEngine + `register_all_realtime_rules` + builds context via Chunk 1 + runs `on_tick()` + `on_5min_beat()`. Audit envelope per meta_monitor canonical.
- **Files**: NEW `backend/app/tasks/realtime_risk_tasks.py` + MODIFY `beat_schedule.py` + MODIFY `celery_app.py` imports
- **New Beat**: ✅ `realtime-risk-tick`, `crontab(minute="*/1", hour="9-14", day_of_week="1-5")`, expires=45
- **New DB**: No (uses existing scheduler_task_log)
- **Risk**: Beat collision with `risk-l4-sweep-1min` (same cadence) → mitigation: Beat sequential dispatch + `--pool=solo` tolerates (both cheap)
- **Dependency**: Chunk 1
- **Test**: pytest verify task registration + mock context builder + 10-rule fire + scheduler_task_log row

### Chunk 3 — DynamicThreshold Cache Wire (S7→S5) (~80 LOC) — iter 155
- **Goal**: Wire `RedisThresholdCache` into engine bootstrap so `_apply_dynamic_thresholds` reads real thresholds from existing `risk-dynamic-threshold-5min` Beat output.
- **Files**: MODIFY `realtime_risk_tasks.py` (`engine.set_threshold_cache` call)
- **Risk**: Threshold cache empty during non-trading hours → mitigation: engine already handles `cache is None` gracefully (`engine.py:98-99`)
- **Dependency**: Chunk 2
- **Test**: pytest verify threshold cache integration + mock Redis threshold keys + `update_threshold` called on rules

### Chunk 4 — AlertDispatcher Wire (P0 DingTalk) (~120 LOC) — iter 156
- **Goal**: Wire AlertDispatcher into Chunk 2 task. P0 RuleResults dispatch immediately via existing `dingtalk_alert.send_with_retry`. P1+P2 buffered + flush on 5min beat.
- **Files**: MODIFY `realtime_risk_tasks.py`
- **Risk**: DingTalk spam on false positives during paper-mode → mitigation: `execution_mode` guard — paper-mode logs but suppresses send. `MAX_BUFFER_SIZE=1000` safety net (`alert.py:53`)
- **Dependency**: Chunk 3
- **Test**: pytest mock `send_fn` + P0 immediate dispatch + P1 buffer/flush + paper-mode suppression

### Chunk 5 — L4 Planner Wire (P0 → ExecutionPlan) (~180 LOC) — iter 157
- **Goal**: P0 alert → `L4ExecutionPlanner.generate_plan(result)` → PENDING_CONFIRM ExecutionPlan → execution_plans INSERT + risk_event_log audit row. Transaction owned by Celery task (铁律 32).
- **Files**: MODIFY `realtime_risk_tasks.py` + NEW/MODIFY persistence service for execution_plans INSERT
- **Risk**: `STAGED_ENABLED=false` default (ADR-027) → plans go straight to CONFIRMED. Correct for initial wire: OFF mode = immediate execution path, existing l4_sweep picks up CONFIRMED within 60s.
- **Dependency**: Chunk 4
- **Test**: pytest verify plan from mock P0 RuleResult + DB row verification (execution_plans + risk_event_log) + OFF vs STAGED mode branching

### Chunk 6 — Integration Smoke + Calendar Gate (~100 LOC) — iter 158
- **Goal**: `is_trading_day_today_or_skip()` calendar gate (per H4 fix pattern, `beat_schedule.py:26-30`). Smoke test marker. E2E verify: Beat fire → context build → engine evaluate → alert dispatch → plan persist → scheduler_task_log row.
- **Files**: MODIFY `realtime_risk_tasks.py` + NEW `backend/tests/test_realtime_risk_beat_smoke.py`
- **Risk**: Smoke flaky on non-trading-day CI → mitigation: mock `is_trading_day_today_or_skip`
- **Dependency**: Chunks 1-5 merged
- **Test**: `pytest -m smoke` integration test + SQL verify scheduler_task_log + execution_plans rows

---

## §4 Cross-cutting

### ADR-DRAFT
- "L1 production runner: Beat task (Option A) vs dedicated Servy process (Option C)" — document why Beat 1min cadence is sufficient for Top-20 portfolio (10 rules × 20 positions = 200 evaluations << 45s budget), and under what scale threshold Option C becomes necessary.

### Frontend parity (§v9.43)
- Tier B Wave 5 MVP 5.2 (Risk Dashboard) would visualize: `risk_event_log` rows + `execution_plans` state machine + L1 heartbeat
- No frontend chunk in this wire — data layer only. MVP 5.2 deferred to Wave 5.

### Reality verification (§v9.49 post-deploy)
- SQL: `SELECT count(*) FROM scheduler_task_log WHERE task_name='realtime_risk' AND start_time > NOW() - INTERVAL '1 hour'` should show ~30 rows (1/min × 30min trading window)
- Log grep: `celery.realtime_risk_tasks` for `[realtime-risk-beat] tick complete`
- DingTalk test: manual `redis-cli DEL market:latest:600519.SH` → stale data alert fires within 60s

### Recommended order
**Chunk 1 → 2 → 3 → 4 → 5 → 6**

Rationale: 1+2 establishes Beat loop (verifiable immediately via scheduler_task_log). Chunk 3 before 4 because threshold wire is low-risk + makes engine evaluation meaningful before alerts go live. Chunk 4 before 5 because alerts are prerequisite for plan generation. Chunk 6 last as integration gate.

---

## §5 Risk + STOP triggers

- **§6 carve-out**: If paper-mode DingTalk spam > 10 alerts/hour during dry-run, STOP + add rate-limiter before Chunk 4
- **User authorization gates**:
  - (a) Beat cadence decision: 1min vs 30s — recommend **1min initially** (matches `risk-l4-sweep-1min` precedent)
  - (b) `STAGED_ENABLED` flip false→true requires separate user decision (ADR-027 5 prerequisites)
  - (c) Post-merge Servy restart per 铁律 44 X9 — sustained from iter 142+143 W2_A_RUNTIME_REVERIFY blocker (currently still pending elevated shell)
- **红线 5/5 sustained**: cash ¥993,520.66 / 0 持仓 / paper / true / 81001102 — wire operates paper-mode only

---

## §6 Effort estimate

Per Phase J Defer Manifest §1.1: **3-5 days** (matches architect agent estimate). At 1 chunk per iter cadence (~30-60 min iter), expect **iter 153-158 = 6 iter cumulative**.

Post Chunk 6 closure: L1 RealtimeRiskEngine has live production caller + L4 ExecutionPlanner produces real PENDING_CONFIRM plans + existing l4-sweep wire activates. Phase J §1.1 + §1.2 closed (1.2 covered via §1.1 chain upstream).

Phase J remaining post §1.1+§1.2: §1.3 daily_reconciliation schtask + §1.4 RAG consumer + §1.5 trade event StreamBus polling gap.

---

**Provenance**: iter 152 §v9.69 multi-agent fan-out — Explore agent (file:line inventory) + architect agent (decomp design). All file:line cites verified at 2026-05-26 ~14:30 SH. Sibling pattern `meta_monitor_tasks.py` iter 132 LL-204 canonical.
