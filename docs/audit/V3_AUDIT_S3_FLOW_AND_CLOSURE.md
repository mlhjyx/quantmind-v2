# V3 Audit Section III — Business Flow + Closed-Loop Verification (2026-05-18 evening)

> **Source**: Subagent D (6 Business Flow + Service Graph) + Subagent E (Closed-Loop + Cascade)
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §8 6+ Business Flow Text-Diagrams

### §8.1 Flow 1 — 数据流 (Data Pipeline)

```
[Tushare API] → tushare_source.py ─┐
[Baostock API] → baostock_source.py ┤
[QMT xtquant] → qmt_source.py ──────┼─► DataPipeline (services/data_orchestrator.py:35)
[6 News APIs] → news/pipeline.py:45 ┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
[klines_daily 11.7M]   [factor_values 840M TimescaleDB 152 chunks]
[daily_basic 11.6M]    [Parquet cache 按年]
[moneyflow 5K/day]              │
[minute_bars 190M]              ▼
                       [Factor Engine — backend/engines/factor_engine/]
```

**Schtask触发器** (Batch 1 verified Disabled): DailyDataIngest_Preopen 09:25 / _Postclose 17:00 / DailyMoneyflow 17:30 / DataQualityCheck 17:45.

**Broken-link #1** [heuristic#4]: Until schtask re-enabled, klines_daily/daily_basic/moneyflow flow **statically disabled at upstream** — last successful 2026-04-28 per Session 50 sediment (20 trading days stale).

**Broken-link #2** [heuristic#20]: `fundamental_context_service.py:136` INSERT is **single-source AKShare** vs V3 §3.3 spec 8 维 (only 1/8 维 wired).

### §8.2 Flow 2 — 信号流 (Signal Generation)

```
[16:30 SH signal_phase Beat] (beat_schedule.py:248 crontab 30/16 Mon-Fri)
              │
              ▼
[signal_service.py:48 SignalService.generate_signals]
              ├──► [load market_data — _load_shared_data via parquet_cache]
              ├──► [factor compute — factor_compute_service]
              ├──► [IC weight — factor_ic_history table lookup]
              ▼
[qm_platform/signal/pipeline.py:76 PlatformSignalPipeline.compose (line 105)]
              ├──► [SignalComposer — engines/signal_engine.py]  (raw weights)
              ├──► [PortfolioBuilder] (Top 20 + SN b=0.50 + industry cap)
              ▼
[SignalResult → signal_service.py:38]
              ├──► [intraday_pre_filter (ST/halt/limit-up)]
              ▼
[_write_signals — signal_service.py:478] → signals table
              ▼
[DailySignal schtask 17:15 SH] (Ready)
```

**Broken-link #3** [heuristic#4]: `pipeline.py:62 FactorStaleError` exception class exists but staleness window **not anchored to TradingDayProvider**. With schtask disabled and DB stale (4-28), pipeline will raise FactorStaleError on first manual trigger.

### §8.3 Flow 3 — 交易流 (Trade Execution)

```
[09:31 SH execute_phase] (run_paper_trading.py)
              ▼
[Step 4: load signal] → [Step 5.9: CB check] → [Step 6: hedged_target?]
              ▼
[run_paper_trading.py:466] exec_svc.process_pending_orders(dry_run=dry_run) ✅ LL-183 fix
              ▼
[run_paper_trading.py:482] exec_svc.execute_rebalance(dry_run=dry_run) ✅ LL-183 fix
              ▼
[execution_service.py:51 ExecutionService.execute_rebalance]
              ├──► [_filter_nontradable_codes — line 283]
              ├──► [execution_service.py:412 if dry_run:] ✅ LL-183 fix gate
              │           ├─ True → log "live模式 dry-run: 跳过QMT下单" → return
              │           └─ False → adapter = QMTExecutionAdapter (line 417)
              ▼
[QMTExecutionAdapter] → [OrderTracker.can_place_order] → [_check_buy_protection]
              ▼
[broker_qmt.py — LL-182 5-axis fix]
              ▼
[trade_log] → [position_snapshot] → [NAV]
```

