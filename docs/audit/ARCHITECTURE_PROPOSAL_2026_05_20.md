# Architecture Proposal — Plan v9 Phase M (2026-05-20)

> **Trigger**: User /goal — "代码 vs 设计文档对照,识别 gap,更新文档,给出更好方案,设计验收目标,实施闭环"
> **Method**: Comprehensive read of 14+ root + docs/ design files + cross-module synthesis
> **Author**: Architect agent (OMC), 2026-05-20 ~03:00 SH
> **Phase**: Plan v9 Phase M (continuation post Phase A-L)
> **5/5 红线 sustained**: ✅ (Phase B-1 frozen)

---

## §1 Executive Summary — 现状评估

### System Maturity Rating (9 modules)

| Module | Maturity | Test Coverage | Production Status |
|---|---|---|---|
| **Data** (Tushare + DataPipeline) | 90% | 200+ tests | ✅ Production |
| **Factor** (CORE3+dv_ttm + IC chain) | 90% | 300+ tests | ✅ Production (5-19 sustained) |
| **Backtest** (Hybrid Python engine) | 85% | 100+ tests | ✅ Reproducible baseline |
| **Strategy + Signal** (Wave 3 MVP 3.3) | 80% | 80+ tests | ✅ PR #116 Stage 3.0 |
| **Risk Framework** (V3 §S5-S8) | 95% | 334 tests | ✅ All merged main |
| **AI Loop** (Layer 1-2 / Layer 3-4) | 55% / 0% | 50+ tests | 🟡 L1-2 active / L3-4 Q3-Q4 |
| **Frontend** (Phase H W1-W6) | 65% | 0 jest/vitest | 🟡 Phase H closed, Phase I 50h pending |
| **Notifications** (DingTalk + 25 templates) | 60% | 30+ tests | 🟡 HMAC pending (P1-43) |
| **Schedule** (20 Beat + 27 schtask) | 75% | 20+ tests | 🟡 4 FAIL + 1 never-run |

### Top 3 Strengths

1. **Rigorous iron-law governance**: 46 rules (32 T1 + 14 T2) + 172+ LL entries, near-zero regression
2. **Walk-forward validated strategy**: CORE3+dv_ttm WF OOS Sharpe 0.8659, max_diff=0 regression baseline
3. **Mature platform SDK**: 16 framework modules under `backend/qm_platform/`, 23 MVPs designed, Wave 1-3 ✅ complete

### Top 3 Weaknesses

1. **Frontend-backend consumption gap**: 74 backend-only endpoints (50% of 148) + 10 frontend orphans
2. **Dual scheduling architecture**: 20 Celery Beat + 27 Windows schtask without unified management
3. **Chronic documentation drift**: ~30% pre-Plan v9 (now ~12% post-sediment); needs automated detection

---

## §2 Per-doc Reading Matrix (18 design docs)

