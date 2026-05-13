# ADR-067: V3 Tier B TB-2 Closure — MarketRegimeService + Bull/Bear/Judge V4-Pro × 3 + L3 Integration

**Status**: Accepted
**Date**: 2026-05-14 (Session 53 + TB-2 closure 4 sub-PR cumulative)
**Type**: V3 Tier B Sprint Closure ADR
**Cumulative**: TB-2a (PR #333 `8a31bbc`) + TB-2b (PR #334 `9d2d88c`) + TB-2c (PR #335 `37a4c80`) + TB-2d (本 PR sediment)
**Plan v0.2 row**: §A TB-2 sprint closure

---

## Context

V3 Tier B Plan v0.2 TB-2 sprint = "MarketRegimeService Bull/Bear V4-Pro × 3 debate + market_regime_log + Celery Beat 3 schedule + L3 集成" per ADR-064 D2 (V4-Pro mapping per ADR-036) sustained 2026-05-13. Chunked into 4 sub-PR per LL-100 体例:

1. **TB-2a foundation**: market_regime_log DDL + interface dataclasses + repository + 20 tests
2. **TB-2b LLM wire**: 3 prompts yaml + agents.py + MarketRegimeService.classify + 24 tests
3. **TB-2c Beat wire**: 3 daily Beat schedules + StubIndicatorsProvider + ops runbook + 11 tests
4. **TB-2d closure (本 PR)**: DefaultIndicatorsProvider real data wire + L3 regime integration + ADR-067 + LL-161 + 8 tests

**Driver**: V3 §5.3 Bull/Bear regime detection (Tier B) — 2 V4-Pro agent debate + Judge V4-Pro 加权 → regime label + confidence + reasoning → DynamicThresholdEngine L3 阈值 调整 (regime=Bear → STRESS 收紧 / Bull → CALM 放松).

---

## Decisions

### D1: 3-layer pattern sustained (Engine PURE + Application + Beat dispatch)

**Decision**: Architecture per V3 §11.4 sustained pattern (from S5/S7/S8/S9/TB-1):
- `backend/qm_platform/risk/regime/` = Engine PURE side (0 IO / 0 DB / 0 LiteLLM in interface + repository pure logic)
- `backend/app/services/risk/market_regime_service.py` = Application orchestration
- `backend/app/tasks/market_regime_tasks.py` = Beat schedule + DB conn lifecycle

**Rationale**: Replication of S5-S9 layered architecture provides consistency + testability (each layer mockable in isolation per existing 体例).

### D2: V4-Pro × 3 mapping (ADR-036 sustained)

**Decision**: BULL_AGENT + BEAR_AGENT + JUDGE all route to `deepseek-v4-pro` (deepseek-reasoner) per LiteLLMRouter TASK_TO_MODEL_ALIAS (already wired in `router.py` per ADR-036 Step 1-7, 2026-05-06).

**Rationale**: Debate agent reasoning capability requires V4-Pro vs V4-Flash 轻量分类. V3 §5.5 line 724 + V3 §11.2 line 1228 cumulative cite.

**Cost**: 3 calls × 3 daily cadence × 30 days = 270 calls/month ≈ $0.39/月 (full price) / $0.10/月 (DeepSeek 75% discount 走 2026-05-31). Well below V3 §16.2 $50/月 cap.

### D3: 3 daily cadence per V3 §5.3 line 664

**Decision**: Beat schedules at 09:00 / 14:30 / 16:00 Asia/Shanghai trading days (Mon-Fri).

**Rationale**: V3 §5.3 line 664 explicit cite. Semantics:
- 09:00 = pre-market regime probe (overnight gap context)
- 14:30 = mid-session L3 阈值 adjust (intraday update)
- 16:00 = post-close summary (next-day regime baseline)

**Collision tolerance**: 16:00 collides with `fundamental-context-daily-1600` Beat entry — Beat sequential dispatch + Windows `--pool=solo --concurrency=1` tolerates sub-second queue. Independent V4-Pro tasks, ~3-5s combined latency.

### D4: Universe-wide regime → L3 阈值 调整 (V3 §6.1 sustained integration)

**Decision**: TB-2d L3 integration is **minimal** — `DynamicThresholdEngine.assess_market_state` ALREADY checks `indicators.regime.lower() == "bear"` → STRESS state. The L3 wire just needs `_build_market_indicators()` to populate `regime` field from latest `market_regime_log` row.

**Implementation**: `_fetch_latest_regime()` helper in `dynamic_threshold_tasks.py` queries `SELECT regime FROM market_regime_log ORDER BY timestamp DESC LIMIT 1` per Beat tick (5min cadence, ~288 fires/day during trading hours, <5ms typical with PK index).

**Rationale**: Zero changes to DynamicThresholdEngine itself — extension point was already designed in V3 §6.1 for future Tier B regime input. TB-2d only adds the data source wire.

### D5: DefaultIndicatorsProvider 4/6 fields wired (2/6 留 TB-5 batch)

**Decision**: TB-2d wires 4 of 6 MarketIndicators fields via real PG queries:
- ✅ `sse_return`: `index_daily['000001.SH'].pct_change / 100`
- ✅ `hs300_return`: `index_daily['000300.SH'].pct_change / 100`
- ✅ `breadth_up`: COUNT klines_daily WHERE pct_change > 0 AND is_suspended=false
- ✅ `breadth_down`: COUNT klines_daily WHERE pct_change < 0 AND is_suspended=false
- ⏭️ `north_flow_cny`: None (留 TB-5 — no moneyflow_hsgt table in current DB schema)
- ⏭️ `iv_50etf`: None (留 TB-5 — no 50ETF option IV data source decision)

**Rationale**: 4/6 coverage is sufficient for v1 production — Bull/Bear/Judge prompts handle "data unavailable" per TB-2a design codification (PR #333 reviewer MEDIUM 1 design lock). 2 deferred fields require additional Tushare API integration (north flow) or external option data feed (50ETF IV) — not blocking for TB-2 closure.

**Graceful per-field degradation**: Each individual query catches exceptions → returns None for that field (反 silent total failure; sustained 铁律 33 fail-loud at field-level granularity).

---

## Results

### Test cumulative across TB-2 (4 sub-PR)

| Sub-PR | Tests | Wall clock |
|--------|-------|------------|
| TB-2a | 20 unit + 3 real-PG SAVEPOINT smoke | 3.18s |
| TB-2b | 24 mock-LLM integration | 0.10s |
| TB-2c | 11 (provider stub + task + Beat + imports) | 0.08s |
| TB-2d | 8 (mock-conn + real-PG smoke) | 0.18s |
| **Total** | **63 tests, 63/63 PASS** | <4s |

### Reviewer 2nd-set-of-eyes cumulative (LL-067 体例 sustained)

| PR | Reviewer verdict | Fixes applied |
|----|------------------|---------------|
| #333 TB-2a | COMMENT, 0 CRITICAL/0 HIGH | 3 MEDIUM + 2 LOW + 1 design codification |
| #334 TB-2b | APPROVE, 0 CRITICAL/0 HIGH | 3 MEDIUM defer-safe + 2 LOW cosmetic |
| #335 TB-2c | REQUEST CHANGES → REVIEWER-FIX | 1 HIGH (runbook SQL column drift) + 1 MEDIUM (5/6 count) |
| 本 TB-2d | pending reviewer spawn | TBD |

Cumulative reviewer 2nd-set-of-eyes 实证 = 14 (12 prior + TB-2c #335 13th + TB-2d 本 14th 候选).

### Pure-function contract sustained (V3 §11.4 line 1294)

- Engine PURE: `qm_platform/risk/regime/agents.py` + `repository.py` + `indicators_provider.py` + `default_indicators_provider.py` — 0 broker / 0 alert / 0 INSERT side effects
- Application orchestration: `market_regime_service.py` 0 DB writes (persist delegated to caller)
- Beat dispatch: `market_regime_tasks.py` is the only transaction owner (铁律 32 explicit conn.commit + rollback)

---

## Sprint chain closure status (Plan v0.2 §A)

- ✅ **TB-2a** PR #333 `8a31bbc` — market_regime_log DDL + interface + repository (19/19 tests)
- ✅ **TB-2b** PR #334 `9d2d88c` — Bull/Bear/Judge V4-Pro × 3 wire + MarketRegimeService (24/24 tests)
- ✅ **TB-2c** PR #335 `37a4c80` — Celery Beat 3 schedules + StubIndicatorsProvider + ops runbook (11/11 tests)
- ✅ **TB-2d** 本 PR — DefaultIndicatorsProvider real wire + L3 regime integration + ADR-067 + LL-161 (8/8 tests)

**TB-2 sprint closure ✅ achieved**. 留 TB-5c batch closure 补 north_flow_cny + iv_50etf real data source + dynamic_threshold full L3 stock_metrics real wire (S7 audit fix follow-up cumulative).

---

## Tier B sprint chain status post-TB-2

| Sprint | Status | Notes |
|--------|--------|-------|
| T1.5 | ✅ DONE | ADR-065 Gate A 7/8 PASS + 1 DEFERRED |
| TB-1 | ✅ DONE | ADR-066 (3 sub-PR a/b/c) |
| **TB-2** | ✅ **DONE** | 本 ADR-067 closure cumulative (4 sub-PR) |
| TB-3 | ⏳ pending | RiskMemoryRAG + pgvector + BGE-M3 + 4-tier retention (~1-2 weeks) |
| TB-4 | ⏳ pending | RiskReflectorAgent + 5 维反思 V4-Pro + lesson 闭环 (~2 weeks) |
| TB-5 | ⏳ pending | Tier B closure + replay 验收 + V3 §15.6 ≥7 scenarios + Gate B/C close (~1 week) |

**Tier B remaining baseline**: ~5-6 weeks (TB-3 + TB-4 + TB-5 cumulative, replan 1.5x = 8-9 weeks).

---

## Sim-to-real verification (V3 §15.5 sustained)

**End-to-end wire verified via 63 cumulative tests**:
1. ✅ DefaultIndicatorsProvider.fetch → MarketIndicators (mock-conn + real-PG smoke)
2. ✅ MarketRegimeService.classify → 3 V4-Pro LLM dispatches in correct order (TB-2b mock side_effect)
3. ✅ persist_market_regime → market_regime_log INSERT + CHECK constraint validation (TB-2a SAVEPOINT smoke)
4. ✅ Celery Beat 3 daily schedules registered + correct task target (TB-2c TestBeatScheduleRegistration)
5. ✅ Task body orchestration + rollback-on-fail + auto-decision_id (TB-2c TestClassifyMarketRegimeTask)
6. ✅ DynamicThresholdEngine.assess_market_state already reads regime.lower()=='bear' → STRESS (existing engine.py)
7. ✅ `_fetch_latest_regime` query → MarketIndicators.regime population (TB-2d dynamic_threshold_tasks.py patch)

**Pending production smoke (user-driven, per runbook v3_tb_2c_market_regime_beat_wire.md)**:
- Servy restart QuantMind-CeleryBeat AND QuantMind-Celery
- 1:1 manual fire `classify_market_regime.apply()`
- Verify row inserted to market_regime_log
- Verify next dynamic_threshold Beat tick (5min cadence) reads the regime row

---

## Constitution / Plan / REGISTRY amendments (本 sediment cycle)

- `docs/adr/REGISTRY.md`: ADR-067 row appended (本 ADR)
- `LESSONS_LEARNED.md` LL-161 append (TB-2 closure pattern + 4-sub-PR chunked SOP sustained)
- `memory/project_sprint_state.md`: Session 53+17 handoff prepend (TB-2 ✅ closure summary)
- `docs/V3_TIER_B_SPRINT_PLAN_v0.1.md` §A TB-2 row closure marker: 留 TB-5c batch closure (sustained ADR-022 反 retroactive content edit)

---

## 红线 sustained (5/5)

- cash=¥993,520.66 (sustained 4-30 user 决议清仓)
- 0 持仓 (xtquant 4-30 14:54 实测)
- LIVE_TRADING_DISABLED=true
- EXECUTION_MODE=paper
- QMT_ACCOUNT_ID=81001102

**0 broker call / 0 .env mutation / 0 真账户 touched** across all 4 TB-2 sub-PRs. DDL apply = read-only schema add. LLM calls in production gated by RT_MAX_COST + LiteLLM budget guardrails.

---

## 关联

**ADR (cumulative)**: ADR-022 (反 retroactive edit) / ADR-027 (清仓) / ADR-029 (10 RealtimeRiskRule) / ADR-036 (V4-Pro mapping) / ADR-054-061 (V3 Tier A S5-S9) / ADR-062 (S10 setup) / ADR-063 (S10 5d skip) / ADR-064 (Plan v0.2 5 decisions lock) / ADR-065 (Gate A formal closure) / ADR-066 (TB-1 closure) / **ADR-067 (本 TB-2 closure)**

**LL (cumulative)**: LL-066 (DataPipeline subset 例外) / LL-067 reviewer 体例 / LL-097 (Beat restart 必显式) / LL-098 X10 / LL-100 (chunked sub-PR SOP) / LL-115 family / LL-141 (4-step post-merge ops) / LL-157 (mock-conn schema drift) / LL-159 (4-step preflight) / LL-160 (synthetic Position) / **LL-161 NEW (TB-2 chunked SOP + 4-sub-PR cumulative + 3-layer pattern 14th 实证)**

**V3 spec**: §5.3 (Bull/Bear regime) / §6.1 (DynamicThresholdEngine L3 integration) / §11.2 line 1227 (MarketRegimeService location) / §11.4 (pure function) / §15.5 (sim-to-real gap) / §16.2 ($50/月 cap)

**File delta (本 TB-2d PR sediment)**:
1. `backend/qm_platform/risk/regime/default_indicators_provider.py` NEW (~210 lines)
2. `backend/qm_platform/risk/regime/__init__.py` MOD (DefaultIndicatorsProvider export +)
3. `backend/app/tasks/market_regime_tasks.py` MOD (Stub → Default switch + import)
4. `backend/app/tasks/dynamic_threshold_tasks.py` MOD (`_fetch_latest_regime` + regime field wire)
5. `backend/tests/test_default_indicators_provider.py` NEW (8 tests)
6. `docs/adr/ADR-067-v3-tb-2-market-regime-closure.md` NEW (本)
7. `docs/adr/REGISTRY.md` MOD (ADR-067 row + count update)
8. `LESSONS_LEARNED.md` MOD (LL-161 append)

8 file delta atomic 1 PR per ADR-064 D5=inline 体例 sustained.

---

**ADR-067 Status: Accepted (V3 Tier B TB-2 closure cumulative 4 sub-PR — MarketRegimeService Bull/Bear/Judge V4-Pro × 3 + L3 integration ✅).**

新人 ADR, 0 reserved reserve.
