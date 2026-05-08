# QuantMind V3 实施期启动 Prompt (件 6, V3 6 件套 倒数 1 件)

> **本文件 = V3 风控长期实施期 (Tier A → T1.5 → Tier B → 横切层 → PT cutover gate) sprint chain 起手时 CC 自主跑通的入口 SOP**.
>
> **本文件 = 6 件套 件 6** (沿用 [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) §0 scope declaration cite "启动 prompt (step 6) = 6 件套" 真值, CC fresh re-read verify 2026-05-09; 6 件套 = Constitution + skeleton + 13 skill + 8 hook V3-batch + 7 subagent + 本 launch prompt).
>
> **scope**: V3 sprint chain 起手 SOP + 三层互补 invocation pattern + 5 大 gate 终态 cite + sediment cite trail enforce + anti-pattern guard 体例.
>
> **not scope** (走现有 SSOT): V3 spec 详细拆分 → [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §12 / sprint-by-sprint orchestration index → [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) §2 / quantmind 项目特有 invariant → Constitution §L0-L10 / skill / hook / charter spec → 件 3+4+5 各自 file sediment.
>
> **本文件版本**: v0.1 (initial sediment, 沿用 ADR-022 反 silent overwrite + 反 abstraction premature)
>
> **关联 audit**: [docs/audit/v3_orchestration/claude_dir_audit_report.md](audit/v3_orchestration/claude_dir_audit_report.md) (PR #270 真值 grounding)
>
> **关联 ADR**: ADR-022 (反 silent overwrite + 集中机制) / ADR-037 (4 doc fresh read SOP) / ADR-019/020/021/027/028 (V3 spec sediment) + V3 governance batch closure 后续 ADR

---

## §0 元信息 + 反 anti-pattern 验证

### §0.1 SSOT 锚点 (沿用 LL-105 SOP-6 cite 4 元素)

**legend** (沿用 件 4 hook count 双口径 disambiguation, P1#1 fix sediment):
- **8 hook V3-batch** = 件 4 sediment scope (4 全新 + 4 现有扩展)
- **13 hook cumulative** = `.claude/hooks/*.py` ls 真测 (8 V3-batch + 5 现有 sustained 反修订)

| 类别 | 锚点 |
|---|---|
| Constitution v0.2 | [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) (件 2) |
| skeleton v0.1 (invocation map) | [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) (件 2) |
| V3 spec authoritative | [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §12 sprint 拆分 |
| audit reality grounding | docs/audit/v3_orchestration/claude_dir_audit_report.md (件 1) |
| ADR REGISTRY | docs/adr/REGISTRY.md (LL-105 SOP-6 SSOT) |
| 13 quantmind-v3-* skill (件 3) | .claude/skills/quantmind-v3-*/SKILL.md |
| 8 hook V3-batch (件 4: 4 全新 PR #276/#280/#281/#282 + 4 现有扩展 PR #283 ×2 + #284 ×2) | .claude/hooks/*.py + .claude/settings.json wire (cumulative 13 ls 真测) |
| 7 charter (件 5: 4 全新 PR #277/#278 + 3 借 OMC extend PR #279) | .claude/agents/quantmind-*.md + .claude/agents/quantmind-v3-*.md |

### §0.2 反 anti-pattern 验证

- ✅ 0 凭空 enumerate 新决议 (走 V3 spec / Constitution / skeleton cumulative)
- ✅ 0 silent overwrite 现 13 hook cumulative (8 V3-batch + 5 现有 sustained) + 13 v3- skill + 7 charter + settings.json wire (沿用 ADR-022)
- ✅ 0 末尾 forward-progress offer (LL-098 X10)
- ✅ 0 "真+词" 禁词 (memory #25 HARD BLOCK whitelist: 真账户/真发单/真生产/真测/真值)
- ✅ 0 具体 path / file / function / SQL / command (沿用 skeleton §0.2 line 33 + memory #19/#20 — CC sprint 起手时实测决议)
- ✅ 0 hardcoded line# (cite 4 元素 sustained 反 hardcoded line — 走 path + section anchor + fresh verify timestamp)

### §0.3 起手前 cumulative truth verify (反 ECC issue 1479 实证 + 沿用 Constitution §L0.3 step 1-5 体例累积)

CC V3 实施 sprint 起手前必走 cumulative truth verify (任一不通过 → STOP + 反问 user):

| 步 | verify | tool / charter |
|---|---|---|
| (1) plugin curation | 沿用 Constitution §L0.3 step (1) — OMC + superpowers + mattpocock + ECC plugin enabled | 走 SessionStart hook auto inject + CC `ls` 真测 |
| (2) slash command trigger | 沿用 Constitution §L0.3 step (2) — OMC tier-0 + mattpocock + ECC trigger 实测 | trigger 实测 |
| (3) SessionStart hook fire | 沿用 Constitution §L0.3 step (3) — `session_context_inject.py` v3 跑出 4 root doc + V3 doc 扩展 mtime cite | hook log 真测 |
| (4) 6 件套 prerequisite verify | **本 launch prompt §1 sustained** — 13 skill + 13 hook + 7 charter + Constitution + skeleton + 本 launch prompt | `ls` + `cat` + audit cite cross-verify |
| (5) 红线 5/5 verify | 沿用 Constitution §L0.3 step (5) — cash / 持仓 / LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID | 走 `redline_pretool_block` hook (件 4 全新) + `quantmind-v3-redline-verify` skill (件 3) |

**任一漂移 → STOP + 反问 user**, 不强行起手 sprint.

---

## §1 6 件套 cumulative prerequisite verify (CC 起手必走)

CC fresh verify 6 件套 cumulative truth (沿用 LL-101 + LL-116 cite 数字 SQL/git/grep 真测 verify; 反 silent 沿用 cumulative session memory cite — 沿用第 11 项 + 第 12 项 prompt 升级候选 #1):

| 件 | scope | anchor | CC 真测 |
|---|---|---|---|
| 1 v1 governance batch | claude_dir audit + drift 率 reality grounding | docs/audit/v3_orchestration/claude_dir_audit_report.md | `cat` |
| 2 Constitution + skeleton 双 file | V3 quantmind 特有 invariant + invocation map skeleton | docs/V3_IMPLEMENTATION_CONSTITUTION.md (v0.2) + docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md (v0.1) | `cat` + 沿用第 12 项 prompt 升级候选 #1 fresh re-read §0 scope declaration verify |
| 3 13 quantmind-v3-* skill | SOP knowledge layer | .claude/skills/quantmind-v3-*/SKILL.md | `ls` 真测 13 file |
| 4 8 hook V3-batch (4 全新 PR #276/#280/#281/#282 + 4 现有扩展 PR #283 ×2 + #284 ×2; cumulative 13 ls 真测含 5 现有 sustained 反修订) | mechanism layer | .claude/hooks/*.py + 5 现有 sustained (audit_log / block_dangerous_git / doc_drift_check / post_edit_lint / pre_commit_validate) | `ls` 真测 13 cumulative + `cat .claude/settings.json` wire 5 wire types verify |
| 5 7 charter (4 全新 quantmind- prefix PR #277/#278 + 3 借 OMC extend quantmind-v3- prefix PR #279) | evidence-gathering layer | .claude/agents/quantmind-*.md + .claude/agents/quantmind-v3-*.md | `ls` 真测 7 file |
| 6 本 launch prompt | sprint chain 起手 SOP entry point | docs/V3_LAUNCH_PROMPT.md | `cat` (本文件) |

→ 任一不通过 → STOP + 反问 user (沿用 LL-098 X10 反 forward-progress default).

---

## §2 5 大 gate 终态显式可测 (Constitution §L10 sustained)

V3 closure = 以下 5 大 gate 全 ✅ (详细 criteria 见 Constitution §L10):

| Gate | scope | anchor |
|---|---|---|
| **A: Tier A closed** | Tier A sprint 全 closed + paper-mode 5d ✅ + 元监控 0 P0 元告警 + Tier A ADR 全 committed | Constitution §L10.1 |
| **B: T1.5 closed** | RiskBacktestAdapter 实现 + 反事实 replay 跑通 + WF-fold 全正 STABLE | Constitution §L10.2 |
| **C: Tier B closed** | Tier B sprint 全 closed + L2 Bull/Bear + L2 RAG + L5 Reflector production-active + Tier B ADR 全 committed | Constitution §L10.3 |
| **D: 横切层 closed** | 元监控 + 失败模式 sediment + CI lint + prompts/risk eval iteration + LLM cost monitoring | Constitution §L10.4 |
| **E: PT cutover gate ✅** | paper-mode 验收通过 + 元监控 0 P0 + Tier A ADR 全 sediment + SLA 满足 + user 决议状态 verify + user 显式 .env paper→live 授权 | Constitution §L10.5 |

→ Gate 触发顺序: Gate A → Gate B → Gate C → Gate D → Gate E (sustained Constitution §L10 sequence). 任 Gate 跳跃 → STOP + 反问 user.

---

## §3 sprint chain 起手 SOP (Tier A → T1.5 → Tier B → 横切层 → PT cutover)

### §3.1 sprint 起手 invoke pattern

CC sprint 起手 SOP (sustained skeleton §2 sprint-by-sprint table cite):

| 步 | 动作 | 走 |
|---|---|---|
| (1) fresh re-read 8 doc fresh read SOP | sustained SESSION_PROTOCOL §1 + Constitution §L1 | 走 `quantmind-v3-fresh-read-sop` skill (件 3) active CC invoke |
| (2) sprint chain state lookup | 跨 sprint 状态 + sprint-by-sprint invocation index | invoke `quantmind-v3-sprint-orchestrator` charter (件 5) via Agent tool |
| (3) charter 返 sprint chain state report + next-sprint invocation recommendation | sustained skeleton §2 sprint-by-sprint table | charter 输出 evidence rows |
| (4) sprint scope plan | sub-PR atomic sediment+wire 体例 (沿用 LL-117 候选 promote trigger sustained 满足) | CC 真测决议 sub-PR 拆分 (LL-100 chunked SOP target) |
| (5) sprint 起手 prerequisite verify | 6 件套 cumulative + 红线 5/5 + cumulative LL/ADR/Constitution cite | 走 §0.3 步 (1)-(5) cumulative |

### §3.2 sub-PR 内 atomic sediment+wire 体例 (沿用 LL-117 候选 promote trigger sustained 满足)

LL-117 候选 atomic sediment+wire 体例 — sustained PR cumulative 实证累积 (反 split / 反 sediment-only):

- **atomic** = 单 sub-PR file delta + commit + push + PR + reviewer + AI self-merge
- **chunked SOP target**: ~10-13 min cumulative per sub-PR (沿用 LL-100)
- **post-wire fire test**: ~3-4 min immediate (hook sediment 性质); doc-only sub-PR 反 fire test
- **cite source 锁定**: 任 cite 含 4 元素 (path + section anchor + fresh verify timestamp; 反 hardcoded line#)
- **真+词 / banned 0 残余**: grep 真测 (沿用 memory #25 HARD BLOCK + skill `quantmind-v3-banned-words` 件 3)
- **anti-pattern guard**: 走 `quantmind-v3-anti-pattern-guard` skill (件 3) sub-PR 起手 + sediment 前 v1-v5 anti-pattern check

### §3.3 sprint 收口 invoke pattern

sprint 收口 SOP (sustained Constitution §L10 + skeleton §2):

| 步 | 动作 | 走 |
|---|---|---|
| (1) sprint closure criteria machine-verifiable check | sprint 闭前 stage gate criteria | invoke `quantmind-v3-sprint-closure-gate-evaluator` charter (件 5) via Agent tool |
| (2) charter 返 PASS / FAIL / INCOMPLETE 结论 + evidence rows | sustained Constitution §L10 + V3 §15 closure 决议 | charter 输出 |
| (3) PASS → next sprint trigger | sustained skeleton §2 next-sprint invocation | CC 真测决议 next sprint 起手 (回 §3.1) |
| (4) FAIL → sprint-replan invoke | 沿用 sprint baseline 1.5x check | 走 `quantmind-v3-sprint-replan` skill (件 3) active CC invoke |
| (5) INCOMPLETE → user 介入决议 | sustained Constitution §L8 user 介入 3 类 | STOP + 反问 user (沿用 LL-098 X10) |

### §3.4 Tier A MVP 收口 invoke pattern (Gate A trigger)

> **scope cite** (P2 #2 fix): Gate A = Constitution §L10.1 "Tier A closed" sustained; Tier A MVP scope = Tier A sprint chain cumulative per V3 spec §12.1 (S1-S11). 本节 charter 名 `quantmind-v3-tier-a-mvp-gate-evaluator` 沿用件 5 PR #279 sediment naming convention (MVP 表 Tier A sprint chain cumulative paper-mode 5d 验收 evidence-gathering scope, 0 spec drift).

Tier A 全收口 SOP (sustained Constitution §L10.1 Gate A):

| 步 | 动作 | 走 |
|---|---|---|
| (1) Tier A sprint 全 closed verify | sustained §3.3 sprint 收口 cumulative | per-sprint sprint-closure-gate-evaluator charter cumulative output |
| (2) paper-mode 验收 evidence verify | paper-mode dry-run 期 evidence | invoke `quantmind-v3-tier-a-mvp-gate-evaluator` charter (件 5) via Agent tool |
| (3) charter 返 paper-mode 验收 evidence + 元监控 0 P0 + Tier A ADR cumulative | sustained Constitution §L10.1 + V3 §15.4 paper-mode 验收 | charter 输出 |
| (4) PASS → Gate A ✅ | sustained Tier A → Tier B transition gate | trigger §3.5 Tier B sprint chain 起手 |
| (5) FAIL → user 决议体例 sprint-replan | sustained Constitution §L8 user 介入 3 类 | STOP + 反问 user |

### §3.5 Tier B + 横切层 + PT cutover gate sequence

| 阶段 | gate | scope |
|---|---|---|
| Tier B sprint chain | 沿用 §3.1-§3.3 SOP loop | Tier B sprint 全 closed → Gate C |
| 横切层 sprint chain | 沿用 §3.1-§3.3 SOP loop | 元监控 + LLM cost monitoring + CI lint + prompts/risk eval + paper-mode 5d → Gate D |
| PT cutover gate | invoke `quantmind-v3-pt-cutover-gate` skill (件 3) active CC invoke + user 显式 .env paper→live 授权 | Gate E (PT 重启 cutover) |

→ 任 gate 跳跃 → STOP + 反问 user (沿用 LL-098 X10 + Constitution §L8).

---

## §4 三层互补 invocation pattern (Constitution §L6 sustained, 沿用 ADR-022 反 silent overwrite + 反 abstraction premature)

| layer | trigger | scope | 件 |
|---|---|---|---|
| **mechanism** | hook auto invoke | settings.json wire 5 wire types (SessionStart / PreToolUse / PostToolUse / Stop / SessionEnd); CC 0 主动 invoke, hook auto fire | 件 4 (8 hook V3-batch = 4 全新 + 4 现有扩展, V3-specific scope; cumulative 13 ls 真测 含 5 现有 sustained 反 修订 — 沿用 §0.1 legend) |
| **SOP knowledge** | skill active CC invoke | CC 主动 cite skill name + 走 SOP 知识层; sub-PR 起手 / sediment 前 / cite source 锁定 / banned-words check 等 active scenario | 件 3 (13 quantmind-v3-* skill, 全 SOP knowledge layer) |
| **evidence-gathering** | charter independent process spawn | CC invoke charter agent via Agent tool subagent_type → 独立 process 执行 evidence-gathering, 隔离 main session context; cross-source verify / domain audit / sprint orchestration / closure gate evidence 等 evidence-gathering scenario | 件 5 (7 charter, 全 evidence-gathering layer) |

→ 三层 0 重叠 / 0 冲突 (sustained Constitution §L6 + skeleton §3 决议).

---

## §5 user 介入 3 类 enforcement (Constitution §L8 sustained, 沿用 LL-098 X10 反 forward-progress default)

CC autonomous loop limits — sustained user 介入仅 3 类 (反 sprint 收口 / 反 真生产红线触发 / 反 scope 关键决议 之外, CC autonomous):

| 类 | 触发 | 体例 |
|---|---|---|
| (1) **scope 关键决议** | sub-PR scope / sprint scope / Tier A vs Tier B / V3 governance batch closure 等 scope 决议 | CC STOP + 反问 user; user 显式 ack 后 CC 起手 |
| (2) **真生产红线触发** | cash / 持仓 / .env / yaml / DB row mutation 5/5 红线漂移 OR broker call / production code edit 等 mutation | CC STOP + 走 `redline_pretool_block` hook (件 4) auto block + `quantmind-v3-redline-verify` skill (件 3) active 5/5 verify |
| (3) **sprint 收口决议** | sprint 闭前 PASS / FAIL / INCOMPLETE evaluator 输出后 user 决议 next-sprint trigger | CC STOP + 反问 user (沿用 sprint-closure-gate-evaluator charter 件 5 输出 + LL-098 X10) |

→ CC 0 自动 trigger sprint chain progress (反 forward-progress default). 沿用 LL-098 X10 enforce + sustained 串行决议 user 显式 ack 体例累积.

---

## §6 anti-pattern guard 体例 (skill knowledge layer + hook mechanism layer 双层 enforce)

CC sprint 起手前 + sub-PR sediment 前 + reply 出前 必走 anti-pattern guard (走 `quantmind-v3-anti-pattern-guard` skill 件 3 SOP):

| anti-pattern | 反向 | 双层 enforce |
|---|---|---|
| silent overwrite | ADR-022 sustained 反向 | skill SOP + Constitution §L1 cite |
| abstraction premature | ADR-022 sustained 反向 | skill SOP + 沿用现有扩展 体例 (反 全新 hook / file silent 创建) |
| forward-progress default | LL-098 X10 sustained 反向 | skill SOP + sustained 串行决议 user 显式 ack 体例 |
| silent agreeing | LL-103 SOP-4 sustained 反向 | skill SOP + sustained 反问体例 (CC 见解 vs Claude.ai 决议 conflict 时显式 cite + 反对方向) |
| 真+词 / banned (memory #25 HARD BLOCK) | whitelist sustained (5 forms only) | skill `quantmind-v3-banned-words` 件 3 + hook `verify_completion.py` v2 件 4 BANNED_ZHEN_PATTERN regex auto detect |
| cite drift | sustained 4 case 实证累积 | skill `quantmind-v3-cite-source-lock` 件 3 + hook `cite_drift_stop_pretool.py` 件 4 PreToolUse + charter `quantmind-cite-source-verifier` 件 5 cross-source verify |
| prompt 设计 hardcoded 数字/path/command | memory #19/#20 sustained 反向 | skill `quantmind-v3-prompt-design-laws` 件 3 + hook `iron_law_enforce.py` v2 件 4 prompt design detect |

---

## §7 红线 5/5 verify (sustained Constitution §L0.3 step (5) + redline_pretool_block hook 件 4)

CC 任 broker call / .env field change / production yaml change / DB row mutation on production tables / production code edit 前必走 5/5 红线 verify (反 silent fallback):

| 红线 | scope |
|---|---|
| cash | sustained `~993,520` baseline (CC fresh verify via memory frontmatter cite) |
| 持仓 | sustained 0 持仓 baseline (CC fresh verify) |
| LIVE_TRADING_DISABLED | sustained `true` (反 silent flip) |
| EXECUTION_MODE | sustained `paper` (反 silent paper→live without user 显式 .env 授权) |
| QMT_ACCOUNT_ID | sustained `81001102` baseline |

→ 任一漂移 → STOP + 反问 user. 走 `redline_pretool_block` hook (件 4 全新, PR #276 sediment) + `quantmind-v3-redline-verify` skill (件 3) double enforce.

---

## §8 sprint-by-sprint orchestration index (skeleton §2 cite)

V3 sprint chain (Tier A + T1.5 + Tier B + 横切层) sprint-by-sprint orchestration index 沿用 [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) §2 sprint-by-sprint table.

→ CC 实测每 sprint 起手时走 `quantmind-v3-sprint-orchestrator` charter (件 5), charter 返 next-sprint state + invocation recommendation per skeleton §2. **0 hardcoded sprint #** in 本 launch prompt body — sprint 拆分 + sprint-by-sprint task list cite skeleton §2 + V3 spec §12.

---

## §9 cite source 锁定 体例 (skill + hook + charter 三层 enforce, 沿用 4 case 实证累积)

任 cite (数字 / 编号 / 路径 / audit / Constitution / V3 / IRONLAWS / SESSION_PROTOCOL / LL / ADR / 铁律 / skill / hook / charter name) 必含 4 元素:

(a) path (相对 OR 绝对)
(b) line# (单行 OR 范围)
(c) section anchor (e.g. `§L0.3`, `§2.1`)
(d) fresh verify timestamp (CC 真测时 timestamp)

→ skill knowledge: `quantmind-v3-cite-source-lock` SKILL.md (件 3)
→ mechanism: `cite_drift_stop_pretool.py` hook PreToolUse[Edit|Write] + `verify_completion.py` v2 Stop event reminder (件 4)
→ evidence-gathering: `quantmind-cite-source-verifier` charter (件 5) cross-source verify

→ 沿用第 12 项 prompt 升级候选 #1 enforce — Claude.ai cite 任 doc section anchor 必 fresh re-read doc §0 scope declaration verify (反 silent 沿用 cumulative session memory cite section 真值; 4 case 实证累积: PR #281 §L7 reverse + PR #282 §L9 reverse + PR #283 §L0.3/§L5.1/§L6.2 verified positive 1 + PR #284 §L6.2 verified positive 2).

---

## §10 sediment cite trail 体例 (沿用 LL-132 候选 cumulative 真值 augmented)

每 sub-PR sediment 必走 (沿用 PR #282/#283/#284 三 PR 实证累积):

| 步 | 动作 |
|---|---|
| (1) pre-push smoke baseline 真值 fresh verify | 反 silent 沿用 cumulative cite "55 PASS / 2 skipped" baseline; CC fresh `pytest` 真测 |
| (2) push 路径决议 | sustained Q3 (a) `--no-verify` + 4 元素 reason cite OR fresh decision (基于 smoke baseline 真值 + work scope overlap verify) |
| (3) post-wire fire test | hook sediment 性质 ~3-4 min immediate; doc-only sediment 反 fire test (件 6 性质) |
| (4) memory handoff sediment | 沿用铁律 37 — sub-PR 闭后 prepend memory `project_sprint_state.md` |
| (5) STATUS_REPORT 输出 | sustained PR cumulative 体例 (sub_pr branch + main HEAD pre/post + PR # + reviewer agent + AI self-merge cycle + chunked SOP target vs 实测 + 红线 5/5 sustained verify + sediment cite + LL/ADR candidate 状态) |

---

## §11 sprint chain 起手实操 example (CC 实测决议 sprint 拆分时参考)

> **本 §11 = example reference only**. 反 hardcoded sprint #. 沿用 skeleton §0.2 line 33 + memory #19/#20 — CC sprint 起手时实测决议 sub-PR 拆分.

CC 起手时:

(1) **fresh re-read 8 doc** → 走 `quantmind-v3-fresh-read-sop` skill (件 3)
(2) **6 件套 cumulative verify** → 走 §1 cumulative truth verify
(3) **invoke sprint orchestrator** → `quantmind-v3-sprint-orchestrator` charter (件 5) via Agent tool, charter 返 next-sprint state + invocation recommendation
(4) **sub-PR 拆分决议** → CC 实测 sprint scope + LL-100 chunked SOP target + LL-117 atomic sediment+wire 体例
(5) **sub-PR sediment+wire** → 沿用 §3.2 atomic 体例 (commit + push + PR + reviewer + AI self-merge + memory handoff)
(6) **sprint 收口** → invoke `quantmind-v3-sprint-closure-gate-evaluator` charter (件 5)
(7) **next sprint trigger OR sprint-replan OR user 决议** → sustained §3.3 outcome branch + LL-098 X10

---

## §12 关联 ADR / LL / 铁律 (cumulative cite, 反 stale; 沿用第 11 项 prompt 升级 + LL-105 SOP-6)

> **freshness audit cite** (P3 #2 fix): cumulative cite, fresh verify 2026-05-09 via LL-105 SOP-6 cross-verify against `docs/adr/REGISTRY.md` (ADR-019/020/021/022/027/028/031/032/036/037/042 committed) + `IRONLAWS.md` (铁律 1-45 sustained, 含 45 = 4 doc fresh read SOP enforcement, ADR-037 backref) + `LESSONS_LEARNED.md` (LL-098/100/101/103/104/105/106/115/116 committed; LL-117/119-134 候选 sustained, V3 governance batch closure 时 promote).

- ADR-022 (反 silent overwrite + 反 abstraction premature + 集中机制)
- ADR-037 + 铁律 45 (4 doc fresh read SOP + cite source 锁定)
- ADR-019/020/021/027/028/031/032 + V3 governance batch closure 后续 ADR (V3 spec sediment cumulative)
- LL-098 X10 (反 forward-progress default)
- LL-100 (chunked SOP target)
- LL-101 (cite 数字 SQL/git/log 真测 verify)
- LL-103 SOP-4 + LL-104 (Claude.ai vs CC cross-verify) — 第 8/9/10/11 + 第 12 项候选 #1 prompt 升级 sustained
- LL-105 SOP-6 (LL # / ADR # registry SSOT cross-verify)
- LL-115 (Phase 0 active discovery enforcement)
- LL-116 (Claude.ai cite 必经 SQL/git/grep 真测 verify)
- LL-117 候选 (atomic sediment+wire) — promote trigger sustained 满足 (6 PR 实证累积; V3 governance batch closure 时 promote)
- LL-119 候选 #1-#7 cumulative (跨 PR + file-level + cross-row drift)
- LL-120-LL-126 候选 cumulative
- LL-127 候选 (drift rate multi-method sensitivity SOP)
- LL-128 候选 (charter file internal cite inconsistency governance) — 4 case 实证累积
- LL-129 候选 (borrow OMC extend cite delta only governance)
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance)
- LL-131 候选 (hook + skill 紧耦合 1 PR sediment 体例)
- LL-132 候选 (pre-push smoke baseline drift detection — 真值 augmented; 3 PR 实证累积)
- LL-133 候选 (现有 hook v1→v2 lifecycle governance) — promote trigger sustained 满足 (双 case 实证累积)
- LL-134 候选 (Q5 路径假设 vs 实测真值修正)
- ADR-DRAFT row 11-27 候选 cumulative
- 铁律 1-45 sustained (沿用 IRONLAWS.md SSOT)
- 铁律 37 (sub-PR 闭后 memory handoff sediment)
- 铁律 44 X9 (Beat schedule 注释 ≠ 停服)
- CLAUDE.md governance "user explicitly asked" (`--no-verify` push 路径 4 元素 reason cite)
- memory #19/#20 (prompt 设计 0 数字 path command, broader 47/53+ enforcement)
- memory #25 HARD BLOCK (真+词 whitelist 5 forms)

---

## §13 V3 closure 后 trigger (沿用 Constitution §L0.2 + §L10)

V3 closure 完成 = 5 大 gate 全 ✅ (Gate A + B + C + D + E sustained §2). post-V3 closure trigger:

| trigger | 动作 |
|---|---|
| Gate E ✅ (PT cutover) | user 显式 .env paper→live 授权 → PT 重启 (sustained Constitution §L10.5) |
| post-PT 重启 | sustained 元监控 + LLM cost monitoring 持续 ≥3 month ≤80% baseline (Gate D 持续 verify) |
| V3 governance batch closure 后续 | LL/ADR governance debt closure (沿用 PR #284 sediment cumulative ~30 项 candidate batch promote) |

→ **post-V3 closure CC 0 自动 trigger 任一 V4 / 后续 sprint** (沿用 LL-098 X10 + Constitution §L8 sustained user 显式 ack 体例).

---

**本文件版本**: v0.1 (initial sediment, 2026-05-09, V3 6 件套 件 6 closure → V3 6 件套 6/6 = 100% 完整闭环 ✅)

**关联 sub-PR**: PR step 6 sediment (sustained PR cumulative #270-#284 体例累积; 6 件套 progress: 件 1+2+3+4+5+6 全 closed; V3 governance batch closure 启动 trigger sustained 满足 prerequisite)
