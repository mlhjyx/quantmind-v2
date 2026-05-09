# QuantMind V3 Skill / Hook / Agent Invocation Map (skeleton)

> **本文件 = V3 实施期 skill / hook / subagent / OMC tier-0 / mattpocock / superpowers / ECC 跨 sprint invocation 索引**.
>
> **scope**: invocation 调度索引 + sprint-by-sprint 触发表 + transition gate + 横切层归属 + 冲突 resolution rules. **0 含 spec body** (skill / hook / subagent 详细 spec 走 step 3-5 各自 file sediment).
>
> **关联**: [V3_IMPLEMENTATION_CONSTITUTION.md v0.3](V3_IMPLEMENTATION_CONSTITUTION.md) (本文件 = Constitution §L6 索引展开, post-V3 governance batch closure sub-PR 3a/3b/3c chunked cumulative cite refresh) + [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §12 sprint 拆分 + [docs/audit/v3_orchestration/claude_dir_audit_report.md](audit/v3_orchestration/claude_dir_audit_report.md) (PR #270 真值 grounding).
>
> **本文件版本**: v0.7 (post-V3 §S2.5 implementation 闭环 + chunked 2 sub-PR split closure + plan-then-execute 体例 5th 实证, 2026-05-09, V3 governance batch closure sub-PR 11b — V3 §S2.5 implementation + ADR-050 + LL-140 sediment, 沿用 ADR-022 反 silent overwrite — v0.1-v0.6 row 保留 + version history append)
> **本文件 scope outside**: ❌ 13 skill SKILL.md 详细 spec (件 3 ✅ closed, PR #272-#275 + #281 bonus) / ❌ 8 hook .py 实施 (件 4 ✅ closed, post-PR #284, 13 hook cumulative — 4 全新 PR #276/#280/#281/#282 + 4 现有扩展 PR #283/#284 + 5 现有 sustained) / ❌ 7 subagent charter (件 5 ✅ closed, PR #277-#279) / ❌ V3 启动 prompt (件 6 ✅ closed, PR #285 v0.1; sustained optional sub-PR 7 v0.2 修订 trigger)
>
> **v0.2 cumulative cite banner** (V3 governance batch closure sub-PR 4 sediment, 2026-05-09; sustained sub-PR 1+2+3a+3b+3c governance pattern parallel体例 + LL-127 §0.3 cumulative cite SSOT 锚点 baseline 真值落地 sustainability sediment cumulative scope 三段累积扩 sub-PR 4 cumulative scope sediment): post-V3 6 件套 100% closure cumulative cite refresh — 件 1 ✅ audit (PR #270, 22 row 真值表) + 件 2 ✅ Constitution v0.3 chunked closure (sub-PR 3a §L0.3+§L1.1 PR #288 + sub-PR 3b §L6.1+§L6.2 PR #289 + sub-PR 3c §L10 + version history v0.3 entry PR #290) + 件 3 ✅ 13 skill (PR #272-#275 + #281 bonus) + 件 4 ✅ 13 hook cumulative (4+4+5, PR #276/#280/#281/#282/#283/#284) + 件 5 ✅ 7 charter (PR #277-#279) + 件 6 ✅ V3_LAUNCH_PROMPT v0.1 (PR #285). V3 governance batch closure cumulative pattern: sub-PR 1 LL-cumulative-batch (PR #286, 8 LL promoted as LL-116/117/127/132/133/134/135/136) + sub-PR 2 ADR-cumulative-batch (PR #287, ADR-044/045/046 直 promote 进 REGISTRY.md) + sub-PR 3 chunked Constitution v0.3 修订 完整闭环 ✅ (3a/3b/3c) + sub-PR 4 本 PR (skeleton v0.2 修订 + Constitution v0.3 §version history typo `架→角` fix). 沿用 LL-098 X10 反 forward-progress default + LL-100 chunked SOP + LL-105 SOP-6 ADR # registry SSOT cross-verify + LL-116 fresh re-read enforce 9 case 实证累积反向 (2 reverse + 7 verified positive PR #281/#282 + PR #283/#284/#285/#287/#288/#289/#290).

---

## §0 元信息 + 反 anti-pattern 验证

### §0.1 SSOT 锚点

| 类别 | 锚点 |
|---|---|
| Constitution v0.2 | [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) |
| V3 设计 sprint 拆分 | V3 §12.1 (Tier A S1-S11) + §12.2 (Tier B S12-S15) |
| audit reality grounding | docs/audit/v3_orchestration/claude_dir_audit_report.md (PR #270, 22 row 真值表) |
| 现 .claude/ 真值 | audit row 1-22 (settings.json wire / 9 hook .py / 7 skill / OMC v4.9.1 / ECC + mattpocock 用户级 enabled) |
| ADR REGISTRY | docs/adr/REGISTRY.md (ADR # SSOT, LL-105 SOP-6) |

### §0.2 反 anti-pattern 验证

- ✅ 不创建新 IRONLAWS audit log entry
- ✅ 0 凭空 enumerate 新决议
- ✅ 0 silent overwrite 现 9 hook + 7 skill + settings.json wire (沿用 ADR-022)
- ✅ 0 末尾 forward-progress offer (LL-098 X10)
- ✅ 0 "真+词" 禁词 (memory #25 HARD BLOCK)
- ✅ 0 具体 path / file / function / SQL / command 由 Claude.ai 写 (沿用 memory #19/#20 — CC sprint 起手时实测决议)

---

## §1 Plugin curation 决议表 (Constitution §L6.1 展开)

### §1.1 OMC v4.9.1 — main orchestration layer

audit row 26 真值: cache 4.9.1 + 4.9.3 双版本, current 4.9.1, available v4.13.6. 不强制 upgrade. 

**OMC 16 agent** (audit §5.2 cite, prefix `oh-my-claudecode:`):

| Agent | model | V3 invocation 触发 |
|---|---|---|
| `explore` | haiku | V3 sprint 起手 codebase search + dependency mapping |
| `analyst` | opus | sprint scope 决议时 requirements 梳理 |
| `planner` | opus | sprint plan 拆 sub-PR (跟 superpowers writing-plans 互补) + 自造 sprint-orchestrator 借此 extend |
| `architect` | opus | V3 §11.1 12 模块 interface 决议 (替代 mattpocock design-an-interface deprecated) |
| `debugger` | sonnet | V3 §14 失败模式 12 项触发 root-cause 时 |
| `executor` | sonnet | sub-PR implementation 主体 |
| `verifier` | sonnet | V3 sprint closure gate / 自造 sprint-closure-gate-evaluator + tier-a-mvp-gate-evaluator 借此 extend |
| `tracer` | sonnet | V3 §13 元监控 trace 梳理 |
| `security-reviewer` | sonnet | V3 §17.4 数据隐私 + 安全 review |
| `code-reviewer` | opus | sub-PR code review (跟 LL-067 reviewer agent 沿用) |
| `test-engineer` | sonnet | V3 §15 测试金字塔 sprint 起手 + S15.4 paper-mode |
| `designer` | sonnet | V3 §13.4 监控 dashboard frontend |
| `writer` | haiku | V3 sprint sediment doc / ADR / LL append |
| `qa-tester` | sonnet | V3 S10 paper-mode 5d dry-run QA |
| `scientist` | sonnet | V3 §15.6 合成场景 methodology |
| `document-specialist` | sonnet | V3 §18.3 新文档 sediment (Constitution / invocation map / runbook 等) |

**OMC 10 tier-0 workflows** (audit §5.1 cite, trigger keyword):

| Workflow | trigger | V3 invocation |
|---|---|---|
| `autopilot` | "autopilot" | V3 sprint full execution (S1-S15) — 跟 superpowers `executing-plans` 互补 (autopilot 偏 autonomous, superpowers 强制 review checkpoint) |
| `ultrawork` | "ulw" | V3 parallel high-throughput (sprint 内 multi sub-task, e.g. S2 News 6 源并行 ingest) |
| `ralph` | "ralph" | V3 long-running self-loop (debug / verify until done — V3 §14 失败模式 灾备演练 ≥1 round 时) |
| `team` | `/team` | V3 multi-agent coordinate (sprint period sediment 体例 — 自造 sprint-orchestrator 借 OMC `team` extend) |
| `ralplan` | "ralplan" | V3 planning consensus (multi-model — Claude + Codex + Gemini 三模型决议; sprint scope 决议时) |
| `deep-interview` | "deep interview" | V3 sprint scope alignment (sprint 起手前 user-CC alignment, 跟 mattpocock `grill-me` 互补 — deep-interview 严, grill-me 轻) |
| `ai-slop-cleaner` | "deslop" / "anti-slop" | V3 dead code cleanup (sprint period 沿用 5 SOP cluster 体例) |
| TDD mode | "tdd" | V3 §15 测试金字塔 + sprint 起手 TDD-first (但 integration-heavy sprint S5/S8 走 integration-first override, 详 §6) |
| deepsearch | "deepsearch" | V3 codebase search (V3 §11 12 模块 import 关联 grep) |
| ultrathink | "ultrathink" | V3 deep reasoning (本 sub-PR 触发 / 复杂 transition gate 决议) |

### §1.2 superpowers — 工作流方法论 (audit row 39 真值: 用户级已 enabled)

10 选片 (Constitution §L6.1 沿用), 跟 OMC tier-0 互补:

| Skill | V3 invocation 触发 |
|---|---|
| `brainstorming` | sprint scope 决议起手 — Socratic refinement (跟 OMC `analyst` + `deep-interview` 互补) |
| `writing-plans` | sprint plan 拆 sub-PR — bite-sized tasks (跟 OMC `planner` + `ralplan` 互补) |
| `subagent-driven-development` | sub-PR 内一 task 一 subagent + two-stage review (stage 1 = spec compliance / stage 2 = code quality, sed via OMC `code-reviewer` + 沿用 LL-067 reviewer agent + AI self-merge) |
| `systematic-debugging` | V3 §14 失败模式 12 项 触发 root-cause (4-phase, 跟 OMC `debugger` 互补) |
| `test-driven-development` | TDD-first sprint (跟 OMC TDD mode 沿用; integration-heavy sprint override 详 §6) |
| `verification-before-completion` | sub-PR 闭前 evidence verify (跟现 verify_completion.py hook 沿用) |
| `requesting-code-review` | sub-PR 闭前自身 review checklist |
| `receiving-code-review` | reviewer agent feedback 处理 (沿用 PR #270 体例) |
| `using-git-worktrees` | 留 superpowers auto-trigger 不强制 (V3 串行 sprint chain S1→S15, worktree 主用于 parallel dev — V3 不需) |
| `finishing-a-development-branch` | sub-PR closure 决议 (merge / PR / keep / discard) |

### §1.3 mattpocock — 协作纪律 (audit row 12-13 真值)

audit row 12-13: 22 SKILL.md, plugin.json 12 register (engineering 9 + productivity 3, misc/ 0 register manual reference, deprecated/ 4 NOT use). 6 选片:

| Skill | path | active 状态 (audit §6) | V3 invocation 触发 |
|---|---|---|---|
| `grill-me` | productivity/ | ✅ plugin registered (line 14) | sprint scope alignment (跟 OMC `deep-interview` 互补 — grill-me 轻量, deep-interview 严) |
| `git-guardrails-claude-code` | misc/ | ⚠️ active 但 plugin 0 register (manual reference) | **patterns 已 sediment 入现 `block_dangerous_git.py`** (5-07 sub-PR 8a-followup-pre 体例). V3 期 reference patterns 来源, 不直 invoke skill |
| `zoom-out` | engineering/ | ✅ plugin registered (line 12) | sub-PR Phase 0 fresh read 遇 unfamiliar 模块时主动后撤大图 |
| `write-a-skill` | productivity/ | ✅ plugin registered (line 16) | step 3 自造 13 quantmind-v3- skill SKILL.md sediment 时 |
| `caveman` | productivity/ | ✅ plugin registered (line 13) | 限 scope 用 — 仅子任务 chat-only 段, 反 cite source / sediment 段 (会丢 cite source 4 元素) |
| `setup-matt-pocock-skills` | engineering/ | ✅ plugin registered (line 8) | sprint 起手 verify mattpocock skills 触发条件 |
| **~~design-an-interface~~** | deprecated/ | ❌ NOT use (audit §6 真值) | ❌ 移除 (v0.1 cite 错). V3 §11.1 12 模块 interface 决议 → 走 OMC `architect` agent |

### §1.4 ECC (everything-claude-code) — harness 性能层

audit row 11/22 真值: 用户级 marketplace + 项目级 settings.json line 49+76 wire `continuous-learning-v2/hooks/observe.sh`.

| 组件 | 用 / 不用 |
|---|---|
| Hook 事件框架 (PreToolUse/PostToolUse/Stop/SessionStart/SessionEnd/PreCompact 6 类型) | ✅ 用框架 (自造 hook 走此体例) |
| Memory persistence hooks (auto save/load to ~/.claude/) | ❌ 关闭 (跟现 handoff_template + memory project_sprint_state.md 二选一, 沿用现) |
| Strategic compaction skill | ✅ 用 (PreCompact 触发, 长 session 不丢 sprint state) |
| `/harness-audit` `/quality-gate` `/loop-status` 命令 | ✅ 用 (V3 sprint 运营级巡检) |
| `continuous-learning-v2/hooks/observe.sh` (PreTool + PostTool wire) | ✅ 沿用现 wire (0 改) — entropy 数据收集, project-scoped |
| AgentShield (npx) | ✅ 用 (限 .claude/ 配置 secrets/permission 扫) |
| 182 skill 批量 / 48 agent 批量 / 68 命令大部分 | ❌ 不批量装 (太杂 + namespace 冲突) |

---

## §2 Sprint-by-sprint invocation 表 (V3 §12.1 + §12.2)

每 sprint 触发的 plugin / 现 hook / 自造组件清单. **TDD-first vs integration-first override** 标记 (详 §6).

### §2.1 Tier A (S1-S11)

| Sprint | scope | 起手 plugin invoke | 主体 plugin invoke | 横切层归属 (§5) | 自造组件触发 | TDD/integration |
|---|---|---|---|---|---|---|
| **S1** LiteLLM 接入 ✅ substantially closed by V2 prior work (post sub-PR 9 verify, PR #219-#226 + #246/247/253/255 cumulative ~5630 行) | V3 §5.5 LLM 路由 | `brainstorming` + OMC `analyst` | OMC `executor` + `subagent-driven-development` + TDD mode | — | `quantmind-v3-redline-verify` + redline-pretool-block hook | TDD-first (post sub-PR 9: verify-only + cite reconcile + ADR-047/LL-137 sediment hybrid 已 done) |
| **S2** L0.1 News 6 源 ✅ substantially closed by V2 prior work (post sub-PR 10 verify, PR #234-#257 cumulative ~22 files / ~3000-4000 行 / 11 test files / 291 pytest pass / ADR-033 + ADR-043 committed; 4/4 RSSHub capacity expansion deferred to S5 per ADR-048) | V3 §3.1 | `brainstorming` (capacity expansion 决议) + OMC `architect` | `subagent-driven-development` + `ultrawork` (并行 ingest) | — | `quantmind-v3-active-discovery` + `quantmind-v3-cite-source-lock` | integration-first (post sub-PR 10: verify-only + cite reconcile + ADR-048/LL-138 sediment hybrid 已 done) |
| **S2.5** L0.4 AnnouncementProcessor 公告流 ingest + parser ⭐ ✅ COMPLETE (sub-PR 11a + 11b cumulative, ADR-049 + ADR-050 sediment, 31/31 tests PASSED) — **架构 sediment ✅ DONE (sub-PR 11a, ADR-049) + DDL sediment ✅ DONE (sub-PR 11a, announcement_raw NEW) + implementation ✅ DONE (sub-PR 11b, ADR-050: AnnouncementProcessor service + Celery task + API endpoint POST /api/news/ingest_announcement + Beat schedule announcement-ingest-trading-hours + 31/31 tests PASSED 6.61s)** | V3 §11.1 row 5 + V3 §3 整体 scope | `brainstorming` + OMC `architect` | `subagent-driven-development` + `ultrawork` (parallel RSSHub route_path arg per Decision 3 ADR-049) | — | `quantmind-v3-active-discovery` + `quantmind-v3-cite-source-lock` | integration-first (post sub-PR 11a + 11b: architecture + DDL + implementation + tests 全 done; post-merge ops 待: announcement_raw migration apply + Servy restart QuantMind-CeleryBeat 铁律 44 X9) |
| **S3** L0.2 NewsClassifier ✅ | V3 §3.2 | `brainstorming` (prompt 设计) + OMC `analyst` | OMC `executor` + `quantmind-v3-prompt-eval-iteration` | 横切 §5.4 prompts/risk eval 起点 | `quantmind-v3-llm-cost-monitor` 起点 | integration-first |
| **S4** L0.3 fundamental_context 8 维 ⏳ 决议待 | V3 §3.3 | **user 决议** (skip / minimal / 完整 — scope 决议 push) + `grill-me` | OMC `executor` (按决议 scope) | — | `quantmind-v3-active-discovery` | per-决议 |
| **S5** L1 实时化 + 8 RealtimeRiskRule ⭐⭐⭐ | V3 §4 (4-29 痛点 fix 核心) | OMC `architect` (xtquant subscribe_quote 集成) + `deep-interview` (设计决议) | `subagent-driven-development` + OMC `executor` + `qa-tester` (paper smoke) | 横切 §5.5 backtest_adapter 接口前置 (V3 §11.4) | `quantmind-v3-redline-verify` + `quantmind-redline-guardian` subagent | **integration-first** (override TDD-first, integration-heavy) |
| **S6** L0 告警实时化 (3 级 + push cadence) | V3 §4.5 | `brainstorming` | `subagent-driven-development` + OMC `executor` | — | `quantmind-v3-anti-pattern-guard` | TDD-first |
| **S7** L3 dynamic threshold + L1 集成 | V3 §6 | OMC `analyst` + `architect` | OMC `executor` + Stress 模拟 | — | `quantmind-v3-cite-source-lock` (阈值动态调整 cite source) | TDD-first |
| **S8** L4 STAGED 决策权 + DingTalk webhook ⭐⭐⭐ | V3 §7 (4-29 痛点 fix 核心) | OMC `architect` + `deep-interview` (反向决策权论据) + `grill-me` (user 介入 STAGED default 模式) | `subagent-driven-development` + OMC `executor` + `qa-tester` (STAGED smoke) | — | `quantmind-redline-guardian` subagent (broker_qmt sell 单红线) + `quantmind-v3-redline-verify` | **integration-first** (override TDD-first, integration-heavy) |
| **S9** L4 batched + trailing + Re-entry | V3 §7.2-§7.4 | OMC `architect` | OMC `executor` + `qa-tester` (历史回放) | — | — | TDD-first |
| **S10** paper-mode 5d dry-run + 触发率验证 | V3 §15.4 | OMC `qa-tester` + `verifier` + `quantmind-v3-pt-cutover-gate` skill | `ralph` (long-running 5d) + `verification-before-completion` | 横切 §5.6 5 SLA verify (V3 §13.1) | `quantmind-v3-tier-a-mvp-gate-evaluator` subagent | E2E (~不适 TDD-first) |
| **S11** Tier A ADR sediment + ROADMAP 更新 | V3 §11.1 ADR-019/020/029 | OMC `document-specialist` + `writer` | `quantmind-v3-doc-sediment-auto` skill + sediment-poststop hook | — | — | doc-only |

### §2.2 Tier B (S12-S15)

| Sprint | scope | 起手 plugin invoke | 主体 plugin invoke | 横切层归属 (§5) | 自造组件触发 |
|---|---|---|---|---|---|
| **S12** L2 Bull/Bear 2-Agent debate | V3 §5.3 (V4-Pro debate) | OMC `architect` + `brainstorming` | OMC `executor` + `quantmind-v3-prompt-eval-iteration` | 横切 §5.4 prompts/risk eval ≥1 round | `quantmind-prompt-iteration-evaluator` subagent |
| **S13** L2 Risk Memory RAG (pgvector + BGE-M3) | V3 §5.4 | OMC `architect` (BGE-M3 vs LiteLLM 决议沿用 PR #216) | OMC `executor` + `qa-tester` (retrieval 命中率 verify) | — | `quantmind-v3-llm-cost-monitor` (embedding cost) |
| **S14** L5 RiskReflector + 5 维反思 | V3 §8 | OMC `scientist` + `analyst` (5 维反思 prompt 设计) | OMC `executor` + `quantmind-v3-prompt-eval-iteration` + `ralph` (周/月/event-after cadence) | 横切 §5.4 reflector_v1.yaml prompt eval | `quantmind-risk-domain-expert` subagent |
| **S15** ADR-025/026 sediment + 闭环验证 | V3 §11.1 | OMC `document-specialist` | `quantmind-v3-doc-sediment-auto` skill + sediment-poststop hook | — | — |

### §2.3 sprint 间 transition (V3 §12.1 依赖)

S1 → S2 (LiteLLM 是 News fetcher 主源 prerequisite) / S2 → S3 (NewsClassifier 输入是 News raw) / S3 → S5 (sentiment modifier 输入是 NewsClassifier 输出, S5 必 wire) / S4 → S6 (fundamental_context 是 push 内容上游, 决议后 S6 起手) / S5 → S7 (RealtimeRiskEngine 实时事件触发动态阈值更新) / S6 → S8 (告警 push 是 STAGED 决策权 prerequisite) / S7 → S5 (动态阈值 fed back 到 RealtimeRiskRule eval) / S8 → S9 (STAGED 是 batched + trailing 上游) / S9 → S10 (Tier A 闭环 paper-mode 5d) / S10 → S11 (paper-mode 通过后 sediment ADR) / S11 → T1.5 (Tier A closed 后 backtest_adapter 实施起手).

---

## §3 自造 13 skill / 8 hook / 7 subagent 索引 (Constitution §L6.2 展开)

### §3.1 13 自造 quantmind-v3- skill (step 3 sediment 详细 spec)

| skill | path | trigger | V3 invocation |
|---|---|---|---|
| `quantmind-v3-fresh-read-sop` | `.claude/skills/quantmind-v3-fresh-read-sop/SKILL.md` | sub-PR / step / cross-session resume 起手 | 跟现 session_context_inject.py v2 hook 互补 — skill 是 CC 主动 invoke 知识, hook 是 SessionStart auto inject |
| `quantmind-v3-cite-source-lock` | 同上路径体例 | 任 数字/编号/路径 cite | 4 元素 cite 强制 (sprint period 跨 sprint 累计) |
| `quantmind-v3-active-discovery` | 同上 | sub-PR 起手 + 中段 + 闭前 | Phase 0 finding ≥1 + 3 类 STOP 触发 (沿用 LL-098 X10) |
| `quantmind-v3-redline-verify` | 同上 | broker / .env / yaml / DB row mutation 前 | 5/5 红线 query + 5 condition 严核 (沿用 SOP-5 LL-103 Part 2) |
| `quantmind-v3-anti-pattern-guard` | 同上 | sub-PR 起手 + sediment 前 | v1-v5 anti-pattern check |
| `quantmind-v3-sprint-closure-gate` | 同上 | sprint 闭前 | stage gate criteria 机器可验证清单 (Constitution §L10) |
| `quantmind-v3-doc-sediment-auto` | 同上 | sub-PR 闭后 | LL/ADR/STATUS_REPORT/handoff/ROADMAP 同步 sediment |
| `quantmind-v3-banned-words` | 同上 | reply + prompt 出前 | 真+词 / sustained 中文滥用 check (memory #25) |
| `quantmind-v3-prompt-design-laws` | 同上 | Claude.ai 写 prompt 给 CC 时 | 0 数字/path/command 守门 (memory #19/#20) |
| `quantmind-v3-sprint-replan` | 同上 | sprint 实际超 baseline 1.5x | replan template + push user (Constitution §L0.4) |
| `quantmind-v3-prompt-eval-iteration` | 同上 | prompts/risk/*.yaml prompt iteration | V4-Flash → V4-Pro upgrade 决议 + 跨 sprint eval methodology |
| `quantmind-v3-llm-cost-monitor` | 同上 | LLM call cost 累积 | 月度 audit + 上限 + warn enforce (V3 §16.2 / §20.1 #6) |
| `quantmind-v3-pt-cutover-gate` | 同上 | PT 重启时机 | cutover gate checklist (Constitution §L10.5 Gate E) |

### §3.2 8 hook 索引 — 4 全新 + 4 现有扩展 (step 4 sediment)

**4 全新 hook**:

| hook | path | 类型 | 跟现 hook 互补 |
|---|---|---|---|
| `redline_pretool_block.py` | `.claude/hooks/redline_pretool_block.py` | PreToolUse | 跟现 `protect_critical_files.py` 互补 — protect 偏 file pattern, redline 偏 5/5 红线 query |
| `cite_drift_stop_pretool.py` | `.claude/hooks/cite_drift_stop_pretool.py` | PreToolUse | 跟 `iron_law_enforce.py` 互补 — iron law 偏铁律 2/4/5/6/8, cite_drift 偏 SESSION_PROTOCOL §3.3 5 类漂移 detect |
| `sediment_poststop.py` | `.claude/hooks/sediment_poststop.py` | Stop | 跟现 `verify_completion.py` 互补 — verify 偏 doc 同步提醒, sediment 偏 LL/ADR/STATUS_REPORT auto append candidate |
| `handoff_sessionend.py` | `.claude/hooks/handoff_sessionend.py` | SessionEnd | audit row 18 真值 SessionEnd 类型现 0 wire — gap 必补; 沿用铁律 37 + handoff_template.md schema |

**4 现有 hook 扩展** (反 v0.1 silent 全新创建):

| 现 hook | path | 扩展 scope |
|---|---|---|
| `session_context_inject.py` v2 | `.claude/hooks/session_context_inject.py` | 扩 V3 doc + Constitution + invocation map + REGISTRY 4 doc 加入 inject scope (合并 fresh-read-sessionstart) |
| `verify_completion.py` | `.claude/hooks/verify_completion.py` | 扩 4 元素 cite source 锁定 enforce (合并 cite-source-poststop) + 真+词 / sustained 中文滥用 reject + auto-rewrite (合并 banned-words-poststop) |
| `iron_law_enforce.py` | `.claude/hooks/iron_law_enforce.py` | 扩 V3 invariant: V3 §11 12 模块 fail-open / 真账户红线 / Beat schedule 注释 ≠ 停服 / prompt 设计 0 数字 path command (合并 anti-prompt-design-violation-pretool) |
| `protect_critical_files.py` (候选) | `.claude/hooks/protect_critical_files.py` | 候选扩: V3 prompts/risk/*.yaml protect (audit §4 cite, 实施时按 sub-PR 决议是否纳入) |

**残余 sub-task** (5-09 V3 governance batch closure sub-PR 2 PR #287 sediment 修订, ADR-DRAFT row 11 直 promote 进 REGISTRY.md as ADR-044 — 现有 hook v1→v2 action mode 反 silent overwrite ADR-022 体例): `block_dangerous_git.py` 5-07 sub-PR 8a-followup-pre committed but never wired settings.json — V3 实施期某 sprint wire 闭环 (沿用 LL-117 committed sub-PR 1 PR #286 atomic sediment+wire 体例).

### §3.3 7 subagent 索引 — 4 全新 + 3 借 OMC (step 5 sediment)

**4 全新 charter file** (`.claude/agents/quantmind-*.md`):

| subagent | OMC equivalent | 论据 |
|---|---|---|
| `quantmind-cite-source-verifier` | 0 | 反 hallucination 专用 cross-source verify, audit §5.2 cite "0 OMC equivalent" |
| `quantmind-redline-guardian` | 0 | 真账户 / .env / DB row 5/5 红线, 0 OMC equivalent |
| `quantmind-risk-domain-expert` | 0 | V3 §13/14/15 风控特有领域审视 (借 quantmind-factor-analyzer skill 底子, 扩到风控域), 0 OMC equivalent |
| `quantmind-prompt-iteration-evaluator` | 0 | V4-Flash vs V4-Pro 路由决议, 0 OMC equivalent |

**3 借 OMC extend + quantmind-v3- charter file**:

| subagent | OMC base extend | charter file |
|---|---|---|
| `quantmind-v3-sprint-orchestrator` | OMC `planner` extend | V3 sprint chain 跟踪 + sprint-by-sprint 触发 invocation 索引 + cross-sprint state |
| `quantmind-v3-sprint-closure-gate-evaluator` | OMC `verifier` extend | V3 §10/15 closure criteria 机器可验证清单 |
| `quantmind-v3-tier-a-mvp-gate-evaluator` | OMC `verifier` extend | V3 S10 paper-mode 5d 验收专用 |

---

## §4 Transition gate (sprint 间 / stage 间)

### §4.1 sprint 间 transition gate

每 sprint 闭前 `quantmind-v3-sprint-closure-gate` skill 跑机器可验证清单:

- [ ] V3 §12.3 测试策略 per Sprint 验收 (Unit ≥ baseline / Integration smoke / pre-push hook PASS / STATUS_REPORT 沉淀)
- [ ] sub-PR 全 closed (CC 实测 git log + PR # cite + ADR REGISTRY committed verify)
- [ ] 5/5 红线 sustained
- [ ] sprint 期 LL append candidate / ADR-DRAFT row candidate sediment cite
- [ ] memory `project_sprint_state.md` handoff sediment (沿用铁律 37 + handoff_template.md)
- [ ] sprint 实际超 baseline 1.5x → STOP + push user replan (沿用 Constitution §L0.4)

任一不通过 → STOP + push user (sprint 收口决议).

### §4.2 stage 间 transition gate

V3 实施 7 stage transition gate (Constitution §L0.2 + §L10):

| stage transition | gate | verifier |
|---|---|---|
| Stage 1 (chunk C / LL-115 / capacity expansion) → Stage 2 (S4-S8) | S4 决议 closed (skip / minimal / 完整) + capacity expansion sub-PR closed | user 介入 (Constitution §L8.1 (a)) |
| Stage 2 (S4-S8) → Stage 3 (S9-S11) | S5+S8 4-29 痛点 fix 主体闭环 (跌停 detection 秒级 + 决策权升级) | `quantmind-v3-sprint-closure-gate` skill |
| Stage 3 → Stage 4 (T1.5 12 年回测) | Tier A closed (Gate A — Constitution §L10.1) | `quantmind-v3-tier-a-mvp-gate-evaluator` subagent |
| Stage 4 → Stage 5 (Tier B) | T1.5 closed (Gate B — Constitution §L10.2) | `quantmind-risk-domain-expert` subagent + `quantmind-v3-sprint-closure-gate-evaluator` subagent |
| Stage 5 → Stage 6 (横切 §13-§17 显式 sprint 化) | Tier B closed (Gate C — Constitution §L10.3) | `quantmind-risk-domain-expert` subagent |
| Stage 6 → Stage 7 (PT 重启 critical path) | 横切层 closed (Gate D — Constitution §L10.4) | `quantmind-v3-sprint-closure-gate-evaluator` subagent + `quantmind-v3-pt-cutover-gate` skill |
| Stage 7 closed | PT cutover gate ✅ (Gate E — Constitution §L10.5) — user 显式 .env paper→live 授权 | `quantmind-v3-pt-cutover-gate` skill |

---

## §5 横切层归属 (V3 §13/14/15.6/17.1/§3.2 §5.2 §5.3 §8.4 prompts/§11.4 backtest_adapter)

V3 §12 sprint 拆分**未显式 sprint 化** 的横切层, 本 invocation map 显式归属:

### §5.1 V3 §13 元监控 (`risk_metrics_daily` + alert on alert)

**归属**: S5 (实施 sprint, RealtimeRiskEngine wire `risk_metrics_daily` 写入) + S10 (paper-mode 5d 验收 `alerts on alert` 触发 ≥0 P0) + Stage 6 横切 sprint (`risk_metrics_daily` SQL row count + 日期连续性 verify ≥14 day).

verifier: `quantmind-v3-tier-a-mvp-gate-evaluator` subagent (Gate A 部分).

### §5.2 V3 §14 失败模式 12 项 enforce

**归属**: S5/S6/S8 (实施 sprint 各 sprint enforce 对应 failure mode subset) + Stage 6 横切 sprint (灾备演练 ≥1 round 沉淀 `docs/risk_reflections/disaster_drill/` 沿用 V3 §14.1).

invocation: superpowers `systematic-debugging` (4-phase root cause) + OMC `debugger` + OMC `ralph` (long-running 灾备演练).

### §5.3 V3 §15.6 合成场景 (CC 决议 methodology, T0-12 G2)

**归属**: S10 (paper-mode 5d dry-run 走合成场景 ≥7 类) + Stage 6 横切 sprint (合成场景 pytest fixture + assertion CI 跑).

invocation: OMC `scientist` (合成场景 methodology) + `qa-tester` + superpowers TDD.

### §5.4 prompts/risk/*.yaml prompt eval / iteration

**归属**: S3 (起点 — NewsClassifier prompt) + S12 (Bull/Bear 2-Agent prompts) + S14 (RiskReflector reflector_v1.yaml) + Stage 6 横切 sprint (`quantmind-v3-prompt-eval-iteration` skill ≥1 round V4-Flash → V4-Pro upgrade 决议 sediment).

invocation: `quantmind-v3-prompt-eval-iteration` skill + `quantmind-prompt-iteration-evaluator` subagent.

### §5.5 V3 §11.4 RiskBacktestAdapter 接口前置

**归属 (上帖 user 决议 (A))**: **S5 sprint 顺带实现接口** (反 sub-task creep, 沿用 V3 §11.4 评估为纯函数, 0 broker / 0 alert / 0 INSERT 依赖). S5 sprint scope 含 RealtimeRiskEngine 抽象出纯函数 evaluate_at(timestamp, positions, market_data, context) 接口.

verifier: `quantmind-risk-domain-expert` subagent (T1.5 起手前 verify 接口 production-ready).

### §5.6 V3 §13.1 5 SLA verify

**归属**: S10 (paper-mode 5d 期 5 SLA 实测 — L1 detection latency P99 / News 6 源 / LiteLLM / DingTalk / STAGED 30min) + Gate E PT cutover prerequisite.

invocation: `quantmind-v3-tier-a-mvp-gate-evaluator` subagent.

### §5.7 V3 §17.1 CI lint `check_anthropic_imports.py`

**归属**: Stage 6 横切 sprint (sediment lint script + pre-push hook 集成沿用现 X10 + smoke pattern).

invocation: ADR-DRAFT row 11 (hook write+wire pairing governance) 候选 promote — 反 file-only sediment 体例 (沿用 audit §4 `block_dangerous_git.py` 0 wire 实证).

### §5.8 V3 §16.2 LLM 月成本 ≤ 上限 + ≥3 month 持续 ≤80% baseline

**归属**: 跨 sprint 持续 audit (S1 起 LiteLLM 接入开始) + Gate D 最终 verify ≥3 month 数据.

invocation: `quantmind-v3-llm-cost-monitor` skill + `prompt-iteration-evaluator` subagent (cost-driven model upgrade 决议).

---

## §6 冲突 resolution rules (Constitution §L6.3 展开)

### §6.1 同名冲突: quantmind 自造 > plugin

任 自造 skill / hook / subagent 跟 plugin 同名 → quantmind 自造覆盖 (沿用 quantmind project governance 优先).

实证: mattpocock `git-guardrails-claude-code` skill 跟现 `block_dangerous_git.py` hook 体例 — 沿用现 hook (项目级 sediment 已落地 sub-PR 8a-followup-pre + reviewer P0/P1 全 adopt), mattpocock skill 仅作 reference patterns 来源 (不直 invoke).

### §6.2 skill auto-trigger 不可控时: invocation map 显式 invoke 强制

superpowers + mattpocock + ECC + OMC 四套 plugin auto-trigger 同名 / 类似 keyword 时 (e.g. "tdd" 跟 superpowers TDD + OMC TDD mode 双触发), invocation map §2 sprint-by-sprint 表显式 invoke 强制.

### §6.3 caveman / zoom-out 等 token 优化 skill 限 scope

仅用于子任务 chat-only 段, 反 cite source / sediment 段 (会丢 cite source 4 元素).

### §6.4 sprint-by-sprint TDD-first vs integration-first override

V3 部分 sprint integration-heavy (S5 实时化 / S8 STAGED 决策权), unit TDD 不够 — 走 integration-first override (audit §2.1 cite). invocation map §2 显式标 sprint TDD/integration 决议.

### §6.5 superpowers two-stage review vs quantmind reviewer agent (LL-067)

不重复跑 reviewer:

- **stage 1 = spec compliance** (新, 跟 V3 §12.3 sprint 验收 criteria 一致) — 走 superpowers `subagent-driven-development` 内置 review
- **stage 2 = code quality** (沿用现 LL-067 quantmind reviewer agent + AI self-merge 体例)

### §6.6 现 hook 扩展 vs 全新 hook (反 silent overwrite)

audit §4 决议: 4 现有 hook 扩展 (session_context_inject / verify_completion / iron_law_enforce / protect_critical_files 候选) + 4 全新 hook (redline / cite_drift / sediment / handoff_sessionend). 反 v0.1 8 全新 silent 创建倾向.

实施时: 现 hook 扩展走 ADR-022 集中机制 sub-PR (1 PR 1 hook 扩展 + reviewer + AI self-merge), 反整套 silent overwrite.

### §6.7 OMC borrow vs 全新 subagent

audit §5.2 + §7 决议: 4 全 0 重叠 全新 charter file + 3 借 OMC extend (沿用 (β) — user 5-08 决议).

实施时: 全新 charter file 走 `.claude/agents/quantmind-*.md` 体例; 借 OMC extend 走 `.claude/agents/quantmind-v3-*.md` charter 体例 (extend OMC `planner` / `verifier`, 不复制 OMC agent file 本身).

反向 .claude/CLAUDE.md "11 agent 全停用 4-15" 体例 — 4 全新是机制 agent 非角色扮演 (cite-source-verifier / redline-guardian / risk-domain-expert / prompt-iteration-evaluator), 4-15 决议适用领域 agent (角色扮演 > 信息增益), 不适用机制 agent.

### §6.8 Celery Beat / Servy / Windows Task Scheduler ops 不进 plugin scope

走 `docs/runbook/cc_automation/` 现有 runbook (reset_setx / Servy 全重启 / DB 命名空间修复 / etc), plugin 不参与. 这是 quantmind 项目 Windows 11 + 32GB 单机环境独有 ops 层.

---

## maintenance + footer

### 修订机制 (沿用 ADR-022 集中机制)

- 新 V3 sprint sediment / 新 audit grounding / 新 user 决议 → 1 PR sediment + Constitution + 自造组件同步 update
- LL append-only (反 silent overwrite)
- ADR # registry SSOT (LL-105 SOP-6) sub-PR 起手前 fresh verify
- 本 invocation map 跟 Constitution v0.X 同步迭代 (Constitution version bump 时本文件同步 review)

### 版本 history

- **v0.1 (initial skeleton, 2026-05-08)**: post-audit grounded — §0 元信息 + §1 plugin curation (OMC 16 agent + 10 tier-0 / superpowers 10 / mattpocock 6 / ECC 选片) + §2 sprint-by-sprint (Tier A S1-S11 + Tier B S12-S15) + §3 自造索引 (13 skill / 4+4 hook / 4+3 subagent) + §4 transition gate (sprint + stage 7 transitions) + §5 横切层归属 (8 横切 layer) + §6 冲突 resolution rules (8 rule)
- **v0.2 (post-V3 6 件套 100% closure cumulative cite refresh, 2026-05-09, V3 governance batch closure sub-PR 4)**: 沿用 ADR-022 反 silent overwrite (v0.1 row 保留, version history append) + sustained sub-PR 1+2+3a+3b+3c governance pattern parallel体例 + LL-127 §0.3 cumulative cite SSOT 锚点 baseline 真值落地 sustainability sediment cumulative scope 三段累积扩 sub-PR 4 cumulative scope. 修订 hybrid (edit cumulative cite refresh + augmented banner cumulative cite + footer NEW + version history append) 沿用 sub-PR 3a edit 体例 + sub-PR 3b/3c pure append 体例 累积扩 sub-PR 4 sediment 体例:
  - **header block**: cite Constitution v0.2 → v0.3 (post-PR #288/#289/#290) + version v0.1 → v0.2 + scope outside refresh (件 3-6 全 closed cumulative PR # cite) + v0.2 cumulative cite banner NEW (V3 6 件套 100% closure + V3 governance batch closure cumulative pattern sub-PR 1+2+3a+3b+3c+4 cite + LL-098/100/105/116 governance pattern cumulative)
  - **§3.2 残余 sub-task cite refresh**: `block_dangerous_git.py` wire pairing governance ADR-DRAFT row 11 直 promote 进 ADR-044 (sub-PR 2 PR #287 sediment 修订) + LL-117 候选 → committed sub-PR 1 PR #286 cite refresh
  - **footer cumulative cite refresh**: scope outside 件 3-6 closure cumulative PR # cite + 关联 LL 8 LL-116~136 promoted cite + 关联 ADR ADR-019 ~ ADR-046 (反 ADR-DRAFT row 11/12/13 detour, sustained Q4 (β) 决议) + 关联铁律 sustained
  - **footer NEW v0.2 cumulative cite section**: V3 governance batch closure sub-PR 4 sediment cumulative scope cite + LL-127 §0.3 cumulative cite SSOT 锚点 baseline 三段累积扩 sub-PR 4 cumulative scope sediment 真值落地 sustainability + sub-PR 5-7 pending cumulative pattern cite
- **v0.3 (post-Tier A plan 修订 sediment, 2026-05-09, V3 governance batch closure sub-PR 8 — Finding #2 (b) S2.5 row 加 + Push back #3 (b) parallel S2 sediment)**: 沿用 ADR-022 反 silent overwrite (v0.1/v0.2 row 保留 + version history append) + sustained sub-PR 1-7 governance pattern parallel体例 + plan-then-execute 体例累积扩 sub-PR 8 cumulative scope sediment. 修订 trigger = user invoke `quantmind-v3-sprint-orchestrator` charter (件 5) 跑 Tier A S1-S11 sprint chain plan phase, surface 3 Phase 0 active discovery findings, user 决议 4 项 (Finding #1 (b) + #2 (b) + #3 (a) + Push back #1 (i) root path / #2 ack content source / #3 (b) S2.5 parallel S2):
  - **header line 9**: 版本 v0.2 → v0.3 + post-Tier A plan 修订 sediment 真值
  - **§2.1 Tier A sprint table 加 S2.5 row** (Finding #2 (b) sediment): V3 §11.1 row 5 AnnouncementProcessor 公告流 ingest + parser, Tier A 11 → 12 sprint, parallel S2 (Push back #3 (b)) 前置 仅 S1 LiteLLMRouter prerequisite (S2 + S2.5 共享 prerequisite 后 parallel cumulative). baseline +0-0.5 周, V3 实施期总 cycle ~26-31 周 (Finding #3 (a) + Push back #3 (b) cumulative)
  - **关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.3 → v0.4 (§0.1 line 35 ROADMAP 标注 + §L0.4 baseline 修订 + version history v0.4 entry append) + 关联 docs/V3_TIER_A_SPRINT_PLAN_v0.1.md NEW file (Tier A 12 sprint plan post-Finding 决议落地, root level path post-Push back #1 (i) accept)
  - **修订 hybrid 体例真值** (CC 真测决议): edit (header version + §2.1 S2.5 row insert) + append (version history v0.3 entry) — 沿用 sub-PR 4-7 hybrid 体例累积扩 sub-PR 8 sediment 体例
  - **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 ADR-DRAFT.md 修订 + 0 LESSONS_LEARNED.md 修订 + 0 REGISTRY.md 修订 + 0 V3_LAUNCH_PROMPT.md 修订 + 0 SESSION_PROTOCOL.md 修订 + 0 §0/§1/§3/§4/§5/§6 修订** sustained (sustained ADR-022 反 silent overwrite + LL append-only governance + sub-PR 1-7 governance pattern parallel体例; 仅 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.3 → v0.4 双 file delta + docs/V3_TIER_A_SPRINT_PLAN_v0.1.md NEW file 三 file delta total)
- **v0.4 (post-V3 §S1 closure verify + V2 prior cumulative cite annotation, 2026-05-09, V3 governance batch closure sub-PR 9 — V3 §S1 ✅ substantially closed by V2 prior work cite annotation)**: 沿用 ADR-022 反 silent overwrite (v0.1/v0.2/v0.3 row 保留 + version history append) + sustained sub-PR 1-8 governance pattern parallel体例 + plan-then-execute 体例累积扩 sub-PR 9 cumulative scope sediment. 修订 trigger = sub-PR 8 closure 后 user explicit ack Tier A S1 起手 + sprint-orchestrator charter (件 5) Phase 0 verify surface "V3 §S1 substantially closed by V2 prior work" finding + user 4 决议 accept (γ+β hybrid / (i) drop "6 provider" sustained 3 routes / (a) baseline ~14-18 周 / (a) sequential):
  - **header line 9**: 版本 v0.3 → v0.4
  - **§2.1 S1 row** (sub-PR 9 sediment): V3 §S1 row 加 "✅ substantially closed by V2 prior work (post sub-PR 9 verify, PR #219-#226 + #246/247/253/255 cumulative ~5630 行)" annotation + TDD/integration col 加 "post sub-PR 9: verify-only + cite reconcile + ADR-047/LL-137 sediment hybrid 已 done" annotation. 沿用 ADR-022 反 silent overwrite + 反 retroactive content edit, 仅 append annotation 0 改 row 原 scope/triggers/横切 4 cols
  - **关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.4 → v0.5 (§L0.4 baseline 真值再修订 ~26-31→~14-18 周 + version history v0.5 entry append) + 关联 docs/V3_TIER_A_SPRINT_PLAN_v0.1.md §A S1 row reconcile (4 cite drift fix) + §E grand total 修订 ~14-18 周 + 关联 ADR-047 NEW + LL-137 NEW
  - **修订 hybrid 体例真值** (CC 真测决议): edit (header version + §2.1 S1 row annotation) + append (version history v0.4 entry) — 沿用 sub-PR 4-8 hybrid 体例累积扩 sub-PR 9 cumulative scope sediment 体例
  - **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 V3_LAUNCH_PROMPT.md 修订 + 0 SESSION_PROTOCOL.md 修订 + 0 §0/§1/§3/§4/§5/§6 修订** sustained (sustained ADR-022 反 silent overwrite + sub-PR 1-8 governance pattern parallel体例; sub-PR 9 doc-only sediment scope = Constitution + skeleton + Plan v0.1 + ADR-047 + REGISTRY + LL-137 6 file delta atomic)
- **v0.5 (post-V3 §S2 closure verify + V2 prior cumulative cite annotation, 2026-05-09, V3 governance batch closure sub-PR 10 — V3 §S2 ✅ substantially closed by V2 prior work + 4/4 RSSHub capacity expansion deferred to S5 per ADR-048)**: 沿用 ADR-022 反 silent overwrite (v0.1/v0.2/v0.3/v0.4 row 保留 + version history append) + sustained sub-PR 1-9 governance pattern parallel体例 + plan-then-execute 体例累积扩 sub-PR 10 cumulative scope sediment. 修订 trigger = sub-PR 9 closure 后 user explicit ack S2/S2.5 起手 + sprint-orchestrator charter (件 5) Phase 0 verify surface "V3 §S2 substantially closed by V2 prior cumulative work" finding (V2 sub-PR 1-7c + 8a/8b/8b-cadence cumulative PR #234-#257 ~22 files / ~3000-4000 行 已 done + 291 pytest pass + 4/4 RSSHub capacity expansion deferred architecture decision LL-115) + user 5 决议 accept (γ verify-only + closure-only gap fix hybrid for S2 / δ full implement for S2.5 / α sequential / a memory frontmatter patch in S2 closure / a defer 4/4 RSSHub capacity expansion to S5):
  - **header line 9**: 版本 v0.4 → v0.5
  - **§2.1 S2 row** (sub-PR 10 sediment): V3 §S2 row 加 "✅ substantially closed by V2 prior work (post sub-PR 10 verify, PR #234-#257 cumulative ~22 files / ~3000-4000 行 / 11 test files / 291 pytest pass / ADR-033 + ADR-043 committed; 4/4 RSSHub capacity expansion deferred to S5 per ADR-048)" annotation + TDD/integration col 加 "post sub-PR 10: verify-only + cite reconcile + ADR-048/LL-138 sediment hybrid 已 done" annotation. 沿用 ADR-022 反 silent overwrite + 反 retroactive content edit, 仅 append annotation 0 改 row 原 scope/triggers/横切 4 cols
  - **关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.5 → v0.6 (header + version history v0.6 entry append) + 关联 docs/V3_TIER_A_SPRINT_PLAN_v0.1.md §A S2 row reconcile (V2 prior cite + retroactive note + cite reconcile sustained S1 row 4 cite drift fix体例) + 关联 ADR-048 NEW + LL-138 NEW
  - **修订 hybrid 体例真值** (CC 真测决议): edit (header version + §2.1 S2 row annotation) + append (version history v0.5 entry) — 沿用 sub-PR 4-9 hybrid 体例累积扩 sub-PR 10 cumulative scope sediment 体例
  - **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 V3_LAUNCH_PROMPT.md 修订 + 0 SESSION_PROTOCOL.md 修订 + 0 §0/§1/§3/§4/§5/§6 修订** sustained (sustained ADR-022 反 silent overwrite + sub-PR 1-9 governance pattern parallel体例; sub-PR 10 doc-only sediment scope = Constitution + skeleton + Plan v0.1 + ADR-048 + REGISTRY + LL-138 6 file delta atomic)
- **v0.6 (post-V3 §S2.5 architecture sediment + DDL sediment + auto mode reasonable defaults 1st 实证, 2026-05-09, V3 governance batch closure sub-PR 11a — V3 §S2.5 architecture sediment cycle 起手 + ADR-049 + LL-139 sediment)**: 沿用 ADR-022 反 silent overwrite (v0.1-v0.5 row 保留 + version history append) + sustained sub-PR 1-10 governance pattern parallel体例 + plan-then-execute 体例累积扩 sub-PR 11a cumulative scope sediment. 修订 trigger = sub-PR 10 closure 后 user explicit ack S2.5 起手 ("同意" 3rd) + sprint-orchestrator charter (件 5 借 OMC `planner` extend) S2.5 architecture decisions surface (6 decisions + 3 Phase 0 findings + chunked 2 sub-PR split recommendation 反 Plan v0.1 §A S2.5 single sub-PR cite) + auto mode reasonable defaults sediment cycle 1st 实证:
  - **header line 9**: 版本 v0.5 → v0.6
  - **§2.1 S2.5 row** (sub-PR 11a sediment): V3 §S2.5 row 加 "架构 sediment ✅ DONE (sub-PR 11a, ADR-049: 6 decisions + 3 findings resolution + chunked 2 split + RSSHub route reuse) + DDL sediment ✅ DONE (announcement_raw NEW); implementation ⏳ sub-PR 11b 待办" annotation + sequential per sub-PR 10 user 决议 #3 (α) sustained 反 Plan §A "parallel S2" 早决议 cite drift fix + RSSHub route reuse (Decision 3 ADR-049) annotation. 沿用 ADR-022 反 silent overwrite + 反 retroactive content edit, 仅 append annotation 0 改 row 原 scope/triggers/横切 4 cols
  - **关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.6 → v0.7 (header + version history v0.7 entry append) + 关联 docs/V3_TIER_A_SPRINT_PLAN_v0.1.md §A S2.5 row patch (architecture sediment status + chunked 11a/11b split + scope acceptance items expanded) + 关联 ADR-049 NEW + LL-139 NEW + 关联 backend/migrations/2026_05_09_announcement_raw.sql + _rollback.sql NEW (DDL atomic pair)
  - **修订 hybrid 体例真值** (CC 真测决议): edit (header version + §2.1 S2.5 row annotation) + append (version history v0.6 entry) — 沿用 sub-PR 4-10 hybrid 体例累积扩 sub-PR 11a cumulative scope sediment 体例
  - **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 V3_LAUNCH_PROMPT.md 修订 + 0 SESSION_PROTOCOL.md 修订 + 0 §0/§1/§3/§4/§5/§6 修订** sustained (sustained ADR-022 反 silent overwrite + sub-PR 1-10 governance pattern parallel体例; sub-PR 11a doc-only + DDL sediment scope = Constitution + skeleton + Plan v0.1 + ADR-049 + REGISTRY + LL-139 + announcement_raw migration + rollback 8 file delta atomic, 反 sub-PR 8-10 doc-only 6 file delta体例 — 加 2 DDL file delta 沿用 sub-PR 7b.1 news_raw migration precedent + 4-phase pattern)
- **v0.7 (post-V3 §S2.5 implementation 闭环 + chunked 2 sub-PR split closure + plan-then-execute 体例 5th 实证, 2026-05-09, V3 governance batch closure sub-PR 11b — V3 §S2.5 implementation + ADR-050 + LL-140 sediment)**: 沿用 ADR-022 反 silent overwrite (v0.1-v0.6 row 保留 + version history append) + sustained sub-PR 1-11a governance pattern parallel体例 + plan-then-execute 体例累积扩 sub-PR 11b cumulative scope sediment. 修订 trigger = sub-PR 11a closure 后 user explicit ack sub-PR 11b implementation ("同意" 4th, sustained ADR-049 §3 chunked 2 sub-PR split):
  - **header line 9**: 版本 v0.6 → v0.7
  - **§2.1 S2.5 row close-out**: V3 §S2.5 row 加 "✅ COMPLETE (sub-PR 11a + 11b cumulative, ADR-049 + ADR-050 sediment, 31/31 tests PASSED)" annotation + implementation status closure annotation. 沿用 ADR-022 反 silent overwrite + 反 retroactive content edit, 仅 append annotation 0 改 row 原 scope/triggers/横切 4 cols
  - **关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.7 → v0.8 (header + version history v0.8 entry append) + 关联 docs/V3_TIER_A_SPRINT_PLAN_v0.1.md §A S2.5 row close-out (✅ COMPLETE annotation + sub-PR 11a + 11b cumulative cite) + 关联 ADR-050 NEW (Beat trading-hours cadence + per-source fail-soft + announcement_type filter EXCLUDE earnings disclosure) + LL-140 NEW (V3 §S2.5 implementation 体例 + announcement_type inference precedent + chunked 2 sub-PR split closure) + 关联 7 production code file delta (announcement_routes.py NEW + announcement_processor.py NEW + __init__.py edit + announcement_ingest_tasks.py NEW + api/news.py edit + beat_schedule.py edit + test_announcement_processor.py NEW)
  - **修订 hybrid 体例真值** (CC 真测决议): edit (header version + §2.1 S2.5 row close-out annotation) + append (version history v0.7 entry) — 沿用 sub-PR 4-11a hybrid 体例累积扩 sub-PR 11b cumulative scope sediment 体例
  - **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 V3_LAUNCH_PROMPT.md 修订 + 0 SESSION_PROTOCOL.md 修订 + 0 §0/§1/§3/§4/§5/§6 修订** sustained (sustained ADR-022 反 silent overwrite + sub-PR 1-11a governance pattern parallel体例; sub-PR 11b implementation scope = Constitution + skeleton + Plan + ADR-050 + REGISTRY + LL-140 + 7 production code file delta ~13 file delta atomic ~1100-1300 lines — 反 sub-PR 8-11a doc-only/DDL 体例, sub-PR 11b 真**首次** production code sediment in V3 governance batch closure cumulative pattern; sustained ADR-049 §3 chunked 2 sub-PR split sub-PR 11a (DDL+ADR sediment) + sub-PR 11b (implementation+tests+ADR sediment) 闭环)

### footer

- **维护频率**: V3 sprint sediment 时 / Constitution v0.X bump 时 / sprint 间 transition gate 不通过时 (1 PR sediment 沿用 LL-100)
- **SSOT**: 本文件 = V3 实施期 invocation 索引唯一权威源
- **关联文件 6 件套**: Constitution + 本 + 13 skill SKILL.md + 8 hook 实施 + 7 subagent charter + 启动 prompt — **V3 6 件套 100% closure ✓** (post-PR #285, 件 1 audit + 件 2 Constitution v0.3 + 件 3 13 skill + 件 4 13 hook cumulative + 件 5 7 charter + 件 6 V3_LAUNCH_PROMPT v0.1 + 本 skeleton v0.2 修订 sub-PR 4 cumulative scope sediment)
- **本文件 scope outside**: ❌ skill / hook / subagent / 启动 prompt 详细 spec — 件 3-6 全 ✅ closed (post-PR #285, V3 6 件套 100% 完整闭环 ✓): 件 3 ✅ 13 skill (PR #272-#275 + #281 bonus) / 件 4 ✅ 13 hook cumulative (4+4+5, PR #276/#280/#281/#282/#283/#284) / 件 5 ✅ 7 charter (PR #277-#279) / 件 6 ✅ V3_LAUNCH_PROMPT v0.1 (PR #285)
- **关联铁律**: 9 / 17 / 25 / 36 / 37 / 42 / 44 (X9) / 45 / X10
- **关联 LL**: LL-098 (X10) / LL-100 / LL-101 / LL-103 / LL-104 / LL-105 / LL-106 / LL-115 / **LL-116 / LL-117 / LL-127 / LL-132 / LL-133 / LL-134 / LL-135 / LL-136** (committed sub-PR 1 PR #286, 8 LL promoted; LL-116 fresh re-read enforce + LL-117 atomic sediment+wire + LL-127 §0.3 cumulative cite SSOT 锚点 baseline + LL-132 pre-push smoke baseline drift detection + LL-133 现有 hook v1→v2 lifecycle + LL-134 路径假设 vs 实测 + LL-135 doc-only sediment + LL-136 sub-PR sediment time CC 自身 cumulative cite cross-verify) + 后续
- **关联 ADR**: ADR-019 ~ ADR-046 (sub-PR 2 PR #287 sediment 直 promote 进 REGISTRY.md as **ADR-044/045/046**, 反 ADR-DRAFT row 11/12/13 detour, sustained user Q4 (β) 决议 + sub-PR 1 LL append-only governance pattern parallel体例)
- **现 last update**: V3 governance batch closure sub-PR 4 sediment (skeleton v0.2 修订 + Constitution v0.3 §version history typo `架→角` fix, post-PR #290 + 本 PR)

### v0.2 cumulative cite footer NEW (V3 governance batch closure sub-PR 4 sediment, 2026-05-09)

- **post-V3 6 件套 100% closure cumulative cite refresh** (本 v0.2 修订 trigger): 件 2 Constitution v0.3 chunked closure (sub-PR 3a/3b/3c PR #288/#289/#290) + 件 3-6 cumulative PR # 完整闭环 → skeleton v0.1 → v0.2 cumulative cite refresh trigger 满足 (sustained sub-PR 4 user explicit trigger)
- **V3 governance batch closure cumulative pattern (~5-7 sub-PR)**: sub-PR 1 LL-cumulative-batch (PR #286 ✓ 8 LL committed) + sub-PR 2 ADR-cumulative-batch (PR #287 ✓ 3 ADR-044/045/046 promoted) + sub-PR 3 chunked Constitution v0.3 修订 完整闭环 ✅ (3a §L0.3+§L1.1 PR #288 + 3b §L6.1+§L6.2 PR #289 + 3c §L10 + version history v0.3 entry PR #290) + **sub-PR 4 本 PR** (skeleton v0.2 修订 + Constitution v0.3 §version history typo fix) + sub-PR 5-7 pending (sub-PR 5 SESSION_PROTOCOL §1.3 扩 / sub-PR 6 untracked cleanup + 全 stale cite refresh / optional sub-PR 7 V3_LAUNCH_PROMPT v0.1→v0.2 修订)
- **LL-127 §0.3 cumulative cite SSOT 锚点 baseline 真值落地 sustainability sediment cumulative scope 四段累积**: sub-PR 3a §L0.3 footer NEW + sub-PR 3b §L6.2 footer NEW + sub-PR 3c §L10 footer NEW + **本 sub-PR 4 skeleton v0.2 footer NEW** = 四段累积 ✓ (LL-127 multi-method sensitivity SOP 体例累积扩 governance pattern parallel体例)
- **第 11 项 prompt 升级 real-world catch 4 case 实证累积**: sub-PR 6 pre-sediment Q5 + sub-PR 1 LL # next free + sub-PR 2 ADR-DRAFT row 11-26 cumulative count drift + sub-PR 3a Constitution 版本号 v0.1→v0.3 vs v0.2→v0.3 真值修正
- **第 12 项 prompt 升级候选 #1 LL-116 9 case 实证累积反向 enforce**: 2 reverse (PR #281/#282) + 7 verified positive (PR #283/#284/#285/#287/#288/#289/#290) — 本 sub-PR 4 fresh re-read skeleton v0.1 §0/§1/§2/§3/§N anchor 真值 verify (sustained 第 10 verified positive case 实证累积扩)
- **sub-PR 4 sediment 体例真值** (CC 真测决议): hybrid (edit + augmented banner cumulative cite + footer NEW + version history append) 沿用 sub-PR 3a edit 体例 + sub-PR 3b/3c pure append 体例 累积扩 sub-PR 4 cumulative scope sediment 体例
- **0 hook + 0 skill + 0 charter + 0 settings.json wire delta + 0 ADR-DRAFT.md 修订 + 0 LESSONS_LEARNED.md 修订 + 0 REGISTRY.md 修订 + 0 §L0.3/§L1.1/§L5/§L6.1/§L6.2/§L8/§L10 修订** sustained (sustained ADR-022 反 silent overwrite + LL append-only governance + sub-PR 1+2+3a+3b+3c governance pattern parallel体例; 仅 docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md skeleton v0.1→v0.2 + docs/V3_IMPLEMENTATION_CONSTITUTION.md §version history typo `架→角` fix 双 file delta)

---

**文档结束**.
