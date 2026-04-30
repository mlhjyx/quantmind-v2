# Adversarial — 推翻共同假设 (Claude+user 都没意识到的)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 6 / blind_spots/03
**Date**: 2026-05-01
**Type**: adversarial review (sustained framework §5.3 — 最深盲点)

---

## §0 元说明

framework §5.3 沉淀: "最深盲点. Claude+user 共同假设但都没意识到错的事".

候选 (framework 列):
1. "项目按 Wave 推进是最佳" vs 推翻重做 / 简化
2. "sprint period 治理 6 块基石是 governance 胜利" vs over-engineering
3. "因子研究 + 风控 + 回测 三领域都需要 V3 升级" vs 仅风控 / 仅因子 / 不升级
4. "memory + repo + Claude.ai + CC 4 源协作有效" vs 协作冗余 + 漂移

CC 主动扩 + 真推翻沉淀.

---

## §1 推翻共同假设 — 真推翻清单

### 1.1 🔴 推翻 "项目按 Wave 推进是最佳"

**共同假设**: 项目按 Wave 1+2+3+4 顺序推进是最佳路径, 完成 Wave 4 后再 Wave 5+ (沿用 QPB v1.16 sprint period sustained).

**CC 实测推翻**:
- Wave 1+2+3 已完结 → Wave 4 MVP 4.1 进行中 → Wave 5+ 未启
- L0 实时风控 (5+1 层 D-L0~L5 V3 design 关键层) 0 在 Wave 1-4 路线图 (路线图设计哲学局限, 沿用 risk/01_april_29_5why §2 Why 5)
- **真生产 4-29 PT 暂停事件 印证 Wave 路线图 0 把 L0 风控前置, 4-29 真金 -¥6,479 损失** (cash 999,999 → 993,520 sprint period sustained 沉淀)
- Wave 4 Observability "完工" 假设 已被 5 schtask 持续失败推翻 (F-D78-8)

**推翻深度**: Wave 路线图设计本身有缺陷 — batch + monitor 哲学 vs event-driven enforce 维度漏

**finding**:
- **F-D78-25 [P0 治理]** 共同假设 "Wave 路线图最佳" 推翻. Wave 1-4 设计哲学 = batch + monitor, L0 event-driven enforce 是路线图外维度. 4-29 真金 ~¥6,479 损失印证

---

### 1.2 🔴 推翻 "memory + repo + Claude.ai + CC 4 源协作有效"

**共同假设**: 4 源协作 (Anthropic memory + git repo + Claude.ai 战略对话 + CC 实施) 是高效协作模式.

**CC 实测推翻**:

**漂移真测** (跨源 inconsistency):
- sprint state (memory) 写 "DB 4-28 stale" vs 真值 4-27 (差 1 天) → memory 漂移
- sprint state 写 "5 schedule entries 生产激活" vs Beat 实测 4 active → memory vs 代码源不同步
- sprint state 写 "T0-19 已 closed" vs DB live snapshot 仍 stale → memory vs DB 真值不一致
- CLAUDE.md 写 "152 chunks" vs 实测 chunk ID 已超 200+ → repo CLAUDE.md vs DB 真值不一致
- CLAUDE.md §文件归属规则写 "根目录 7 上限" vs 实测 8 → repo CLAUDE.md vs repo 实际状态不一致

**协作冗余真测**:
- 4 源同 fact 描述多份 (e.g. PT 状态在 memory + CLAUDE.md + sprint state Session 内 多次描述) — N+ 同步成本
- ADR-022 反"数字漂移高发" sprint period sustained 但 enforcement 失败 (上述漂移仍 active)

**推翻深度**: 4 源协作产生 N×N 同步矩阵, 任一源更新需手动同步其他 N-1 源, sprint period sustained 22 PR 大量 docs 同步操作 (governance/01_six_pillars_roi §3 治理 sprint period 论证) 印证

