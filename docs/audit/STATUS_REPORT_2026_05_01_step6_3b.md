# STATUS_REPORT — Step 6.3b CLAUDE.md 重构 + 5 层叠加 audit + line 89 修补 + §3.2 修订 + handoff enumerate (2026-05-01 ~00:30)

**PR**: chore/step6-3b-claude-md-refactor (Step 6.3b)
**Scope**: CLAUDE.md 全文件温和精简 (Path C 折中) + IRONLAWS §22 v3.0.3 entry + 5 层叠加 audit + Step 6.3a 漏检 4 项修补 + handoff 治理 enumerate
**Date**: 2026-05-01 ~00:30
**关联**: Step 6.3a STATUS_REPORT (PR #178 merged f26b0d8) + ADR-021 §2.5 + §4.5 + handoff §4 sprint 路径
**LL-098 stress test**: **第 10 次自我应用** (本 PR 末尾 0 forward-progress offer 验证)
**第 19 条铁律**: **第 6 次连续 verify** (prompt 不假设具体数字, CC 实测决定)

---

## §0 环境前置检查 E1-E14

| # | 检查项 | 结果 |
|---|---|---|
| E1 | git status + HEAD | ✅ main `f26b0d8` Step 6.3a, working tree clean |
| E2 | PG stuck backend | ✅ 0 stuck (`SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction' AND state_change < NOW() - INTERVAL '5 minutes'` = 0) |
| E3 | Servy 4 services | ✅ FastAPI / Celery / CeleryBeat / QMTData 全 Running |
| E4 | .venv Python | ✅ 3.11.9 |
| E5 | LIVE_TRADING_DISABLED | ✅ default=True (live_trading_guard.py:7 docstring), .env 未显式覆盖 → guard 默认阻断真金 |
| E6 | 真账户 ground truth | ✅ 沿用 4-30 14:54 xtquant 实测 (positions=0 / cash=¥993,520.16) |
| E7 | cb_state.live | ✅ level=0, nav=993520.16, trigger_reason='PT restart gate cleanup 2026-04-30' (匹配 ground truth) |
| E8 | position_snapshot live | ⚠️ **prompt 假设 "0 行" 与实测冲突** — 实测 trade_date=4-28 stale 19 行, 是 T0-19 已 enumerate 的 P1 债 (sprint period 第 N+1 数字假设错). 不 STOP, 记主动发现 #1. |
| E9 | PROJECT_FULL_AUDIT + SNAPSHOT | ✅ 实存 (PR #172 锁) |
| E10 | LL-098 inline | ✅ LESSONS_LEARNED.md L3032 实存 |
| E11 | IRONLAWS §18/§21.1/§22/§23 + v3.0.2 | ✅ L667/§21.1/L813/L834 全实存, §22 v3.0.2 entry L827 实存 |
| E12 | ADR-021 §3.6 | ✅ L156 实存 |
| E13 | pre-push X10 hook | ✅ config/hooks/pre-push L11 X10 守门段实存 |
| E14 | STATUS_REPORT_step6_3a §3.2 | ✅ L170 实存 (本 PR WI 4 修订对象) |

**结论**: E1-E7 + E9-E14 ✅, E8 ⚠️ (T0-19 known debt, 不阻塞文档 PR scope). 进 WI 1.

---

## §1 Work Item 1 — CLAUDE.md 全文件重构 (主任务)

### §1.1 实测 CLAUDE.md 段结构 (沿用第 19 条铁律 不假设)

CLAUDE.md 813 行 / 38 个段 (含 sub-section). 实测各段角色:

| 段类型 | 段数 | 行数小计 | 处理 |
|---|---|---|---|
| 项目身份 + banner | 1 | 9 | KEEP (PR #174 已加 v3.0 banner) |
| 项目概述 + 技术栈 + 因子系统 + 架构分层 | 4 | 58 | KEEP (操作必备, 短) |
| **目录结构** | 1 | 163 | **大幅精简** (~30 行) |
| 编码规则 (Python/React/SQL/xtquant/Redis Streams/PMS/Servy/PT 参数/并发限制/研究任务资源调度) | 8 sub | 100 | KEEP (operational hard rules, 多无 SSOT 候选) |
| **铁律段 ref** | 1 | 124 | KEEP (PR #174 已 ref 化, 锁) |
| 因子审批硬标准 + 因子画像评估协议 | 2 | 16 | KEEP (因子治理 hard rules) |
| 性能规范 | 1 | 15 | KEEP (短 + 操作 ref) |
| **已知失败方向** | 1 | 36 | **大幅精简** (~12 行 high-level) |
| **策略配置** | 1 | 105 | **大幅精简** (~30 行 当前 PT 配置 + 真账户状态) |
| 文档查阅索引 | 1 | 26 | KEEP (核心导航) |
| **当前进度** | 1 | 110 | **大幅精简** (~30 行 latest milestone) |
| CC 自动化操作 | 1 | 7 | KEEP (短) |
| 文件归属规则 + 执行流程 | 2 | 36 | KEEP (governance) |

### §1.2 ADR-021 §4.5 "~150 行" target 实测推翻 (STOP-1 + STOP-2 双触发, LL "假设必实测" 沉淀)

ADR-021 §4.5 后续步骤写: "Step 6.3: 6+1 文档 SSOT 整合 + 11 项 Tier 0 enumerate + CLAUDE.md 全文件 ~150 行 重构".

**实测推翻** (沿用 LL "假设必实测" + 第 19 条铁律):

**STOP-1 触发** (target 行数与决议冲突): ~150 行需要将大量 inline operational rules / factor governance hard rules / etc 移到新 SSOT 文件 (如 `CODING_RULES.md` / `FACTOR_GOVERNANCE.md` / `PERFORMANCE_BUDGET.md`). 这扩 PR scope (本 PR 硬边界明确 "0 业务代码 / 0 .env / 0 服务重启" 但 "✅ 写新 audit / 整合文档" 解读保守限于 audit doc, 不含创建新 SSOT 文件).

**STOP-2 触发** (含独有内容无 SSOT 候选):
- 编码规则 §xtquant/miniQMT 规则 (7 行): operational hard rule, 无 SSOT 候选
- 编码规则 §Redis Streams 数据总线规则 (8 行): operational, 无 SSOT
- 编码规则 §PMS 阶梯利润保护规则 (8 行): operational, 无 SSOT
- 编码规则 §并发限制 (9 行): operational, 无 SSOT (DEV_BACKEND.md headers 无此段)
- 编码规则 §研究任务资源调度 (10 行): operational, 无 SSOT
- 因子审批硬标准 (7 行): factor governance, DEV_FACTOR_MINING.md 无对应段 (实测 grep)
- 因子画像评估协议 (7 行): factor governance, 同上无对应段

**SSOT 候选实测**:
- DEV_BACKEND.md §一 (L122-295): 项目目录结构 SSOT, 但仅 backend, 不含 platform/scripts/configs/frontend (CLAUDE.md inline 更全)
- SYSTEM_STATUS.md: 部分 SSOT, 但 5 day stale (Step 6.3a §4 #3 enumerate, 0 Session 4X matches 实测), 不能作为完整 PT 状态 / Sprint 进度 SSOT
- FACTOR_TEST_REGISTRY.md: 因子池 SSOT (CLAUDE.md L57 已声明 "因子池状态以 FACTOR_TEST_REGISTRY.md 为唯一真相源")
- docs/research-kb/failed/ + decisions/: 8 failed + 5 decisions, **CLAUDE.md inline 30+ 项失败方向不全在 research-kb** (覆盖不完整)
- .claude/skills/quantmind-performance/: skill 入口, 非 user-readable SSOT

### §1.3 决议: Path C 温和保守 (~530 行 target, 实际 509 行落地)

**4 候选 path**:
- Path A 激进 (~150 行): STOP-1 + STOP-2 双触发, 需新建 3-4 个 SSOT 文件, 扩 PR scope
- Path B 温和 (~300-400 行): 移走目录结构 + 当前进度 + 已知失败方向 + 策略配置 + 性能规范, 但因子治理 hard rules / 编码规则部分仍需新 SSOT
- **Path C 温和保守 (~500-550 行)** ⭐: 仅大幅精简 4 段 (目录结构 / 已知失败方向 / 策略配置 / 当前进度), 保留 inline 所有 operational + factor governance + meta governance 段
- Path D STOP 反问 user: 沿用 prompt §0 STOP 触发, 但 sprint period 6 PR 链路应有交付

**决议**: **Path C** (沿用 prompt "挑战 Claude 假设" #2 反驳 — "实测如某段不应 reference 化, 反驳" 已落地). 0 新文件创建, 0 触 PR scope hard 边界. ADR-021 §4.5 "~150 行" target 在 IRONLAWS §22 v3.0.3 entry 沉淀为 "实测推翻" (LL "假设必实测" 累计候选).

### §1.4 实测落地

```diff
CLAUDE.md: 813 → 509 行 (-304, -37%)
```

| 段 | 之前行数 | 之后行数 | Δ |
|---|---|---|---|
| 项目身份 + banner | 9 | 11 | +2 (Step 6.3b banner entry) |
| 项目概述 | 10 | 8 | -2 (V4 路线图 cross-out 简化) |
| 技术栈 + 因子系统 + 架构分层 | 48 | 48 | 0 |
| 目录结构 | 163 | 35 | **-128** (high-level + DEV_BACKEND.md §一 link) |
| 编码规则 | 100 | 100 | 0 (KEEP) |
| 铁律段 | 124 | 124 | 0 (PR #174 锁) |
| 因子审批 + 画像 | 16 | 16 | 0 |
| 性能规范 | 15 | 15 | 0 |
| 已知失败方向 | 36 | 20 | **-16** (12 关键 + research-kb link) |
| 策略配置 | 105 | 30 | **-75** (当前 PT 配置 + 真账户状态 + SHUTDOWN_NOTICE link) |
| 文档查阅索引 | 26 | 26 | 0 |
| 当前进度 | 110 | 25 | **-85** (milestone overview + SYSTEM_STATUS link) |
| CC 自动化操作 | 7 | 9 | +2 (separator) |
| 文件归属规则 | 27 | 28 | +1 (IRONLAWS.md 加入根目录列表) |
| 执行标准流程 | 8 | 8 | 0 |

✅ **WI 1 完成**.

---

## §2 Work Item 2 — 5 层叠加 audit (补 Step 6.3a Work Item 1 范围未完成)

沿用 Step 6.3a §1.2 6+1 文档边界 (5 root MD + Platform Blueprint + V2 SYSTEM Blueprint).

### §2.1 Overlap Matrix (CC 决议 schema)

| Topic | CLAUDE.md | IRONLAWS.md | LESSONS_LEARNED.md | SYSTEM_STATUS.md | FACTOR_TEST_REGISTRY.md | Platform Blueprint | 漂移评估 |
|---|---|---|---|---|---|---|---|
| 铁律内容 | reference (PR #174) | SSOT | LL backref | - | - | - | ✅ acceptable cross-ref (X5 落地) |
| 铁律历史编号引用 | 简述 + link | 完整 | inline | - | - | - | ✅ acceptable (历史保持) |
| PT 状态 (真账户) | 当前 4-30 实测 | - | - | 5d stale (Session 5 时代 "已暂停清仓 2026-04-10") | - | - | ⚠️ SYSTEM_STATUS 已 enumerate stale (T0-Step 6.3a §4 #3) |
| 因子池状态 | 7 行 high-level + ref | - | - | - | SSOT | - | ✅ acceptable |
| 已知失败方向 | 12 行精简 (本 PR 后) | - | - | - | - | - | ⚠️ research-kb 不全 (8 failed + 5 decisions vs CLAUDE.md 旧 30+ 项) |
| Wave/MVP 状态 | high-level milestones (本 PR 后) | - | - | 详细 §0+ | - | 路线图 SSOT (QPB v1.16) | ✅ acceptable |
| 当前 Sprint state | inline summary | - | - | inline detail | - | - | ⚠️ Anthropic memory `project_sprint_state.md` 是真 SSOT (跨 session, repo 外) |
| 目录结构 | high-level (本 PR 后) | - | - | - | - | - | ⚠️ DEV_BACKEND.md §一 仅 backend (新发现, 详 §2.2) |
| ADR 历史决议保留 | banner + ref | §21.1 ADR 编号系统 | - | - | - | - | ✅ acceptable (PR #176 §21.1 落地) |

### §2.2 P0 / P1 / P2 漂移分类

**P0 (新发现)**: 0 项 — 所有 P0 已在 Step 6.3a §4 enumerate (SYSTEM_STATUS.md 5d stale / FACTOR_TEST_REGISTRY.md 3w stale)

**P1 (新发现 1 项)**:
- **#P1-1**: 目录结构 SSOT 不完整 — DEV_BACKEND.md §一 (L122-295) 仅覆盖 backend/ 子树, 不含 backend/platform/ + scripts/ + configs/ + frontend/ + cache/ + docs/ 等. CLAUDE.md inline 目录结构含全部 + ⭐ MVP/Step 注释 (是更完整 SSOT). Step 6.3b WI 1 决议 inline 留 high-level + DEV_BACKEND.md §一 link 是合理折中 (避免完全失去信息), 长期可考虑 DEV_BACKEND §一 扩 platform/ 部分 (留 Step 7+).

**P2 (设计性 cross-ref)**:
- 铁律 reference 化 (CLAUDE.md ↔ IRONLAWS): X5 单源化设计性, acceptable
- ADR-021 ↔ IRONLAWS §22 关联: design 关联, acceptable
- IRONLAWS §21.1 ADR 历史决议保留 ↔ ADR-021 §3.6: PR #176 双向 anchor, acceptable

### §2.3 决议

- 0 新 P0 SSOT 漂移 → 不触发新 STOP, 不阻塞 WI 1 实施
- 1 P1 新发现 (目录结构 SSOT 不完整) → enumerate 留 Step 7+ 决议
- P2 设计性 cross-ref 全 acceptable

✅ **WI 2 完成** (audit 沉淀, 0 新 P0, 1 P1 新发现 enumerate 留后续).

---

## §3 Work Item 3 — PROJECT_FULL_AUDIT line 89 数字漂移修补 (D71 决议选项 c)

### §3.1 实测 line 89 内容 + 数字分析

PROJECT_FULL_AUDIT line 89: `**剩 11 项 (T0-1 ~ T0-12 + T0-14)**: 留 Step 6 / Step 7 / T1.4 阶段处理.`

**实测**:
- T0-1 ~ T0-12 = 12 个 ID
- T0-14 = 1 个 ID
- 合计 = 13 个 ID 候选, 但 line 81 标 "T0-1 ~ T0-12 部分修", 实测 T0-1/T0-2/T0-3 + T0-11 已 closed
- Step 6.3a §2.1 实测严格状态 = 9 项待修 (T0-4/5/6/7/8/9/10/12/14)
- line 89 写 "11 项" = 把 T0-1 ~ T0-12 整体 enumerate, 未减除 line 81 "部分修" 的 4 项 → 11 = 12 - 1(T0-11) (但仍含 T0-1/2/3 已修)

**数字漂移源**: line 81 "部分修" 集合定义模糊, line 89 enumerate 时未严格减除 closed 项.

### §3.2 D71 决议 4 选项 ROI 评估

| 选项 | 描述 | ROI | 风险 |
|---|---|---|---|
| (a) | 不修, 引用 Step 6.3a STATUS_REPORT 替代 | 0 改动 + 0 风险 | line 89 自身仍漂移, 长期不闭环 |
| (b) | inline 注 PROJECT_FULL_AUDIT line 89 | 中 | **违 PR #172 锁** (PR #172 LOCK 不修原文件) |
| (c) | IRONLAWS §22 v3.0.3 entry 加引用 STATUS_REPORT 实测 | 中-高 | 0 触 PR #172 锁, 长期 audit log 链 |
| (d) | Step 6.3b 修原 PROJECT_FULL_AUDIT line 89 | 中 | **违 PR #172 锁** |

**决议**: 选项 **(c)** ⭐ — 沿用 PR scope 允许 "加 IRONLAWS §22 v3.0.3 entry", 0 触 PR #172 锁, 长期治理走 IRONLAWS audit log 链.

### §3.3 实施: IRONLAWS.md §22 v3.0.3 entry

加段位置: §22 v3.0.2 之后, v3.x+ 之前.

```markdown
- **v3.0.3** (2026-05-01, Step 6.3b PR Step 6.3b): CLAUDE.md 重构 + audit 沉淀
  - CLAUDE.md 全文件温和精简 (Path C, 813→~509 行, -37%): ...
  - **ADR-021 §4.5 "~150 行" target 实测推翻** (LL "假设必实测" 沉淀): ...
  - **PROJECT_FULL_AUDIT line 89 数字漂移 audit 沉淀** (沿用 Step 6.3a §2.2 + 本 PR WI 3 D71 决议选项 c): line 89 写 "剩 11 项 (T0-1 ~ T0-12 + T0-14)" 实测 = 9 项待修 (T0-4/5/6/7/8/9/10/12/14). 差 2 项源 = T0-1/2/3 在 line 81 标 "🟡 部分修" 但 line 89 整体 enumerate 时未减除. **PR #172 PROJECT_FULL_AUDIT 文件保持锁定** (历史 audit 时点真实记录), 修补走本条 v3.0.3 entry + Step 6.3a STATUS_REPORT §2 实测 audit log 链.
  - X10 stress test 实绩段累计第 9 次 (Step 6.3a) → 第 10 次 (本 PR Step 6.3b)
```

✅ **WI 3 完成** (IRONLAWS.md §22 v3.0.3 entry 落地).

---

## §4 Work Item 4 — Step 6.3a §3.2 表格修订决议 (沿用 D71)

### §4.1 实测 Step 6.3a §3.2 4 fail mode 表格

| # | fail mode | Step 6.3a 标记 | 实测验证状态 | 修订决议 |
|---|---|---|---|---|
| 1 | branch name 命中 hard pattern | ✅ 已 cover | ✅ 真有 PR #177 dry-run scenario 1 实测 (`dryrun-pass-test` branch 扫) | **保持 ✅** (实测充分) |
| 2 | amend commit 引入 hard pattern | ✅ 已 cover | ⚠️ **未实测** (claim "hook scan logic 不区分 amend vs 新 commit" 仅逻辑推理) | **修订 🟡 理论 cover** |
| 3 | cherry-pick 引入 hard pattern | ✅ 已 cover | ⚠️ **未实测** (claim "cherry-pick 创建新 commit, subject 沿用源 commit subject" 仅逻辑推理) | **修订 🟡 理论 cover** |
| 4 | merge commit subject 含 hard pattern | ⚠️ 理论 cover | ⚠️ 已诚实标 ⚠️ | **🟡 理论 cover** (与 §4.3 Row 4 决议统一, Step 6.4 G1 修订) |

### §4.2 D71 判断准确度

D71 判断: "Step 6.3a §3.2 4 fail mode 表格 ✅ 标记过度乐观 — 实际全 🟡 理论 cover".

**CC 实测部分准确**:
- D71 对 Row 2/3 准确 (✅ 标过度乐观, 应改 🟡)
- D71 对 Row 1 不准确 (Row 1 真有 PR #177 dry-run scenario 1 实测)
- D71 对 Row 4 不适用 (Row 4 已诚实标 ⚠️)

### §4.3 修订实施 (本 STATUS_REPORT 写新段, 不改 Step 6.3a 原文件)

沿用 D71 决议 — 不修原 STATUS_REPORT 避审计混乱. 修订内容沉淀本节 §4.

**修订后 §3.2 表格** (本 STATUS_REPORT §4.1 上表):
- Row 1 (branch name): ✅ 真已 cover (PR #177 实测)
- Row 2 (amend): 🟡 理论 cover (未实测 verify)
- Row 3 (cherry-pick): 🟡 理论 cover (未实测 verify)
- Row 4 (merge): 🟡 理论 cover (已诚实)

**留 Step 7+ 工程化测试** (低优先级):
- amend / cherry-pick / merge 的 hook scan 行为可写 dry-run scenario 验证 (沿用 PR #177 dry-run 模式)
- 候选实施: `tests/governance/test_x10_pre_push_hook.py` 新增 4 fail mode parametrize

✅ **WI 4 完成** (修订决议沉淀本 STATUS_REPORT, 不改 Step 6.3a 原文件).

---

## §5 Work Item 5 — handoff 文档治理 enumerate (Step 6.3b 仅 enumerate)

### §5.1 实测 handoff 现状

- **repo 内 docs/**: 0 命中 (`grep -rl "SESSION_HANDOFF\|session_handoff\|HANDOFF_2026" docs/` 仅 1 命中, 是 Step 6.3a STATUS_REPORT 内 reference SESSION_HANDOFF 不存在 doc, 沿用 Step 6.3a §4 #1 主动发现)
- **Anthropic memory 系统**: 含 `project_sprint_state.md` (实测) + `session_37_handoff_2026_04_26.md` + `session_38_handoff_2026_04_27.md` (实测 2 文件)
- **SessionStart hook 自动注入**: 工作正常 (本 session 开场实证, hook 注入 sprint state frontmatter)

### §5.2 候选治理路径 (CC enumerate, 不假设路径数)

| # | 路径 | Pro | Con | ROI 评估 |
|---|---|---|---|---|
| 1 | **保持现状** (Anthropic memory 唯一 SSOT, X5 单源化已落地) | 0 重复 / 0 改动 / 跨 session 自动注入工作正常 | 文档外部 / 单点风险 (Anthropic memory 服务不可用 = 失忆) | **高 ROI** ⭐ — memory 是 Anthropic 托管, 与 repo 一样可靠 |
| 2 | docs/handoff/ 镜像 docs (定期 sync memory → repo) | repo 内可追溯 / git history 完整 | 双源同步成本高 (每 session 关闭手工 sync) / **违 X5 单源化** | 低 ROI |
| 3 | docs/session/ 仅记 milestone (沿用 docs/audit/STATUS_REPORT_*) | 沉淀关键 milestone | vs STATUS_REPORT 重复 (现状 STATUS_REPORT 已记录 sprint milestone) | 低 ROI (重复) |
| 4 | git tag (每 sprint 末打 tag, message 含 handoff summary) | git 原生 / 0 docs 维护 | tag message 不可编辑 / Sprint 中迭代 handoff 不友好 | 中 ROI |
| 5 | GitHub Wiki / Discussions | 协作友好 / 版本化 | 出 repo / 失去 git source of truth / 不适用个人项目 | 不适用 |

### §5.3 决议

**enumerate 决议**: 路径 **1 (保持现状)** 最优 — Anthropic memory SSOT 工作正常 + X5 单源化对齐. 路径 2/3 重复, 路径 4 不友好, 路径 5 不适用.

**留 Step 7 / T1.4 决议是否升级** (本 PR 仅 enumerate 不实施).

**自洽性检查**: Step 6.3a §4 #1 主动发现 写 "SESSION_HANDOFF doc 0 命中, handoff 不在 repo, inter-session asset 单点风险". 本 §5 实测确认 — 单点风险存在但 ROI 评估下保持现状最优 (memory 自动注入工作正常 + 不违 X5).

✅ **WI 5 完成** (5 候选 enumerate, 路径 1 决议, 留 Step 7+).

---

## §6 主动发现累计

### §6.1 sprint period 第 N+1 假设错 (LL "假设必实测" sediment)

**沿用 Step 6.3a §5 narrower 30 / broader 35 + LL 总数 92 baseline**.

本 PR 累计 (CC 实测决议):

| # | 假设源 | 实测推翻 | narrower / broader / 0 |
|---|---|---|---|
| #1 | prompt §0 E8 假设 "position_snapshot live 0 行" | 实测 trade_date=4-28 stale 19 行 (T0-19 P1 已 enumerate) | **broader +1** (sprint period 累积假设错) |
| #2 | ADR-021 §4.5 "~150 行" target | 实测 SSOT 现实约束下不可达 (STOP-1 + STOP-2 双触发, Path C 折中 ~509 行) | **broader +1** + 沉淀 IRONLAWS §22 v3.0.3 entry |
| #3 | D71 判断 "Step 6.3a §3.2 4 fail mode 全 🟡 理论 cover" | 实测 Row 1 ✅ 真有 dry-run scenario 1 实测, Row 4 ⚠️ 已诚实, 仅 Row 2/3 ✅ 标过度乐观 | **broader +1** (D71 部分准确) |
| #4 | prompt 引用 SESSION_HANDOFF doc | 实测不存在 (Step 6.3a §4 #1 已 enumerate) | (sustained Step 6.3a 主动发现) |

**本 PR sediment**:
- narrower (LL 内文链): **30** unchanged (本 PR audit doc only, 0 LL 沉淀)
- broader (PROJECT_FULL_AUDIT scope): **35 → 38** (沿用 Step 6.3a 35 + 本 PR 3 新发现)
- LL 总数: **92** unchanged

### §6.2 其他主动发现

#### #5 IRONLAWS.md §22 v3.0.3 entry 加入 → 第 4 个版本 entry (v3.0 / v3.0.1 / v3.0.2 / v3.0.3) — sprint period 治理腐烂高发率反映

每 sprint period PR 沉淀一个版本 entry (PR #174 v3.0 / PR #176 v3.0.1 / PR #177 v3.0.2 / 本 PR v3.0.3). 4 entries / 1 day. 沿用 X5 文档单源化, 治理债 audit log 链 functional. 评估: **可接受频率** (sprint period treadmill, 每 PR 都沉淀 audit log 是治理目标, 不是问题).

#### #6 CLAUDE.md 文件归属规则段加入 IRONLAWS.md (本 PR 第 1 次 sediment 加入根目录 5 doc 列表)

旧版本仅 4 doc (CLAUDE / SYSTEM_STATUS / LESSONS_LEARNED / FACTOR_TEST_REGISTRY). PR #174 IRONLAWS.md 落地后, 其作 SSOT 也应入根目录列表. 本 PR §文件归属规则 + §文档层级 同步 (CLAUDE.md L475 + L497).

#### #7 PT 重启 gate prerequisite 中 T0-19 已 PR #168 落地

handoff §1 写 T0-19 P1 (emergency_close 后没自动刷 DB), 但实测 (沿用 SHUTDOWN_NOTICE §9): "T0-19 已 PR #168 落地". CLAUDE.md 重构后 §策略配置 PT 状态段已对齐 (写 "T0-19 已 PR #168 落地"). prompt 假设 T0-19 still待修 漂移源 = handoff §1 是 4-30 ~18:30 时点真实, PR #168 是 sprint period 后续 merge — sustainable.

#### #8 SYSTEM_STATUS.md 5d stale 持续未修 (Step 6.3a §4 #3 enumerate 后 1 天未修)

本 PR 不触 SYSTEM_STATUS (PR scope 限制). 留 Step 7+ 修订 (沿用 Step 6.3a §4 #3 决议).

---

## §7 LL-098 stress test 第 10 次 verify

**主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作.

**子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件.

**本 PR 末尾 verify 清单**:
- ❌ 不写 "Step 6.3c 启动" / "Step 7 启动" / "T1.3 架构研讨"
- ❌ 不写 "schedule agent 5d dry-run" / "paper-mode" / "cutover"
- ❌ 不写 "PT 重启 gate 解锁" / 任何前推动作
- ✅ 等 user 显式触发

**累计 stress test 次数**: 第 10 次 (PR #173 → PR #174 → PR #175 → PR #176 → PR #177 → Step 6.3a → 本 PR Step 6.3b 累计 10 次连续 verify, 0 失守).

---

## §8 验收 + 文件改动清单

### §8.1 文件改动 (CC 实测)

| 文件 | 改动 | 行数 |
|---|---|---|
| `CLAUDE.md` | Path C 温和精简 | 813 → 509 (-304) |
| `IRONLAWS.md` | §22 v3.0.3 entry 加段 | +6 |
| `docs/audit/STATUS_REPORT_2026_05_01_step6_3b.md` | 新建 (本文件) | 新文件 |

**0 改动** (PR scope hard 边界守门):
- 任何业务代码 (backend/ scripts/)
- .env / configs/
- LESSONS_LEARNED.md
- IRONLAWS.md 已有段 (除 §22 v3.0.3 entry 加段)
- ADR-021
- SNAPSHOT
- config/hooks/pre-push
- STATUS_REPORT_step6_3a (沿用 D71)
- 任何 INSERT / UPDATE / DELETE / TRUNCATE / DROP SQL
- Servy / schtask / Beat 重启

### §8.2 验收清单

- ✅ E1-E14 全 (含 E8 ⚠️ T0-19 known debt)
- ✅ WI 1 CLAUDE.md 重构 (Path C 决议 + STOP-1+2 sediment + 813→509)
- ✅ WI 2 5 层叠加 audit (0 新 P0 / 1 P1 enumerate / P2 acceptable)
- ✅ WI 3 PROJECT_FULL_AUDIT line 89 修补 (D71 选项 c IRONLAWS §22 v3.0.3 entry)
- ✅ WI 4 Step 6.3a §3.2 修订决议 (CC 实测 D71 部分准确, 修订沉淀本 §4)
- ✅ WI 5 handoff enumerate (5 候选, 路径 1 保持现状最优, 留 Step 7+)
- ✅ WI 6 STATUS_REPORT (本文件)
- ✅ LL-098 stress test 第 10 次 (末尾 0 forward-progress offer)
- ✅ 第 19 条铁律第 6 次 (prompt 不假设具体数字, CC 实测决定 — 含 line count / 段数 / target 行数 / fail mode 计数 / 候选路径数 等)

### §8.3 sprint 治理基础设施 5 块基石维持

| 基石 | 状态 |
|---|---|
| 1. IRONLAWS.md SSOT (v3.0+) | ✅ 维持 (本 PR 加 v3.0.3 entry) |
| 2. ADR-021 编号锁定 | ✅ 维持 |
| 3. 第 19 条 memory 铁律 (prompt 不假设数字) | ✅ 第 6 次 verify |
| 4. X10 + LL-098 + pre-push hook | ✅ 维持 (LL-098 第 10 次 stress test) |
| 5. §23 双口径计数规则 | ✅ 维持 (本 PR sediment broader +3, narrower 0) |

---

## §9 关联 + 后续

### §9.1 关联 PR

- PR #172 (Step 5 PROJECT_FULL_AUDIT + SNAPSHOT): 锁定文件保持, line 89 修补走 IRONLAWS §22 v3.0.3 audit log
- PR #173 (Step 6.1 LL-098 沉淀): X10 候选声明 source
- PR #174 (Step 6.2 IRONLAWS + ADR-021 + X10 inline): 铁律段 reference 化锁定
- PR #175 (Step 6.2.5a 纯 audit): D 决议链 source (D-1=A / D-2=A / D-3=A)
- PR #176 (Step 6.2.5b-1 文档修订): IRONLAWS v3.0.1 + §21.1 ADR 历史决议保留 + §23 双口径
- PR #177 (Step 6.2.5b-2 hook 实施): IRONLAWS v3.0.2 + pre-push X10 守门 + dry-run 3 场景
- PR #178 (Step 6.3a 6+1 audit + Tier 0 enumerate): 9 项 Tier 0 enumerate + 4 项主动发现 source
- **本 PR Step 6.3b**: CLAUDE.md 重构 (Path C) + IRONLAWS v3.0.3 + 5 层叠加 audit + line 89 修补 + §3.2 修订 + handoff enumerate

### §9.2 后续治理债 (留 Step 7+ / T1.4+)

| 债 | 来源 | 优先级 |
|---|---|---|
| SYSTEM_STATUS.md 5d stale 修订 | Step 6.3a §4 #3 + 本 PR §6 #8 | P1 |
| FACTOR_TEST_REGISTRY.md 3w stale 修订 | Step 6.3a §4 #4 | P2 |
| 9 项 Tier 0 待修 (T0-4/5/6/7/8/9/10/12/14) | Step 6.3a §3.1 | P0/P1 各异 |
| Step 6.3a §3.2 4 fail mode amend/cherry-pick/merge dry-run scenario 工程化 | 本 PR §4.3 | P3 (低) |
| handoff 治理候选评估 (Step 7 决议是否升级路径 1 → 路径 4) | 本 PR §5.3 | P3 |
| DEV_BACKEND.md §一 扩 platform/scripts (1 P1 SSOT 漂移) | 本 PR §2.2 #P1-1 | P2 |
| 已知失败方向 research-kb 完整迁移 (8 → 30+ 项) | 本 PR §1.2 STOP-2 验证 | P2 |
| 候选 X1/X3/X4/X5 promote 评估 | ADR-021 §2.3 + IRONLAWS §19 | (留 Step 6.2.5+ / Step 7+) |

---

**STATUS_REPORT 写入完成 (2026-05-01 ~00:30, ~480 行)**.
