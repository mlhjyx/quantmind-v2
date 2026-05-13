# ADR-060: V3 §S9a Batched 平仓 + Trailing Stop (S9 chunked half)

**Status**: committed
**Date**: 2026-05-13 (PR #311 squash merged as `a1ac5f6`)
**Type**: V3 Tier A S9a implementation sediment
**Parents**: ADR-027 (L4 STAGED design SSOT) + ADR-056 (S8 8a state machine) + ADR-059 (S8 8c-followup broker wire)
**Children**: future S9b (re-entry tracker + DingTalk push + 历史回放 smoke)

## §1 背景

V3 §S9 acceptance: "batched sell 多笔; trailing stop; Re-entry 决议; 历史回放; unit ≥95%". Per Plan §A S9 row "single sub-PR OR chunked 2 (batched+trailing vs Re-entry)" — chunked into 2 sub-PRs:
- **S9a (this PR)**: V3 §7.2 batched 平仓 PURE planner + V3 §7.3 dynamic trailing stop RiskRule
- **S9b (deferred)**: V3 §7.4 re-entry tracker + DingTalk push integration + 历史回放 smoke

No new 5/5 红线 触发 — both modules are PURE / rule-layer; broker dispatch reuses S8 8c-followup wire path (ADR-059).

Sustains V3 governance batch closure cumulative pattern (ADR-054→S5, ADR-055→S7, ADR-056→S8 8a, ADR-057→S8 8b, ADR-058→S8 8c-partial, ADR-059→S8 8c-followup, this ADR→S9a).

## §2 Decision 1: Batched 平仓 PURE planner (V3 §7.2)

**真值**: New module `backend/qm_platform/risk/execution/batched_planner.py` exposes `generate_batched_plans(positions, mode, at) → list[ExecutionPlan]`. Pure function: 0 IO, 0 broker, 0 DB. Caller assembles BatchedPositionInput from L1 PositionSource + L2 sentiment + realtime market data, planner produces N ExecutionPlan rows with batch_index/batch_total/scheduled_at staggered.

**论据**:
1. **铁律 31 sustained**: planner is pure — broker dispatch + DB persistence + Celery countdown task scheduling all live in the caller layer. Sustains 3-layer architecture pattern from S8 (Engine PURE → Service DB → Adapter production).
2. **V3 §7.2 formula**: N = max(3, ceil(positions × 0.3)). Implemented as `compute_batch_count()` helper.
3. **Quantity split fairness**: `_split_qty(total, batches)` returns equal split with remainder added to early batches (100/3 → [34, 33, 33]). 0-qty batches are skipped at plan emission (1 share / 3 batches → only 1 plan, not 3).
4. **Priority order determinism**: `_priority_key` = (drop_pct ASC, daily_volume ASC, sentiment_24h ASC, code ASC). 4-tier key with code as final tiebreaker eliminates non-determinism in test fixtures. None sentiment treated as 0 (neutral).
5. **Per-batch deadline** (not shared): each batch's cancel_deadline = scheduled_at + 30min. Sharing a single deadline would crowd late batches into too-short user-decision windows.
6. **Mode routing**: STAGED → PENDING_CONFIRM (each batch awaits user); OFF/AUTO → CONFIRMED (each batch dispatches at scheduled_at via Celery countdown).
7. **Limit price**: `current_price × 0.98` per V3 §7.1 (-2% defensive sell limit).

## §3 Decision 2: Trailing Stop as RealtimeRiskRule (V3 §7.3)

**真值**: New module `backend/qm_platform/risk/rules/realtime/trailing_stop.py` exposes `TrailingStop(RiskRule)`. Replaces PMSRule v1 静态阈值 per ADR-016 D-M2 deprecation path. Registers on 5min cadence via `RealtimeRiskEngine.register(rule, cadence="5min")`. Severity P1, action=`sell` — engine dispatches via S8 8c-followup broker wire.

**论据**:
1. **V3 §7.3 bracket logic implemented as `_trailing_pct(pnl_pct, atr_pct)`**:
   - pnl ≥ 100% → trailing = max(10%, ATR × 1)
   - pnl ≥ 50% → trailing = max(10%, ATR × 1.5)
   - pnl ≥ 20% → trailing = max(10%, ATR × 2)
   - 10% floor (反 stop_price 紧贴 peak when ATR missing / too small)
2. **ATR injection via RiskContext**: `context.realtime[code]["atr_pct"]` — caller (L1 RealtimeRiskEngine) populates from market data. None → falls back to 10% floor.
3. **Peak ratchet (monotonic upward)**: `state.peak_price = max(stored, pos.peak_price, pos.current_price)`. Three sources because (a) caller may have authoritative peak from position history, (b) current_price may have just made a new high mid-beat, (c) stored peak from prior beats. Always upward.
4. **In-memory state**: `dict[code, _TrailState]` (rule-internal, not in RiskContext). Reset on engine restart acceptable per V3 §7.3 — peak rebuilds from current_price on next 5min beat. Future S10 paper-mode 5d may upgrade to PG persistence.
5. **Activation gate**: pnl ≥ 20% (configurable via `update_threshold` from S7 DynamicThresholdEngine). On rule construction with bad threshold (0 / ≥ 1), `update_threshold` raises ValueError.
6. **State purge post-trigger**: after trigger fires, state is popped — next position entry rebuilds fresh peak from current_price.

## §4 Decision 3: Activation-vs-tracking semantic (反 state-clear-on-retrace)

**真值**: Once activated (state exists), trailing stop tracks even if pnl retraces below 20%. Earlier draft cleared state on retrace below activation — REVIEWER P1 cross-found this as MISSING SEMANTIC COVERAGE (one test passed by accident — retrace ALSO triggered the trailing stop at 10% floor, masking the activation-clear-on-retrace path entirely).

**论据**:
1. **Whole purpose of trailing stop**: catch the retrace from a profitable peak. Clearing state on retrace below 20% would defeat the rule (the moment price falls back into "not activated" territory we'd lose our peak memory).
2. **Bracket frozen at peak pnl** (not current pnl): `peak_pnl_pct = (state.peak_price - entry) / entry`. This prevents bracket downgrade on retrace (e.g. peak at 60% pnl → bracket = ATR × 1.5; current pnl drops to 30% but peak still 60% → bracket STAYS at ATR × 1.5, not downgraded to ATR × 2).
3. **Reviewer fix**: 2-test split. `test_state_persists_on_retrace_below_activation_without_trigger` (peak=125, current=119 → retrace below activation but above stop → state persists, no trigger) covers the previously-untested semantic. `test_state_cleared_on_retrace_that_triggers_stop` covers the trigger purge path. Both pass.

## §5 Decision 4: Duplicate-code rejection in batched_planner (reviewer P2)

**真值**: `generate_batched_plans` raises ValueError if any two positions share the same `code`. Earlier draft would silently overwrite the splits dict (keyed by code) while still emitting plans for both — double quantity bug.

**论据**:
1. **Silent dict overwrite is dangerous**: `splits = {p.code: _split_qty(p.shares, n) for p in sorted_positions}` — second AAA entry overwrites first; `sorted_positions` still contains both; both would emit plans with wrong (second) qty split.
2. **Fail-fast**: caller assembles positions list; if dedup is required by domain logic, caller dedups. Planner is strict about input contract — both safer + more debuggable than silent overwrite.
3. **Error message lists duplicates**: `raise ValueError(f"duplicate position codes not allowed: {dups}")` shows operator exactly which codes collided.

## §6 Decision 5: current_price > 0 validation (reviewer P2)

**真值**: `generate_batched_plans` validates `current_price > 0` per position. Earlier draft only checked `shares > 0`; zero/negative current_price would yield `limit_price = 0` (nonsensical sell at 0).

**论据**:
1. **Sustained 反 silent**: 0-priced sell order would be rejected by broker but at a downstream point with worse audit trail than upstream fail-fast at planner.
2. **Sustained existing pattern**: trailing_stop.py:143 already guards `pos.current_price > 0` in its evaluate loop. Symmetric defensive practice.

## §7 Decision 6: Sustained S5+S7+S8 cumulative pattern (no new red-line, paper-mode sustained)

**真值**: 0 broker import in S9a code (planner + rule both PURE / rule-layer). Caller dispatches via S8 8c-followup broker wire path (ADR-059). LIVE_TRADING_DISABLED=true sustained; paper-mode factory routes to RiskBacktestAdapter stub.

**论据**:
1. **No new 5/5 红线 关键点 触发**: S9a doesn't open new broker integration points; it only produces RuleResult / ExecutionPlan dataclasses that the existing S8 chain dispatches.
2. **Build on S8 wire**: when batched plans dispatch (Celery countdown per scheduled_at), each batch invokes the same StagedExecutionService.execute_plan that 8c-followup already wired. Symmetric across single-shot + batched paths.
3. **3rd consecutive paper-mode sustained PR** (after S8 8b/8c-partial/8c-followup): paper-mode factory routing is now stable + tested across 4 entry points (webhook single, sweep single, batched dispatch via either, plus trailing stop sell trigger).

## §8 Decision 7: Test coverage 64 → 68 (4-test reviewer follow-up)

**真值**: Initial PR shipped 64 tests; reviewer HIGH + 2 MEDIUM follow-up added 4 tests:
- `test_state_persists_on_retrace_below_activation_without_trigger` (HIGH semantic coverage)
- `test_state_cleared_on_retrace_that_triggers_stop` (companion)
- `test_duplicate_codes_rejected` (P2 validation)
- `test_zero_current_price_rejected` + `test_negative_current_price_rejected` (P2 validation)

Cumulative: 219/219 PASS (S5/S7/S8/S9a + adjacent regression). Pre-push smoke 55 PASS / 2 skipped (3x: initial push, reviewer-fix push, sediment push).

**论据**:
1. **Reviewer 2nd-set-of-eyes value**: HIGH finding was a test design lesson — the original test name implied a semantic ("state cleared on retrace below activation") that was NOT actually being tested (only the trigger purge path). This is a textbook case of test-by-accident; the reviewer catch is the 2nd-set-of-eyes value materializing.
2. **Pre-emption + reviewer combo**: 64-test initial coverage was thorough, but 2 latent bugs (duplicate code overwrite, current_price=0) only surfaced via reviewer scrutiny. Combined CC + agent reviewer catches more than either alone.

## §9 已知限制 (留 future)

1. **S9b deferred** (separate PR, no new 红线): Re-entry tracker for batched-sold symbols + DingTalk push integration + 历史回放 smoke.
2. **In-memory trailing state**: resets on engine restart. Future S10 paper-mode 5d may upgrade to PG persistence if observed drift is problematic.
3. **Batched re-evaluation logic** between batches (V3 §7.2 "若市场反弹 + alert 清除 → 停止后续 batch"): planner produces all N upfront; caller's between-batch re-eval logic is out of S9a scope. Future S9b or follow-up will wire a Celery task that polls alert state per scheduled_at and cancels pending batches.
4. **PMSRule v1 static** still exists in `backend/qm_platform/risk/rules/pms.py` per ADR-016 D-M2 path. Actual deprecation (replacement of all PMSRule usage with TrailingStop) deferred to operational follow-up. S9a adds TrailingStop alongside; doesn't remove PMSRule.

## §10 关联

- ADR-027 (L4 STAGED design SSOT)
- ADR-016 (PMSRule v1 deprecation path D-M2)
- ADR-056 (S8 8a state machine + DDL)
- ADR-059 (S8 8c-followup broker wire — broker dispatch reused by S9a)
- LL-154 NEW (TrailingStop activation-vs-tracking semantic correction + reviewer test-by-accident catch)
- 铁律 24 (single-responsibility — 1 rule = 1 file)
- 铁律 31 (PURE engine — batched_planner 0 IO; trailing_stop state rule-internal not engine IO)
- 铁律 33 (fail-loud — empty positions / shares ≤ 0 / 0 current_price / bad activation / duplicate code all ValueError)
- V3 §7.2/§7.3/§7.5 / Plan §A S9 row partial-complete (9a ✅ / 9b pending)
- PR #311 (`7851dc2` initial + `94e25fe` reviewer-fix → squash `a1ac5f6` merged 2026-05-13)