**finding**:
- **F-D78-26 [P0 治理]** 共同假设 "4 源协作有效" 推翻. 4 源 N×N 同步矩阵 sustained 漂移 (F-D78-1/5/7/9/13 5 漂移 finding 印证), sprint period 治理 sprint period 大头是 4 源同步 overhead

---

### 1.3 ⚠️ 推翻 "sprint period 治理 6 块基石是 governance 胜利"

**共同假设**: sprint period 22 PR 沉淀 6 块基石 = 治理胜利, 项目治理 maturity ↑.

**CC 实测推翻**: 已在 governance/01_six_pillars_roi + blind_spots/01_claude_assumptions §1.2/§1.3 推翻.

**推翻汇总**:
- 3/6 块基石 ✅ + 2/6 ⚠️ + 1/6 🔴
- sprint period 22 PR 是 治理 sprint period (0 业务前进)
- ADR-022 反 sprint period treadmill 自身是 sprint period 沉淀 (反 anti-pattern 自身复发)

**关联 finding**: F-D78-19 [P0 治理]

---

### 1.4 ⚠️ 推翻 "因子研究 + 风控 + 回测 三领域都需要 V3 升级"

**共同假设**: 项目下一阶段需要因子 V3 + 风控 V3 + 回测 V3 同步升级 (Wave 5+ 候选 sustained).

