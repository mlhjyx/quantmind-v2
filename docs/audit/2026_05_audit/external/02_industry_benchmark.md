# External Review — 行业对标 (vs Qlib / RD-Agent / 公开量化基金)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / external/02
**Date**: 2026-05-01
**Type**: 评判性 + 行业对标 (sustained framework §3.12)

---

## §1 sprint period sustained 行业对标 沉淀

实测 sprint period sustained sustained:
- **Qlib 阶段0 调研 NO-GO** (sprint state Session 10b 2026-04-10): "三重阻断 / .bin 双份数据 / 回测无 PMS 涨跌停"
- **RD-Agent 阶段0 调研 NO-GO** (同上)
- **24-Project Landscape Analysis** (sprint state Session 36 2026-04-26): docs/research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md sustained 沉淀
- 30 模式索引 (memory project_borrowable_patterns sustained, ADR-012/013 sustained)

---

## §2 真对标候选 (本审查未深查)

| 对标 | sprint period sustained | 真对标 candidate (待深查) |
|---|---|---|
| Qlib (微软) | NO-GO 沿用 4-10 调研 | 真 deep dive 1 年后 sprint period sustained 0 sustained 复审 (沿用 memory project_research_nogo_revisit sustained "U1 Parity / U3 Lineage / U5 Attribution 完成后重试") |
| RD-Agent (微软) | NO-GO 同源 | 同上候选复审 |
| AQR / Two Sigma / 等公开因子披露 | (sprint period 0 sustained sustained 真对标) | 因子拥挤度真测 candidate (F-D78-141 sustained sustained) |
| LightGBM Synthesis (Phase 3D NO-GO) | NO-GO 沉淀 4-14 | sprint period sustained "ML 预测层 CLOSED" 沉淀 sustained 真重审 candidate |

**finding**:
- F-D78-159 [P2] 行业对标 sprint period sustained NO-GO sustained 沉淀 (Qlib / RD-Agent / 30 模式) 但真深 dive 真 vs 当前 candidate 0 sustained sustained 复审, 沿用 memory project_research_nogo_revisit "7 项研究 NO-GO 是当前基建下 FAIL 非永久封案" sustained

---

## §3 学术 methodology 对标 candidate (CC 扩 M1)

(详 [`external/03_academic_methodology.md`](03_academic_methodology.md))

---

## §4 投资人 ROI 视角 (sustained framework §3.12)

实测 sprint period sustained sustained:
- 项目个人投资性质 sustained sustained
- 真金 ¥993,520.66 (sustained snapshot/07 §1)
- 真 ROI ~-0.65% / 60 day (business/03 §1)
- vs 投资人 benchmark (e.g. 沪深 300 / etc) 真对标 0 sustained sustained sustained 度量

候选 finding:
- F-D78-160 [P3] 投资人 ROI 真对标 (vs benchmark index) 0 sustained sustained 度量, sprint period sustained sustained 0 sustained 真 benchmark 数据 (沪深 300 / 中证 500 / etc 60 day 真值 vs PT 真值 reconciliation candidate)

---

## §5 新人 onboarding 难度 + 知识可持续性 (sustained framework §3.12)

(详 [`governance/02_knowledge_management.md`](../governance/02_knowledge_management.md) §2 + §3 sustained F-D78-51/52 P1)

---

## §6 跨 LLM session continuity (sustained framework §3.12)

(详 governance/02 §2 sustained sustained)

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-159 | P2 | 行业对标 (Qlib / RD-Agent / 30 模式) sprint period NO-GO 沉淀 sustained 但真深 dive 真 vs 当前 candidate 0 sustained 复审 |
| F-D78-160 | P3 | 投资人 ROI 真对标 (vs benchmark index) 0 sustained 度量 |

---

**文档结束**.
