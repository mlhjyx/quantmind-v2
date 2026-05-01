# Factors Review — Factor Lifecycle + Health (sustained factors/01)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / factors/03
**Date**: 2026-05-01
**Type**: 评判性 + factor lifecycle Beat 真触发 + warning factors

---

## §1 factor_lifecycle Beat 真触发 verify

实测 sprint period sustained sustained:
- Beat schedule: `factor-lifecycle-weekly` 周五 19:00 (snapshot/03 §2.1 ✅ active)
- scheduler_task_log 真值 (Phase 3): factor_health_daily warning 3 entries in 7 day
- sprint state Session 5 (4-18) 沉淀: dv_ttm warning ratio=0.517 < 0.8

---

## §2 dv_ttm warning sustained 真测

实测 sprint period sustained sustained:
- dv_ttm Session 5 (4-18) lifecycle ratio=0.517 < 0.8 warning
- sprint period sustained sustained "未升级决议" sustained sustained sustained
- F-D78-23 P2 sustained sustained sustained 候选

**真测 Phase 4** (factors/01 §1.2):
- dv_ttm 4-28 IC=+0.0397 ✅ sign sustained, magnitude reasonable
- ratio 0.517 vs threshold 0.8 — warning 仍 active candidate

**finding**:
- F-D78-23 (复) [P2] dv_ttm warning sustained 4-18 → 5-01 14 day 0 升级决议
- F-D78-178 [P3] factor_health_daily Beat 7 day 3 warning 真触发, 沿用 F-D78-23 dv_ttm warning + 候选其他 factor warning enumerate (本审查未深查 真 warning factor 全清单)

---

## §3 factor 退役 / lifecycle 决议路径 真测

实测 sprint period sustained sustained:
- DEPRECATED 5: momentum_5/momentum_10/momentum_60/volatility_60/turnover_std_20 (CLAUDE.md sustained sustained)
- INVALIDATED 1: mf_divergence (sprint period sustained sustained sustained, 沉淀 sprint period research-kb)

**真测**: 5 DEPRECATED + 1 INVALIDATED sustained sustained sustained sprint period sustained sustained sustained

候选 finding:
- F-D78-179 [P3] factor 退役决议路径 sustained sprint period sustained sustained sustained 0 sustained 文档化 SOP, sprint period sustained "DEPRECATED 5 + INVALIDATED 1" sustained sustained 但真退役流程 (warning → DEPRECATED → INVALIDATED 状态机 / 真触发条件 / 真审批) 0 sustained sustained sustained 沉淀

---

## §4 factor 拥挤度 + alpha decay (CC 扩 candidate, sustained factors/02 §2-3)

(详 [`factors/02_research_kb_completeness.md`](02_research_kb_completeness.md) §2-3 sustained F-D78-140/141 sustained candidate)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-23 (复) | P2 | dv_ttm warning sustained 4-18 → 5-01 14 day 0 升级决议 |
| F-D78-178 | P3 | factor_health_daily Beat 7 day 3 warning 真触发, 候选 warning factor 全清单 enumerate |
| F-D78-179 | P3 | factor 退役决议路径 0 sustained 文档化 SOP (warning → DEPRECATED → INVALIDATED 真状态机) |

---

**文档结束**.
