# ADR-058: V3 §S8 8c-PARTIAL Celery L4 Sweep + STAGED Smoke (broker_qmt wire deferred)

**Status**: committed
**Date**: 2026-05-13 (PR #308 squash merged as `3a4a324`)
**Type**: V3 Tier A S8 8c-partial implementation sediment
**Parents**: ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback design SSOT) + ADR-056 (S8 8a state machine + DDL) + ADR-057 (S8 8b DingTalk webhook receiver)
**Children**: future S8 8c-followup (broker_qmt sell wire + broker_order_id writeback + broker_fill_status + paper-mode integration smoke with real qmt_data_service)

## §1 背景

V3 §S8 acceptance line cites: `broker_qmt sell 单 wire (5/5 红线 关键点) + STAGED smoke`. Plan §A S8 chunks: 8a (state machine) ✅ → 8b (DingTalk webhook) ✅ → **8c (broker_qmt wire + Celery sweep + STAGED smoke)**.

This ADR sediments **8c-PARTIAL** covering 2 of 3 sub-items:
- ✅ Celery Beat sweep for PENDING_CONFIRM expired → TIMEOUT_EXECUTED
- ✅ STAGED smoke integration test (L1 → L4 → state transitions via RiskBacktestAdapter stub)
- ⏸ DEFERRED: broker_qmt sell wire post-CONFIRMED + broker_order_id writeback (5/5 红线 关键点 needs explicit user ack per Plan §A S8 红线 SOP)

Sustains V3 governance batch closure cumulative pattern (ADR-054 sediments S5, ADR-055 sediments S7, ADR-056 sediments S8 8a, ADR-057 sediments S8 8b, this ADR sediments S8 8c-partial).

## §2 Decision 1: 8c-partial scope decomposition (反 monolithic broker wire)

**真值**: 8c is split into 8c-partial (this PR) + 8c-followup (real broker wire, deferred).

**论据**:
1. **5/5 红线 enforcement**: Plan §A S8 红线 SOP requires `broker_qmt sell 单 → STOP + push user`. Mixing broker_qmt code with Celery sweep + STAGED smoke would force the entire PR to wait on red-line authorization.
2. **Forward momentum without red-line breach**: Celery sweep + STAGED smoke close 2/3 8c sub-items cleanly. They have 0 broker call, 0 真账户 mutation, 0 .env mutation — pure paper-mode-safe state machine work.
3. **Clean handoff to 8c-followup**: deferred work has clear seams — `_sweep_inner` line 95-97 INFO log emits "(broker invocation deferred to 8c-followup)"; smoke test line 172-174 documents `adapter.sell_calls == []` will need update when broker wires.

## §3 Decision 2: Sweep cadence — 1min during trading hours

**真值**: Beat cron `* 9-14 * * 1-5` Asia/Shanghai (every 1min, hours 9-14, Mon-Fri). 360 fires/day. expires=45s (within 60s cycle, 反 overlap on slow PG).

**论据**:
1. **Granularity**: ADR-027 §2.2 cancel_deadline default is 30min; auction floor 2min. Sweep at 1min provides ≤1min latency on TIMEOUT_EXECUTED transition (反 multi-minute drift).
2. **Hour bound 9-14**: hour=14 includes 14:00-14:59 (the FINAL clamp 14:55 + 5min grace). Cross-day clamp from ADR-027 §2.2 (d) forces deadline ≤14:55, so 14:55+grace is the latest possible sweep target.
3. **PG load**: partial index `idx_exec_plans_status_deadline WHERE status='PENDING_CONFIRM'` from 8a DDL. 360 SELECT/day on a table with ~tens of rows is negligible.
4. **Beat collision 反**: PT chain (16:25/16:30/09:31) excluded by hour ≤14 (09:31 conflict avoided because Beat at minute=0..59 of hour=9 hits 9:00,9:01...9:59 — 9:31 included but PT chain task is a different Beat entry, sequential dispatch handles).
5. **expires=45s 反 overlap**: if a sweep takes >45s (slow PG / lock wait), the next minute's fire skips this dispatch (反 stacking).

## §4 Decision 3: Race-safe atomic UPDATE pattern (沿用 8b webhook)

**真值**: `UPDATE execution_plans SET status='TIMEOUT_EXECUTED', user_decision='timeout', user_decision_at=NOW() WHERE plan_id::text = %s AND status='PENDING_CONFIRM' AND cancel_deadline < NOW()`. rowcount=0 → race (concurrent webhook user CONFIRM/CANCEL stole the row).

**论据**:
1. **Atomic CAS**: WHERE status='PENDING_CONFIRM' provides compare-and-set semantics. Concurrent webhook updates that change status to CONFIRMED/CANCELLED between sweep's SELECT and UPDATE result in rowcount=0 → sweep skips, webhook wins (correct semantic — user explicit decision overrides timeout default).
2. **Defensive `cancel_deadline < NOW()` in UPDATE**: also re-checks at UPDATE time (not just SELECT). Defends against future row-extension features (theoretical) where deadline could move forward between SELECT and UPDATE.
3. **`races` counter**: monitoring metric — high race rate signals user activity timing close to deadline. Operator visibility via task return dict + INFO log.
4. **Sustained 8b webhook 体例**: same WHERE clause pattern used by `DingTalkWebhookService._race_safe_update` — symmetric race semantics across both paths.

## §5 Decision 4: STAGED smoke uses RiskBacktestAdapter stub (0 broker / 0 alert / 0 INSERT)

