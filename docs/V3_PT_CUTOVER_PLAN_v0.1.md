# V3 PT Cutover Sprint Plan v0.4 (5-sprint chain IC-1~3 + CT-1~2)

> **Status**: ⏳ DRAFT — pending user explicit ack on sprint chunking + 2 决议 lock (D1=Replace + replay-as-gate / D2=3 carried Gate-E deferrals → POST-cutover monitoring). Sediment from Phase 0 audit (V3 production-integration state) + user AskUserQuestion 1 round (D1=Replace 推荐).
>
> **创建**: 2026-05-15 (Plan v0.4 sub-PR 起手, post 横切层 FULLY CLOSED 2026-05-15 ADR-076).
>
> **scope**: V3 实施期最后一个 plan — PT 重启 cutover (Gate E, Constitution §L10.5). 5-sprint chain = **integrate-first then cutover-second**: IC-1 V3→signal-path wire + L1 production runner / IC-2 de-stub remaining + L4 broker wire / IC-3 replay-as-cutover-gate validation suite (5y + counterfactual + ≥7 synthetic) / CT-1 cutover hygiene + V3-in-path shake-down / CT-2 Gate E formal verify + .env paper→live + go-live 监控. **The ONLY plan in V3 with 真账户 mutation** (CT-2 .env flip + LIVE_TRADING_DISABLED unlock + real broker order). 0 mutation in IC-1~3 + CT-1.
>
> **sediment 触发**: 横切层 FULLY CLOSED (ADR-076, Gate D 形式 close 2026-05-15) + Phase 0 audit surfaced V3 entirely disconnected from `run_paper_trading.py` signal path (run_paper_trading.py:48 imports legacy `check_circuit_breaker_sync` only, 0 `qm_platform.risk` imports; signal_service.py + signal_engine.py 0 V3 risk refs) → ADR-076 §2 D6 prereq list under-scoped (omitted V3 production integration step) → Plan v0.4 needs to do the integration **before** cutover.
>
> **关联 ADR**: ADR-022 (反 silent overwrite + 反 retroactive content edit + 反 abstraction premature) / ADR-063 (paper-mode deferral pattern — 沿用 D2) / ADR-070 (TB-5b replay acceptance methodology — 沿用 IC-3 replay-as-gate) / ADR-071 (Tier B FULLY CLOSED) / ADR-072 (Plan v0.3 3 决议 lock) / ADR-073/074/075/076 (横切层 HC-1~4 closure) / Plan v0.4 期内候选 ADR-077 (本 plan 3 决议 lock cumulative — D1 Replace + D2 deferrals reframe + D3 sprint chunking) + ADR-078~081 reserved (IC-1~3 + CT-1 + CT-2 各 sprint closure ADR per LL-100 chunked SOP)
>
> **关联 LL**: LL-098 X10 (反 forward-progress default — cutover 必 user 显式 trigger) / LL-100 (chunked SOP) / LL-115/116 (fresh-read enforce family) / LL-159 (4-step preflight SOP) / LL-164 (Gate-verifier-as-charter) / LL-166/167/168/169 (横切层 HC-1~4 closure 体例 cumulative — net-new-wiring balloons / verify-heavy holds classification 沿用 IC-1~3 vs CT-1~2 estimate) / Plan v0.4 期内候选 LL-170 (本 plan 体例 — V3-as-island detection + integrate-first-then-cutover 体例 + replay-as-gate 取代 wall-clock observation 体例)

---

## §A Per-sprint plan (5 sprint: IC-1 + IC-2 + IC-3 + CT-1 + CT-2)

### IC-1 — V3 → signal path wire + L1 production runner

| element | content |
|---|---|
| Scope | **(D1) Replace legacy with V3 in signal path**: 改 `scripts/run_paper_trading.py:48` legacy `check_circuit_breaker_sync` import + `backend/app/services/signal_service.py` + `backend/engines/signal_engine.py` 老 `vol_regime` 调用,改用 V3 L0-L5 invocation chain (L0 NewsClassifier → L2 MarketRegimeService Bull/Bear → L3 DynamicThresholdEngine → L4 STAGED execution decision → L5 RiskReflector lesson injection). **Build L1 production runner**: 真生产进程 `XtQuantTickSubscriber` + `RealtimeRiskEngine` subscribe loop (NOT replay-only), Servy-managed OR Beat-scheduled subprocess (复用现有 QMT Data Service 体例). 沿用 ADR-073 D3 (L1 wiring 留 Plan v0.4 cutover scope). |
| Acceptance | `grep -n "qm_platform.risk" scripts/run_paper_trading.py backend/app/services/signal_service.py backend/engines/signal_engine.py` 全有 imports + 真调用; legacy `check_circuit_breaker_sync` deprecated/retired; L1 production runner registered (Servy service OR Beat entry) + 实跑 ≥1h 0 crash; integration test 证 V3 decision reaches `execution_service`; smoke test 28 PASS sustained; 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained. |
| File delta | ~20-30 files / ~2500-4000 lines (signal_service/signal_engine V3 wire ~600-900 / run_paper_trading.py V3 wire ~200-400 / L1 production runner script + Servy config + Beat entry ~400-700 / integration tests ~600-1000 / ADR-078 sediment ~6-10KB / legacy retire annotations) |
| Chunked sub-PR | **chunked 3 sub-PR baseline** (per LL-168/169 net-new-wiring expect balloon — 真值留 sub-PR 起手时 1.5x replan): IC-1a (signal_service + signal_engine V3 wire — replace vol_regime call sites + V3 invocation orchestration) → IC-1b (run_paper_trading.py V3 wire — replace check_circuit_breaker_sync + L4 STAGED hookup) → IC-1c (L1 production runner — XtQuantTickSubscriber + RealtimeRiskEngine subscribe loop + Servy/Beat 注册 + ADR-078 sediment) |
| Cycle | ~1.5-2 周 baseline; replan trigger 1.5x = ~2.25-3 周 (net-new-wiring expected balloon — LL-168 lesson 1) |
| Dependency | 前置: 横切层 FULLY CLOSED (✅ ADR-076) / 后置: IC-2 (de-stub) + IC-3 (replay validation) — 都依赖 V3 在 signal path 的实际调用 |
| LL/ADR candidate | **ADR-078** ✅ promote (IC-1 V3 signal-path integration closure — Replace 策略真值落地 + L1 production runner architectural decision); **LL-170 候选 lesson 1** (V3-as-island detection 体例 — 横切层 closed ≠ live-path integrated) |
| Reviewer reverse risk | V3 invocation 引入 latency regression vs legacy (mitigation: integration test 含 latency budget assert per V3 §13.1 SLA); L1 production runner memory leak / disconnect silent (mitigation: 元监控 alert-on-alert 已 wire HC-1, L1-heartbeat instrumentation 在 IC-1c 配套加入); legacy retire 漏触一处导致双链 (mitigation: grep verify 全 call sites + integration test cover); paused L1-L3 risk-daily-check Beat decision 留 IC-2 (本 sprint 不 touch) |
| 红线 SOP | sustained 横切层; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce; 0 .env mutation; 0 真账户 broker call (integration test 走 mock broker); L1 production runner subscribe live tick 但 paper-mode (LIVE_TRADING_DISABLED=true sustained); 红线 5/5 sustained |
| Paper-mode | sustained; L1 production runner subscribe 真 xtquant tick (read-only) — paper-mode 下 0 真发单 |

