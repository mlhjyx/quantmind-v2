# ADR-059: V3 §S8 8c-followup Broker QMT Sell Wire — Full S8 Closure

**Status**: committed
**Date**: 2026-05-13 (PR #309 squash merged as `184959c`)
**Type**: V3 Tier A S8 8c-followup implementation sediment
**Parents**: ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback design SSOT) + ADR-056 (S8 8a state machine + DDL) + ADR-057 (S8 8b DingTalk webhook receiver) + ADR-058 (S8 8c-partial Celery sweep + STAGED smoke)
**Children**: future Tier B paper→live cutover validation (Constitution §L10.5 Gate E prereq — adds the LIVE_TRADING_DISABLED=false ramp)

## §1 背景

V3 §S8 acceptance line cites: `broker_qmt sell 单 wire (5/5 红线 关键点) + STAGED smoke`. Plan §A S8 chunks: 8a (state machine) ✅ ADR-056 → 8b (DingTalk webhook) ✅ ADR-057 → 8c-partial (Celery sweep + STAGED smoke) ✅ ADR-058 → **8c-followup (broker_qmt sell wire post-CONFIRMED + post-TIMEOUT_EXECUTED, this ADR)**.

This ADR sediments **S8 8c-followup**, closing 4 of 6 ADR-058 §10 deferred items:
- ✅ broker_qmt sell wire post-CONFIRMED transition
- ✅ broker_order_id writeback to execution_plans.broker_order_id (8a DDL ready)
- ✅ broker_fill_status tracking + partial-fill semantics (8a DDL ready)
- ✅ Integration smoke covered by `test_l4_staged_smoke.py` §6 (3 new tests)
- ⏸ DEFERRED: Operator dashboard / re-issue button (UX work, not in S8 scope)
- ⏸ DEFERRED: Multi-secret rotation (operational follow-up)

5/5 红线 关键点 triggered by **explicit user ack** (Constitution §L8.1 (a)). Paper-mode sustained (`LIVE_TRADING_DISABLED=true` + `EXECUTION_MODE=paper`): factory routes to RiskBacktestAdapter stub; 0 real broker call. Live mode (post Tier B cutover) wires `MiniQMTBroker.place_order` through QMTSellAdapter; LiveTradingGuard inside the broker is the last line of defense.

