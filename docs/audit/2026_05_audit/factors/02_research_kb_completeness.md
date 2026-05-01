# Factors Review — research-kb 完整性 + alpha decay candidate

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 4 / factors/02
**Type**: 评判性 + research-kb 沉淀 verify (CC 扩 M3 + framework_self_audit §3.4)

---

## §1 research-kb 沉淀 真测 (sustained sprint period sustained)

实测 sprint period sustained sustained:
- 8 failed (mf_divergence / 风险平价 / Phase 2.1 / 2.2 / 3B / 3D / 3E / etc)
- 25 findings
- 5 decisions
- (CLAUDE.md sustained §已知失败方向 sustained sustained "30+ 失败方向已沉淀")

**真测** (本审查未深查 docs/research-kb/* 全清单):
- 候选 finding: 真 8 + 25 + 5 = 38 条目 vs CLAUDE.md "30+" 沉淀 — 数字漂移候选

候选 finding:
- F-D78-139 [P3] research-kb 真清单 (failed / findings / decisions 全 enumerate) 0 sustained 实测, 沿用 CLAUDE.md "30+ 失败方向" sustained sustained vs sprint state Session 46 末 "8+25+5=38" sustained sustained, 候选数字漂移

---

## §2 alpha decay (CC 扩 M3 candidate, framework_self_audit §3.4)

(本审查未深查 CORE3+dv_ttm 历史 IC 时序 trend. 沿用 factors/01 §1.2 latest 4-28 IC sustained 真测 ✅)

候选深查 (待 sub-md):
- 30 day rolling IC mean by factor
- 90 day rolling IC mean
- 180 day rolling IC mean
- 365 day rolling IC mean
- alpha decay 半衰期分析 (沿用 IC 衰减>50% 标记虚假 alpha, LL-013/014)

候选 finding:
- F-D78-140 [P2] CORE3+dv_ttm alpha decay 历史 IC 时序 0 sustained sustained 度量 in 本审查, 候选 sub-md 详查 (factor_ic_history 113 distinct factor_name × time matrix 真测), sustained 铁律 4 (LL-013/014) sustained sustained 但 enforcement candidate

---

## §3 因子拥挤度 (CC 扩 M3, framework §3.4)

(本审查未深查 CORE3+dv_ttm vs 公开量化基金披露 / 学术因子 真重叠度. 候选 finding):
- F-D78-141 [P3] 因子拥挤度 0 sustained sustained 度量 (vs Qlib / RD-Agent / AQR 公开因子 真重叠 实测 candidate)

---

## §4 因子谱系图 (CC 扩 M3, framework §3.4)

(本审查未深查 CORE3+dv_ttm + 历史 deprecated 因子 谱系演进. 候选 finding):
- F-D78-142 [P3] 因子谱系图 0 sustained sustained sustained 沉淀, 候选 sub-md 详查 (CORE5 → CORE3+dv_ttm 真演进 + DEPRECATED 5 因子 真退役历史 sustained sprint period sustained sustained)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-139 | P3 | research-kb 真清单 0 sustained 实测, CLAUDE.md "30+" vs sprint state "38" 候选数字漂移 |
| F-D78-140 | P2 | CORE3+dv_ttm alpha decay 历史 IC 时序 0 sustained sustained 度量, 铁律 4 enforcement candidate |
| F-D78-141 | P3 | 因子拥挤度 0 sustained 度量 (vs 公开因子 真重叠) |
| F-D78-142 | P3 | 因子谱系图 0 sustained 沉淀 (CORE5 → CORE3+dv_ttm 真演进 + DEPRECATED 退役历史) |

---

**文档结束**.
