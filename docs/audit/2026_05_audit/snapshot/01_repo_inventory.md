# 现状快照 — Repo 清单 (类 1)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 3 / snapshot/01
**Date**: 2026-05-01
**Type**: 描述性 + 实测证据 + finding

---

## §1 文件计数实测 (CC 5-01 04:30)

| 类 | 计数 | 实测命令 |
|---|---|---|
| docs/ *.md | 270 | `find docs -name "*.md" -type f | wc -l` |
| 全 repo *.py (排除 .venv/node_modules) | 846 | `find . -path ./node_modules -prune -o -path ./.venv -prune -o -name "*.py" -print | wc -l` |
| 全 repo *.md (排除 .venv/node_modules) | 700 | 同上模式 |
| test_*.py | 266 | `find . ... -name "test_*.py" -print | wc -l` |
| 根目录 *.md | **8** | `ls *.md` |

---

## §2 🔴 根目录 *.md 真清单 + 文件归属规则违反

实测 (CC 5-01 04:30 `ls *.md`):
```
CLAUDE.md
FACTOR_TEST_REGISTRY.md
IRONLAWS.md
LESSONS_LEARNED.md
PROJECT_ANATOMY.md           ← 未授权
PROJECT_DIAGNOSTIC_REPORT.md ← 未授权
SYSTEM_RUNBOOK.md            ← 未授权
SYSTEM_STATUS.md
```

CLAUDE.md §文件归属规则 sustained 写:
> 根目录只允许以下文件: CLAUDE.md / IRONLAWS.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / pyproject.toml / .gitignore

**实测违反 3 个**:
- `PROJECT_ANATOMY.md` (未授权)
- `PROJECT_DIAGNOSTIC_REPORT.md` (未授权, sprint state Session 44 提到的诊断报告)
- `SYSTEM_RUNBOOK.md` (未授权)

**F-D78-5 [P2]** 根目录文档 anti-pattern 复发. CLAUDE.md §文件归属规则 reactive 治理失败 (规则在 sustained 但实测违反 sustained). 沿用 ADR-022 §7.3 "5+1 层 0 repo sediment, memory only" 同源 anti-pattern (规则写了但 enforcement 缺).

---

## §3 git 历史活跃度 (CC 5-01 实测)

| 时间 | commit count | 实测 |
|---|---|---|
| 30 day | 578 | `git log --since="30 days ago" --oneline | wc -l` |
| 90 day | 741 | `git log --since="90 days ago" --oneline | wc -l` |
| All | **741** | `git log --oneline | wc -l` |

**判定 (重大)**:
- **项目 git history 全长 = 741 commits, ~90 day 内 ALL = 741, 30 day 内 = 578** (~78% commits 集中近 30 day)
- **项目实际 90 day 之前 0 git history** (项目 git init 时间 ~2026-02-01, 沿用 sprint period 时间线)
- sprint period 22 PR (#172-#181, 4-30~5-01) 共 ~50+ commits 占 30-day 高密度的相当部分

**F-D78-13 [P2]** 项目 git 全 history 仅 90 day. **bus factor 高风险**: user 退出后接手者无 multi-year 演进 context. 沿用 framework_self_audit §3.1 D11 "项目可持续性" 维度 + framework v3.0 候选 "Knowledge Management" 领域.

---

## §4 git log 沉默地带 candidate

(本审查未跑 git log 按文件 / 30 day 0 commit 但 production 关键文件 实测. 留 governance/code archaeology sub-md 详查.)

---

## §5 git blame 高频改动文件 candidate

(本审查未跑 git blame 高频改动 file 实测. 留 governance/code archaeology sub-md 详查.)

---

## §6 untracked files 真状态 (CC 5-01 实测 git status)

```
?? docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md
?? docs/audit/2026_05_audit/
```

- `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` — sprint period sprint state 提到的 V3 design doc, 未 commit (sprint period sustained "T1.3 design doc 落地" 通过 PR #181 走的是 `docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md`, 这个 V3_DESIGN.md 是另一份 untracked draft. **F-D78-14 [P3]** untracked draft 与 PR #181 沉淀的 design doc 关系 sprint state 未明确)
- `docs/audit/2026_05_audit/` — 本审查 folder (本审查 commit 中)

---

## §7 发现汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-5 | P2 | 根目录 *.md = 8, 多 3 个未授权 (PROJECT_ANATOMY / PROJECT_DIAGNOSTIC_REPORT / SYSTEM_RUNBOOK), CLAUDE.md §文件归属规则 reactive 治理失败 |
| F-D78-13 | P2 | 项目 git 全 history 仅 90 day (741 commits 全集中近 90 day), bus factor 高风险 |
| F-D78-14 | P3 | docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md untracked, 与 PR #181 沉淀的 T1_3_RISK_FRAMEWORK_DECISION_DOC.md 关系 sprint state 未明确 |

---

**文档结束**.
