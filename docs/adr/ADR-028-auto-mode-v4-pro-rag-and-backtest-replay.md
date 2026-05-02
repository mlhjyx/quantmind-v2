# ADR-028: AUTO 模式 + V4-Pro X 阈值动态调整 + Risk Memory RAG + backtest replay

> **Status**: Proposed (5-02 起草, 等 user 决议; user merge PR = Accept signal)
> **Date**: 2026-05-02
> **Authors**: Claude.ai+user 战略对话 sediment (V3 §20.1 #5 + #9 决议)
> **Related**:
> - [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](../QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §1.2 Layer 3 (V4-Pro 路由) + §5.4 (RAG vector store) + §5.5 (LLM 路由) + §15.5 (backtest replay) + §7.1 STAGED + §17.4 (隐私) + §18.1 row 5/6 (原 ADR-025/026 真 RAG / Bull/Bear 预约 sustained reserve, 0 silent overwrite)
> - [docs/adr/ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md](ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md) (STAGED 5 prerequisite sustained, AUTO 5 prerequisite 真扩展)
> - [docs/adr/ADR-022-sprint-treadmill-revocation.md](ADR-022-sprint-treadmill-revocation.md) (anti-pattern enforcement sustained)

## §1 Context

### 1.1 触发背景

- **user "很少看, 需要 AUTO" 真实场景**: V3 §20.1 #5 决议输入. user 真离线 / 移动设备 / 工作时段, STAGED 反向决策权 (T+30min) 真不够 — Crisis regime + portfolio < -5% intraday 时真需要 immediate sell, 0 cancel.
- **V3 §5.4 RAG (Risk Memory)**: V4-Pro 推荐 X 阈值动态调整 (88-98% range, ±3-5% 步长) 真依赖历史事件 retrieval (similarity search), 沿用 daily_stock_analysis + QuantDinger 借鉴.
- **V3 §15.5 backtest replay (12 yr)**: 真 RAG 数据来源 — 历史 12 yr 事件回放生成 simulator data, source='backtest_replay' 仅作上下文参考 不进 confidence (反 fabrication 风险).
- **V3 §18.1 row 5/6 真预约**: 原 cite "ADR-025 RAG vector store" + "ADR-026 L2 Bull/Bear 2-Agent" 真 sustained reserve 0 silent overwrite (沿用 user (a-iii) 决议). 本 ADR # 下移 028, RAG implementation 真沉淀 V3 §5.4 + ADR-025 (待 user 决议 vector store 选型时创建), Bull/Bear 真 ADR-026 sustained Tier B 架构决议.

### 1.2 5 AUTO prerequisite (sustained ADR-027 §2.1 5 STAGED prerequisite 真扩展)

实施 sequence: Sprint 1~M (AUTO 不开发) → Sprint M+1~N (AUTO + RAG + backtest replay 实施) → Sprint N+ (5 AUTO prerequisite 满足后启用):

1. **STAGED 真实运行 ≥ 1 个月 0 真生产事件** (sustained ADR-027 §2.1 长期 5 prerequisite 满足后)
2. **paper-mode 5d 真 validated** (sustained PR #210 sim-to-real gap finding)
3. **SOP-6 sediment 完成** (5+ condition 真生产下单 fail-safe, 沿用 SOP-5 体例 LL-103 Part 2)
4. **Crisis regime detection 3 互锁指标** (TP ≥ 95% / FP ≤ 5% / FN ≤ 5%) + V4-Pro 接入 X 阈值动态调整 (V3 §1.2 Layer 3 + §5.5) + Risk Memory RAG 接入 (真实事件实时入库 + backtest replay 12 yr V3 §15.5 + replay source='backtest_replay' 仅作上下文 不进 confidence + simulator V3 §7 STAGED 默认逻辑) + 4 hard guardrails (X ∈ [88%, 98%] / 单次 ≤ 3% / 冷却 ≥ 1 月 / Override FN→+5%, FP 大损失→-3%) + RAG 3 风险缓解 (第一年 confidence ≤ 0.7 / ≤ 12 月真实数据 / user approve sustained)
5. **user 显式 .env 双启用** (`LIVE_TRADING_DISABLED=false` + `AUTO_ENABLED=true`)

**触发条件**: Crisis regime + portfolio < -5% intraday + .env 双启用 → 立即 sell, 0 cancel.

## §2 Decision

### 2.1 AUTO 模式: (D-改) 接受

- **default = OFF** (sustained 5 prerequisite 满足前)
- **Sprint 1~M**: AUTO 不开发 (sustained ADR-027 STAGED implement 优先)
- **Sprint M+1~N**: AUTO + Risk Memory RAG (V3 §5.4) + backtest replay (V3 §15.5) 实施
- **Sprint N+**: 5 prerequisite 满足后 user 显式启用

### 2.2 V4-Pro X 阈值动态调整 sequence (Sprint M+1~N)

- **DeepSeek V4-Pro 路由** (V3 §1.2 Layer 3 + §5.5): 月度复盘 cadence (沿用 V3 §17.4 隐私 + #6 月预算 review)
- **X 阈值 default**: 92% (4 hard guardrails 中位)
- **动态调整步长**: ±3-5% (sustained 4 hard guardrails)
- **4 hard guardrails**:
  1. X ∈ [88%, 98%] (绝对 range)
  2. 单次调整 ≤ 3%
  3. 冷却期 ≥ 1 月
  4. Override 触发 (FN → +5% / FP 大损失 → -3%)

### 2.3 Risk Memory RAG (V3 §5.4 cite)

- **embedding model**: BGE-M3 (sustained V3 §20.1 #3 + 1024 维 / 中文优化 / 0 cost / 本地隐私 V3 §17.4)
- **vector store 选型**: 待 user 决议 (沿用 ADR-025 真预约, 本 ADR 0 silent overwrite)
- **3 风险缓解**:
  1. 第一年 confidence ≤ 0.7 (真实数据少)
  2. 真实数据 ≤ 12 月才纳入 confidence (反 fabrication 风险)
  3. user approve 真 sustained (反向决策权)

### 2.4 Backtest replay (V3 §15.5 cite, 12 yr)

- **data source**: `source='backtest_replay'` — 仅作上下文参考, 不进 confidence (反 RAG fabrication 风险)
- **simulator**: 沿用 V3 §7 STAGED 默认逻辑 (sustained ADR-027 STAGED 1 个月 0 事件)
- **12 yr 真覆盖**: 反 sim-to-real gap finding (PR #210 sediment, audit F-D78-85 真证据加深, WF 5 fold test 期最后=2026-04-10, 4-29 PT 真生产事件不在 fold 内)

### 2.5 L5 反思 lesson 入 RAG 自动度: (c) 自动 + 后置抽查

- **自动入库**: 每事件 outcome 收集后 V4-Flash embedding → INSERT risk_memory, source='auto_lesson', confidence = V4-Pro 自评
- **3 hard guardrails 入库前**:
  1. lesson ≤ 500 字
  2. 必须 cite source
  3. confidence ≥ 0.3 否则 reject
- **后置抽查** (每月 1 日 V4-Pro 月复盘, 沿用 V3 §20.1 #4 cadence): confidence < 0.5 全抽 + random 10%, 检测异常 (重复 / fabrication / 矛盾 / 偏离 user 风格), 异常 push DingTalk, 反向决策权 (30 day approve / remove)
- **retention 分级**:
  - confidence ≥ 0.8: 永久保留
  - confidence < 0.8: ≤ 12 个月

## §3 Consequences

### 3.1 真依赖 (Sprint M+1~N)

- ADR-025 (RAG vector store 选型) 真 prerequisite — sustained reserve, 等 user 决议 (本 ADR 0 silent overwrite)
- V3 §5.4 RAG schema (risk_memory 表 + embedding column + similarity search index) 真 implementation
- V3 §15.5 backtest replay 真 data pipeline (12 yr 历史事件 → backtest_replay source 入库)
- ADR-027 STAGED 1 个月 0 事件 真 sustain 验证 (sustained §1.2 prerequisite 1)

### 3.2 Crisis regime detection 3 互锁指标真后果

- **TP ≥ 95%**: 真 crisis 真触发 (反 false-negative, 4-29 case 真延迟)
- **FP ≤ 5%**: 0 假告警 (反 N×N 同步漂移 — false alarm fatigue)
- **FN ≤ 5%**: 真 crisis 漏判 ≤ 5% (沿用 4 hard guardrails Override FN → +5% 反向)

### 3.3 V4-Pro X 阈值真后果

- 月度复盘真触发 → 沿用 V3 §20.1 #6 LLM 预算 ($50/月 + 80% warn / 100% Ollama fallback / 月度 review)
- Override 触发真 audit row 入库 (沿用 SOP-5 5 condition 0 真金风险)
- user 反向决策权: 30 day approve / remove 异常 lesson (沿用 §2.5 后置抽查)

## §4 Anti-pattern verify (沿用 ADR-022)

- ✅ **V4-Pro 推荐 ≠ 自动改 .env**: X 阈值调整真 4 hard guardrails 边界, NOT V4-Pro free-form 调整 (沿用铁律 27/35)
- ✅ **RAG fabricate 边界**: 3 风险缓解 (confidence ≤ 0.7 第一年 / ≤ 12 月真实数据 / user approve) + replay source 不进 confidence (沿用 §2.3 + §2.4)
- ✅ **lesson hard guardrails**: 入库前 3 guardrails (≤ 500 字 / cite source / confidence ≥ 0.3) + 后置抽查异常 reject (沿用 §2.5)
- ✅ **不 silent overwrite ADR-025/026 真预约**: 沿用 user (a-iii) 决议, RAG implementation 沉淀 V3 §5.4 + ADR-025 (待 user 决议 vector store 选型时创建), Bull/Bear sustained ADR-026 Tier B 架构决议
- ✅ **sustained 真账户保护**: AUTO default = OFF (短期) 沿用 LIVE_TRADING_DISABLED + EXECUTION_MODE=paper 双层 + 5 prerequisite 真显式 verify

## §5 实施 source

- V3 §20.1 #5 (AUTO 模式) + #9 (lesson 入 RAG 自动度) — Claude.ai+user 战略对话 sediment, 5-02
- V3 §1.2 Layer 3 (V4-Pro 路由) + §5.4 (RAG vector store) + §5.5 (LLM 路由) + §15.5 (backtest replay) + §7.1 STAGED + §17.4 (隐私)
- ADR-027 (STAGED 5 prerequisite, AUTO 5 prerequisite 真扩展)
- ADR-022 (sprint period treadmill 反 anti-pattern, sustained enforcement)
- LL-103 Part 2 SOP-5 (audit row backfill 真 SQL 写 5 condition, 沿用 §3.3)
- PR #210 sim-to-real gap finding (audit F-D78-85 真证据加深, sustained §2.4 backtest replay 12 yr 真依赖)