**Confirmed LL-183 fix anchors** (CC verified 2026-05-18 23:00):
- `scripts/run_paper_trading.py:466` ✅ + `:482` ✅
- `backend/app/services/execution_service.py:412-413` ✅

**Broken-link #5** [heuristic#4 P0-24]: line 412-414 dry_run branch returns without explicitly initializing `fills`/`new_pending`; line 432 `if new_pending and not dry_run` may NameError on dry_run path.

### §8.4 Flow 4 — V3 风控流

```
[QMT tick] → [subscribe_quote callback]
              ▼
[qm_platform/risk/realtime/engine.py:43 RealtimeRiskEngine.on_tick]
              ▼
[10 RealtimeRiskRule.evaluate]
   ├─ SingleStockStopLossRule (rules/single_stock.py:72)
   ├─ NewPositionVolatilityRule (rules/new_position.py:49)
   ├─ IntradayPortfolioDropRule (Drop3PctRule + Drop5PctRule + Drop8PctRule)
   ├─ QMTDisconnectRule (rules/intraday.py:176)
   ├─ PositionHoldingTimeRule
   ├─ CircuitBreakerRule
   ├─ QMTFallbackTriggeredRule
   ├─ PMSRule
   └─ rules/realtime/rapid_drop.py
              ▼
[RuleResult] → [AlertDispatcher] → [DingTalk channel chain] → [risk_event_log]
              ▼
[L4 STAGED — planner.py:174 L4ExecutionPlanner]
   ├─ cancel_deadline (line 78)
   ├─ _compute_cancel_deadline (line 274) [hardcoded _CANCEL_WINDOW_MINUTES — P1-25]
   ├─ timeout_execute (line 96)
   └─ is_past_deadline check (line 143)
              ▼
[confirm/execute → 反向 sell] via broker_qmt
```

**L2 MarketRegime Beat**: 09:00/14:30/16:00 (beat_schedule.py:270/278/286)
**L3 DynamicThresholdEngine** (engine.py:107)
**L5 ReflectorAgent** (agent.py:296, Sun 19:00 + month 1st 09:00)
**元监控** (every 5min ALL hours)

**Broken-link #7** [heuristic#4 CRITICAL P1-25]: `_CANCEL_WINDOW_MINUTES` hardcoded constant (planner.py:317-318), V3 ADR-027 §2.2 spec says yaml-driven.

**Broken-link #9** [heuristic#3]: subscribe_quote depends on `qmt_data_service.py:65` standalone process. If dies, **0 on_tick** fires → all 10 realtime rules silently inactive. P0-008 confirmed Redis dark.

### §8.5 Flow 5 — 因子研究流

```
[新因子 proposal] (FACTOR_TEST_REGISTRY.md row)
              ▼
[IC compute — compute_daily_ic.py:219]
              ▼
[factor_ic_history table] (铁律 11 唯一入库)
              ▼
[factor_profiler V2]
              ▼
[Gate G1-G10 — engines/factor_gate.py]  ⚠️ NO RUNNER (P1-34)
              ▼
[backtest — paired bootstrap p<0.05]
              ▼
[onboard/reject — factor_onboarding.py]
              ▼
[factor_lifecycle — Beat 周五 19:00]
   └─ active / warning / deprecated
```

**Broken-link #10**: Phase 3D LightGBM CLOSED but `engines/ml_engine.py` + `engines/mining/` still exist (heuristic #22 dead code).

**Broken-link #11**: Alpha158 158 factors vs 113 in factor_ic_history → 45 factor gap (P1-27).

### §8.6 Flow 6 — 对账+报表流

