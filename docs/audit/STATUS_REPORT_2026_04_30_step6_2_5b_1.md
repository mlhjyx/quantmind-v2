# STATUS_REPORT — Step 6.2.5b-1 文档修订 (2026-04-30 ~22:45)

**PR**: chore/step6-2-5b-1-doc-revisions
**Base**: main @ `cc1553e` (PR #175 Step 6.2.5a 纯 audit 决议 merged)
**Scope**: 5 work item, 改 IRONLAWS.md + ADR-021 (2 文件 + 本 STATUS_REPORT = 3 文件改).
**真金风险**: 0 (纯文档修订, 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 hook 实施)
**LL-098 stress test**: 第 7 次

---

## §0 环境前置检查 (E1-E13)

| 检查 | 实测 | 状态 |
|---|---|---|
| E1 git | main HEAD = `cc1553e` (PR #175), 工作树干净 (开始时) | ✅ |
| E2 PG stuck | 沿用 4-30 ~22:00 PR #175 baseline | ✅ (沿用) |
| E3 Servy | 沿用 PR #175 baseline | ✅ (沿用) |
| E4 venv | Python 3.11.9 | ✅ |
| E5 LIVE_TRADING_DISABLED | True | ✅ |
| E6 真账户 | 沿用 4-30 14:54 实测 | ✅ (沿用) |
| E7 cb_state.live nav | 993520.16 (PR #171 reset) | ✅ (沿用) |
| E8 position_snapshot 4-28 live | 0 行 (PR #171 DELETE) | ✅ (沿用) |
| E9 PROJECT_FULL_AUDIT + SNAPSHOT | 实存 (PR #172) | ✅ |
| E10 LL-098 | L3032 实存 (PR #173) | ✅ |
| E11 IRONLAWS.md | 实存 (PR #174 创建, 791 行) | ✅ |
| E12 ADR-021 | 实存 (PR #174 创建, 206 行) | ✅ |
| E13 PR #175 6.2.5a STATUS_REPORT | 实存 (audit 决议来源) | ✅ |

---

## §1 5 项 work item 逐答

### Work Item 1 — IRONLAWS.md §18 X10 检测脚本候选语义修订

**原内容** (IRONLAWS.md L711-714, PR #174 锁定状态):
```
#### 检测脚本候选 (Step 6.2.5+)

- pre-merge hook grep PR description / commit message 含 "schedule agent" / "paper-mode 5d" / "auto cutover" / "next step ..." 类 forward-progress 关键词 → block + 提示 X10 checklist
- Claude system prompt-level guard — 末尾输出阶段 detect forward-progress 关键词, 自动 strip 或要求二次 confirm
```

**修订后** (IRONLAWS.md L719-728, PR #175 §1 主题 A 决议落地):
- 加修订声明 (沿用 PR #175 §7 #1 实证)
- pre-merge → **commit-msg hook 或 pre-push extension** (Git 原生支持)
- 加 cutover-bias 关键词清单分两类:
  - 硬阻 hard pattern (减误报): `/schedule agent` / `paper-mode 5d` / `paper-mode dry-run` / `paper→live` / `auto cutover` / `自动 cutover`
  - 不阻 generic pattern (高误报): "next step" / "下一步" / "Step X.Y" 描述路径词
- 误报绕过机制说明 (`--no-verify` + commit message 写 reason, 沿用铁律 33-d silent_ok 模式)
- Claude system prompt-level guard 留 Wave 5+ 远期

**实测**: ✅ 修订完成 (Edit 操作成功).

### Work Item 2 — 4 条 backref header 标准化

CC 实测 + 修订:

| 铁律 | 原状态 | 修订后 | 行号 (修订后) |
|---|---|---|---|
| **16** (信号路径) | inline "LL-051+" 在 §1 table, §7 内文无 header | + `**LL backref**: LL-051 (开源优先) / LL-054 (PT 状态实测)` | L262 |
| **25** (代码变更前必读) | inline "LL-019 + 本 sprint" 在 §1 table, §12 内文无 header | + `**LL backref**: LL-019` | L396 |
| **38** (Blueprint) | inline "ADR-008" 在 §1 table, §15 内文无 header | + `**ADR backref**: ADR-008 (execution-mode-namespace-contract)` | L547 |
| **42** (PR 分级) | inline "LL-051 / LL-054 / LL-055" 在 §1 table, §16 内文无 header | + `**LL backref**: LL-051 / LL-054 / LL-055` | L611 |

**实测**: ✅ 4 条全部修订完成 (Edit 操作成功). 沿用 PR #175 §4 D.4 例外建议.

### Work Item 3 — IRONLAWS §21 + ADR-021 §3 加 ADR 历史保留注释

**IRONLAWS.md §21.1 新加** (L791-803):
- 子段 "ADR 编号系统历史决议保留 (Step 6.2.5b-1, 沿用 PR #175 §6 主题 F F.5)"
- 表格 4 行 (ADR-0009 / ADR-010 双 / ADR-015~020 gap / ADR-021)
- 修订时点候选: Wave 5+ 远期
- 防未来 sprint 重提 rename 声明

**ADR-021 §3.6 新加** (L156-167):
- 子段 "ADR 编号系统历史决议保留 (Step 6.2.5b-1 沉淀, 沿用 PR #175 §6 主题 F F.5)"
- 同样 4 行表格 + 同样修订时点候选 + 防 rename 声明

**实测**: ✅ 双向沉淀 (IRONLAWS §21.1 + ADR-021 §3.6) 完成. SSOT 历史决议保留声明在两处对齐.

### Work Item 4 — IRONLAWS.md 新 §23 双口径计数规则

**位置选择 (Q4 决议)**: ✅ 选 (a) IRONLAWS.md 新加 §23.

**论据**:
- (a) 新独立段 §23: 显式独立 SSOT, 后续 PR 引用清晰
- (b) §22 末加子段: §22 是版本变更记录, 双口径规则不属版本变更, 语义错位
- (c) LL-098 内文: PR #173 锁, 不可改

**§23 内容** (IRONLAWS.md L828-874):
- §23.1 narrower 口径: LL-091~ 起, 起点 22, 严格 +1, 当前 30
- §23.2 broader 口径: PROJECT_FULL_AUDIT scope, 起点 31, 累加规则三种 (LL+1+1 / audit doc +1 / cross-PR 候选 +1), 当前 34
- §23.3 双口径并存论据 (不合并不替代)
- §23.4 broader 34 决议 (本 PR 沉淀 +1, 沿用 Q5 决议 (a))
- §23.5 后续 PR 累加范围 (沉淀位置 + 修订规则)

**实测**: ✅ §23 完整新加 + 占用 IRONLAWS.md L828-874 (47 行新加).

### Work Item 5 — broader 34 候选状态决议

**Q5 决议**: ✅ 选 (a) — 本 PR 沉淀 broader +1 = 34.

**论据**:
- PR #175 §7 #1 "Git 不支持 pre-merge hook" 是真实证 (LL "假设必实测" 同质)
- 本 PR audit doc + IRONLAWS.md §18 修订是 audit doc 沉淀点, broader +1 合理
- 不沉淀 LL-099 (沿用 PR #175 §5 主题 E E.3 决议: 编号膨胀风险)
- narrower 30 不变 (本 PR 0 新 LL)

**实测**: ✅ §23.4 显式声明决议 (a). 后续 PR 沿用 §23.5 累加范围.

---

## §2 改动 diff verify

### IRONLAWS.md before/after diff (关键段)

#### §18 X10 检测脚本候选 (L711 → L719+)

**Before** (PR #174 锁, 4 行):
```markdown
#### 检测脚本候选 (Step 6.2.5+)

- pre-merge hook grep PR description / commit message 含 "schedule agent" / "paper-mode 5d" / "auto cutover" / "next step ..." 类 forward-progress 关键词 → block + 提示 X10 checklist
- Claude system prompt-level guard — 末尾输出阶段 detect forward-progress 关键词, 自动 strip 或要求二次 confirm
```

**After** (本 PR 修订, 11 行):
```markdown
#### 检测脚本候选 (Step 6.2.5+)

> **修订 (Step 6.2.5b-1, 沿用 PR #175 §1 主题 A 决议 + §7 主动发现 #1)**: Git 原生不支持 `pre-merge` hook (PR #175 实测). 修订为 **commit-msg hook (commit 时阻) 或 pre-push extension (push 时阻)** — Git 原生支持.

- **commit-msg hook 或 pre-push extension** — grep PR description / commit message / branch name 含 cutover-bias **hard pattern** 关键词 → block + 提示 X10 checklist
  - **硬阻 hard pattern** (减误报): `/schedule agent` / `paper-mode 5d` / `paper-mode dry-run` / `paper→live` / `auto cutover` / `自动 cutover`
  - **不阻 generic pattern** (工程文档语境合法, 高误报): "next step" / "下一步" / "Step X.Y" 类描述路径词
  - 误报需绕过: `git commit --no-verify` / `git push --no-verify` + commit message 显式声明违规理由 (沿用铁律 33-d silent_ok 模式)
- **Claude system prompt-level guard** (Wave 5+ 远期, 依赖 Anthropic API custom system prompt) — 末尾输出阶段 detect forward-progress 关键词, 自动 strip 或要求二次 confirm
```

#### 4 条铁律 backref header 加 (L262 / L396 / L547 / L611)

每条加 1-2 行 header (沿用 §1 主题 D D.4 例外建议):
- L262 铁律 16: `**LL backref**: LL-051 (开源优先) / LL-054 (PT 状态实测) — 信号路径分裂的两个早期触发事件.`
- L396 铁律 25: `**LL backref**: LL-019 (代码变更前必读源码).`
- L547 铁律 38: `**ADR backref**: ADR-008 (execution-mode-namespace-contract) — Blueprint 漂移导致跨 session execution_mode 命名空间错乱的实例.`
- L611 铁律 42: `**LL backref**: LL-051 / LL-054 / LL-055.`

#### §21.1 新加 (L791-803)

13 行 ADR 编号系统历史决议保留子段 (ADR-0009 / ADR-010 双 / ADR-015~020 gap / ADR-021 维持现状 + 修订时点候选 Wave 5+ + 防未来 rename 声明).

#### §22 v3.0.1 entry (L815-820)

5 行版本变更记录 (Step 6.2.5b-1 PR 修订项: §18 X10 / 4 条 backref / §21.1 ADR 历史 / §23 双口径).

#### §23 新加 (L828-874)

47 行新独立段 (§23.1-§23.5).

**总变化**: IRONLAWS.md 791 行 → 874 行 (+83 行 +10.5%).

### ADR-021 before/after diff (§3 子段)

#### §3.6 新加 (L156-167)

12 行 ADR 编号系统历史决议保留子段 (与 IRONLAWS.md §21.1 双向对齐, 防 rename).

**总变化**: ADR-021 206 行 → 221 行 (+15 行 +7%).

---

## §3 主动发现 (Step 6.2.5b-1 副产品)

1. **§18 X10 检测脚本候选 PR #174 写时假设错** — Git 不支持 pre-merge hook. 本 PR 修订. 沉淀 broader 34 (§23.4 决议 (a)).
2. **§22 版本变更记录加 v3.0.1 entry** — 沿用铁律 22 文档跟随代码 + 铁律 X5 文档单源化, 任何后续 IRONLAWS.md 修订必加 §22 entry.
3. **§21.1 + ADR-021 §3.6 双向对齐** — SSOT 历史决议保留声明双处沉淀, 减未来 sprint 重提 rename 风险.
4. **§23 双口径累加规则** — sprint period 之前散落在 PR #173/#174/#175 STATUS_REPORT §3, 本 PR 正式化进 SSOT.
5. **铁律 16/25/38/42 backref header 标准化** — 不补 Inline 教训类 ref (沿用 PR #175 §4 D.4 决议 iii: 真孤儿 0 条, 大部分 inline 教训已足够). 仅补已有 LL/ADR 编号的 4 条.

---

## §4 LL "假设必实测" 累计更新

| 口径 | PR #175 后 | 本 PR (Step 6.2.5b-1) 后 |
|---|---|---|
| narrower (LL 内文链 LL-091~) | 30 | **30** (本 PR 0 新 LL) |
| broader (PROJECT_FULL_AUDIT scope) | 33 (实际) / 34 候选 | **34** (本 PR 沉淀 PR #175 §7 #1 Git pre-merge 实证) |
| LL 总条目 | 92 | **92** (本 PR 0 新 LL) |

⚠️ **discrepancy 持续**: narrower 30 vs broader 34, 差 4. 沿用 §23.3 双口径并存论据 (主题 B B.5 决议).

---

## §5 不变

- Tier 0 债 11 项不变 (本 PR 不动)
- LESSONS_LEARNED.md 不变 (PR #173 锁, LL 总数 92, 0 新 LL)
- CLAUDE.md 不变 (PR #174 锁) — IRONLAWS.md 是 SSOT, CLAUDE.md 是 reference, 改 IRONLAWS 不需同步改 CLAUDE.md (沿用 PR #174 D-1=A reference 设计)
- PROJECT_FULL_AUDIT / SNAPSHOT 不变 (PR #172 锁)
- 其他 ADR 不变 (ADR-NNN ≠ 021)
- 其他 docs 不变 (含 SYSTEM_RUNBOOK / SYSTEM_STATUS / DEV_*.md / MEMORY / 等)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 真金风险 / 0 触 LIVE_TRADING_DISABLED
- 0 hook 实施 (留 6.2.5b-2)
- 真账户 ground truth 沿用 4-30 14:54 实测 (0 持仓 + ¥993,520.16)
- PT 重启 gate 沿用 PR #171 7/7 PASS

---

## §6 关联

- **本 PR 文件**: IRONLAWS.md (修改, +83) / docs/adr/ADR-021-ironlaws-v3-refactor.md (修改, +15) / docs/audit/STATUS_REPORT_2026_04_30_step6_2_5b_1.md (新建, 本文件)
- **关联 PR**: #170 (X9) → #171 (PT gate) → #172 (Step 5) → #173 (Step 6.1) → #174 (Step 6.2) → #175 (Step 6.2.5a audit) → 本 PR (Step 6.2.5b-1 文档修订)
- **关联 LL**: LL-097 (X9) / LL-098 (X10) / LL-001 series ~ LL-098
- **关联 ADR**: ADR-021 (PR #174 + 本 PR §3.6)
- **关联铁律**: 22 / X4 / X5 / X9 / X10 (本 PR 第 7 次 stress test) / 16/25/38/42 backref header (本 PR 修订)

---

## §7 LL-059 9 步闭环不适用 — 沿用 PR #172/#173/#174/#175 LOW 模式

本 PR 是文档修订 (0 业务代码 / 无 smoke 影响), 跳 reviewer + AI self-merge.

LL-098 stress test 第 7 次 verify (沿用 LL-098 规则 1+2):
- PR description / 本 STATUS_REPORT / 任何末尾 0 写前推 offer
- 不 offer "Step 6.2.5b-2 启动" / "Step 6.3 启动" / "Step 7" / "paper-mode" / "cutover"
- 等 user 显式触发
