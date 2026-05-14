# V3 prompts/risk Eval Iteration Report — HC-3b (横切层 Gate D item 4)

> **本文件 = V3 横切层 Plan v0.3 §A HC-3b deliverable** — prompts/risk 5-YAML eval
> iteration ≥1 round (structural baseline) + V4-Flash/V4-Pro routing 决议. HC-3b 走
> `quantmind-v3-prompt-eval-iteration` skill (5-step eval methodology).
>
> **Status**: HC-3b sediment (docs-only 直 push 铁律 42) — HC-3 sprint closure (HC-3a
> CI lint verify + HC-3b prompts eval = HC-3 chunked 2 sub-PR, **planned 2, actual 2 —
> 0 balloon**, 反 HC-1/HC-2 双 3→5 balloon).
>
> **eval scope decision** (user 决议 A, AskUserQuestion 1 round): paper-mode 0
> production traffic → skill §4 routing triggers (cost-driven sustained 月成本 /
> quality-driven paper-mode 5d false-positive/negative) **cannot fire** (sustained
> ADR-072 D2 — LiteLLM cost decision already DEFERRED for the same 0-traffic
> precondition). eval ≥1 round = **structural baseline eval** (NOT live-LLM fixture
> run): per-prompt schema completeness / 行为约束 edge-case coverage / user_template
> placeholder ↔ caller match / model routing ↔ ADR-036 SSOT match.
>
> **Date**: 2026-05-14 (Session 53+31)
>
> **关联**: Plan v0.3 §A HC-3b row + §C Gate D item 4 / `quantmind-v3-prompt-eval-iteration`
> skill (5-step methodology) / V3 §3.2 (NewsClassifier) + §5.3 (Bull/Bear/Judge) + §8
> (RiskReflector) / ADR-036 (V4-Flash→V4-Pro model routing SSOT) / ADR-072 D2 (cost
> decision DEFER, 0-traffic precondition) / ADR-063 (paper-mode deferral pattern) /
> ADR-075 (HC-3 closure) / 铁律 36 (precondition 核) / 铁律 45 (cite fresh verify)

---

## §1 Eval Methodology (沿用 `quantmind-v3-prompt-eval-iteration` skill §3, paper-mode adapted)

skill §3 5-step methodology, adapted for paper-mode 0-traffic:

| step | skill §3 SSOT | HC-3b 实施 (paper-mode) |
|---|---|---|
| (1) baseline 锁定 | 起手 prompt + V4 model + 合成场景 fixture baseline | 5 prompt yaml v1 fresh-read + 起手 model per ADR-036 (§2 matrix) |
| (2) iteration trigger 类型 | drift / cost-driven / quality-driven | **0 trigger fired** — drift: 0 cross-system cite drift on prompt content; cost-driven: 0 月成本 data (paper-mode 0 traffic); quality-driven: 0 paper-mode 5d false-positive/negative data (5d dry-run not run) |
| (3) iteration scope 锁定 | 仅改 prompt yaml / 仅改 model / 双改 | **0 iteration** — no trigger fired → 5 prompts sustained v1, 0 yaml change, 0 model change |
| (4) eval ≥1 round | 合成场景 fixture + 实际 News raw fixture + paper-mode 5d shadow eval | **structural baseline eval** (user 决议 A) — live-LLM fixture run + paper-mode 5d shadow both gated on production traffic (DEFERRED); structural round = §2 matrix |
| (5) ADR sediment | iteration 决议 ADR promote | **ADR-075** (HC-3 closure — CI lint verify-only + prompts/risk eval iteration; routing 决议 lock) |

**真值 disclosure** (铁律 28): step (4)'s live-LLM fixture run + paper-mode 5d shadow
eval are **DEFERRED** — not skipped. They require production traffic (cost data
accumulation / 5d dry-run false-positive集) that 0-traffic paper-mode cannot provide.
The structural baseline eval (§2) is a legitimate ≥1 round — it applies the methodology
to all 5 prompts and produces per-prompt findings — but it does NOT exercise live LLM
output quality. Live eval re-route 留 Gate E (paper-mode 5d) / post-cutover traffic
(sustained ADR-072 D2 + ADR-063 deferral pattern).

---

## §2 5-Prompt Structural Baseline Matrix

每 prompt: schema completeness / 行为约束 edge-case coverage / user_template placeholder
↔ caller match / model routing ↔ ADR-036 SSOT. status ✅ = structurally sound.