| Doc | Lines | Main Contents | Impl Match | Quality | Plan v9 Action |
|---|---|---|---|---|---|
| **SYSTEM_BLUEPRINT.md** | 791 | 16 chapters: architecture + data + factor + signal + backtest + execution + risk + multi-strategy + ML + AI loop + frontend + schedule + params + forex + upgrades | 80% | Good (code-first truth) | ✅ §12.1 sediment (148 endpoints + Phase H) |
| **PLATFORM_BLUEPRINT.md (QPB v1.16)** | ~600 | 12 Framework + 6 升维 + 17 MVPs, Wave 1-3 complete | 85% | Excellent (anti-bloat rules) | 🟡 QPB v1.17 Framework #13 (Calendar) decision |
| **CLAUDE.md** | ~600 | 编码规则 + 铁律 SSOT reference + navigation | 95% | Excellent | ✅ L424 AI EVOLUTION sediment (0% → 45-55%) |
| **IRONLAWS.md** | ~500 | 46 rules (T1+T2) + tier system + LL/ADR backref | 95% | Excellent governance | Sustained |
| **DEV_BACKEND.md** | ~400 | 3-layer architecture + data flows + module matrix | 70% | Good structure | ✅ 96→148 endpoints + 25→57 services |
| **DEV_BACKTEST_ENGINE.md** | ~600 | Hybrid + 8 modules + 34 decisions + WF | 65% | Partially obsolete (Rust never impl) | ✅ §1-§十 HISTORICAL marker + stamp_tax + can_trade TRUTH |
| **DEV_FACTOR_MINING.md** | ~500 | LLM 3-Agent + GP + FactorDSL + Alpha158 | 55% | Numbers drifted | ✅ Alpha158 158→~40 + Phase C LOC |
| **DEV_FRONTEND_UI.md** | 1094 | 12 pages + Glassmorphism + components | 65% | Seriously stale | ✅ Phase H W1-W6 5 NEW components + Axios SSOT |
| **DEV_SCHEDULER.md** | ~350 | Beat + schtask dual + time sequences | 30% (self-label) | Partially obsolete | ✅ Phase D 20 Beat + 27 schtask inventory |
| **DEV_PARAM_CONFIG.md** | ~400 | 220+ params across 11 modules | 25% | DESIGN_OVERSIZED | ✅ Header warning + SSOT redirect |
| **DEV_AI_EVOLUTION.md** | 705 | 4-layer + Orchestrator state machine + L1-L4 | 45-55% | Good design, claim drifted | ✅ V3 §S5-S8 merged sediment + Layer 3-4 deprecation |
| **DEV_NOTIFICATIONS.md** | ~300 | NotificationService + DingTalk + 25 templates + throttler | 60% | Path drift | ✅ Dual-layer architecture (alert.py + dingtalk_webhook_service.py) |
| **GP_CLOSED_LOOP_DESIGN.md** | ~400 | FactorDSL + Warm Start GP + 5 seeds | 45% | Numbers unverified | ✅ Implementation status table + 7-op claim marked unverified |
| **RISK_CONTROL_SERVICE_DESIGN.md** | ~350 | L1-L4 circuit breaker state machine | 35% | L4 DEPRECATED | ✅ V3 ADR-027 SSOT redirect header |
| **V3_IMPLEMENTATION_CONSTITUTION** | ~800 | 20+ sections: governance + anti-hallucination + skill/hook coord | 90% | Excellent | Sustained (§L10 amend pending TB-5c) |
| **V3_DESIGN (Risk Framework)** | ~1000 | 5+1 layer risk + news ingest + real-time rules + reflector | 70% | Excellent design (S5-S8 merged) | Sustained (Layer 3-4 Q3-Q4) |
| **ML_WALKFORWARD_DESIGN.md** | 1096 | LightGBM WF + feature eng + 5 fold | FROZEN | Good technical (experimentally invalidated) | Annotate FROZEN status |
| **SYSTEM_STATUS.md** | ~1500 | System state snapshot + sprint progress | 75% | Numbers stale (factor_values 501M vs 840M real) | ✅ §0.-5 Plan v9 closure addendum |
| **FACTOR_TEST_REGISTRY.md** | 168 | Factor test results + PASS/FAIL/INVALIDATED status | 90% | Compact | Add explicit M=213 cumulative counter (P2) |
| **LESSONS_LEARNED.md** | ~7000 | 173 LL entries (post-Plan v9 LL-193 sediment) | 95% | Active maintenance | ✅ LL-193 audit cascade error appended |

### §2.1 Root Cause of Documentation Drift

Pre-Plan v9 ~30% drift not from carelessness but **structural**: no automated mechanism detects when code changes invalidate design doc claims. The 46 iron laws govern code behavior but only T2 rule 22 ("docs follow code") covers sync — insufficient severity for chronic drift. **Proposal 9 (below) addresses this via automated audit**.

---

## §3 Better Solutions — 12 Architectural Proposals

### Proposal 1: Unified Transaction Context Manager (P0)

**Problem**: 9 sites use F16-classC pattern (services commit); 2 sites (`data_orchestrator.py:256` + `t0_19_audit.py:506`) were active iron-law 32 violations until Phase C-1 annotation.

**Solution**: 
- Extract `@transactional` decorator OR `TransactionContext` context manager 
- Wrap service calls with commit/rollback at router/celery caller level
- All commits move to caller, leaf utilities use `with conn.transaction():` pattern

**Implementation steps**:
1. Audit all `\.commit\(\)` / `session.commit()` in `backend/app/services/`
2. Create `backend/app/core/transaction.py` with `TransactionContext`
3. Migrate F16-classC sites one-by-one with regression test per site
4. Add ruff custom rule OR pre-commit check for `\.commit\(\)` in `services/`

