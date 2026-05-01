# ANTI_PATTERN_CATALOG — sprint period anti-pattern 真测整合

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 8 / ANTI_PATTERN_CATALOG
**Date**: 2026-05-01
**Type**: sprint period anti-pattern catalog (sustained ADR-022 + LL-098 sustained)

---

## §0 元说明

ADR-022 sprint period 6.4 G1 PR #180 沉淀 反 3 anti-pattern (audit log 链膨胀 + 留 Step 7+ 滥用 + 数字漂移高发). 本 md 整合本审查 sustained 实测扩 anti-pattern catalog.

---

## §1 ADR-022 反 3 anti-pattern + 本审查实测扩

### 1.1 §22 audit log 链膨胀 (ADR-022 第 1 条)

实测 sprint period sustained:
- ADR-022 sustained sustained 反 §22 entry sustained sustained
- 本审查 sustained 0 §22 entry 创建 ✅ (sustained Phase 1-7 reverify)

**判定**: ✅ ADR-022 第 1 条 enforcement sustained 在本审查

### 1.2 留 Step 7+ 滥用 (ADR-022 第 2 条)

实测 sprint period sustained:
- ADR-022 sustained 反 "留 Step 7" 滥用 sustained sustained
- 本审查 sustained sustained 0 "留 Step 8 / 留 Phase 9" 主动 offer ✅
- 但 sprint period sustained sustained sustained "留 T1.4 / 留 Step 7" 在 sprint state Session 46 末沉淀 (sustained F-D78-137 P2 candidate validation 失败)

**判定**: ⚠️ ADR-022 第 2 条 enforcement 部分 (本审查 ✅, sprint state 沉淀 sustained 候选)

### 1.3 数字漂移高发 (ADR-022 第 3 条)

实测 sprint period sustained 多漂移:
- F-D78-1/5/7/9/57/60/76/81/122/123/147/148/153/171/214/219/223/228 = ~18 数字漂移真测扩 (sustained F-D78-46/171 broader 84+)

**判定**: 🔴 ADR-022 第 3 条 enforcement **失败** (sustained F-D78-16 ex-post 沉淀但 ex-ante prevention 缺)

---

## §2 本审查实测扩 anti-pattern (5 新)

### 2.1 反 §7.9 被动 follow framework

实测 sprint period sustained:
- framework_self_audit §7.9 sustained 反 "被动 follow Claude framework" anti-pattern
- 本审查 sustained 主动扩 framework (8 维度 + 14 方法论 + 16+1 领域 + 22 类 + 8 端到端 + 5 adversarial + 6 视角 + 5 严重度) ✅
- **但 framework 自身**: 16 领域 candidate 缺 frontend (F-D78-196 sustained 加深) — sustained §7.9 反 anti-pattern 自身复发

### 2.2 LL-098 第 13 次 stress test (X10 候选铁律)

实测 sprint period sustained:
- 全 91 sub-md 末尾 0 forward-progress offer ✅
- pre-push hook X10 守门 (sustained sprint period sustained PR #177 sustained sustained)
- 13 次 stress test 0 失守 sustained sustained sustained sustained

**判定**: ✅ LL-098 enforcement sustained, X10 候选 promote 候选 (sustained F-D78-18 P3 sustained sustained candidate)

### 2.3 第 19 条铁律 (memory 数字 SQL verify before 写)

实测 sprint period sustained:
- 第 19 条 sustained sprint period sustained sustained 9 次 verify
- 本审查 prompt + 全 sub-md 数字 全 SQL/grep/du/pytest 实测 verify ✅
- 但 sprint state handoff 自身漂移 sustained (F-D78-1/4/7/76/81/etc, sustained F-D78-17 P2 sustained handoff 写入层 0 enforce)

**判定**: ⚠️ 第 19 条 enforcement 部分 (prompt 层 ✅, handoff 写入层 ❌)

### 2.4 sprint period treadmill (ADR-022 反 anti-pattern 自身复发)

实测:
- ADR-022 sustained 反 sprint period treadmill 自身是 sprint period 6.4 G1 PR #180 末次 reactive 沉淀
- sprint period 22 PR + Phase 1-8 8 PR = 30 PR 跨日 4 day = **本审查自身就是新一轮 sprint period treadmill candidate**

**判定**: ⚠️ sprint period treadmill anti-pattern 自身复发候选 (本审查可能 contributes to it, sustained F-D78-19 sustained candidate)

### 2.5 4 源 N×N 协作漂移 (新)

实测 sprint period sustained:
- 4 源 (Anthropic memory + git repo + Claude.ai + CC) N×N 同步矩阵 sustained
- broader 84+ drift 真测 (F-D78-46/171/26 sustained sustained sustained sustained P0 治理)
- sprint period 22 PR + 本审查 8 PR 大头 docs 同步 (sustained governance/04 §3 F-D78-147 P0 治理 加深)

**判定**: 🔴 4 源 N×N 协作漂移 anti-pattern sustained 真实证扩

---

## §3 anti-pattern catalog 总

| Anti-pattern | 类别 | enforcement |
|---|---|---|
| §22 audit log 链膨胀 (ADR-022 第 1) | 治理 | ✅ 本审查 sustained |
| 留 Step 7+ 滥用 (ADR-022 第 2) | 治理 | ⚠️ partial |
| 数字漂移高发 (ADR-022 第 3) | 治理 | 🔴 失败 |
| 反 §7.9 被动 follow framework | framework | ⚠️ partial |
| LL-098 forward-progress offer | 协作 | ✅ |
| 第 19 条 memory 数字 SQL verify | 数据 | ⚠️ prompt ✅ / handoff 写入层 ❌ |
| sprint period treadmill (本审查自身候选) | 治理 | ⚠️ candidate |
| 4 源 N×N 协作漂移 | 协作 | 🔴 sustained |

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-234 | P2 | sprint period treadmill anti-pattern 自身候选复发 (本审查 30 PR 跨日 4 day candidate contributes), sustained F-D78-19 P0 治理 加深 |

---

**文档结束**.
