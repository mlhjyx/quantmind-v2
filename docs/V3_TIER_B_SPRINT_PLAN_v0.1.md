# V3 实施期 Tier B Sprint Plan v0.1 (T1.5 + TB-1 + TB-2 + TB-3 + TB-4 + TB-5, 6 sprint)

> **本文件 = V3 风控长期实施期 Tier B 6 sprint chain 起手前 user-approved plan sediment** (post-Tier A code-side 12/12 closure cumulative Session 53 + ADR-063 sediment 真值落地, plan-then-execute 体例 第 4 case 实证累积扩, sustained Plan v0.1 sub-PR 8 体例).
>
> **Status**: ✅ User approved (Session 53+1, 5 决议 lock: D1=a 串行 / D2=A BGE-M3 / D3=b 2 关键窗口 / D4=否 仅 Tier B / D5=inline 完整). Sediment from CC 推荐 + user 2 round 反问 ack (Round 1 = 3 sub-recommendation I/II/III → user picked (I) / Round 2 = 5 decision matrix → user picked CC 推荐 all).
>
> **本文件版本**: v0.1 (post-Tier A code-side closure cumulative + ADR-063 sediment + 5 决议 lock + plan-then-execute 体例 第 4 case 实证累积扩 cumulative 体例 sustainability, 2026-05-13, Plan v0.2 sub-PR sediment cycle)
>
> **scope**: V3 Tier B sprint chain (T1.5 Tier A formal closure + TB-1 RiskBacktestAdapter full impl + TB-2 MarketRegimeService + TB-3 RiskMemoryRAG + TB-4 RiskReflectorAgent + TB-5 Tier B closure + replay 验收 + Gate B/C sediment) plan + 5 决议 lock sediment + cycle baseline 真值 + cross-sprint surface risk + Gate B + Gate C criteria + Tier B replay 真测期 SOP + plan review trigger SOP.
>
> **not scope**: V3 spec 详细拆分 → [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §12.2 / Constitution layer scope → [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) §L0-L10 / sprint-by-sprint orchestration index → [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) §2.2 (Plan v0.2 sediment NEW) / sprint chain 起手 SOP entry point → [V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) §3 / 横切层 scope → 留 Plan v0.3 (Gate D scope) / cutover scope → 留 Plan v0.4 (Gate E scope).
>
> **关联 ADR**: ADR-022 (反 silent overwrite + 反 retroactive content edit + 反 abstraction premature) / ADR-037 + 铁律 45 (4 doc fresh read SOP + cite source 锁定) / ADR-049 §3 (chunked sub-PR 体例 greenfield scope) / ADR-063 (Tier A 5d paper-mode skip + Tier B replay 真测路径, 本 plan 直接 follow-up) / ADR-064 候选 (Plan v0.2 5 决议 lock, 本 sub-PR sediment) / Tier B 期内候选 ADR-065 (T1.5 Gate A formal close) + ADR-066 (TB-1 RiskBacktestAdapter full impl + 历史回放 infra) + ADR-067 (TB-2 MarketRegimeService prompt + DDL + 集成) + ADR-068 (TB-3 BGE-M3 + risk_memory + 4-tier retention) + ADR-069 (TB-4 RiskReflectorAgent + lesson 闭环) + ADR-070 (TB-5 Tier B replay 真测结果 sediment) + ADR-071 (TB-5 Tier B closure cumulative)
>
> **关联 LL**: LL-098 X10 (反 forward-progress default) / LL-100 (chunked SOP target) / LL-101/103/104/105/106/115/116/117/127/132/133/134/135/136/137/138/139/140 (Plan v0.1 sub-PR 8+ cumulative) / LL-157 (Mock-conn schema-drift LL-115 family 8/9 实证, Session 53 cumulative) / LL-158 候选 (Tier B plan-then-execute 体例 第 4 case sediment, 本 sub-PR sediment) / Tier B 期内候选 LL-159 (TB-1 sim-to-real gap calibration) + LL-160 (TB-2 V4-Pro Bull/Bear prompt iteration) + LL-161 (TB-3 BGE-M3 latency / RAM 实测) + LL-162 (TB-4 RiskReflector 4 边界 case prompt eval) + LL-163 (TB-5 Tier B closure 体例 sediment)

---

## Context

V3 风控 **Tier A code-side 12/12 sprint 全 closed** (Session 53 cumulative 19 PR累积, sub-PR 9~19 sediment 体例 cumulative: PR #296~#323 cumulative). Latest 5 PR post-compact (Session 53 +9 5d operational kickoff):
- PR #319: Celery Beat wire `risk-metrics-daily-extract-16-30` crontab `30 16 * * 1-5` Asia/Shanghai
- PR #320: 2 silent-zero bug fix (column-name drift `total_cost_usd`/`date` → real schema `cost_usd_total`/`day` + severity case-mismatch P0/P1/P2 大写 → 小写 p0/p1/p2) + 3 schema-aware smoke tests (SAVEPOINT-insert pattern, sentinel-empty + SQL-parse 无法 distinguish "case wrong" from "no data")
- PR #321: C1 synthetic 5d toolkit (`scripts/v3_s10_c1_inject_synthetic_5d.py` 18 risk_event_log + 10 execution_plans rows tagged `c1_synthetic_%`) + cleanup runbook + verify CLI report (3/4 §15.4 PASS + 1 deferred latency)
- PR #322: ADR-063 sediment (V3 §S10 5d paper-mode skip empty-system anti-pattern) + LL-157 sediment + Constitution §L10.1 Gate A item 2 ⏭️ DEFERRED amend + Plan v0.1 §A S10 DEFERRED 标注
- PR #323: Plan v0.1 §A S10 + §C Gate A line 253 + §D 真测期 SOP 5d-related anchors post-ADR-063 sync

**Gate A 7/8 项**: sustained pending T1.5 formal close (Session 53 cumulative code-side 12/12 closure but Gate A 形式 close = T1.5 sprint scope).

**ADR-063 sediment 5-13**: Tier A wall-clock 5d paper-mode acceptance ⏭️ DEFERRED → Tier B `RiskBacktestAdapter` 历史 minute_bars replay 真测路径. Empty-system (0 持仓 + 0 tick subscribe + dev-only LLM activity) state 下 5d 自然 fire 信息熵 ≈ 0, trivially-pass 不 distinguishable from silent-zero bug class (本 session PR #320 修了正是此 class). 真测路径转 Tier B `RiskBacktestAdapter` 历史 minute_bars 回放 → 9 RealtimeRiskRule 真触发. Constitution §L10.1 Gate A item 2 ⏭️ DEFERRED 锁定. Tier B closure 时另加 ADR-070 sediment 记录真测结果.

红线 5/5 sustained throughout: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. PT 暂停清仓 (4-29 user 决议) sustained throughout Tier B.

**Why this plan**: V3 §12.2 Tier B 4 sprint chain (S12-S15, ~4-5 周 baseline) → 6 sprint chain (T1.5 + TB-1 + TB-2 + TB-3 + TB-4 + TB-5, ~8.5-12 周 baseline) post-ADR-063 真测路径修订 + ADR-022 反 silent overwrite + LL-098 X10 反 silent self-trigger. User invoked plan-then-execute 体例 (sustained Plan v0.1 sub-PR 8 sediment 体例 第 4 case 实证累积扩). User approved 5 决议 (D1-D5) → 本文件 sediment.

**Inputs fresh re-read** (sustained Constitution §L1.1 fresh read SOP + LL-116 enforce + 铁律 45 + ADR-037 + SOP-7):
- [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) v0.8 §L0/L1/L5/L6/L8/L10 全 layer scope (post-PR #322 Gate A item 2 ⏭️ DEFERRED amend sediment)
- [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) v0.7 §2.1 Tier A sprint-by-sprint table (sustained sub-PR 11b cumulative)
- [docs/V3_TIER_A_SPRINT_PLAN_v0.1.md](V3_TIER_A_SPRINT_PLAN_v0.1.md) §A-F 体例 (post-PR #322+#323 5d-related anchor sync sediment)
- [docs/V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) v0.2 §3 sprint chain SOP entry point
- [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §5.3 Bull/Bear regime detection + §5.4 RAG + §8 L5 反思闭环 + §11.1 12 模块 (Tier B 含 row 6/7/8 + RiskBacktestAdapter T1.5 prereq stub + full impl Tier B scope) + §11.4 RiskBacktestAdapter + §12.2 Tier B Sprint S12-S15 + §13.1 5 SLA + §13.2 元监控 + §14 失败模式 12 + §15.4 E2E 4 项 acceptance (post-ADR-063 transferable to replay path) + §15.5 历史回放 (sim-to-real gap counterfactual) + §15.6 合成场景 ≥7 类 + §16.1/16.2 32GB RAM + LLM budget
- [docs/adr/REGISTRY.md](adr/REGISTRY.md) (ADR-001~063 committed, 54 # space sustained, ADR-064 候选本 sub-PR sediment, ADR-065~071 候选 Tier B 期内 sediment)
- [docs/adr/ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md](adr/ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (Tier A 5d skip + Tier B replay 真测路径 决议)
- [backend/qm_platform/risk/backtest_adapter.py](../backend/qm_platform/risk/backtest_adapter.py) S5 sub-PR 5c `a656176` 140 行 stub base (RiskBacktestAdapter BrokerProtocol + NotifierProtocol + PriceReaderProtocol stub 实现, 16 tests cumulative)
- [LESSONS_LEARNED.md](../LESSONS_LEARNED.md) LL-157 last (Session 53 cumulative, ll_unique_ids canonical sustained)
- [memory/project_sprint_state.md](../memory/project_sprint_state.md) (Session 53 +9 cumulative handoff)

---

## §A Per-sprint plan (Tier B T1.5 + TB-1 + TB-2 + TB-3 + TB-4 + TB-5, 6 sprint)

Each sprint row: scope cite → acceptance → file delta order → chunked sub-PR → cycle baseline → deps → LL/ADR sediment → reviewer reverse risk → 红线 SOP → paper-mode sustained.

**Numerical thresholds 留 sprint 起手时 CC 实测决议 + ADR sediment 锁** (sustained user 5-08 决议 + memory #19/#20 + Constitution §L10 footer 体例 + Plan v0.1 §A footer 体例 sustained).

### T1.5 — Tier A formal closure + Gate A 7/8 verify + Tier A ADR cumulative promote ⭐ (D1=a 串行 lock)

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — ADR-065 (Gate A 7/8 PASS + 1 DEFERRED). PR #325-#328.

| element | content |
|---|---|
| Scope | Tier A code-side 12/12 sprint closure 已成 (Session 53 cumulative 19 PR, sub-PR 9~19 sediment 体例 cumulative). 形式 Gate A 7/8 项 verify + Tier A ADR-047~063 cumulative promote + sprint timeline 真值修订 (sub-PR 9 cite + ADR-063 sediment post-修订) + ROADMAP doc sediment (Constitution §0.1 line cite "RISK_FRAMEWORK_LONG_TERM_ROADMAP.md, planned, sediment 时机决议 Tier B closure 后" 标注 sustained, Plan v0.2 Tier B closure 时由 TB-5 sediment closure 标注). **Status (post Session 53 cumulative)**: Gate A item 1 ✅ (12 sprint code-side closed) + item 2 ⏭️ DEFERRED per ADR-063 + items 3-8 待 `quantmind-v3-tier-a-mvp-gate-evaluator` subagent verify run |
| Acceptance | Gate A 7/8 items all PASS: (3) 元监控 `risk_metrics_daily` 14d sediment verify (CC 实测 SQL row count + 日期连续性, sub-PR 10 真值 verify dimension); (4) ADR-019/020/029 + Tier A 后续 ADR-047~063 全 REGISTRY committed (CC 实测 REGISTRY SSOT verify); (5) V3 §11.1 12 模块 production-ready (CC 实测 `import qm_platform.risk.realtime.engine` + smoke + module health check); (6) LiteLLM 月成本累计 ≤ V3 §16.2 上限 ~$50/月 (CC 实测 SQL llm_cost_daily aggregate verify); (7) CI lint `check_anthropic_imports.py` (或 `check_llm_imports.sh` per ADR-031 §6 sustained) 生效 + pre-push hook 集成 verify; (8) V3 §3.5 fail-open 设计实测 (任 1 News 源 fail / fundamental_context fail / 公告流 fail, alert 仍发, CC 实测 mock fail scenario); `quantmind-v3-tier-a-mvp-gate-evaluator` subagent verdict = PASS; ROADMAP.md 标注 NEW 或 修订 sediment (sustained ADR-022 反 silent inflate, 仅 Constitution §0.1 line 35 标注修订 closure 状态); Tier A 期 LL append-only sediment review (LL-127~157 cumulative review verify) |
| File delta | ~5-10 doc edits / ~500-1000 lines (verify-only + ADR-065 sediment + ROADMAP.md 标注 closure + Constitution patch sustained ADR-022 反 retroactive content edit体例); 0 code change (verify-only sprint sustained 沿用 sub-PR 9 verify-only 体例) |
| Chunked sub-PR | **chunked 2 sub-PR** (沿用 LL-100 chunked SOP + Plan v0.1 §A S2.5 sub-PR 11a/11b chunked precedent): T1.5a (subagent verify run + 7/8 items evidence sediment doc + Tier A 期 LL append-only review) → T1.5b (Tier A ADR cumulative ROADMAP doc 标注 closure + Constitution version v0.8 → v0.9 + Plan v0.2 §C Gate A item 2 ⏭️ DEFERRED transferable 标注 + ADR-065 Gate A formal close sediment) |
| Cycle | 3-5 day baseline (T1.5a ~1-2 day + T1.5b ~1-2 day + buffer ~1 day); replan trigger 1.5x = 4.5-7.5 day |
| Dependency | 前置: Tier A code-side 12/12 ✅ closed (Session 53 PR #319~#323 cumulative); V3 6 件套 100% closure ✅ (Constitution v0.8 + skeleton v0.7 + 13 quantmind-v3-* skill + 13 hook cumulative + 7 charter + V3_LAUNCH_PROMPT v0.2) / 后置: TB-1 (D1=a 串行 sustained per Plan v0.2 §G I.1 决议, NOT 并行) |
| LL/ADR candidate | **ADR-065** ✅ promote (T1.5 Gate A formal close + 7/8 item evidence cumulative sediment + ADR-063 deferred item 2 transferable to Tier B replay path 体例 sustainability); **LL-158** ✅ promote (Tier B plan-then-execute 体例 第 4 case sediment + Plan v0.1 sub-PR 8 体例 cumulative scope 实证累积扩 sustainability — sustained Plan v0.1 sub-PR 8 sediment 体例真值落地实证累积扩 cumulative pattern 体例文档化 4 case: case 1 Plan v0.1 5-09 / case 2 sub-PR 11b 5-09 / case 3 sub-PR 13 5-09 / case 4 本 Plan v0.2 5-13) |
| Reviewer reverse risk | 反 silent skip Gate A items (LL-098 X10 sustained); 反 retroactive ADR content edit (ADR-022 sustained, 仅 append 标注); ROADMAP doc scope creep 候选 (留 TB-5 Tier B closure post 横切层 完整 sediment, Constitution §0.1 line 35 标注 sustained); 反 subagent verdict silent overwrite (LL-115 capacity expansion 真值 silent overwrite 体例 sustained) |
| 红线 SOP | redline_pretool_block hook + quantmind-v3-redline-verify skill (5/5 query: cash + 0 持仓 + LIVE_TRADING_DISABLED + EXECUTION_MODE + QMT_ACCOUNT_ID); 0 .env mutation (sustained 红线 5/5); 0 真账户 broker call (subagent verify run 走 read-only path); 0 production yaml mutation |
| Paper-mode | 0 真账户 mutation, 0 broker call, sustained 红线 5/5 throughout T1.5 |

### TB-1 — RiskBacktestAdapter 完整实现 + 历史 minute_bars replay 2 关键窗口 ⭐ (D3=b 2 关键窗口 lock)

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — ADR-066. PR #330 (TB-1a) + #331 (TB-1b) + #332 (TB-1c).
> **9 rules → 10 rules 标注 (ADR-066 D2)**: 本节多处 cite "9 RealtimeRiskRule" 是 ADR-029 S5 base-time write 体例; S9a 加 TrailingStop 为第 10 个 (ADR-060), 且 CorrelatedDrop 亦在 ADR-029 10-rule set 内但本节 Scope list 漏列 — 实为 **10 RealtimeRiskRule** (LimitDownDetection / NearLimitDown / GapDownOpen / TrailingStop / RapidDrop5min / RapidDrop15min / VolumeSpike / LiquidityCollapse / IndustryConcentration / CorrelatedDrop). Append-only 标注, sustained ADR-022 反 retroactive content edit.

| element | content |
|---|---|
| Scope | V3 §11.4 `RiskBacktestAdapter` 完整实现 (sustained S5 sub-PR 5c `a656176` 140 行 stub base + full implementation evaluator framework, BrokerProtocol + NotifierProtocol + PriceReaderProtocol pure stub sustained, full impl 加 evaluate_at(timestamp, positions, market_data, context) → list[RiskEvent] pure function 接口 per V3 §11.4 line 1287) + 9 RealtimeRiskRule (LimitDownDetection / NearLimitDown / RapidDrop5min / RapidDrop15min / GapDown / VolumeSpike / LiquidityCollapse / IndustryConcentrationDrop / TrailingStop, sustained Tier A S5 sub-PR 5a/5b 已 production) 真触发 integration + 2 关键窗口 historical replay infra: **(D3=b 决议 lock)** 2024Q1 量化踩踏 + 2025-04-07 关税冲击 -13.15% (vs 5y full ~191M minute_bars rows, 5y full 留 Tier B closure post 横切层 Plan v0.3 scope) + dedup uniqueness contract (timestamp, symbol_id, rule_id) per V3 §11.4 line 1298 + 纯函数契约 audit (0 broker / 0 INSERT / 0 alert) per V3 §11.4 line 1294 + counterfactual analysis 框架 (V3 §15.5 sim-to-real gap audit, "what would V3 alert do? vs actual outcome" sediment 进 `docs/risk_reflections/replay/`) |
| Acceptance | 9 RealtimeRiskRule 真触发 verify on 2 historical windows (CC 实测 fire count + symbol coverage + 时间分布, ADR-066 sediment 锁 baseline); replay completes within reasonable wall-clock budget (CC 实测 baseline + ADR-066 sediment, 2 关键窗口 estimate ~2-4M minute_bars rows × 2537 stocks × 9 rules, wall-clock <6h 候选); dedup contract verify (timestamp, symbol_id, rule_id) unique on replay path (SAVEPOINT-insert pattern sustained per LL-157 8/9 实证 schema-aware smoke); 纯函数契约 audit PASS (0 broker call via mock NotifierProtocol/BrokerProtocol/PriceReaderProtocol injection verify / 0 DB INSERT via SAVEPOINT verify per LL-157 pattern / 0 alert push via mock injection); counterfactual analysis output sediment 进 `docs/risk_reflections/replay/2024Q1_quant_crash.md` + `docs/risk_reflections/replay/2025-04-07_tariff_shock.md` NEW (sustained V3 §8.2 risk_reflections dir 体例); integration test coverage ≥80% (L4 hybrid acceptance per V3 §12.3); 13 tests minimum (sub-PR 5c 16 tests sustained + full impl ~30 tests 新 + 9 rule integration ~15 tests) |
| File delta | ~10-15 files / ~1500-2500 lines (RiskBacktestAdapter full impl evaluate_at() ~300-500 lines + 9 rule integration adapter wrapper ~400-600 lines + 2 window replay infra ~400-600 lines + counterfactual framework ~200-400 lines + integration tests ~400-500 lines + reflection sediment dir ~100-200 lines doc + ADR-066 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 3 sub-PR** (沿用 LL-100 chunked SOP + ADR-049 §3 chunked precedent for greenfield scope): TB-1a (RiskBacktestAdapter full evaluator evaluate_at() + dedup contract + 纯函数契约 audit + 9 rule integration adapter wrapper ~800-1200 lines + ~400 lines tests) → TB-1b (2 关键窗口 replay infra + counterfactual framework + replay timing instrumentation ~600-900 lines + ~300 lines tests) → TB-1c (replay 真测 fire count baseline + reflection dir sediment 2 file + ADR-066 sediment + LL-159 候选 sediment ~300-500 lines + verification evidence) |
| Cycle | 2 周 baseline (TB-1a ~0.7 周 + TB-1b ~0.7 周 + TB-1c ~0.4 周 + buffer 0.2 周); replan trigger 1.5x = 3 周 |
| Dependency | 前置: T1.5 ✅ closed (D1=a 串行 sustained per 决议) + minute_bars hypertable ~191M rows ready (SYSTEM_STATUS §0 sustained, 2 关键窗口 ~2-4M rows ready) + 9 RealtimeRiskRule production-ready (Tier A S5 sub-PR 5a `8888da7` 5 rule + 5b `4dc6849` 4 rule + 5c `a656176` stub adapter 全 closed); RiskBacktestAdapter stub `a656176` 140 行 base sustained (BrokerProtocol + NotifierProtocol + PriceReaderProtocol stub) / 后置: TB-2 (regime context input on replay path 等价 via market_regime_log integration) + TB-5 (final acceptance Tier B replay 验收) |
| LL/ADR candidate | **ADR-066** ✅ promote (TB-1 RiskBacktestAdapter full impl + 历史回放 infra 2 关键窗口 + 9 RealtimeRiskRule 真触发 evaluator + counterfactual analysis framework + 纯函数契约 audit 决议 锁); **LL-159** ✅ promote (sim-to-real gap calibration first finding via 2 关键窗口 真测 — sustained PR #210 sim-to-real gap 体例 实证累积扩 第 2 case Tier B context) |
| Reviewer reverse risk | replay infra silent INSERT path 风险 (LL-115 capacity expansion 真值 silent overwrite, mitigation: SAVEPOINT-insert verify per LL-157 pattern); 反 fire count silent 0 anti-pattern (LL-157 family — empty result silent miss, mitigation: counterfactual analysis output 必含 ≥1 alert event per window); 反 .env tick subscribe accidental enable on replay path (红线 5/5, mitigation: mock injection verify); 反 wall-clock budget overshoot silent (LL-100 chunked SOP boundary, mitigation: TB-1b cycle 内 wall-clock baseline + ADR-066 锁) |
| 红线 SOP | sustained T1.5; replay path tick subscribe 0 真 xtquant API call (mock injection verify); 0 真账户 broker call sustained; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout TB-1 |
| Paper-mode | sustained T1.5; replay 走 mock broker/notifier/price reader (RiskBacktestAdapter stub sub-PR 5c 体例 sustained), 0 真 production system contact; LIVE_TRADING_DISABLED=true sustained throughout TB-1 |

### TB-2 — L2 MarketRegimeService Bull/Bear 2-Agent debate (V4-Pro × 3) + market_regime_log + L3 集成

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — ADR-067. PR #333 (TB-2a) + #334 (TB-2b) + #335 (TB-2c) + #336 (TB-2d).

| element | content |
|---|---|
| Scope | V3 §5.3 Bull/Bear regime detection + V3 §11.1 row 6 `MarketRegimeService` (`backend/app/services/risk/`); V4-Pro Bull Agent (3 看多论据, sustained ADR-036 mapping V4-Flash → V4-Pro debate reasoning capability) + V4-Pro Bear Agent (3 看空论据) + V4-Pro Judge (regime 输出: Bull/Bear/Neutral/Transitioning + confidence + reasoning); `prompts/risk/bull_agent_v1.yaml` + `prompts/risk/bear_agent_v1.yaml` + `prompts/risk/regime_judge_v1.yaml` NEW (sustained quantmind-v3-prompt-design-laws skill enforce 0 hardcoded 决议 + sprint 起手 CC 实测决议 + ADR-067 sediment 锁); `market_regime_log` DDL NEW (TimescaleDB hypertable, 1 month chunk per V3 §5.3 line 670, BIGSERIAL PK + timestamp + regime VARCHAR(20) CHECK + confidence NUMERIC(5,4) + bull/bear_arguments JSONB + judge_reasoning TEXT + market_indicators JSONB + cost NUMERIC(8,4)); Celery Beat 3 schedule (9:00 + 14:30 + 16:00 Asia/Shanghai per V3 §5.3 line 664); L3 阈值集成 (regime=Bear → L1 RT_RAPID_DROP_5MIN × 0.8 verify per V3 §5.3 line 685); regime change → 每日 push user 确认调整 (不全自动 per V3 §5.3 line 687); 输入: 上证指数 / 沪深 300 + 板块涨跌家数 + 北向资金 + 50ETF 期权 IV (恐慌指数 proxy) per V3 §5.3 line 658 |
| Acceptance | 3 prompts/risk/*.yaml NEW + prompt eval methodology 跑通 (50 历史 regime case via TB-1 replay sourced or Tushare 历史回放 2 关键窗口 sourced, Bull/Bear/Judge accuracy ≥ baseline e.g. 70% match against retrospective regime labels — CC 实测 baseline + ADR-067 sediment 锁); `market_regime_log` DDL NEW + migration apply + rollback pair (sustained Plan v0.1 §A S2.5 sub-PR 11a 4-phase pattern DDL+rollback 体例); Celery Beat 3 schedule production-active + 真 fire log verify (Servy QuantMind-CeleryBeat restart + 3 schedule entry verify, sustained 铁律 44 X9 post-merge ops); L3 integration (regime=Bear → L1 阈值 × 0.8) integration smoke verify (testcontainers PG + Redis mock + LiteLLM mock per V3 §15.3); LiteLLM cost ≤ V3 §16.2 budget (~$30/月 Judge + ~$0.10-0.39/月 Bull/Bear discount 走 2026-05-31 / full price post-2026-05-31, CC 实测 SQL llm_cost_daily aggregate verify); unit ≥95% (L2 critical per V3 §12.3); integration smoke (testcontainers PG + LiteLLM mock + xtquant mock); regime change push user 确认 channel verify (DingTalk integration smoke) |
| File delta | ~12-18 files / ~1500-2500 lines (3 prompts yaml ~300-500 lines + MarketRegimeService class ~400-600 lines + `market_regime_log` DDL + migration ~200-300 lines + Celery task + Beat schedule wire ~200-300 lines + L3 integration patch (l3 dynamic_threshold engine 修改) ~200-300 lines + prompt eval framework ~300-500 lines + tests cumulative ~600-1000 lines + ADR-067 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 3 sub-PR**: TB-2a (DDL + migration + rollback pair + MarketRegimeService skeleton class + 3 prompts yaml structure ~400-600 lines + smoke tests ~200-300 lines) → TB-2b (3 prompts/risk/*.yaml content sediment + Bull/Bear/Judge V4-Pro wire via LiteLLMRouter (sustained ADR-031/032/033) + prompt eval framework + 50 历史 case eval run ~500-700 lines + prompt eval tests ~300-400 lines) → TB-2c (Celery Beat 3 schedule wire + Servy restart runbook + L3 integration (l3 dynamic_threshold engine 修改) + integration smoke + ADR-067 sediment + LL-160 候选 sediment ~400-600 lines + verification evidence) |
| Cycle | 2 周 baseline (TB-2a ~0.7 周 + TB-2b ~0.7 周 + TB-2c ~0.6 周); replan trigger 1.5x = 3 周 |
| Dependency | 前置: TB-1 ✅ closed (replay path 提供 prompt eval 50 历史 case 数据源 候选, OR Tushare 历史回放 alternative source) + LiteLLM router production-ready (Tier A S1 ✅ closed PR #221-#226) + V4-Pro budget verify (V3 §16.2 ~$50/月 上限 sustained) + ADR-036 V4-Flash → V4-Pro mapping sustained (committed) / 后置: TB-3 (regime context column 入 risk_memory snapshot context_snapshot JSONB schema) + TB-4 (regime context input 入 5 维反思 Context 维) |
| LL/ADR candidate | **ADR-067** ✅ promote (TB-2 MarketRegimeService Bull/Bear 2-Agent debate prompt 设计 + `market_regime_log` DDL + Celery Beat 3 cadence + L3 阈值 集成 + regime change push user 决议 锁; alias 沿用 ADR-026 reserved 体例 sustained REGISTRY); **LL-160** ✅ promote (V4-Pro Bull/Bear debate prompt iteration findings — sustained `quantmind-v3-prompt-iteration-evaluator` skill 体例 + V4-Pro debate reasoning capability 实测 finding) |
| Reviewer reverse risk | V4-Pro prompt silent drift 风险 (LL-115, mitigation: ADR-067 sediment 锁 prompt v1.yaml SHA verify + diff-aware review); 反 Judge bias toward Bull regime in calm period (prompt 设计反 anti-pattern, mitigation: 50 历史 case eval 含 Bull/Bear/Neutral 三 regime 平衡分布); LiteLLM monthly cost overshoot risk (V3 §16.2 上限 ≤ $50/月 sustained, mitigation: `quantmind-v3-llm-cost-monitor` skill 月度 cost audit + warn ≥80% + reject ≥100%); 反 market_regime_log silent INSERT path (sustained 铁律 17 DataPipeline 例外条款 sub-task creep 候选, mitigation: TB-2a DDL + DataPipeline contract integration verify) |
| 红线 SOP | sustained T1.5; V4-Pro prompt 改 → ADR-067 sediment 锁 (反 silent prompt drift); 0 真账户 mutation; LIVE_TRADING_DISABLED sustained throughout TB-2; LiteLLM cost overshoot ≥100% upper bound → STOP + push user |
| Paper-mode | sustained T1.5; prompt eval 走 historical case 数据 (TB-1 replay sourced OR Tushare 历史回放), 0 真 live regime signal action; regime change push user 确认 走 DingTalk 但 NOT auto-execute (sustained V3 §5.3 line 687) |

### TB-3 — L2 RiskMemoryRAG + pgvector + BGE-M3 本地 embedding ⭐ (D2=A BGE-M3 lock)

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — ADR-068. PR #339 (TB-3a) + #340 (TB-3b) + #341 (TB-3c) + #342 (TB-3d).

| element | content |
|---|---|
| Scope | V3 §5.4 Risk Memory RAG + V3 §11.1 row 7 `RiskMemoryRAG` (`backend/app/services/risk/`); `risk_memory` DDL NEW (per V3 §5.4 line 694: BIGSERIAL PK + event_type VARCHAR(50) + symbol_id VARCHAR(20) + event_timestamp TIMESTAMPTZ + context_snapshot JSONB + action_taken VARCHAR(50) + outcome JSONB + lesson TEXT + embedding VECTOR(1024) + created_at TIMESTAMPTZ); pgvector extension verify (TimescaleDB 同 PG, 0 新依赖 per V3 §5.4 line 716 "已验证"); ivfflat index ON embedding USING vector_cosine_ops + event_type composite index (event_type, event_timestamp DESC) per V3 §5.4 line 706-707; **(D2=A 决议 lock)**: BGE-M3 本地 embedding (1024 维, 中文优化, 2GB RAM 常驻 per V3 §16.1 sustained, vs LiteLLM API B 选项 reject — 沿用 V3 §16.1 32GB RAM 风控总常驻 ~5GB + buffer 7GB 留 BGE-M3 2GB 内可容 + 0 cost advantage + 中文优化 + 沿用 V3 §5.4 line 712-714 option A); retrieval API (vector cosine similarity top 5 per V3 §5.4 line 710); L1 触发时 push 集成 ("类似情况 N 次, 做 X 动作, 平均结果 Y" 沿用 V3 §5.4 design); 4-tier retention (recent 30d / monthly 90d / quarterly 365d / permanent lessons-only, sustained V3 §16.4 storage budget ~5MB/月 60MB/year permanent lessons); BGE-M3 service container / conda env 部署 (CC 实测决议 + ADR-068 sediment) |
| Acceptance | `risk_memory` DDL NEW + migration apply + rollback pair (sustained Plan v0.1 §A S2.5 sub-PR 11a 4-phase pattern); pgvector extension verify (CREATE EXTENSION IF NOT EXISTS vector + index 创建 verify); BGE-M3 embedding service (docker container OR conda env, CC 实测决议 + ADR-068 sediment 锁) healthcheck + ≤ 2GB RAM verify (CC 实测 docker stats OR process RSS 实测 baseline, sustained V3 §16.1 风控总常驻 ~5GB budget); retrieval API < 200ms P99 verify on N=10k memory rows synthetic dataset (CC 实测 baseline + ADR-068 sediment 锁); L1 触发时 push 内容含 RAG top 5 verify (integration smoke testcontainers PG + Redis mock + BGE-M3 service mock); 4-tier retention 策略 verify (Celery Beat 月 retention cleanup task + apply on synthetic dataset verify); unit ≥95% (retrieval critical per V3 §12.3); embedding fallback policy (BGE-M3 OOM → retrieval skip alert path verify per V3 §14 #13 sustained, alert 仍发, integration smoke fail-mode injection verify); 沿用 LL-157 schema-aware smoke pattern (SAVEPOINT-insert verify 反 silent miss) |
| File delta | ~10-15 files / ~1200-2000 lines (`risk_memory` DDL + migration + rollback ~200-300 lines + RiskMemoryRAG class ~300-500 lines + BGE-M3 service wrapper ~200-400 lines + retrieval API ~200-300 lines + L1 push integration ~200-300 lines + 4-tier retention Beat schedule + cleanup task ~200-300 lines + tests cumulative ~400-600 lines + ADR-068 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 3 sub-PR**: TB-3a (`risk_memory` DDL + migration + rollback pair + RiskMemoryRAG skeleton + pgvector verify + synthetic dataset generator ~400-600 lines + smoke tests ~200-300 lines) → TB-3b (BGE-M3 service container / conda env 部署 + embedding wrapper + retrieval API + L1 push integration ~500-700 lines + integration smoke testcontainers + BGE-M3 service mock ~200-300 lines) → TB-3c (4-tier retention Beat schedule + cleanup task + ADR-068 sediment + LL-161 候选 sediment + cleanup runbook ~300-500 lines + verification evidence) |
| Cycle | 1-2 周 baseline (TB-3a ~0.5 周 + TB-3b ~0.5-1 周 + TB-3c ~0.3 周); replan trigger 1.5x = 1.5-3 周 |
| Dependency | 前置: TB-2 ✅ closed (regime context column 入 context_snapshot JSONB schema, MarketRegimeService output 作 risk_memory snapshot source) + pgvector extension verify production-ready (沿用 V3 §5.4 line 716 "已验证") / 后置: TB-4 (RAG 闭环 lesson sink point, RiskReflector V4-Pro reflection outcome → V4-Flash embed → INSERT risk_memory) + TB-5 (final acceptance Tier B replay 验收 含 RAG retrieval 命中率 baseline) |
| LL/ADR candidate | **ADR-068** ✅ promote (TB-3 BGE-M3 本地 embedding 选型 vs LiteLLM API + `risk_memory` DDL + 4-tier retention 策略 + retrieval API < 200ms P99 baseline + BGE-M3 OOM fail-mode 决议 锁; alias 沿用 ADR-025 reserved 体例 sustained REGISTRY); **LL-161** ✅ promote (BGE-M3 embedding latency / RAM 实测 baseline + 4-tier retention boundary case findings + pgvector ivfflat probes tuning 实测) |
| Reviewer reverse risk | BGE-M3 OOM → retrieval silent skip without alert (反 LL-157 family — silent fail, mitigation: integration smoke fail-mode injection verify alert 仍发); pgvector ivfflat index probes 参数 tune 漂移 (LL-115, mitigation: probes 数 ADR-068 sediment 锁); 反 risk_memory INSERT 路径 silent FK violation (sustained 铁律 17 DataPipeline 例外条款 sub-task creep 候选, mitigation: TB-3a DDL + DataPipeline contract integration verify SAVEPOINT pattern) |
| 红线 SOP | sustained T1.5; risk_memory INSERT 走 DataPipeline (铁律 17) OR 手工 partial UPSERT per subset-column 例外 (LL-066, PR #43/#45 sustained); 0 真账户 mutation; LIVE_TRADING_DISABLED sustained throughout TB-3 |
| Paper-mode | sustained T1.5; synthetic dataset (TB-3a sub-PR generated) + TB-1 replay sourced memory rows, 0 真 live event data 入库 (until TB-4 闭环 lesson loop activate at TB-4 cycle); BGE-M3 service NOT production-active (offline embedding only on synthetic + replay-sourced data) |

### TB-4 — L5 RiskReflectorAgent + 5 维反思 (V4-Pro) + 周/月/event cadence + lesson→risk_memory 闭环

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — ADR-069. PR #343 (TB-4a) + #344 (TB-4b) + #345 (TB-4c) + #346 (TB-4d).

| element | content |
|---|---|
| Scope | V3 §8 L5 反思闭环层 + V3 §11.1 row 8 `RiskReflectorAgent` (`backend/app/services/risk/`); `prompts/risk/reflector_v1.yaml` NEW (V4-Pro 5 维反思 per V3 §8.1: Detection / Threshold / Action / Context / Strategy 5 维); Celery Beat 3 cadence per V3 §8.1 line 918-921 (Sunday 19:00 周复盘 / 月 1 日 09:00 月复盘 / 重大事件后 24h e.g. 单日 portfolio < -5% / N 股同时跌停 / STAGED cancel 率异常); DingTalk push 摘要 per V3 §8.2 (周复盘 markdown report 摘要 + repo 沉淀); `docs/risk_reflections/YYYY_WW.md` + `docs/risk_reflections/YYYY_MM.md` + `docs/risk_reflections/event/YYYY-MM-DD_<event_summary>.md` 沉淀 dir 体例 NEW (sustained V3 §8.2 line 938-942); lesson→risk_memory 闭环 per V3 §8.3 (每事件 outcome 收集后 V4-Flash embedding → INSERT risk_memory 走 DataPipeline 铁律 17); 参数候选→user reply approve→CC 自动生成 PR per V3 §8.3 line 965-967 (候选不自动改 .env, sustained ADR-022, user reply approve → CC 自动 commit + push → user merge); user reply reject → 候选入 `docs/research-kb/risk_findings/` 长尾留存 per V3 §8.3 line 968; 候选规则新增→docs/research-kb/risk_findings/ 长尾留存→正常 PR 流程 per V3 §8.3 line 970-972 |
| Acceptance | `prompts/risk/reflector_v1.yaml` NEW + prompt eval methodology 跑通 4 边界 case per V3 §15.2 line 1507 (empty week / 1 event / 100 events / V4-Pro timeout — CC 实测 baseline + ADR-069 sediment 锁); Celery Beat 3 cadence production-active + 真 fire log verify (Sunday 19:00 ± 1h SLA per V3 §13.1 line 1376, 沿用 铁律 44 X9 Servy restart post-merge); DingTalk push 摘要 接入 verify (integration smoke testcontainers + DingTalk mock); lesson→risk_memory 闭环 (V4-Pro reflection outcome JSONB → V4-Flash embedding 1024 维 → INSERT 走 DataPipeline 铁律 17, V3 §16.2 cost ~$1-2/月 Embedding RAG ingest sustained) integration smoke verify; user reply approve → CC 自动 PR 生成 happy path verify (e2e test mocked DingTalk webhook reply + CC PR generate flow); 候选规则新增 → `docs/research-kb/risk_findings/YYYY-MM-DD_<rule>.md` 沉淀 体例 verify; unit ≥80% (L5 non-critical per V3 §12.3); LiteLLM V4-Pro cost ≤ V3 §16.2 budget ~$5-10/月 RiskReflector (CC 实测 SQL llm_cost_daily aggregate verify) |
| File delta | ~15-20 files / ~2000-3000 lines (RiskReflectorAgent class ~400-600 lines + `prompts/risk/reflector_v1.yaml` 5 维 prompt template ~300-500 lines + Celery task + Beat 3 schedule wire ~300-400 lines + DingTalk push integration ~200-300 lines + `docs/risk_reflections/` dir 体例 setup + .gitkeep + README ~50-100 lines + lesson loop integration (V4-Flash embed → DataPipeline INSERT risk_memory) ~200-300 lines + user reply approve → CC 自动 PR 生成 flow + DingTalk webhook receiver patch ~300-500 lines + tests cumulative ~500-700 lines + ADR-069 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 4 sub-PR** (反 sub-PR 8 sediment 单 sub-PR 估; sustained sub-PR 8 chunked 3a/3b/3c precedent for greenfield scope + Plan v0.1 §A S2.5 sub-PR 11a/11b chunked + ADR-049 §3 sediment, 累积扩 4 chunked for TB-4 较大 scope): TB-4a (RiskReflectorAgent skeleton class + `prompts/risk/reflector_v1.yaml` 5 维 prompt template + V4-Pro wire via LiteLLMRouter (sustained ADR-031/032/033/036) ~400-600 lines + smoke tests ~200-300 lines) → TB-4b (Celery Beat 3 cadence + Servy restart runbook + DingTalk push 摘要 + `docs/risk_reflections/` dir 体例 setup ~500-700 lines + integration smoke testcontainers ~200-300 lines) → TB-4c (lesson→risk_memory 闭环 + V4-Flash embed → INSERT 走 DataPipeline 铁律 17 + 4 边界 case prompt eval (empty week / 1 event / 100 events / V4-Pro timeout) ~400-600 lines + closed-loop integration smoke ~200-300 lines) → TB-4d (user reply approve→CC 自动 PR 生成 flow + DingTalk webhook receiver patch (sustained Tier A S8 sub-PR 8b PR #248 webhook receiver 体例) + 候选规则新增→`docs/research-kb/risk_findings/` 体例 + ADR-069 sediment + LL-162 候选 sediment ~400-600 lines + e2e mocked test ~200-300 lines) |
| Cycle | 2 周 baseline (TB-4a ~0.5 周 + TB-4b ~0.5 周 + TB-4c ~0.5 周 + TB-4d ~0.5 周); replan trigger 1.5x = 3 周 |
| Dependency | 前置: TB-3 ✅ closed (RAG 闭环 lesson sink point, risk_memory DDL + BGE-M3 service production-ready) + TB-2 ✅ closed (regime context input 入 5 维反思 Context 维) + DingTalk webhook receiver (sustained Tier A S8 sub-PR 8b PR #248 ✅ closed) / 后置: TB-5 (final acceptance + 闭环 0 P0 元告警 verify + V3 §15.4 4 项 acceptance on Tier B replay path) |
| LL/ADR candidate | **ADR-069** ✅ promote (TB-4 RiskReflectorAgent 5 维反思 prompt 设计 + Celery Beat 3 cadence Sunday/月/event + lesson→risk_memory 闭环 + user reply approve→CC 自动 PR 生成 flow + 候选规则新增→docs/research-kb/risk_findings/ 体例 决议 锁); **LL-162** ✅ promote (V4-Pro RiskReflector reasoning quality findings + 4 边界 case prompt eval 实测 baseline — sustained `quantmind-v3-prompt-iteration-evaluator` skill 体例 实证累积扩 第 2 case Tier B context) |
| Reviewer reverse risk | user reply approve→CC 自动 PR 生成 silent .env mutation 风险 (反 ADR-022 + 铁律 35 sustained, mitigation: CC 仅 generate PR, NOT auto-merge, user 显式 merge 走 redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce); V4-Pro timeout silent skip 风险 (LL-157 family — 反思周/月 silent miss, mitigation: 4 边界 case prompt eval V4-Pro timeout case 必含, 重试一次 + 失败则跳过本周 + 元告警 per V3 §14 #14); lesson→risk_memory 闭环 N×N drift 风险 (LL-101/103/116, mitigation: `quantmind-v3-doc-sediment-auto` skill 4 doc 同步 enforce); reflector_v1.yaml prompt drift 反 (sustained LL-115, mitigation: ADR-069 sediment 锁 prompt SHA verify) |
| 红线 SOP | sustained T1.5; 0 .env mutation via reply approve (仅 PR generate, user 显式 merge); 0 真账户 mutation; user 显式 merge sustained (sustained redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce); LiteLLM cost overshoot ≥100% upper bound → STOP + push user |
| Paper-mode | sustained T1.5; reflection 走 TB-1 replay sourced events OR mock data (synthetic + replay-sourced), 0 真 live PT outcome 影响; user reply approve → CC 自动 PR 仅 generate, NOT merge (sustained user 显式 merge) |

### TB-5 — Tier B closure + RiskBacktestAdapter replay 验收 + V3 §15.6 合成场景 ≥7 类 + Gate B/C 形式 close

> **✅ CLOSED 2026-05-14 (TB-5c 标注)** — TB-5a PR #347 (≥7 synthetic scenarios) + TB-5b PR #348 ADR-070 (replay acceptance) + TB-5c PR #349 ADR-071 (Gate B 5/5 + Gate C 6/6 formal close). **V3 Tier B (6-sprint chain T1.5→TB-1→TB-2→TB-3→TB-4→TB-5) FULLY CLOSED.** Next: Plan v0.3 横切层 (user 显式 ack required, sustained LL-098 X10).

| element | content |
|---|---|
| Scope | Tier B replay 验收 per ADR-063 (Constitution §L10.1 Gate A item 2 transferable: V3 §15.4 4 项 acceptance + V3 §13.1 5 SLA verify on RiskBacktestAdapter replay path 等价 transferable, sustained Plan v0.1 §D:271 post-ADR-063 体例); V3 §15.6 合成场景 ≥7 类 fixture + assertion CI 跑通 per V3 §15.6 line 1546-1552 (1. 4-29 类事件 3 股盘中跌停 + 大盘 -2% / 2. 单股闪崩 -15% in 5min / 3. 行业崩盘 持仓 5 股同行业 day -5% / 4. regime 急转 Bull → Bear in 1 day / 5. LLM 服务全挂 + Ollama fallback / 6. DingTalk 不可用 + email backup / 7. user 离线 4h + STAGED 30min timeout); Gate B subagent verify (借 `quantmind-v3-tier-a-mvp-gate-evaluator` charter → Tier B variant subagent 借用 charter 体例 sustained); Gate C subagent verify (Constitution §L10.3, V3 §12.2 Sprint S12-S15 mapping to TB-2/TB-3/TB-4); Tier B ROADMAP doc sediment (Constitution §0.1 line 35 "planned, sediment 时机决议 Tier B closure 后" 标注 closure 修订, sustained ADR-022 反 silent inflate); ADR-070 (Tier B replay 真测结果 sediment per ADR-063 referenced "ADR-XXX 记录真测结果") + ADR-071 (Tier B closure cumulative + Gate B + Gate C formal close) sediment; sprint timeline 真值修订 (Plan v0.2 §E sub-PR cite + post-Tier B closure 真值落地) |
| Acceptance | V3 §15.4 4 项 PASS on replay path: (1) P0 alert 误报率 < 30% (CC 实测 baseline + ADR-070 sediment 锁 on replay run 2 关键窗口); (2) L1 detection latency P99 < 5s on replay timing instrumentation; (3) L4 STAGED 流程闭环 0 失败 on replay flow (sustained Tier A S8 + S9 sub-PR cumulative 8a/8b/8b-cadence/9a/9b 全 production-ready 体例); (4) 元监控 0 P0 元告警 on replay run (risk_metrics_daily aggregate verify); V3 §13.1 5 SLA verify on replay path (L1<5s / News 30s / LiteLLM<3s / DingTalk<10s / STAGED 30min, transferable per Plan v0.1 §D:271 post-ADR-063); V3 §15.6 ≥7 scenarios CI green (pytest fixture + assertion, 沿用 pre-push hook X10 + smoke pattern); Gate B 5 items PASS (Constitution §L10.2 amend per Plan v0.2 §G II Push back #1 + #2: item 1 RiskBacktestAdapter ✅ TB-1 + item 2 12 年 counterfactual ⏭ MODIFIED per D3=b → 2 关键窗口 sustained + item 3 WF 5-fold ⏭ N/A factor research scope + item 4 T1.5 sediment ADR ✅ T1.5 closed ADR-065 + item 5 sim-to-real gap 0 复发); Gate C 5 items PASS (Constitution §L10.3, V3 §12.2 mapping to TB-2/TB-3/TB-4 全 closed + L2 Bull/Bear production-active + L2 RAG production-active + L5 RiskReflector 周/月/event cadence ≥1 完整 cycle + lesson→risk_memory 自动入库 + 后置抽查 ≥1 round + ADR-067/068/069/070/071 全 committed); ADR-070 + ADR-071 + Tier B LL append-only sediment review (LL-158~163 cumulative review verify); Tier B ROADMAP doc sediment via Constitution §0.1 line 35 标注 closure (Plan v0.3 横切层 起手 prereq sediment); `quantmind-v3-doc-sediment-auto` skill enforce 4 doc 同步 (Plan v0.2 / Constitution §L10.2 amend / REGISTRY / memory handoff) |
| File delta | ~10-15 files / ~1500-2500 lines (V3 §15.6 ≥7 scenarios fixture + assertion ~500-700 lines + replay 验收 report doc + ADR-070 sediment ~5-8KB + ADR-071 sediment ~5-8KB + Constitution §L10.1 + §L10.2 amend patch ~100-200 lines + Constitution §0.1 line 35 ROADMAP closure 标注 patch ~20-50 lines + REGISTRY rows ~10-20 lines + memory handoff append + ROADMAP doc NEW or 标注 closure ~200-500 lines cumulative) |
| Chunked sub-PR | **chunked 3 sub-PR**: TB-5a (V3 §15.6 ≥7 scenarios fixture + assertion + CI green ~600-800 lines + pytest 体例 sustained) → TB-5b (replay 验收 4 项 PASS + 5 SLA verify run on 2 关键窗口 + ADR-070 sediment + report doc sediment ~400-600 lines + verification evidence) → TB-5c (Gate B + Gate C subagent verify run + ADR-071 cumulative sediment + Constitution §L10.1 + §L10.2 amend patch per Plan v0.2 §G II Push back #1 + #2 + Constitution §0.1 line 35 ROADMAP closure 标注 + Tier B LL append-only review + memory handoff append + Plan v0.3 横切层 起手 prereq sediment ~500-700 lines) |
| Cycle | 1 周 baseline (TB-5a ~0.4 周 + TB-5b ~0.3 周 + TB-5c ~0.3 周); replan trigger 1.5x = 1.5 周 |
| Dependency | 前置: TB-1~4 全 ✅ closed (TB-1 RiskBacktestAdapter full impl + 历史回放 2 关键窗口 + TB-2 MarketRegimeService production-active + TB-3 RiskMemoryRAG production-active + TB-4 RiskReflectorAgent production-active + lesson 闭环 ≥1 cycle) / 后置: Plan v0.3 横切层 起手 prereq (Gate D scope: V3 §13 元监控 + V3 §14 失败模式 12 项 enforce + V3 §17.1 CI lint + prompts/risk eval ≥1 round + LiteLLM cost ≥3 month ≤80% baseline, NOT in Plan v0.2 scope per D4=否 决议) |
| LL/ADR candidate | **ADR-070** ✅ promote (Tier B replay 真测结果 sediment per ADR-063 referenced ADR-XXX, replay path 4 项 acceptance + 5 SLA verify 数值锁); **ADR-071** ✅ promote (Tier B closure cumulative + Gate B + Gate C formal close + Constitution §L10.2 amend per Plan v0.2 §G II + Plan v0.3 横切层 起手 prereq sediment); **LL-163** ✅ promote (Tier B closure 体例 sediment + plan-then-execute Tier B 第 6 sprint case cumulative 实证累积扩 sustainability + Plan v0.2 5 决议 lock 实证落地 plan-then-execute 体例 第 4 case 全链 closure 真值落地实证累积扩 sustainability cumulative pattern 体例文档化 5 case cumulative) |
| Reviewer reverse risk | V3 §15.4 阈值 silent drift on replay path (LL-115, mitigation: ADR-070 sediment 锁 阈值 SHA + diff-aware review); 反 Gate B 5 items silent skip (LL-098 X10, mitigation: tier-a-mvp-gate-evaluator subagent borrow + Tier B variant charter 5 items 全 verify); ADR-070 silent overwrite 反 ADR-022 (sustained append-only); Constitution §L10.2 amend silent overwrite 反 ADR-022 (sustained ADR-022 仅 append 标注 per Plan v0.2 §G II Push back #1 + #2 体例); ROADMAP closure 标注 silent inflate 反 ADR-022 (mitigation: sustained Plan v0.1 §H Finding #1 (b) 体例 仅标注 closure, NOT 创建 ROADMAP 完整 sediment file — 完整 ROADMAP sediment 留 Tier B closure post 横切层 Plan v0.3 scope) |
| 红线 SOP | sustained T1.5; 0 真账户 mutation; LIVE_TRADING_DISABLED sustained throughout Tier B closure; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout TB-5; 0 production yaml mutation |
| Paper-mode | sustained T1.5; Tier B closure → 横切层 prereq (Plan v0.3 起手前 user 显式 trigger sustained LL-098 X10), NOT cutover (cutover 留 Plan v0.4 Gate E scope); replay 验收 走 mock broker/notifier/price reader + 2 关键窗口 historical minute_bars + synthetic ≥7 scenarios fixture, 0 真 live production system contact |

---

## §B Cross-sprint surface risk register

| # | risk | mitigation |
|---|---|---|
| 1 | TB-1 RiskBacktestAdapter full impl silent INSERT path 风险 (LL-115 family + LL-157 mock-conn schema-drift 8/9 实证) | 纯函数契约 audit via SAVEPOINT verify per LL-157 pattern + mock injection contract (BrokerProtocol + NotifierProtocol + PriceReaderProtocol pure stub sustained); LL-159 候选 sediment baseline |
| 2 | TB-2 V4-Pro Judge prompt drift 风险 (LL-115 capacity expansion 真值 silent overwrite) | prompt eval iteration (50 历史 regime case via TB-1 replay sourced) + ADR-067 sediment 锁 prompt v1.yaml SHA + `quantmind-v3-prompt-iteration-evaluator` skill enforce |
| 3 | TB-3 BGE-M3 OOM (V3 §14 #13 sustained) | retrieval skip alert path verify (integration smoke fail-mode injection alert 仍发) + 32GB RAM budget audit (V3 §16.1 sustained ~5GB 风控总常驻 + 7GB buffer 留, BGE-M3 2GB 内可容) |
| 4 | TB-4 lesson→risk_memory 闭环 V4-Flash embed silent fail 风险 (LL-115 + LL-157 family) | DataPipeline fail-loud (铁律 17 + 33 sustained); LL-162 候选 sediment baseline + 4 边界 case prompt eval V4-Pro timeout 必含 |
| 5 | TB-5 V3 §15.4 阈值 silent drift on replay path (LL-115 + ADR-063 transferable scope sustained) | ADR-070 sediment 锁 阈值 + 阈值 CC 实测 baseline + sustained Plan v0.1 §D:271 post-ADR-063 transferable 体例 |
| 6 | LiteLLM 月成本 overshoot (V3 §16.2 ≤ $50/月 sustained) | `quantmind-v3-llm-cost-monitor` skill 月度 cost audit + warn ≥80% + reject ≥100% upper bound STOP; LiteLLM cost 实测 SQL llm_cost_daily aggregate verify per sprint |
| 7 | 5/5 红线 sustained throughout Tier B (cash / 0 持仓 / LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID) | redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout Tier B; 0 .env mutation; CC 自动 PR generate (TB-4) NOT auto-merge sustained |
| 8 | TB-5 dependent on TB-1~4 全 closed | 任 sprint INCOMPLETE → STOP + push user (Constitution §L8.1 (c) sprint 收口决议 + `quantmind-v3-sprint-replan` skill trigger + replan template = 治理债 surface + sub-task creep cite + remaining stage timeline 修订) |
| 9 | sub-PR Plan v0.2 sediment 模板 dependent on Tier B LL/ADR cumulative append-only | sustained governance batch closure pattern (sub-PR cumulative batch promote, ADR-022 反 silent overwrite + 反 retroactive content edit); Plan v0.1 sub-PR 8 体例 sustained 第 4 case 实证累积扩 |
| 10 | 跨 sprint surface — 13 hook + mattpocock + OMC unexpected breakage | sprint 起手 fresh-read SOP (Constitution §L0.3 step (3)); 现 hook 真测 fire log verify (LL-133 sustained); 沿用 Plan v0.1 §B item 10 体例 sustained |
| 11 | sub-task creep 风险 (任 sprint 实际超 baseline 1.5x) | `quantmind-v3-sprint-replan` skill trigger; replan template + push user (沿用 Plan v0.1 §B item 11 体例 sustained); per-sprint cycle replan threshold per §E table |
| 12 | sim-to-real gap 风险 on Tier B replay (PR #210 体例 + LL-159 候选 TB-1) | Constitution §L10.2 Gate B + sustained Tier A 实施期间 0 复发 audit log (LL-098 sub-PR cumulative review sustained) + TB-1c counterfactual analysis output verify "what would V3 alert do? vs actual outcome" |
| 13 | N×N 同步漂移 (LL-101/103/116 cumulative) Plan v0.2 / Constitution §L10.2 / V3 §12.2 / REGISTRY / memory handoff 5 doc | `quantmind-v3-doc-sediment-auto` skill 强制 4 doc 同步; sub-PR closure 闭后 sediment SOP; Plan v0.2 sub-PR sediment cycle 含 5 doc 同步 patch (Plan v0.2 doc + Constitution + skeleton + REGISTRY + ADR-064 + LL-158 + memory handoff) |
| 14 | Tier B vs Tier A scope boundary 混淆 (V3 §11.1 row 1-5 Tier A vs row 6-8 Tier B + RiskBacktestAdapter T1.5 prereq stub Tier A vs full impl TB-1 Tier B) | Plan v0.2 §A T1.5 + TB-1~5 each row 明确 cite Tier B scope; ADR-066 sediment 锁 RiskBacktestAdapter full impl Tier B scope (vs S5 sub-PR 5c 140 行 stub Tier A scope sustained); Plan v0.2 §G III sediment 真值差异 explicit |
| 15 | 5y full replay vs 2 关键窗口 scope creep (D3=b 决议 lock sustained) | TB-1c ADR-066 sediment 锁 2 关键窗口 boundary (2024Q1 量化踩踏 + 2025-04-07 关税 -13.15%); 5y full replay 留 Tier B closure post 横切层 Plan v0.3 scope explicit defer; sustained ADR-022 反 retroactive scope creep |
| 16 | Constitution §L10.2 Gate B item 2 "12 年 counterfactual" vs D3=b 2 关键窗口 drift (Plan v0.2 §G II Push back #1) | Plan v0.2 §C Gate B item 2 标注 "MODIFIED per D3=b 决议" (sustained ADR-022 反 retroactive edit Constitution, 仅 amend Plan v0.2 §C); Constitution §L10.2 amend 留 TB-5c sediment 周期 batch closure pattern |
| 17 | Constitution §L10.2 Gate B item 3 "WF 5-fold" 真值 scope mis-attribution drift (Plan v0.2 §G II Push back #2) | Plan v0.2 §C Gate B item 3 标注 "⏭ N/A — factor research scope, NOT Tier B 风控 scope"; Constitution §L10.2 amend 留 TB-5c sediment 周期 batch closure pattern |
| 18 | Plan v0.2 6 sprint (T1.5 + TB-1~5) vs V3 §12.2 4 sprint (S12-S15) scope 真值差异 (Plan v0.2 §G II Push back #3) | Plan v0.2 §G III sediment 真值差异 explicit: ADR-063 加 TB-1 完整实现 + T1.5 formal close + TB-5 closure; V3 §12.2 mapping to TB-2/TB-3/TB-4/TB-5 sustained per Plan v0.2 §C Gate C item 1 |

---

## §C Tier B closure → 横切层 trigger STOP gate

**Constitution §L10.2 Gate B 5 项 checklist + §L10.3 Gate C 6 项 checklist** (CC 实测每项 via Gate B + Gate C subagent run on TB-5):

### Gate B (T1.5 closure level, Constitution §L10.2)

1. V3 §11.4 `RiskBacktestAdapter` 实现 + 0 broker / 0 alert / 0 INSERT 依赖 verify ✅ (TB-1 full impl, post-ADR-066 sediment, sustained S5 sub-PR 5c 140 行 stub + TB-1 full evaluator)
2. ~~12 年 counterfactual replay 跑通 (沿用 sim-to-real gap audit 体例, V3 §15.5)~~ ⏭ **MODIFIED per D3=b 决议** — 2 关键窗口 (2024Q1 量化踩踏 + 2025-04-07 关税冲击 -13.15%) replay 跑通 ✅ TB-1c; 5y full replay deferred to Tier B closure post 横切层 (Plan v0.3 scope) — Constitution §L10.2 line 411 amend 留 TB-5c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive edit, 仅标注 amend)
3. ~~WF 5-fold 全正 STABLE (沿用 4-12 CORE3+dv_ttm 体例, OOS Sharpe / MDD / Overfit 阈值 sprint 起手时 CC 实测决议)~~ ⏭ **N/A** — factor research scope (Phase 2 factor team CORE3+dv_ttm 2026-04-12 WF PASS 沿用 PT 配置, Tier B 风控独立轨道), NOT Tier B 风控 scope. Constitution §L10.2 line 412 amend 留 TB-5c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive edit, 仅标注 amend)
4. T1.5 sediment ADR ✅ (ADR-065 T1.5 Gate A formal close + Tier A ADR-047~063 cumulative promote)
5. sim-to-real gap finding (PR #210 体例) Tier A + Tier B 实施期间 0 复发 (CC 实测 audit log)

### Gate C (Tier B closure level, Constitution §L10.3)

1. V3 §12.2 Sprint S12-S15 全 closed → mapped to **TB-2 (S12 L2 Bull/Bear) + TB-3 (S13 L2 RAG) + TB-4 (S14 L5 RiskReflector) + TB-5 (S15 ADR sediment + closure)** ✅
2. L2 Bull/Bear regime production-active (Daily 3 次 cadence verify per V3 §20.1 #2) ✅ TB-2c
3. L2 RAG (BGE-M3 + pgvector) production-active + retrieval 命中率 ≥ baseline (V3 §20.1 #3, CC 实测 baseline + ADR-068 sediment 锁) ✅ TB-3c
4. L5 RiskReflector 周/月/event-after cadence ≥1 完整 cycle (V3 §20.1 #4) ✅ TB-4 闭环 + TB-5 verify
5. 反思 lesson → risk_memory 自动入库 + 后置抽查 ≥1 round (V3 §20.1 #9 (c) hybrid) ✅ TB-4c lesson→risk_memory 闭环 + TB-5 抽查
6. ADR-025 (RAG vector store 选型, alias ADR-068 per Plan v0.2 ADR-X mapping) + ADR-026 (Bull/Bear 2-Agent debate, alias ADR-067) + Tier B 后续 ADR (ADR-066/068/069/070/071) 全 committed ✅ TB-5c

### V3 §15.4 4 项 acceptance on Tier B replay path (post-ADR-063 transferable)

1. P0 alert 误报率 < 30% (CC 实测 baseline + ADR-070 sediment 锁 on replay run 2 关键窗口)
2. L1 detection latency P99 < 5s on replay timing instrumentation
3. L4 STAGED 流程闭环 0 失败 on replay flow (sustained Tier A S8 + S9 sub-PR cumulative 8a/8b/8b-cadence/9a/9b 全 production-ready 体例)
4. 元监控 0 P0 元告警 on replay run (risk_metrics_daily aggregate verify)

### V3 §13.1 5 SLA verify on replay path

1. L1 detection latency P99 < 5s (transferable per Plan v0.1 §D:271)
2. L0 News 6 源 30s timeout early-return (transferable on synthetic ≥7 scenarios fixture LLM 服务全挂 case)
3. LiteLLM API 单 call < 3s, fail → Ollama (transferable, sustained LiteLLM router production-ready Tier A S1)
4. DingTalk push < 10s P99 (transferable on synthetic ≥7 scenarios fixture DingTalk 不可用 case)
5. L4 STAGED 30min cancel 窗口 严格 30min (transferable on synthetic ≥7 scenarios fixture user 离线 4h + STAGED 30min timeout case)

**STOP gate**: TB-5 closure → `quantmind-v3-tier-a-mvp-gate-evaluator` subagent (件 5) Tier B variant 借用 charter verify Gate B 5/5 + Gate C 6/6 全 ✅ + V3 §15.4 4/4 PASS + V3 §13.1 5/5 SLA verify → STOP + push user (Constitution §L8.1 (c) sprint 收口决议, sustained LL-098 X10 反 silent self-trigger 横切层 Plan v0.3 起手)

**Plan v0.3 横切层 起手 prereq**: Tier B closure ✅ + 横切层 scope Plan v0.3 起手前 user 显式 ack (sustained Plan v0.1 §F (vi) plan-then-execute 体例 sustainability sustained)

> **✅ Tier B FULLY CLOSED 2026-05-14 (TB-5c, ADR-071)** — STOP gate satisfied: Gate B 5/5 ✅ + Gate C 6/6 ✅ + V3 §15.4 4/4 ✅ + V3 §13.1 5/5 ✅. **Plan v0.3 横切层 NOT auto-started — user 显式 ack required** (sustained LL-098 X10 反 silent self-trigger).
>
> **Plan v0.3 横切层 起手 prereq sediment** (scope carried into Plan v0.3 when user triggers it):
> - **Gate D 横切层 core** (Constitution §L10.4): V3 §13 元监控 `risk_metrics_daily` + alert-on-alert production-active / V3 §14 失败模式 12 项 enforce + 灾备演练 ≥1 round / V3 §17.1 CI lint + pre-push hook 集成 / prompts/risk eval ≥1 round / LiteLLM cost ≥3 month ≤80% baseline
> - **Carried-forward DEFERRALS from Tier B** (need live production query traffic, N/A in paper-mode — sustained ADR-063 paper-mode deferral pattern):
>   - Gate C item 3 sub-item — RAG retrieval 命中率 ≥ baseline measurement (ADR-071 D4)
>   - Gate C item 5 sub-item — lesson→risk_memory 后置抽查 ≥1 live round (ADR-071 D4)
>   - 5y full minute_bars replay (ADR-064 D3=b — Tier B did 2 关键窗口 only)
>   - ADR-067 D5 — `north_flow_cny` + `iv_50etf` MarketIndicators real-data-source wire
>   - `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` full sediment (Constitution §0.1 — Tier B closure REACHED, sediment 时机 now due)
> - **D4 决议 lock sustained** (ADR-064): Plan v0.2 = Tier B scope only; 横切层 = Plan v0.3; cutover = Plan v0.4 Gate E.

---

## §D Tier B RiskBacktestAdapter replay 真测期 SOP

> **post-ADR-063 transferable** (2026-05-13, sustained Plan v0.1 §D body content fully valid for Tier B replay context per ADR-063 §1.5 Evidence) — 原 Tier A S10 wall-clock 5d 上下文已 DEFERRED to Tier B `RiskBacktestAdapter` 历史 minute_bars replay path. 本节 SOP content 沿用 Plan v0.1 §D 体例 transferable (WHAT 不变, WHEN+HOW 换). TB-1 + TB-5 起手时 cite 本节 SOP details.

**RiskBacktestAdapter replay 监控 SOP** (sustained Plan v0.1 §D post-ADR-063 transferable 体例, 替代 Tier A wall-clock 5d):

- 元监控 risk_metrics_daily 0 P0 元告警 (V3 §13.2, on replay run aggregate)
- 5 SLA 满足 verify (V3 §13.1: L1<5s on replay timing instrumentation / News 30s on synthetic LLM 全挂 case / LiteLLM<3s on TB-2/TB-3/TB-4 production call / DingTalk<10s on synthetic DingTalk 不可用 case / STAGED 30min on synthetic user 离线 case) — replay path 等价 transferable per ADR-063 §1.5 + Plan v0.1 §D:271 体例 sustained
- V3 §15.4 验收 4 项 (P0 误报率<30% / L1 P99<5s / L4 STAGED 0 失败 / 元监控 0 P0) on replay path 2 关键窗口
- 数值阈值 TB-5 起手 CC 实测决议 + ADR-070 sediment 锁

**反 silent self-trigger paper→live** (sustained Plan v0.1 §D):

- LIVE_TRADING_DISABLED=true sustained throughout Tier B 全程
- EXECUTION_MODE=paper sustained
- redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce
- paper→live cutover NOT in Plan v0.2 scope, 留 Plan v0.4 cutover gate (Constitution §L10.5)

**Gate E PT cutover gate prereq** (Constitution §L10.5, NOT in Plan v0.2 scope per D4=否 决议, 留 Plan v0.4):

- paper-mode 5d 通过 (Gate A 部分) — ⏭️ post-ADR-063: satisfied by Tier B `RiskBacktestAdapter` replay 等价 path 替代 wall-clock (本 Plan v0.2 TB-1 + TB-5 deliver, sustained Plan v0.1 §D:284 体例)
- 元监控 0 P0 (Gate A 部分) — Tier A code-side closed + 横切层 (Plan v0.3) sediment
- Tier A ADR 全 sediment (Gate A 部分) — T1.5 closure (Plan v0.2 T1.5) sediment ADR-065
- 5 SLA 满足 — Tier B closure (Plan v0.2 TB-5) sediment ADR-070 + 横切层 (Plan v0.3) cumulative verify
- 10 user 决议状态 verify (V3 §20.1, sustained PR #216) — Plan v0.4 scope
- user 显式 .env paper→live 授权 (4 锁: LIVE_TRADING_DISABLED / DINGTALK_ALERTS_ENABLED / EXECUTION_MODE / L4_AUTO_MODE_ENABLED) — Plan v0.4 scope

---

## §E Tier B estimated total cycle

per-sprint baseline cite (Plan v0.2 §A T1.5 + TB-1~5 cumulative):

| Sprint | baseline | replan trigger 1.5x | chunked sub-PR |
|---|---|---|---|
| T1.5 | 3-5 day | 4.5-7.5 day | 2 (T1.5a + T1.5b) |
| TB-1 | 2 周 | 3 周 | 3 (TB-1a + TB-1b + TB-1c) |
| TB-2 | 2 周 | 3 周 | 3 (TB-2a + TB-2b + TB-2c) |
| TB-3 | 1-2 周 | 1.5-3 周 | 3 (TB-3a + TB-3b + TB-3c) |
| TB-4 | 2 周 | 3 周 | 4 (TB-4a + TB-4b + TB-4c + TB-4d) |
| TB-5 | 1 周 | 1.5 周 | 3 (TB-5a + TB-5b + TB-5c) |

**Tier B total**: ~8.5-12 周 baseline (含 buffer), replan 1.5x = ~13-18 周. vs V3 §12.2 原 ~4-5 周 — 因为 ADR-063 加 TB-1 完整实现 (V3 §12.2 原 仅 stub T1.5 prereq) + TB-5 replay 验收 net new scope (post-ADR-063) + T1.5 formal close net new scope (Gate A 7/8 verify + Tier A ADR cumulative).

**V3 实施期总 cycle 真值再修订** (post Plan v0.2 sediment, sustained sub-PR 9 V2 prior cumulative cite + ADR-063 sediment):

- Tier A 真 net new ~3-5 周 (V2 prior cumulative S1/S4/S6/S8 substantially pre-built per sub-PR 9 sediment 体例) ✅ 已 closed Session 53 cumulative 19 PR
- T1.5 Plan v0.2 = 3-5 day
- Tier B Plan v0.2 = 8.5-12 周
- 横切层 Plan v0.3 = ≥12 周 (Plan v0.1 §E cite sustained)
- cutover Plan v0.4 = 1 周
- **真值 estimate (post Plan v0.2 sediment)**: Tier A ~3-5 + T1.5 3-5 day + Tier B 8.5-12 + 横切层 ≥12 + cutover 1 = **~25-30 周** (~6-7 月)
- replan trigger 1.5x = ~37-45 周 (~9-11 月)

**replan trigger condition** (Constitution §L0.4): 任 sprint 实际超 baseline 1.5x → STOP + push user; `quantmind-v3-sprint-replan` skill (件 3) trigger; replan template = 治理债 surface + sub-task creep cite + remaining stage timeline 修订

---

## §F Plan review trigger SOP (sustained, post Plan v0.2 user approve)

**Plan output → STOP + 反问 user** (反 silent self-trigger T1.5, sustained LL-098 X10 + Constitution §L8.1 (a) 关键 scope 决议, sustained Plan v0.1 §F 体例):

**user options** (sustained Plan v0.1 §F workspace plan review):

- **(i)** approve plan as-is → T1.5 起手 (CC exit plan mode → sprint 实施 cycle, Constitution §L0.3 5 step verify + V3_LAUNCH_PROMPT §3.1 SOP, sustained Plan v0.1 §F (i) 体例)
- **(ii)** sprint 顺序修订 (e.g. TB-1 / TB-2 顺序换 / T1.5 与 TB-1 并行 D1=b 反 决议 / TB-3 提前 TB-2)
- **(iii)** scope 拆分 (e.g. TB-1 chunked 进一步拆 (3 → 4) / TB-4 chunked 进一步拆 (4 → 5))
- **(iv)** chunked sub-PR 体例修订 (sustained sub-PR 8 chunked precedent + LL-100)
- **(v)** skip 某 sprint (e.g. T1.5 skip 直接 TB-1 / TB-2 skip if Bull/Bear scope 决议 NO-GO / TB-4 skip if RiskReflector 决议 deferred Plan v0.3 横切层)
- **(vi)** 其他修订 — ✅ accepted, plan-then-execute 体例 sub-PR sediment cycle (本文件 sediment)

**user 显式 trigger T1.5 起手** → CC exit plan mode → sprint 实施 cycle (sustained per-sprint cycle 体例)

---

## §G 主动思考 (sustained LL-103 SOP-4 反 silent agreeing)

### (I) 5 决议 lock sediment 反思

**D1=a 串行 lock** (T1.5 → TB-1):

- ✅ Gate A 7/8 PASS 是 ADR-063 sustained 的前提 (Tier A 形式 close 完整, Tier B 不带 Tier A debt 进场)
- ✅ 干净 phase transition + sub-PR 8 plan-then-execute 体例 sustainability sustained
- ⚠️ trade-off: 多 ~3-5 day vs 并行 — accept (干净 phase 更稳, sub-task creep 风险 lower, sustained Plan v0.1 §B item 11 sub-task creep mitigation 体例)

**D2=A BGE-M3 lock**:

- ✅ 32GB RAM budget verify (V3 §16.1: 风控总常驻 ~5GB + buffer 7GB 留, BGE-M3 2GB 内可容)
- ✅ 0 cost advantage + 中文优化 + 1024 维 retrieval 命中率 baseline (V3 §5.4 line 712-714 option A sustained)
- ⚠️ trade-off: 部署复杂度 (docker container OR conda env, CC 实测决议 + ADR-068 sediment 锁) vs LiteLLM API 0 部署 — accept (V3 §16.2 上限 ≤$50/月 sustained, BGE-M3 0 cost 内含足, 沿用 V3 §16.2 line 1591 RAG ingest ~$1-2/月 候选 LiteLLM API B 选项 reject)
- ⚠️ V3 §14 #13 sustained: BGE-M3 OOM → retrieval skip alert path verify (TB-3c acceptance, integration smoke fail-mode injection alert 仍发)

**D3=b 2 关键窗口 lock** (vs 5y full):

- ✅ TB-1 cycle 2 周 baseline reasonable (5y full ~191M rows × 2537 stocks × 9 rules wall-clock 估 ~1-2 周 仅 replay run + 不含 evaluator + counterfactual framework)
- ✅ 5y full replay 留 Tier B closure post 横切层 (Plan v0.3 scope) — 横切层 V3 §13 元监控 + V3 §14 12 失败模式 + V3 §17.1 CI lint + LiteLLM cost ≥3 month 完整, 5y full replay 提供 long-tail acceptance
- ⚠️ trade-off: 2 关键窗口 (~2-4M rows) vs 5y full (~191M rows) — accept (2 关键窗口 cover regime 极端 case 充分: 2024Q1 量化踩踏 + 2025-04-07 关税冲击 -13.15%, TB-1 acceptance baseline 不需 full)

**D4=否 Plan v0.2 仅 Tier B scope lock** (vs 含 横切层 + cutover):

- ✅ sustained Plan v0.1 体例每 Tier 独立 plan (v0.1 = Tier A, v0.2 = Tier B, v0.3 = 横切层, v0.4 = cutover)
- ✅ 每 plan 可独立 user approve + sediment + replan
- ⚠️ trade-off: Plan v0.3 / v0.4 起手前需 user 显式 trigger — sustained LL-098 X10 反 silent self-trigger sustainability sustained

**D5=inline 完整 lock**:

- ✅ sustained Plan v0.1 54KB 体例 inline 完整 (sub-PR 8 sediment 体例 sustainability)
- ✅ 单 plan doc 单 file 易 cite + REGISTRY row + memory handoff 同步 (反 N×N 漂移 LL-101/103/116)
- ⚠️ trade-off: Plan v0.2 ~40-50KB single Write call — accept (chunked SOP per LL-100 applies to PR-level, NOT file-write-level; Plan v0.2 sub-PR sediment 1 PR single commit 沿用 Plan v0.1 sub-PR 8 体例 sustained)

### (II) CC-domain push back

**Push back #1 — Constitution §L10.2 Gate B 项 2 "12 年 counterfactual replay" vs D3=b 2 关键窗口 drift detect**:

- Constitution §L10.2 line 411 cite "12 年 counterfactual replay 跑通 (沿用 sim-to-real gap audit 体例, V3 §15.5)"
- D3=b decision (本 Plan v0.2 ack): 2 关键窗口 (2024Q1 + 2025-04-07) — NOT 12 年 full
- **Drift type**: scope 真值漂移 (Constitution §L5.2 5 类漂移 #2)
- **Drift impact**: TB-1 cycle baseline 真值 (2 周 vs 12 年 full replay 估 ~1-2 周 仅 replay run, scope different)
- **决议候选** (本 Plan v0.2 §C Gate B item 2 标注 "MODIFIED per D3=b 决议") — sediment 时 amend Constitution §L10.2 line 411 留 TB-5c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive edit, 仅标注 amend)

**Push back #2 — Constitution §L10.2 Gate B 项 3 "WF 5-fold 全正 STABLE" 真值 scope mis-attribution drift detect**:

- Constitution §L10.2 line 412 cite "WF 5-fold 全正 STABLE (沿用 4-12 CORE3+dv_ttm 体例, OOS Sharpe / MDD / Overfit 阈值 sprint 起手时 CC 实测决议)"
- 真值: WF 5-fold = factor research scope (Phase 2 factor team CORE3+dv_ttm 2026-04-12 已 PASS 沿用 PT 配置), NOT Tier B 风控 scope (Tier B 风控独立轨道, sustained Plan v0.2 §A scope cite)
- **Drift type**: scope 真值漂移 (Constitution §L5.2 5 类漂移 #2) + cross-domain attribution (factor research vs 风控)
- **决议候选** (本 Plan v0.2 §C Gate B item 3 标注 "⏭ N/A — factor research scope, NOT Tier B 风控 scope") — sediment 时 amend Constitution §L10.2 line 412 cite scope 标注 留 TB-5c sediment 周期

**Push back #3 — Plan v0.2 6 sprint (T1.5 + TB-1~5) vs V3 §12.2 4 sprint (S12-S15) scope 真值差异 detect**:

- V3 §12.2 cite S12-S15 4 sprint (~4-5 周 baseline)
- Plan v0.2 §A cite T1.5 + TB-1 + TB-2 + TB-3 + TB-4 + TB-5 6 sprint (~8.5-12 周 baseline) ≈ S12-S15 mapping (TB-2 ≈ S12 / TB-3 ≈ S13 / TB-4 ≈ S14 / TB-5 ≈ S15) + TB-1 完整 RiskBacktestAdapter NOT in V3 §12.2 原 + T1.5 NOT in V3 §12.2 原
- **Drift type**: scope 真值差异 + capacity expansion (post-ADR-063 加 TB-1 完整实现 + T1.5 formal close net new)
- **决议候选** (本 Plan v0.2 §G III sediment 真值差异: ADR-063 加 TB-1 完整实现 + T1.5 formal close net new scope, V3 §12.2 mapping to TB-2/TB-3/TB-4/TB-5 sustained per Plan v0.2 §C Gate C item 1)

### (III) Long-term + 二阶 / 三阶 反思

**V3 实施期 Tier B plan phase 修订 6 月后 governance 演化 sustainability**:

- sustained sub-PR 1-8 governance pattern (Plan v0.1 sub-PR 8 sediment 体例) + 本 Plan v0.2 plan-then-execute 体例 实证累积扩 plan-then-execute 体例 sustainability cumulative 第 4 case (case 1 Plan v0.1 5-09 + case 2 sub-PR 11b 5-09 + case 3 sub-PR 13 5-09 + case 4 本 Plan v0.2 5-13)
- Tier B 6 sprint baseline 真值落地 sustainability — Tier B 8.5-12 周 cycle + replan trigger 1.5x = 13-18 周 reasonable scope
- V3 实施期总 cycle ~25-30 周 修订真值落地 sustainability — sustained Tier A code-side ~3-5 + T1.5 + Tier B + 横切层 + cutover 完整 chain sediment

**5 决议 lock 体例 LL/ADR sediment sustainability**:

- D1=a / D2=A / D3=b / D4=否 / D5=inline 5 决议 lock via Plan v0.2 §G I sediment + ADR-064 sediment 锁 (新 ADR # CC sprint 起手时实测决议, sustained ADR-022 + LL-105 SOP-6 ADR # registry SSOT)
- 沿用 Plan v0.1 5 user 决议 (Finding #1/#2/#3 + Push back #1/#2/#3) 累积扩 cumulative pattern 6 项决议 (Plan v0.1) + 5 项决议 (Plan v0.2) = 11 项决议 cumulative sediment

### (IV) Governance/SOP/LL/ADR candidate sediment

- **plan-then-execute 体例 Tier B context LL/ADR 候选 sediment** — promote 时机决议 Plan v0.2 user approve → T1.5 起手 trigger 后 OR alternative direction (本 sub-PR sediment cycle 体例 sustained)
- **5 决议 lock 体例 ADR-064 候选** (sustained ADR-022 + LL-105 SOP-6 ADR # registry SSOT, 本 sub-PR sediment)
- **Constitution §L10.2 amend candidate** (Gate B 项 2 + 项 3 per D3=b + WF scope drift) — 留 TB-5c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)
- **sub-PR sediment 体例 hybrid 决议 SOP LL 候选** (sustained Plan v0.1 sub-PR 8 + 本 Plan v0.2 sediment 体例真值落地实证累积扩 cumulative pattern 体例文档化候选 LL-158 promote 本 sub-PR sediment)

---

## §H Phase 0 active discovery findings (sustained LL-115 enforce + Constitution §L5.3, 全 ✅ user 决议 sediment)

### Finding #1: "和我假设不同" — Constitution §L10.2 Gate B 项 2 "12 年 counterfactual replay" vs D3=b 2 关键窗口 ✅ user 决议 (lock D3=b) sediment

**Cite drift detect**:

- Constitution §L10.2 line 411 cite "12 年 counterfactual replay 跑通"
- D3=b decision (本 Plan v0.2 ack): 2 关键窗口 — NOT 12 年 full
- **Fresh verify** (本 plan, 2026-05-13): Constitution §L10.2 line 411 真值 cite "12 年" vs D3=b 真值 "2 关键窗口"
- **类型**: scope 真值漂移 (Constitution §L5.2 5 类漂移 #2)
- **影响**: TB-1 cycle baseline 真值 (2 周 vs 12 年 full replay 估 ~1-2 周 仅 replay run, scope different)

**user 决议** ✅ (D3=b lock) accepted:

- Plan v0.2 §C Gate B item 2 标注 "MODIFIED per D3=b 决议" (反 silent overwrite ADR-022, 仅 amend Plan v0.2 §C, NOT retroactive edit Constitution §L10.2)
- Constitution §L10.2 line 411 amend 留 TB-5c sediment 周期 (sustained sub-PR 8 sediment 体例 batch closure pattern, sustained Plan v0.1 §H Finding #1 (b) 体例 batch sediment)

### Finding #2: "prompt 没让做但应该做" — Constitution §L10.2 Gate B 项 3 "WF 5-fold" 真值 scope mis-attribution ✅ user 决议 (lock N/A) sediment

**Drift**:

- Constitution §L10.2 line 412 cite "WF 5-fold 全正 STABLE" 真值 = factor research scope (Phase 2 CORE3+dv_ttm 2026-04-12 WF PASS sustained PT 配置), NOT Tier B 风控 scope (Tier B 风控独立轨道)
- silent miss 风险 (LL-115 capacity expansion 真值 silent overwrite 体例) — Tier B 风控 closure 验收 silent assume factor research WF 5-fold 真值

**user 决议** ✅ (lock N/A) accepted:

- Plan v0.2 §C Gate B item 3 标注 "⏭ N/A — factor research scope, NOT Tier B 风控 scope"
- Constitution §L10.2 line 412 amend 留 TB-5c sediment 周期 (sustained sub-PR 8 体例 + Plan v0.1 §H Finding #2 (b) 体例 batch sediment)

### Finding #3: "prompt 让做但顺序错 / 有更好做法" — Plan v0.2 sub-PR sediment 体例 chunked 真值 ✅ user 决议 (D5=inline lock) sediment

**Drift**: Plan v0.2 sub-PR sediment 体例 candidate:

- (a) 单 sub-PR sediment (sustained Plan v0.1 sub-PR 8 体例)
- (b) 分章节 phased sediment (反 sub-PR 8 precedent)
- (c) 5 决议 lock 体例 inline 完整 (sustained ADR-064 sediment 锁)

**user 决议** ✅ (D5=inline lock + sub-PR sediment 单 PR) accepted:

- 本 Plan v0.2 ~40-50KB inline 完整 single Write call, single PR sediment (Plan v0.2 doc + Constitution amend (header v0.8 → v0.9, NOT §L10.2 amend — §L10.2 amend 留 TB-5c batch closure) + skeleton amend (header v0.7 → v0.8 + §2.2 Tier B sprint chain row) + REGISTRY row + memory handoff + ADR-064 + LL-158, sustained Plan v0.1 sub-PR 8 precedent 体例 7 file delta 累积扩 7 file delta sustained)
- chunked SOP per LL-100 applies to TB-1~5 sub-PR level (TB-1 chunked 3 / TB-2 chunked 3 / TB-3 chunked 3 / TB-4 chunked 4 / TB-5 chunked 3 cumulative)

---

## §I Sub-PR (Plan v0.2 sediment) cycle (本文件 sediment trigger)

Sub-PR (Plan v0.2 sediment) cycle = post Plan v0.2 user approve (D1=a / D2=A / D3=b / D4=否 / D5=inline) → CC 实施 → ~7 file delta atomic 1 PR (sustained Plan v0.1 sub-PR 8 sediment 体例 cumulative scope 实证累积扩):

| # | file | scope | line delta |
|---|---|---|---|
| 1 | `docs/V3_TIER_B_SPRINT_PLAN_v0.1.md` (本文件) | NEW root level file, content = Plan v0.2 inline 完整 (post 5 决议 lock + 主动思考 sediment + Phase 0 active discovery + sub-PR cycle 沉淀) | NEW file ~40-50KB |
| 2 | [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) | header v0.8 → v0.9 + §0.1 line 35 ROADMAP cite 标注 sustained (NOT amend §L10.2 — §L10.2 amend 留 TB-5c batch closure 周期) + 5 doc list (§0.1 SSOT 锚点) 加 Plan v0.2 cite link + version history v0.9 entry append | edit + append |
| 3 | [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) | header v0.7 → v0.8 + §2.2 NEW Tier B sprint chain (T1.5 + TB-1~5) row 体例 (sustained §2.1 Tier A sprint chain row 体例 sustained) + version history v0.8 entry append | edit + append |
| 4 | [docs/adr/REGISTRY.md](adr/REGISTRY.md) | ADR-064 NEW row (Plan v0.2 5 决议 lock + Tier B sprint chain plan sediment), ADR-065~071 reserved row cumulative sediment | edit + append |
| 5 | `docs/adr/ADR-064-v3-tier-b-plan-v0-1-5-decisions-lock.md` | NEW file, content = 5 决议 (D1=a / D2=A / D3=b / D4=否 / D5=inline) lock rationale + cumulative cite (Plan v0.2 §A acceptance + §G I sediment + §H Finding) | NEW file ~5-8KB |
| 6 | [LESSONS_LEARNED.md](../LESSONS_LEARNED.md) | LL-158 append (Tier B plan-then-execute 体例 第 4 case sediment + Plan v0.1 sub-PR 8 体例 cumulative scope 实证累积扩 sustainability) | append |
| 7 | `memory/project_sprint_state.md` | Session 53+1 handoff 顶部 update (Plan v0.2 user approved + 5 决议 lock + T1.5 起手 prereq + cumulative cite Plan v0.1 sub-PR 8 体例) | edit + append |

Sub-PR (Plan v0.2 sediment) closure → Tier B T1.5 sprint 起手 prerequisite 全 satisfied (post-Plan v0.2 5 决议 lock 真值落地) → §F (vi) plan review trigger SOP STOP gate before T1.5 起手 sustained (LL-098 X10).

---

## maintenance + footer

### 修订机制 (沿用 ADR-022 集中机制)

- 新 Tier B sprint sediment / 新 user 决议 / 新 V3 设计扩展 → 1 PR sediment + Plan v0.2 同步 update + 自造 skill / hook / subagent 同步 update
- LL append-only (反 silent overwrite, sustained ADR-022)
- ADR # registry SSOT (LL-105 SOP-6) sub-PR 起手前 fresh verify
- Plan v0.2 fresh read SOP (本文件 §H + sustained Constitution §L1.1 9 doc fresh read SOP) 跟 SESSION_PROTOCOL §1.3 同步 update
- Constitution §L10.2 amend (Gate B item 2 + item 3 per Plan v0.2 §G II Push back #1 + #2) 留 TB-5c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)

### 版本 history

- **v0.1 (initial draft, 2026-05-13)**: Plan v0.2 Tier B sprint chain (T1.5 + TB-1 + TB-2 + TB-3 + TB-4 + TB-5, 6 sprint) + 5 决议 lock (D1=a 串行 / D2=A BGE-M3 / D3=b 2 关键窗口 / D4=否 仅 Tier B / D5=inline 完整) + cycle baseline ~8.5-12 周 + cross-sprint risk register 18 项 + Gate B 5 项 + Gate C 6 项 criteria + Tier B replay 真测期 SOP (post-ADR-063 transferable) + plan review trigger SOP. 沿用 Plan v0.1 sub-PR 8 sediment 体例 (post-Tier A code-side 12/12 closure cumulative Session 53 cumulative + ADR-063 sediment 真值落地 plan-then-execute 体例 实证累积扩 第 4 case 全链 closure 真值落地实证累积扩 sustainability cumulative pattern 体例文档化 cumulative pattern 五段累积扩).

---

## §J Cumulative cite footer (Plan v0.2 sediment, sustained Plan v0.1 体例 + Constitution §L10 footer 体例)

**Plan v0.2 sub-PR sediment cumulative cite** (sustained Plan v0.1 sub-PR 8 cumulative cite 体例 + sub-PR 9-19 cumulative scope sediment 五段累积扩):

- **plan-then-execute 体例 sustainability cumulative scope**: case 1 Plan v0.1 5-09 sub-PR 8 + case 2 sub-PR 11b 5-09 + case 3 sub-PR 13 5-09 + case 4 本 Plan v0.2 5-13 (Tier B context) cumulative pattern 体例文档化 4 case 实证累积扩 sustainability sustained
- **5 决议 lock 体例 cumulative**: D1=a / D2=A / D3=b / D4=否 / D5=inline 5 项决议 lock via Plan v0.2 §G I sediment + ADR-064 sediment 锁 + LL-158 promote 本 sub-PR sediment cumulative
- **Tier B 期 ADR sediment cumulative**: ADR-064 (本 sub-PR) + ADR-065 (T1.5) + ADR-066 (TB-1) + ADR-067 (TB-2) + ADR-068 (TB-3) + ADR-069 (TB-4) + ADR-070 (TB-5 replay 真测结果) + ADR-071 (TB-5 Tier B closure cumulative) — 8 项 Tier B ADR cumulative sediment
- **Tier B 期 LL sediment cumulative**: LL-158 (本 sub-PR) + LL-159 (TB-1 sim-to-real gap) + LL-160 (TB-2 V4-Pro Bull/Bear prompt iteration) + LL-161 (TB-3 BGE-M3 latency/RAM 实测) + LL-162 (TB-4 RiskReflector 4 边界 case prompt eval) + LL-163 (TB-5 Tier B closure 体例 sediment) — 6 项 Tier B LL cumulative sediment
- **Constitution amend pending TB-5c batch closure**: §L10.2 line 411 item 2 amend per D3=b + line 412 item 3 amend per N/A scope (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例 留 TB-5c sediment 周期 batch closure pattern)
- **5/5 红线 sustained throughout Plan v0.2**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 (sustained Plan v0.1 §I cumulative cite 体例 + redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout Plan v0.2 sediment cycle)