**Acceptance criteria** (machine-verifiable):
```bash
grep -r "\.commit()" backend/app/services/ | grep -v "# F16-classC\|# silent_ok" | wc -l  # → 0
```

**Effort**: 2-3 days | **Priority**: P0

---

### Proposal 2: Frontend API Consumption Audit + Dead Endpoint Cleanup (P1)

**Problem**: 74/148 (50%) backend endpoints have no frontend consumer per `docs/API_COVERAGE.md`. 10 frontend calls target nonexistent backend paths. `/api/strategies/list` causes 500 due to routing collision with `/{strategy_id}`.

**Solution**: 
- Annotate each backend-only endpoint: `ADMIN_ONLY` / `INTERNAL` / `DEPRECATED` / `CLEANUP_CANDIDATE`
- Fix 10 frontend orphan paths in `pipeline.ts` (3 done Phase K, 7 remain) + other API modules
- Fix `/api/strategies/list` routing collision (Path param validation OR explicit `/list` route before `/{strategy_id}`)

**Acceptance criteria**:
- `docs/API_COVERAGE.md` shows 0 UNKNOWN-purpose backend-only endpoints
- 0 frontend 404/500 on cold-start page load

**Effort**: 3-5 days | **Priority**: P1

---

### Proposal 3: Schedule Architecture Unification (P1)

**Problem**: Dual scheduling (20 Beat + 27 schtask) with no single management interface. 4 FAIL + 6 STALE + 1 never-run (`VacuumAnalyze` 232034h stale). 2 NotImplementedError stubs in `beat_schedule.py` (per Phase A finding, Phase C-1 clarified as wrapper-implemented).

**Solution**: 
- Create unified schedule registry (`backend/qm_platform/observability/schedule_registry.py`)
- Tracks both Beat and schtask entries programmatically
- Beat heartbeat + schtask freshness probes auto-running
- New endpoint `/api/system/schedules` returns unified JSON view
- Frontend `ScheduleMonitor` component (Phase I addition)

**Acceptance criteria**:
- `GET /api/system/schedules` returns JSON with all 47 scheduled tasks + last-run + health
- 0 `NotImplementedError` stubs in `beat_schedule.py`

**Effort**: 1-2 weeks | **Priority**: P1

---

### Proposal 4: Structured Logging Unification (P1)

**Problem**: Logs scattered across `logs/fastapi-stdout.log`, `logs/celery-stdout.log` etc. with no structured format. Risk events write to `risk_event_log` DB table but operational logs remain unstructured. No log correlation ID across 4 Servy services.

**Solution**: 
- Adopt structured JSON logging with correlation IDs
- Add `structlog` or `python-json-logger` to dependencies
- Create `backend/app/core/logging_config.py` with JSON formatter + correlation ID middleware
- FastAPI middleware injects `request_id`; Celery task decorator injects `task_id`

**Acceptance criteria**:
- `jq '.request_id' logs/fastapi-stdout.log | head -5` returns valid UUIDs
- All log lines parse as valid JSON

**Effort**: 3-5 days | **Priority**: P1

---

### Proposal 5: Test Coverage Expansion to 7000+ (P1)

**Problem**: 6251 tests collected with 0 errors strong, but coverage uneven. Platform risk module has 334 tests; `services/news/` + `services/dispatchers/` minimal. No end-to-end integration fixtures (signal → risk → execution paper-mode).

**Solution**: 
- Add integration test fixtures for 3 critical flows
- Property-based tests (`hypothesis`) for factor engine pure functions
- Target 7000 collected tests

**Acceptance criteria**:
- `pytest --co 2>&1 | tail -1` shows >= 7000 collected
- `pytest -m integration` passes
- 3 new `backend/tests/integration/test_flow_*.py` files exist

**Effort**: 1-2 weeks | **Priority**: P1

---

### Proposal 6: DB Maintenance Automation (P1)

**Problem**: `QuantMind_VacuumAnalyze` schtask never ran (232034h stale per Phase L audit). `factor_values` at 840M rows (172 GB) across 152 TimescaleDB chunks needs regular maintenance. 24 empty tables identified but not cleaned.

