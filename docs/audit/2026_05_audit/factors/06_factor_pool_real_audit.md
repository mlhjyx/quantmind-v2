# Factors Review — 因子池真测 (active / pass / deprecated / invalidated)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 7 WI 4 / factors/06
**Date**: 2026-05-01
**Type**: 评判性 + 因子池真清单 (sustained CLAUDE.md sustained §因子池状态)

---

## §1 sprint period sustained 因子池 vs 真测

实测 sprint period sustained sustained CLAUDE.md §因子池状态:

| 池 | sprint period sustained | 真测 |
|---|---|---|
| CORE (Active, PT 在用) | 4 (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm) | ✅ factors/01 §1.2 真测 IC sustained sign 全 align |
| CORE5 (前任) | 5 (含 reversal_20 + amihud_20) | (sprint period sustained 沉淀 sustained) |
| PASS 候选 | 32+16 (Alpha158 六 + PEAD-SUE + 16 微结构) | (sprint period sustained 沉淀 sustained) |
| INVALIDATED | 1 (mf_divergence) | (sprint period sustained sustained) |
| DEPRECATED | 5 (momentum_5/10/60 + volatility_60 + turnover_std_20) | (sprint period sustained sustained) |
| 北向个股 RANKING | 15 | (sprint period sustained sustained) |
| LGBM 特征集 | 70 | (sprint period sustained sustained) |

**真测 vs sprint period 沉淀**:
- 真 factor_values DISTINCT factor_name = **276** (factors/01 §1.1 sustained F-D78-58 P2 sustained)
- 真 factor_ic_history DISTINCT factor_name = **113** (factors/01 §1.1)
- sprint period sustained "70 LGBM 特征集" + "32 PASS" + "4 CORE" + "16 微结构" + "15 北向" + "5 DEPRECATED" + "1 INVALIDATED" 累计 ~143 vs 真 276 = **+133 候选差** (历史 + 实验 + 未沉淀因子)

**🔴 finding**:
- **F-D78-223 [P2]** sprint period sustained 因子池清单 sustained 沉淀累计 ~143 vs 真 factor_values 276 distinct = +133 候选差 (历史 + 实验 + 未沉淀因子), sprint period sustained sustained sustained 0 sustained sustained sync update CLAUDE.md §因子池状态 真清单 sustained sustained 沉淀

---

## §2 因子真 IC 入库率

实测真值:
- factor_values 276 distinct (raw 入库)
- factor_ic_history 113 distinct (IC 入库)
- **真 IC 入库率 = 113/276 = ~41%** (沿用 F-D78-58 sustained "163 因子 raw 但 0 IC 入库 = 等同不存在")

候选 finding:
- F-D78-224 [P2] 真 IC 入库率 ~41% (113/276), 真生产铁律 11 enforcement candidate, sustained F-D78-58 sustained P2 sustained 加深印证

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-223 | P2 | sprint period 因子池累计 ~143 vs 真 factor_values 276 distinct = +133 候选差, sustained CLAUDE.md sync update 0 |
| F-D78-224 | P2 | 真 IC 入库率 ~41% (113/276), 真生产铁律 11 enforcement candidate (沿用 F-D78-58 加深) |

---

**文档结束**.
