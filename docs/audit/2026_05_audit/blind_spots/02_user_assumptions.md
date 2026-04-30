# Adversarial — 推翻 User 假设清单

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 6 / blind_spots/02
**Date**: 2026-05-01
**Type**: adversarial review (sustained framework §5.2 — User D77 显式开放)

---

## §0 元说明

framework §5.2 沉淀: User 显式开放 CC 主动 flag user 假设错.

候选 (framework 列):
1. 4-29 痛点真根因 (user 假设 "盘中盯盘 + 风控未设计", 真根因可能更深)
2. PT 重启信心来源 (user 假设 "Tier A 完成 + paper-mode 5d → 重启", 真信心可能要更多)
3. 经济性假设 (user 时间投入 vs 项目产出)
4. 工作流假设 (Claude.ai + CC 协作真有效)

CC 主动扩 + 真推翻沉淀.

---

## §1 推翻 User 假设 — 真推翻清单

### 1.1 ⚠️ 推翻 "4-29 痛点真根因 = 盘中盯盘 + 风控未设计"

**User 假设** (sprint state Session 44 沉淀触发本次 sprint period sustained 假设): 4-29 PT 真生产事件 (-29% 跌停) 真根因 = 盘中盯盘失败 + 风控未设计.

**CC 实测推翻**: 已在 risk/01_april_29_5why §2 5 Why 推到底:
- Why 1: batch 5min Beat vs event-driven 架构 (user 假设方向对)
- Why 2: L0 实施未到位 (user 假设方向对)
- Why 3: 项目优先级排序 (深 1 层)
- Why 4: 路线图设计 (深 2 层)
- **Why 5: 路线图设计哲学 = batch + monitor, L0 event-driven 漏维度 (深 3 层)** — 真根因

**推翻深度**: User 假设 = Why 1-2 (盘中 + 实施) → 真根因 = Why 5 (路线图哲学), 深 3 层

**关联 finding**: F-D78-21 [P0 治理] (复述) — 5 Why 真根因路线图哲学局限

---

### 1.2 ⚠️ 推翻 "PT 重启 prerequisite = Tier A 完成 + paper-mode 5d → 重启"

**User 假设** (sprint state Session 45 修订, sprint period sustained): PT 重启 prerequisite = Tier A code 完工 + paper-mode 5d dry-run + .env paper→live 用户授权 → 重启.

**CC 实测推翻**: 已在 blind_spots/03_shared_assumptions §1.6 推翻:
- 5d dry-run 检测什么? 未明确
- paper-mode 5d ≠ live 真账户 5d (paper-mode 0 真金, 仍漏 4-29 类事件)
- 真根因路线图哲学 (Why 5), **5d dry-run 不能解决路线图哲学问题**

**推翻深度**: prerequisite 是 sufficient 假设漏, 真 sufficient 需 L0 风控落地 + 路线图调整

**关联 finding**: F-D78-29 [P1] (复述)

---

### 1.3 (CC 主动扩) ⚠️ 推翻 "User 时间投入 vs 项目产出" 经济性假设

**User 隐含假设**: 项目全职投入是合理的 (user_profile sustained "全职量化开发者, 期望 Team Lead 主动推进").

**CC 实测推翻 candidate**:

**项目产出真值**:
- 真金 NAV: ¥1,000,000 → ¥993,520.66 (sprint period sustained, **小幅亏损 ~-0.65%**)
- PT 期间 ~60 day (3-25 启动 → 4-29 暂停), Sharpe 1.0+ 预期 vs 真期间 ~0 (PT 暂停 + 清仓)
- alpha-generation 真业务前进: sprint period 22 PR 0 业务前进 (governance sprint period)

**User 时间投入** (sprint period 真测):
- D72-D78 4 次反问 + 跨日多 sprint period sustained 工作 (sprint state sustained 沉淀 user 全职投入)
- sprint period 22 PR 治理 sprint period 大头 docs/ 沉淀 — user 时间投入大量在 docs/ review 而非 alpha generation

**经济性 candidate 推翻**:
- 全职投入 N 月 → 真金亏损 ~-0.65% + 0 业务前进 — **经济性假设 candidate 不成立**
- 项目从 alpha generation 视角看 ROI 中性偏负
- User 时间机会成本 (vs 全职薪酬 / 等同等价) 远超项目产出

**推翻深度**: User 隐含 "项目全职投入合理" 假设 — 真测 ROI 中性偏负, 经济性 candidate 推翻

**finding**:
- **F-D78-31 [P1]** User 时间投入 vs 项目产出经济性假设候选推翻. 真金 NAV ~-0.65% + 0 业务前进 + 全职 N 月 — ROI 中性偏负, 候选经济性重审

---

### 1.4 (CC 主动扩) ⚠️ 推翻 "Claude.ai + CC 协作模式真有效" 工作流假设

**User 隐含假设**: Claude.ai 战略对话 + CC 实施 双角色协作真有效.

**CC 实测推翻 candidate**:

**漂移真测** (沿用 blind_spots/03_shared_assumptions §1.2 4 源协作):
- Claude.ai 沉淀 vs CC 实测 不同步 (sprint state 4-28 vs 4-27 / 5 vs 4 entries / etc)
- D72-D78 4 次反问 + Claude 4 次错读 印证 协作产生 N+ 错读 episode

