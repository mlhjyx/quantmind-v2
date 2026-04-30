# Risk Review — 4-29 PT 暂停事件 5 Why 深挖

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 4 / risk/01
**Date**: 2026-05-01
**Type**: 评判性 + 真根因 5 Why (反 framework §3.6 "5 Why 不止 5min Beat 太慢")

---

## §0 元说明

sprint state Session 44 (4-29) 沉淀 PT live 真生产事件 (688121 -29% / 000012 -10%, 30天 risk_event_log 0 行) → user 决策"全清仓暂停 PT".

User D77 显式开放本审查 adversarial 推翻 user 假设 (沿用 framework §5.2): "user 假设 4-29 真根因 = 盘中盯盘 + 风控未设计, 但真根因可能更深".

本 md 走 5 Why 真根因深挖, 沿用 framework §3.6.

---

## §1 4-29 事件真值实测 (sprint state Session 44)

| 时间 | 事件 |
|---|---|
| 2026-04-29 ~10:25 | 688121.SH 卓然新能 -29% 跌停 |
| 同日 | 000012 -10% 大跌 |
| 30 天累计 | risk_event_log = 0 行 (即 ✅ 0 风控告警触发) |
| ~10:43 | CC emergency_close 17 股 |
| ~跌停 | 1 股 (688121.SH 4500 股) cancel (跌停无成交) |
| 4-30 user GUI sell | 卓然新能 4500 股清 |
| 4-30 14:54 | 真账户 0 持仓 / cash ¥993,520.16 |

(本审查 5-01 04:16 实测真账户仍 0 持仓 / cash ¥993,520.66 ✅ sustained)

---

## §2 5 Why 深挖

### Why 1: 为什么 -29% 跌停了 risk_event_log = 0 行?

**user 假设答**: "5min Beat 风控太慢, intraday 看不到 -8% 阈值".

**实测真值**:
- intraday-risk-check Beat 5min 高频 — sprint period 4-29 PR PAUSED (沿用 LL-081 钉钉刷屏理由)
- 即使未 PAUSED, 5min 周期内 -29% 跌停一次性发生, Beat 检测时已 cancel 不可
- **真原因**: 5min Beat 是 batch 检测, 不是 real-time event-driven. 跌停 -10% 触发后 Beat 5min 内才检测到, 已晚

**Why 1 答**: ✅ user 假设方向对, 但深一层是 **batch vs event-driven 架构选择**

### Why 2: 为什么用 batch 5min Beat 而非 event-driven 实时风控?

**user 假设答**: "5+1 层风控 D-L0~L5 sustained 设计, T1.3 design doc 沉淀, 实施层未到位".

