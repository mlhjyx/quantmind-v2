# ROOT_CAUSE_ANALYSIS — 22 P0 治理 5 Why 整合

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 8 / ROOT_CAUSE_ANALYSIS
**Date**: 2026-05-01
**Type**: 整合 22 P0 治理 finding 真根因 5 Why

---

## §0 元说明

Phase 1-7 累计 22 P0 治理 finding sustained sustained sustained, 部分已 5 Why 推到底 (e.g. F-D78-21 risk/01 sustained), 部分仅 finding 描述未深推 root cause. 本 md 整合**真根因 5 Why** for 22 项 P0 治理.

---

## §1 22 P0 治理 真根因汇总

### 1.1 真生产 enforce cluster (10 项 P0 治理, 同源 root cause)

| Finding | 表层 | 5 Why 真根因 |
|---|---|---|
| F-D78-8 | 5 schtask 持续失败 | **Why 5: Wave 4 Observability 'self-health' design vs 真生产 enforce 候选 vacuum** (sprint period sustained "完工" 仅 PR merge, 真生产 enforce 0 sustained verify) |
| F-D78-61 | risk_event_log 仅 2 audit log entries | **Why 5: Wave 1-4 路线图哲学局限 = batch + monitor, L0 event-driven enforce 漏维度** (sustained F-D78-21 同源) |
| F-D78-62 | event_outbox 0/0 真使用 | **Why 5: ADR-003 Event Sourcing design vs 真生产 disconnect** (4-29 PT 暂停后 event source 0 produce + Beat publisher 真 connect 0 verify) |
| F-D78-89 | 路径 3 (PT→风控→broker) 0 active | **Why 5: 4-29 PT 暂停 sustained + 5+1 层 1/6 实施** (sustained F-D78-21 路线图哲学局限) |
| F-D78-115 | intraday_risk_check 73 error | **Why 5: position_snapshot mode='paper' 0 行 命名空间漂移** (sustained F-D78-229/232 加深 verify) |
| F-D78-116 | alert_dedup 38 fires + 3 schtask 0 alert | **Why 5: alert routing 部分 enforce 但 silent failure cluster 漏告警 sustained** (Wave 4 MVP 4.1 batch 1 ✅ but batch 2 self-health 失败 sustained) |
| F-D78-119 | intraday silent failure 0 通知 | **Why 5: 铁律 33 enforcement 失败** (sprint period sustained 沉淀 silent_failure 反 anti-pattern 但 真生产 0 enforce) |
| F-D78-183 | minute_bars 7d 0 增量 | **Why 5: Baostock incremental pipeline 真断 sustained sustained sustained 0 sustained 度量** (4-29 PT 暂停 / API issue / pipeline pause / etc 真根因 candidate 未深查) |
| F-D78-195 | 路径 1 全 step silent failure | **Why 5: 多 step (Baostock+IC+SignalComposer+PT) sustained 同源 5 Why 路线图哲学局限** |
| F-D78-208 | AI 闭环 Step 1-2-3 disconnect | **Why 5: Step 1 PT PAUSED + Step 2 GP weekly mining 0 真产出 + Step 3 0 实施 = 三步走战略 sustained design only** |

### 1.2 治理 over-engineering cluster (4 项 P0 治理, 同源 root cause)

| Finding | 表层 | 5 Why 真根因 |
|---|---|---|
| F-D78-19 | sprint period 22 PR 治理 sprint period | **Why 5: 1 人项目走企业级 4 源协作 N×N 同步 集中爆发 in CLAUDE.md 30 day 103 commits churn** (sustained F-D78-147 sustained 同源) |
| F-D78-26 | 4 源协作 N×N 漂移 broader 84+ | **Why 5: 1 人项目走企业级理念** (sustained F-D78-28 candidate 推翻 P1) |
| F-D78-147 | CLAUDE.md 30 day 103 commits 极高 churn | **Why 5: ADR-022 ex-post 沉淀但 ex-ante prevention 缺** (sustained F-D78-16 sustained 同源, handoff 数字必 SQL verify before 写候选 0 sustained) |
| F-D78-176 | 协作 ROI 量化 0 业务前进 | **Why 5: 真目标 candidate ≠ alpha 角度 = 治理 maturity** (sustained F-D78-33 同源) |

### 1.3 路线图哲学层 cluster (2 项 P0 治理)

| Finding | 表层 | 5 Why 真根因 |
|---|---|---|
| F-D78-21 | 4-29 PT 暂停真根因 | **Why 5: Wave 1-4 路线图设计哲学 = batch + monitor, L0 event-driven enforce 是哲学外维度** |
| F-D78-25 | 共同假设 "Wave 路线图最佳" 推翻 | **Why 5: 同 F-D78-21 路线图哲学局限同源** |

### 1.4 盲点 + 项目目标层 cluster (4 项 P0 治理)

| Finding | 表层 | 5 Why 真根因 |
|---|---|---|
| F-D78-33 | 项目目标 vs 真测产出 disconnect | **Why 5: User 隐含假设 "项目全职投入 = alpha generation" vs 真测投入产出 中性偏负** (sustained F-D78-31 同源) |
| F-D78-48 | 项目 bus factor 极低 | **Why 5: 1 人项目 + 4 源协作漂移 + 70-110 audit md 无 SOP + repo 自给自足度不足** |
| F-D78-53 | broker 单点 lock-in | **Why 5: 真账户单一 broker 设计 + 真金 ¥993K 全 lock-in + 替换难度极高** |
| F-D78-196 | Frontend 完整 0 audit cover | **Why 5: framework_self_audit 16 领域自身候选缺 frontend 维度** (sustained 反 §7.9 被动 follow Claude framework anti-pattern 自身复发) |

### 1.5 测试 + DB 数字漂移 cluster (2 项 P0 治理, 同源)

| Finding | 表层 | 5 Why 真根因 |
|---|---|---|
| F-D78-76 | 测试基线 +1212 漂移 | **Why 5: ADR-022 ex-ante prevention 缺 (handoff 数字必 SQL verify before 写候选 0 sustained)** (sustained F-D78-147/16 同源) |

---

## §2 5 大 root cause cluster 总结

| Root cause cluster | P0 治理 finding |
|---|---|
| **路线图哲学层** | F-D78-21/25/61/89/195 |
| **真生产 enforce silent failure** | F-D78-8/62/115/116/119/183/208 |
| **治理 over-engineering 1 人 vs 企业级** | F-D78-19/26/33/147/176 |
| **盲点 + framework 自身缺** | F-D78-48/53/196 |
| **数字漂移 ex-ante prevention 缺** | F-D78-76 |

---

## §3 真根因 cross-cluster 推断

实测 sprint period sustained:
- 5 root cause cluster 中 **3 cluster (路线图 + enforce + 治理 over-engineering)** sustained 同根: **1 人项目走企业级理念 + Wave 1-4 batch+monitor 哲学 + 4 源协作 N×N + 0 真生产 enforce sustained verify**
- 真根因总: **1 人项目 vs 企业级架构 disconnect + Wave 路线图哲学局限 + 协作模式 N×N**

候选 finding:
- F-D78-233 [P0 治理] 5 root cause cluster cross-cluster 推断: 3 cluster (路线图 + enforce + 治理) 同根 = 1 人项目 vs 企业级架构 disconnect (沿用 F-D78-28 candidate 推翻 P1 sustained 加深 P0 治理)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-233** | **P0 治理** | 5 root cause cluster cross-cluster 推断, 3 cluster 同根 = 1 人项目 vs 企业级架构 disconnect, sustained F-D78-28 候选 P1 加深 P0 治理 |

---

**文档结束**.