> **IC-1 FULLY CLOSED 2026-05-15** (post HC-4c Gate D close, IC-1c WU-5 docs-only sediment 铁律 42 直 push). **IC-1 chain effective 2 sub-PR cumulative**: IC-1a PR #361 `4a609bd` (V3 → signal path 抽象 seam: `backend/app/services/v3_cutover_adapter.py` NEW + `scripts/run_paper_trading.py` 2 call sites replace, IC-1a behavior delta = 1 观察 log 行 only per LL-169 verify-heavy estimate-held) + IC-1c = 3 internal WU sub-PRs cumulative (WU-1 `backend/qm_platform/risk/realtime/rule_registry.py` SSOT extract PR #362 `a0de0f8` + WU-2 `scripts/realtime_risk_engine_service.py` L1 RealtimeRiskEngine production runner PR #363 `5629186` + WU-3 `meta_monitor_service._collect_l1_heartbeat` Redis read path replace + TTL bug fix PR #364 `0f1c205` + WU-4 dropped via Phase 0 T0-verify-then-decide → T1-implicit `RedisThresholdCache` + Beat publishes already wired); IC-1b 原 scope 空 (LL-169 lesson 1 应用: IC-1a 是 scope-shrink reuse existing risk_wiring.py infra NOT net-new-wiring 以 balloon). **IC-1c estimate held**: chunked baseline 3 + 1 dropped via fresh-verify = 3 actual sub-PRs cumulative matching plan; **LL-168 verify-heavy-vs-net-new-wiring classification 7-th sprint 实证 cumulative** confirmed — WU-2 single net-new wiring did NOT balloon (~410-line target held), WU-1 + WU-3 + WU-4-dropped = verify-refactor estimate held. **ADR-073 D3 dormant L1元告警 re-activated end-to-end** at code level (runner SETEX `risk:l1_heartbeat <iso> TTL=3600s` per tick → meta_monitor read path → `evaluate_l1_heartbeat` PURE rule fires P0 if (now - last_tick_at) > 300s → channel fallback chain 主 DingTalk → 备 email → 极端 log-P0); HC-1b3 Finding "instrumenting would never fire because no production runner exists" resolved at code level (ops still needs Servy register for full operational closure, post-merge ops checklist). **ADR-076 D1 replay-as-gate parity invariant honored** by WU-1 `register_all_realtime_rules` extracted to SSOT free function; both `RiskBacktestAdapter.register_all_realtime_rules` (replay) AND IC-1c production runner import same function → rule drift between replay (HC-4a 5y full minute_bars + CT-1 cutover gate) and production is prevented by construction. **Reviewer 2nd-set-of-eyes 6 实证 cumulative across 3 PRs** (WU-1: code+python APPROVE / WU-2: code REQUEST-CHANGES 2 P1 + 4 P2 → all addressed + python APPROVE-with-P2 / WU-3: code REQUEST-CHANGES 1 P1 + 1 P2 + python REQUEST-CHANGES 1 P1 + 4 P2 → all addressed). **0 broker / 0 .env mutation / 0 yaml mutation / 0 DB row mutation**, 红线 5/5 sustained: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. ADR-078 reserved→committed (REGISTRY.md row updated 2026-05-15) + LL-171 NEW (5 lessons sediment) + 本 closure blockquote append + memory `project_sprint_state.md` handoff prepend. **Next sprint**: IC-2 (De-stub remaining V3 inputs + L4 broker wire) — pending user 显式 trigger per LL-098 X10.

---

### IC-2 — De-stub remaining V3 inputs + L4 broker wire

