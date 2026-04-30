# Governance Review — Knowledge Management (CC 扩领域)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 4 / governance/02
**Date**: 2026-05-01
**Type**: 评判性 (CC 主动扩领域, sustained framework_self_audit §3.1 D6)

---

## §0 元说明

framework_self_audit §3.1 D6 决议: "Knowledge Management (跨 session continuity + memory drift + repo 自给自足度) — sprint state 4-28 vs 4-27 印证, 与"治理"重叠但独立维度".

本 md 是 CC 扩领域 - 4 源协作 (Anthropic memory + git repo + Claude.ai + CC) sustained N×N 漂移矩阵 (沿用 blind_spots/03_shared_assumptions §1.2 F-D78-26 P0 治理推翻).

---

## §1 4 源 真覆盖 + 真同步成本

### 1.1 4 源真测

| 源 | 描述 | 真覆盖 | 真同步成本 |
|---|---|---|---|
| Anthropic memory | `~/.claude/projects/D--quantmind-v2/memory/` (本审查实测 50+ memory entry) | sprint state + user profile + sustained feedback + project pillars | 每 session 末手工 update (sprint state Session 1-46+ 累计) |
| Git repo | docs/ 270 *.md + 根目录 8 *.md + ADR / LL / TIER0 + 等 | 全代码 + 全 docs + 全 ADR + 全 LL + sprint state PR 沉淀 | sprint period sustained PR push (sprint period 22 PR 跨日) |
| Claude.ai 战略对话 | sprint period sustained user 战略对话 (D72-D78 跨日 4 次反问印证) | 战略决议 + 反 sprint period treadmill | sprint period sustained user 主导 |
| CC 实施 | sprint state Session 1-46+ 累计 CC 实施 sustained | 代码 + audit + handoff + status report | sprint period 22 PR 跨日 |

### 1.2 跨源 fact 真同步矩阵

实测 sprint period sustained 跨源 fact 同步 (粗估):
- 同 fact 跨 4 源 = N×(N-1) = 12 同步 path
- 实测 sprint period sustained 22 PR 跨日, 大头是跨源 docs / handoff / sprint state 沉淀 同步 (governance/01_six_pillars_roi §3 治理 sprint period 论证)
- **真同步成本 candidate**: ~70% sprint period sustained 时间投入在跨源同步, ~30% 真业务前进

---

## §2 跨 session continuity 真测

### 2.1 sprint state Session 1-46+ continuity

实测 sprint period sustained Session 跨日 continuity:
- sprint state Session 1-46+ 累计 sustained sustained sustained
- 每 Session 末写 handoff (sustained 铁律 37 sustained)
- handoff 漂移 (F-D78-1/7/44/etc) 跨 Session 真测

### 2.2 新 Claude session onboard 路径

实测 sprint period sustained 新 Claude session onboard:
- 走 CLAUDE.md (sprint period sustained 重构 813 → 509 行)
- 走 SYSTEM_STATUS.md
- 走 sprint state Anthropic memory frontmatter
- 走 docs/QUANTMIND_PLATFORM_BLUEPRINT.md (QPB v1.16)
- 走 docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md (791 行)

**真测 onboard 难度**: 高 (5+ 关键文档 + sprint state Session frontmatter + 跨文档漂移 sustained)

**finding**:
- F-D78-51 [P1] 新 Claude session onboard 难度高, 5+ 关键文档 + sprint state frontmatter + 跨文档漂移 sustained, sprint period sustained 6 块基石 sustained 但 onboard SOP 0 自动化

---

## §3 memory drift 真测

### 3.1 sprint state vs 真值真 drift (本审查实测)

| sprint state 写 | 真值 | finding |
|---|---|---|
| "DB 4-28 stale" | 真 4-27 | F-D78-1 |
| "5 schedule entries 生产激活" | 真 4 active + 2 PAUSED | F-D78-7 |
| "T0-19 已 closed" | DB stale 仍 active | F-D78-4 |
| "DataQualityCheck 17:45 hang REPRO" | 真 18:30 (时点漂移) | F-D78-11 |

**累计**: sprint state 4 fact drift 真测 (本审查 sustained 4 个), sprint period sustained "broader 47" + 本审查 22+ = broader 70+ (F-D78-46 P2)

### 3.2 memory drift 真原因 (5 Why 推断)

- Why 1: handoff 数字写入时未 SQL verify (沿用 第 19 条铁律 F-D78-17 handoff 写入层 0 enforce)
- Why 2: sprint state 跨 Session 复制 + 微调 (Session N+1 复 Session N 沉淀 + 调整, 漂移累积)
- Why 3: ADR-022 反"数字漂移高发" enforce 失败 (F-D78-16 ex-post 沉淀 但 ex-ante prevention 缺)
- Why 4: 4 源 N×N 同步矩阵 sustained (F-D78-26 P0 治理)
- Why 5: 1 人项目走企业级理念 (F-D78-28 candidate 推翻) — 1 人无法 sustain N×N 同步

---

## §4 repo 自给自足度真测

### 4.1 repo 是否真自给自足 (新接手者 onboard 必读)?

实测真值:
- CLAUDE.md sprint period sustained sustained ✅
- SYSTEM_STATUS.md sprint period sustained sustained ✅
- IRONLAWS.md sprint period sustained sustained ✅
- sprint state Session N frontmatter 在 Anthropic memory (**not repo**), 接手者 0 access

**真测 finding**:
- F-D78-52 [P1] sprint state 关键 context 在 Anthropic memory frontmatter (not repo), 新接手者 (无 user Claude account) 0 access, repo 自给自足度 candidate 不足

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-26 (复) | P0 治理 | 4 源协作有效假设推翻, N×N 同步矩阵 sustained 漂移 |
| F-D78-46 (复) | P2 | 跨文档漂移 broader 70+ |
| F-D78-51 | P1 | 新 Claude session onboard 难度高, onboard SOP 0 自动化 |
| F-D78-52 | P1 | sprint state 关键 context 在 Anthropic memory (not repo), 新接手者 0 access |

---

**文档结束**.
