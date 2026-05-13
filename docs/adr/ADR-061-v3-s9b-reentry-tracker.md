# ADR-061: V3 §S9b Re-entry Tracker + End-to-End Chain Smoke (S9 Full Closure)

**Status**: committed
**Date**: 2026-05-13 (PR #313 squash merged as `7fc5bd2`)
**Type**: V3 Tier A S9b implementation sediment
**Parents**: ADR-027 (L4 STAGED design SSOT) + ADR-060 (S9a batched + trailing) + ADR-059 (S8 8c-followup broker wire — reused by chain smoke)
**Children**: future caller-side Celery wire (trade_log polling + AlertDispatcher dispatch — operational follow-up, not blocker for Tier A)

## §1 背景

V3 §S9 acceptance: "batched sell 多笔; trailing stop; Re-entry 决议; 历史回放; unit ≥95%". S9a (ADR-060) closed batched + trailing. S9b (this PR) closes Re-entry + 历史回放, completing Plan §A S9 row.

No new 5/5 红线 触发 — reentry_tracker is PURE (0 IO/DB/broker/AlertDispatcher); chain smoke reuses S8 8c-followup broker wire path (ADR-059) via RiskBacktestAdapter stub. Caller-side Celery wire (which would actually push DingTalk re-entry notifications) deferred — pure tracker is ready for caller integration.

Sustains V3 governance batch closure cumulative pattern (ADR-054→S5, ADR-055→S7, ADR-056-059→S8, ADR-060→S9a, this ADR→S9b; ADR-061 # space).

## §2 Decision 1: PURE tracker design (反 service-mixed layered ambiguity)

**真值**: `backend/qm_platform/risk/execution/reentry_tracker.py` exposes `ReentryTracker.check(sold, current_price, sentiment_24h, regime, at) → ReentryCheckResult`. Caller layer is responsible for trade_log query + Redis read + AlertDispatcher push. Tracker is 100% pure — verifiable via grep: zero imports of DB / broker / network / AlertDispatcher.

**论据**:
1. **铁律 31 sustained**: continues 3-layer pattern from S8 (Engine PURE → Service DB → Adapter production). reentry_tracker is the engine layer.
2. **Caller flexibility**: Celery task / FastAPI endpoint / one-off ops script can all call the same `check()` without coupling. Test injection is trivial — just construct SoldRecord with desired fields and pass synthetic current_price + sentiment + regime.
3. **Per-condition breakdown surfaces partial matches**: `ReentryCheckResult.price_ok / sentiment_ok / regime_ok / within_window` lets a future operator dashboard show "almost re-entry: 3 of 4 conditions met" — useful for RAG-driven future tuning of thresholds. Aggregate `should_notify=True` requires ALL 4.
4. **Frozen dataclass result**: ReentryCheckResult is `frozen=True`. Sustains S5/S8/S9 layered architecture pattern of pure-result-from-pure-engine.

## §3 Decision 2: Sentiment > 0 strict (反 ≥ 0 sloppy boundary)

**真值**: Re-entry sentiment check uses `sentiment_24h > 0` (strict), not `>= 0`. Zero sentiment treated as "not yet 转正" — fail to notify.

**论据**:
1. **V3 §7.4 wording "sentiment_24h 转正"**: "turning positive" is a directional change. Zero is the boundary, not a positive value. Strict > matches the wording semantics.
2. **Defensive against neutral noise**: sentiment computed from LLM aggregations is noisy near zero (e.g. ±0.05 random walk). Strict > 0 avoids triggering re-entry signals on borderline-neutral days.
3. **Test boundary coverage**: `test_zero_sentiment_not_ok` explicitly asserts zero blocks the aggregate. Future tweaks to threshold (e.g. > 0.1) would just update the constant in tracker without changing the test's intent.

## §4 Decision 3: None sentiment fail-closed (反 silent assume positive)

**真值**: When `sentiment_24h is None` (L2 RAG returned no data for this symbol), `sentiment_ok = False`. The caller does NOT push a re-entry notification.

**论据**:
1. **反 silent positive assumption**: missing data should never produce an action signal. Silent assume-positive would result in re-entry pushes for symbols where sentiment is unknown (e.g. just-listed, just-IPO, low-news-coverage stocks) — exactly the symbols where re-entry is RISKIER.
2. **Fail-loud trail**: reason string includes "sentiment_24h unknown — fail-closed (反 silent assume positive)" so operator sees WHY the candidate was skipped, not just that it was.
3. **Defensive pattern sustained**: this is the 6th project-wide instance of "None data → fail-closed semantic" (sustained from S5 9 rules + S7 dynamic threshold + S8 8b webhook). Project-wide convention now enforced via reviewer-caught test coverage.

## §5 Decision 4: Price reb upper bound +5% (反 chasing momentum)

**真值**: `current_price ≤ sell_price * (1 + 5%)` upper bound check. Both endpoints inclusive: `sell_price ≤ current_price ≤ sell_price × 1.05`.

**论据**:
1. **V3 §7.4 explicit**: "卖出价 + 5% 内反弹" — within +5% of sell_price.
2. **Past +5% = momentum gone**: if price has already rebounded > 5% above sell, the entry opportunity is missed — re-entry at that level would be chasing momentum, which is exactly the behavior the rule is supposed to prevent (we sold for a reason; chasing back the high invalidates that reason).
3. **Boundary tests both sides**: `test_price_at_5pct_boundary_ok` (current = sell × 1.05 exactly) and `test_price_past_5pct_momentum_gone` (current = sell × 1.06) frame the rule cleanly.

## §6 Decision 5: 1-day window inclusive + future-sell_at guard (reviewer P2 fix)

**真值**: `elapsed = at - sold.sell_at`. Window check `elapsed <= timedelta(days=1)` is inclusive at the 1-day boundary. Reviewer P2 fix: explicit guard `if elapsed < timedelta(0)` for future sell_at (clock skew / bad data) — without it, negative td trivially passes `≤ 1d` check.

**论据**:
1. **Inclusive boundary**: test `test_exactly_24h_ok` documents the contract — exact 24h is still within window.
2. **Negative elapsed guard**: future sell_at is structurally impossible in production (DB timestamps are monotonic), but defensive against clock skew, test fixtures using future times, and copy-paste bugs in caller code. Returns `within_window=False` with explicit reason "sell_at in future — clock skew or bad data".
3. **Sustained fail-fast philosophy**: don't trust input. Caller-assembled SoldRecord could pull a row with future timestamp; tracker treats this as a stale-signal-equivalent and returns no-notify with audit trail.

## §7 Decision 6: Suggested qty = 50% default (反 1:1 round-trip)

**真值**: `suggested_qty = max(1, round(sold.sell_qty × 0.5))`. Configurable via `suggest_ratio` constructor param.

**论据**:
1. **Conservative re-entry**: round-trip 100% of sold qty assumes the market verdict on the sold position has fully reversed. Reality is closer to "partial reversal, watch how it plays out". 50% lets user dollar-cost-average back in.
2. **Min = 1**: tiny positions (1 share sold) still get a valid suggestion (1 share) rather than rounding to 0.
3. **Configurable**: future operators may tune (e.g. 30% for more cautious, 75% for more aggressive). Constructor validation (`0 < ratio ≤ 1`) prevents bad config.

## §8 Decision 7: End-to-end chain smoke covers V3 §7.2/§7.3/§7.4 integration

**真值**: `test_l4_staged_smoke.py` `TestHistoricalReplayChain` covers the full V3 §7 chain — BatchedPlanner → broker_executor + RiskBacktestAdapter → ReentryTracker. 2 positions × 3 batches = 6 broker calls verified; 18h later price rebound + sentiment positive + regime calm → re-entry signal verified. Companion test asserts regime=stress blocks re-entry.

**论据**:
1. **Sustained `历史回放` Plan §A S9 acceptance**: this is the smoke test that proves the chain composes without integration glitches.
2. **0 broker call**: all dispatch via `RiskBacktestAdapter.sell` stub. Tests run with `LIVE_TRADING_DISABLED=true` sustained, 0 真账户 mutation.
3. **Forward-compat seam for S10 paper-mode 5d**: when S10 runs the 5d dry-run, the chain test fixtures are ready as a synthetic baseline for "happy path looks like this" — drift in production behavior will be obvious against this fixture.

## §9 测试覆盖

| Test file | Count | Scope |
|-----------|-------|-------|
| `test_reentry_tracker.py` | 49 | all-conditions / window (within / exactly-24h / past / future-sell_at-guarded) / price (below / at / within-5% / at-5% / past-5%) / sentiment (positive / zero-strict / negative / None-fail-closed) / regime (calm / stress / crisis / unknown) / suggested_qty (50% default / custom / min-1) / Defensive parametrized (zero + negative for sell_price / sell_qty / current_price) / constructor validation / format markdown |
| `test_l4_staged_smoke.py` §7 (+2) | 2 | chain smoke (BatchedPlanner → broker_executor → ReentryTracker, 6 broker calls, re-entry suggestion) + regime-block negative case |

**Total**: 51 NEW (after reviewer-fix 47 → 51). **S5/S6/S7/S8/8a/8b/8c-partial/8c-followup/S9a/S9b + adjacent cumulative**: 115/115 PASS within scope. Pre-push smoke: 55 PASS / 2 skipped.

## §10 已知限制 (留 caller-side wire / future)

1. **Caller-side Celery task**: `app/tasks/reentry_tasks.py` would poll trade_log for recent batched-sold rows + call ReentryTracker.check + push via AlertDispatcher. Out of S9b scope; ready for operational follow-up.
2. **Between-batch re-evaluation Celery task**: V3 §7.2 "若市场反弹 + alert 清除 → 停止后续 batch". This polls L1 alert state per scheduled_at and cancels pending batches. Out of S9 scope (out of acceptance line); operational follow-up.
3. **PMSRule v1 actual deprecation**: per ADR-016 D-M2 path. S9a added TrailingStop alongside; this PR doesn't remove PMSRule. Operational follow-up.
4. **Sentiment threshold tuning**: > 0 strict may be too conservative for some symbols; future RAG correlation analysis (S10+) may suggest per-symbol or per-regime tuning.

## §11 关联

- ADR-027 (L4 STAGED design SSOT)
- ADR-059 (S8 8c-followup broker wire — reused by chain smoke)
- ADR-060 (S9a batched + trailing — parent)
- LL-155 NEW (S9b sediment + sentiment strict-vs-zero + None-fail-closed pattern sustained as 6th 实证 + reviewer 2nd-set-of-eyes 5th 实证 + 5th consecutive sediment-in-same-session enforcement)
- 铁律 22 (doc 跟随代码 — ADR-061 + LL-155 + REGISTRY + Plan amend in same session)
- 铁律 31 (PURE engine — reentry_tracker 0 IO imports verified by grep)
- 铁律 33 (fail-loud — invalid sell_price / qty / current_price / constructor params all raise ValueError; None sentiment fails closed)
- V3 §7.4 / Plan §A S9 row ⚠️ PARTIAL → ✅ DONE (9a + 9b cumulative)
- PR #313 (`2ce177c` initial + `d43bf5a` reviewer-fix → squash `7fc5bd2` merged 2026-05-13)