```
[15:40 SH reconciliation Beat]
              ▼
[backend/app/services/qmt_reconciliation_service.py:35]
              ▼
[17:35 SH PT audit — scripts/pt_audit.py:672]
   ├─ check_st_leak / check_mode_mismatch / check_turnover_abnormal
   ├─ check_rebalance_date_mismatch / check_db_drift
              ▼
[send_aggregated_alert (line 653)]
              ├──► _send_alert_via_platform_sdk (primary)
              └──► _send_alert_via_legacy_dingtalk (fallback)
              ▼
[DingTalk + frontend Dashboard]
              ▼
[scheduler_log table]
```

**Broken-link #12**: dual implementation (primary + legacy fallback) NOT auto-triggered on dedup_key collision.

### §8.7 Flow 7 — News + LLM Pipeline

```
[6 News API cron] (Beat 110/126/146)
              ▼
[qm_platform/news/pipeline.py:45 DataPipeline.fetch_all]
   ├─ AnspireNewsFetcher / AkshareCninfo / RsshubFetcher / Tavily / Marketaux / GDELT / Zhipu
   ├─ _safe_fetch wrapper (line 236)
   └─ _dedup_items (line 241)
              ▼
[news_raw table]
              ▼
[NewsClassifier V4-Flash via LiteLLMRouter:123]
              ▼
[news_classified] → [FundamentalContext daily] → [Bull/Bear/Judge debate]
              ▼
[market_regime_log]
```

**Broken-link #14** [heuristic#4 CRITICAL P1-29]: `LiteLLMRouter:407 FallbackDetectionError` raises but no automatic V4-Flash → V4-Pro failover per ADR-028.

### §8.8 Flow 8 — L5 Reflector Pipeline

```
[Sun 19:00 / month 1st 09:00 Beat]
              ▼
[risk_reflector_tasks.py:171] → [ReflectorAgent.reflect:333]
   ├─ _load_prompt (reflector_v1.yaml)
   ├─ V4-Pro 5维反思 via LiteLLMRouter.completion
   └─ _parse_reflection_response
              ▼
[ReflectionOutput → reflection_log] → [risk_memory pgvector via BGE-M3 embedding]
              ▼
[adapt candidate]  ⚠️ apply_reflection NOT WIRED (P0-4)
```

**Broken-link #16** [heuristic#4 P0-4]: Reflector → ThresholdEngine NOT wired. Grep `apply_reflection|adapt_threshold` 0 hits.

---

