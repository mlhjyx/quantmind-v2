# SKILL_ROUTING — 自主调用决议表 (CC 沿用)

**SSOT**: 本文件 = QuantMind V2 真**curated skill allowlist + 触发条件 SOP** sustained.

**真**目的** sustained: 反 400+ skill 真 noise + 反**反 efficient 1% threshold** judgment, 真**只扫本表 curated subset** sustained 真**autonomy invocation 沿用 trigger 条件 SOP** sustained.

**真**触发协议** sustained:
1. 每次 user prompt 起手前 — CC 真扫**本表 trigger 条件** sustained
2. 任一 trigger match → CC 真自主 `Skill` tool invoke (反 ask user)
3. trigger 0 match → 沿用现 sub-PR Phase 0/1/2/3/4 framework 体例 sustained

**真**沿用 governance** sustained:
- 沿用 `using-superpowers` skill 真**1% threshold** rule (本表 = 1% 沉淀真值)
- 沿用 LL-098 X10 forward-progress 边界 sustained — invoke skill 真**reactive 反 proactive offer**
- 沿用 IRONLAWS 铁律 45 + ADR-037 + SOP-7 真生产 enforcement 体例 sustained

---

## Tier 0 — 流程基础 (always-on 沿用 SessionStart enforce)

| Skill | 触发 | 真用 |
|---|---|---|
| `superpowers:using-superpowers` | session start | 真**沿用 1% threshold rule** sustained, 真**本 SKILL_ROUTING 真扩展** sustained |
| `mattpocock-skills:git-guardrails` | already setup as PreToolUse hook | 真**层 2 防御** sustained 红线 sustained 5/5 (git push / reset --hard / clean -fd / branch -D / checkout . / restore .) |

---

## Tier 1 — 高价值任务触发 (Python+PG+LLM 真生产场景)

### Code review / quality

| Skill | 触发条件 (CC 沿用 keyword + context match) | 真用 cite |
|---|---|---|
| `everything-claude-code:python-review` | 真**Python code change PR** 起手前 (含 `.py` Edit/Write tool, 真 reviewer 第二把尺子 LL-067 体例 sustained) | code-reviewer subagent 真**互补** sustained Python-specific |
| `code-review:code-review` | 真**PR review** task / user 显式 "review this PR" / sub-PR merge 前 | 沿用 sub-PR 7b stack reviewer 体例 sustained |
| `everything-claude-code:postgres-patterns` | 真 SQL / migration / DDL 真生产 (e.g. `backend/migrations/*.sql` Edit, query optimization) | 真**沿用 sub-PR 7b.1 v2 + 7c news_raw INSERT 体例** sustained |
| `everything-claude-code:database-migrations` | 真**新 migration file create / DDL change** | 真**沿用 sub-PR 7b.1 v2 #240 体例** sustained |
| `everything-claude-code:security-review` | 真**user input / auth / API endpoint / sensitive data** 处理代码 | OWASP Top 10 + secrets sustained |
| `everything-claude-code:python-testing` | 真**新 test file create + TDD 真生产** | 真**沿用 sub-PR 7b stack 13-58 mock + e2e 真生产体例** sustained |

### Architecture / planning

| Skill | 触发条件 | 真用 cite |
|---|---|---|
| `everything-claude-code:architecture-decision-records` | 真**新 ADR create / 大架构决议** sediment | 真**沿用 ADR-031 §6 + ADR-032 + ADR-035 + ADR-036 + ADR-037 体例** sustained |
| `everything-claude-code:context-budget` | 真**长 session 真 context 跑高** OR user 显式 "audit context" | 真**stale context cleanup 体例** sustained |
| `everything-claude-code:strategic-compact` | 真 session ≥ 200K tokens / 真 phase shift | 真**手工 compact** sustained 反**自动 compact 漂移** |

### LLM-specific