| prompt yaml | 起手 model | routing ↔ ADR-036 SSOT | JSON schema completeness | 行为约束 edge-case coverage | user_template placeholder ↔ caller | status |
|---|---|---|---|---|---|---|
| `news_classifier_v1.yaml` | V4-Flash | ✅ `NEWS_CLASSIFY: deepseek-v4-flash` (router.py:110) | ✅ 6 fields (sentiment_score [-1,1] / category 4-enum / urgency P0-P3 / confidence [0,1] / profile 4-enum / rationale optional ≤200字) — aligns news_classified DDL CHECK (sub-PR 7b.1 v2 #240) | ✅ 信息不足 → confidence ≤0.4 + sentiment≈0 反猜测; 重大事件 → category=事件驱动 + urgency≥P1; 中文新闻沿用中文 enum | ✅ 7 placeholders (source/timestamp/title/content/url/symbol_id/lang) — filled by `news_classifier_service.py` (TB-era; covered by news classifier mock-LLM tests) | ✅ |
| `bull_agent_v1.yaml` | V4-Pro | ✅ `BULL_AGENT: deepseek-v4-pro` (router.py:112) | ✅ `arguments` array 正好 3 (argument ≤80字 / evidence ≤80字 / weight [0,1]) — aligns RegimeArgument dataclass (interface.py) | ✅ data unavailable (None field) → 论据侧重 available + weight 降低; 反编造数据 / 反重复论据 / 反跟 Bear 互文 | ✅ 6 placeholders (timestamp/sse_return/hs300_return/breadth_up/breadth_down/north_flow_cny/iv_50etf — MarketIndicators 5维) — filled by `regime/agents.py` (TB-2b; covered by `test_market_regime_service.py` mock-LLM) | ✅ |
| `bear_agent_v1.yaml` | V4-Pro | ✅ `BEAR_AGENT: deepseek-v4-pro` (router.py:113) | ✅ symmetric with bull_agent — `arguments` 正好 3 (same schema) | ✅ symmetric — data unavailable → weight 降低; 反编造 / 反重复 / 反跟 Bull 互文 (debate symmetry sustained) | ✅ same 6 placeholders as bull_agent — filled by `regime/agents.py` | ✅ |
| `regime_judge_v1.yaml` | V4-Pro | ✅ `JUDGE: deepseek-v4-pro` (router.py:115) | ✅ 3 fields (regime 4-enum Bull/Bear/Neutral/Transitioning / confidence [0,1] / reasoning ≤300字) — aligns market_regime_log DDL CHECK + MarketRegime dataclass | ✅ data unavailable 多 → regime 倾向 Neutral/Transitioning + confidence 降低; 反编造论据 / 反创造新论据 (只加权) | ✅ placeholders incl 6维 indicators + `{bull_arguments}` + `{bear_arguments}` JSON — filled by `regime/agents.py` Judge | ✅ |
| `reflector_v1.yaml` | V4-Pro | ✅ `RISK_REFLECTOR: deepseek-v4-pro` (router.py:116) | ✅ overall_summary ≤300字 + reflections{5维 each summary/findings/candidates} — aligns V3 §8.1 line 927-933 5维 + ReflectionOutput dataclass | ✅ empty-week (0 events/plans/P&L) → 各维 summary 标注"数据不足待下周期" + findings/candidates 空 list; 反 hindsight bias; 反 hallucinate 漏报; candidates 仅 enumerate 反自动 commit (ADR-022) | ✅ placeholders (period_label/period_start/period_end/events_summary/plans_summary/pnl_outcome/rag_top5) — filled by RiskReflectorAgent (TB-4a; covered by `test_reflector_agent_skeleton.py` mock-LLM) | ✅ |

**Matrix 真值小结**: 5/5 prompts structurally sound — all `version: "v1"`, well-formed
(description + system_prompt + user_template), strict-JSON schema complete + aligned to
the consuming DDL/dataclass, 行为约束 covers the edge cases the caller code expects
(notably the empty/None-data degradation paths), model routing 100% matches ADR-036
`TASK_TO_MODEL_ALIAS` SSOT. **0 structural defect found** — 0 iteration needed.

注: per `quantmind-v3-prompt-eval-iteration` skill §2, the skill's own prompt-scope
table is stale (cites `bull_bear_v1.yaml` + `rag_retrieval_v1.yaml` — pre-TB-2/TB-3:
Bull/Bear became 3 separate agent prompts bull/bear/judge; RAG retrieval used BGE-M3
embedding, NO prompt yaml). Eval scope = the 5 actual files (Plan v0.3 §A HC-3b truth,
fresh-verified `prompts/risk/`). HC-3b Finding — flagged for the skill's future amend.

---

## §3 V4-Flash / V4-Pro Routing 决议

**决议: 5 prompts sustained 起手 model per ADR-036 — 0 routing change.**

| prompt | 起手 model | routing 决议 | trigger status |
|---|---|---|---|
| news_classifier | V4-Flash | **sustained V4-Flash** | cost-driven Pro-upgrade trigger (sustained 月成本 ≤ V3 §16.2 上限 50% × 1.5 month) — **0 traffic data, cannot evaluate, DEFERRED**; quality-driven (paper-mode 5d false-positive) — **5d dry-run not run, DEFERRED** |
| bull_agent | V4-Pro | **sustained V4-Pro** | cost-driven Flash-downgrade trigger (sustained 月成本 ≥ 上限 80% × 1 month) — **0 traffic data, DEFERRED** |
| bear_agent | V4-Pro | **sustained V4-Pro** | same as bull_agent — **DEFERRED** |
| regime_judge | V4-Pro | **sustained V4-Pro** | same — **DEFERRED** |
| reflector | V4-Pro | **sustained V4-Pro** | same — **DEFERRED** |

**决议论据** (skill §4 + ADR-072 D2 sustained):
- All 4 routing triggers (skill §4) are **traffic-dependent**: cost-driven needs
  ≥1-1.5 month of accumulated 月成本 vs V3 §16.2 上限; quality-driven needs the
  paper-mode 5d dry-run's false-positive/negative集. Paper-mode (`LIVE_TRADING_DISABLED=
  true` / `EXECUTION_MODE=paper` / 0 持仓) has **0 production traffic** → 0 trigger data.
- ADR-072 D2 already established this exact deferral: "LiteLLM 月成本 ≥3 month ≤80%
  baseline → ⏭ Gate E 自然累积 paper-mode 0 traffic sustained ADR-063 deferral pattern".
  HC-3b's routing 决议 sustains that pattern — the 5 prompts' cost/quality-driven
  re-eval is **routed to Gate E** (paper-mode 5d dry-run) / post-cutover traffic
  accumulation, NOT evaluated-and-skipped.
- The structural baseline eval (§2) found **0 defect** → 0 prompt-content iteration
  needed (the drift-driven trigger also did not fire — prompt content has 0
  cross-system cite drift). So HC-3b = "eval ≥1 round complete, 0 iteration, sustained".

**This IS a routing 决议** (sustained ADR-036 + DEFER cost/quality re-eval to Gate E) —
a documented decision with reasoning on record, NOT a vacuous "TBD" (sustained ADR-071
D4 honest-scope 体例 — DEFERRED with reasoning ≠ INCOMPLETE).

---

## §4 Cumulative cite footer

- **HC-3b deliverable**: 本 eval report + ADR-075 (HC-3 closure) + LL-168 + REGISTRY
  ADR-075 reserved→committed + Plan v0.3 §A HC-3 row closure blockquote (append-only)
- **HC-3 chunked 2 sub-PR closure**: HC-3a (V3 §17.1 CI lint verify-only report + CRLF
  fix, PR #359) → HC-3b (本 — prompts/risk eval iteration ≥1 round structural baseline
  + routing 决议 + ADR-075). **planned 2, actual 2 — 0 balloon** (反 HC-1 3→5 + HC-2
  3→5 双 balloon — HC-3 estimate held).
- **关联**: Plan v0.3 §A HC-3b row + §C Gate D item 4 / `quantmind-v3-prompt-eval-iteration`
  skill (5-step methodology — skill §2 prompt-scope table stale, HC-3b Finding) / V3
  §3.2 / §5.3 / §8 / §16.2 (LLM cost 上限) / ADR-036 (model routing SSOT — 5/5 verified
  match) / ADR-072 D2 (cost decision DEFER, 0-traffic precondition sustained) / ADR-063
  (paper-mode deferral pattern) / ADR-071 D4 (DEFERRED-with-reasoning ≠ INCOMPLETE) /
  ADR-075 (HC-3 closure) / 铁律 28 (发现即报告 — skill scope-table stale Finding) / 铁律
  36 (precondition 核 — fresh-verified prompts/risk/) / 铁律 45 (cite fresh verify —
  routing ↔ TASK_TO_MODEL_ALIAS router.py:109-116)
- **5/5 红线 sustained**: cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true /
  EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 — HC-3b = docs-only eval report +
  closure sediment, 0 prompt yaml change / 0 code / 0 broker / 0 .env / 0 LLM call
  (structural eval, no live-LLM fixture run) / 0 DB mutation
