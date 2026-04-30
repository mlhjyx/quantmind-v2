# Business Review — User 工作流 + 经济性 + 可持续性

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 4 / business/01
**Date**: 2026-05-01
**Type**: 评判性 + 经济性 + 5 Why (sustained framework §3.11 + WI 0 §3.1 D11 项目可持续性 + 1.5 Financial steward)

---

## §0 元说明

User D77 显式开放本审查 adversarial 推翻 user 假设 (沿用 framework §5.2). 本 md 走经济性 + 可持续性 深审 — 沿用 framework_self_audit §3.1 D11 项目可持续性 + 1.5 Financial steward 视角.

User 隐含假设 + CC 实测推翻 (沿用 blind_spots/02_user_assumptions §1.3-1.6) — 本 md 深化论据.

---

## §1 User 真日常工作流 (sprint period 真测)

实测 sprint period sustained user 工作流 (sprint state Session 1-46+ 累计):

### 1.1 工作流分布 (粗估 sprint period)

| 工作类 | 时间占比 | 真测 sprint period sustained sustained |
|---|---|---|
| Claude.ai 战略对话 | ~20% | sprint period 4-30 ~02:30 决议 + D72-D78 4 次反问跨日 |
| CC 实施监督 | ~30% | sprint period 22 PR 跨日 user reviewer 角色 |
| 真生产观察 (PT / schtask / etc) | ~20% | sprint period 4-29 ~10:25 紧急 emergency_close + 跨日 sustained 监控 |
| 因子研究 / 业务前进 | ~10% | sprint period 22 PR 0 业务前进印证 (governance sprint period) |
| 文档 review / handoff | ~20% | sprint state sustained 沉淀 + sprint state Session 22+ 累计 |

**真测 disconnect**:
- 业务前进 ~10% vs 治理 + 监督 + 战略 ~70% — 治理 sprint period 印证
- 真金 alpha-generation 时间投入低

---

## §2 经济性 5 Why 深挖 (沿用 blind_spots/02_user_assumptions §1.3)

### Why 1: 项目真金 ROI?

实测真值:
- 真金 NAV: ¥1,000,000 → ¥993,520.66 (sprint period sustained)
- 真期间 PT 累计: ~60 day (3-25 → 4-29 PT 暂停)
- 真金 ROI: ~-0.65% (60 day, 折年 ~-3.95% annualized)
- vs CLAUDE.md 目标: 年化 15-25% (远未达)

**Why 1 答**: 真金 ROI ~-0.65% vs 目标 15-25%, **真金 alpha-generation 失败**

### Why 2: 为什么真金 ROI 失败?

5+ candidate:
- 4-29 -29% 跌停事件 (一次性 -¥6,479)
- L0 实时风控 0 实施 → 跌停未防
- batch 5min Beat 风控太慢 (路线图设计哲学局限)
- CORE3+dv_ttm WF OOS 0.8659 vs 真期间 PT NAV ~0 disconnect (回测 vs 真生产 sim-to-real gap candidate)
- 真期间 PT 仅 ~25 day (3-25 → 4-12 沉淀 sprint period 沉淀 PT 配置切换 + 4-29 暂停 = 实际短期间)

**Why 2 答**: 多 root cause, 主导是 4-29 单事件 + L0 风控空缺

### Why 3: 为什么 L0 风控空缺?

(沿用 risk/01_april_29_5why §2 5 Why) — 路线图设计哲学局限.

### Why 4: 为什么路线图设计哲学局限?

User 假设 + Claude 沉淀: Wave 1-4 batch + monitor 哲学是企业级最佳实践 (12 framework + 6 升维 + 4 Wave 沉淀).

**真测**: 1 人项目 vs 企业级理念 disconnect (沿用 blind_spots/03_shared_assumptions §1.5 推翻).

### Why 5: 为什么 1 人项目走企业级理念?

