# Cross-Validation — D 决议链 SSOT drift 真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 7 WI 5 / cross_validation/04
**Date**: 2026-05-01
**Type**: 跨领域 + D 决议链 SSOT 0 in CLAUDE.md 真测

---

## §1 真测 (CC 5-01 实测)

实测 grep "D[0-9]{2,3} OR D72 OR D73 OR D74 OR D75 OR D76 OR D77 OR D78" 4 顶级 SSOT:

| 文件 | grep 命中 |
|---|---|
| CLAUDE.md | **0** ⚠️ |
| IRONLAWS.md | ✅ 真存 |
| SYSTEM_STATUS.md | ✅ 真存 |
| FRAMEWORK.md (本审查 sustained) | ✅ 真存 (§0.1 D72-D78 enum) |

---

## §2 🔴 重大 finding — CLAUDE.md 0 D 决议链 reference

**真值**: CLAUDE.md 项目入口文件, sprint period sustained sustained sustained "Claude Code 启动自动读" sustained sustained sustained, 但 **0 D 决议链 reference**. 

**真测**:
- 新 CC session 启动 → 读 CLAUDE.md → **0 知 D 决议链 sustained**
- 沿用铁律 38 sustained "Blueprint (QPB) 是唯一长期架构记忆, 跨 session 实施漂移禁止" sustained sustained 但 D 决议链 0 in CLAUDE.md → 跨 session 漂移 high risk

**🔴 finding**:
- **F-D78-221 [P1]** CLAUDE.md 0 D 决议链 reference, 新 CC session 0 知 D 决议链 sustained sustained, 沿用 governance/03 §1 F-D78-130/131 sustained sustained sustained sustained sustained "D 决议链 SSOT 0 sustained" 加深印证. 候选 CLAUDE.md add D 决议链 banner reference

---

## §3 D 决议链跨 4+ 文档分布真测

实测 sprint period sustained:

| 文档 | D 决议覆盖度 |
|---|---|
| FRAMEWORK.md §0.1 | D72-D78 (5 项 enum) |
| ADR-022 | sustained 反 anti-pattern decisions sustained |
| T1.3 design doc | D-L0~L5 + D-T-A1~A5 + D-T-B1~B3 + D-N1~N4 + D-M1~M2 (20 项 enum) |
| memory project_platform_decisions.md | 4+4 项 |
| sprint state Session frontmatter | sprint period sustained sustained sustained 沉淀 (但 sprint state 0 in repo, F-D78-52 sustained) |
| CLAUDE.md | 0 |
| IRONLAWS.md | partial |
| SYSTEM_STATUS.md | partial |

**真测**: D 决议链跨 7+ 源 sustained sustained 沉淀, 0 SSOT, candidate finding (sustained F-D78-130/131 sustained):
- F-D78-222 [P2] D 决议链跨 7+ 源 sustained 0 SSOT, 候选 D_DECISION_REGISTRY.md SSOT 沉淀 candidate (本审查 0 决议)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-221** | **P1** | CLAUDE.md 0 D 决议链 reference, 新 CC session 0 知 D 决议链, 跨 session 漂移 high risk |
| F-D78-222 | P2 | D 决议链跨 7+ 源 sustained 0 SSOT, 候选 D_DECISION_REGISTRY.md sustained candidate |

---

**文档结束**.