| Skill | 触发条件 | 真用 cite |
|---|---|---|
| `everything-claude-code:claude-api` | 真**Claude API / Anthropic SDK** 真生产 (反 LiteLLM router, e.g. 直 Anthropic SDK call) | 真**反触本项目 LLM 路由层** sustained ADR-031 §6 sustained — **0 触发** sustained 沿用 V4 路由层 0 智谱 + DeepSeek + Ollama sustained |
| `everything-claude-code:cost-aware-llm-pipeline` | 真**LLM cost optimization plan** task (e.g. routing tier / budget threshold review) | 真**沿用 V3§20.1 #6 $50/月 budget cap + ADR-031 §6 灾备 sustained** |

### Mattpocock 条件触发

| Skill | 触发条件 | 真用 cite |
|---|---|---|
| `mattpocock-skills:diagnose` | 真**bug 触发** (test fail / perf regression / unexpected exception / "diagnose this" / "debug this" / "broken" / "throwing") | 真**6 phase loop sustained**: feedback loop → reproduce → 3-5 hypotheses → instrument → fix + regression → cleanup |
| `mattpocock-skills:grill-with-docs` | 真**新 Sprint 起手前 OR 大 plan stress-test** (反 sub-PR cycle 内, 真 Sprint level cross-check V3 / IRONLAWS / ADR domain glossary) | 真**一题一答 grill** sustained — **反 silent invoke** sustained per skill spec |

### Superpowers 流程辅助

| Skill | 触发条件 | 真用 cite |
|---|---|---|
| `superpowers:test-driven-development` | 真**TDD task user 显式触发** OR sub-PR 起手 implementation 前 | 真**沿用 sub-PR 7b 体例 mock-only test 真生产 + reviewer P2 fix add test** sustained |
| `superpowers:verification-before-completion` | 真**claim "complete" / "fixed" / "passing" 前** | 真**沿用 LL-067 reviewer 第二把尺子 + LL-104 cross-verify 体例** sustained |
| `superpowers:requesting-code-review` | 真**sub-PR push 前** | 真**沿用 sub-PR 7b stack reviewer 体例** sustained |
| `superpowers:systematic-debugging` | 真**bug 触发** (替代 mattpocock-skills:diagnose 候选) | 真**反重复 mattpocock-skills:diagnose** sustained — **优先 mattpocock-skills:diagnose** 沿用真 6 phase loop 真完整 sediment |

---

## Tier 2 — 流程辅助 (低频触发)