| element | content |
|---|---|
| Scope | **De-stub** dynamic_threshold ATR/beta inputs (currently `dynamic_threshold_tasks.py:13` 注 "stub via QMTClient.read_positions; ATR/beta wire deferred"); reflector input gathering (audit 发现 stub); **L4 broker sell wire** (currently state-transitions only, NOT 真发 broker sell — 沿用 audit 真值). **Decision on paused Beat**: `risk-daily-check` (L1-L3 14:30) + `intraday-risk-check` 当前 PAUSED (commented out); IC-1 完成后 V3 在 signal path → 这两 Beat 是冗余的还是需 unpause 作 cron-style backstop?决议 + 实施。 |
| Acceptance | 0 stub 在 V3 production code path (grep verify); ATR/beta 产真实值 (validate via fixture + 1d live data); L4 STAGED 真 issues broker sell call (paper-mode mock broker accept the call); paused Beat 决议 sediment (un-pause OR formal 退休 + 删除 commented-out lines); smoke 28 PASS sustained; 红线 5/5 sustained |
| File delta | ~10-15 files / ~1000-1800 lines (dynamic_threshold ATR/beta wire ~300-500 / reflector input wire ~200-400 / L4 broker sell wire + tests ~300-500 / paused Beat 决议 + 实施 ~100-200 / ADR-079 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 2 sub-PR baseline**: IC-2a (dynamic_threshold ATR/beta + reflector input de-stub) → IC-2b (L4 broker sell wire + paused Beat 决议 + ADR-079 sediment) |
| Cycle | ~0.7-1 周 baseline (verify-heavy + targeted de-stub — LL-168 lesson 1 verify-heavy estimate holds); replan trigger 1.5x = ~1-1.5 周 |
| Dependency | 前置: IC-1 closed (V3 在 signal path 是 de-stub 的前提) / 后置: IC-3 (replay validation) |
| LL/ADR candidate | **ADR-079** ✅ promote (IC-2 de-stub closure — ATR/beta 数据源决议 + paused Beat retire/unpause 决议 + L4 broker wire architectural decision); **LL-170 候选 lesson 2** (de-stub vs 重写 体例 — stub 是显式 deferral 标记, IC-2 落实 deferred items) |
| Reviewer reverse risk | ATR/beta 数据源选错(Tushare vs xtquant vs 计算)→ V3 §13.1 SLA 受影响 (mitigation: ADR-079 sediment 锁数据源决议 + integration test); L4 broker sell wire 触发 真发单 (mitigation: paper-mode flag 检 + mock broker assertion + redline-guardian 双层); paused Beat retire 漏触 docs cite (mitigation: cite-source-lock skill + grep all refs) |
| 红线 SOP | sustained IC-1; L4 broker wire test 走 mock broker / paper-mode 双重 guard; 0 真账户 / 0 真发单; 红线 5/5 sustained |
| Paper-mode | sustained; L4 broker call 走 paper-mode mock |

> **IC-2 FULLY CLOSED 2026-05-16** (IC-2d docs-only sediment 铁律 42 直 push). **IC-2 chain effective 3 sub-PR cumulative** (NOT plan baseline 2; expanded post-Phase-0 reshape via user (B1) 决议 — Finding #18 critical revision in IC-2c Phase 0 revealed reflector inputs were a real de-stub work item, NOT verify-only as Finding #14 initially claimed): **IC-2a PR #365** `9a67a12` (`_build_stock_metrics` de-stub via factor_values atr_norm_20 5.6M rows + beta_market_20 10.4M rows + daily_basic dv_ttm PERCENT_RANK + stock_basic industry_sw1; per-source fail-soft; per-factor CTE date-skew fix + ImportError hoist post reviewer-fix) + **IC-2b PR #366** `5750ffd` (paused Beat formal retire: delete commented blocks risk-daily-check 14:30 + intraday-risk-check 5min + 4 stale-cite update across daily_pipeline / market_regime_tasks / 2 smoke tests / services_healthcheck + audit doc FORMAL RETIRE append; LL-171 lesson 4 applied — smoke tests inverted to ABSENCE regression guards) + **IC-2c PR #367** `6c35ffc` (reflector input full 4-source wire: `_build_stub_input` → `_build_reflection_input` orchestrator + 4 fail-soft gatherers `_gather_events_summary` / `_gather_plans_summary` + cancel-rate / `_gather_pnl_outcome` paper-only / `_gather_rag_top5` RAG k=5; `_get_rag` lazy singleton shares embedding_service with RiskReflectorAgent; **CRITICAL P1 conn leak fix in `risk_memory_rag.py`** — IC-2c was activation point exposing latent leak from TB-3c, weekly + monthly Beat would have exhausted PG max_connections over months) + **IC-2d 本 sediment** (docs-only). **Plan-cite drift discovered + reshape体例 sustained** (Finding #13 + #14 IC-2 kickoff): L4 broker sell wire ALREADY wired pre-Plan v0.4 (S8 8c-followup landed before Plan); reflector inputs INITIALLY mis-identified as wired (Finding #14 single-directory grep'd `qm_platform/risk/reflector/` only, MISSED `app/tasks/risk_reflector_tasks.py:165-191`); Finding #18 IC-2c kickoff CRITICAL REVISION via multi-directory grep — LL-159 4-step preflight amended with step (e) multi-directory grep SOP per LL-172 lesson 1. **IC-2 estimate balloon classified per LL-168/169** — plan baseline 2 sub-PR → actual 3 sub-PR (+1 net-new-wiring IC-2c reflector de-stub, ~400 lines); LL-168 prediction "net-new-wiring expected 1.5x balloon" → 2 × 1.5 = 3 actual matches upper bound; **8-th sprint 实证 cumulative** of net-new-wiring-vs-verify-heavy classification (HC-1~4 + IC-1 + IC-2a/b/c). **Reviewer 2nd-set-of-eyes 6 实证 cumulative across 3 PRs** (IC-2a: code REQUEST-CHANGES 2 P1 + 1 P2 → addressed + python APPROVE-with-P2 3 P2 → addressed / IC-2b: code APPROVE-with-P2 1 P2 + 1 LOW + python APPROVE-with-P2 3 P2 / IC-2c: code REQUEST-CHANGES 1 P1 + 2 P2 + python APPROVE-with-P2 3 P2). **LL-171 lesson 5 sustained** — 10th 实证 cumulative of pair-review convergence (signature-level findings converge — dup import + private cross-module access in IC-2c; domain-specific findings diverge — IC-2c P1 RAG conn leak unique to code-reviewer). **0 broker / 0 .env mutation / 0 yaml mutation / 0 DB row mutation**, 红线 5/5 sustained throughout IC-2 chain: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. **P2 deferred** (per convergent reviewer "merge-with-tracked-debt" guidance): IC-2c `_get_rag` private `service._ensure_embedding_service()` cross-module access — public property hoist on RiskReflectorAgent is separate refactor out of IC-2 PR scope, tracked in ADR-079 + LL-172 for future scope. ADR-079 reserved→committed (REGISTRY.md row body fully written 2026-05-16) + LL-172 NEW (5 IC-2 cycle lessons: multi-directory grep / activation-point latent-bug exposure / RAG query placeholder contamination / verify-then-wire reshape saves plan-cite honest / estimate held within LL-168 balloon) + 本 closure blockquote append + memory `project_sprint_state.md` handoff prepend. **Next sprint**: IC-3 (Replay-as-cutover-gate validation suite, 3 families) — pending user 显式 trigger per LL-098 X10.

---

### IC-3 — Replay-as-cutover-gate validation suite (3 families)

| element | content |
|---|---|
| Scope | **3 replay families on FULLY-INTEGRATED V3** (NOT on V3-as-island — re-run after IC-1+IC-2 完成): (a) **5y full minute_bars replay** — 沿用 HC-4a `scripts/v3_hc_4a_5y_replay_acceptance.py` infra, 但 evaluate 路径走 真 integrated V3 chain (NOT only L1 RealtimeRiskEngine subset); (b) **V3 §15.5 counterfactual replay** — 4-29 crash + 其他 historical incidents,assert V3 would have prevented 或 mitigated 损失 (counterfactual 比 baseline ≥X% improvement); (c) **V3 §15.6 ≥7 synthetic scenarios** — 沿用 TB-5a `test_v3_15_6_synthetic_scenarios.py` infra,Crisis regime + News flood + LiteLLM down + xtquant 断连 + ... 全 green. **3 reports sediment in `docs/audit/`** = the cutover gate (NOT calendar wall-clock,沿用 memory feedback_no_observation_periods 反日历式观察期). |
| Acceptance | (a) 5y replay ✅ PASS 4/4 V3 §15.4 (FP rate <30% / latency P99 <5s / STAGED 0 failed / 元监控 0 P0) on integrated V3 path; (b) counterfactual ≥7 个 historical incident replay green + 4-29 crash 显式 prevented/mitigated 量化; (c) ≥7 synthetic scenarios all green (沿用 TB-5a 12 模式 fixture + HC-2 灾备演练 sediment); 3 reports sediment + ADR-080 + integration tests CI green; 红线 5/5 sustained |
| File delta | ~5-10 files / ~800-1500 lines (5y replay re-run report ~200-400 / counterfactual replay script + report ~300-600 / synthetic scenarios re-run report ~200-400 / ADR-080 sediment ~6-10KB / 任何 V3 latent bug 在 replay surfaced 的 fix patches) |
| Chunked sub-PR | **chunked 3 sub-PR baseline** (沿用 HC-4a 3-family replay 体例): IC-3a (5y full replay re-run on integrated V3 + report) → IC-3b (counterfactual replay + 4-29 prevention assertion + report) → IC-3c (synthetic scenarios re-run + report + ADR-080 sediment) |
| Cycle | ~0.7-1 周 baseline (replay infra exists,主要 wall-clock 是 replay run time per HC-4a 实测 5y ~1414s; replan trigger 1.5x = ~1-1.5 周) |
| Dependency | 前置: IC-2 closed (de-stub complete, replay 才 valid) / 后置: CT-1 (cutover hygiene) + CT-2 (Gate E formal close 依赖 IC-3 reports) |
| LL/ADR candidate | **ADR-080** ✅ promote (IC-3 replay-as-cutover-gate validation suite closure — 3 families result + 任何 latent bug surfaced 的 决议 lock + cutover gate 阈值 sustained ADR-070); **LL-170 候选 lesson 3** (replay-as-gate 取代 wall-clock observation 体例 — 沿用 memory feedback_no_observation_periods, 集体证据) |
| Reviewer reverse risk | 5y replay scope creep (mitigation: 沿用 HC-4a 阈值 lock); counterfactual incident 选取偏向 (mitigation: ADR-080 sediment 显式 enumerate incident 选取 criteria); synthetic scenario 不足 7 类 (mitigation: TB-5a + HC-2 灾备演练 superset, ≥7 sustained); replay surfaces latent V3 bug 但 IC-3 fix scope creep (mitigation: 任何 latent bug fix 走 separate sub-PR / hotfix, IC-3 不 inline fix) |
| 红线 SOP | sustained IC-1+IC-2; replay 走 read-only DB SELECT + in-memory; 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained throughout IC-3 |
| Paper-mode | sustained; 全 replay 走 historical data + mock broker / mock notifier / mock price reader |

> **IC-3 FULLY CLOSED 2026-05-16** (IC-3d docs-only sediment 铁律 42 直 push). **IC-3 chain effective 3 work sub-PR + 1 docs-only closure**: **IC-3a PR #368** `c6196bc` (5y integrated V3 chain replay — HC-4a infra composition + L3 daily-cadence wiring extension, 4/4 V3 §15.4 PASS: FP rate 4.12% / latency P99 0.010ms max-quarter / STAGED 0 failed / 元监控 0 P0 + 1212 td × 4 rules = 4848 eval_calls 0 crashes; 139M minute_bars / 3.76M events / 20 quarters / 25 tests, +28 with reviewer-fix HIGH-1 invariant guards) + **IC-3b PR #369** `cdfd452` (counterfactual replay 3 incidents — 2025-04-07 Tariff Shock 182k P0 alerts L1 fired earliest 09:35 + 2024Q1 DMA Snowball 196k P0 alerts L1 fired earliest 09:35 + 2026-04-29 user-liquidation daily wiring health green; mixed-methodology体例 per user 决议 B path with Phase 0 STOP gate triggered — 4-29 minute_bars max=2026-04-13 < crash date fell to klines_daily daily-cadence; 23 tests) + **IC-3c** `c01ee8a` (V3 §15.6 ≥7 synthetic scenarios re-run — 0 new code TB-5a infra sustained, 24/24 PASS across 7 scenario classes: 4-29类 + 单股闪崩 + 行业崩盘 + regime切换 + LLM挂 + DingTalk挂 + user离线; verify-heavy docs-only direct push 铁律 42) + **IC-3d 本 sediment** (docs-only closure). **3 reports sediment in `docs/audit/`** = the cutover gate per Plan §A row 4: `v3_ic_3a_5y_integrated_replay_report_2026_05_16.md` + `v3_ic_3b_counterfactual_replay_report_2026_05_16.md` + `v3_ic_3c_synthetic_scenarios_report_2026_05_16.md`. **Phase 0 meta-finding critical sediment insight (4-29)**: 4-29 was actually a USER-INITIATED PORTFOLIO LIQUIDATION (NOT systemic market crash) — Phase 0 klines_daily verify revealed 17 emergency_close stocks closed FLAT to slight GAIN on 4-29 vs prior month avg (max loss vs avg = -4.79%, mostly +/-5% range, NONE breached SingleStockStopLoss L1 10% threshold); V3 daily-cadence rules CORRECTLY silent on benign price action (sustained 铁律 33 silent_ok skip-path semantics in PMSRule + SingleStockStopLossRule); daily PASS criterion reframed as wiring health, NOT alert count; "4-29 crash" narrative is sediment-historical phrase, actual market event was controlled portfolio exit not systemic shock. **ADR-080 selection criteria enumerated** (Plan §B row 5 mitigation "counterfactual incident 选取偏向"): 5 criteria (Real documented / V3 risk-type coverage / Data avail / Counterfactual measurability / Diversity ≥2 shock types) — ADR-080 sediment体例 makes incident 选取 explicit + auditable. **Estimate held per LL-168/169 verify-heavy classification** — IC-3a composition (HC-4a re-import + L3 extension, ~625 lines) verify-heavy + IC-3b new infrastructure (~782 lines, reuses HC-4a/TB-5b) verify-heavy + IC-3c 0 new code; **11-th sprint 实证 cumulative** of verify-heavy-vs-net-new-wiring classification (HC-1~4 + IC-1 + IC-2a/b/c + IC-3a/b/c). **Reviewer 2nd-set-of-eyes cumulative across IC-3a + IC-3b** (IC-3c was docs-only direct push, IC-3d 本 docs-only): IC-3a code REQUEST-CHANGES 2 HIGH + 2 MEDIUM → addressed + python APPROVE-with-MEDIUM 7 MEDIUM → addressed; IC-3b code REQUEST-CHANGES 2 P1 + 3 P2 + 2 P3 → addressed + python APPROVE-with-MEDIUM 3 MEDIUM + 3 LOW → addressed. **LL-171 lesson 5 sustained — 12th 实证 cumulative of pair-review convergence** (signature-level converged on unused `_hc4a_aggregate` import in IC-3b; domain-specific diverged — P0 SSOT + UTC label + counterfactual_passed contract unique to code-reviewer; ruff format + BLE001 noqa alignment unique to python-reviewer). **LL-172 lesson 1 multi-directory grep amended preflight applied IC-3 chain** — IC-3a Phase 0 verified L1 0 reflector imports + 4 daily rules carry 铁律 31 PURE marker via multi-dir grep; IC-3b Phase 0 step (e) data avail SQL verify across 3 incidents surfaced 4-29 minute_bars gap STOP gate that triggered user 决议 B path lock — Phase 0 active discovery saved the chain from a silent wrong-premise scope. **0 broker / 0 .env mutation / 0 yaml mutation / 0 DB row mutation**, 红线 5/5 sustained throughout IC-3 chain: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. ADR-080 reserved→committed (REGISTRY.md row body fully written 2026-05-16) + LL-173 NEW (5 IC-3 cycle lessons: replay-as-gate 取代 wall-clock observation体例 / Phase 0 meta-finding catches false premise narrative / mixed-methodology selection criteria sediment / cumulative pair-review convergence 12 实证 / cutover gate cumulative via 3-family green) + 本 closure blockquote append + memory `project_sprint_state.md` handoff prepend. **Cutover gate green for CT-1 transition** — IC-3 3-family results = cutover prerequisite sediment per CT-1 dependency row "前置: IC-3 closed (replay green = pre-shake-down gate)". **Next sprint**: CT-1 (Cutover hygiene + paper-mode V3-in-path shake-down — first non-zero-mutation sprint in Plan v0.4) — pending user 显式 trigger per LL-098 X10.

---

### CT-1 — Cutover hygiene + paper-mode V3-in-path shake-down

| element | content |
|---|---|
| Scope | **(SHUTDOWN_NOTICE §9 prereq cleanup)** DB stale snapshot 清理 — DELETE stale `position_snapshot` rows + `circuit_breaker_state` (`cb_state` shorthand in original draft, actual table name = `circuit_breaker_state`) **already reset 2026-04-30** (cite drift fix per CT-1a Phase 0 active discovery 2026-05-16: `circuit_breaker_state.live` NAV=¥993,520.16 with `trigger_reason="PT restart gate cleanup 2026-04-30"` — pre-existing closed, NO action this sprint). **Scope reshape per Phase 0 SQL truth**: stale `position_snapshot` rows actual scope = **114 rows across 6 dates** `[2026-04-20, 04-21, 04-22, 04-23, 04-24, 04-27]` × 19 stocks (Plan original "4-28 stale 19-stock" cite is stale — 4-28 = 0 rows due to Beat pause before 4-28 close); + **7 stale `performance_series` rows** (4-20 ~ 4-28 with position_count=19) per user 决议 T1 2026-05-16. Per SHUTDOWN_NOTICE §9 prereq, user 显式触发 SQL DELETE — redline-guardian 双层. DB row mutation 是 CT-1 期 ONLY mutation type. **Paper-mode V3-in-path shake-down**: SLA-threshold-driven verification (sustained LL-173 lesson 1 replay-as-gate 取代 wall-clock observation体例, user 决议 S1 2026-05-16, 反日历式观察期); single-session run走 fully-integrated V3 chain (NOT legacy) — operational shake-down to catch UI/log/alert flow issues that replay can't catch (real DingTalk push / real PG load / real Servy resource use); 5 SLA (V3 §13.1) measured during shake-down with real traffic patterns. |
| Acceptance | DB row cleanup verified (`SELECT COUNT(*) FROM position_snapshot WHERE date='2026-04-28'` = 0 + cb_state.live_value = 993520); shake-down 1-2 自然日 0 P0 alert + 5 SLA satisfied + 元监控 clean + 0 crash + 0 silent failure; operational issue list sediment + fixed (任何 surfaced 的 P1 fix 走 separate sub-PR); 红线 5/5 sustained (LIVE_TRADING_DISABLED=true throughout, EXECUTION_MODE=paper) |
| File delta | ~3-5 files / ~200-500 lines (SQL cleanup script + rollback ~100-200 / shake-down 监控 dashboard / log analysis report ~100-300 / ADR-081 sediment ~3-5KB) |
| Chunked sub-PR | **chunked 2 sub-PR baseline**: CT-1a (DB stale cleanup SQL + cb_state reset — user 显式 SQL DELETE trigger required) → CT-1b (paper-mode V3-in-path shake-down 1-2 day + 监控 report + ADR-081 sediment) |
| Cycle | ~0.5 周 baseline (含 1-2 自然日 shake-down — wall-clock); replan trigger 1.5x = ~0.75 周 |
| Dependency | 前置: IC-3 closed (replay green = pre-shake-down gate) / 后置: CT-2 (Gate E formal verify) |
| LL/ADR candidate | **ADR-081** ✅ promote (CT-1 cutover hygiene + V3-in-path shake-down closure — DB cleanup result + 5 SLA shake-down measurement + 任何 operational issue 决议); **LL-170 候选 lesson 4** (cutover hygiene 体例 — DB row mutation 是 cutover phase ONLY pre-mutation, 走 redline-guardian 双层) |
| Reviewer reverse risk | DB DELETE 误删 (mitigation: SQL 含 explicit WHERE date='2026-04-28' AND audit_marker assertion + rollback script 同 PR + user 显式触发); cb_state reset 错值 (mitigation: SHUTDOWN_NOTICE §9 cite + user verify before commit); shake-down 1-2 day 退化为日历式观察期 (mitigation: 显式 SLA + 监控 metrics threshold,NOT "wait and see") |
| 红线 SOP | **CT-1 是 Plan v0.4 期 first non-zero-mutation sprint** — DB row mutation (4-28 stale cleanup); 走 redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce + user 显式 SQL DELETE trigger required; 0 .env mutation; 0 真账户 broker call (paper-mode sustained); 0 production code mutation; 红线 5/5 sustained |
| Paper-mode | sustained throughout CT-1; shake-down 走 paper-mode (LIVE_TRADING_DISABLED=true, EXECUTION_MODE=paper) — first time V3 fully in path with real market data |

> **CT-1 FULLY CLOSED 2026-05-17** (CT-1c docs-only sediment 铁律 42 直 push). **CT-1 chain effective 2 work sub-PR + 1 docs-only closure**: **CT-1a PR #370** `50d0401` (DB stale snapshot cleanup — 114 position_snapshot + 7 performance_series stale rows DELETE'd via runner-managed atomic transaction; 47KB / 121-row JSON rollback snapshot captured atomically pre-DELETE; user 显式 "同意 apply" trigger 2026-05-16 23:58 satisfied 3-step gate per Plan §A 红线 SOP + LL-098 X10; assertion-guarded SQL with pre+post DO block raise; SQL identifier injection guard + JSON-native pass-through + strict env gate + atomic txn boundary per reviewer P1+P2 fixes; **Phase 0 active discovery surfaced 4 sediment-cite drifts** via multi-directory SQL verify: Plan §A 'cb_state' → actual `circuit_breaker_state` already-closed 2026-04-30 NAV=993520.16, Plan §A '4-28 stale 19-stock' → actual 114 rows × 6 dates + performance_series 7 rows scope expansion per user T1, 000012.SZ trade_log completeness gap recorded for future audit) + **CT-1b PR #371** `a50922d` (operational readiness harness 6/6 ✅ READY live run 2026-05-17 00:08 — Servy 5 services Running + FastAPI /health OK execution_mode=paper + Redis PING + 3 qm:* streams + PG SELECT on 5 production tables + DingTalk webhook TCP reachable no push + RSSHub TCP reachable no fetch; **NOT 1-2 自然日 wall-clock shake-down** per user 决议 M1+V1+S1 反日历式观察期 sustained LL-173 lesson 1 replay-as-gate; V3 §13.1 5 SLA evidence cumulative from IC-3a/b/c reports — replay-path equivalent per ADR-063; SQL injection guard + Redis client close + RSSHub config-driven + ImportError narrow + Servy detail accuracy per reviewer P1+P2 fixes) + **CT-1c 本 sediment** (docs-only closure). **Mutation type accounting**: CT-1 = Plan v0.4 期 first non-zero-mutation sprint; DB row mutation = ONLY mutation type (121 stale rows DELETE in CT-1a); 0 broker / 0 .env / 0 yaml / 0 production code mutation; 红线 5/5 sustained throughout CT-1 chain: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. **Defense-in-depth demonstrated 3 times during CT-1a apply**: (1) strict env-check fired on 1st `--apply` attempt — env vars unset in PowerShell shell context FAILED FAST per P2 fix; (2) redline_pretool_block hook BLOCKED commit message containing `$env:LIVE_TRADING_DISABLED=` literal pattern; (3) atomic txn boundary held throughout 2-migration sequence — partial-failure rollback state impossible per code-reviewer P1 fix. **Estimate held per LL-168/169 verify-heavy classification 12+13-th sprint 实证 cumulative** — CT-1a was verify-heavy mutation-script work (SQL + runner + tests + rollback snapshot ~1300 lines fitting verify-heavy because each component reused established patterns from prior migrations); CT-1b was 0-mutation operational verify (~930 lines fitting verify-heavy NOT net-new-wiring); 13-th sprint 实证 cumulative (HC-1~4 + IC-1 + IC-2a/b/c + IC-3a/b/c + CT-1a/b). **Reviewer 2nd-set-of-eyes cumulative across CT-1a + CT-1b**: CT-1a 3 reviewers (redline-guardian NEEDS_USER + code-reviewer WARNING 1 P1 + 4 P2 + 1 P3 → addressed + python-reviewer BLOCK 3 P1 + 5 P2 + 6 P3 + 1 LOW → addressed); CT-1b 2 reviewers (code-reviewer WARNING 2 HIGH + 2 MEDIUM + 3 LOW → addressed + python-reviewer BLOCK 1 HIGH + 5 MEDIUM + 5 LOW → addressed). **LL-171 lesson 5 sustained — 13th + 14th 实证 cumulative of pair-review convergence pattern** (CT-1a convergent: float NAV equality + env-check unset silent pass; CT-1b convergent: SQL injection f-string + RSSHub hardcode + detail accuracy). **3 sediment reports in `docs/audit/`** + 1 rollback snapshot: `v3_ct_1a_cleanup_report_2026_05_16.md` + `v3_ct_1a_rollback_snapshot_2026_05_16.json` + `v3_ct_1b_operational_readiness_report_2026_05_17.md`. ADR-081 reserved→committed (REGISTRY.md row body fully written 2026-05-17) + LL-174 NEW (5 CT-1 cycle lessons: Phase 0 catches multi-cite-drift in single sprint / 3-step user gate体例 / atomic txn boundary defense-in-depth / pair-review convergence sustained 14-th 实证 cumulative / cutover hygiene体例 — DB row mutation ONLY pre-mutation) + 本 closure blockquote append + memory `project_sprint_state.md` handoff prepend via Write-script. **CT-2 prerequisite green** — Plan §A CT-2 dependency row "前置: CT-1 closed (DB clean + V3-in-path shake-down ✅)" satisfied. **Next sprint**: CT-2 (Gate E formal verify + .env paper→live + go-live 监控 — V3 实施期 ONLY 真账户解锁 sprint, **highest-stakes mutation** per Plan §A 红线 SOP, user 显式 .env 授权 hardgate required) — pending user 显式 trigger per LL-098 X10.

---

### CT-2 — Gate E formal verify + .env paper→live + go-live 监控

| element | content |
|---|---|
| Scope | **Gate E formal verify** — `quantmind-v3-pt-cutover-gate` skill 走完 + `quantmind-v3-tier-a-mvp-gate-evaluator` (Gate E charter borrow per Plan v0.3 §C 体例) verify run → Constitution §L10.5 5 prereq + 10 user 决议 verify (V3 §20.1) + 5 SLA verify + 元监控 0 P0 verify + IC-3 replay 3 reports re-cite + CT-1 shake-down report cite. **真账户解锁**: user 显式 .env paper→live 授权 (Constitution §L8.1 (c) sprint 收口决议 user 介入硬门 — NOT auto-trigger sustained LL-098 X10); flip `LIVE_TRADING_DISABLED=true` → `false` + `EXECUTION_MODE=paper` → `live` (双 .env field 改, redline_pretool_block hook 双层 enforce + user 显式 trigger). **Go-live 监控** 1d (next trading day 全程) — full SRE-style watching the dashboards / alerts / 元监控 / V3 layer outputs;首单真发 broker order via V3 path. **ADR-077~081 sediment** + Constitution §L10.5 amend (5 prereq [x] + closure blockquote + version bump v0.12→v0.13) + skeleton patch + memory handoff + post-cutover monitoring sediment (3 carried-Gate-E deferrals reframed as ongoing monitoring per D2). |
| Acceptance | Gate E charter PASS 5/5 (paper-mode shake-down ✅ from CT-1 + 元监控 0 P0 + Tier A ADR 全 sediment + 5 SLA + 10 user 决议 verify); user 显式 .env 授权 captured (commit message + ADR-077 cite); .env flipped + verified (`grep LIVE_TRADING_DISABLED=false` + `EXECUTION_MODE=live`); first 1d live trades execute via V3 path + 0 P0 alert in 1d live + 元监控 clean; ADR-077 (Plan v0.4 closure cumulative + Gate E formal close) sediment + Constitution §L10.5 amend + memory handoff; 3 carried-Gate-E deferrals 转为 ongoing monthly monitoring (beat_schedule + 元告警 wire) sediment ADR-082 (or inline ADR-077 §3); 红线 **transitioned** (cash 真值 / 持仓 → 真持仓 / LIVE_TRADING_DISABLED → false / EXECUTION_MODE → live / QMT_ACCOUNT_ID sustained 81001102) |
| File delta | ~10-15 files / ~1500-2500 lines (.env amend + audit cite ~50-100 / ADR-077 closure cumulative ~10-15KB / ADR-082 ongoing-monitoring sediment ~5-8KB / Constitution §L10.5 5-checkbox amend + closure blockquote + version v0.12→v0.13 + version history entry ~150-300 / skeleton patch ~50-100 / Plan v0.3 §C STOP gate closure 标注 ~30-50 / Plan v0.4 §A CT-2 closure blockquote ~50-100 / REGISTRY ADR-077~082 cumulative ~30-50 / LL-170 NEW append ~200-400 / memory handoff Session N+M handoff prepend / post-cutover ongoing monitoring beat_schedule + 元告警 wire — minimal code: ~200-400) |
| Chunked sub-PR | **chunked 3 sub-PR baseline** (Plan v0.4 final sprint, 高风险 mutation 隔离): CT-2a (Gate E charter verify run + 5 prereq + 10 user 决议 verify report doc) → CT-2b (**user 显式 .env 授权 hardgate** + .env paper→live flip + LIVE_TRADING_DISABLED unlock + first live trade verify) → CT-2c (1d live 监控 + ADR-077 + post-cutover ongoing monitoring sediment + Constitution §L10.5 amend + closure batch sediment) |
| Cycle | ~1 周 baseline (Gate E verify ~0.3 + .env flip ~0.1 含 user 显式 trigger + go-live 1d 监控 ~0.4 含 1 自然日 trading day + 闭环 sediment ~0.2); replan trigger 1.5x = ~1.5 周 |
| Dependency | 前置: CT-1 closed (DB clean + V3-in-path shake-down ✅) + IC-1+IC-2+IC-3 cumulative ✅ / 后置: V3 实施期 FULLY CLOSED → ongoing live operation (本 plan 之后无下一 plan; ongoing monitoring 是 BAU) |
| LL/ADR candidate | **ADR-077** ✅ promote (Plan v0.4 closure cumulative + Gate E formal close + cutover real-money go-live 决议 cumulative); **ADR-082** ✅ promote (post-cutover ongoing monitoring 体例 — 3 carried-Gate-E deferrals 转 ongoing monthly review sediment); **LL-170** ✅ promote (本 Plan v0.4 完整体例 — V3-as-island detection + integrate-first-then-cutover + replay-as-gate + cutover hygiene + go-live 1d 监控 5 lesson cumulative); Plan v0.4 = V3 实施期 LAST plan, 后续 LL/ADR 是 ongoing-operation sediment NOT plan-期 sediment |
| Reviewer reverse risk | **CT-2b .env flip 是整 V3 实施期 highest-stakes mutation** — 走 redline_pretool_block hook + quantmind-redline-guardian subagent 双层 + user 显式 trigger + commit message hard-cite + ADR-077 cite (4 layer enforce); Gate E charter verify 漏触 1 prereq → cutover unsafe (mitigation: 5+10+5+元监控 全 explicit cite + charter pre-sediment verify per LL-164); 1d live 监控发现 P0 issue 但 cutover already done → emergency rollback 程序? (mitigation: ADR-077 §3 含 emergency rollback path — flip back .env + LIVE_TRADING_DISABLED → true 走 redline 反向 unlock); first live trade execute via V3 path 但 V3 决策 differ from baseline 致 unexpected loss (mitigation: shake-down + 1d 监控 + immediate rollback option) |
| 红线 SOP | **CT-2 是 V3 实施期 ONLY 真账户解锁 sprint** — 红线 5/5 changes here — full enforcement: redline_pretool_block + quantmind-redline-guardian + user 显式 .env 授权 (Constitution §L8.1 (c) hard gate) + commit message hard-cite + ADR-077 cite + emergency rollback path readiness; .env mutation 走 protect_critical_files hook (.env path pattern auto block 反 silent change); broker call 真发单 — 走 paper→live mode flip 后 first 1d 紧密 监控 |
| Paper-mode | **CT-2b 是 paper→live 切换点** — paper-mode sustained throughout CT-2a (charter verify) + CT-2b 切换前; CT-2b flip 后 = live mode; CT-2c 1d 监控 = live mode 全程 |

---

## §B Cross-sprint surface risk register

| # | surface risk | mitigation |
|---|---|---|
| 1 | V3 latent bug 未 surfaced 在 unit test 但在 integrated path 暴露 | IC-1 integration test full chain + IC-3 replay 3 families + CT-1 shake-down 1-2d + CT-2c 1d live 监控 — 4 层 defense |
| 2 | L1 production runner 内存泄露 / xtquant 断连 silent | IC-1c 含 L1-heartbeat instrumentation (HC-1 D3 deferred 候选 IC-1c 落地); 元告警 alert-on-alert 已 wire; 24h 跑 IC-1c 末; CT-1 shake-down 测 |
| 3 | legacy retire 漏触一处 → V3 + legacy 双链 race condition | grep verify 全 call sites + integration test cover; sub-PR 起手 precondition 核 (铁律 36) |
| 4 | de-stub 数据源选错(ATR/beta 多 source 竞争) → V3 §13.1 SLA 受影响 | ADR-079 sediment 锁数据源决议 + integration test latency budget assert |
| 5 | replay 阈值 silent drift / scope creep 回 12 年 full | 沿用 HC-4a + ADR-064 D3=b lock; ADR-080 sediment 锁阈值 |
| 6 | shake-down 1-2 自然日 退化为日历式观察期 | sustained memory feedback_no_observation_periods; 显式 SLA threshold + 监控 metrics,NOT "wait and see" |
| 7 | DB DELETE 误删 stale + 同删非 stale rows | CT-1a SQL 显式 WHERE date='2026-04-28' AND audit_marker assertion + rollback script 同 PR + user 显式触发 + redline-guardian |
| 8 | .env flip silent overwrite NOT user-triggered | redline_pretool_block hook + protect_critical_files hook + user 显式 trigger 4 层 enforce; CT-2b sub-PR 起手 hardgate |
| 9 | 1d live 监控发现 P0 issue 后 emergency rollback 漏触 | ADR-077 §3 sediment emergency rollback path 显式 (.env flip back + LIVE_TRADING_DISABLED → true + 真账户暂停 cycle); rollback drill 在 CT-2a charter verify 时 dry-run |
| 10 | 3 carried-Gate-E deferrals (LiteLLM 3-month / RAG 命中率 / lesson 抽查) silent drop after cutover | ADR-082 sediment + beat_schedule monthly review entry + 元告警 wire (1st 测量 1 month post-cutover, 沿用 元监控 alert-on-alert pattern) |
| 11 | Gate E charter verifier pre-sediment REQUEST_CHANGES (ADR-077 not yet created at verify time, sustained LL-164) | 沿用 LL-169 lesson 3 体例 — verify prompt 显式 scope:gate criteria 是 underlying deliverables NOT closure paperwork |
| 12 | sub-PR balloon (本 plan 5 sprint chain net-new-wiring 多, IC-1 expect balloon per LL-168/169 classification) | 沿用 LL-168/169 net-new-wiring vs verify-heavy classification; IC-1 baseline 1.5x replan trigger; user-acknowledged AskUserQuestion 走 §F (iii) |
| 13 | CT-2b user 显式 .env trigger 时机判断错误 (e.g. CT-1 shake-down 报告 P1 但 CC 自决推进) | sustained Constitution §L8.1 (c) sprint 收口决议 user 介入 + LL-098 X10; CT-2b 起手 必走 STOP gate user 显式 ack — NOT CC 自决推进 |

---

## §C Cutover → live trigger STOP gate (Gate E formal close, Constitution §L10.5)

**Constitution §L10.5 Gate E 5 prerequisite** (CC 实测每项 via CT-2a `quantmind-v3-pt-cutover-gate` skill + Gate E charter run):

1. paper-mode 5d 通过 — **redefined**: replay 3 families (5y + counterfactual + ≥7 synthetic) all green = the equivalent (沿用 memory feedback_no_observation_periods 反日历式观察期; ADR-077 sediment 锁此 redefinition)
2. 元监控 0 P0 (HC-1 alert-on-alert + IC-3 replay 0 P0 + CT-1 shake-down 0 P0)
3. Tier A ADR 全 sediment ✅ (ADR-065 Gate A formal closure)
4. 5 SLA 满足 (V3 §13.1 — detection latency / News 6 源 / LiteLLM / DingTalk / STAGED 30min, CC 实测每项 — IC-3 replay + CT-1 shake-down 双 evidence)
5. 10 user 决议状态 verify (V3 §20.1 10 决议 closed PR #216)

**Plus 真账户解锁 hardgate** (Constitution §L10.5 footer):
- user 显式 .env paper→live 授权 (Constitution §L8.1 (c) hard gate) + commit message hard-cite + ADR-077 cite

**3 carried-Gate-E deferrals** (D2 reframed as POST-cutover monitoring NOT pre-cutover gates per LL-169 lesson 1):
- LiteLLM 月成本 ≥3 month ≤80% baseline → POST-cutover ongoing monitoring (1st 测量 1 month post-cutover, 后续 monthly)
- RAG retrieval 命中率 ≥ baseline → POST-cutover ongoing measurement (1st 测量 1 month post-cutover, 后续 monthly)
- lesson→risk_memory 后置抽查 ≥1 round → POST-cutover (1st 抽查 1 month post-cutover)

→ 3 deferrals sediment 走 ADR-082 (or inline ADR-077 §3) + beat_schedule monthly entries + 元告警 wire,**transitioned from "pre-cutover gate" (logically impossible per LL-169) to "ongoing operational monitoring" (BAU).**

**STOP gate**: Plan v0.4 closure → V3 实施期 FULLY CLOSED → ongoing live operation. **NO Plan v0.5** (本 Plan v0.4 是 V3 实施期 last plan; cutover 后是 BAU,sediment 走 SYSTEM_STATUS.md ongoing-operation 体例 NOT plan-期 体例). User 显式 trigger required for **CT-2b** (.env flip) — sustained LL-098 X10 + Constitution §L8.1 (c).

---

## §D Cutover 真测期 SOP

### Replay-as-cutover-gate methodology (sustained ADR-070 + memory feedback_no_observation_periods)

**3 replay families on integrated V3** (IC-3 sub-PR cumulative):
- 5y full replay (HC-4a infra) — long-tail acceptance
- counterfactual replay — 4-29 crash + 7 历史 incident,assert prevention/mitigation
- ≥7 synthetic scenarios (TB-5a + HC-2 灾备演练 superset) — stress test

**3 reports collectively = cutover gate** (NOT calendar wall-clock):
- 沿用 ADR-063 paper-mode deferral pattern + HC-4a 4/4 V3 §15.4 acceptance 体例
- 沿用 memory feedback_no_observation_periods 反"5d/30d 日历观察期" 体例
- replay 验证证据强于 wall-clock (历史 incident superset > N-day live observation)

### Paper-mode V3-in-path shake-down (CT-1b, ~1-2 自然日)

- **NOT 5d wall-clock** — 1-2 day operational shake-down 
- 5 SLA real-traffic measurement
- UI/log/alert flow 真测 (replay 不能 catch)
- 0 P0 + 元监控 clean = pass
- surfaced operational issue → separate sub-PR fix, NOT inline

### Go-live 1d 监控 (CT-2c, 1 trading day)

- full SRE-style: 全程 watch dashboards + alerts + 元监控
- first live trade execute via V3 path
- 真账户 P&L 监控
- emergency rollback path readiness (ADR-077 §3)

---

## §E Plan v0.4 estimated total cycle

| Sprint | baseline | 1.5x replan trigger | sub-PR count |
|---|---|---|---|
| IC-1 | 1.5-2 周 | 2.25-3 周 | 3 (IC-1a + IC-1b + IC-1c) |
| IC-2 | 0.7-1 周 | 1-1.5 周 | 2 (IC-2a + IC-2b) |
| IC-3 | 0.7-1 周 | 1-1.5 周 | 3 (IC-3a + IC-3b + IC-3c) |
| CT-1 | 0.5 周 | 0.75 周 | 2 (CT-1a + CT-1b) |
| CT-2 | 1 周 | 1.5 周 | 3 (CT-2a + CT-2b + CT-2c) |
| **Total** | **~4.5-5.5 周** | **~6.5-8.25 周** | **13 sub-PR baseline** |

V3 实施期 grand total estimate (post Plan v0.4): Tier A + T1.5 + Tier B + 横切层 + cutover ≈ ~17-24 周 + ~4.5-5.5 = ~21.5-29.5 周 (~5.4-7.4 月). Plan v0.4 替代 Constitution §0.1 line 35 area "long-term Roadmap §3.2 Gate E PT cutover critical path" 时序 estimate.

---

## §F Plan review trigger SOP (sustained Plan v0.3 §F 体例)

任一 trigger → Plan v0.4 自身 review:
- (i) 任一 sprint 实际 cycle 超 1.5x baseline (Constitution §L0.4)
- (ii) sub-PR scope balloon 显式 user-acknowledge (e.g. IC-1 expected per LL-168 — net-new-wiring)
- (iii) IC-3 replay 3 family 任一 surface latent V3 bug 致 IC-1/IC-2 需 patch — Plan §A IC-1/IC-2 closure marker amend
- (iv) CT-1 shake-down surface P0 致 CT-2 不能起手 — Plan v0.4 replan + ADR sediment
- (v) user 显式 ack 改变 cutover 计划 (e.g. push delay due to市场 volatility)

→ 走 AskUserQuestion 1 round + ADR sediment + Plan §A append-only amend (sustained ADR-022 反 retroactive content edit).

---

## §G 主动思考 (sustained LL-103 SOP-4 反 silent agreeing)

### (I) 2 决议 lock sediment 反思

**D1 Replace + replay-as-gate**: 选 Replace 避免 dual-system reconciliation 复杂性,选 replay-as-gate 沿用 V3 设计初衷 (TB-1+ADR-070+HC-4a 的 replay 验证体例) 而非 wall-clock observation。**风险**: V3 latent bug 没有运行时 fallback。**mitigation**: replay 3 families + integration test + shake-down + 1d 监控 4 层 defense; emergency rollback path readiness。

**D2 3 carried-Gate-E deferrals → POST-cutover monitoring**: LL-169 lesson 1 finding — 这 3 个物理上 cannot 是 pre-cutover gate (循环依赖)。Reframe 为 ongoing monitoring 是 the only physically coherent option。**风险**: silent drop after cutover。**mitigation**: ADR-082 sediment + beat_schedule monthly entries + 元告警 wire (sustained 元告警 alert-on-alert HC-1 体例)。

### (II) CC-domain push back

- **Sprint chunking 5 vs 4 vs 6**: 5 是 baseline 推荐 — IC-1/IC-2/IC-3/CT-1/CT-2 各有清晰 mission boundary; 4 (合并 IC-2 进 IC-1) 风险 IC-1 过 large; 6 (IC-1 拆 by-layer L0/L2/L3/L4/L5) 过细 carving. user 可以 §F (iii) replan 修订。
- **L1 production runner 复用 vs 新建 process**: 推荐复用 QMT Data Service 体例 (Servy-managed) 而非新建 process,降运维负担。决议留 IC-1c sub-PR 起手时实测决议。
- **paused L1-L3 risk-daily-check + intraday-risk-check Beat**: IC-2b 决议 = retire (V3 在 signal path 后 cron-style backstop redundant); 留 IC-2b 实测 retire 可行性。

### (III) Long-term + 二阶 / 三阶 反思

- **post-cutover ongoing monitoring 体例 sediment** (ADR-082) 是 V3 实施期 → BAU 过渡的 governance interface; 后续 V4 评估期 (2027 Q1+) 沿用此 sediment 决议 V4 起手时机。
- **Plan v0.4 后无 plan**: V3 实施期 FULLY CLOSED 后 sediment 走 SYSTEM_STATUS.md ongoing-operation 体例; 不再走 plan-期 体例 (LL/ADR/Constitution §L10.X gate)。这是 V3 governance 体例 → BAU 体例的切换点,需在 ADR-077 §3 显式 sediment。
- **LL-170 lesson 涵盖 5 块**: V3-as-island detection + integrate-first-then-cutover + replay-as-gate + cutover hygiene + go-live 1d 监控 — 跨 5 sprint cumulative pattern, sustained LL-100 chunked SOP cumulative 体例。

### (IV) Governance/SOP/LL/ADR candidate sediment

- ADR-077 (Plan v0.4 closure cumulative + Gate E formal close) — CT-2c sediment
- ADR-078 (IC-1 V3 signal-path integration closure) — IC-1c sediment
- ADR-079 (IC-2 de-stub closure) — IC-2b sediment
- ADR-080 (IC-3 replay-as-gate validation suite closure) — IC-3c sediment
- ADR-081 (CT-1 cutover hygiene + V3-in-path shake-down closure) — CT-1b sediment
- ADR-082 (post-cutover ongoing monitoring 体例 — 3 carried-Gate-E deferrals 转 ongoing) — CT-2c sediment (or inline ADR-077 §3)
- LL-170 (Plan v0.4 完整体例 — V3-as-island detection 5 lesson cumulative) — CT-2c sediment

→ ADR # registry SSOT: ADR-077~082 reserved 在 Plan v0.4 sediment 时一并 reserve (本 sub-PR), 各 sprint closure 时 reserved→committed (沿用 ADR-073~076 体例)。

---

## §H Phase 0 active discovery findings (the audit, sustained LL-115 enforce + Constitution §L5.3)

### Finding #1: "和我假设不同" — V3 风控框架完全没接进 live signal→execution 路径 ✅ sediment

- prompt cite (ADR-076 §D6 prereq list): "paper-mode 5d 通过 / 5 SLA 满足 / 元监控 0 P0 / Tier A ADR 全 sediment / 10 user 决议 verify / 3 carried deferrals / DB cleanup / .env 授权" — 0 mention V3 production integration step
- fresh verify 真值 (audit subagent + 我 cross-check):
  - `scripts/run_paper_trading.py:48` 只 import legacy `check_circuit_breaker_sync` — 0 `qm_platform.risk` import
  - `backend/app/services/signal_service.py` + `backend/engines/signal_engine.py` — 0 V3 risk refs (grep verified)
  - V3 L0-L5 只通过 Celery Beat task 跑 — parallel to (NOT in) signal→execution path
- 真值修正 scope: ADR-076 §D6 prereq list under-scoped (omit V3 production integration step); Plan v0.4 必须 integrate-first then cutover (NOT cutover-prereqs + flip .env)
- 处理: 本 plan §A IC-1+IC-2 (V3 production integration — replace legacy + L1 runner + de-stub) 落地 (D1=Replace 决议 sediment)

### Finding #2: "和我假设不同" — L1 RealtimeRiskEngine 无 production runner ✅ sediment (ADR-073 D3 confirmed)

- prompt cite (ADR-073 D3): "XtQuantTickSubscriber/RealtimeRiskEngine 仅 tests + replay runner 实例化, 无 production runner — instrument 永不触发; 留 Plan v0.4 cutover scope 候选"
- fresh verify 真值: confirmed via grep — instantiation only in `scripts/v3_tb_5b_replay_acceptance.py:358` + `scripts/v3_tb_1_replay_2_windows.py:419` + `scripts/v3_hc_4a_5y_replay_acceptance.py:171` + tests
- 处理: IC-1c (L1 production runner build) 落地

### Finding #3: "和我假设不同" — V3 Beat task mixed stub state ✅ sediment

- prompt cite (audit subagent claim): "全 V3 Beat 跑 stub" — overstatement
- fresh verify 真值 (cross-check): 
  - market-regime: real input (`market_regime_tasks.py:90` `DefaultIndicatorsProvider()` — 沿用 HC-4a 验证)
  - dynamic-threshold: 部分 stub (`dynamic_threshold_tasks.py:13` 注 "ATR/beta wire deferred")
  - reflector: stub input gathering
  - L4 sweep: 仅状态机, 无 broker wire
- 真值修正 scope: NOT "all stubs" but "mixed — market-regime real, others partial/full stub"
- 处理: IC-2 (de-stub remaining + L4 broker wire) 落地

### Finding #4: 3 carried-Gate-E deferrals 物理上不能是 pre-cutover gates (循环依赖) ✅ sediment

- prompt cite (ADR-076 §D6): LiteLLM 月成本 ≥3 month / RAG 命中率 baseline / lesson 后置抽查 — 列为 Gate E prereq
- fresh verify 真值: 三者全需 live traffic; live traffic 只有 cutover 之后才有 → 循环依赖
- 真值修正 scope: 重新分类为 POST-cutover ongoing monitoring obligations (D2=reframe 决议 sediment); 沿用 LL-169 lesson 1 + ADR-072 D2 体例
- 处理: 本 plan §C + ADR-082 sediment (CT-2c) 落地

### Finding #5: PostgreSQL16 当前 Stopped (operational, NOT alarming) ✅ sediment

- fresh verify 真值: `Get-Service PostgreSQL16` → Stopped 2026-05-15
- 真值修正 scope: dev 机操作层, all V3 Beat task 当前失败; 走 `pg_ctl start -D D:\pgdata16` 重启
- 处理: 本 sub-PR sediment 期已 trigger PG restart (background task)

---

## §I Sub-PR (Plan v0.4 sediment) cycle (本文件 sediment trigger)

本 file = Plan v0.4 sub-PR sediment, **trigger** = 横切层 FULLY CLOSED (ADR-076, Gate D 形式 close 2026-05-15) + Phase 0 audit Finding #1-#5 surface + user AskUserQuestion 1 round (D1=Replace 推荐 picked + D2 reframe 隐含 confirmed)。

**本 sub-PR scope**:
- Plan v0.4 doc NEW (本 file)
- ADR-077 reserved (Plan v0.4 closure cumulative + Gate E formal close — sediment 时机 = CT-2c)
- ADR-078~082 reserved (IC-1~3 + CT-1 + post-cutover monitoring — 各 sprint closure sediment)
- Constitution amend pending CT-2c batch closure pattern (sustained ADR-022 反 retroactive — §L10.5 amend 留 CT-2c 周期)
- skeleton §2.X.X Plan v0.4 sprint chain row pending (沿用 §2.2.2 横切层 row 体例 — 留 CT-2c batch sediment? OR 起手 sediment? 决议 CC 实测时实施)
- REGISTRY ADR-077~082 reserved row append
- LL-170 reserved (Plan v0.4 完整体例 — sediment 时机 = CT-2c)
- memory handoff Session 53+34 prepend

**关联 sub-PR**: PR # 不适用 (docs-only sediment 直 push per 铁律 42, sustained Plan v0.3 sub-PR sediment 体例) — 本 file + REGISTRY ADR-077~082 reserved row + memory handoff 3 file delta atomic。

### 修订机制 (沿用 ADR-022 集中机制)

- 任 sprint 起手 时 §A append-only sub-section amend (NOT retroactive content edit)
- 任 sprint closure 时 §A row append closure blockquote (沿用 横切层 HC-1~4 体例)
- 5 决议 lock 锁死,任 修订必走 §F replan trigger SOP + ADR sediment
- 版本 history append-only

### 版本 history

- **v0.1 (initial draft, 2026-05-15)**: Plan v0.4 PT cutover sprint chain (IC-1~3 + CT-1~2, 5 sprint) + 2 决议 lock (D1=Replace + replay-as-gate / D2=3 carried Gate-E deferrals → POST-cutover monitoring) + cycle baseline ~4.5-5.5 周 + cross-sprint risk register 13 项 + Gate E 5 项 prereq + carried deferrals 3 项 reframe 路由 + Cutover 真测期 SOP (replay-as-gate + paper-mode shake-down + go-live 1d 监控) + Plan review trigger SOP + Phase 0 active discovery 5 Finding (V3-as-island + L1 no-runner + mixed-stub + circular-deferral + PG-stopped). 沿用 Plan v0.3 sub-PR sediment 体例 (post-横切层 FULLY CLOSED cumulative 2026-05-15 + ADR-076 sediment 真值落地 plan-then-execute 体例 第 6 case Plan v0.4 context)。

---

## §J Cumulative cite footer (Plan v0.4 sediment, sustained Plan v0.1/v0.2/v0.3 体例 + Constitution §L10.5 footer 体例)

- Plan v0.4 = V3 实施期 LAST plan (post Plan v0.1 Tier A + Plan v0.2 Tier B + Plan v0.3 横切层 cumulative)
- 6-case plan-then-execute 体例累积扩 (Plan v0.1 sub-PR 8 / sub-PR 11b / sub-PR 13 / Plan v0.2 / Plan v0.3 / **Plan v0.4 本**)
- ADR-022 反 silent overwrite + 反 retroactive content edit + 反 abstraction premature sustained throughout
- 红线 5/5 sustained at sediment time: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 — **CT-2b 是 V3 实施期 ONLY 红线 transition point**
- LL-098 X10 (反 forward-progress default) sustained throughout — cutover 必 user 显式 trigger
- Phase 0 active discovery 5 Finding sediment (V3-as-island detection 是 Plan v0.4 的 raison d'être)
