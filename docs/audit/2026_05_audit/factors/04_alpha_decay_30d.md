# Factors Review — Alpha Decay 30d (CC 扩 M3)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / factors/04
**Date**: 2026-05-01
**Type**: 评判性 + alpha decay 真测 (sustained factors/01 §1.2 + factors/02 §2)

---

## §1 CORE3+dv_ttm 30 day rolling IC 真测候选

实测真值 (sustained factors/01 §1.2):
- turnover_mean_20: ic_20d=-0.0957 (sign -1 ✅)
- volatility_20: ic_20d=-0.0905 (sign -1 ✅)
- bp_ratio: ic_20d=+0.0586 (sign +1 ✅)
- dv_ttm: ic_20d=+0.0397 (sign +1 ✅, ratio=0.517 < 0.8 warning sustained F-D78-23)

(本审查未深查 30/90/180/365 day rolling IC 时序 trend, 沿用 F-D78-140 P2 sustained factors/02 §2)

---

## §2 Alpha decay 半衰期 candidate

实测 sprint period sustained sustained:
- LL-013/014 sustained "IC 衰减>50% 标记虚假 alpha" 沉淀 sustained sustained
- factor_ic_history schema 含 ic_ma20 + ic_ma60 + decay_level (sustained Phase 2 query)
- 真 decay_level distribution by factor 0 sustained sustained 度量 (本审查 partial)

候选 finding:
- F-D78-194 [P2] CORE3+dv_ttm alpha decay 30/90/180 day rolling IC 时序 trend 真测 0 sustained 度量, 沿用 F-D78-140 P2 sustained, decay_level 真 distribution by factor 0 sustained sustained sustained 度量

---

## §3 dv_ttm warning sustained 14 day 0 升级决议 (sustained F-D78-23)

实测 sprint period sustained:
- Session 5 (4-18) lifecycle warning ratio=0.517 < 0.8 sustained sustained
- 5-01 真测 IC=+0.0397 ✅ sign sustained but magnitude 候选 weak
- sprint period sustained sustained sustained 14 day 0 升级决议 sustained sustained

**finding** (sustained):
- F-D78-23 (复) [P2] dv_ttm warning sustained 4-18 → 5-01 14 day 0 升级决议

---

## §4 因子谱系图 + 拥挤度 (sustained factors/02 §3+4)

(沿用 [`factors/02_research_kb_completeness.md`](02_research_kb_completeness.md) §3+4 sustained F-D78-141/142 P3 sustained sustained)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-194 | P2 | CORE3+dv_ttm alpha decay 30/90/180 day rolling IC 时序真测 0 sustained, decay_level distribution 0 度量 |
| F-D78-23 (复) | P2 | dv_ttm warning sustained 14 day 0 升级决议 |

---

**文档结束**.