**真值**: `test_l4_staged_smoke.py` exercises the full pipeline END-TO-END using `RiskBacktestAdapter` (S5 sub-PR 5c, recorded calls without real broker/notifier/DB) as integration sink. Verifies state machine transitions are atomic + 0 adapter.sell_calls when only state machine used.

**论据**:
1. **8c-partial safety**: 0 real broker call possible at test layer — adapter is a recording stub.
2. **Forward-compat marker**: comment at test_l4_staged_smoke.py:172-174 documents `adapter.sell_calls == []` will need update when 8c-followup wires broker. Future maintainer has clear seam.
3. **Sanity test pairs**: `test_adapter_records_zero_sell_when_only_state_machine_used` (验证 0-call assertion is meaningful) paired with `test_adapter_records_sell_when_explicit_call` (反 silent stub no-record). Both must pass — the pair establishes the assertion semantics.
4. **Lifecycle coverage**: PENDING_CONFIRM → CONFIRMED → EXECUTED happy path + PENDING_CONFIRM → TIMEOUT_EXECUTED → EXECUTED timeout path. Both terminal states verified.

## §6 Decision 5: SWEEP_BATCH_LIMIT via settings (reviewer P2-1)

**真值**: `SWEEP_BATCH_LIMIT = getattr(settings, "L4_SWEEP_BATCH_LIMIT", 100)` reads from pydantic settings with default 100. Operator can override via .env.

**论据**:
1. **Default 100/min generous**: trading-day volume ~tens of plans/day; 100/min handles typical load.
2. **Override path for backlog**: crash + restart with 1000+ expired rows → at default 100/min = 10min clear; operator can raise `L4_SWEEP_BATCH_LIMIT=500` for 2min clear.
3. **PG lock contention**: higher batch sizes increase per-row UPDATE lock contention; doc comment in config.py warns operator.

## §7 Decision 6: Pre-assign `conn = None` before try (reviewer LOW)

**真值**: Task body now has `conn = None` before try block. `finally: if conn is not None: conn.close()` guards against `get_sync_conn()` failure raising UnboundLocalError that would mask the original exception.

**论据**:
1. **Standard psycopg2 pattern**: idiomatic to PG connection error handling.
2. **铁律 33 fail-loud preservation**: original PG connection exception (e.g. "connection refused") propagates unmasked to Celery retry handler.

## §8 Decision 7: NOW() timezone clarifying comment (reviewer P1-2)

**真值**: Inline comment in `_sweep_inner` documents that PG `NOW()` is UTC-correct for TIMESTAMPTZ comparison regardless of Celery `timezone="Asia/Shanghai" + enable_utc=False`.

**论据**:
1. **PG TIMESTAMPTZ semantics**: comparison is always timezone-aware UTC-correct internally — no live bug.
2. **铁律 41 reinforcement**: project's explicit timezone iron law. Without the comment, a future maintainer seeing `enable_utc=False` could (incorrectly) assume Asia/Shanghai local time semantics in the SQL.
3. **Prevents future drift**: cheap insurance against a class of timezone bugs that have hit other parts of the project (e.g. LL-067).

## §9 测试覆盖

| Test file | Count | Scope |
|-----------|-------|-------|
| `test_l4_sweep_tasks.py` | 14 | task registration / Beat cron / 0/1/3/race/mixed/batch_limit rows / 铁律 32 / SWEEP_BATCH_LIMIT const |
| `test_l4_staged_smoke.py` | 11 | L1 → L4 plan / webhook CONFIRM/CANCEL / sweep timeout / adapter isolation 0 sell / sanity 1 sell / full lifecycle confirm path / full lifecycle timeout path |

**Total**: 25 new tests. **Full S5/S6/S7/S8/8a/8b/8c-partial + fundamental cumulative**: 337/337 PASS post-reviewer-fix. Ruff clean.

## §10 已知限制 (留 8c-followup)

1. **broker_qmt sell wire post-CONFIRMED transition** — requires explicit user ack per Plan §A S8 红线 SOP (5/5 红线 关键点)
2. **broker_order_id writeback to execution_plans.broker_order_id** — schema column from 8a DDL ready
3. **broker_fill_status tracking + partial-fill semantics** — schema column from 8a DDL ready
4. **Integration smoke with real qmt_data_service** (paper-mode only, sustained `LIVE_TRADING_DISABLED=true`)
5. **Operator dashboard / re-issue button for pending execution_plans + audit query** — UX work
6. **Multi-secret rotation** (operational follow-up across 8b webhook secret + DingTalk outbound secret)

## §11 关联

- ADR-027 (design SSOT for L4 STAGED + 反向决策权 + 跌停 fallback)
- ADR-056 (S8 8a state machine + DDL — parent)
- ADR-057 (S8 8b DingTalk webhook receiver — sibling)
- LL-152 (S8 8c-partial sediment + reviewer lesson)
- 铁律 22 (doc 跟随代码 — ADR-058 + LL-152 + REGISTRY + Plan amend in same session as code)
- 铁律 31 (engine pure compute — not directly invoked, task layer)
- 铁律 32 (service 不 commit — `_sweep_inner` verified by 1 explicit test)
- 铁律 33 (fail-loud — SQL errors propagate to Celery retry; rowcount=0 counted as race, NOT silent skip)
- 铁律 41 (timezone — explicit comment + Asia/Shanghai Celery / UTC PG TIMESTAMPTZ symmetry)
- 铁律 44 X9 (Beat restart enforce — post-merge ops checklist)
- V3 §7 + §S8 acceptance (Plan §A)
- PR #308 (`ab0b9dc` initial + `32cd307` reviewer-fix → squash `3a4a324` merged 2026-05-13)
