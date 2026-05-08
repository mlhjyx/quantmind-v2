# `.claude/` 现状 audit + V3 实施期 wire 整理报告

> **sub-PR**: `fix/claude-dir-audit-v3-orchestration-pre`
> **触发**: 2026-05-08 user 决议 — V3 风控实施期主线起手前置 audit (Claude.ai 探讨 step 1 closure 后 surface 8 finding, 0 SQL/git/log 真测 verify, 本 sub-PR 第一职责真测 cross-verify).
> **scope**: doc-only audit + 整理报告. 0 改 settings.json / hooks / skills / production code / .env / yaml. 0 修订 Constitution v0.1 (v0.2 修订是后续独立 sub-PR).
> **基线**: main HEAD `8dca576` (PR #269 后, fresh `git log -1 --format=%h main` 真测 2026-05-08).
> **红线 5/5 sustained**: cash ¥993,520 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID 未触.
> **关联**: ADR-022 / ADR-037 / 铁律 45 / LL-098 X10 / LL-100 / LL-101 / LL-103 SOP-4 / LL-104 / LL-105 SOP-6 / LL-115.

---

## §1 现状真值表 (cite source 4 元素 — path / line# / section / fresh verify timestamp)

每行 fresh 真测 2026-05-08 (本 sub-PR Phase 0 verify 沿用 SESSION_PROTOCOL §3.1 cite SOP).

| # | 项 | path | 真值 | cite 元素 |
|---|---|---|---|---|
| 1 | settings.json wire 类型 | `.claude/settings.json` | **4 wire types** (SessionStart / PreToolUse / PostToolUse / Stop). **NOT 5** — `SessionEnd` 0 wire | line 5-93 fresh read |
| 2 | settings.json hook entries | `.claude/settings.json` | **9 hook entries** total. **7 unique .py** (session_context_inject / pre_commit_validate / protect_critical_files / iron_law_enforce / post_edit_lint / audit_log / verify_completion) + **2 ECC observe.sh** (pre + post) | line 11-92 fresh read |
| 3 | hook .py 文件总数 | `.claude/hooks/*.py` | **9 .py** (audit_log / block_dangerous_git / doc_drift_check / iron_law_enforce / post_edit_lint / pre_commit_validate / protect_critical_files / session_context_inject / verify_completion) | fresh `Glob` 2026-05-08 |
| 4 | hook .md 文件总数 | `.claude/hooks/*.md` | **4 .md** (pre-task / pre-commit / post-task / research) — 无 frontmatter, 仅 doc placeholders | fresh `Glob` |
| 5 | hook .log | `.claude/hooks/audit.log` | **31537 bytes**, last write **2026-05-08 19:54:29** (今日 fresh — `audit_log.py` hook 实际触发) | fresh `Get-Item` |
| 6 | hook 0-wire .py | settings.json grep | **2 unwired**: `block_dangerous_git.py` (gap) + `doc_drift_check.py` (BY DESIGN — docstring line 1 "不是hook，是独立脚本") | settings.json full read + 2 .py docstring read |
| 7 | skill self-built 总数 | `.claude/skills/*/SKILL.md` | **7 skills**: 6 `quantmind-*` (db-safety / factor-discovery / factor-research / overnight-experiment / performance / research-kb) + **1 `omc-reference`** (NOT quantmind- prefixed) | fresh `Glob` |
| 8 | skill frontmatter schema | `.claude/skills/<name>/SKILL.md` head | **2 schema variants**: quantmind-* 用 `trigger:` 字段 (e.g. db-safety line 4 "ALTER TABLE\|DELETE FROM..."); omc-reference 用 `user-invocable: false` (line 4) — **NO `trigger`** | fresh head 5 read |
| 9 | OMC plugin 真值版本 | `C:/Users/hd/.claude/plugins/cache/omc/oh-my-claudecode/` | **4.9.1** + **4.9.3** 双版本 cached. session-start hint cite "current 4.9.1, available v4.13.6". user-home `settings.json` `enabledPlugins: oh-my-claudecode@omc=true` | fresh `Get-ChildItem` + user settings.json read |
| 10 | OMC tier-0 keyword triggers | `.claude/CLAUDE.md` line 33 | autopilot / ralph / ulw / ccg / ralplan / "deep interview" / deslop\|anti-slop / deep-analyze / tdd / deepsearch / ultrathink / cancelomc | fresh project CLAUDE.md read |
| 11 | ECC plugin 真值路径 | `C:/Users/hd/.claude/plugins/marketplaces/everything-claude-code/` | wired in project settings.json line 49 (PreToolUse pre) + line 76 (PostToolUse post). observe.sh = bash script, reads stdin JSON, project-scoped (resolves git root from `cwd`), 写 observation 到 project-specific dir | fresh observe.sh head 80 + settings.json grep |
| 12 | mattpocock SKILL.md 总数 | `.claude/external-skills/mattpocock-skills/skills/**` | **22 SKILL.md**. 分类 (沿用 CLAUDE.md `engineering/productivity/misc/personal/deprecated`): engineering 9 / productivity 3 / misc 4 / personal 2 / **deprecated 4** | fresh `Glob` |
| 13 | mattpocock plugin.json registry | `.claude/external-skills/mattpocock-skills/.claude-plugin/plugin.json` | **12 skills registered** (engineering 9 + productivity 3). misc/ + personal/ + deprecated/ 全 0 register (沿用 mattpocock CLAUDE.md 体例 "personal/ 和 deprecated/ must not appear in either") | fresh plugin.json read |
| 14 | rules/quantmind-overrides.md | `.claude/rules/quantmind-overrides.md` | 1 file, 5 节 (测试规则 / 数据库安全 / 因子研究 / 代码风格 / 不适用的ECC功能). cite 铁律 9/11/13 + Harvey-Liu-Zhu-2016 — 全 IRONLAWS v3.0 valid (0 stale cite). ECC 覆盖 scope: TDD / TS / Go / Java / E2E / Node | fresh read |
| 15 | commands | `.claude/commands/check-ic.md` | **1 slash command**: `/check-ic <factor_name>` 因子 IC 快查 (factor_ic_history + factor_profile 双 SQL) | fresh read |
| 16 | worktrees/ at root | `D:/quantmind-v2/worktrees/` | **DIRECTORY DOES NOT EXIST** | fresh `Test-Path` returned `worktrees_DIR_MISSING` |
| 17 | .gitignore worktrees | `.gitignore:67` | `.claude/worktrees/` (under `.claude/`, NOT root). `.claude/worktrees/` 同样 NOT EXIST | fresh grep + Test-Path |
| 18 | launch.json | `.claude/launch.json` | 2 configs: Frontend Vite port 5173 + Backend FastAPI port 8000. **0 V3-specific entries** | fresh full read |
| 19 | settings.local.json | `.claude/settings.local.json` | 仅 `permissions.allow` allowlist (Bash + 17 WebFetch domains + 2 MCP). **0 hooks**, 0 enabledPlugins | fresh full read |
| 20 | COMMIT_MSG_TMP files | `.claude/COMMIT_MSG_TMP_*.txt` | **22 files** (NOT ~24 per Claude.ai cite — drift). **NOT in .gitignore** (workspace residue, untracked) | fresh `Get-ChildItem` count + `.gitignore` grep |
| 21 | external-skills/.omc/state/ | `.claude/external-skills/**/.omc/` | **DOES NOT EXIST** in inventory. `.gitignore` line 100-101 ignores `.omc/` + `**/.omc/` (runtime artifact dir, project-wide) | fresh `Glob` recursive |
| 22 | user-home settings.json | `C:/Users/hd/.claude/settings.json` | 2133 bytes. enabledPlugins (true): code-review / code-simplifier / feature-dev / claude-md-management / firecrawl / ralph-loop / superpowers / hookify / commit-commands / oh-my-claudecode / everything-claude-code / superpowers (local-desktop-app-uploads) / **mattpocock-skills (local-desktop-app-uploads)** | fresh full read |

**汇总**: `.claude/` 实际 file 数: settings.json (1) + settings.local.json (1) + launch.json (1) + CLAUDE.md (1) + 22 COMMIT_MSG_TMP_*.txt + hooks/ (9 .py + 4 .md + 1 .log = 14) + skills/ (7 SKILL.md) + commands/ (1) + rules/ (1) + external-skills/mattpocock-skills/ (22 SKILL.md + plugin.json + ...) = sub-tree 含 100+ entry. 本 audit 锁 14 关键 entry, 详 §3.

---

## §2 Claude.ai 8 finding cross-verify (5 类漂移 detect — 沿用 SESSION_PROTOCOL §3.3)

| # | Claude.ai cite | fresh verify 真值 | 漂移类型 | 真值修正 scope |
|---|---|---|---|---|
| 1 | "settings.json wire 配 hook 全套" | settings.json 真有 wire (4 types, 9 entries, 7 unique .py + 2 observe.sh) | ✅ verified | 补充: SessionEnd 类型 0 wire — V3 实施期需补 (`handoff-sessionend` v0.1 §L6.2 候选) |
| 2 | "OMC v4.9.1" | cache 4.9.1 + 4.9.3, current 4.9.1, available 4.13.6 | ✅ verified | 现 4.9.1, 不强制 upgrade (V3 实施期 0 必 4.13.6 dependency) |
| 3 | "ECC continuous-learning-v2 hook wired" | wired pre + post, observe.sh project-scoped | ✅ verified | 0 修正 |
| 4 | "mattpocock 项目级 clone" | cloned at `.claude/external-skills/mattpocock-skills/` (含 .git/), 22 SKILL.md, plugin.json 12 register | ✅ verified | 0 修正 (clone 真生效) |
| 5 | **"9 hook 5 类型 wire"** | **9 .py 真存在 ✅, 但 7 wired in 4 types ❌** (SessionEnd 0 wire + block_dangerous_git + doc_drift_check 0 wire) | ❌ **数字漂移 + 编号漂移** | "Claude.ai cite '9 hook 5 类型 wire' / fresh verify 真值 '9 .py + 7 wired in 4 types' / 真值修正: 7/9 .py wired, 2/9 unwired (block_dangerous_git=gap, doc_drift_check=BY DESIGN), SessionEnd 类型缺失" |
| 6 | "7 自造 skill" | **7 skills ✅**, 但 6 quantmind-* + 1 omc-reference (NOT 7 quantmind-) | 🟡 **partial** (数字 ✅, 命名构成 drift) | "Claude.ai cite '7 自造 skill' / fresh verify 真值 '7 skills (6 quantmind-* + 1 omc-reference)' / 真值修正: 命名规范 NOT uniform, frontmatter schema 2 variants (trigger vs user-invocable)" |
| 7 | "rules/quantmind-overrides.md ECC 覆盖体例" | `.claude/rules/quantmind-overrides.md` 1 file, ECC 覆盖 scope (TDD/TS/Go/Java/E2E/Node) confirmed, 铁律 cite 全 valid | ✅ verified | 0 修正 |
| 8 | **"worktrees + COMMIT_MSG_TMP"** | **worktrees/ 0 存在** (Claude.ai 沿 `.gitignore:67` 推断, 实际目录不存在). COMMIT_MSG_TMP **22** (NOT ~24, drift), **NOT in .gitignore** (workspace residue) | ❌ **存在漂移 + 数字漂移** | "Claude.ai cite 'worktrees + ~24 COMMIT_MSG_TMP' / fresh verify 真值 'worktrees/ 0 存在 (root + .claude/ 双否) + 22 COMMIT_MSG_TMP NOT in .gitignore' / 真值修正: worktrees/ 候选用途 (superpowers using-git-worktrees / OMC team workflow) 待 V3 sub-PR 时机激活; COMMIT_MSG_TMP cleanup governance 决议待 sediment (ADR-DRAFT row 12 候选)" |

**漂移汇总**: 8 finding 中 **5 verified ✅** (#1-#4 + #7) / **1 partial 🟡** (#6 数字对构成 drift) / **2 drift ❌** (#5 + #8). drift 率 25%, 沿用 LL-101 实证 (Claude.ai cite 必 SQL/git/ls/grep 真测 verify before 复用) 第 N+1 次实证. 详 §10 LL-116 候选.

---

## §3 现 7 skill V3 实施期 mapping 真值

| skill | path | V3 触发关联 | mapping 评级 | 备注 |
|---|---|---|---|---|
| `omc-reference` | `.claude/skills/omc-reference/SKILL.md` | V3 全程 OMC delegation reference (12+ agent catalog / tier-0 workflow / commit protocol) | ✅ **V3 全程必 reference** | sprint period sediment, 0 stale, V3 invocation map step 2 必 cite |
| `quantmind-db-safety` | `.claude/skills/quantmind-db-safety/SKILL.md` | V3 §3.1 news_articles hypertable + §10 11 张新 risk 表 + §13 risk_metrics_daily + 铁律 9/11/17 触发 (ALTER TABLE / batch INSERT / DataPipeline) | ✅ **V3 §3.1 + §10 + §13 触发** | trigger field cite "ALTER TABLE\|DELETE FROM\|DROP\|TRUNCATE\|大批量\|写入\|migrate" — V3 11 张新表 prerequisite |
| `quantmind-performance` | `.claude/skills/quantmind-performance/SKILL.md` | V3 §15 backtest replay (12 年 counterfactual) + V3 §11.4 RiskBacktestAdapter | 🟡 **V3 间接相关** | sprint period 沿用, V3 期只在 backtest path 触发 |
| `quantmind-research-kb` | `.claude/skills/quantmind-research-kb/SKILL.md` | failed/findings/decisions 防重复失败方向 (38 条目 sediment) | 🟡 **V3 不直接相关 / ongoing 项目相关** | 无 V3 direct trigger, 但 ongoing 项目防 NO-GO 重做必 reference |
| `quantmind-factor-discovery` | `.claude/skills/quantmind-factor-discovery/SKILL.md` | 因子 pipeline (论文 → IC → 中性化 → 画像 → 报告) | 🟡 **V3 不直接相关 / ongoing 项目相关** | 因子 layer V3 之外 ongoing scope |
| `quantmind-factor-research` | `.claude/skills/quantmind-factor-research/SKILL.md` | 新因子标准流程 (经济机制 → 计算 → IC → 入库) — 铁律 13/14 enforcement | 🟡 **V3 不直接相关 / ongoing 项目相关** | 因子 layer ongoing scope |
| `quantmind-overnight-experiment` | `.claude/skills/quantmind-overnight-experiment/SKILL.md` | 过夜批量参数网格 + 反过拟合 | 🟡 **V3 不直接相关 / ongoing 项目相关** | ongoing 实验 scope |

**汇总**: ✅ V3 全程必 reference: **2** (omc-reference / quantmind-db-safety). 🟡 V3 间接 / ongoing: **5**. ❌ deprecate 候选: **0** (无 stale skill — 沿用 ADR-022 反 silent deprecation, 0 删除).

**V3 期 skill gap**: v0.1 §L6.2 cite 自造 13 skill (quantmind- prefix) — 现仅 6 个 quantmind- skill, gap = **7 skills 待 step 3 sediment** (沿用 v0.1 §L6.2 总览, 详 §7 + §9).

---

## §4 现 9 hook V3 实施期 mapping 真值

| hook | path | wire 状态 | wire matcher | V3 mapping | 扩展候选 |
|---|---|---|---|---|---|
| `audit_log.py` | `.claude/hooks/audit_log.py` | ✅ wired | PostToolUse `""` | V3 全程必沿用 (audit.log fresh 2026-05-08 19:54 实证) | 0 (扩 V3 cost row sediment 由 sediment-poststop 候选 hook 接管) |
| `block_dangerous_git.py` | `.claude/hooks/block_dangerous_git.py` | ❌ **0 wire (gap)** | — | V3 必 wire (PreToolUse[Bash] — 5/5 红线 enforcement layer 2 防御) | **wire to PreToolUse[Bash]** (file 5-07 sub-PR 8a-followup-pre committed but never wired settings.json — LL-109 hook governance 4 days 0 catch reverse case sustained, ADR-DRAFT row 11 候选) |
| `doc_drift_check.py` | `.claude/hooks/doc_drift_check.py` | 🟡 **0 wire BY DESIGN** | — (standalone script) | V3 间接相关 (DDL vs DB drift 检测 — V3 §10 11 张新表入库时 trigger) | 不必 wire (沿用 docstring "不是hook，是独立脚本"); V3 期 manual run 或 schtask wire (ops 层, 不进 settings.json) |
| `iron_law_enforce.py` | `.claude/hooks/iron_law_enforce.py` | ✅ wired | PreToolUse `Edit\|Write` | V3 全程必沿用 (铁律 enforcement) | 扩 V3 invariant (V3 §11 12 模块 fail-open / 真账户红线 / Beat schedule 注释 ≠ 停服 等) — 候选 v0.2 修订 |
| `post_edit_lint.py` | `.claude/hooks/post_edit_lint.py` | ✅ wired | PostToolUse `Edit\|Write` | V3 全程必沿用 | 0 |
| `pre_commit_validate.py` | `.claude/hooks/pre_commit_validate.py` | ✅ wired | PreToolUse `Bash` | V3 全程必沿用 (commit lint — pre-push hook 配合) | 0 |
| `protect_critical_files.py` | `.claude/hooks/protect_critical_files.py` | ✅ wired | PreToolUse `Edit\|Write` | V3 全程必沿用 (.env / yaml / production code 红线) | 扩 V3 11 张新 DDL 表 / prompts/risk/*.yaml protect — 候选 v0.2 修订 |
| `session_context_inject.py` | `.claude/hooks/session_context_inject.py` | ✅ wired | SessionStart | V3 全程必沿用 (sprint state inject — v2 line 31-39 真测 frontmatter description 字段提取) | 扩 V3 doc fresh read trigger (8 doc 沿用 v0.1 §L1.1, 当前仅 4 root doc + Blueprint cite) — `fresh-read-sessionstart` v0.1 §L6.2 候选可合并到现 hook |
| `verify_completion.py` | `.claude/hooks/verify_completion.py` | ✅ wired | Stop `""` | V3 全程必沿用 (任务完成 verify) | 扩 V3 closure gate criteria (`tier-a-mvp-gate-evaluator` subagent 触发) |

**汇总**: 9 .py 中 **7 wired in 4 types** (SessionStart 1 / PreToolUse 4 / PostToolUse 2 / Stop 1) + **2 unwired** (1 gap + 1 BY DESIGN). 0 stale, 0 dead (audit.log 实证 today fresh).

**V3 期 hook 扩展决议**:
- **优先 wire**: `block_dangerous_git.py` (gap, sub-PR 后续闭环, 不进本 audit sub-PR 0 修改硬边界)
- **复用扩展**: 3 现有 hook (session_context_inject / iron_law_enforce / protect_critical_files) — 沿用复用 > 新 hook 创建 (反 v0.1 §L6.2 8 hook 全 new sediment 倾向)
- **新 hook 减量**: v0.1 §L6.2 cite 自造 8 hook → 真测决议候选 4 (redline-pretool-block / cite-drift-stop-pretool / sediment-poststop / handoff-sessionend) — 因 fresh-read-sessionstart / cite-source-poststop / banned-words-poststop / anti-prompt-design-violation-pretool 4 个建议合并到现 hook 扩展 (沿用 ADR-022 反 silent overwrite + 反 abstraction premature)

---

## §5 OMC tier-0 workflows + 12+ agent V3 实施期 invocation 真值

### §5.1 Tier-0 workflows V3 invocation

| Tier-0 workflow | 触发关键词 | V3 invocation | superpowers 覆盖? |
|---|---|---|---|
| `autopilot` | "autopilot" | V3 sprint full execution (S1-S15 各 sprint 起手 / verify / debug / review 一站式) | partial — superpowers `executing-plans` 更细粒度 (review checkpoint 细分) |
| `ultrawork` | "ulw" | V3 parallel high-throughput (multi sub-task in sprint, e.g. S2 双 BudgetGuard + LLMCallLogger 并行) | partial — superpowers `subagent-driven-development` 类似 |
| `ralph` | "ralph" | V3 long-running self-loop (debug / verify until done) | 0 overlap — superpowers 无 self-loop 等价 |
| `team` (`/team`) | `/team` | V3 multi-agent coordinate (sprint period sediment 体例 — sprint-orchestrator 驱动) | partial — superpowers `subagent-driven-development` 类似 |
| `ralplan` | "ralplan" | V3 planning consensus (multi-model, e.g. Claude + Codex + Gemini 三模型决议) | partial — superpowers `writing-plans` 单 agent |
| `deep-interview` | "deep interview" | V3 mathematical ambiguity gating (sprint 起手前 user-CC alignment) | unique — superpowers 无 (mattpocock `grill-me` 类似但更轻) |
| `ai-slop-cleaner` | "deslop"/"anti-slop" | V3 dead code cleanup (sprint period 沿用 — 5 SOP cluster 体例) | partial — refactor-cleaner agent |
| TDD mode | "tdd" | V3 §17.1 CI lint enforcement + 测试 first 体例 | superpowers `test-driven-development` 沿用 (V3 sprint 起手 TDD 优先) |
| deepsearch | "deepsearch" | V3 codebase search (sprint dependency 起点 — V3 §11 12 模块 import 关联 grep) | 0 overlap |
| ultrathink | "ultrathink" | V3 deep reasoning (本 sub-PR 触发) | 0 overlap |

**Claude.ai cite 挑战 (§4(b))**: "OMC tier-0 workflows 已覆盖 superpowers brainstorming + writing-plans + executing-plans"

**真测 verify**:
- ❌ **partial drift**. tier-0 5 workflow (autopilot/ultrawork/ralph/team/ralplan) 是 OMC 自有 multi-agent orchestration, scope **大于** superpowers 3 个 (brainstorming/writing-plans/executing-plans). 但**细粒度方法论**:
  - superpowers `brainstorming` 是 user-CC alignment 强制 SOP (creative work 必 invoke) — OMC tier-0 0 等价
  - superpowers `writing-plans` 是 multi-step task plan SOP — OMC `ralplan` 类似但侧重 multi-model consensus
  - superpowers `executing-plans` 是 review checkpoint SOP — OMC `autopilot`/`ralph` 不等价 (OMC 偏 autonomous, superpowers 强制 checkpoint)
- **结论**: OMC tier-0 vs superpowers 3 skill **scope 重叠 partial, 互补**. v0.1 §L6.1 cite "superpowers brainstorming / writing-plans / subagent-driven-development / systematic-debugging / TDD / verification-before-completion / requesting-code-review / receiving-code-review / finishing-a-development-branch / using-git-worktrees" 选片 (10 skill) 真值与 OMC tier-0 互补, **不应砍掉 superpowers 选片**.

### §5.2 OMC 16 agent vs 自造 7 subagent 重叠 verify

OMC `omc-reference` skill cite agent catalog (16 个, prefix `oh-my-claudecode:`):

```
explore (haiku) / analyst (opus) / planner (opus) / architect (opus) /
debugger (sonnet) / executor (sonnet) / verifier (sonnet) / tracer (sonnet) /
security-reviewer (sonnet) / code-reviewer (opus) / test-engineer (sonnet) /
designer (sonnet) / writer (haiku) / qa-tester (sonnet) /
scientist (sonnet) / document-specialist (sonnet)
```

v0.1 §L6.2 cite 自造 7 subagent (quantmind- prefix candidate):

```
sprint-orchestrator / cite-source-verifier / redline-guardian /
sprint-closure-gate-evaluator / risk-domain-expert /
prompt-iteration-evaluator / tier-a-mvp-gate-evaluator
```

| 自造 subagent | OMC 等价 | 重叠? |
|---|---|---|
| `sprint-orchestrator` | planner + architect 复合 | 🟡 partial — quantmind-* sprint chain 跟踪 OMC 0 等价 |
| `cite-source-verifier` | 无 OMC 等价 | ✅ 0 重叠 (反 hallucination 专用 cross-source verify) |
| `redline-guardian` | 无 OMC 等价 | ✅ 0 重叠 (真账户 / .env / DB row 5/5 红线) |
| `sprint-closure-gate-evaluator` | verifier 类似 | 🟡 partial — V3 §10/15 closure criteria 机器可验证清单 OMC 0 等价 |
| `risk-domain-expert` | 无 OMC 等价 | ✅ 0 重叠 (V3 §13/14/15 风控特有领域审视) |
| `prompt-iteration-evaluator` | 无 OMC 等价 | ✅ 0 重叠 (V4-Flash vs V4-Pro 路由决议) |
| `tier-a-mvp-gate-evaluator` | verifier 类似 | 🟡 partial — V3 S10 paper-mode 5d 验收专用 OMC 0 等价 |

**结论**: 自造 7 subagent 中 **4 全 0 重叠** (cite-source-verifier / redline-guardian / risk-domain-expert / prompt-iteration-evaluator). **3 partial overlap** (sprint-orchestrator / sprint-closure-gate-evaluator / tier-a-mvp-gate-evaluator) — 可走 OMC general-purpose / planner / verifier extend 体例, 不必全新 subagent file.

V3 期 subagent 决议候选: **0 全新 subagent — 借现 OMC general-purpose / planner / verifier + .claude/agents/ quantmind-* charter file 体例** (沿用 .claude/CLAUDE.md "QM 11 agent 全停用 2026-04-15" 决议反向 — 慎重新增 agent file). 但 v0.1 §L6.2 cite 7 subagent — 与本 audit 0 全新 subagent 真值 **冲突**, v0.2 修订必决议.

---

## §6 mattpocock 选片 verify (Claude.ai 推荐 6 skill)

| Skill | Claude.ai 推荐 | 真值位置 (path) | active 状态 | 状态 cite |
|---|---|---|---|---|
| `grill-me` | ✅ | `productivity/grill-me/SKILL.md` | ✅ active | plugin.json line 14 |
| **`design-an-interface`** | ✅ | `deprecated/design-an-interface/SKILL.md` ❌ | **❌ NOT active** | `deprecated/README.md` line 5: "Skills I no longer use"; plugin.json 0 register; mattpocock CLAUDE.md "deprecated/ must not appear in either" |
| `git-guardrails-claude-code` | ✅ | `misc/git-guardrails-claude-code/SKILL.md` | ⚠️ active 但 plugin.json 0 register | mattpocock CLAUDE.md 体例: "engineering/, productivity/, misc/ must have a reference in top-level README.md and an entry in `.claude-plugin/plugin.json`" — 但 plugin.json fresh read 仅 12 entry (engineering 9 + productivity 3, **无 misc/**). misc/ skills 需 manual reference, 不自动 plugin auto-load |
| `zoom-out` | ✅ | `engineering/zoom-out/SKILL.md` | ✅ active | plugin.json line 12 |
| `write-a-skill` | ✅ | `productivity/write-a-skill/SKILL.md` | ✅ active | plugin.json line 16 |
| `caveman` | ✅ | `productivity/caveman/SKILL.md` | ✅ active | plugin.json line 13 |

**汇总**: 6 推荐中 **4 ✅ active + plugin registered** / **1 ⚠️ active 但 plugin 0 register** (git-guardrails-claude-code) / **1 ❌ deprecated** (design-an-interface).

**Claude.ai cite 挑战 (§4(c))**: "mattpocock 推荐 6 skill 全 active" — **❌ 真值漂移**. `design-an-interface` 是 deprecated. v0.1 §L6.1 cite 此 skill 为选片, 与 audit 真值 **直接冲突** — v0.2 修订必移除.

**git-guardrails-claude-code 备注**: skill 真存在 + 沿用其 `block-dangerous-git.sh` patterns sediment 入 `.claude/hooks/block_dangerous_git.py` (sub-PR 8a-followup-pre 5-07 sediment, ADR-DRAFT row 7 candidate sediment 体例). **misc/ category 0 plugin auto-load** 不影响其作为 reference patterns 来源的真值.

---

## §7 新建组件清单 (post-audit grounded) + 0 冲突 verify

| 组件类型 | prompt cite 数 | v0.1 §L6.2 cite 数 | audit 真值决议 | path 候选 | 现状 0 冲突 verify |
|---|---|---|---|---|---|
| 4 新 hook (prompt) / 8 自造 hook (v0.1) | **4** | **8** | **真值决议候选 4 全新** (redline-pretool-block / cite-drift-stop-pretool / sediment-poststop / handoff-sessionend) + **4 合并现有** (fresh-read-sessionstart → session_context_inject 扩 / cite-source-poststop → verify_completion 扩 / banned-words-poststop → verify_completion 扩 / anti-prompt-design-violation-pretool → iron_law_enforce 扩) | `.claude/hooks/<name>.py` | 跟现 9 hook **0 命名冲突 ✅**. 但 prompt cite "4" vs v0.1 §L6.2 cite "8" — **数字漂移** — v0.2 修订必决议 |
| 3 现有 hook 扩展 (prompt) | **3** | — | 与上行决议一致: **3 扩展** (session_context_inject / iron_law_enforce / verify_completion). protect_critical_files.py 扩 (V3 prompts/risk/*.yaml protect) 候选 → 实际 4 扩展 | 扩展 path 不动 | 0 冲突 ✅ |
| 13 v3- 前缀 skill (prompt + v0.1 §L6.2) | **13** | **13** | match ✅ | `.claude/skills/quantmind-<name>/SKILL.md` | 跟现 6 quantmind-* (db-safety / factor-discovery / factor-research / overnight-experiment / performance / research-kb) **0 命名冲突 ✅** (新 13 全 quantmind-* prefix 0 重名) |
| 3 自造 subagent (prompt) / 7 自造 subagent (v0.1) | **3** | **7** | **真值决议候选 4 全 0 重叠 全新** (cite-source-verifier / redline-guardian / risk-domain-expert / prompt-iteration-evaluator) + **3 借 OMC** (sprint-orchestrator → planner extend / sprint-closure-gate-evaluator → verifier extend / tier-a-mvp-gate-evaluator → verifier extend) | `.claude/agents/quantmind-*.md` (or 借 OMC) | `.claude/agents/` 现 0 file (CLAUDE.md cite "11 agent 全停用 2026-04-15"). 复用 .claude/agents/ path 跟历史 0 命名冲突 ✅ — 但 v0.1 §L6.2 cite "7 subagent" vs prompt cite "3" + audit 决议 "4 全新 + 3 借 OMC" — **数字漂移**, v0.2 修订必决议 |

**汇总**: 4 处 cite drift (prompt vs v0.1):
1. 新 hook: prompt 4 / v0.1 8 (audit 决议 4 全新 + 4 合并现有)
2. 现有 hook 扩展: prompt 3 / v0.1 隐含 (audit 决议 4 — 加 protect_critical_files)
3. v3- 前缀 skill: prompt 13 / v0.1 13 (match ✅)
4. 自造 subagent: prompt 3 / v0.1 7 (audit 决议 4 全新 + 3 借 OMC)

→ v0.2 修订必决议这 4 处真值, 沿用 anti-pattern v5 (Claude 给具体 → CC 实测决议).

---

## §8 next-prompt 草稿 — Constitution v0.2 修订 sub-PR prompt

> **scope**: V3_IMPLEMENTATION_CONSTITUTION.md v0.1 → v0.2 修订, 沿用 LL-100 chunked SOP, 单 sub-PR (doc-only).
> **关联**: 本 audit report (`docs/audit/v3_orchestration/claude_dir_audit_report.md`) 真值反馈 + ADR-022 反 silent overwrite (v0.1 row 保留, version history append).

### 修订要点 (基于本 audit 真值)

#### §L0.3 起手 verify SOP (5 步) — 修订

| step | v0.1 cite | audit 真值 | v0.2 修订方向 |
|---|---|---|---|
| (1) plugin 装上 verify | superpowers + mattpocock + ECC 选片在 ~/.claude/plugins/ | ✅ verified (user-home settings.json line 30-33 + plugin cache dir 全存在) | 0 修订 |
| (2) slash command trigger verify | `/brainstorming` `/grill-me` `/harness-audit` cli verify | partial verified (本 audit 0 trigger 实测, 仅 plugin path 实测) | 加 cli output capture 体例 (沿用 SESSION_PROTOCOL §3.3 mtime 漂移 detect) |
| (3) **SessionStart hook fire** | "自造 fresh-read-sessionstart hook 跑出 4 doc + V3 doc 扩展 mtime cite" | ❌ **真值漂移** — fresh-read-sessionstart hook 0 存在; **现 session_context_inject.py v2 已 wired** (SessionStart, line 1-39 v2 重写 cite) | v0.2 修订: cite **session_context_inject.py v2** (现实) + 扩 V3 8 doc fresh read trigger (反新 hook 全新创建, 沿用 ADR-022 反 silent overwrite + 反 abstraction premature) |
| (4) 13 skill / 8 hook / 7 subagent verify | "存在 + 内容真测" | ❌ **真值漂移** — 当前 6 quantmind-skill + 9 hook (7 wired) + 0 quantmind-subagent | v0.2 修订: 锁定 audit 真值 cite 起点 (6 → 13 skill / 9 hook (7 wired) → 13 hook (12 wired) / 0 → 4 subagent (full new) + 3 OMC extend), 反 prompt 数字单 cite |
| (5) 红线 5/5 verify | python scripts/_verify_account_oneshot.py | ✅ verified (本 audit 红线 sustained verify 实证) | 0 修订 |

#### §L1.1 8 doc fresh read — 修订

| Doc | v0.1 cite | audit 真值 | v0.2 修订方向 |
|---|---|---|---|
| CLAUDE.md / IRONLAWS.md / LESSONS_LEARNED.md / SYSTEM_STATUS.md | committed | ✅ verified | 0 修订 |
| docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md | committed | ✅ verified (V3 main spec) | 0 修订 |
| docs/V3_IMPLEMENTATION_CONSTITUTION.md (本文件) | committed | ✅ verified (v0.1 sediment 5-08) | 修订为 v0.2 |
| **docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md** (step 2) | "step 2 产出" | ❌ **0 存在** (planned, 未 sediment) | v0.2 cite 改 "planned" 标记, 不算 fresh read 必读 doc; 或 step 2 sub-PR 起手时再加入 |
| docs/adr/REGISTRY.md | committed | ✅ verified | 0 修订 |

→ 真值: 8 doc cite 中 **6 committed + 2 planned** (Constitution 自身在本 v0.2 PR 修订 + INVOCATION_MAP step 2 待生)

#### §L6.1 plugin 选片 — 修订

mattpocock 选 list: v0.1 cite "grill-me / **design-an-interface** / git-guardrails-claude-code / zoom-out / write-a-skill / caveman" — **必移除 design-an-interface** (deprecated 真值, audit §6 cite).

可选加: `setup-matt-pocock-skills` (engineering/, plugin.json line 8) — 跟 mattpocock plugin 起手 verify 配合 (沿用 README.md line 31 cite).

#### §L6.2 自造 13/8/7 总览 — 修订

audit 决议真值 (§7 cite):
- skill: **13** match (新 13 全 quantmind- prefix, 跟现 6 0 命名冲突)
- hook: **4 全新 + 4 合并现有** (反 v0.1 §L6.2 8 全新 全 sediment 倾向, 沿用 ADR-022 反 silent overwrite + 反 abstraction premature)
- subagent: **4 全新 + 3 借 OMC** (反 v0.1 §L6.2 7 全新 sediment 倾向, .claude/agents/ 历史 0 file 状态尊重)

**v0.2 修订规则**: 反 prompt-only 数字 cite, 沿用 anti-pattern v5 (Claude 给具体 → CC 实测决议) + memory #19/#20 prompt 设计铁律 (写"方向+目标+验收", CC 实测决议具体值).

### 修订后 v0.2 必含

- §L0.3 step (3) cite session_context_inject.py v2 (现实)
- §L1.1 标 6 committed + 2 planned
- §L6.1 移除 design-an-interface, 可选加 setup-matt-pocock-skills
- §L6.2 总览改 13 skill / **8 hook (4 全新 + 4 现有扩展)** / **7 subagent (4 全新 + 3 OMC extend)** — match v0.1 总数 但**实施分类清晰**
- §maintenance + footer: version history append "v0.2 (2026-05-XX, post-audit grounded), audit cite docs/audit/v3_orchestration/claude_dir_audit_report.md"

---

## §9 LL append 候选清单

LL # next free 真测: **LL-116** (LESSONS_LEARNED.md 末 LL-115 实测 grep, line 3791. LL-102 历史 skipped — LL-100/101/103-115 sequence).

### LL-116 候选 (本 sub-PR 主 sediment)

> **LL-116: Claude.ai 跨 system finding cite 必经 SQL/git/ls/grep 真测 verify before sub-PR 起手 (5-08 .claude/ audit pre-V3 sub-PR sediment, 8 finding 4 drift 实证, LL-101 + LL-103 SOP-4 + LL-104 cumulative)**

实证 4 drift:
1. "9 hook 5 类型 wire" → 真值 9 .py + 7 wired in 4 types (SessionEnd missing, 2 unwired)
2. "design-an-interface mattpocock 推荐" → 真值 in `deprecated/`, plugin.json 0 register
3. "worktrees/ exists" → 真值 worktrees/ 0 存在 (root + .claude/ 双否, 仅 .gitignore line 67 entry)
4. "~24 COMMIT_MSG_TMP" → 真值 22 + NOT in .gitignore

SOP enforcement: 沿用 LL-103 SOP-4 (Claude.ai vs CC 分离 architecture, 不信单 cite) + LL-104 (表格 cite 仅看 1 row 不够, grep 全表 cross-verify) + LL-105 SOP-6 (registry SSOT cross-verify).

### LL-117 候选 (条件触发 — block_dangerous_git.py wire 实施时)

> **LL-117: hook file-only sediment 反 wire 体例 — sub-PR sediment 必含 settings.json wire grep verify (反 5-07 sub-PR 8a-followup-pre block_dangerous_git.py 5-08 audit 真测 0 wire 4 days production 0 catch, LL-109 hook governance 4 days 0 catch reverse case 沿用, ADR-DRAFT row 11 候选)**

触发: 本 audit confirm `block_dangerous_git.py` (.claude/hooks/block_dangerous_git.py:1-80 真测 docstring 体例完整 + 4 PUSH_DANGEROUS_PATTERNS 5-07 reviewer P0/P1 全 adopt) **不在 settings.json wire** — sediment 走但 wire 未走. 4 days production 0 fire (从 5-07 PR 至 5-08 audit). LL-109 hook governance 4 days 0 catch reverse case 第 N+1 次实证.

### LL-118 候选 (可选 sediment)

> **LL-118: Constitution v0.1 self-design vs reality grounding gap (5-08 audit 真测 — fresh-read-sessionstart hook 0 存在, V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md 0 存在, design-an-interface deprecated 真值 cite 漂移). 设计层文档 sediment 后必走 audit grounding sub-PR before 后续 step 起手**

触发: v0.1 §L0.3/§L1.1/§L6.1/§L6.2 4 处 reality drift 集中暴露, 沿用 anti-pattern v5 + memory #19/#20 (Claude 给具体 → CC 实测决议).

→ **LL-118 是否单独 sediment 决议**: candidate, 不必本 sub-PR 立即 sediment (沿用 ADR-022 集中机制 + LL-115 体例先 candidate sediment 入 ADR-DRAFT, 实施时再 promote LL).

---

## §10 ADR-DRAFT row 候选清单

ADR-DRAFT.md 末 row 真测: **row 10 → ADR-042 (committed, chunk C-ADR 5-08 closure ✅)**. 下 candidate row = **row 11**.

### ADR-DRAFT row 11 候选

> **主题**: hook write+wire pairing governance — 反 file-only sediment

**source**: 本 sub-PR `.claude/` audit + LL-109 hook governance 4 days 0 catch reverse case 沿用 + LL-117 候选 (条件触发).

**case**: 5-07 sub-PR 8a-followup-pre 真测 sediment `block_dangerous_git.py` (file 完整 + docstring + 4 PUSH_DANGEROUS_PATTERNS reviewer P0/P1 全 adopt) — 但 settings.json wire 未走 (本 5-08 audit fresh verify confirm 0 wire). 4 days production 0 fire. 沿用 ADR-037 + 铁律 45 (4 doc fresh read SOP) 反向: hook sediment SOP 必含 settings.json wire grep verify, 反 file-only sediment.

**promote target**: V3 §17.1 CI lint 实施 sub-PR (S5 / 横切层 sprint) — 走 hook governance 决议 ADR (e.g. `check_hook_wire.py` lint 类似 `check_anthropic_imports.py` 体例).

### ADR-DRAFT row 12 候选

> **主题**: `.claude/COMMIT_MSG_TMP_*.txt` workspace residue governance

**source**: 本 sub-PR audit + Claude.ai finding 8 真值 cross-verify (22 file NOT in .gitignore).

**决议方向 2 选 1**:
- (α) `.gitignore` append `.claude/COMMIT_MSG_TMP_*.txt` 体例 — 反 git status 反复 ?? 干扰
- (β) sub-PR 闭后 cleanup hook (Stop matcher) 自动清 — 沿用 ADR-022 体例 反 silent (用户可见 cleanup 运行 cite)

**promote target**: 后续 sub-PR governance batch (audit Week 2 候选, 沿用 ADR-DRAFT row 4 production-level 闭环语义体例 candidate 同步走).

### ADR-DRAFT row 13 候选 (可选)

> **主题**: Constitution v0.2 修订 reality grounding sediment SOP — 反 v0.1 cite 与 audit 真值 4 处漂移

**source**: 本 sub-PR audit §8 next-prompt 草稿 4 处 cite drift (mattpocock design-an-interface deprecated / fresh-read-sessionstart hook 0 存在 / V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md 0 存在 / 自造 hook 数 4 vs 8 prompt-v0.1 drift).

**决议方向**: governance SOP "设计层文档 sediment 后 ≤1 sub-PR 必走 reality audit grounding sub-PR before 后续 step 起手" — 反 prompt-only design 与 reality 累积漂移 (沿用 LL-118 候选).

**promote target**: v0.2 修订 sub-PR (即 next-prompt §8 草稿 sub-PR), 走 ADR # reservation + commit.

---

## §11 STATUS_REPORT (沿用 5-08 sub-PR LL-115 体例)

```yaml
sub_pr: fix/claude-dir-audit-v3-orchestration-pre
date: 2026-05-08
trigger: V3 风控实施期主线起手前置 audit (Claude.ai 探讨 step 1 closure 后 surface 8 finding cross-verify)

basline:
  main_HEAD: 8dca576  # CC 实测 git log -1 --format=%h main 2026-05-08
  red_lines_5_5_sustained:
    cash: ¥993,520.16
    positions: 0
    LIVE_TRADING_DISABLED: true
    EXECUTION_MODE: paper
    QMT_ACCOUNT_ID: untouched

audit_findings_total: 22 现状真值表 row + 8 Claude.ai cross-verify + 4 cite drift

claude_ai_8_finding_verify_status:
  finding_1_settings_json_wire: ✅ verified
  finding_2_OMC_v4.9.1: ✅ verified
  finding_3_ECC_continuous_learning_v2: ✅ verified
  finding_4_mattpocock_clone: ✅ verified
  finding_5_9_hook_5_types_wire: ❌ DRIFT (9 .py / 7 wired / 4 types — SessionEnd missing + 2 unwired)
  finding_6_7_self_built_skill: 🟡 partial (7 真值 ✅, 但 6 quantmind-* + 1 omc-reference; frontmatter schema 2 variants)
  finding_7_quantmind_overrides_md_ECC_override: ✅ verified
  finding_8_worktrees_COMMIT_MSG_TMP: ❌ DRIFT (worktrees/ 0 存在; 22 not ~24; NOT in .gitignore)
  drift_rate: 25%  # 2/8 ❌ + 1/8 🟡 + 5/8 ✅

LL_append_candidates:
  - LL-116: Claude.ai 跨 system finding cite 必经 SQL/git/ls/grep 真测 verify (本 sub-PR 主 sediment)
  - LL-117: hook file-only sediment 反 wire 体例 (条件触发, block_dangerous_git.py wire 实施时)
  - LL-118: Constitution v0.1 self-design vs reality grounding gap (可选 sediment)

ADR_DRAFT_row_candidates:
  - row_11: hook write+wire pairing governance — 反 file-only sediment
  - row_12: .claude/COMMIT_MSG_TMP_*.txt workspace residue governance (α gitignore vs β cleanup hook)
  - row_13: Constitution v0.2 修订 reality grounding sediment SOP (可选)

constitution_v0_2_revision_required:
  layer_L0_3: cite session_context_inject.py v2 (反 fresh-read-sessionstart 全新 hook)
  layer_L1_1: 标 6 committed + 2 planned (V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md 0 存在)
  layer_L6_1: 移除 design-an-interface (deprecated 真值)
  layer_L6_2: 13 skill / 8 hook (4 全新 + 4 现有扩展) / 7 subagent (4 全新 + 3 OMC extend)
  scope: 后续独立 sub-PR (本 audit 0 修订, 仅 next-prompt 草稿 sediment)

chunked_SOP:
  target: ~8 min (LL-100)
  actual: 待 commit + push + PR 后实测
  scope: doc-only (1 new file claude_dir_audit_report.md ~700 lines + 1 sub_pr 起手 + 1 commit + 1 push + 1 PR + 1 reviewer agent + AI self-merge)

reviewer_agent_AI_self_merge:
  reviewer: oh-my-claudecode:code-reviewer (并行) + general-purpose (cross-check)
  AI_self_merge: 沿用 LL-067 + LL-100 体例 — doc-only PR P0/P1 0 时立 merge
  user_接触: 0 (沿用 LL-059 autonomous 9 步, audit/docs PR 类 user ≤2 接触)

memory_handoff_sediment:
  target_file: memory/project_sprint_state.md
  schema: handoff_template.md (铁律 37)
  sediment_scope:
    - sub-PR PR # cite + main HEAD post-merge
    - 8 finding cross-verify status
    - LL-116 ID 锁定 + 4 实证 cite
    - ADR-DRAFT row 11 sediment
    - V3 next-prompt v0.2 修订 sub-PR ready
    - 5/5 红线 sustained
```

---

## footer + maintenance

### 沿用 SOP

- ADR-022 反 silent overwrite + 集中机制 (审计无配置改动, 0 hook 0 skill 0 setting 改)
- ADR-037 + 铁律 45 (4 doc fresh read SOP) — 本 audit Phase 0 真测 verify 沿用
- LL-098 X10 (反 forward-progress default) — 本报告 footer 0 forward-progress offer
- LL-100 (chunked SOP ≤8 min target) — 单 PR + AI self-merge
- LL-101 (audit cite 数字 SQL/git/log 真测 verify) — 本 sub-PR 第一职责
- LL-103 SOP-4 + LL-104 (Claude.ai vs CC 跨 system cite cross-verify) — 8 finding cross-verify
- LL-105 SOP-6 (LL # / ADR # registry SSOT cross-verify) — LL-116 / ADR-DRAFT row 11 决议
- LL-115 (Phase 0 active discovery enforcement) — 本 sub-PR 起手 finding ≥1 满足

### 关联文档

- `docs/V3_IMPLEMENTATION_CONSTITUTION.md` v0.1 (本 audit grounding 反馈 → v0.2 修订 sub-PR)
- `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` (V3 main spec, 不直接 audit scope)
- `LESSONS_LEARNED.md` LL-100/101/103/104/105/106/109/115 (本 audit 沿用 + LL-116 候选 sediment)
- `docs/adr/ADR-DRAFT.md` (row 11/12/13 候选 sediment)
- `IRONLAWS.md` (铁律 9/11/13/22/25/36/37/42/45 + X10 — 本 sub-PR 沿用)

### 本报告 maintenance 规则

- append-only (沿用 LL-099 体例): 后续 audit 走新 file (e.g. `claude_dir_audit_report_v2.md`), 0 改本 file 历史 cite
- 本 file = V3 实施期 起手前 reality grounding **第一次** sediment, 后续 v0.2 修订 sub-PR 反馈走新 audit cycle 时 cite

**报告结束**.