User 隐含假设 + Claude 沉淀:
- "项目目标 = 真金 alpha-generation"
- "alpha 需企业级架构 (12 framework / 6 升维 / 等)"
- "企业级架构 = sprint period 治理 6 块基石"

**Why 5 真测推翻**: User 项目目标 vs 真测投入产出 disconnect (沿用 blind_spots/02_user_assumptions §1.5 F-D78-33).
- 真目标候选 ≠ alpha-generation
- 真目标候选 = 治理 maturity / Claude 协作 maturity / docs sustainability / etc

---

## §3 可持续性评估 (bus factor)

### 3.1 项目 bus factor 真测

实测真值:
- User 全职 1 人项目
- git history 90 day (F-D78-13)
- docs/ 270 *.md + 根目录 8 *.md (含 3 未授权 F-D78-5)
- 6 块基石治理沉淀 (3 ✅ + 2 ⚠️ + 1 🔴)
- 4 源协作 sustained 漂移 (F-D78-26)

**bus factor 真测**:
- User 退出 / 度假 / 健康问题 N 月后接手者:
  - 走 audit folder onboard? 本审查 sub-md 70-110 但缺自动化 SOP
  - 走 CLAUDE.md + sprint state? sprint state 漂移 + CLAUDE.md 与真生产 disconnect
  - 走 Claude.ai / CC 协作? 4 源协作 sustained 漂移
- 项目 idle / auto-recover:
  - Servy 4 服务 auto-restart? sustained 沉淀但本审查未深查 真 auto-restart 历史
  - schtask 自动? 5 schtask 持续失败 cluster 沉淀 silent failure 真生产 fail-loud 0
- **bus factor candidate = 极低** (1 人项目, 接手 onboarding 极困难, 真生产 self-recover 0 enforce)

### 3.2 finding

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-48** | **P0 治理** | 项目 bus factor 极低. User 退出 N 月后接手者 onboarding 极困难 (4 源协作漂移 + 70-110 audit md 无 SOP + 真生产 self-recover 0). 沿用 F-D78-13 (git history 90 day) + F-D78-41 (User 健康风险) |

---

## §4 决策权 audit (沿用 framework §3.11)

实测真值:
- 真生产决策: 4-29 PT 暂停 → user 100% 手工 (CC emergency_close 沿用 user 触发)
- T1.3 V3 design STAGED: 0 自动 → 半自动 → 自动 — 仍 stage 0
- panic SOP: 4-29 user emergency 触发 CC ad-hoc emergency_close — 无 sustained panic SOP runbook

**finding**:
- F-D78-49 [P1] panic SOP 沉淀 0 (4-29 ad-hoc), 候选 docs/runbook/cc_automation/panic_sop.md sustained 沉淀 (沿用 sprint period sustained "CC 自动化操作" 模式扩 panic candidate)

---

## §5 经济性 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-31 (复) | P1 | User 时间投入 vs 项目产出经济性候选推翻, NAV ~-0.65% + 0 业务前进 + 全职 N 月 |
| F-D78-33 (复) | P0 治理 | User 项目目标 (alpha 15-25%) vs 真测投入产出 (治理 + Observability) disconnect, 真目标候选 = 治理 maturity 而非 alpha |
| **F-D78-48** | **P0 治理** | 项目 bus factor 极低, User 退出 N 月后接手者 onboarding 极困难 |
| F-D78-49 | P1 | panic SOP 沉淀 0 (4-29 ad-hoc), 候选 docs/runbook/cc_automation/panic_sop.md sustained 沉淀 |

---

## §6 实测证据 cite

- 真金 NAV: snapshot/07_business_state §1 (xtquant 5-01 04:16 实测)
- PT 期间: sprint state Session 1-46 累计
- CLAUDE.md 目标: CLAUDE.md §项目概述 (sprint period sustained "年化15-25%, Sharpe 1.0-2.0, MDD <15%")
- 4-29 事件: sprint state Session 44 + risk/01_april_29_5why
- bus factor: snapshot/01_repo_inventory §3 (git history 90 day)

---

**文档结束**.