**Solution**: 
- Wire VacuumAnalyze schtask properly (script `scripts/vacuum_analyze_heavy_tables.py` exists from Phase G F-S7-008)
- Create `scripts/db_maintenance.py` — top-10 heavy tables VACUUM ANALYZE + TimescaleDB chunk maintenance
- Identify and drop 24 empty tables after confirmation

**Acceptance criteria**:
- `audit_schtask_freshness.py` shows VacuumAnalyze OK status
- `scripts/db_maintenance.py --dry-run` completes without error

**Effort**: 2-3 days | **Priority**: P1

---

### Proposal 7: AI Loop Layer 3-4 Architectural Prep (P2)

**Problem**: Layer 1-2 at ~60% but Layer 3 (Feature Map / MAP-Elites) + Layer 4 (Capital Allocation) at 0%. ADR-028 defers to Q3-Q4 but no concrete interface contracts exist.

**Solution**: 
- Define `backend/qm_platform/eval/feature_map.py` interface (Quality-Diversity archive, MAP-Elites grid)
- Define `backend/qm_platform/strategy/capital_allocator.py` interface
- Interface-only + unit tests, 0 implementation (per QPB pattern)

**Acceptance criteria**:
- `backend/qm_platform/eval/feature_map.py` exists with `FeatureMap` abstract class
- `backend/qm_platform/strategy/capital_allocator.py` exists with `CapitalAllocator` abstract class
- pytest imports succeed

**Effort**: 2-3 days | **Priority**: P2

---

### Proposal 8: Frontend Dual-Track CSS Migration (P2)

**Problem**: LL-187 documents Tailwind 4.1 + legacy CSS coexistence. Phase H W1-W6 added 5 NEW components using modern patterns but 22 existing pages mix styles. ~50h estimated.

**Solution**: 
- Incremental migration page by page
- Highest-traffic first (Dashboard / Execution / FactorLibrary)
- Visual regression with screenshots

**Acceptance criteria**:
- `grep -r "import.*\.css" frontend/src/pages/ | grep -v tailwind | grep -v index.css` → 0 (per migrated page)

**Effort**: ~50h (multi-sprint) | **Priority**: P2

---

### Proposal 9: Doc-Code Sync Automation (P2)

**Problem**: Plan v9 found ~50% initial doc-code alignment. Manual audit effective but expensive. Root cause: no automated detection of doc-code drift.

**Solution**: 
- Create `scripts/audit_doc_code_sync.py` checking key metrics (endpoint count, test count, service count, factor count, schedule count) vs documented values
- Flag drift > 10%
- Wire to weekly schtask or pre-push hook

**Acceptance criteria**:
- `python scripts/audit_doc_code_sync.py` exits 0 when metrics match within 10% tolerance
- Exits 1 with specific drift items listed when out of sync

**Effort**: 3-5 days | **Priority**: P2

---

### Proposal 10: GP Engine Closure (40% → 80%) (P2)

**Problem**: `GP_CLOSED_LOOP_DESIGN.md` shows 40% implementation. FactorDSL and WarmStart exist but closed-loop evaluation (DSL → IC auto-eval → Gate auto → factor_values upsert) is not wired. Session 16d claims of "7 new operators + 243 tests" lack git evidence.

**Solution**: 
- Verify actual GP engine state with fresh code read
- Create `backend/engines/mining/gp_evaluator.py` bridging GP output to existing IC/Gate pipeline
- Add integration test: synthetic GP factor → IC → Gate verdict

**Acceptance criteria**:
- `pytest -k test_gp_to_gate_integration` passes
- GP weekly mining Celery Beat task produces ≥ 1 evaluated candidate per run

**Effort**: 1-2 weeks | **Priority**: P2

---

### Proposal 11: Production Readiness Phase B-2 Prerequisites (P0)

**Problem**: Phase B-2 cutover targeted 5-27 Wed. Prerequisites include: regression baseline refresh (22d stale), DB stale snapshot cleanup, paper-mode 5d dry-run, .env paper→live user authorization.

**Solution**: Checklist-driven cutover with machine-verifiable gates:
1. Run `regression_test.py` to refresh baseline
2. Verify DB data freshness (factor_values, klines_daily dates)
3. Complete paper-mode 5d dry-run with 0 P0 anomalies
4. User explicitly authorizes .env EXECUTION_MODE=live flip

