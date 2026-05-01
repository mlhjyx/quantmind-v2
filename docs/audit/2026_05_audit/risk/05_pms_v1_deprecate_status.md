# Risk Review — PMS v1 deprecate 真状态 (sprint state "ADR-016" 漂移)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 7 WI 4 / risk/05
**Date**: 2026-05-01
**Type**: 评判性 + PMS v1 deprecate 真状态 + sprint state ADR 编号漂移

---

## §1 真测 (CC 5-01 实测)

实测 grep "PMS deprecat OR ADR-016 OR ADR-010-pms":
- ADR-003-event-sourcing-streambus.md (sustained, ref PMS sustained sustained)
- **ADR-010-pms-deprecation-risk-framework.md** (真 ADR 编号)
- README.md (sustained 索引)

**🔴 finding**:
- **F-D78-219 [P3]** **sprint state Session 46 末沉淀 "ADR-016 PMS v1 deprecate" 真值是 ADR-010-pms-deprecation-risk-framework**, ADR 编号漂移 (sprint state "ADR-016" vs 真 "ADR-010"), sustained F-D78-152 ADR-010 双文件 (addendum-cb-feasibility + pms-deprecation-risk-framework) 共用编号 010 同源 anti-pattern + sprint state 错引

---

## §2 PMS v1 真 deprecate 真状态

实测 sprint period sustained sustained:
- ADR-010-pms-deprecation-risk-framework.md sustained sustained
- sprint period CLAUDE.md sustained "PMS Beat (pms.py daily_pipeline 调用 + api/pms) 已 deprecated (PR #34 停 Beat + 去重)"
- 真 PMS v1 实施 0 候选 enumerate (是否真删 vs 仅 stop calling)
- sustained F-D78-66 P2 sustained "sprint period 死码清理真删除 vs 仅 stop calling 候选 verify"

候选 finding:
- F-D78-220 [P2] PMS v1 真 deprecate 状态 (真删 vs 仅 stop calling) 0 sustained sustained 度量, sustained F-D78-66 sustained, sprint state Session 46 末 "C2 (D-M1 T0-12 methodology) + C1 (D-M2 ADR-016 PMS v1 deprecate) 隐含 prerequisite" sustained 沉淀但 真 prerequisite candidate 验证

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-219** | **P3** | sprint state "ADR-016 PMS v1 deprecate" 真值是 ADR-010-pms-deprecation-risk-framework, ADR 编号漂移 |
| F-D78-220 | P2 | PMS v1 真 deprecate 状态 (真删 vs 仅 stop calling) 0 sustained 度量 |

---

**文档结束**.
