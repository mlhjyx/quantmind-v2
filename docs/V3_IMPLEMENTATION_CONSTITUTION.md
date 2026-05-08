# QuantMind V3 实施 Constitution

> **本文件 = V3 风控长期实施期 (跨 session / 跨 sub-PR / 跨 stage) CC 自主跑通的元规则集**.
>
> **本文件 +** `V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` (step 2) **+** 自造 13 skill (step 3) **+** 自造 8 hook (step 4) **+** 自造 7 subagent (step 5) **+** 启动 prompt (step 6) **= 6 件套**, 共同支撑 V3 closure.
>
> **scope**: V3 quantmind 项目特有 invariant + skill/hook/agent invocation 索引 + user 介入 enforcement + V3 closure 终态 criteria.
>
> **not scope** (plugin handle): 通用 spec / brainstorm / plan / TDD / debug / review 方法论 → superpowers / 通用 grill / git guard / interface design / token 优化 → mattpocock / harness 性能 / hook 框架 / strategic compaction → ECC.
>
> **not scope** (现有 SSOT 处理): 4 doc fresh read SOP → SESSION_PROTOCOL §1 / 铁律 → IRONLAWS / D 决议 → DECISION_LOG / LL → LESSONS_LEARNED / ADR # → docs/adr/REGISTRY.md / handoff → handoff_template.
>
> **本文件版本**: v0.2 (post-audit reality grounding, 沿用 ADR-022 反 silent overwrite — v0.1 row 保留 + version history append)
> **关联 audit**: `docs/audit/v3_orchestration/claude_dir_audit_report.md` (PR #270, 2026-05-08, 22 row 真值表 + 8 finding cross-verify drift 率 25%)
> **关联 ADR**: ADR-019 / ADR-020 / ADR-021 / ADR-022 / ADR-027 / ADR-028 / ADR-037 + 后续 V3 实施期 ADR (含 ADR-DRAFT row 11/12/13 候选)

---

## §0 元信息 + 锚点 + 反 anti-pattern 验证

### §0.1 SSOT 锚点 (reference, 0 inline 重复)

| 类别 | 锚点 |
|---|---|
| V3 设计 | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` |
| 项目入口 | `CLAUDE.md` |
| 铁律 | `IRONLAWS.md` (v3.0) |
| session SOP | `docs/SESSION_PROTOCOL.md` |
| LL backlog | `LESSONS_LEARNED.md` |
| ADR REGISTRY | `docs/adr/REGISTRY.md` |
| handoff 模板 | `docs/handoff_template.md` |
| D 决议 | `docs/DECISION_LOG.md` |
| ops runbook | `docs/runbook/cc_automation/00_INDEX.md` |
| invocation map | `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` (step 2 产出) |
| 长期 Roadmap | `docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` (V3 §18.3 reserved) |

### §0.2 反 anti-pattern 验证 (沿用 ADR-022 集中机制)

- ✅ 不创建新 IRONLAWS audit log entry
- ✅ 0 凭空 enumerate 新决议 (V3 §20.1 10 决议 closed PR #216, 不再讨论)
- ✅ 0 凭空削减 V3 §12 sprint 拆分 (本文件 = orchestration 层 reference V3 §12)
- ✅ 0 末尾 forward-progress offer (LL-098 X10)
- ✅ 0 "真+词" 禁词 (memory #25 HARD BLOCK, 仅允许 真账户 / 真发单 / 真生产 / 真测 / 真值)

### §0.3 Layer 编号说明

本文件仅写 **L0 / L1 / L5 / L6 / L8 / L10 六层** (V3 quantmind 特有 invariant). 其余 layer 由 plugin 或自造 skill 处理:

| Layer | 由谁 handle |
|---|---|
| L0 身份 + 起手 verify + V3 closure 终态 | 本文件 §L0 |
| L1 governance 锚点 (reference) | 本文件 §L1 (reference, 不 inline) |
| L2 自主 decomposition | superpowers `brainstorming` + `writing-plans` |
| L3 closed loop self-eval (sprint/stage gate) | 自造 `quantmind-sprint-closure-gate` skill (step 3) + 自造 `tier-a-mvp-gate-evaluator` subagent (step 5) |
| L4 active discovery enforcement | mattpocock `grill-me` + 自造 `quantmind-active-discovery` skill (step 3) |
| L5 anti-hallucination guard | 本文件 §L5 (plugin 不覆盖, 必留) |
| L6 skill + agent + hook 协调索引 | 本文件 §L6 (索引向 invocation map) |
| L7 documentation sediment automation | 自造 `quantmind-doc-sediment-auto` skill (step 3) + `sediment-poststop` hook (step 4) |
| L8 user 介入 3 类 enforcement | 本文件 §L8 |
| L9 long-horizon coherence | ECC `Strategic compaction` skill + 自造 `handoff-sessionend` hook + memory `project_sprint_state.md` |
| L10 V3 closure 5 大终态 gate | 本文件 §L10 |

---

## §L0 身份 + V3 closure 起手 + 终态双锚定

### §L0.1 CC 身份

CC 是 V3 风控实施期 quantmind 项目主实施 agent. 协作模式沿用:

- **LL-059 autonomous**: reviewer agent + AI self-merge 自跑 (audit / docs / ADR / GLOSSARY / 纯 read-only doc 类)
- **LL-100 chunked SOP**: 单 PR sediment ≤ ~8 min target, 超阈值拆 ≥2 chunked PR
- **memory #24 user 介入限 3 类**: scope 关键决议 / 真生产红线触发 / sprint 收口决议

### §L0.2 V3 closure 5 大 gate (终态显式可测)

V3 closure 完成 = 以下 5 大 gate 全 ✅. 详细判定 criteria 见本文件 §L10. 高级总览:

| Gate | scope |
|---|---|
| **A: Tier A closed** | V3 §12.1 Sprint S1-S11 全 closed + paper-mode 5d ✅ + 元监控 0 P0 元告警 + Tier A ADR 全 committed |
| **B: T1.5 closed** | V3 §11.4 backtest_adapter 实现 + 12 年 counterfactual replay 跑通 + WF 5-fold 全正 STABLE |
| **C: Tier B closed** | V3 §12.2 Sprint S12-S15 全 closed + L2 Bull/Bear + L2 RAG + L5 Reflector production-active + Tier B ADR 全 committed |
| **D: 横切层 closed** | V3 §13 元监控 + §14 失败模式 12 项 + §17.1 CI lint + prompts/risk eval iteration ≥1 round |
| **E: PT cutover gate ✅** | paper-mode 5d 通过 + 元监控 0 P0 + Tier A ADR 全 sediment + 5 SLA 满足 + 10 user 决议状态 verify + user 显式 .env paper→live 授权 |

### §L0.3 起手前 verify (反 ECC issue 1479 实证 + audit reality grounding)

CC 第一次 V3 实施 sprint 起手前必走 verify (5 步任一不通过 → STOP + 反问 user). v0.2 修订: step (3) sediment 现实 (audit §4 cite — `session_context_inject.py v2` 已 wired SessionStart, 反 v0.1 cite "fresh-read-sessionstart hook" 0 存在 silent 创建):

| 步 | verify | tool |
|---|---|---|
| (1) plugin 装上 | 用户级 `~/.claude/plugins/` (audit row 22 真测): mattpocock-skills + superpowers + everything-claude-code (ECC) + oh-my-claudecode (OMC) 全 enabled. 项目级 `.claude/external-skills/mattpocock-skills/` clone 真测 | `Get-ChildItem` 真测 |
| (2) slash command trigger | OMC tier-0 (autopilot / ultrawork / ralph / team / ralplan / deep-interview / ai-slop-cleaner / TDD / deepsearch / ultrathink) + mattpocock 选片 (grill-me / git-guardrails / zoom-out / write-a-skill / caveman / setup-matt-pocock-skills) + ECC (/harness-audit / /quality-gate / /loop-status) cli output capture verify | trigger 实测 + 沿用 SESSION_PROTOCOL §3.3 mtime 漂移 detect |
| (3) SessionStart hook fire | 现 `.claude/hooks/session_context_inject.py` v2 (audit row 11 真测已 wired) 跑出 4 root doc + V3 doc 扩展 mtime cite. v0.2 修订 scope: 扩 V3 doc fresh read trigger (反全新 hook 创建, 沿用 ADR-022 反 abstraction premature) | 现 hook log 真测 + 扩展候选走 sub-PR (§L6.2 修订决议) |
| (4) 自造组件 verify | `.claude/skills/quantmind-v3-*/SKILL.md` 13 个 (跟现 6 quantmind-* 0 命名冲突) + `.claude/hooks/*.py` 4 全新 + 4 现有扩展 + `.claude/agents/quantmind-*.md` 4 全新 + 3 借 OMC charter file. v0.1 cite "13 skill / 8 hook / 7 subagent" 总数沿用, 但实施分类分 全新 vs 现有扩展 vs OMC borrow (audit §7 真值) | `ls` + `cat` 真测 + audit cite cross-verify |
| (5) 红线 5/5 verify | cash / 持仓 / LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID | `python scripts/_verify_account_oneshot.py` |

**任一漂移 → STOP + 反问 user**, 不强行起手 sprint.

### §L0.4 timeline baseline + replan 触发

- **baseline**: progress report Part 4 cite (~12-16 周, 紧)
- **replan 触发**: 任 stage 实际超 baseline 1.5x → CC 主动 push user (sprint 收口决议) + replan template
- **replan template**: 治理债 surface + sub-task creep cite + remaining stage timeline 修订 + Tier B / cutover 时间窗口重谈

---

## §L1 governance 锚点 (reference, 0 inline 重复)

### §L1.1 必读 doc — 8 doc fresh read sub-PR 起手 (扩展 SESSION_PROTOCOL §1.3 4 doc; audit §8 cite 6 committed + 2 planned)

| Doc | 状态 | 沿用 SOP |
|---|---|---|
| `CLAUDE.md` | committed ✅ | SESSION_PROTOCOL §1.3 |
| `IRONLAWS.md` | committed ✅ | SESSION_PROTOCOL §1.3 |
| `LESSONS_LEARNED.md` | committed ✅ | SESSION_PROTOCOL §1.3 |
| `SYSTEM_STATUS.md` | committed ✅ | SESSION_PROTOCOL §1.3 |
| `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | committed ✅ | 本 plan 新增 — V3 实施期 main spec |
| `docs/V3_IMPLEMENTATION_CONSTITUTION.md` (本文件) | committed ✅ (本 v0.2 修订 sub-PR 后) | 本 plan 新增 |
| `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` | **planned** (step 2 sediment 待生 — 与本 v0.2 同 PR 或下 sub-PR) | 本 plan 新增 |
| `docs/adr/REGISTRY.md` | committed ✅ | 本 plan 新增 — ADR # SSOT (LL-105 SOP-6) |

→ 现 `.claude/hooks/session_context_inject.py` v2 (audit row 11 真测 wired SessionStart) 已 inject 4 root doc + Blueprint cite. **扩展候选**: V3 doc + Constitution + invocation map + REGISTRY 4 doc 加入 inject scope, 走 §L6.2 决议的 hook 扩展 sub-PR (反 silent 全新创建 fresh-read-sessionstart, 沿用 ADR-022 + audit §4 真值).

### §L1.2 必沿用 SOP

| SOP | 锚点 |
|---|---|
| 4 doc + 4 doc 扩展 fresh read | SESSION_PROTOCOL §1.3 |
| cite source 锁定 4 元素 (doc + line# + section + timestamp) | SESSION_PROTOCOL §3.1 + LL-101/104/105 |
| handoff sediment (sql_verify 全 cite) | handoff_template + memory `project_sprint_state.md` (铁律 37) |
| ADR # registry SSOT | docs/adr/REGISTRY.md (LL-105 SOP-6) |
| LL append-only sediment | ADR-022 不 silent overwrite |
| chunked PR (~8 min target) | LL-100 |
| reviewer agent + AI self-merge | LL-067 + LL-100 |
| 6 块 prompt 模板 | memory #15 (背景 / 强制思考 / 主动发现 / 挑战假设 / 硬执行边界 / 输出含 finding+next prompt+STATUS_REPORT) |
| 9 项自检 | memory #18 (三件事 / 找漏 / 反驳 / 跨决策一致性 / 边界 / 主动建议 / SSOT 防腐 / 长期>短期 / 认错) |
| prompt 设计 0 数字/path/command | memory #19/#20 (写"方向+目标+验收", CC 实测决议具体值) |
| 表达风格 banned 真+词 | memory #25 (Ctrl-F 检查) |

### §L1.3 必沿用 anti-pattern 守门 v1-v5

| anti-pattern | 守门方式 | 沿用 |
|---|---|---|
| **v1 凭空数字** | 必 cite source 4 元素 (handoff_template §3) | LL-101 |
| **v2 凭空 path/file** | 必 ls/find/glob/cat verify | memory #20 broader |
| **v3 信 user GUI cite** | 必 CC SQL/script/log cross-check | LL-103 SOP-4 |
| **v4 静态 grep ≠ 真测 verify** | 必 run command + output cite, 0 grep/cat 推断 | memory anti-pattern v4.0 |
| **v5 Claude 给具体 → CC 实测决议** | prompt 仅写方向 + 目标 + 验收, CC 实测 path/SQL/command | memory #19/#20 prompt 设计铁律 |

### §L1.4 必沿用铁律子集 (V3 实施期最相关)

详见 IRONLAWS.md. 本 V3 实施期最频繁触发铁律:

- **铁律 1** (不靠猜测做技术判断) — V3 sprint 起手 SOP 起点
- **铁律 9** (资源密集任务必经资源仲裁) — Celery / Beat / 重数据任务 OOM 防御
- **铁律 11** (IC 入库) — V3 §3 / §5 LLM 路由 cost 沉淀
- **铁律 17** (DataPipeline) — V3 §3 / §10 数据入库 11 张新表
- **铁律 25** (代码变更前必读当前代码) — sub-PR 起手 fresh read
- **铁律 36** (代码变更前必核 precondition) — 依赖/锚点/数据三项核
- **铁律 37** (Session 关闭前必写 handoff) — 自造 `handoff-sessionend` hook
- **铁律 42** (PR 分级审查) — reviewer agent + AI self-merge
- **铁律 44 (X9)** (Beat schedule 注释 ≠ 停服, 必显式 restart) — V3 §12.4 Celery Beat 6 schedule 实施时
- **铁律 45** (4 doc fresh read SOP enforcement) — 自造 `fresh-read-sessionstart` hook
- **X10** (AI 自动驾驶 detection — 末尾不写 forward-progress offer) — sub-PR 闭后 0 forward-progress offer

---

## §L5 anti-hallucination guard (plugin 不覆盖, 本 layer 必留)

### §L5.1 cite source 锁定 SOP

任 cite 8 doc + V3 §X.Y + ADR # + LL # + sprint state + 任一具体 number / path / 编号 → 4 元素 cite (沿用 SESSION_PROTOCOL §3.1):

| 元素 | 体例 |
|---|---|
| (a) doc + line# + section | `[IRONLAWS.md:35](IRONLAWS.md#L35) "T1 强制 (共 31 条)"` |
| (b) fresh verify timestamp | "起手 fresh verify ✅" / "起手 git log -1 真测" |
| (c) 真值 vs prompt cite 漂移 | "prompt cite 'A' / fresh verify 真值 'B'" |
| (d) 真值修正 scope | "起点 X / patch = Y / 编号 next = Z" |

→ 自造 `quantmind-v3-cite-source-lock` skill (step 3) 强制 + 现 `verify_completion.py` 扩展 (合并 cite-source-poststop, 沿用 §L6.2 line 278 决议) reject 反 silent

### §L5.2 5 类漂移 detect (沿用 SESSION_PROTOCOL §3.3)

任 sub-PR 起手 + sediment 前必 detect 5 类漂移:

| 类型 | 体例 |
|---|---|
| 数字漂移 | e.g. "T1=8 vs 起点 T1=31" |
| 编号漂移 | e.g. "LL-120 vs 起点 LL next free = LL-X" |
| 存在漂移 | e.g. "已存在拆分 vs 真值 0 存在" |
| mtime 漂移 | e.g. "4 doc 起手 mtime vs 真值 0/4 起手" |
| cross-reference 漂移 | e.g. "doc A cite doc B 'Y' vs 真值 0 cite" |

→ 自造 `cite-drift-stop-pretool` hook (step 4) 强制 STOP + 反问

### §L5.3 Phase 0 active discovery enforcement (沿用 LL-098 X10)

每 sub-PR 起手 Phase 0 必产 finding ≥1, 三类 STOP 触发:

- **"和我假设不同"**: 立即 surface (e.g. LL-115 实证 — "capacity 1/4 → 4/4 working" 真值 = 6 backend file 100% docstring/comment cleanup, 0 production execution path)
- **"prompt 没让做但应该做"**: 列扩展候选, 不 silent 加
- **"prompt 让做但顺序错 / 有更好做法"**: 先 STOP + 反问

→ 自造 `quantmind-active-discovery` skill (step 3) 强制 + mattpocock `grill-me` skill 作为 user-CC alignment 工具

### §L5.4 静态 grep ≠ 真测 verify (沿用 anti-pattern v4.0)

verify 必 run command + output cite, 不 grep / cat / static 推断:

| 层 | 方法 |
|---|---|
| design 层审视 | 静态分析 OK |
| enforcement 层 verify | 必 真测 (cli / SQL / HTTP / process spawn / xtquant API) |

实证 (沿用 sprint period audit Phase 1-10 揭露): broker.connect()=-1 / schtask 17h 0 runs / 4 abort logs 根因, 静态分析全部 miss, 真测才暴露.

### §L5.5 跨 system claim source 锁定 (沿用 LL-103 SOP-4 + LL-104)

user "跟 Claude 说过 X" / "Claude.ai 决议 Y" / "memory cite Z" 等跨 system claim:

- CC 必明示 source 锁定 (memory cite / DB row / git log / xtquant API / file grep / cross-source cross-verify ≥2)
- 不信 user 单 cite, 不信 prompt 单 cite, 不信 memory 单 cite
- 沿用 LL-103 Claude.ai vs CC 分离 architecture finding (两 system 分离, conversation 不 cross-sync)

→ 进 自造 `quantmind-cite-source-lock` skill (step 3) scope, 扩 SOP-4

---

## §L6 skill + agent + hook 协调 (索引)

### §L6.1 plugin 选片决议 (audit reality grounding, 详见 invocation map §1)

audit row 22 真值: 用户级 `~/.claude/settings.json` `enabledPlugins` 含 mattpocock-skills + superpowers + ECC + OMC 全 enabled. 项目级 `.claude/external-skills/mattpocock-skills/` clone 真测.

| Plugin | 装载状态 | 选 | 不选 |
|---|---|---|---|
| **OMC v4.9.1 (oh-my-claudecode)** | ✅ 用户级 enabled (audit row 26) + 项目级 settings.json `enabledPlugins: oh-my-claudecode@omc=true` | **全沿用**: 16 agent (explore / analyst / planner / architect / debugger / executor / verifier / tracer / security-reviewer / code-reviewer / test-engineer / designer / writer / qa-tester / scientist / document-specialist) + 10 tier-0 workflows (autopilot / ultrawork / ralph / team / ralplan / deep-interview / ai-slop-cleaner / TDD mode / deepsearch / ultrathink) + omc-reference skill (V3 全程必 reference) | 0 排除 |
| **superpowers** | ✅ 用户级 enabled (audit row 39 反 v0.1 §L6.1 cite "0 装" 错; OMC tier-0 vs superpowers scope 重叠 partial 互补 — audit §5.1) | brainstorming / writing-plans / subagent-driven-development / systematic-debugging / TDD / verification-before-completion / requesting-code-review / receiving-code-review / finishing-a-development-branch / using-git-worktrees (留 auto-trigger 不强制 V3 串行 sprint chain) | 0 排除 |
| **mattpocock** | ✅ 项目级 clone (`.claude/external-skills/mattpocock-skills/` audit row 12-13: 22 SKILL.md, plugin.json 12 register: engineering 9 + productivity 3) | grill-me (`productivity/`, plugin.json line 14) / git-guardrails-claude-code (`misc/`, plugin.json 0 register 但 manual reference, sediment 入现 `block_dangerous_git.py`) / zoom-out (`engineering/`) / write-a-skill (`productivity/`) / caveman (`productivity/`) / **setup-matt-pocock-skills** (`engineering/`, plugin.json line 8, V3 sprint 起手 verify 配合) | **~~design-an-interface~~** ❌ (`deprecated/`, plugin.json 0 register, audit §6 真值 — v0.1 cite 必移除) / diagnose / tdd / to-prd / request-refactor-plan / improve-codebase-architecture / qa-session / 其余 |
| **ECC (everything-claude-code)** | ✅ 用户级 enabled (audit row 11) + 项目级 settings.json line 49+76 wire `continuous-learning-v2/hooks/observe.sh` PreToolUse + PostToolUse | hook 事件框架 (PreToolUse/PostToolUse/Stop/SessionStart/SessionEnd/PreCompact 6 类型) / Strategic compaction skill / `/harness-audit` `/quality-gate` `/loop-status` 命令 / AgentShield (限 .claude/ 配置 secrets/permission 扫) / continuous-learning-v2 hook (已 wire) | Memory persistence hooks (跟现 handoff_template + memory project_sprint_state.md 二选一, 沿用现; relevant ECC observe.sh project-scoped 已 wire 不冲突) / 182 skill 批量 / 48 agent 批量 / 68 命令大部分 |

**不装** `bdarbaz/claude-stack-plugin` (合并版): 命名空间冲突 + 丢失 superpowers 工作流强制性.

### §L6.2 自造 13 skill / 8 hook / 7 subagent 总览 (audit reality grounding, 详见 invocation map §3)

audit §7 真值决议: 总数沿用 v0.1 (13 / 8 / 7), 但**实施分类分** "全新 vs 现有扩展 vs OMC borrow", 反 v0.1 默认 sediment 倾向 (沿用 ADR-022 反 abstraction premature).

**自造 13 skill** (全 `quantmind-v3-` 中缀, 区分现 6 quantmind- 因子研究 skill + audit row 24-25 真测 0 命名冲突):

| skill | scope |
|---|---|
| `quantmind-v3-fresh-read-sop` | sub-PR / step / cross-session resume 起手 8 doc fresh read (跟现 session_context_inject.py v2 hook 互补 — skill 是 CC 主动 invoke, hook 是 SessionStart auto trigger) |
| `quantmind-v3-cite-source-lock` | 任 数字/编号/路径 cite 4 元素强制 |
| `quantmind-v3-active-discovery` | Phase 0 finding ≥1 + 3 类 STOP 触发 |
| `quantmind-v3-redline-verify` | 任 broker / .env / yaml / DB row mutation 5/5 红线 verify |
| `quantmind-v3-anti-pattern-guard` | sub-PR 起手 + sediment 前 v1-v5 anti-pattern check |
| `quantmind-v3-sprint-closure-gate` | sprint 闭前 stage gate criteria 机器可验证 |
| `quantmind-v3-doc-sediment-auto` | sub-PR 闭后 LL/ADR/STATUS_REPORT/handoff/ROADMAP 同步 |
| `quantmind-v3-banned-words` | reply + prompt 出前 真+词 / sustained 中文滥用 check |
| `quantmind-v3-prompt-design-laws` | Claude.ai 写 prompt 给 CC 时 0 数字/path/command 守门 |
| `quantmind-v3-sprint-replan` | sprint 实际超 baseline 1.5x → push user replan |
| `quantmind-v3-prompt-eval-iteration` | prompts/risk/*.yaml prompt eval methodology + V4-Flash → V4-Pro upgrade 决议 |
| `quantmind-v3-llm-cost-monitor` | 月度 LiteLLM cost audit + 上限 + warn enforce |
| `quantmind-v3-pt-cutover-gate` | PT 重启 cutover gate checklist (Gate E) |

**自造 8 hook = 4 全新 + 4 现有扩展** (audit §4 + §7 决议, 反 v0.1 8 全新 silent 创建倾向):

| hook | 类型 | 实施分类 |
|---|---|---|
| **redline-pretool-block** | PreToolUse | ✅ **全新** (`.claude/hooks/redline_pretool_block.py`, 跟现 `protect_critical_files.py` 互补 — protect 偏 file pattern, redline 偏 5/5 红线 query) |
| **cite-drift-stop-pretool** | PreToolUse | ✅ **全新** (`.claude/hooks/cite_drift_stop_pretool.py`) |
| **sediment-poststop** | Stop | ✅ **全新** (`.claude/hooks/sediment_poststop.py`, 跟现 `verify_completion.py` 互补 — verify 偏 doc 同步提醒, sediment 偏 LL/ADR/STATUS_REPORT auto append) |
| **handoff-sessionend** | SessionEnd | ✅ **全新** (`.claude/hooks/handoff_sessionend.py`, audit §1 row 18 真值 SessionEnd 类型现 0 wire — gap 必补) |
| ~~fresh-read-sessionstart~~ | (合并到现 `session_context_inject.py`) | 🟡 **现有扩展** (扩 V3 doc + Constitution + invocation map + REGISTRY 4 doc 加入 inject scope) |
| ~~cite-source-poststop~~ | (合并到现 `verify_completion.py`) | 🟡 **现有扩展** (扩 4 元素 cite source 锁定 enforce) |
| ~~banned-words-poststop~~ | (合并到现 `verify_completion.py`) | 🟡 **现有扩展** (扩 真+词 / sustained 中文滥用 reject + auto-rewrite) |
| ~~anti-prompt-design-violation-pretool~~ | (合并到现 `iron_law_enforce.py`) | 🟡 **现有扩展** (扩 V3 invariant: V3 §11 12 模块 fail-open / 真账户红线 / Beat schedule 注释 ≠ 停服 / prompt 设计 0 数字 path command) |

→ 4 全新 hook + 4 现有 hook 扩展, 沿用 ADR-022 反 silent overwrite.

**候选追加** (audit §4 cite): `protect_critical_files.py` 扩 V3 prompts/risk/*.yaml protect — 实施时按 sub-PR 决议是否纳入扩展清单.

**自造 7 subagent = 4 全新 + 3 借 OMC extend** (audit §5.2 § §7 决议, 沿用 (β) — user 5-08 决议; 反 .claude/CLAUDE.md "11 agent 全停用 2026-04-15" 反向 — 4 全新是机制 agent 非角色扮演):

| subagent | 实施分类 |
|---|---|
| `quantmind-cite-source-verifier` | ✅ **全新** charter file (`.claude/agents/quantmind-cite-source-verifier.md`, 0 OMC equivalent — 反 hallucination 专用 cross-source verify) |
| `quantmind-redline-guardian` | ✅ **全新** charter file (0 OMC equivalent — 真账户 / .env / DB row 5/5 红线) |
| `quantmind-risk-domain-expert` | ✅ **全新** charter file (0 OMC equivalent — V3 §13/14/15 风控特有领域审视) |
| `quantmind-prompt-iteration-evaluator` | ✅ **全新** charter file (0 OMC equivalent — V4-Flash vs V4-Pro 路由决议) |
| ~~sprint-orchestrator~~ | 🟡 **借 OMC** `planner` extend + 写 `quantmind-v3-sprint-orchestrator.md` charter (V3 sprint chain 跟踪 + sprint-by-sprint 触发 invocation) |
| ~~sprint-closure-gate-evaluator~~ | 🟡 **借 OMC** `verifier` extend + 写 `quantmind-v3-sprint-closure-gate-evaluator.md` charter (V3 §10/15 closure criteria 机器可验证清单) |
| ~~tier-a-mvp-gate-evaluator~~ | 🟡 **借 OMC** `verifier` extend + 写 `quantmind-v3-tier-a-mvp-gate-evaluator.md` charter (V3 S10 paper-mode 5d 验收专用) |

### §L6.3 自造 vs plugin 优先级

- **同名冲突**: quantmind 自造 > plugin (沿用 quantmind project governance 优先)
- **skill auto-trigger 不可控时**: invocation map 显式 invoke 强制
- **caveman / zoom-out 等 token 优化 skill**: 限 scope 用, 反 cite source / sediment 段
- **sprint-by-sprint TDD override**: integration-heavy sprint (S5/S8 等) 走 integration-first 而非 superpowers TDD-first
- **superpowers two-stage review**: stage 1 = spec compliance (新, V3 §12.3 验收) / stage 2 = code quality (沿用现 LL-067 reviewer agent + AI self-merge), 不重复跑 reviewer

### §L6.4 Celery Beat / Servy / Windows Task Scheduler ops 不进 plugin scope

走 `docs/runbook/cc_automation/` 现有 runbook (reset_setx / Servy 全重启 / DB 命名空间修复 / etc), plugin 不参与. 这是 quantmind 项目 Windows 11 + 32GB 单机环境独有 ops 层.

---

## §L8 user 介入 3 类 enforcement (memory #24)

### §L8.1 必 user 介入 (CC 不可自决)

| 类型 | 触发条件 | hook 强制 |
|---|---|---|
| **(a) scope 关键决议** (option A/B/C 类) | e.g. S4 决议 (skip / minimal / 完整) / Tier B 起手时机 / V3 §11.4 backtest_adapter 前置归属 / cutover 时间窗口 / PT 重启时机 | 0 hook (CC 主动 surface push) |
| **(b) 真生产红线触发** | LIVE_TRADING_DISABLED / EXECUTION_MODE / DB row mutation / 真生产 .env / yaml 改动 / default flag 改动 / 启 PT 信号链 / broker call | `redline-pretool-block` hook 阻断 + push user |
| **(c) sprint 收口决议** | sprint 闭前 closure gate 不通过 / sprint 实际超 baseline 1.5x / 治理债 累积超阈值 / stage transition gate | `quantmind-sprint-closure-gate` skill + `tier-a-mvp-gate-evaluator` subagent surface |

### §L8.2 不必 user 介入 (CC 自决, 沿用 sprint period LL-059 9 步闭环 user ≤2 接触/PR)

- audit / docs / ADR / GLOSSARY / 纯 read-only doc 类 sediment
- sub-PR 内 task 决议 (CC 实测决议 path / file / function / SQL / command)
- reviewer agent + AI self-merge (沿用 LL-100)
- LL append / cite source 修复 / 5 类漂移 sediment (沿用 ADR-022)
- skill / hook / subagent invocation 决议 (沿用 invocation map)
- 治理债 closure 类 sub-PR (e.g. governance / 4 doc cleanup / scope correction)

### §L8.3 user 介入 push 频率 (修正 12 决议)

- **(B) 每 stage 收口 push** (V3 实施 7 stage = 大约每 2-4 周 1 次 stage 收口)
- 加 scope 决议 / 红线触发 临时 push (沿用 §L8.1 (a) (b))
- **每 sprint 闭后 STATUS_REPORT 进 memory `project_sprint_state.md`** (CC 自决, 不必单 sprint 收口 push user)

### §L8.4 user 介入 push template (沿用 6 块 prompt 反向)

CC push user 时含 6 块反向结构:

- (1) **背景** (sprint / stage / sub-PR 当前真值 cite source)
- (2) **决议项** (option A / B / C 列举 + 我倾向 + 论据)
- (3) **主动发现** (我识别到的盲区 / 跨域影响 / 未提决议项)
- (4) **挑战假设** (上次决议矛盾 cite + 当前决议是否需修正前决议)
- (5) **边界 + 风险** (真账户 / CC 误执行 / STOP 够吗 / 长期影响)
- (6) **输出含 finding** (sub-PR / sprint / stage closure status + next prompt 草稿 + STATUS_REPORT)

---

## §L10 V3 closure 终态 criteria (机器可验证)

每 gate 详细 criteria 由对应 skill / subagent 跑机器可验证清单. 任一不通过 → STOP + push user (sprint 收口决议).

### §L10.1 Gate A: Tier A closed

verifier: `tier-a-mvp-gate-evaluator` subagent

**Checklist** (CC 实测每项):

- [ ] V3 §12.1 Sprint S1-S11 全 closed (CC 实测 git log + PR # cite + ADR REGISTRY committed verify)
- [ ] paper-mode 5d 验收 ✅ (V3 §15.4 标准: P0 alert 误报率 / L1 detection latency P99 / L4 STAGED 流程闭环 / 元监控 0 P0 元告警, 数值阈值 sprint 起手时 CC 实测决议)
- [ ] 元监控 `risk_metrics_daily` 全 KPI 14 day 持续 sediment (CC 实测 SQL row count + 日期连续性 verify)
- [ ] ADR-019 (V3 vision) + ADR-020 (Claude 边界 + LiteLLM) + ADR-029 (L1 实时化) + Tier A 后续 ADR 全 committed (REGISTRY SSOT verify)
- [ ] V3 §11.1 12 模块全 production-ready (CC 实测 import + smoke test + module health check)
- [ ] LiteLLM 月成本累计 ≤ V3 §16.2 上限 (CC 实测 SQL llm_cost_daily aggregate)
- [ ] CI lint check_anthropic_imports.py 生效 + pre-push hook 集成 (CC 实测 hook log + lint output)
- [ ] V3 §3.5 fail-open 设计实测 (任 1 News 源 fail / fundamental_context fail / 公告流 fail, alert 仍发, CC 实测 mock fail scenario)

### §L10.2 Gate B: T1.5 closed

verifier: `risk-domain-expert` subagent + `sprint-closure-gate-evaluator` subagent

**Checklist**:

- [ ] V3 §11.4 `RiskBacktestAdapter` 实现 + 0 broker / 0 alert / 0 INSERT 依赖 verify (CC 实测 import 验 + 静态 + 真测 mock backtest run)
- [ ] 12 年 counterfactual replay 跑通 (沿用 sim-to-real gap audit 体例, V3 §15.5)
- [ ] WF 5-fold 全正 STABLE (沿用 4-12 CORE3+dv_ttm 体例, OOS Sharpe / MDD / Overfit 阈值 sprint 起手时 CC 实测决议)
- [ ] T1.5 sediment ADR (新 ADR # CC sprint 起手时实测决议)
- [ ] sim-to-real gap finding (PR #210 体例) Tier A 实施期间 0 复发 (CC 实测 audit log)

### §L10.3 Gate C: Tier B closed

verifier: `risk-domain-expert` subagent

**Checklist**:

- [ ] V3 §12.2 Sprint S12-S15 全 closed
- [ ] L2 Bull/Bear regime production-active (Daily 3 次 cadence verify, V3 §20.1 #2)
- [ ] L2 RAG (BGE-M3 + pgvector) production-active + retrieval 命中率 ≥ baseline (V3 §20.1 #3)
- [ ] L5 RiskReflector 周/月/event-after cadence ≥1 完整 cycle (V3 §20.1 #4)
- [ ] 反思 lesson → risk_memory 自动入库 + 后置抽查 ≥1 round (V3 §20.1 #9 (c) hybrid)
- [ ] ADR-025 (RAG vector store 选型) + ADR-026 (Bull/Bear 2-Agent debate) + Tier B 后续 ADR 全 committed

### §L10.4 Gate D: 横切层 closed

verifier: `sprint-closure-gate-evaluator` subagent + `quantmind-pt-cutover-gate` skill

**Checklist**:

- [ ] V3 §13 元监控 `risk_metrics_daily` + alert on alert production-active
- [ ] V3 §14 失败模式 12 项 enforce ✅ (灾备演练 ≥1 round 沉淀 `docs/risk_reflections/disaster_drill/`)
- [ ] V3 §17.1 CI lint `check_anthropic_imports.py` 生效 + pre-push hook 集成 (沿用现 X10 + smoke pattern)
- [ ] `prompts/risk/*.yaml` prompt eval iteration ≥1 round (V4-Flash → V4-Pro upgrade 决议体例 sediment, ADR # CC 实测决议)
- [ ] LiteLLM 月成本 ≤ V3 §16.2 上限 ≥3 month 持续 ≤80% baseline + 月度 review cadence sediment (V3 §20.1 #6)

### §L10.5 Gate E: PT cutover gate ✅

verifier: `quantmind-pt-cutover-gate` skill

**5 prerequisite** (沿用 V3 §20.1 #1 + #5):

- [ ] paper-mode 5d 通过 (Gate A 部分)
- [ ] 元监控 0 P0 (Gate A 部分)
- [ ] Tier A ADR 全 sediment (Gate A 部分)
- [ ] 5 SLA 满足 (V3 §13.1 detection latency / News 6 源 / LiteLLM / DingTalk / STAGED 30min, CC 实测每项)
- [ ] 10 user 决议状态 verify (V3 §20.1 10 决议 closed PR #216 sediment, CC 实测 grep + cross-verify)

**user 显式 .env paper→live 授权**:

- LIVE_TRADING_DISABLED=true → false 解锁
- DINGTALK_ALERTS_ENABLED=false → true 解锁
- EXECUTION_MODE=paper → live 解锁
- L4_AUTO_MODE_ENABLED 是否启用 (沿用 V3 §17.2 双锁)

**0 自动 .env 改动** (沿用 ADR-022 反 anti-pattern). user 显式 push merge.

---

## maintenance + footer

### 修订机制 (沿用 ADR-022 集中机制)

- 新 V3 sprint sediment / 新 user 决议 / 新 V3 设计扩展 → 1 PR sediment + invocation map 同步 update + 自造 skill / hook / subagent 同步 update
- LL append-only (反 silent overwrite)
- ADR # registry SSOT (LL-105 SOP-6) sub-PR 起手前 fresh verify
- 8 doc fresh read SOP (本文件 §L1.1) 跟 SESSION_PROTOCOL §1.3 同步 update

### 版本 history

- **v0.1 (initial draft, 2026-05-08)**: §L0 / L1 / L5 / L6 / L8 / L10 六层 收 + plugin 选片 + 自造 13/8/7 + V3 closure 5 gate
- **v0.2 (post-audit reality grounding, 2026-05-08)**: 沿用 ADR-022 反 silent overwrite (v0.1 row 保留, version history append). 修订基于 [docs/audit/v3_orchestration/claude_dir_audit_report.md](audit/v3_orchestration/claude_dir_audit_report.md) (PR #270 sediment, 22 row 真值表 + 8 finding cross-verify drift 率 25%):
  - **§L0.3 step (3)** cite session_context_inject.py v2 (反 v0.1 cite "fresh-read-sessionstart hook" 0 存在 silent 创建)
  - **§L1.1** 8 doc 标 6 committed + 2 planned (audit §8 真值)
  - **§L6.1** 移除 mattpocock `design-an-interface` (audit §6 真值: deprecated/, plugin.json 0 register), 加候选 `setup-matt-pocock-skills`. superpowers 沿用 v0.1 选片 (audit row 39 真值: 用户级已 enabled, 反 v0.1 cite "0 装" 错). OMC v4.9.1 + ECC continuous-learning-v2 wire 真值 sediment (audit row 11/22/26)
  - **§L6.2** 13 skill 全 `quantmind-v3-` 中缀 (audit §7 命名 0 冲突). 8 hook = 4 全新 + 4 现有扩展 (audit §4 + §7 决议, 反 v0.1 8 全新 silent 创建). 7 subagent = 4 全新 charter file + 3 借 OMC extend (audit §5.2/§7 决议, 沿用 (β) — user 5-08 决议; 反向 .claude/CLAUDE.md "11 agent 全停用 4-15" 体例 — 4 全新是机制 agent 非角色扮演)

### footer

- **维护频率**: V3 sprint sediment 时 / sprint 收口决议时 / V3 横切层 sprint 化时 (1 PR sediment 沿用 LL-100)
- **SSOT**: 本文件 = V3 实施期 quantmind 项目 跨 session / 跨 sub-PR / 跨 stage 元规则集 唯一权威源
- **关联文件 6 件套**: 本 + invocation map + 13 skill + 8 hook + 7 subagent + 启动 prompt
- **关联铁律**: 1 / 9 / 11 / 17 / 25 / 36 / 37 / 42 / 44 (X9) / 45 / X10
- **关联 LL**: LL-098 (X10) / LL-100 / LL-101 / LL-103 / LL-104 / LL-105 / LL-106 / LL-115 + 后续 V3 实施期 LL
- **关联 ADR**: ADR-019 / ADR-020 / ADR-021 / ADR-022 / ADR-027 / ADR-028 / ADR-037 + 后续 V3 实施期 ADR
- **现 last update**: V3 实施期 sediment

---

**文档结束**.
