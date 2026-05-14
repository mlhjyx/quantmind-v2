# ADR-075: V3 横切层 HC-3 Closure — CI lint verify-only + prompts/risk eval iteration ≥1 round

**Status**: Accepted
**Date**: 2026-05-14
**Context**: Session 53+31, V3 横切层 Plan v0.3 §A HC-3 sprint closure (Gate D item 3 + 4)
**Related**: ADR-020 (Claude 边界 + LiteLLM 路由 + CI lint) / ADR-031 (`check_anthropic_imports.py` → `check_llm_imports.sh` path 决议) / ADR-032 (S4 caller code _internal/ bypass scan) / ADR-036 (V4-Flash→V4-Pro model routing SSOT) / ADR-072 D2 (cost decision DEFER — 0-traffic precondition) / ADR-063 (paper-mode deferral pattern) / ADR-073 (HC-1 closure) / ADR-074 (HC-2 closure) / LL-098 X10 / LL-100 (chunked SOP) / LL-166 (HC-1 closure 体例) / LL-167 (HC-2 closure 体例 — scope-balloon 2nd-consecutive) / LL-168 (本 HC-3 closure 体例 — estimate-held + verify-surfaced-RED + paper-mode-structural-eval)

---

## §1 Context

V3 横切层 Plan v0.3 §A HC-3 = Gate D item 3 (CI lint verify-only) + item 4 (prompts/risk eval iteration ≥1 round). HC-3 chunked **2 sub-PR** (HC-3a + HC-3b) — **planned 2, actual 2: 0 balloon** (反 HC-1 3→5 + HC-2 3→5 双 consecutive balloon — LL-167 lesson 1; HC-3's estimate held because both items were "verify/audit-heavy doc deliverables on already-closed infra", NOT net-new wiring).

红线 5/5 sustained throughout: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

---

## §2 Decision

### D1 — HC-3a: V3 §17.1 CI lint verify-only (5 components production-active) + CRLF Finding fix

V3 §17.1 CI lint (禁直接 import anthropic/openai, only path = LiteLLMRouter) 已 substantially closed in Tier A (ADR-020 + ADR-032). HC-3a = **verify-only** confirm 5 components production-active (NOT 重建): `scripts/check_llm_imports.sh` (2-round S6+S4 scan, `--full` exit 0) / `config/hooks/pre-push` + `config/hooks/pre-commit` (integrate the script) / `backend/tests/test_llm_import_block_governance.py` / `docs/LLM_IMPORT_POLICY.md`. `git config core.hooksPath` = `config/hooks` 真生产激活.

**HC-3a Finding [type a — verify-surfaced RED]**: `scripts/check_llm_imports.sh` + `config/hooks/pre-commit` had **CRLF line endings** with no `.gitattributes` `eol=lf` protection (only `pre-push` was protected). Consequence: `test_llm_import_block_governance.py` was **8/10 RED on main `0165915`** — its `subprocess.run(["bash", ...])` hits `syntax error near unexpected token $'in\r'`. Production hooks worked (git runs hooks via tolerant `sh`); strict `bash` in the test did not. NOT in the session prompt's known-pre-existing-fail note. **Fix** (user 决议 A — AskUserQuestion 1 round, HC-3a 内修): `.gitattributes` add `*.sh text eol=lf` (glob — future-regression guard) + `config/hooks/pre-commit text eol=lf` + working-tree renormalize → governance test **8/10 RED → 10/10 GREEN**. spec path drift 真值 (sustained Constitution §L10.1 item 7 + ADR-031 §6): V3 §17.1 cites `check_anthropic_imports.py` — pre-ADR-031, 真值 = `scripts/check_llm_imports.sh`.

### D2 — HC-3b: prompts/risk eval iteration ≥1 round = structural baseline eval (paper-mode 0-traffic)

prompts/risk = **5 YAML** (`news_classifier_v1` / `bull_agent_v1` / `bear_agent_v1` / `regime_judge_v1` / `reflector_v1` — fresh-verified `prompts/risk/`, matches Plan v0.3 §A HC-3b). HC-3b 走 `quantmind-v3-prompt-eval-iteration` skill 5-step methodology.

**eval scope decision** (user 决议 A, AskUserQuestion 1 round): paper-mode (`LIVE_TRADING_DISABLED=true` / 0 持仓) has **0 production traffic** → the skill §4 routing triggers (cost-driven: sustained 月成本 vs V3 §16.2 上限; quality-driven: paper-mode 5d false-positive/negative) **cannot fire** — same 0-traffic precondition ADR-072 D2 already used to DEFER the LiteLLM cost decision. eval ≥1 round = **structural baseline eval** (NOT live-LLM fixture run): per-prompt JSON-schema completeness / 行为约束 edge-case coverage / user_template placeholder ↔ caller match / model routing ↔ ADR-036 SSOT. Result: **5/5 prompts structurally sound, 0 defect, 0 iteration needed** (drift-driven trigger also did not fire — 0 prompt-content cross-system cite drift). live-LLM fixture run + paper-mode 5d shadow eval **DEFERRED** to Gate E / post-cutover traffic (sustained ADR-072 D2 + ADR-063, honest-disclosure per 铁律 28 — DEFERRED ≠ skipped).

### D3 — V4-Flash/V4-Pro routing 决议: 5 prompts sustained 起手 model per ADR-036

**决议: 0 routing change.** All 5 prompts sustained 起手 model — `news_classifier` V4-Flash; `bull_agent` / `bear_agent` / `regime_judge` / `reflector` V4-Pro — verified 100% match `router.py:109-116 TASK_TO_MODEL_ALIAS` SSOT (`NEWS_CLASSIFY: deepseek-v4-flash` / `BULL_AGENT` / `BEAR_AGENT` / `JUDGE` / `RISK_REFLECTOR: deepseek-v4-pro`). cost-driven + quality-driven routing re-eval **DEFERRED to Gate E** (paper-mode 5d) / post-cutover traffic accumulation — the routing triggers are all traffic-dependent and there is 0 traffic. This IS a routing 决议 (sustained ADR-036 + DEFER with reasoning on record), NOT a vacuous TBD (sustained ADR-071 D4 honest-scope 体例).

### D4 — HC-3 estimate held (0 balloon) — 反 HC-1/HC-2 双 consecutive 3→5

HC-1 ballooned 3→5 (ADR-073), HC-2 ballooned 3→5 (ADR-074) — LL-167 lesson 1 flagged the 2-consecutive pattern as structural evidence the 横切层 plan's per-sprint estimate runs low. **HC-3 held at planned 2 sub-PR.** Root cause of the difference: HC-1/HC-2 involved net-new wiring (alert-on-alert layer / failure-mode detection+degrade paths) where precondition 核 kept surfacing under-estimation; HC-3's both items were **verify/audit-heavy doc deliverables on already-closed infra** (CI lint = ADR-020/032 closed; prompts = 5 YAML already sediment in S3/TB-2/TB-4). Verify-heavy sub-PRs estimate accurately; net-new-wiring sub-PRs balloon. (LL-168 lesson.)

### D5 — `quantmind-v3-prompt-eval-iteration` skill §2 prompt-scope table stale (HC-3b Finding)

skill §2 cites `bull_bear_v1.yaml` (2 prompt) + `rag_retrieval_v1.yaml` + `reflector_v1.yaml`. Fresh verify: actual `prompts/risk/` = `news_classifier` + `bull_agent` + `bear_agent` + `regime_judge` + `reflector` (5 files, matches Plan v0.3 §A). The skill table is pre-TB-2/TB-3 stale (Bull/Bear debate ended up as 3 separate agent prompts bull/bear/judge; RAG retrieval used BGE-M3 embedding — NO prompt yaml). **决议**: HC-3b eval scope = the 5 actual files (Plan §A truth); skill §2 amend 留 future skill-maintenance cycle (sustained ADR-022 反 retroactive — Finding recorded here).

---

## §3 Consequences

### §3.1 HC-3 2 sub-PR cumulative

| sub-PR | PR | scope |
|---|---|---|
| HC-3a | #359 `2716af4` | V3 §17.1 CI lint 5-component verify-only report + CRLF fix (`.gitattributes` `*.sh` + `pre-commit` `eol=lf`; governance test 8/10 RED → 10/10 GREEN) |
| HC-3b | 本 (docs-only 直 push, 铁律 42) | prompts/risk eval iteration ≥1 round structural baseline (5 YAML) + V4-Flash/V4-Pro routing 决议 (sustained + DEFER) + ADR-075 + LL-168 + REGISTRY + Plan §A HC-3 amend |

Reviewer 2nd-set-of-eyes: HC-3a `oh-my-claudecode:code-reviewer` APPROVE (0 CRITICAL/HIGH, 3 report-precision nits, MEDIUM + 1 LOW applied — reviewer independently re-verified all report claims). HC-3b = docs-only closure sediment 直 push (铁律 42, sustained HC-1c 体例 — no reviewer agent for docs-only closure sediment).

### §3.2 HC-3 closed — Gate D item 3 + 4 code-side complete

Gate D item 3 (CI lint verify-only): 5 components confirmed production-active, governance test green. Gate D item 4 (prompts/risk eval ≥1 round): structural baseline eval complete, 5/5 prompts sound, routing 决议 locked. **Gate D item 3 + 4 formal verify 留 HC-4c** (sustained Plan v0.3 §C — Gate D formal close = HC-4c, NOT per-sprint HC-3b).

### §3.3 横切层 sprint chain status post-HC-3

HC-1 ✅ closed (ADR-073) + HC-2 ✅ closed (ADR-074) + **HC-3 ✅ closed (本 ADR-075)** / HC-4 ⏳ (Gate D formal close + 5y replay long-tail acceptance + north_flow/iv wire + carried deferral 路由 + ROADMAP sediment). 横切层 = 3/4 sprint closed.

### §3.4 横切层 期 ADR cumulative

ADR-072 (Plan v0.3 3 决议 lock) + ADR-073 (HC-1 closure) + ADR-074 (HC-2 closure) + **ADR-075 (本 — HC-3 closure)** + ADR-076 (HC-4 + Gate D formal close) reserved.

---

## §4 Cite

- [Plan v0.3 §A HC-3a + HC-3b rows](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (HC-3 sprint plan + closure blockquote)
- [Plan v0.3 §C](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (Gate D criteria — item 3 + 4 formal verify 留 HC-4c)
- [HC-3a CI lint verify report](../audit/v3_hc_3a_ci_lint_verify_report_2026_05_14.md)
- [HC-3b prompts/risk eval report](../audit/v3_hc_3b_prompts_risk_eval_report_2026_05_14.md)
- [ADR-036](ADR-036-bull-bear-agent-mapping-v4-flash-to-v4-pro.md) (V4-Flash→V4-Pro model routing SSOT — 5/5 prompts verified match)
- [ADR-072](ADR-072-v3-crosscutting-plan-v0-3-3-decisions-lock.md) (Plan v0.3 3 决议 lock; D2 cost-decision DEFER 0-traffic precondition — HC-3b routing 决议 sustains)
- [ADR-073](ADR-073-v3-hc-1-meta-alert-closure.md) (HC-1 closure) / [ADR-074](ADR-074-v3-hc-2-failure-mode-closure.md) (HC-2 closure)
- [LL-168](../../LESSONS_LEARNED.md) (HC-3 closure 体例 — estimate-held vs HC-1/HC-2 balloon + verify-surfaced-RED + paper-mode-structural-eval + skill-scope-table-stale)
- HC-3 PR #359 (HC-3a); HC-3b docs-only 直 push

### Related ADR

- [ADR-022](ADR-022-anti-anti-pattern-集中修订机制.md) (反 retroactive content edit — Plan §A append-only amend + skill §2 amend 留 future cycle)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (paper-mode deferral pattern — live-LLM eval DEFERRED 沿用)
- [ADR-071](ADR-071-v3-tier-b-closure-gate-bc-formal-close.md) (D4 honest-scope 体例 — DEFERRED-with-reasoning ≠ INCOMPLETE)