**实测真值**:
- T1.3 design doc (PR #181, docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md 342 行) 20 项决议 enumerate ✅
- 5+1 层 D-L0~L5: **L1 ✅ 已落地 (MVP 3.1+3.1b ~10 rules), L0/L2/L3/L4/L5 全 ❌ 0 repo sediment** (sprint state Session 46 末)
- L0 (real-time event-driven 风控) 0 实施

**Why 2 答**: ✅ user 假设对, 实施层未到位 (L0 ❌)

### Why 3: 为什么 L0 未实施?

**user 假设答**: 沿用 framework §3.6 — 风控架构 4-29 真根因更深.

**实测真值**:
- sprint period (4-30~5-01) 22 PR 全是治理基础设施 (6 块基石建立), 0 业务前进 (governance sprint period, 沿用 governance/01_six_pillars_roi §3)
- T1.3 design doc 沉淀 (PR #181) 仅 design 未实施
- sprint period 之前 (Session 42-43) Wave 4 MVP 4.1 Observability 沉淀 — 但 Observability 非 L0 风控 (是 alert / monitor 而非 enforce)
- **真原因**: 项目优先级在 governance sprint period + Observability, **L0 实时风控未列优先级**

**Why 3 答**: 项目优先级排序 ⚠️ — L0 风控非"前推动作"反而是"留下次", 沿用 ADR-022 第 2 条 anti-pattern

### Why 4: 为什么项目优先级把 governance + Observability 排在 L0 实时风控前?

**user 假设答**: "Claude 沉淀 + sprint period 22 PR 链推动 + treadmill anti-pattern".

**实测真值**:
- sprint period 22 PR 链 集中 4-30 ~ 5-01 ~24h 高密度 (sprint state Session 46 末: 22 PR 跨日)
- D72-D78 4 次反问印证 user 已不耐烦 治理 sprint period
- Wave 1-4 路线图 sustained 沉淀 (sprint state QPB v1.16) 但 4 Wave 仅 Wave 1+2 完结 / Wave 3 完结 / **Wave 4 MVP 4.1 进行中 + Wave 5+ 未启**
- L0 实时风控不在 Wave 1-4 现路线图 (是 Wave 5+ 未启的 candidate, sprint state 沉淀 sustained 优先级)

**Why 4 答**: 项目路线图设计 ⚠️ — Wave 1-4 路线图 0 含 L0 风控, sprint period 22 PR 链 sustained 路线图执行优先, **真根因是路线图设计本身没把 L0 实时风控前置**

### Why 5: 为什么 Wave 1-4 路线图 0 含 L0 实时风控?

**user 假设答**: 沿用 framework §5.2 推翻 user 假设 — "项目按 Wave 推进是最佳" 假设可能错.

**实测真值**:
- Wave 1-4 路线图 sprint period sustained 沉淀 (QPB v1.16, sprint state 沉淀)
- Wave 1+2+3 是 platform skeleton + data + risk framework (V2 ADR-010 PMSRule 14:30 Beat = batch 风控, 非 event-driven)
- Wave 4 MVP 4.1 是 Observability (alert / monitor 非 enforce)
- L0 实时风控 = event-driven 实时 enforce, 与 Wave 1-4 设计哲学 (batch + monitor) 不同
- **真根因 (Why 5)**: **Wave 1-4 路线图设计哲学 = batch + monitor, 不是 event-driven enforce. L0 实时风控需要不同设计哲学 + 重大架构改变 (event sourcing 沿用, 但实时 enforce 层未设计)**

**Why 5 答**: ⚠️ **路线图设计哲学局限** — Wave 1-4 batch + monitor 哲学, L0 event-driven enforce 是路线图外维度, 需重大架构改变

---

## §3 5 Why 链总结 + 真根因

| Why | 答 |
|---|---|
| Why 1 (-29% 0 风控告警) | batch 5min Beat vs event-driven 架构选择 |
| Why 2 (batch 5min Beat 而非 event-driven) | L0 实施层未到位 (sprint period 5+1 层 L0 ❌ 0 repo sediment) |
| Why 3 (L0 未实施) | 项目优先级排序 — L0 非前推, 沿用 ADR-022 第 2 条 anti-pattern |
| Why 4 (优先级把 governance/Observability 排在 L0 前) | 路线图设计本身没把 L0 实时风控前置 (Wave 1-4 0 含) |
| **Why 5 (路线图 0 含 L0)** | **路线图设计哲学 = batch + monitor, L0 event-driven enforce 是哲学外维度** |

---

## §4 真根因 vs user 假设对比

| 用户假设 | 真根因 (5 Why 推到底) |
|---|---|
| "盘中盯盘 + 风控未设计" | **路线图设计哲学局限** (batch + monitor, L0 event-driven 哲学外) |
| "5min Beat 太慢" | batch vs event-driven 架构选择, batch 是路线图必然产物 |
| "T1.3 风控设计沉淀, 实施未到位" | T1.3 design 自身受路线图哲学限制 (sustained batch + 弱 enforce) |

**真根因深度**: user 假设 (实施层) → CC 实测 (路线图哲学层) — **深 1-2 层**

---

## §5 V3 设计 gap 评估 (沿用 framework §3.6)

T1.3 design doc (PR #181) 5+1 层 D-L0~L5 决议:
- L0 = real-time event-driven 风控 (新增维度) ✅ design
- L1 = batch 14:30 Beat (现 V2 PMSRule, 已落地)
- L2-L5 = 其他层 (sprint state 沉淀)

**V3 设计 gap**:
- ✅ L0 已 design (PR #181 沉淀)
- ❌ L0 0 实施 (沿用 sprint state Session 46 末 "L0/L2/L3/L4/L5 全 ❌ 0 repo sediment, memory only")
- ⚠️ V3 design 仅 design doc 342 行, 真接入点路径 (event sourcing → real-time enforce → broker_qmt sell only) 未 demonstrate

---

## §6 决策权边界审 (沿用 framework §3.6)

**现 0 自动 vs 设计 STAGED**:
- sprint period sustained (4-29) PT 暂停后, 决策权 = user 100% 手工
- T1.3 design doc 决议 STAGED (sprint state 沉淀): 0 自动 → 半自动 (Claude 决议) → 自动 (CC 决议) — 3 stage
- **真现状**: 仍 stage 0 (0 自动), STAGED 路径未推进

**决策权边界 finding**:
- F-D78-20 [P2] 4-29 后 STAGED 决策权路径 0 推进, T1.3 design 仅 design doc, 真生产仍 user 100% 手工

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-21** | **P0 治理** | **4-29 PT 暂停事件真根因 (5 Why 推到底): Wave 1-4 路线图设计哲学局限 = batch + monitor, L0 event-driven enforce 是哲学外维度. user 假设"实施层未到位"深 1-2 层** |
| F-D78-22 | P2 | T1.3 V3 design doc 342 行沉淀但真接入点路径未 demonstrate (event sourcing → real-time enforce → broker_qmt sell only) |
| F-D78-20 | P2 | 4-29 后 STAGED 决策权路径 0 推进, 真生产仍 user 100% 手工 |

---

## §8 实测证据 cite

- 4-29 事件: sprint state Session 44 (Anthropic memory project_sprint_state.md frontmatter)
- T1.3 design: docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md (PR #181, 342 行)
- 5+1 层: ADR-022 §7.3 + sprint state Session 46 末
- Wave 1-4 路线图: docs/QUANTMIND_PLATFORM_BLUEPRINT.md (QPB v1.16)
- 真账户实测: snapshot/07_business_state.md §1

---

**文档结束**.