**Acceptance criteria**:
- `cache/baseline/regression_result_*.json` mtime < 7 days
- `audit_schtask_freshness.py` shows 0 FAIL tasks
- Paper-mode dry-run log shows 5 consecutive trading days with 0 P0 anomalies
- User provides written authorization for live flip

**Effort**: 1 week (calendar time for 5 trading days) | **Priority**: P0

---

### Proposal 12: Legacy Code Decommissioning (P2)

**Problem**: Multiple deprecated code paths: old `pms_engine.py` (superseded by Platform Risk), `qm:pms:protection_triggered` StreamBus (F27 dead, no consumer), `RISK_CONTROL_SERVICE_DESIGN.md` L4 state machine (V3 ADR-027 supersedes), `DEV_FOREX.md` archived 5-19 but `DashboardForex.tsx` still placeholder.

**Solution**: Systematic dead code removal with sunset gates:
1. List all deprecated modules with sunset conditions
2. Verify sunset conditions met
3. Remove with single PR per module
4. Update all doc references

**Acceptance criteria**:
- `grep -r "DEPRECATED" backend/ --include="*.py" | wc -l` decreases by ≥ 5
- Removed modules have 0 remaining import references

**Effort**: 3-5 days | **Priority**: P2

---

## §4 Acceptance Criteria Matrix (9 Modules × 6 Test Types)

