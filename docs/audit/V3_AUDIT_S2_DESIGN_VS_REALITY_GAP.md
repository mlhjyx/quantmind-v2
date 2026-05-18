# V3 Audit Section II Sub-doc — Design vs Implementation Gap (NEW v8, 2026-05-18 evening)

> **Source**: Subagent B Part 2-3 (Design vs Implementation Gap Analysis + Bidirectional Traceability)
> **Parent**: `V3_AUDIT_S2_INVENTORY.md` §6 Doc Inventory
> **Plan v8 trigger**: User "docs 中很多文档, 你需要梳理设计文档中的设计, 哪些是实施了, 哪些没有实施, 然后需要判断哪些设计是需要纳入后续工作的, 需要深度思考哪些设计是有价值的但没有实施的"
> **Method**: For each design doc, read first ~80 lines, sample 5-10 design claims, grep code验证存在. Score IMPLEMENTED %.
> **Heuristic #20** (NEW v8): Design-Implementation Reverse Mapping — bidirectional trace

---

## §1 Design vs Implementation Gap Analysis (20 Priority Design Docs)

| # | Design doc | Lines | IMPL % | Valuable-but-未实施 (top 3) | Recommendation |
|---|---|---|---|---|---|
| 1 | `DEV_BACKEND.md` | ~1200+ | **60%** | (1) 7 个设计 Service 接口签名漂移；(2) Phase C 重构未在 doc 刷新；(3) Engine 层"纯计算"边界未全闭合 | **(d) merge** with SYSTEM_BLUEPRINT (CLAUDE.md 已声明 SSOT) |
| 2 | `DEV_BACKTEST_ENGINE.md` | ~900 | **70%** | (1) Rust 加速→声明不存在；(2) VectorizedBacktester archived；(3) 12年 OOS 验证 ✅ | (c) archive §一-§十 历史章节,保留 §0 |
| 3 | `DEV_FACTOR_MINING.md` | ~800 | **55%** | (1) Gate G9/G10 register 硬门 (MVP 3.5 ✅);(2) Engine 1-4 并行 → 实际仅 GP+LLM Agent 三件套；(3) Engine 3 LLM Agent 闭环 partial | (b) revisit post Plan v0.4 closure |
| 4 | `DEV_FRONTEND_UI.md` | ~600+ | **45%** | (1) 12 页面 + AI 助手面板未全 wire；(2) WebSocket 5 通道 → 仅 partial；(3) Figma 改进清单 15 项进度未刷 | **(a) implement now** (Wave 5 Operator UI per ADR-012) |
| 5 | `DEV_SCHEDULER.md` | ~400 | **25%** | (1) T1-T17 大部分未实施；(2) FX1-FX11 全 deferred；(3) Celery Beat + Windows Task Scheduler 双轨 partial | (d) merge with `SCHEDULING_LAYOUT.md` |
| 6 | `DEV_PARAM_CONFIG.md` | ~600 | **25%** | (1) Level 3 AI 自动调 14 参数 (0% 实施);(2) GP 13 参数前端面板 ⏸；(3) 220 参数已 D5 决议裁剪 50+30 | (c) archive 设计 220 参数, 保留 §1 四级控制 + 当前 50 核心 |
| 7 | `DEV_AI_EVOLUTION.md` | 705 | **25%** ⚠️ | (1) AILoopOrchestrator 8 节点状态机 (无中枢);(2) Feature Map 策略种群矩阵 (Grep 0 hits);(3) Layer 4 Risk Budgeting riskfolio-lib (Grep 0 backend hits) — **#2 design Orphan + #14** | (b) revisit Q3-Q4 — AI 闭环价值高但 PT 重启优先 |
| 8 | `DEV_FOREX.md` | 682 | **0%** ⚠️⚠️ | (1) MT5 Adapter (Windows FastAPI 网关);(2) 14 对品种数据接入;(3) 4 层 14 项风控 — **全 0% implementation, Grep 0 backend hits** | (c) archive — A股 PT 稳态前不启动, 文档作 reference. **P1-37** |
| 9 | `DEV_NOTIFICATIONS.md` | ~300 | **35%** | (1) 25+ 通知模板 partial;(2) 邮件/微信推送 ⏸；(3) WebSocket `/ws/notifications` ⏸ | (b) revisit Q3-Q4 (Wave 4 4.1 batch 3.x 中已 partial wire) |
| 10 | `GP_CLOSED_LOOP_DESIGN.md` | ~600 | **40%** | (1) GP 适应度 = SimBroker Sharpe (实际仍用 IC proxy);(2) Pipeline 8 节点状态机 (代码已 partial);(3) AlphaAgent KDD 2025 范式 (LLM prompt 改造未实施) | (b) revisit post Plan v0.4 closure — GP 闭环价值高 |
| 11 | `RISK_CONTROL_SERVICE_DESIGN.md` | ~400 | **50%** | (1) L1-L4 升级 / 恢复规则 (state machine ✅);(2) **L4 STAGED 在 V3 ADR-027 重定义 — Drift heuristic #1 CRITICAL**;(3) recovery approval_queue ⏸ | **(d) merge with V3 ADR-027 + 删除原 L1-L4 升级冲突**. **P0-18** |
| 12 | `ML_WALKFORWARD_DESIGN.md` | 1096 | **50%** | (1) 第 1-2 fold OOS 强制 retrain;(2) Optuna 多目标 (RankIC + Sharpe + Stability);(3) DSR 校正 — ML 作为独立策略 NO-GO sediment in research-kb | (e) deprecate ML-as-independent-strategy 章节, 保留 WF 框架作 PortfolioNetwork 融合层未来 |
| 13 | `QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | 巨型 | **85%** | (1) Gate E DINGTALK_ALERTS_ENABLED + L4_AUTO_MODE_ENABLED sustained OFF;(2) §20.4 4 V4 candidates open;(3) §20.1 10/10 ✅ closed | (a) implement now CT-2 final cutover, post LL-183 incident closeout |
| 14 | `V3_IMPLEMENTATION_CONSTITUTION.md` | ~2000 | **95%** | (1) §L10 5-gate enforcement: Gate E partial (CT-2c-pre operational fix in flight);(2) Step 10b sediment deferred post-Monday;(3) ADR-082 reserved | (a) implement now — 闭 Gate E formal close, LL-183 incident handling priority |
| 15 | `V3_PT_CUTOVER_PLAN_v0.1.md` (v0.4) | ~700+ | **90%** | (1) CT-2 Gate E formal verify + .env paper→live + go-live 监控;(2) 14:30 Beat decision;(3) `LL-183` pre-push regression gate completed Mon AM | (a) implement now — LL-183 incident handling priority |
| 16 | `QUANTMIND_PLATFORM_BLUEPRINT.md` (QPB v1.16) | ~1600 | **80%** | (1) Wave 4 4.1 batch 3.x 17 scripts SDK migration in-flight;(2) Wave 4 4.2/4.3/4.4 ⏸；(3) Wave 5+ Operator UI (ADR-012) ⏸ | (a) implement now — Wave 4 closure 进行中 |
| 17 | `QUANTMIND_V2_SYSTEM_BLUEPRINT.md` | 791 | **85%** | (1) §17 AI闭环作为 Application 部分 implemented;(2) §11 GP Pipeline 8 节点 partial；(3) §13 监控 dashboard partial | (a) implement now —唯一设计真相源,持续 maintain |
| 18 | `V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` | ~500 | **100%** | 0 (6 件套全 closed) | (a) maintain — V3 实施期 LAST plan |
| 19 | Latest MVP (Wave 4 4.1) | ~200 | **60%** | (1) PostgresAlertRouter ✅;(2) MetricExporter ✅;(3) AlertRulesEngine ✅;(4) batch 3.x 17 scripts SDK migration 🟡 | (a) implement now |
| 20 | `SETUP_DEV.md` | ~200 | **100%** | 0 | (a) maintain — bootstrap doc |

---

## §2 Per-Doc Deep Dive (Top 5 Most Divergent)

### §2.1 `DEV_FOREX.md` (0% / 682 lines) — heuristic #2 Design Orphan, P1-37

Grep `MT5|ECMarkets|forex_bars|forex_swap_rates` → **0 backend hits**.
- 14 对品种 / 93 strategic decisions / Phase 2 完整设计,代码完全不存在
- **Recommendation (c) archive**: 文件移至 `docs/archive/`, CLAUDE.md §当前进度 标注 "外汇模块 = Phase 2+, A股稳态前不启动"
- 节省 cold-start cognitive load

### §2.2 `DEV_AI_EVOLUTION.md` (25% / 705 lines) — Drift + Partial, P1-38

V2.1 设计 Layer 1-4 + Orchestrator 8 节点闭环. Grep 命中:
- Layer 2 Trajectory Engine: `idea_agent.py` / `factor_agent.py` / `eval_agent.py` ✅ (4 files)
- Layer 3 Feature Map: **0 hits** ⏸
- Layer 4 Risk Budgeting `riskfolio`: **0 hits** ⏸
- Orchestrator 8 节点状态机: **0 中枢实现** ⏸

价值高 (per memory `feedback_research_actionable`), 但 PT 重启 (Plan v0.4) priority 更高.

### §2.3 `DEV_FRONTEND_UI.md` (45% / ~600 lines) — Drift

设计 57 endpoints,实际 96 endpoints (header 自标注). 设计 5 WebSocket 通道,Grep `socket.io|websocket` → partial. Wave 5 (ADR-012) 已规划 Operator UI 重做.

### §2.4 `DEV_PARAM_CONFIG.md` (25% / ~600 lines) — Oversized, P1-40

220 参数设计 vs 实际在用 ~50 (D5 决议). Level 3 AI 自动调 14 参数 0% 实施. 文档与现实差距大.

### §2.5 `RISK_CONTROL_SERVICE_DESIGN.md` (50%) — CRITICAL Conflict with V3 ADR-027, P0-18

L4_STOPPED 旧设计 = 停止所有交易 + 人工审批.
V3 ADR-027 重定义 L4 = STAGED 默认 + 反向决策权 + 跌停 fallback.
**Forward design vs Backward implementation 存在 semantic conflict** — heuristic #1 Drift CRITICAL.

---

## §3 Bidirectional Traceability Spot Check (Heuristic #20)

### §3.1 Forward (Design → Code) — 5 Design Claims from `DEV_AI_EVOLUTION.md`

| Design claim | Code anchor exists? | Notes |
|---|---|---|
| §二-A AILoopOrchestrator state machine | ❌ NO | Grep 0 hits; engine_selector.py 仅工具不是 state machine |
| Layer 1 ic_monitor / rolling_wf / pt_daily_summary | ✅ YES | scripts/monitor_factor_ic.py / scripts/run_rolling_wf.py 实际有 |
| Layer 2 Idea / Factor / Strategy / Eval Agent | 🟡 PARTIAL | idea_agent / factor_agent / eval_agent ✅; strategy_agent ❌ |
| Layer 3 Feature Map (RANKING/FAST/EVENT/MODIFIER × 风险/市值) | ❌ NO | 0 hits — heuristic #14 Documentation Lying |
| Layer 4 riskfolio-lib quarterly rebalance | ❌ NO | Grep `riskfolio` 0 backend hits — heuristic #14 |

### §3.2 Backward (Code → Design) — 5 Core Code Modules → Which Design Doc?

| Code module | Design doc cite? | Notes |
|---|---|---|
| `backend/engines/broker_qmt.py` | 🟡 PARTIAL — V3 `RISK_FRAMEWORK_V3` + ADR-027/059 reference | Original 设计 doc 缺失,只在 CLAUDE.md §xtquant 提到 |
| `backend/app/services/execution_service.py` | 🟡 — `DEV_BACKEND.md §3.1` Router→Service→Engine 通用规范,无专 spec | 缺 ExecutionService 详细 design doc |
| `backend/engines/paper_broker.py` | ❌ NO design doc | 仅在 DEV_BACKTEST_ENGINE.md §0 间接提到 SimBroker; PaperBroker 是 V3 cutover wire,缺独立 spec — **heuristic #20 Code Orphan**. P1-39 |
| `backend/engines/factor_engine/` (package) | 🟡 — Phase C 重构后 `DEV_FACTOR_MINING.md:3` 注 "已过时" | 重构未刷新设计 doc |
| `backend/qm_platform/risk/realtime/engine.py` (RealtimeRiskEngine) | ✅ YES — `QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md §4` + ADR-029/054 | V3 设计 traceable |

### §3.3 New P0 (Heuristic #20 Backward — Code Orphan)

Grep `class.*Broker|broker_qmt|paper_broker` 返回 43 files, 其中:
- `backend/engines/paper_broker.py` + `backend/engines/base_broker.py` → 缺独立设计 doc
- `backend/qm_platform/signal/router.py` (SignalRouter) → 缺独立设计 doc

---

## §4 Top 10 Findings (Sediment-Ready)

| # | Finding | Severity | Heuristic | Recommendation |
|---|---|---|---|---|
| 1 | `RISK_CONTROL_SERVICE_DESIGN.md` L4 vs V3 ADR-027 L4 STAGED semantic conflict | **P0** | #1 | Merge old doc → archive + V3_DESIGN §4 inline complete L1-L4 |
| 2 | `DEV_AI_EVOLUTION.md` Layer 3 Feature Map / Layer 4 Risk Budgeting Grep=0 但 doc 705 lines | **P1** | #14 | Update doc header → "Layer 3+4 NOT_STARTED Q3-Q4 trigger" |
| 3 | `DEV_FOREX.md` 682 lines / 0% impl / 0 backend hits | **P1** | #2 / #14 | archive → `docs/archive/` + CLAUDE.md 注 "Phase 2+ deferred" |
| 4 | 3 code modules (paper_broker / base_broker / signal_router) 缺独立 design doc | **P1** | #20 | Spawn 3 spec doc OR 沉淀到 `DEV_BACKEND.md` §扩展 |
| 5 | `DEV_PARAM_CONFIG.md` 220 参数 vs 实际 50 + D5 决议未在 doc 刷新 | **P1** | #1 | rewrite doc to 50 active + 30 candidate + 140 archived |
| 6 | `docs/audit/` 122 files = 一次性诊断 chain 大量沉积, 缺索引 | **P1** | #2 | 重写 AUDIT_MASTER_INDEX 含全 122 file 状态 |
| 7 | `docs/research-kb/` 实测 41 entries vs CLAUDE.md cite 38 → cite drift | **P2** | #1 | update CLAUDE.md 数字 41 |
| 8 | `DEV_SCHEDULER.md` T1-T17 + FX1-FX11 大部分未实施 + Celery+TaskScheduler 双轨 | **P2** | #1 | 重写为当前 active schedules only |
| 9 | `DEV_NOTIFICATIONS.md` 邮件/微信/WebSocket 三项 ⏸ ~35% | **P2** | #1 | implement now (Wave 4 4.1 batch 3.x 已 partial wire) |
| 10 | `archive/` 含 ROADMAP_V3.md / DESIGN_V5.md 但 CLAUDE.md / SYSTEM_STATUS 仍有 latent reference | **P2** | #1 | grep all md/code 替换 reference |

---

**End Design vs Reality Gap sub-doc.**