**真有效 vs 真无效**:
- 协作 maturity: 22 PR 链 / sprint period sustained / 6 块基石 — 表面 maturity 高
- 真生产 enforce 失败 (5 schtask + 4-29 PT 暂停) 印证 协作产出在治理层 vs 真生产层 disconnect

**推翻深度**: 协作模式表面 maturity 高 vs 真生产 enforce 失败 — 协作有效性 candidate 推翻

**finding**:
- **F-D78-32 [P1]** 协作模式 (Claude.ai + CC + memory + repo 4 源) 候选推翻有效性. 治理层 maturity 高 vs 真生产层 enforce 失败 disconnect, D72-D78 4 次反问 印证

---

### 1.5 (CC 主动扩) ⚠️ 推翻 "User 项目目标 = 真金 alpha-generation"

**User 隐含假设** (CLAUDE.md sustained): 项目目标 = 年化 15-25% / Sharpe 1.0-2.0 / MDD <15%.

**CC 实测推翻 candidate**:

**真生产 vs 目标**:
- 真期间 PT NAV -0.65% (远未达 15-25% 年化)
- Sharpe 真期间未达 1.0 (PT 暂停 + 清仓终结期间)
- MDD 真期间未达 <15% (4-29 -29% 跌停事件超 15% 阈值)

**User 投入 vs 目标 vs 真测**:
- 全职投入 N 月真测产出 0 业务前进 (sprint period 22 PR 治理)
- alpha-generation 候选目标 vs 真测协作模式产出 (治理 + Observability 沉淀) **目标 vs 真测 disconnect**

**推翻深度**: User 项目目标真测 unachieved, 真测投入产出在治理层而非 alpha-generation, **真目标 candidate ≠ 表面目标**

**finding**:
- **F-D78-33 [P0 治理]** User 项目目标 (alpha generation 15-25%/ Sharpe 1.0-2.0) vs 真测投入产出 (治理 + Observability 沉淀) disconnect, 真目标 candidate 是治理 maturity 而非 alpha generation, 候选目标重审

---

### 1.6 (CC 主动扩) ⚠️ 推翻 "User D72-D78 4 次反问后 D78 决议 (一次性 + 0 修改 + 0 时长) 是终极反 sprint period treadmill"

**User 假设** (D78 决议本身): 一次性审完 + 0 修改 + 0 时长 + 不分 Phase = 终极反 sprint period treadmill 决议.

**CC 实测**: 已在 framework_self_audit §1.3 评估:
- 一次性 ✅ 反 sprint period treadmill 大体合理
- 0 修改 ✅ read-only audit 大体合理
- 0 时长 ✅ CC 自决议大体合理
- 不分 Phase ✅ 反 sprint period treadmill 大体合理
- **但风险**: context limit + P0 真金例外 + scope 物理边界 (framework_self_audit §1.3 4 风险)

**推翻 candidate**:
- D78 决议是 reactive 反 sprint period treadmill (sprint period 22 PR 链触发 user 不耐烦后 4-30 ~02:30 决议)
- 反 sprint period treadmill 自身可能是新一轮 sprint period 起点 (本审查 70-110 sub-md ≈ 新 sprint period)
- D78 假设 "一次性审完所有" 物理可行 — 本审查实测 context limit 风险 sustained, 候选 D78 假设过乐观

**finding**:
- F-D78-34 [P2] D78 决议本身候选不完美 (context limit 风险 + 反 sprint period treadmill 自身可能新 sprint period 起点). 沉淀候选, 不本审查推翻 (沿用 D78 sustained, 仅 finding 沉淀)

---

## §2 真推翻 vs 部分推翻 vs 候选推翻 总结

| User 假设 | 推翻判定 | 关联 finding |
|---|---|---|
| 4-29 痛点真根因 = 盘中 + 风控未设计 | ⚠️ 部分推翻 (深 3 层) | F-D78-21 [P0 治理] |
| PT 重启 prerequisite = paper-mode 5d | ⚠️ 推翻 | F-D78-29 [P1] |
| User 时间投入 vs 产出经济性 (CC 扩) | ⚠️ 候选推翻 | F-D78-31 [P1] |
| Claude.ai + CC 协作有效 (CC 扩) | ⚠️ 候选推翻 | F-D78-32 [P1] |
| User 项目目标 = alpha generation (CC 扩) | ⚠️ 候选推翻 | F-D78-33 [P0 治理] |
| D78 决议本身终极反 treadmill (CC 扩) | ⚠️ 候选不完美 | F-D78-34 [P2] |

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-31 | P1 | User 时间投入 vs 项目产出经济性候选推翻, NAV ~-0.65% + 0 业务前进 + 全职 N 月 ROI 中性偏负 |
| F-D78-32 | P1 | 协作模式 (Claude.ai + CC + memory + repo 4 源) 候选推翻有效性, 治理层 maturity vs 真生产层 enforce disconnect |
| **F-D78-33** | **P0 治理** | **User 项目目标 (alpha 15-25%) vs 真测投入产出 (治理 + Observability) disconnect, 真目标候选 = 治理 maturity 而非 alpha** |
| F-D78-34 | P2 | D78 决议本身候选不完美 (context limit 风险 + 反 treadmill 可能新 sprint period 起点) |

---

**文档结束**.
