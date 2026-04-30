# ADR-022: Sprint Period Treadmill 反 anti-pattern + 集中修订机制

**Status**: Accepted
**Date**: 2026-05-01 (Step 6.4 G1 PR 落地)
**Decision Maker**: User (D72 反问沉淀) + CC (实施)
**Supersedes**: 部分撤销 ADR-021 §4.5 + 部分修订 PROJECT_FULL_AUDIT (PR #172) line 89 数字
**Related**: PR #172 / PR #174 (ADR-021) / PR #178 (Step 6.3a) / PR #179 (Step 6.3b) / 本 PR (Step 6.4 G1)

---

## §1 Context

### §1.1 Sprint period treadmill anti-pattern (D72 user 反问沉淀, 2026-05-01)

Step 6.1 → 6.3b 累计 8 PR (PR #172-#179) sprint period 治理基础设施 5 块基石建设期间, 出现以下 anti-pattern:

1. **Audit log 链膨胀**: 每发现 PR 锁文件中过期 target / 数字 / 假设, 走 IRONLAWS §22 新加 v3.0.X entry sediment, 累计 4 entries (v3.0 / v3.0.1 / v3.0.2 / v3.0.3) / 1 day. 单看每条合理, 累计后 IRONLAWS §22 治理 audit log 长 + 真核心铁律内容被稀释.

2. **"留 Step 7+" 滥用**: 每个 PR 都积累若干 "留 Step 7+" 候选, 代表本 PR scope 边界外的发现. 当这类候选累计 13+ 项 (Step 6.4 G1 prompt 实测), 表面是治理纪律 (不擅自扩 scope), 实质是 sprint period treadmill (永远不真清理债, 只 enumerate 留下一波).

3. **数字漂移高发**: PR #172 PROJECT_FULL_AUDIT line 89 "11 项" 实测 9 项 / ADR-021 §4.5 "~150 行" target 实测不可达 / CLAUDE.md L401 PT prerequisite 暗示 still 待办的 T0 项实际 closed / SYSTEM_STATUS.md 5 day stale / FACTOR_TEST_REGISTRY.md 3 week stale / 等等. 单看每个漂移可走 audit log 沉淀, 累计后形成 "PR 锁文件已不可信" 的隐患.

### §1.2 Trigger event (D72 决议)

User 在 Step 6.4 G1 prompt 反问点出: "不再走 Step 6.3c 轻量修补模式. 一次性 cleanup 13 项治理债, 进 Step 7 T1.3 时 clean state."

D72 决议 (2026-05-01): **反 sprint period treadmill anti-pattern**, 一次性 G1 cleanup 11 项文档同步债 (G2 2 项架构层决议留 Step 7 T1.3, 因 CC 不能单方面 promote / 撤销 / 决议).

### §1.3 现有 PR 锁松动机制审查

PR #172-#179 8 PR 锁定的文件中:
- ADR-021 §4.5 "Step 6.3 全文件 ~150 行 重构" 假设
- PROJECT_FULL_AUDIT line 89 "剩 11 项" 数字
- IRONLAWS.md §22 v3.0/v3.0.1/v3.0.2/v3.0.3 audit log 链

走 audit log 链膨胀模式将无限延续 — 每 sprint period PR 都新增 entry. 必须有终止机制.

---

## §2 Decision

### §2.1 一次性 cleanup + 反 anti-pattern 声明

本 ADR-022 一次性集中处理:

1. **撤销 ADR-021 §4.5 "~150 行" target** — 实测推翻 (Step 6.3b STOP-1+STOP-2 双触发, Path C 实施 ~509 行落地)
2. **修订 PROJECT_FULL_AUDIT line 89 "11 项" → "9 项"** (沿用 Step 6.3a §2.1 严格 enumerate)
3. **声明: 未来同源 sprint period 漂移走本 ADR-022 (或后续 ADR-023+) 集中修订, 不再走 IRONLAWS §22 audit log entry 模式**

### §2.2 PR 锁松动一次性原则

本 ADR 实施时:
- ADR-021 §4.5 inline 注 "本段已被 ADR-022 §2.1 #1 撤销" (锁松动一处)
- PROJECT_FULL_AUDIT line 89 inline 注 "本数字已被 ADR-022 §2.1 #2 修订" (锁松动一处)
- 修后立刻重新锁定 (sustainable)

### §2.3 IRONLAWS §22 audit log 链终止

- **终止决议**: §22 v3.0.4+ 不再 sediment sprint period 漂移修补 audit. 漂移修补走 ADR-022 (本 ADR) 或后续 ADR-023+ 集中.
- **§22 保留范围**: 仅记 IRONLAWS.md 自身的 SSOT 内容版本变更 (e.g. 新铁律加入 / Tier 重新 calibration / 候选 promote 等).
- **本 PR (Step 6.4 G1) 加 v3.0.4 entry?** — 不加. 本 PR 走 ADR-022 直接, 0 sediment §22.

### §2.4 反 "留 Step 7+" 滥用原则

本 PR 实施时, 每发现 "留 Step 7+" 候选默认尝试本 PR 一并修. 仅以下情况可留 Step 7 T1.3:
- G2 架构层决议 (X1/X3/X4/X5/X11 promote / 撤销 / 等) — CC 不能单方面决议
- 4 fail mode 工程化测试 (amend/cherry-pick/merge dry-run scenario) — 需写代码 (违 0 业务代码硬边界)

---

## §3 Consequences

### §3.1 短期 (本 PR 实施期间)

- ADR-021 §4.5 inline 注 "撤销" 标记
- PROJECT_FULL_AUDIT line 89 inline 注 "修订" 标记
- IRONLAWS.md §22 不加 v3.0.4 entry (终止 sprint period audit log 链)
- ADR-022 (本 ADR) 创建, 集中沉淀决议 + 实施清单

### §3.2 长期治理

- 未来 sprint period PR 锁文件中发现漂移 → 默认走集中 ADR (新建 ADR-023+ 或 update 本 ADR-022 §X 段) 沉淀
- IRONLAWS.md §22 仅记真 SSOT 内容版本变更
- "留 Step 7+" 仅限架构层决议 + 写代码项

### §3.3 反 anti-pattern 验证

- ✅ Audit log 链终止 (§22 不加 v3.0.4)
- ✅ "留 Step 7+" 滥用 — Step 6.4 G1 11 项 cleanup 一次性 + 仅 G2 2 项留 Step 7 T1.3
- ✅ PR 锁松动一次性原则 (松动一处, 修后立刻重锁)

### §3.4 副作用接受

- ADR-022 自身可能成为新 audit log 链 (新 anti-pattern 风险). 缓解: §2.4 明示 "未来同源走本 ADR (或 ADR-023+) 集中" — 最多 1-2 个 ADR, 不会无限累计.

---

## §4 Implementation Checklist (Step 6.4 G1 实施)

### §4.1 ADR-021 §4.5 撤销 inline 注

```diff
 ### 4.5 后续步骤 (留 Step 6.2.5+, 本 PR 不预设)
+
+> **Step 6.4 G1 撤销** (2026-05-01, ADR-022 §2.1 #1): "Step 6.3 全文件 ~150 行 重构" target 实测推翻 (Step 6.3b STOP-1+STOP-2 双触发). 实际 Path C ~509 行落地 (PR #179). **本节 §4.5 仅作历史快照保留, 后续步骤实际走 ADR-022 + Step 6.4 G1 (本 PR)**.
```

### §4.2 PROJECT_FULL_AUDIT line 89 修订 inline 注

```diff
-**剩 11 项 (T0-1 ~ T0-12 + T0-14)**: 留 Step 6 / Step 7 / T1.4 阶段处理.
+**剩 9 项**: 留 Step 6 / Step 7 / T1.4 阶段处理. <!-- Step 6.4 G1 修订 (ADR-022 §2.1 #2): 严格 enumerate 9 项 = T0-4/5/6/7/8/9/10/12/14 (T0-1/2/3/11/15/16/17/18/19 已 closed 或撤销). 详 docs/audit/TIER0_REGISTRY.md (本 PR WI 9 新建) -->
```

### §4.3 IRONLAWS §22 audit log 链终止 inline 注

§22 末尾追加段:

```markdown
### §22.终止 sprint period audit log 链 (Step 6.4 G1, 2026-05-01)

> **终止决议** (沿用 ADR-022 §2.3): 本 §22 不再 sediment sprint period 漂移修补 audit. v3.0.3 (Step 6.3b) 是末次 audit log entry. v3.0.4+ 仅记真 SSOT 内容变更 (新铁律 / Tier calibration / 候选 promote 等). 漂移修补走 ADR-022 (或后续 ADR-023+) 集中.
```

### §4.4 ADR 索引更新

- CLAUDE.md L80 "架构决议 (ADR-001 ~ ADR-021)" → "ADR-001 ~ ADR-022"
- IRONLAWS.md §21.1 ADR 编号系统 → 加 ADR-022 entry

---

## §5 Acceptance

- ✅ ADR-022 创建 (本文件)
- ✅ ADR-021 §4.5 撤销 inline 注 (本 PR 实施)
- ✅ PROJECT_FULL_AUDIT line 89 修订 inline 注 (本 PR 实施)
- ✅ IRONLAWS §22 终止段 inline 加 (本 PR 实施)
- ✅ CLAUDE.md ADR 范围 ref 同步 (本 PR 实施)
- ✅ 反 audit log 链膨胀 anti-pattern + "留 Step 7+" 滥用 + 数字漂移高发 三个 anti-pattern 集中处理

---

## §6 关联

- **ADR-021** (本 ADR 部分撤销): IRONLAWS v3 重构 + 编号锁定
- **PR #172** (PROJECT_FULL_AUDIT 锁松动一处): 修订 line 89 数字
- **PR #174-#179** (sprint period 治理基础设施 5 块基石): IRONLAWS §22 audit log 链来源
- **D72 user 反问** (2026-05-01 Step 6.4 G1 prompt): 反 sprint period treadmill anti-pattern 决议触发
- **Step 6.4 G1 STATUS_REPORT** (本 PR): 详细实施清单 + 实测验证

---

## §7 Handoff 治理决议 (Step 6.4 G1 WI 8 sediment)

> **背景**: Step 6.3b §5.3 enumerate 5 候选, 路径 1 (Anthropic memory 唯一 SSOT) 决议最优. 本 §7 集中 sediment 决议 + 候选 ROI + 反 anti-pattern 视角.

### §7.1 决议: 路径 1 (Anthropic memory 唯一 SSOT)

- **范围**: handoff 文档 (跨 session 工作交接 / sprint state 持续记录) **不沉淀到 repo**, 唯一 SSOT 在 Anthropic memory 系统 `project_sprint_state.md` frontmatter + `session_NN_handoff_*.md`.
- **机制**: SessionStart hook 自动注入 sprint state, 跨 session continuity 工作正常 (Step 6.3b 实证).
- **X5 单源化对齐**: 不在 repo docs/ 镜像 → 0 重复 / 0 双源同步成本 / 0 stale 风险.

### §7.2 5 候选 ROI 评估摘要 (沿用 Step 6.3b §5.2)

| # | 路径 | ROI | 决议 |
|---|---|---|---|
| 1 | Anthropic memory 唯一 SSOT (现状) | 高 | ✅ 采纳 (本 ADR §7.1) |
| 2 | docs/handoff/ 镜像 (定期 sync memory → repo) | 低 | ❌ 双源同步成本 + 违 X5 |
| 3 | docs/session/ 仅记 milestone | 低 | ❌ vs STATUS_REPORT 重复 |
| 4 | git tag (每 sprint 末打 tag, message 含 handoff) | 中 | ❌ tag 不友好迭代 |
| 5 | GitHub Wiki / Discussions | 不适用 | ❌ 个人项目 |

### §7.3 单点风险评估 + 缓解

- **风险**: Anthropic memory 服务不可用 = handoff 失忆.
- **概率评估**: Anthropic memory 是 Anthropic 托管基础设施, 与 Claude Code CLI 同等可靠级别. 风险 ≈ Claude Code 不可用风险 (实测 sprint period 0 失败).
- **缓解**: 关键 sprint milestone (如 Step 6.x 治理基础设施 5 块基石 / Wave N 完结 / PT 重启 gate 状态等) 同步沉淀到 repo (SYSTEM_STATUS.md §0.-N + STATUS_REPORT). repo 是 last-resort 恢复源 (即使 memory 全失忆, 走 repo + git log 可重建 ~80% sprint state).
- **Step 6.4 G1 实证**: WI 3 SYSTEM_STATUS.md §0.-2 sediment 已对齐此原则 — sprint period 关键 milestone 在 repo + memory 双源 (memory = 真 SSOT, repo = recovery snapshot).

### §7.4 反 anti-pattern 验证

- ✅ 不引入新 "留 Step 7+" 候选 (本 §7 直接决议路径 1)
- ✅ 不创建 docs/handoff/ 镜像新结构 (避双源)
- ✅ 与 ADR-022 §2.4 "反 留 Step 7+ 滥用" 原则一致

---

**ADR-022 写入完成 (2026-05-01, 含 §7 handoff sediment)**.