| Skill | 触发条件 | 真用 cite |
|---|---|---|
| `commit-commands:commit` | user 显式 "commit" / sub-PR 完成 真 commit 前 | 真**沿用现 git commit + pre-commit hook 体例** sustained, 真**反 silent invoke** sustained |
| `everything-claude-code:codebase-onboarding` | 真**新 contributor / 真 re-onboard** | 真**反真当前** sustained — 沿用 audit Week 2 batch sediment 候选 |
| `everything-claude-code:plankton-code-quality` | 真**write-time auto-format / lint** | 真**沿用现 ruff + post_edit_lint.py hook 体例** sustained, 真**反 invoke** sustained |
| `mattpocock-skills:write-a-skill` | 真**audit Week 2 batch sediment 真**封装现 sub-PR 体例 (Phase 0/1/2/3/4 framework + 真讽刺案例 #4-#13 候选 cumulative lesson) 进 reusable skill** sustained 真**Sprint 3 完结时**真生效价值最大化 sustained | 真**audit Week 2 batch sediment 候选** sustained |

---

## Tier 3 — 反真生产 scope (反触发)

- `design:*` — 反 UX/Figma 真当前 scope 真生产
- `pdf-viewer:*` — 反 PDF 真生产 scope
- `productivity:*` — 反 Asana/Linear/Notion 真生产 toolset
- `everything-claude-code:android-*` / `kotlin-*` / `cpp-*` / `go-*` / `rust-*` / `springboot-*` / `laravel-*` / `django-*` / `swift-*` — Python-only 项目, **0 重叠** sustained
- `everything-claude-code:fal-ai-media` / `videodb` / `slack-gif-creator` — 反 media/video 真生产
- `everything-claude-code:nutrient-document-processing` / `visa-doc-translate` — 反 document 真生产
- `everything-claude-code:carrier-relationship-management` / `customs-trade-compliance` / `energy-procurement` / `inventory-demand-planning` / `logistics-exception-management` / `production-scheduling` / `quality-nonconformance` / `returns-reverse-logistics` — 反 enterprise B2B operations 真生产
- `mattpocock-skills:zoom-out` — metadata `disable-model-invocation: true` 真**禁** model 自主 invoke sustained
- `mattpocock-skills:grill-me` — 跟 sub-PR Phase 1 (b) STOP push back SOP **完全重叠** sustained
- `pdf-viewer:*` / `claude-md-management:*` (Tier 4 governance only)

---

## 真自主调用 SOP (CC 沿用)

### 起手前真扫

```
对每条 user prompt:
1. extract task type (code change / SQL / migration / bug / planning / ADR / etc.)
2. scan Tier 1 trigger 条件 — match? → 自主 Skill invoke
3. scan Tier 2 trigger 条件 — explicit user mention? → 自主 Skill invoke
4. Tier 3 全 skip sustained
5. 反 match → 沿用 sub-PR Phase 0/1/2/3/4 framework 体例 sustained
```

### 真生效 invoke 体例 (沿用 `using-superpowers` skill spec sustained)

```
Skill tool invoke (sustained):
  skill="<plugin>:<name>"  # e.g. "everything-claude-code:python-review"
  args=""  # optional skill-specific args
```

### 真**反 silent invoke** triggers (沿用 LL-098 X10 sustained)

- `mattpocock-skills:grill-with-docs` — 一题一答 grill 真**反 silent 走** sustained
- `mattpocock-skills:grill-me` — 沿用同 spec, **反 silent 走** sustained
- `mattpocock-skills:zoom-out` — `disable-model-invocation: true` 真**禁 model 自主** sustained
- `commit-commands:commit` / `commit-commands:commit-push-pr` — git push 真**真生效真生产 governance change** sustained, 沿用 git-guardrails block + LL-098 X10 sustained 真**等 user 显式触发** sustained

---

## 维护 SOP

- 真**新 skill** 添加 — 真**先评估 Tier (1/2/3)** + cite source 锁定真值 sustained
- 真**触发条件 drift** — sediment 真讽刺案例 #N 候选 + 真生效更新本表 sustained 沿用 audit Week 2 batch sediment 候选 sustained
- 真**Tier 3 skill 真生效价值跃升** (e.g. Python → 多 lang 项目) — 真**reframe Tier sustained** sustained

---

## 真讽刺案例 #13 候选 sediment cite source 锁定真值 sustained

`mattpocock-skills:git-guardrails` 真 bundled `block-dangerous-git.sh` 真**bash + jq dependency** sustained, Windows Git Bash 真**0 jq** 真**silent fail exit 0** sustained 真**反真生效层 2 防御** sustained.

**修订 path**: 新创 `.claude/hooks/block_dangerous_git.py` (Python stdlib only, 沿用现 5 Python hook 体例 sustained), settings.json 真**改 Python wrapper 反 bash + jq dependency** sustained, 真**保留 skill bundled `.sh` pristine** 沿用真讽刺案例 #6 "候选" qualifier 反豁免 lesson 真应用 sustained.

**真讽刺**: skill 真**bundled script 真**Linux/Mac 假设** sustained 真**Windows 反真生效** sustained — 真讽刺案例 #13 候选 sustained, sediment audit Week 2 batch sediment 候选 LL-107 候选 sustained.

**真生效 verify**: 7/7 test PASS (5 BLOCK + 2 PASS) sustained 真**层 2 防御 真生效** sustained 5-07 ~02:30 UTC.