Sustains V3 governance batch closure cumulative pattern (ADR-054 → S5, ADR-055 → S7, ADR-056 → S8 8a, ADR-057 → S8 8b, ADR-058 → S8 8c-partial, this ADR → S8 8c-followup; ADR-059 # space).

## §2 Decision 1: 3-layer architecture (Engine / Service / Adapter)

**真值**: broker wire decomposed into 3 layers per CLAUDE.md §3.1:
- PURE engine `backend/qm_platform/risk/execution/broker_executor.py` — `execute_plan_sell(plan, broker_call, timeout, at)` pure function; 0 broker_qmt import, 0 DB, 0 network.
- DB service `backend/app/services/risk/staged_execution_service.py` — `StagedExecutionService.execute_plan(plan_id, conn)`: SELECT plan → broker_executor → race-safe UPDATE writeback. 0 commit (铁律 32).
- Production adapter `backend/app/services/risk/qmt_sell_adapter.py` — single point importing `MiniQMTBroker`; `sell(code, shares, reason, timeout) → dict` matches `RiskBacktestAdapter.sell` shape (BrokerProtocol parity).

**论据**:
1. **铁律 31 sustained**: broker_executor module is 100% pure — verifiable by `grep -E '^import|^from' broker_executor.py` returning 0 broker / DB / network imports.
2. **Test injectability**: `BrokerCallable = Callable[[str, int, str, float], dict[str, Any]]` allows pytest tests to inject recording mocks without monkey-patching modules. 17 broker_executor tests use this pattern.
3. **Sustained 8b体例**: DingTalkWebhookService had the same 3-layer split (parser PURE → service DB → API endpoint). Pattern replication 3rd 实证 cumulative.
4. **Live wire isolation**: only `qmt_sell_adapter.py` imports `MiniQMTBroker`; the rest of the code path never touches broker_qmt internals. Reviewer scope-creep audit + future broker swap (e.g. simulated live broker for paper-trade dry-runs) is single-file change.

## §3 Decision 2: Paper-mode routing factory (`is_paper_mode_or_disabled`)

**真值**: `build_default_broker_call()` reads `settings.EXECUTION_MODE` + `settings.LIVE_TRADING_DISABLED`. Returns `(RiskBacktestAdapter.sell, "paper_stub")` if either condition is paper/disabled; otherwise `(QMTSellAdapter.sell, "live_qmt")` wrapping connected `MiniQMTBroker`.

**论据**:
1. **Defense in depth (5/5 红线)**: three independent layers prevent unintended live execution: (a) `is_paper_mode_or_disabled()` routes to stub adapter when paper or disabled, (b) `LiveTradingGuard.assert_live_trading_allowed()` inside `MiniQMTBroker.place_order` raises `LiveTradingDisabledError`, (c) `QMTSellAdapter` catches that error and returns `rejected` status (not silent swallow). All three must be bypassed for a real order.
2. **Safe default**: `is_paper_mode_or_disabled()` defaults to True (paper stub) when settings attributes are missing — defensive against partial/empty config.
3. **Operator clarity**: explicit `mode_tag = "paper_stub" | "live_qmt"` returned alongside the callable. Future health endpoint / dashboard can surface this without coupling to broker internals.
4. **Test parity**: `test_qmt_sell_adapter.py::TestPaperModeRouting` covers all 4 combinations (paper / live_disabled / live_enabled / missing settings).

## §4 Decision 3: Atomic webhook commit boundary (CONFIRMED + EXECUTED together)

**真值**: webhook endpoint `_sync_db_block` commits BOTH the CONFIRMED state transition (from DingTalkWebhookService) AND the broker writeback (from StagedExecutionService) in a single `conn.commit()`. On any exception, `conn.rollback()` reverts BOTH. CANCEL path commits the cancellation alone (no broker call).

**论据**:
1. **反 orphan CONFIRMED row**: if we committed CONFIRMED separately and broker call then raised, the row would sit in CONFIRMED state forever with no broker order — operator + audit chain confusion.
2. **Atomic per-webhook semantics**: from the user's perspective, "I confirmed" → either both transitions land (CONFIRMED + EXECUTED) or neither does (rollback + 500). Matches user mental model of a single decision point.
3. **Service-layer composition**: both DingTalkWebhookService AND StagedExecutionService share the same `conn` injection; neither commits internally. The API endpoint owns the boundary. 铁律 32 sustained 4th 实证 (sweep task, webhook service, this endpoint).
4. **Defensive note (reviewer LOW deferred)**: on broker exception, user sees 500. Future enhancement could catch broker exceptions separately, commit CONFIRMED, then mark FAILED via a second UPDATE — but this complicates user mental model and the current full-rollback behavior is acceptable for the volume of webhook traffic expected.

## §5 Decision 4: Live broker construction failure → raise hard + P0 alert (reviewer HIGH fix)

**真值**: in live mode (LIVE_TRADING_DISABLED=false + EXECUTION_MODE=live), broker construction failure in `build_default_broker_call` RAISES the exception after emitting a P0 DingTalk alert (best-effort, silent_ok on alert failure). Earlier draft silently fell back to RiskBacktestAdapter stub — code-reviewer + security-reviewer cross-flagged as HIGH-severity safety gap.

**论据**:
1. **反 silent false-EXECUTED**: silent fallback would mark plans EXECUTED with `stub-<plan_id>` order_id while no real order reached the broker. Operator believes live broker active; reality is paper-stub. This is the worst class of failure in a trading system.
2. **STAGED queue starvation < false-EXECUTED**: the original concern (fallback prevents starvation) is valid for paper mode but inverted in live mode. Live mode tolerates a blocked queue better than fake fills.
3. **Operator paged**: P0 DingTalk via `notification_service.send_alert` — best-effort (silent_ok on send failure so the raise still propagates).
4. **Paper mode unchanged**: paper-mode default has no fallback path. Stub IS the intended choice; no exception-handling needed.

## §6 Decision 5: Race-safe UPDATE with `WHERE status IN (CONFIRMED, TIMEOUT_EXECUTED)` (沿用 8b/8c-partial)

**真值**: `UPDATE execution_plans SET status=?, broker_order_id=?, broker_fill_status=? WHERE plan_id = CAST(%s AS uuid) AND status IN ('CONFIRMED', 'TIMEOUT_EXECUTED')`. rowcount=0 → race (another worker / manual fix already wrote EXECUTED or FAILED).

**论据**:
1. **Atomic CAS for both entry paths**: WHERE status IN provides compare-and-set covering both CONFIRMED (webhook) and TIMEOUT_EXECUTED (Celery sweep) entry paths. Concurrent updates from either path that pre-flip the row to EXECUTED/FAILED result in rowcount=0 — service returns RACE outcome (反 silent overwrite).
2. **UUID cast on param side** (reviewer P2-4 fix): `plan_id = CAST(%s AS uuid)` preserves index usage on the (plan_id, created_at) unique constraint. Previous `plan_id::text = %s` forced sequential scan across hypertable chunks. LL-034 pattern sustained.
3. **Sustained 8b/8c-partial 体例**: same WHERE-clause race-safe pattern used by DingTalkWebhookService._race_safe_update + l4_sweep_tasks._sweep_inner UPDATE. Symmetric race semantics across all 3 sites.
4. **`broker_race` counter**: sweep task tracks this independently from the TIMEOUT_EXECUTED transition race counter, so operator can distinguish "user confirmed/cancelled during sweep" (transition race) from "EXECUTED/FAILED written by another worker before broker writeback" (broker race).

## §7 Decision 6: BrokerCallable Protocol contract (沿用 RiskBacktestAdapter.sell shape)

**真值**: `BrokerCallable = Callable[[str, int, str, float], dict[str, Any]]` returning dict with keys `{status, code, shares, filled_shares, price, order_id, error}`. Success statuses: `stub_sell_ok / ok / filled / partial_filled`. Failure statuses: `rejected / error` (or unknown → treated as failure).

**论据**:
1. **Replicates existing Stage 5 contract**: RiskBacktestAdapter.sell (S5 sub-PR 5c) already returns this shape — no new protocol invented; both stub + production broker conform to the same callable signature.
2. **`stub-<plan_id_prefix>` order_id synthesis**: when broker returns None/empty order_id (paper-mode stub), broker_executor synthesizes a deterministic placeholder so the DB column is non-null + traceable. 反 silent NULL in audit query.
3. **Status whitelist**: only enumerated success statuses count as broker-accepted. Unknown status → FAILURE with error_msg pointing to the unrecognized status string (reviewer P3 sustained — defensive default).
4. **Partial-fill semantics**: `partial_filled` counts as broker-side success (broker accepted, just couldn't fill all). filled_shares persisted to broker_fill_status column for downstream reconciliation. Full vs partial vs zero-fill distinction lives in column data, not state machine.

## §8 Decision 7: Error message length cap (200 chars) — reviewer security MEDIUM

**真值**: `error_msg` in `BrokerExecutionResult` + `QMTSellAdapter.sell` return dict capped at `_MAX_ERR_LEN = 200` characters via `f"{type(exc).__name__}: {str(exc)[:200]}"`. Surfaced in API response body `response["broker"]["error"]`.

**论据**:
1. **A05/A09 — Information Disclosure**: raw exception strings (e.g. `ConnectionRefusedError: [Errno 111]...`) could leak internal paths / xtquant internals through the HMAC-authenticated webhook response. Cap bounds the blast radius.
2. **Operator log preserved**: full exception details still in `logger.exception` at the broker_executor + adapter layers — debug context retained for the operator who has log access.
3. **Stable error tokens**: `LiveTradingDisabledError` mapped to literal `"live_trading_disabled"` string (no exception detail leak); broker_returned_-1 mapped to literal `"broker_returned_-1"`. These tokens are stable across error message changes.
4. **Future hardening hook**: 200-char limit can tighten further if a downstream consumer needs a stricter contract.

## §9 测试覆盖

| Test file | Count | Scope |
|-----------|-------|-------|
| `test_broker_executor.py` | 14 | SUCCESS (stub/ok/filled/partial_filled) + FAILURE (rejected/error/unknown/raises) + Defensive (4 invalid statuses + timeout/reason audit + sym/qty propagate) |
| `test_qmt_sell_adapter.py` | 12 | success / -1 reject / LiveTradingDisabledError → rejected / generic exception → error / shares≤0 ValueError / reason truncate / 4 paper-mode routing combos |
| `test_staged_execution_service.py` | 8 | CONFIRMED→EXECUTED / TIMEOUT_EXECUTED→EXECUTED / rejection→FAILED / NOT_FOUND / NOT_EXECUTABLE / RACE / 铁律 32 no-commit |
| `test_l4_staged_smoke.py` +3 §6 | 3 | end-to-end smoke confirmed+timeout broker wire / broker rejection→FAILED |
| `test_l4_sweep_tasks.py` +4 §8 | 4 | broker wire executed/failed/race counters / legacy no-injection compat / race UPDATE rowcount=0 skips broker |
| `test_dingtalk_webhook_endpoint.py` +1 | 1 | endpoint integration: TRANSITIONED → CONFIRMED → staged stub → EXECUTED override; atomic commit assertion |

**Total**: 42 new tests + 1 updated endpoint test. **Full S5/S6/S7/S8/8a/8b/8c-partial/8c-followup + fundamental cumulative**: 156/156 PASS post-reviewer-fix. Pre-push smoke: 55 PASS / 2 skipped. Ruff clean.

## §10 已知限制 (留 future S8 follow-ups / Tier B cutover)

1. **Async broker callback wire** — `QMTSellAdapter.sell` returns at order-submit time (filled_shares=0). Real fill confirmation arrives async via `MiniQMTBroker` callback (`register_trade_callback`). Future PR wires the callback to UPDATE `broker_fill_status` post-fill. Out of S8 scope.
2. **Operator dashboard / re-issue button** — pending UX work; ADR-058 §10 item 5.
3. **Multi-secret rotation** — operational follow-up across DingTalk webhook secret + outbound webhook secret; not blocked by this PR.
4. **Partial-fill reconciliation** — `partial_filled` counts as success in the current implementation. Future enhancement: split-execution row (FILLED part + retry on remainder). Out of S8 scope.
5. **Live-mode integration smoke** — covered by `qmt_sell_adapter` unit tests with mocked `MiniQMTBroker`, but no end-to-end paper-mode → mock-live cutover dry-run. Tier B cutover gate (Constitution §L10.5 Gate E) is the proper validation moment.

## §11 关联

- ADR-027 (design SSOT for L4 STAGED + 反向决策权 + 跌停 fallback)
- ADR-056 (S8 8a state machine + DDL — grandparent)
- ADR-057 (S8 8b DingTalk webhook receiver — sibling)
- ADR-058 (S8 8c-partial Celery sweep + STAGED smoke — sibling, this closes §10 items 1-4)
- LL-153 NEW (S8 8c-followup sediment + 5/5 红线 关键点 explicit user ack pattern)
- 铁律 22 (doc 跟随代码 — ADR-059 + LL-153 + REGISTRY + Plan amend in same session as code)
- 铁律 31 (engine PURE — broker_executor 0 broker/DB/network imports)
- 铁律 32 (services 不 commit — staged_execution_service + 沿用 dingtalk_webhook_service 体例)
- 铁律 33 (fail-loud — broker exceptions surface as FAILED, not silent skip; live broker construction failure RAISES with P0 alert)
- 铁律 35 (secrets via env — QMT_PATH/QMT_ACCOUNT_ID direct settings attr access, fail fast)
- 铁律 41 (timezone — sustained from 8c-partial; PG TIMESTAMPTZ + Asia/Shanghai Celery symmetry)
- 铁律 44 X9 (Beat restart enforce — staged_service rebuilt per Celery task; post-merge ops checklist sustained)
- V3 §S8 acceptance (Plan §A row): ⚠️ NEAR-COMPLETE → ✅ DONE (4/4 ADR-058 §10 items 1-4 closed)
- PR #309 (`0283de5` initial + `4f3f5c5` reviewer-fix → squash `184959c` merged 2026-05-13)
