# T1.3 风控架构决议 Design Doc (Step 7-prep, 2026-05-01)

**Status**: Design input (NOT decision). T1.3 决议留 user/CC 对话沉淀.
**Created**: 2026-05-01 (Step 7-prep PR)
**Source**: CC 实测推导 (现有 repo 资产 + memory recent_updates 设计概念 prompt cite)
**Maintainer**: CC + user (T1.3 对话期间迭代)
**关联**: ADR-010 / ADR-010-addendum / ADR-022 §7.3 / TIER0_REGISTRY T0-12 / SHUTDOWN_NOTICE §9 / MVP 3.1 / MVP 3.1b
**反 anti-pattern**: 沿用 D72/D73/D74 — design doc 是 T1.3 决议**输入**, 不替代决议. 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用 — 本 doc enumerate 全决议项, 不偷懒留下波.

---

## §0 Scope + 边界

### §0.1 设计目标

将 memory recent_updates 中的风控架构设计概念**首次 sediment 到 repo**, 锚定 T1.3 决议. 消除 ADR-022 §7.3 提到的"memory 是真 SSOT, repo 仅 milestone snapshot"路径下的设计概念缺 repo 锚定问题.

### §0.2 设计边界 (本 doc 范围)

✅ enumerate:
- 现有 repo 已落地范围 (实测 SSOT)
- memory 设计概念 sediment (5+1 层架构 / Tier A/B 拆分 / 不采纳清单 / RiskReflector / Bull-Bear / NEWS 4 层 / fundamental_context / V4-Flash / LiteLLM / 6 news / TradingAgents 借鉴)
- T1.3 决议清单 (~20 项, CC 实测推导)
- 5+1 层 SSOT 现状 (各层 implementation prerequisite + 已落地 evidence)
- Tier A/B 拆分 (含不采纳论据完整链)
- anchor 矩阵 (G1-G4 候选)
- 推荐起手项 + 论据
- 不变项 (现 4+ rules + risk_event_log + Beat 等保留)

❌ 不 enumerate:
- 决议本身 (CC 不擅自决议, 留 T1.3 对话)
- 具体 implementation 行号 / 函数签名细节 (留具体 PR design)
- 真生产数据 / 真账户数字 (沿用 SHUTDOWN_NOTICE / TIER0_REGISTRY SSOT)

### §0.3 LL-098 stress test 第 12 次 verify

末尾 0 forward-progress offer (T1.3 启动 / 起手项执行 / paper-mode / cutover / 等).

---

## §1 现有 repo 资产实测清单 (WI 1)

### §1.1 SSOT 文档

