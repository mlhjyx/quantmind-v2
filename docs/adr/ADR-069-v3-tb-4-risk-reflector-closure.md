# ADR-069: V3 Tier B TB-4 Closure — RiskReflectorAgent + 5 维反思 V4-Pro + lesson 闭环 + AI-PR-generation flow

**Status**: Accepted
**Date**: 2026-05-14 (Session 53 + TB-4 closure 4 sub-PR cumulative)
**Type**: V3 Tier B Sprint Closure ADR
**Cumulative**: TB-4a (PR #343 `9aa13ea`) + TB-4b (PR #344 `460f18a`) + TB-4c (PR #345 `6cd2f16`) + TB-4d (本 PR sediment)
**Plan v0.2 row**: §A TB-4 sprint closure

---

## Context

V3 Tier B Plan v0.2 TB-4 sprint = "L5 RiskReflectorAgent + 5 维反思 (V4-Pro) + 周/月/event cadence + lesson→risk_memory 闭环 + user reply approve → CC 自动 PR generate flow" per V3 §8 L5 反思闭环层. Chunked into 4 sub-PR per LL-100 体例:

1. **TB-4a skeleton**: RiskReflectorAgent + reflector_v1.yaml 5 维 prompt + V4-Pro wire (57 tests)
2. **TB-4b Beat cadence**: Celery Beat 2 cadence (Sunday 19:00 + 月 1 日 09:00) + DingTalk push + docs/risk_reflections/ dir 体例 (37 tests)
3. **TB-4c lesson loop**: lesson→risk_memory 闭环 (BGE-M3 embed → RiskMemory → persist) + 4 边界 case prompt eval (23 tests)
4. **TB-4d closure (本 PR)**: user reply approve → CC 自动 PR generate flow + DingTalk webhook receiver patch + 候选规则新增→risk_findings/ 体例 + ADR-069 + LL-163 (37 tests)

**Driver**: V3 §8 L5 反思闭环层 — 周/月/事件后系统反思 → lesson 沉淀 RAG + 候选参数调整 push user 决策. **闭环至于此** (V3 §8 目标 line 912).

---

## Decisions

### D1: 3-layer pattern sustained — Engine PURE + Application + Beat dispatch (16th 实证)

**Decision**: Architecture per V3 §11.4 sustained (S5-S9/TB-1/TB-2/TB-3 cumulative):
- `backend/qm_platform/risk/reflector/` = Engine PURE (interface + agent V4-Pro wrapper)
- `backend/app/services/risk/risk_reflector_agent.py` = Application orchestration (reflect + sediment_lesson) per V3 §11.2 line 1228 SSOT
- `backend/app/services/risk/reflection_candidate_service.py` (TB-4d) = Application (candidate sediment, file IO)
- `backend/app/tasks/risk_reflector_tasks.py` = Beat dispatch (3 cadence + markdown sediment + DingTalk push)
- `scripts/generate_risk_candidate_pr.py` (TB-4d) = explicit-trigger tool (the ONLY git-touching component)

**16th cumulative 实证** (S5 + S7 + S8×4 + S9×2 + S10 + TB-1×3 + TB-2×4 + TB-3×4 + TB-4×4).

### D2: V4-Pro for RiskReflector (ADR-036 sustained) + 5 维 prompt 锁

**Decision**: `RiskTaskType.RISK_REFLECTOR` → `deepseek-v4-pro` (already wired in router.py per ADR-036). 5 维反思 prompt `prompts/risk/reflector_v1.yaml` — Detection / Threshold / Action / Context / Strategy (V3 §8.1 line 927-933 1:1).

**Cost** (V3 §16.2 line 726 budget ~$5-10/月): actual estimate ~$0.05/月 (7 calls/month × ~3500 tokens × ~$0.0021 input + ~$0.0056 output ≈ $0.0077/call). Well below budget — TB-4 reflection cadence is low-frequency (4 weekly + 1 monthly + ~2 event/month).

### D3: lesson→risk_memory embedding = BGE-M3 local (NOT V4-Flash — pre-ADR-064 spec drift resolved)

**Decision**: TB-4c `sediment_lesson` embeds reflection lesson via BGE-M3 local `BGEM3EmbeddingService` (TB-3b), NOT LiteLLM V4-Flash API embedding.

**Rationale**: V3 §8.3 line 962 + §16.2 line 727 + Plan v0.2 §A TB-4 row cite "V4-Flash embedding" — but ADR-064 D2 + ADR-068 D2 superseded this with BGE-M3 local embedding lock (0 cost vs LiteLLM Flash ~$0.01/event, 中文优化, 1024-dim). The "V4-Flash embedding" cite is a pre-ADR-064 spec artifact. **TB-5c batch will amend V3 §8.3 line 962 + §16.2 line 727 doc** (sustained ADR-022 反 retroactive content edit — batch amend, not inline).

### D4: AI-PR-generation flow safety boundary — "Webhook sediment + scripts/ PR 生成器" (option B, user 决议 PR #345 plan)

**Decision**: The V3 §8.3 line 967 "user reply approve → 系统生成 PR (CC 自动 commit + push)" flow is implemented as **option B** (user explicitly chose, PR #345 plan AskUserQuestion):

| Component | git ops | .env ops | trigger |
|---|---|---|---|
| DingTalk webhook handler | ❌ 0 | ❌ 0 | webhook hot path (automatic) |
| ReflectionCandidateService | ❌ 0 | ❌ 0 | webhook handler invokes |
| `scripts/generate_risk_candidate_pr.py` | branch+commit+push (**NEVER merge**) | ❌ 0 (red-line self-check) | **explicit human/CC trigger** |
| user | merge PR | via PR review only | explicit |

**Rationale**:
- **Option A** (webhook sediment only, no PR generation) — safest but V3 §8.3 "CC 自动生成 PR" 闭环 incomplete.
- **Option C** (webhook handler itself does git commit+push) — REJECTED: production Celery process running git is fragile (lock contention / auth / branch state) + webhook hot path mutating repo is the largest 红线 surface.
- **Option B** (chosen) — webhook handler stays pure (0 git / 0 .env), the `scripts/` PR generator is the ONLY git-touching component, behind an explicit trigger, with a **red-line self-check** that aborts if the staged change set touches anything outside `docs/research-kb/risk_findings/` (反 .env / production code / configs mutation per ADR-022 + 铁律 35). The script does branch+commit+push but **NEVER merge** — user 显式 merge sustained (LL-098 X10).

### D5: candidate_id scheme `<period_label>#<index>` + event_type namespace prefix

**Decision**:
- candidate_id = `<period_label>#<global_index>` (1-based, across 5 维 in ReflectionDimension enum order). DingTalk 摘要 (TB-4b patched in TB-4d) lists each candidate with its id so user replies `approve <candidate_id>` / `reject <candidate_id>`.
- risk_memory.event_type for periodic reflections uses `Reflection:` namespace prefix (`Reflection:Weekly` / `Reflection:Monthly` / `Reflection:Event` default) — 反 semantic pollution of the event_type space shared with real risk events (LimitDown/RapidDrop/etc). event_reflection caller-supplied event_type stays unprefixed (L1 dispatch passes the REAL triggering event type — a reflection ABOUT a LimitDown IS relevant when RAG-querying LimitDown memories). Sustained PR #345 reviewer MEDIUM 2.

### D6: candidate sediment idempotency + fail-loud

**Decision**: `ReflectionCandidateService.process_candidate_command` is idempotent — re-reply of the same candidate_id returns `ALREADY_DECIDED` without overwriting (反 DingTalk webhook auto-retry double-write + 反 silent decision flip). Fail-loud per 铁律 33: report-not-found / candidate-index-out-of-range raise `ReflectionCandidateError` (caller maps to HTTP 4xx idempotent body).

---

## Results

### Test cumulative across TB-4 (4 sub-PR)

| Sub-PR | Tests | Wall clock |
|--------|-------|------------|
| TB-4a | 57 (skeleton + prompt + V4-Pro wire) | 0.11s |
| TB-4b | 37 (Beat cadence + DingTalk + dir 体例) | 0.18s |
| TB-4c | 23 (lesson loop + 4 边界 case eval) | 0.20s |
| TB-4d | 37 (webhook parse + candidate service + PR script) | 0.46s |
| **Total** | **154 tests, 154/154 PASS** | <1s combined (all mocked) |

### Reviewer 2nd-set-of-eyes cumulative (LL-067 体例 sustained)

| PR | Reviewer verdict | Fixes applied |
|----|------------------|---------------|
| #343 TB-4a | APPROVE, 0 CRITICAL/0 HIGH | 2 MEDIUM (brace escape + direct response.content) applied |
| #344 TB-4b | REQUEST CHANGES → APPROVE | 1 HIGH (collision analysis) + 2 MEDIUM + 1 LOW applied |
| #345 TB-4c | APPROVE, 0 CRITICAL/0 HIGH | 2 MEDIUM (import-root + event_type prefix) + 1 LOW (501-char test) applied; 2 LOW reviewer-confirmed no-change |
| 本 TB-4d | pending reviewer spawn (23rd) | TBD |

**Cumulative reviewer 2nd-set-of-eyes 实证 = 23** (19 prior TB-1+TB-2+TB-3 + 4 TB-4 sub-PR).

### Engine PURE contract sustained (V3 §11.4)

- `qm_platform/risk/reflector/` = interface + agent (Engine PURE)
- `qm_platform/risk/execution/webhook_parser.py` = pure parser (0 IO, HMAC verify + command parse)
- `app/services/risk/risk_reflector_agent.py` + `reflection_candidate_service.py` = Application orchestration
- `app/tasks/risk_reflector_tasks.py` = Beat dispatch (transaction owner per 铁律 32)
- `scripts/generate_risk_candidate_pr.py` = explicit-trigger tool (only git-touching component)

---

## Sprint chain closure status (Plan v0.2 §A)

- ✅ **TB-4a** PR #343 `9aa13ea` — RiskReflectorAgent skeleton + reflector_v1.yaml 5 维 prompt + V4-Pro wire (57 tests)
- ✅ **TB-4b** PR #344 `460f18a` — Celery Beat 2 cadence + DingTalk push + risk_reflections/ dir 体例 (37 tests)
- ✅ **TB-4c** PR #345 `6cd2f16` — lesson→risk_memory 闭环 + 4 边界 case prompt eval (23 tests)
- ✅ **TB-4d** 本 PR — AI-PR-generation flow + webhook patch + candidate service + ADR-069 + LL-163 (37 tests)

**TB-4 sprint closure ✅ achieved**. RiskReflector 闭环 production-ready: 5 维反思 → markdown 沉淀 + DingTalk push + lesson→risk_memory + user approve → candidate sediment → scripts/ PR generate → user merge.

---

## Tier B sprint chain status post-TB-4

| Sprint | Status | Notes |
|--------|--------|-------|
| T1.5 | ✅ DONE | ADR-065 Gate A 7/8 PASS + 1 DEFERRED |
| TB-1 | ✅ DONE | ADR-066 (3 sub-PR) |
| TB-2 | ✅ DONE | ADR-067 (5 sub-PR 真完全) |
| TB-3 | ✅ DONE | ADR-068 (4 sub-PR) |
| **TB-4** | ✅ **DONE** | 本 ADR-069 closure cumulative (4 sub-PR) |
| TB-5 | ⏳ pending | Tier B closure + replay 验收 + V3 §15.6 ≥7 scenarios + Gate B/C close (~1 week) |

**Tier B remaining baseline**: ~1 week (TB-5 only, replan 1.5x = 1.5 weeks).

---

## Sim-to-real verification (V3 §15.5 sustained)

**End-to-end wire verified via 154 cumulative tests**:
1. ✅ ReflectorAgent V4-Pro single-call: yaml load + JSON parse + 5 维 schema validate (TB-4a)
2. ✅ RiskReflectorAgent reflect() delegation + sediment_lesson() BGE-M3 embed → RiskMemory → persist (TB-4a/c)
3. ✅ Celery Beat 2 cadence registered + 3 tasks (weekly/monthly/event) (TB-4b)
4. ✅ Markdown sediment → docs/risk_reflections/ + DingTalk 摘要 push via send_with_dedup (TB-4b)
5. ✅ lesson→risk_memory: _compose_lesson_text ≤500 char + _compose_context_snapshot JSONB + persist_risk_memory INSERT (TB-4c)
6. ✅ 4 边界 case prompt eval: empty week / 1 event / 100 events / V4-Pro timeout (TB-4c)
7. ✅ webhook parse_candidate_command: approve/reject/批准/拒绝 + path-traversal blocked (TB-4d)
8. ✅ ReflectionCandidateService: candidate sediment + idempotency + report resolution + extraction (TB-4d)
9. ✅ scripts/generate_risk_candidate_pr.py: red-line self-check (PASS + abort-on-violation) + dry-run in tmp git repo (TB-4d)

**Pending production smoke** (user-driven, per docs/runbook/cc_automation/v3_tb_4b_reflector_beat_wire.md):
- Servy restart QuantMind-CeleryBeat AND QuantMind-Celery
- 1:1 manual fire weekly_reflection.apply()
- Verify markdown report + risk_memory INSERT row + DingTalk push (if enabled)

---

## Constitution / Plan / REGISTRY amendments (本 sediment cycle)

- `docs/adr/REGISTRY.md`: ADR-069 row appended + count update (committed 61 → 62)
- `LESSONS_LEARNED.md` LL-163 append (TB-4 closure pattern + AI-PR-generation flow safety design)
- `memory/project_sprint_state.md`: Session 53 handoff append (TB-4 ✅ closure summary, out-of-repo)
- `docs/V3_TIER_B_SPRINT_PLAN_v0.1.md` §A TB-4 row closure marker: 留 TB-5c batch closure (sustained ADR-022)
- V3 §8.3 line 962 + §16.2 line 727 "V4-Flash embedding" → BGE-M3 amend: 留 TB-5c batch (D3 sustained ADR-022)

---

## 红线 sustained (5/5)

- cash=¥993,520.66 (sustained 4-30 user 决议清仓)
- 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102

**0 broker call / 0 .env mutation / 0 真账户 touched** across all 4 TB-4 sub-PRs. TB-4c risk_memory INSERT = single-row via persist_risk_memory (LL-066 例外, 铁律 17). TB-4d AI-PR-generation flow: webhook handler 0 git / 0 .env; `scripts/generate_risk_candidate_pr.py` red-line self-check aborts on any non-risk_findings/ staged path; NEVER git merge.

---

## 关联

**ADR (cumulative)**: ADR-022 (反 retroactive edit + 反 silent .env mutation) / ADR-031 (LiteLLMRouter) / ADR-036 (V4-Pro mapping) / ADR-057 (S8 webhook receiver 体例) / ADR-064 D2 + ADR-068 D2 (BGE-M3 embedding sustained) / ADR-065 (Gate A) / ADR-066 (TB-1) / ADR-067 (TB-2) / ADR-068 (TB-3) / **ADR-069 (本 TB-4 closure)**

**LL (cumulative)**: LL-066 (DataPipeline subset 例外) / LL-067 reviewer 体例 (23rd 实证) / LL-097 (Beat restart) / LL-098 X10 (反 silent forward-progress — sustained in AI-PR-generation flow: script generates PR, user merges) / LL-100 (chunked sub-PR SOP — 7th case 实证 TB-4 4-sub-PR) / LL-115 family / LL-141 (4-step post-merge ops) / LL-151 (S8 webhook 体例) / LL-157 (V4-Pro timeout 反 silent skip) / LL-159 (4-step preflight) / LL-160 (DI factory) / LL-161 (TB-2 closure) / LL-162 (TB-3 closure) / **LL-163 NEW (TB-4 closure + AI-PR-generation flow safety design 体例)**

**V3 spec**: §8 (L5 反思闭环层) / §8.1 line 918-933 (cadence + 5 维) / §8.2 line 939-957 (markdown 沉淀 + DingTalk 摘要) / §8.3 line 959-972 (闭环核心) / §8.4 (V4-Pro 路由) / §11.2 line 1228 (RiskReflectorAgent location SSOT) / §11.4 (pure function) / §14 #13 (V4-Pro timeout fail-loud) / §16.2 ($50/月 cap)

**File delta (本 TB-4d PR sediment)**:
1. `backend/qm_platform/risk/execution/webhook_parser.py` MOD (parse_candidate_command + CandidateCommand + ParsedCandidateWebhook)
2. `backend/app/services/risk/reflection_candidate_service.py` NEW (~290 lines)
3. `scripts/generate_risk_candidate_pr.py` NEW (~210 lines, red-line self-check)
4. `backend/app/tasks/risk_reflector_tasks.py` MOD (_render_dingtalk_summary candidate IDs)
5. `docs/research-kb/risk_findings/README.md` NEW (dir 体例)
6. `backend/tests/test_reflection_candidate_flow.py` NEW (37 tests)
7. `docs/adr/ADR-069-v3-tb-4-risk-reflector-closure.md` NEW (本)
8. `docs/adr/REGISTRY.md` MOD (ADR-069 row + count)
9. `LESSONS_LEARNED.md` MOD (LL-163 append)

9 file delta atomic 1 PR per ADR-064 D5=inline 体例 sustained.

---

**ADR-069 Status: Accepted (V3 Tier B TB-4 closure cumulative 4 sub-PR — RiskReflectorAgent + 5 维反思 V4-Pro + lesson 闭环 + AI-PR-generation flow ✅).**

新人 ADR (post-ADR-068 count: committed 62 — 61 file-based inc ADR-069 + 1 alias-committed ADR-025 + reserved 2; active 64 = 68 # space - 4 historical gap), 0 new reserved reserve.