## §9 Service Interaction Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Frontend (React 18 — 31 days stale since 2026-04-17)                   │
│  Dashboard/* ─► /api/dashboard      RiskMonitor.tsx ─► /api/risk        │
│  FactorLibrary ─► /api/factors      PMS.tsx ─► /api/pms                 │
│  BacktestRunner ─► /api/backtest    Execution ─► /api/execution         │
│  MarketData.tsx ─► /api/market      PipelineConsole ─► /api/pipeline    │
│  AgentConfig.tsx ─► /api/strategies                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Service Layer (sync psycopg2, no commit per铁律 32, 30 violations P0-9)  │
│                                                                          │
│  SignalService ◄──► FactorRepository ◄──► FactorComputeService            │
│       │                                                                  │
│       ▼                                                                  │
│  PlatformSignalPipeline ──► SignalComposer ──► PortfolioBuilder           │
│       │                                                                  │
│       ▼                                                                  │
│  ExecutionService ──► QMTExecutionAdapter ──► BrokerQMT ──► xtquant       │
│       │                                                                  │
│       ▼                                                                  │
│  PlatformRiskEngine ──► 10 RealtimeRiskRule ──► AlertDispatcher           │
│                              ├──► DingTalkDispatcher                     │
│                              └──► email_backup                            │
│                                                                          │
│  QMTReconciliationService ──► xtquant.query_stock_positions              │
│  FundamentalContextService ──► AKShare (single source vs V3 §3.3 spec 8) │
│  ReflectorAgent ──► LiteLLMRouter ──► V4-Pro                             │
│  NewsService → 6 NewsFetcher → news_raw                                  │
└──────────────────────────────────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Beat / Schtask Triggers                                                  │
│  Celery Beat (32 entries) + Windows Schtask (19, 4 Disabled) + Servy     │
└──────────────────────────────────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Event Bus + DB                                                           │
│  Redis Streams qm:* (verified 0 keys live — P0-8)                        │
│  TimescaleDB (PG 16.8 + TS 2.26.0): factor_values 840M / klines 11.7M    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## §10 Closed-Loop Verification (5 of 7 Broken)

| Loop | Description | Status | Heuristic | Master P0/P1 |
|---|---|---|---|---|
| **Loop 1** | Signal → Execute → Performance → Feedback to Signal | ❌ **OPEN** — signal_service.py:60 0 NAV / past trade_log refs | #4 | P1-31 |
| **Loop 2** | Risk Event → STAGED → Reflector → Threshold adapt → Detection | ❌ **NOT WIRED** — apply_reflection grep 0 hits | #4 / #16 | **P0-4** |
| **Loop 3** | Factor → IC → Profile → Lifecycle → Strategy → Backtest → Feedback | ⚠️ **HALF-BROKEN** — manual handshake only at backtest→pool | #4 | medium |
| **Loop 4** | News → Regime → Threshold → Detection | ⚠️ **REGIME → SIGNAL disconnect** — only risk threshold | #4 | P1-32 |
| **Loop 5** | LLM call → Cost → Budget → Throttle | ✅ **CLOSED** with caveat (conn_factory=None bypass) | — | P2 |
| **Loop 6** | Backup → Verify → Restore test → Confidence | ❌ **NEVER TESTED** — pg_restore --list TOC only | #4 / #6 | **P0-3** |
| **Loop 7** | Schtask → Log → Health → Alert | ❌ **NO BEAT/SCHTASK FRESHNESS PROBE** (LL-181) | #4 / #16 | **P0-5/P0-6** |

---

## §11 Failure Cascade Map (Top 9 SPF)

| SPF | Cascade hops | Pre-Mortem (heuristic #16) |
|---|---|---|
| **SPF 1** DB unreachable | 5 | PG OOM repeat 2026-04-03 history → signal_phase silent fail → execute 0 orders |
| **SPF 2** Redis unreachable | 6 | qm:* die → outbox backup → portfolio:current stale → tick blind → no risk action |
| **SPF 3** xtquant disconnect (LL-180/182) | 5 | subscribe_quote 0 ticks → 10 rules silent → broker can't place |
| **SPF 4** Beat death (LL-179/181) | **8 (longest)** | 32 schedules 0 fire → news/regime/factor cascade → NAV drift, slow detection |
| **SPF 5** LLM unavailable | 5 | NewsClassifier fail → Bull/Bear/Reflector fail → regime stale |
| **SPF 6** Tushare quota/rate limit | 7 | daily_basic missing → factor compute NULL → IC SKIP → lifecycle false warning |
| **SPF 7** schtask QuantMind_DailyExecute Disabled forgot re-enable | 4 | signals generated but never executed → cash drifts vs target |
| **SPF 8** .env unrolled to live forgot revert | **3 (CRITICAL NOW)** | If schtask accidentally re-enabled → real broker fire on next signal |
| **SPF 9** Memory drift (CC restart, bus factor=1) | 4 | CC re-tests known-failed direction (mf_divergence repeat 5x pattern) |

### §11.bis Maximum Cascade Chain (Beat Death, 8 hops)

```
Beat dies → 32 schedule entries 0 fire → news stale → market_regime stale
→ ThresholdCache stale → RealtimeRiskEngine uses defaults → factor_lifecycle skip
→ stale active factors → live IC drift → NAV decline (root cause obscured)
```

**Strategic risk severity**: CRITICAL. Single-point failure causes cross-domain degradation. Slow-to-detect.

**Mitigation priority**: Beat heartbeat probe + Schtask freshness probe = **first 2 P0s** post-LL-183. P0-5 + P0-6.

---

**End Section III.**