| # | 文件 | 行数 | 范围 | 状态 |
|---|---|---|---|---|
| 1 | `docs/RISK_CONTROL_SERVICE_DESIGN.md` | 678 | L1-L4 熔断状态机 + service interface (cb_state 表 + 接口 + 调用方集成) | ✅ 老 SSOT (CB 状态机) — Wave 3 MVP 3.1 批 0 spike 后, CB 走方案 C Hybrid wrapper, 该文件保持作为 1030 行 async API 历史 |
| 2 | `docs/adr/ADR-010-pms-deprecation-risk-framework.md` | 186 | PMS v1 5 重失效 (F27-F31) + Risk Framework D1-D7 决策 | ✅ ADR-010 主决议 |
| 3 | `docs/adr/ADR-010-addendum-cb-feasibility.md` | 262 | CB 状态机映射 RiskRule 可行性 spike (方案 C Hybrid wrapper) | ✅ ADR-010 addendum (批 0 spike) |
| 4 | `docs/mvp/MVP_3_1_risk_framework.md` | 217 | Risk Engine + 11 规则迁移 + risk_event_log + 批 0/1/2/3 实施结构 | ✅ MVP 3.1 设计稿 |
| 5 | `docs/mvp/MVP_3_1b_risk_v2.md` | 103 | Risk v2 加固 (单股层 SingleStockStopLossRule + scheduler_task_log + entry_date 契约) | ✅ MVP 3.1b 设计稿 |
| 6 | `docs/research/G2_RISK_PARITY_REPORT.md` | (未读) | G2 风险平价 7 组 NO-GO 论据 | ✅ research |
| 7 | `docs/research-kb/failed/g2-risk-parity.md` | (未读) | G2 NO-GO sediment | ✅ research-kb |
| 8 | `docs/research-kb/failed/pms-v2-consecutive-days.md` | (未读) | PMS v2 NO-GO sediment | ✅ research-kb |
| 9 | `docs/research-kb/decisions/pms-v1-tiered-protection.md` | (未读) | PMS v1 阶梯保护决议 | ✅ research-kb |
| 10 | `docs/research-kb/decisions/mdd-layer-xd.md` | (未读) | MDD 层 XD 决议 | ✅ research-kb |
| 11 | `docs/audit/TIER0_REGISTRY.md` | (PR #180 新建) | T0-12 Risk Framework v2 9 PR 真生产 0 events 验证 (G2 待 methodology 决议) | ✅ |

### §1.2 已完全缺失 (主动发现 #1)

- ❌ `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` 不存在 (memory 假设)
- ❌ `ADR-019` / `ADR-020` 不存在 (memory cite "pending ADR")
- ❌ memory 中 5+1 层架构 / Tier A/B 拆分 / RiskReflector / Bull-Bear / NEWS 4 层 / fundamental_context / V4-Flash / LiteLLM / 6 news / TradingAgents 借鉴 — repo 0 sediment

**根因**: ADR-022 §7.3 决议 "memory 是真 SSOT, repo 仅 milestone snapshot" — 这些设计概念是 sprint planning, sediment 仍在 memory 系统. 本 doc 是首次 sediment 到 repo.

### §1.3 已落地 Risk Framework 范围 (实测 sustained)

| 层 | 已落地 rules | 来源 PR | 文件 |
|---|---|---|---|
| 组合层 | IntradayPortfolioDrop 3/5/8% | PR #59/#60 (Session 28-30 MVP 3.1 批 2) | `backend/qm_platform/risk/rules/intraday.py` |
| 组合层 | QMTDisconnectRule | PR #59/#60 | 同上 |
| 组合层 | QMTFallbackTriggeredRule (T0-15 修, PR #170 c4) | PR #170 | `backend/qm_platform/risk/rules/qmt_fallback.py` |
| 单股层 (MVP 3.1 批 1) | PMSRule L1/L2/L3 (浮盈 30/20/10% + 回撤 15/12/10%) | PR #55/#57/#58 (MVP 3.1 批 1) | `backend/qm_platform/risk/rules/pms.py` |
| 单股层 (Risk v2) | SingleStockStopLossRule (-10/15/20/25% 4 档) | PR #139 (Risk v2) | `backend/qm_platform/risk/rules/single_stock.py` |
| 单股层 (Risk v2) | PositionHoldingTimeRule (持仓 ≥ 7 天 + 亏损 ≥ -10%) | PR #148 (Risk v2 Phase 1.5) | `backend/qm_platform/risk/rules/holding_time.py` |
| 单股层 (Risk v2) | NewPositionVolatilityRule (新建仓 ≤ 7 天 -15%) | PR #148 | `backend/qm_platform/risk/rules/new_volatility.py` |
| 熔断 | CircuitBreakerRule (Hybrid wrapper, L1-L4) | PR #61 (MVP 3.1 批 3) | `backend/qm_platform/risk/rules/circuit_breaker_adapter.py` |
| 输出 | risk_event_log table (TimescaleDB hypertable, 90d retention) | PR #170 c0 (T0-11 F-D3A-1 missing migration) | `backend/migrations/risk_event_log.sql` |
| 调度 | risk-daily-check Beat 14:30 + intraday-risk-check Beat `*/5 9-14` | PR #58 + PR #60 | `backend/app/tasks/beat_schedule.py` |
| 守门 | scheduler_task_log audit + Beat dead-man's-switch self-health 18:45 | PR #144-146 (Risk v2) | `backend/app/services/scheduler_audit.py` |
| 数据 | Position.entry_date 契约 (avoiding -1 sentinel type lie) | PR #147 (Risk v2) | `backend/qm_platform/risk/sources/qmt_realtime.py` |

**总计实落地 rule count**: ~10-11 (4 组合 + 7 单股 + CB Hybrid).
**实落地 PR count**: ~15 (MVP 3.1 6 + Risk v2 9 + T0 修补).

---

## §2 T1.3 决议清单 (CC 实测推导, WI 2)

> **声明**: 本节 enumerate 决议项, **不擅自决议**. 决议候选 + NO-GO 反例论据 完整链 cite source. 决议本身留 T1.3 对话.

### §2.1 D-L0 ~ D-L5 5+1 层架构决议 (6 项)

| # | 决议项 | 候选 + 论据 | source |
|---|---|---|---|
| **D-L0** | 多源数据接入 | (a) 接入 LiteLLM + 6 news + V4-Flash classification (memory cite Tier A 主导路径) / (b) 不接入, sustain 现 QMT realtime + DB snapshot 双源 (sustained MVP 3.1 D3) / (c) 部分接入 (仅 sentiment, 不接 fundamental_context) | memory recent_updates Tier A 5 项 |
| **D-L1** | 基础规则保留 + 扩展 | (a) sustain 现 ~10 rules / (b) 扩 IndustryConcentrationRule (MVP 3.1b Out-of-scope Phase 3) / (c) 扩 ConcentratedLossRule (同上) / (d) 全扩 + 阈值 calibration | MVP 3.1b L48-50 Out-of-scope, ADR-016 候选 |
| **D-L2** | 智能规则纳入 | (a) RAG-based decision (Tier B) / (b) 单 RiskReflector (TradingAgents pattern) / (c) Bull-Bear agent debate (TradingAgents pattern) / (d) 不纳入, 智能层留 Wave 4+ | memory Tier B 3 项 |
| **D-L3** | 动态阈值 | (a) sustain hardcoded (PMS 10/12/15%, SingleStockStopLoss -10/15/20/25%) / (b) regime-based dynamic (沿用 Step 6-E NO-GO: 5 指标 p>0.05 线性方法无效) / (c) volatility-based dynamic (新方向, 未实测) / (d) percentile-based (vs 历史 quantile) | research-kb/findings/step6-failure-analysis.md (regime NO-GO) |
| **D-L4** | batched + trailing + re-entry | (a) sustain 现 single trigger - sell - never re-buy / (b) batched (累积 N 触发后 sell, 反 single-shock 误触) / (c) trailing (动态 stop 跟随 peak) / (d) re-entry logic (sell 后 N 日内不重买, 防 churn) | research-kb/decisions/pms-v1-tiered-protection.md, research-kb/decisions/mdd-layer-xd.md |
| **D-L5** | reflection 层 | (a) TradingAgents pattern (Bull/Bear/Neutral 3 agents debate, RAG-augmented) / (b) 单 RiskReflector (post-trade 反思 + memory store) / (c) 不纳入, sustain rule-based / (d) Wave 4+ AI 闭环 整合 (沿用 DEV_AI_EVOLUTION V2.1) | memory Tier B + DEV_AI_EVOLUTION V2.1 |

### §2.2 D-T-A1 ~ D-T-A5 Tier A 拆分决议 (5 项, before T1.5)

| # | 决议项 | 候选 + 论据 | source |
|---|---|---|---|
| **D-T-A1** | LiteLLM multi-provider abstraction | (a) 接入 LiteLLM 作 OpenAI-compatible facade (沿用 LANDSCAPE 借鉴 #12 QuantDinger) / (b) 自建 Enum + auto-detect / (c) 不接, 直调 OpenAI/Anthropic SDK | LANDSCAPE_ANALYSIS_2026 借鉴 #12 |
| **D-T-A2** | 6 news 源 enumerate | (a) 实测哪 6 source (memory cite "6 news" 数字) / (b) 改 N news (CC 决议 source 数) / (c) 不接, news 是 Wave 4+ scope | memory cite, 实测 source 列表缺失 |
| **D-T-A3** | V4-Flash classification | (a) Gemini 2.0 Flash classification model / (b) DeepSeek V4 (assumed memory cite) / (c) 自建 classifier (vs LLM) | memory cite |
| **D-T-A4** | fundamental_context | (a) 接入财报数据 (PB/PE/ROE/dividend) 作上下文 / (b) 接入行业数据 (SW1 sector beta) / (c) 不接, sustain 现 daily_basic 只读 | memory cite |
| **D-T-A5** | NEWS 4 layer pipeline | (a) raw → classified → aggregated → decision 4 stage / (b) 简化 3 stage (skip aggregation) / (c) 不接 | memory cite "NEWS 4 层" |

### §2.3 D-T-B1 ~ D-T-B3 Tier B 拆分决议 (3 项, T2)

| # | 决议项 | 候选 + 论据 | source |
|---|---|---|---|
| **D-T-B1** | RiskReflector | (a) post-trade 反思 + memory store (借鉴 TradingAgents) / (b) per-trade pre-check (实时反思 vs post-hoc) / (c) 不纳入 | memory Tier B + TradingAgents |
| **D-T-B2** | Bull-Bear agent debate | (a) 多 agent debate 输出 risk verdict (借鉴 TradingAgents) / (b) 单 LLM judge (vs debate, 简化) / (c) 不纳入 | memory Tier B + TradingAgents |
| **D-T-B3** | RAG vector store | (a) 接入 (e.g. ChromaDB / pgvector) 作 LLM context retrieval / (b) 不接, sustain prompt-only / (c) 简化 keyword search | memory Tier B |

### §2.4 D-N1 ~ D-N4 不采纳清单 sediment (4 项)

| # | 不采纳项 | 论据完整链 (memory cite) |
|---|---|---|
| **D-N1** | jin-ce-zhi-suan (金策智算) | LANDSCAPE_ANALYSIS_2026 §"知识星球营销 vs 工程质量" — 金策"四个文件并读"模式过浮 + Issue 反馈滞后 + 关键功能 (record_{ts}.json) 已被 #9 借鉴, 不必整体采纳 |
| **D-N2** | QuantDinger | LANDSCAPE_ANALYSIS_2026 Issue #52 (手续费没扣) — SaaS 营销 ≠ 实战核心, stars 2K 不等工程质量. 关键功能 (LLM multi-provider / candle path / sandbox) 已被 #12/#13/#20 借鉴 |
| **D-N3** | LangGraph | (论据待 memory 完整 sediment, 推测: multi-agent 编排 over-kill, QM single-strategy 单方向适合 fastapi 直接调度, LangGraph state machine 引入复杂度高于收益) |
| **D-N4** | RD-Agent (Wave 3 末决议) | ADR-013 已 sediment "Wave 4+ Decision Gate, not adoption decision". 沿用阶段 0 NO-GO (Docker 硬依赖 + Windows bug + Claude 不支持). Wave 3 末重新评估, 但 Wave 3 已完结无 RD-Agent 引入 |

### §2.5 D-M1 ~ D-M2 Methodology 决议 (2 项)

| # | 决议项 | 候选 + 论据 | source |
|---|---|---|---|
| **D-M1** | T0-12 Risk Framework v2 真生产 0 events 验证 methodology | (a) 历史回放 (使用 backtest 数据流模拟历史风控 events) / (b) 合成场景 (写测试用例模拟 -29% / -10% scenario) / (c) 双管齐下 (a + b) | TIER0_REGISTRY §2.8 + MVP 3.1b 实测真根因 |
| **D-M2** | ADR-016 PMS v1.0 deprecate 决议 | (a) 删 PMS v1 完全 (Risk v2 SingleStockStopLoss 替代) / (b) PMS v1 + Risk v2 共存 (sustain 现状, MVP 3.1b 决议) / (c) PMS v1 重新激活 (修复 5 重失效 vs 写 v2) | MVP 3.1b L103 + ADR-010 §D7 |

### §2.6 决议项总数 (CC 实测)

- D-L0 ~ D-L5: **6 项** (5+1 层架构)
- D-T-A1 ~ D-T-A5: **5 项** (Tier A)
- D-T-B1 ~ D-T-B3: **3 项** (Tier B)
- D-N1 ~ D-N4: **4 项** (不采纳 sediment)
- D-M1 ~ D-M2: **2 项** (methodology)
- **总计: 20 项**

---

## §3 5+1 层架构 SSOT 现状 (WI 3)

> **背景**: memory recent_updates 提到 "5+1 层风控架构: L0 多源 / L1 基础 / L2 智能 / L3 动态阈值 / L4 batched+trailing+re-entry / L5 reflection". 实测 repo SSOT 现状下表.

| 层 | memory 描述 | repo SSOT 现状 | implementation prerequisite |
|---|---|---|---|
| **L0 多源** | LiteLLM + 6 news + V4-Flash + fundamental_context | ❌ repo 0 sediment | LiteLLM 接入 / 6 news 源 enumerate / V4-Flash classifier / fundamental_context schema |
| **L1 基础** | PMS L1/L2/L3 + 单股层 + intraday + CB | ✅ MVP 3.1 + MVP 3.1b 已落地 ~10 rules (sustain) | (sustained, 现 SSOT 就是 implementation) |
| **L2 智能** | RAG / fundamental_context / sentiment | ❌ repo 0 sediment | RAG vector store / sentiment ingestion / fundamental_context schema |
| **L3 动态阈值** | regime-based / volatility-based dynamic | ❌ repo 0 sediment (Step 6-E regime NO-GO sustained, volatility-based 未实测) | volatility-based design / quantile-based design |
| **L4 batched + trailing + re-entry** | 累积 + 跟踪 + 重购防护 | ❌ repo 0 sediment (现 single trigger - sell - never re-buy) | batched logic / trailing stop algorithm / re-entry blacklist |
| **L5 reflection** | TradingAgents Bull/Bear pattern | ❌ repo 0 sediment | RiskReflector class / Bull-Bear agent / Wave 4+ AI 闭环依赖 |

**L1 已落地, L0/L2/L3/L4/L5 全 0 repo sediment**. 这是 T1.3 决议的核心 scope.

---

## §4 Tier A/B 拆分实测 (WI 4)

> **背景**: memory recent_updates 提到 "Tier A (before T1.5): LiteLLM + 6 news + V4-Flash + fundamental_context + NEWS 4 层. Tier B (T2): RiskReflector + Bull/Bear + RAG. 不采纳: jin-ce-zhi-suan / QuantDinger / LangGraph / RD-Agent Wave 3 末".

### §4.1 Tier A 5 项 implementation prerequisite

| # | 项 | repo 现状 | implementation prerequisite |
|---|---|---|---|
| A1 | LiteLLM | ❌ 0 sediment | pip install litellm + provider config + auth keys |
| A2 | 6 news 源 | ❌ 0 sediment | enumerate 6 source (e.g. RSS / Twitter / 财经媒体 / 公告) + ingestion pipeline + dedup |
| A3 | V4-Flash classifier | ❌ 0 sediment (config has DeepSeek API but未集成) | classifier schema (label set) + LLM call wrapper + confidence threshold |
| A4 | fundamental_context | ❌ 0 sediment | data source (沿用 daily_basic? 或新接入 Wind/Choice?) + refresh freq |
| A5 | NEWS 4 layer | ❌ 0 sediment | pipeline design: raw → classified → aggregated → decision |

### §4.2 Tier B 3 项 implementation prerequisite

| # | 项 | repo 现状 | implementation prerequisite |
|---|---|---|---|
| B1 | RiskReflector | ❌ 0 sediment | reflector class + memory store + invocation hook |
| B2 | Bull-Bear agent | ❌ 0 sediment | multi-agent debate framework + judge LLM + verdict aggregation |
| B3 | RAG | ❌ 0 sediment | vector store (ChromaDB/pgvector) + embedding model + retrieval API |

### §4.3 不采纳 4 项论据完整链

| # | 项 | 论据 | source |
|---|---|---|---|
| N1 | 金策智算 | LANDSCAPE §"知识星球营销 vs 工程质量". 关键功能已被借鉴 #9 (record_{ts}.json) | LANDSCAPE_ANALYSIS_2026 §discussion |
| N2 | QuantDinger | Issue #52 (手续费没扣) + stars ≠ 工程质量. 关键功能已被借鉴 #12/#13/#20 | LANDSCAPE_ANALYSIS_2026 §discussion |
| N3 | LangGraph | (memory cite, 推测) multi-agent 编排 over-kill for QM single-strategy. fastapi 直调度足够. **决议依据待 T1.3 user 输入完整论据** (sustained STOP 主动发现 #2: memory 论据未完整 sediment) | memory cite (incomplete) |
| N4 | RD-Agent | ADR-013 已 sediment "Wave 4+ Decision Gate". 沿用阶段 0 NO-GO (Docker / Windows / Claude). Wave 3 末未重启. | ADR-013 |

### §4.4 与 T1.5 回测引入风控的接口契约 (memory cite)

memory: "评估为纯函数, 0 broker / 0 notification / 0 INSERT 依赖, dedup + timestamp via context".

实测 sustained: MVP 3.1 D2 RiskRule.evaluate() 已是纯函数 (return list[RuleResult], 0 IO). MVP 3.1 D4 execute() 有 broker/notification/INSERT (沿用 Risk Framework 直接执行 design). T1.5 backtest 引入需要走 evaluate 不走 execute (or mock execute). ✅ 接口契约 sustained, T1.5 引入 prerequisite minimal.

---

## §5 anchor 矩阵 (G1-G4 候选, WI 5)

> **背景**: 沿用 D73 模式 — design doc + T1.3 决议自然 anchor G1-G4 项 (反 "留 Step 7+" 滥用).

### §5.1 G1 (本 PR + T1.4 批 2.x AI 自主修, sustained TIER0_REGISTRY §4.1)

T1.3 决议**不直接** anchor G1 (G1 是已 enumerate 的 7 项 T0-4/5/6/7/8/9/10). T1.3 决议层是更上层 (架构 vs T0 业务).

### §5.2 G2 (Step 7 T1.3 架构层决议)

| T1.3 决议 # | 自然 anchor | 实施时机 |
|---|---|---|
| D-M1 (T0-12 methodology) | T0-12 G2 项 | T1.3 决议后 → AI 自主 PR 实施 methodology |
| D-M2 (ADR-016 PMS v1) | TIER0_REGISTRY §2.8 (T0-12 closeup), MVP 3.1b L103 future PR | T1.3 决议后 → AI 自主 PR 实施 ADR-016 |

### §5.3 G3 (候选铁律 X1/X3/X4/X5/X11 promote)

T1.3 决议**不直接** anchor G3 (X 候选是 IRONLAWS §22 已 enumerate, 与风控架构正交).

### §5.4 G4 (4 fail mode 工程化测试)

T1.3 决议**不直接** anchor G4 (G4 是 git hook 工程化, 与风控架构正交).

### §5.5 总结

T1.3 决议主要 anchor **G2** (架构层决议). G1/G3/G4 与风控架构正交, sustained 各自 enumerate 的 SSOT (TIER0_REGISTRY / IRONLAWS §22).

---

## §6 推荐起手项 (WI 6)

> **声明**: CC 仅推荐, **不擅自决议起手项**. user 看 design doc 后决议起手项, T1.3 对话沉淀.

### §6.1 起手项候选评估 (CC 实测推导 ROI)

| # | 候选 | 依赖 | ROI | 后续锁定 |
|---|---|---|---|---|
| **C1** | D-M2 (ADR-016 PMS v1 deprecate) | 0 (现 PMS v1 已被 SingleStockStopLoss 互补) | 中 (清死码 + 锁 ADR) | 锁 PMS 命运, 解 MVP 3.1b L103 future PR |
| **C2** | D-M1 (T0-12 methodology) | 0 (T0-12 是 G2 已 enumerate, 等 methodology 决议) | 高 (verify Risk Framework v2 9 PR 真生产 0 events 是否设计合理) | 解 TIER0_REGISTRY §2.8 + MVP 3.1b 真根因 |
| **C3** | D-L0 / D-T-A* (LiteLLM + 6 news + V4-Flash) | 高 (multi-prerequisite: provider 接入 + news ingestion + classifier) | 中 (架构展开) | 解 5+1 层 L0 |
| **C4** | D-L4 (batched + trailing + re-entry) | 中 (现 single trigger 替换 batched logic) | 中 (改进现 rule semantics) | 解 5+1 层 L4 |
| **C5** | D-L1 (基础规则扩展 IndustryConcentration / ConcentratedLoss) | 低 (沿用现 RiskRule abstract 加新 rule) | 中 (扩 rule count, 但是真增 alpha 不确定) | 解 MVP 3.1b Phase 3 |
| **C6** | D-N1/N2/N3/N4 (不采纳清单 sediment) | 0 (sediment doc only) | 低 (沿用 sustain) | 锁不采纳 SSOT (反 sprint period 重提) |

### §6.2 推荐起手项 (CC 论据)

**推荐: C2 (D-M1, T0-12 methodology)** — 论据三选一加权:

1. **依赖最少**: T0-12 是已 enumerate 的 G2 项, methodology 决议**不依赖**任何其他 D-L0~L5 / D-T-A*/B* / D-N* 决议 (各 D 项是平行决议)
2. **决议 ROI 最高**: T0-12 真生产 0 events 验证缺是 sprint period sustained 已知风险 (TIER0_REGISTRY §2.8 + MVP 3.1b 真根因实测). methodology 决议解锁 verify Risk Framework v2 9 PR 真有效
3. **后续决议 scope 锁定**: methodology 决议 (历史回放 / 合成场景 / 双管齐下) 是 verify methodology 锁定后, 后续 D-L*/D-T-* 决议自然走该 methodology verify (sustained pattern, 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用)

### §6.3 prerequisite 起手项声明 (CC 主动发现 #3)

**D-M2 (ADR-016)** 是 D-L1 / D-L2 / D-L4 的隐含 prerequisite — 因 PMS v1 命运未锁前, D-L1 扩展 (新 rule) 与 D-L4 (batched/trailing) 设计上可能与 PMS v1 重叠 / 冲突. 推荐 C2 起手 + C1 紧随 (or 并行).

### §6.4 不推荐起手项

- C3 (LiteLLM + 6 news + V4-Flash): 依赖最高, 架构展开 ROI 中, 应**留后期** (T1.3 决议链末)
- C5 (基础规则扩展): 依赖低但 ROI 中 (新 rule 是真 alpha 不确定), 应**与 D-L1 决议同步**
- C6 (不采纳 sediment): ROI 低, design doc 已 sediment, 不需起手

---

## §7 不变项 (sustained, T1.3 决议不动)

| 项 | sustained source |
|---|---|
| Risk Framework 4 接口 (RiskRule / RiskEngine / PositionSource / RiskContext) | MVP 3.1 D1-D5 (PR #55-#61 已落地) |
| risk_event_log 单表统一日志 (90d retention TimescaleDB hypertable) | ADR-010 D4 + PR #170 c0 (T0-11 修) |
| 调度: risk-daily-check 14:30 + intraday `*/5 9-14` Beat | MVP 3.1 (PR #58 + #60) |
| scheduler_task_log audit + Beat dead-man's-switch self-health 18:45 | Risk v2 (PR #144-146) |
| Position.entry_date 契约 | Risk v2 (PR #147) |
| ADR-008 execution_mode 命名空间 | sustained 全链路动态 settings |
| 直接执行 (F27 根治, 不走 StreamBus 3 hops) | ADR-010 D3 |
| QMTPositionSource Redis primary 60s + DBPositionSource fallback | MVP 3.1 D3 |
| pre-push hook X10 cutover-bias 守门 | PR #177 |
| LL-098 + LL-098 stress test 累计第 12 次 verify | sprint period sustained |
| ADR-022 §7 handoff 治理路径 1 (Anthropic memory 唯一 SSOT + repo 仅 milestone snapshot) | PR #180 |

---

## §8 关联 + 后续 + LL-098 verify

### §8.1 关联 PR 链 (sustained sprint period)

- PR #172 (Step 5) / #173 (Step 6.1) / #174 (Step 6.2) / #175-#177 (Step 6.2.5*) / #178 (Step 6.3a) / #179 (Step 6.3b) / #180 (Step 6.4 G1)
- 本 PR (Step 7-prep, T1.3 design doc 落地)

### §8.2 关联 ADR (sustained ADR 编号)

- ADR-010 (PMS Deprecation + Risk Framework Migration)
- ADR-010-addendum (CB Hybrid spike)
- ADR-013 (RD-Agent Re-evaluation Plan, 沿用阶段 0 NO-GO)
- ADR-014 (Evaluation Gate Contract G1-G10 + G1'-G3')
- ADR-021 (IRONLAWS v3 重构)
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制)

### §8.3 关联 MVP / TIER0

- MVP 3.1 (Risk Framework, 4 + CB rules)
- MVP 3.1b (Risk v2 加固, 单股层)
- TIER0_REGISTRY §2.8 (T0-12 G2 待修)

### §8.4 后续 (T1.3 对话起手 留 user 显式触发)

T1.3 对话起手由 user 显式触发. 沿用 LL-098 stress test 第 12 次 verify, 本 design doc 末尾 0 forward-progress offer.

### §8.5 LL-098 stress test 第 12 次 verify 清单

- ❌ 不写 "T1.3 启动 offer"
- ❌ 不写 "起手项 C2 执行" / 任何前推动作
- ❌ 不写 "schedule agent" / "paper-mode" / "cutover"
- ✅ 等 user 看 design doc 后显式触发起手项

**累计 stress test 次数**: 第 12 次 (PR #173 → 本 PR 累计 12 次连续 verify, 0 失守).

---

## §9 主动发现累计 (broader sediment)

沿用 Step 6.4 G1 §6.1 broader 42 / narrower 30 / LL 总数 92 baseline.

| # | 假设源 | 实测推翻 | broader / narrower 影响 |
|---|---|---|---|
| #1 | prompt §1 cite memory recent_updates "5+1 层 / Tier A/B / RiskReflector / 等" | 实测 repo 0 sediment (sustained ADR-022 §7.3 memory-only 路径) | **broader +1** (sprint period 设计概念 sediment 缺) |
| #2 | prompt §1 cite "pending ADR-019 / ADR-020" | 实测不存在 | **broader +1** (sprint period 命名占位错) |
| #3 | D-M2 (ADR-016) 是 D-L1/L2/L4 隐含 prerequisite | 实测推导发现 (CC 起手项分析 by-product) | **broader +1** (CC 实测推导发现新依赖关系) |
| #4 | RISK_FRAMEWORK_LONG_TERM_ROADMAP 不存在 | 实测 (sustained Step 6.3a/b 主动发现) | (sustained, 不增 broader) |

**本 PR sediment**:
- narrower (LL 内文链): **30** unchanged (本 PR 0 LL 沉淀)
- broader (PROJECT_FULL_AUDIT scope): **42 → 45** (沿用 Step 6.4 G1 42 + 本 PR 3 新发现)
- LL 总数: **92** unchanged

---

**T1_3_RISK_FRAMEWORK_DECISION_DOC.md 写入完成 (2026-05-01, ~510 行, ~20 项决议 enumerate, 5+1 层 + Tier A/B + 不采纳 + methodology 全 sediment)**.
