# ADR-020: Claude Boundary + LiteLLM Routing + CI Lint Enforcement

**Status**: Committed (reserved 2026-04-29 + formal promote 2026-05-13 via T1.5b-2 Plan v0.2 §A T1.5 Acceptance item (4) closure)
**Date**: 2026-04-29 (decision) / 2026-05-13 (formal promote)
**Decider**: User 4-29 决议
**Related**: ADR-019 (V3 vision) / ADR-022 (反 silent overwrite) / ADR-031 (S2 LiteLLMRouter implementation path) / ADR-032 (S4 caller bootstrap factory) / ADR-033 (News 源替换 5-02) / ADR-034 (qwen3 fallback 5-06) / ADR-035 (智谱 News#1 + V4 路由层 5-06) / ADR-036 (BULL/BEAR V4-Flash → V4-Pro mapping) / ADR-039 (LLM audit failure resilience) / ADR-064 (Plan v0.2 5 决议 lock) / V3_DESIGN §17.1 (SSOT)

---

## §1 Context

**Origin (2026-04-29 user 决议 + Anthropic API + LiteLLM ecosystem audit)**:

- Anthropic Claude (Opus/Sonnet/Haiku) 是 dev path 主力 (Claude Code + Claude.ai 战略对话)
- 生产推理 (NewsClassifier / fundamental_context_summarizer / Bull-Bear-Judge / RiskReflector / Embedding) 走 LiteLLM (multi-provider abstraction layer)
- **风险**: 生产 path silent import `anthropic` SDK → Claude API call → 直接 vendor lock + cost 不可控 + bypass LiteLLM routing audit + bypass cost monitor
- **历史教训** (sustained LL-098 X10 + LL-115 family + ADR-022): silent SDK import 是 capacity expansion 真值 silent overwrite anti-pattern, 反 zero-cost free-provider preference

**Why CI lint (vs runtime check)**:

- Runtime check 只 catch fire-on-execution, 已部署后再发现成本太高
- CI lint pre-commit/pre-push catch import drift early, before merge
- 生产 path = `backend/app/**` + `backend/scripts/**`, dev path = `backend/engines/mining/**` (legacy allowlist) + `.claude/**` + `tools/**`

---

## §2 Decision

### §2.1 Sub-decision #1: Claude 仅 dev path

- ✅ Allowed: Claude Code CLI (dev), Claude.ai web UI (战略对话), `.claude/skills/**`, `.claude/agents/**`
- ❌ Forbidden in prod: `backend/app/**` + `backend/scripts/**` 任何 `import anthropic` (CI lint enforce)
- ⚠️ Legacy allowlist: `backend/engines/mining/deepseek_client.py:222` (S2-deferred-PR-219 explicit `# llm-import-allow:` marker) — sustained

### §2.2 Sub-decision #2: 生产推理 走 LiteLLM 3-route

V3 §5.5 sustained:

| Route | Provider | Use case | Cost (V3 §16.2) |
|---|---|---|---|
| **V4-Flash** | deepseek-v4-flash (or qwen3-local Ollama fallback per ADR-034) | NewsClassifier / fundamental_context_summarizer / Embedding | $1.5-3/月 + $0.5/月 + $1-2/月 |
| **V4-Pro** | deepseek-v4-pro (or qwen3-pro fallback) | Bull/Bear Agent / Judge / RiskReflector | ~$0.39/月 Bull/Bear discount + $30/月 Judge + $5-10/月 Reflector |
| **Ollama 本地 fallback** | qwen3 (5-06 升级 fallback model per ADR-034) | LiteLLM 全 timeout fallback path | $0 |

**月预算 budget**: $40-50/月 (V3 §16.2, sustained `quantmind-v3-llm-cost-monitor` skill 月度 audit)

**Discount window**: ADR-036 沿用 — Bull/Bear discount 走 2026-05-31 (post-discount price ~$0.39/月 full → $0.10/月 discount)

### §2.3 Sub-decision #3: CI lint `check_llm_imports.sh`

- Path: `scripts/check_llm_imports.sh` (NOT `scripts/audit/check_anthropic_imports.py` per Plan v0.2 §A T1.5 row cite drift / Constitution §L10.1 line 401 cite drift)
- Behavior: AST-walk `backend/app/**/*.py` + `backend/scripts/**/*.py`, detect `import anthropic` or `from anthropic import ...`, exclude allowlist marker `# llm-import-allow:`
- Integration:
  - **Pre-commit** (mode `--staged`): scope = staged .py files 中 backend/ + scripts/
  - **Pre-push** (mode `--full`): scope = 全 backend/app/ + backend/scripts/
  - Path: `config/hooks/pre-push` line 62-63 — `if [ -x scripts/check_llm_imports.sh ]; then sh scripts/check_llm_imports.sh --full; fi`
- Pre-push real-fire log (PR #324 push 2026-05-13): `ALLOWLIST_HIT: backend/engines/mining/deepseek_client.py:222` + `[check_llm_imports] 0 unauthorized import 命中, mode=--full, 放行`

### §2.4 Sub-decision #4: Allowlist legacy explicit marker

- Format: `# llm-import-allow:<reason-tag>` (e.g. `# llm-import-allow:S2-deferred-PR-219`)
- Audit trail: 反 silent allowlist add, 每 allowlist entry require explicit reason
- Current allowlist: 1 entry (`backend/engines/mining/deepseek_client.py:222`, S2-deferred-PR-219 sustained per V2 prior cumulative)

### §2.5 Sub-decision #5: LiteLLM SDK + Router implementation path

Sustained subsequent ADR cumulative chain:

- **ADR-031**: S2 LiteLLMRouter implementation path 决议 (新建 `backend/qm_platform/llm/` module + 渐进 deprecate legacy `backend/engines/mining/deepseek_client.py`)
- **ADR-032**: S4 caller bootstrap factory + naked LiteLLMRouter export 限制
- **ADR-033**: News 源替换 决议 (5-02 sediment, V3 §3.1 + V3 §20.1 #10 patch)
- **ADR-034**: LLM Fallback Model Upgrade (qwen3:8b → qwen3.5:9b, 5-06)
- **ADR-035**: 智谱 News#1 fetcher (GLM-4.7-Flash) + V4 路由层 0 智谱决议 (5-06 (a)+(b) 修订)
- **ADR-036**: BULL/BEAR Agent mapping V4-Flash → V4-Pro (debate reasoning capability + V3 §5.5 internal drift 修复)
- **ADR-039**: LLM audit failure path resilience — retry policy + transient/permanent classifier (S2.4)

---

## §3 Consequences

### §3.1 Cost control sustained

- May 2026 累计 LiteLLM cost = $0.0000 (per T1.5a Gate A item 6 verify, CC psql `SELECT SUM(cost_usd_total) FROM llm_cost_daily WHERE day >= '2026-05-01'` 2026-05-13)
- Free-provider sustained throughout Tier A code-side closure 期 (ADR-063 Evidence cite "dev-only LLM free-provider activity")
- V3 §16.2 上限 ~$50/月 well within budget

### §3.2 CI lint enforcement empirical

- Pre-push hook real-fire log 累积 cumulative 29 PR (#296-#324) 全 PASS check_llm_imports.sh
- 0 unauthorized import detected to date (post-PR #324 verify 2026-05-13)
- 1 legacy allowlist entry sustained (deepseek_client.py:222 with explicit marker)

### §3.3 Subsequent ADR sediment chain

- post-ADR-020 sediment, ADR-031~036 + ADR-039 cumulative subsequent decisions (7 ADRs sediment Tier A 期内)
- LiteLLM routing 实施真值 fully decomposed via subsequent ADR chain (sustained ADR-022 反 silent overwrite + 渐进 sediment 体例)

### §3.4 Test coverage

- `scripts/check_llm_imports.sh` unit + integration tests sediment (S2/S4 sub-PR cycle cumulative)
- Pre-commit + pre-push hook integration verified via 29 PR cumulative pre-push hook fire log

---

## §4 Cite

- V3_DESIGN §17.1 (Claude 边界 + LiteLLM 路由 + CI lint)
- V3_DESIGN §5.5 (V4-Flash vs V4-Pro 路由 + 月预算 budget)
- V3_DESIGN §16.2 (LLM 成本 budget ≤ $50/月 上限)
- V3_DESIGN §18.1 row 2 (本 ADR-020 reserve)
- scripts/check_llm_imports.sh (实施 SSOT)
- config/hooks/pre-push line 62-63 (集成 SSOT)
- backend/engines/mining/deepseek_client.py:222 (legacy allowlist sustained)
- llm_cost_daily 表 (cost monitoring SSOT, May 2026 $0.0000 verified)
- `quantmind-v3-llm-cost-monitor` skill (月度 audit SOP)

### Related Decisions

- ADR-019 (V3 vision 5+1 层) — V3 §0 设计起点
- ADR-022 (反 silent overwrite + 反 retroactive content edit) — V3 文档治理 pattern sustained
- ADR-031 (S2 LiteLLMRouter implementation path) — 本 ADR §2.5 sub-decision #5 第 1 follow-up
- ADR-032 (S4 caller bootstrap factory) — sub-decision #5 第 2 follow-up
- ADR-033 (News 源替换 5-02) — sub-decision #5 第 3 follow-up
- ADR-034 (LLM Fallback Model Upgrade) — sub-decision #5 第 4 follow-up
- ADR-035 (智谱 News#1 + V4 路由层) — sub-decision #5 第 5 follow-up
- ADR-036 (BULL/BEAR V4-Flash → V4-Pro) — sub-decision #5 第 6 follow-up
- ADR-039 (LLM audit failure resilience) — sub-decision #5 第 7 follow-up
- ADR-064 (Plan v0.2 5 决议 lock) — Tier B Bull/Bear/RAG/Reflector LLM 路由 sustained