**CC 实测推翻**:
- 因子: 9+ NO-GO 沉淀 (Phase 2.1/2.2/3B/3D/3E 全 FAIL), CORE3+dv_ttm = 等权 alpha 上限 sprint period sustained → **因子 V3 升级 ROI 不明** (待重评估)
- 风控: T1.3 V3 design doc 342 行沉淀 (PR #181), L0 ❌ 0 实施 → **风控 V3 升级 ROI 高 (4-29 真金损失印证)**
- 回测: regression max_diff=0 sustained sustained, 但本审查未深查真 enforcement → **回测 V3 升级 ROI 不明**

**推翻深度**: 三领域 V3 升级 ROI 不对等, **风控 V3 应该独立优先 vs 三领域同步**.

**finding**:
- **F-D78-27 [P1]** 共同假设 "三领域 V3 同步升级" 推翻. 风控 V3 ROI 高 (4-29 真金损失), 因子+回测 V3 ROI 不明. 候选优先级调整 (风控 V3 独立优先)

---

### 1.5 (CC 主动扩) 推翻 "1 人量化项目走企业级架构"

**共同假设** (CC 主动扩): 项目走 12 framework + 6 升维 + 4 Wave 等企业级架构.

**CC 实测**: 
- 项目实际 = 1 人 / 32GB RAM / 单机 / Servy 4 服务
- 12 framework + 6 升维 = 企业级 multi-team 架构理念
- sprint period 治理基础设施 6 块基石 = 企业级治理 (ATAM / ADR / IRONLAWS / TIER0_REGISTRY / etc)
- **真适配?** 1 人项目走 5+ 重治理 治理 vs alpha-generation 投入产出比 中性偏负 (sprint period 22 PR 0 业务前进印证)

**推翻深度**: 项目治理 over-engineering 候选, 沿用 framework_self_audit §1.4 ADR-022 reactive 局限 + governance/01_six_pillars_roi §2 总评

**finding**:
- **F-D78-28 [P1]** 共同假设 "1 人量化走企业级架构" 候选推翻. 12 framework + 6 升维 + 4 Wave + 6 块基石 = 企业级理念, 1 人项目 ROI 中性偏负 (sprint period 治理 sprint period 0 业务前进印证). 候选简化 candidate

---

### 1.6 (CC 主动扩) 推翻 "PT 重启 prerequisite 5d dry-run + paper-mode 是充分条件"

**共同假设** (sprint state sustained): PT 重启需要 paper-mode 5d dry-run + .env paper→live 用户授权.

**CC 实测**:
- 5d dry-run 检测什么? **未明确** (sprint state 沉淀 sustained 但未列具体检测项)
- paper-mode 5d dry-run vs live 真账户 5d sustained 是否等价? 候选 NO — paper-mode 0 真金风险, 5d dry-run 仍可能漏 4-29 类事件 (跌停 + L0 风控空缺)
- 真根因 (4-29 5 Why) = 路线图设计哲学局限, **5d dry-run 不能解决路线图哲学问题**

**推翻深度**: PT 重启 prerequisite (5d dry-run) 是 sufficient 假设漏 — 真 sufficient 需要 L0 风控落地 + 路线图调整

**finding**:
- **F-D78-29 [P1]** 共同假设 "PT 重启 5d dry-run + paper-mode = 充分条件" 推翻. 真 sufficient 需要 L0 风控落地 + 路线图调整 (5 Why 真根因, F-D78-21). 候选: PT 重启 prerequisite 重审, 不仅 dry-run

---

### 1.7 (CC 主动扩) 推翻 "audit / sub-md / 治理沉淀越多越好"

**共同假设** (Claude + CC sustained 行为): audit md / sprint period sustained 沉淀越多越好.

**CC 实测**:
- 项目 docs/ 270 *.md (本审查 5-01 实测) — 文档量已巨大
- sprint period 22 PR 大头是 docs/ 沉淀 (governance/01 §3 论证)
- 本审查本身在写 30+ audit md (按 framework_self_audit §3.2 估算 70-110 sub-md)
- **真 ROI?** 文档沉淀越多 → 文档间漂移 N×N 矩阵 → ADR-022 反"数字漂移" 自我推翻

**推翻深度**: 文档治理 over-engineering 反向 anti-pattern — 文档越多漂移越多

**finding**:
- **F-D78-30 [P1]** 共同假设 "audit / 治理沉淀越多越好" 候选推翻. 文档沉淀 N×N 漂移矩阵, ADR-022 反"数字漂移" 自我推翻. 候选: 文档审 sprint period 启动 (合并 / 删 / 简化)

---

## §2 真推翻 vs 部分推翻 vs 候选推翻 总结

| 共同假设 | 推翻判定 | 关联 finding |
|---|---|---|
| 项目按 Wave 推进最佳 | 🔴 真推翻 | F-D78-25 [P0 治理] |
| 4 源协作有效 | 🔴 真推翻 | F-D78-26 [P0 治理] |
| sprint period 6 块基石治理胜利 | ⚠️ 部分推翻 | F-D78-19 (复) [P0 治理] |
| 三领域 V3 同步升级 | ⚠️ 推翻 | F-D78-27 [P1] |
| 1 人量化走企业级架构 (CC 扩) | ⚠️ 候选推翻 | F-D78-28 [P1] |
| PT 重启 5d dry-run = 充分条件 (CC 扩) | ⚠️ 推翻 | F-D78-29 [P1] |
| audit 沉淀越多越好 (CC 扩) | ⚠️ 候选推翻 | F-D78-30 [P1] |

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-25** | **P0 治理** | 共同假设 "Wave 路线图最佳" 推翻, 路线图设计哲学局限 (batch + monitor 哲学, L0 event-driven 漏维度), 4-29 真金损失印证 |
| **F-D78-26** | **P0 治理** | 共同假设 "4 源协作有效" 推翻, 4 源 N×N 同步矩阵 sustained 漂移 (5 漂移 finding 印证) |
| F-D78-27 | P1 | 共同假设 "三领域 V3 同步升级" 推翻, 候选风控 V3 独立优先 |
| F-D78-28 | P1 | 共同假设 "1 人量化走企业级架构" 候选推翻 (CC 扩), 候选简化 candidate |
| F-D78-29 | P1 | 共同假设 "PT 重启 5d dry-run = 充分条件" 推翻 (CC 扩), 候选 prerequisite 重审 |
| F-D78-30 | P1 | 共同假设 "audit 沉淀越多越好" 候选推翻 (CC 扩), 候选文档审 sprint period 启动 |

---

**文档结束**.