| Module | Unit | Integration | Smoke | Live | Regression | Observability |
|---|---|---|---|---|---|---|
| **Data** | 200+ tests `pytest -k data` | ⚠️ flow needed (Prop 5) | 5 PASS | schtask 16:15 DailyFetch | N/A | Beat heartbeat OK |
| **Factor** | 300+ tests `pytest -k factor` | ✅ IC chain tested (PR #37-#45) | 8 PASS | lifecycle Fri 19:00 | ✅ baseline max_diff=0 | IC monitor 17:20 |
| **Backtest** | 100+ tests `pytest -k backtest` | ✅ WF 5-fold tested | 3 PASS | N/A | ⚠️ 5yr+12yr 22d stale | N/A |
| **Strategy** | 80+ tests `pytest -k signal or strategy` | ⚠️ Signal-exec flow needed | 2 PASS | DailySignal 16:30 | ✅ Signal bit-identical (PR #116) | config_guard startup |
| **Risk** | 334 tests `pytest -k risk` | ⚠️ AlertDispatcher chain (Phase J) | 4 PASS | Beat 14:30 risk-daily | N/A | ✅ 5min meta-monitor HC-1b |
| **AI** | 50+ tests `pytest -k ai or agent` | ⚠️ RAG consumer wire (Phase J) | 2 PASS | N/A | N/A | ✅ LLM cost (F-S7-001) |
| **Frontend** | ❌ 0 (no jest/vitest) | ❌ 0 | manual | env-state 5s poll | N/A | N/A |
| **Notifications** | 30+ tests `pytest -k notification or alert` | ⚠️ DingTalk HMAC pending | 1 PASS | webhook 未配置 | N/A | throttler metrics |
| **Schedule** | 20+ tests `pytest -k schedule or calendar` | ⚠️ cascade test (Prop 5) | 2 PASS | 27 schtask + 20 Beat | ✅ freshness probe | heartbeat probe |

**Total cells**: 9 × 6 = 54

**Coverage gaps**:
- ❌ Frontend: 0 across all test types except manual — **largest gap**
- ⚠️ Integration tests: 3 critical flow tests missing (Proposal 5)
- ⚠️ AlertDispatcher chain: not wired end-to-end (Phase J)
- ⚠️ DingTalk: HMAC secret not configured (user touchpoint P1-43)

---

## §5 Full Closure Roadmap

### §5.1 Phase J P0 Multi-week (1-2 weeks)

| # | Item | Effort | Cite |
|---|---|---|---|
| J-1 | AlertDispatcher → Beat chain wire | 3-7d | Phase J defer manifest |
| J-2 | daily_reconciliation schtask 复活 | 2h | Same |
| J-3 | RAG consumer wire (V3 §5.4) | 1-2w | V3 design |
| J-4 | trade event publish flow 3→4 | 1w | Same |
| J-5 | Regression baseline refresh | 30min-1h | Phase B-2 prerequisite |

### §5.2 Phase J P1 User Touchpoints

| # | Item | Cite |
|---|---|---|
| J-6 | PG password rotation execute | docs/runbook/pg_password_rotate_playbook.md |
| J-7 | DingTalk HMAC secret 配置 | P1-43 |
| J-8 | 4 schtask register (RotateServyLogs / SchtaskFreshnessProbe / BeatHeartbeatProbe / MarketOpenWatcher) | scripts/register_phase_b_1_schtasks.ps1 |
| J-9 | 5-27 Wed live flip 第 3 trigger '你执行' | ADR-027 §7 |
| J-10 | 11 stale local branches + 3 stale OPEN PRs cleanup | STALE_BRANCHES_AND_PRS_AUDIT_2026_05_20.md |

### §5.3 Phase B-2 Cutover Prerequisites (5-27 Wed)

| # | Gate Criterion | Verify Command |
|---|---|---|
| B2-1 | Regression baseline refreshed (< 7 days stale) | `ls -lt cache/baseline/regression_result_*.json` |
| B2-2 | Paper-mode 5d dry-run with 0 P0 anomalies | `grep "P0" docs/audit/STATUS_REPORT_2026_05_*_pt_paper_dryrun_day*.md \| wc -l` → 0 |
| B2-3 | DB data freshness (factor_values + klines_daily) | `SELECT max(date) FROM factor_values;` >= 5-26 |
| B2-4 | All FAIL schtasks resolved | `python scripts/audit_schtask_freshness.py 2>&1 \| grep FAIL \| wc -l` → 0 |
| B2-5 | User written authorization for .env live flip | ADR-027 §7 explicit signed-off message |

### §5.4 Q3-Q4 Layer 3-4 AI Trigger

| # | Item |
|---|---|
| Q34-1 | Feature Map interface contracts (Prop 7) |
| Q34-2 | Capital allocator interface contracts (Prop 7) |
| Q34-3 | Multi-strategy framework StrategyBase (Blueprint §9) |
| Q34-4 | GP engine closure 40% → 80% (Prop 10) |
| Q34-5 | LLM prompt engineering overhaul (AlphaAgent paradigm) |

### §5.5 Decommissioning Candidates (P2)

| # | Item |
|---|---|
| D-1 | `backend/app/services/pms_service.py` (老 PMS, Platform Risk supersedes) |
| D-2 | `qm:pms:protection_triggered` StreamBus stream (F27 dead, no consumer) |
| D-3 | `RISK_CONTROL_SERVICE_DESIGN.md` L4 state machine (V3 ADR-027 supersedes) |
| D-4 | `frontend/src/pages/DashboardForex.tsx` (placeholder, DEV_FOREX archived) |
| D-5 | `frontend/src/pages/ComingSoon.tsx` (placeholder) |
| D-6 | 2 NotImplementedError Beat stubs (Phase C-1 verified wrappers exist, comments stale) |

**Total roadmap items**: 26 (5 P0 + 5 P1 user + 5 B-2 gates + 5 Q3-Q4 + 6 D-N)

---

## §6 Cross-module Integration Verify Plan

### §6.1 Flow 1: Data → Factor → Signal (Daily Production Chain)
- **Test**: Inject synthetic Tushare data → verify factor_values updated → verify signal_service produces target list
- **Verify**: `pytest backend/tests/integration/test_flow_data_to_signal.py`
- **Current**: Individual modules tested, end-to-end flow test missing
- **Action**: Proposal 5

### §6.2 Flow 2: Signal → Risk → Execution (Paper-mode)
- **Test**: Inject synthetic signal → verify risk engine evaluates → verify staged execution service creates orders (paper mode)
- **Verify**: `pytest backend/tests/integration/test_flow_signal_to_execution.py`
- **Current**: Wave 3 MVP 3.3 wired Stage 3.0 switch, no automated flow test
- **Action**: Proposal 5

### §6.3 Flow 3: Schedule Cascade (Multi-schtask)
- **Test**: Simulate 16:15 DailyFetch → 16:25 Precheck → 16:30 DailyFactors → 17:00 DailySignal chain with mock time
- **Verify**: `pytest backend/tests/integration/test_flow_schedule_cascade.py`
- **Current**: Individual schtask scripts tested, cascade timing manual
- **Action**: Proposal 5

### §6.4 Flow 4: API Consumer-Producer Pairing
- **Test**: For each frontend API module, verify all called paths return 200
- **Verify**: `python scripts/audit_api_coverage.py --verify-live`
- **Current**: Static `docs/API_COVERAGE.md` documents pairs, 10 orphans identified
- **Action**: Proposal 2 + new audit script

---

## §7 Risk Assessment + Mitigation

### §7.1 5/5 红线 Sustained Mechanisms (continuous)

| Red line | Sustained verify |
|---|---|
| EXECUTION_MODE=paper | backend/.env L17, EnvStateBanner 5s poll |
| LIVE_TRADING_DISABLED=true | backend/.env L20, config_guard startup hard-raise |
| QMT_ACCOUNT_ID=81001102 | backend/.env, mismatch alarm |
| DINGTALK_ALERTS_ENABLED=true | backend/.env, P0 alert path active |
| L4_AUTO_MODE_ENABLED=unset | default false per config.py + ADR-027 hardcoded STAGED |

### §7.2 Phase B-2 Transition Risks (5-27 Wed)

| Risk | Severity | Mitigation |
|---|---|---|
| Regression baseline 22d stale | Medium | Refresh before cutover (B2-1) |
| DB data freshness gap | Medium | Fresh pull + VACUUM ANALYZE (B2-3) |
| schtask 4 FAIL + 6 STALE | Low | Resolve all before cutover (B2-4) |
| Paper-to-live flip user error | High | ADR-027 3-trigger gate (B2-5) |
| Factor IC drift during PT pause | Medium | Fresh IC compute + lifecycle check before first live signal |

### §7.3 AI Loop Ramp-up Risks (Q3-Q4)

| Risk | Severity | Mitigation |
|---|---|---|
| GP closed-loop junk factors | High | G1-G10 auto-eval + paired bootstrap p<0.05 hard gate |
| LLM cost overrun | Medium | V3 §16.2 monthly cap + F-S7-001 cost tracking |
| Feature Map overfitting | Medium | WF validation mandatory before production entry |
| Multi-strategy allocation instability | High | Fixed YAML weights initially, dynamic only after 3-month stable period |

---

## §8 References

- `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` — 16-chapter truth source (791 lines)
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` — QPB v1.16, 12 Framework + 17 MVPs
- `docs/audit/PLAN_V9_DESIGN_REALITY_GAP_MATRIX_2026_05_20.md` — Phase A-B gap matrix
- `docs/audit/SYSTEM_CLOSURE_REPORT_2026_05_20.md` — Phase L end-to-end verification
- `docs/API_COVERAGE.md` — 148 endpoints × 11 frontend modules
- `IRONLAWS.md` — 46 rules (32 T1 + 14 T2)
- `LESSONS_LEARNED.md` — 173 LL entries (post LL-193)
- `backend/qm_platform/` — 16 framework directories
- `backend/qm_platform/risk/` — 10 subdirectories (S5-S8 merged)
- `backend/app/services/` — 40 .py + 3 subdirs (dispatchers/news/risk)
- `backend/engines/backtest/` — 8 modules
- `backend/engines/mining/` — 11 .py (gp_engine/factor_dsl/pipeline_orchestrator etc.)
- `docs/adr/` — 71 ADRs (per Phase G audit)
- `docs/mvp/` — 23 MVP design files

---

## §9 Metrics Summary

- **12 proposals** (2 P0, 6 P1, 4 P2)
- **Acceptance matrix**: 9 modules × 6 test types = **54 cells populated**
- **26 roadmap items** (5 Phase J P0 + 5 J P1 + 5 B-2 gates + 5 Q3-Q4 + 6 decommissioning)
- **4 cross-module integration flows** defined
- **14 risk items** (5 red-line + 5 Phase B-2 + 4 AI loop)

---

**Maintained by**: CC autonomous (Plan v9 Phase M architect agent dispatch, 2026-05-20)
**Verified at**: 2026-05-20 ~03:00 SH
**Status**: Architecture Proposal ready for Phase J prioritization + Phase B-2 cutover preparation
