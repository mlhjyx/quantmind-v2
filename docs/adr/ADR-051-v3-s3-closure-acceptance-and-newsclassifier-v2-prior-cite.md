---
adr_id: ADR-051
title: V3 §S3 closure verify + V2 prior cumulative cite sediment + NewsClassifier ✅ partial fresh re-verify (V3 governance batch closure sub-PR 13 sediment)
status: accepted
related_ironlaws: [22, 25, 36, 37, 38, 41, 45]
recorded_at: 2026-05-09
---

## Context

V3 governance batch closure sub-PR 12 (PR #300) sediment hotfix bundle (celery_app.py imports + ride-next reviewer findings + LL-141 + ADR-050 §post-merge ops 4-step patch). User explicit "可以，主动思考全面" → CC invoke sprint-orchestrator + Phase 0 active discovery (sub-PR 11/12 reverse体例 sustained).

**Phase 0 finding** (sub-PR 13 active discovery, sustained sub-PR 9/10 cumulative体例 第 3 case 实证累积扩):

V3 §S3 NewsClassifier substantially closed by V2 prior cumulative work — file path verify:
- `backend/app/services/news/news_classifier_service.py:175 class NewsClassifierService` ✅
- `backend/app/services/news/news_classifier_service.py:250 def classify` ✅
- `prompts/risk/news_classifier_v1.yaml` v1 (4 profile schema: ultra_short / short / medium / long) ✅
- V2 prior PRs cumulative: PR #241 sub-PR 7b.2 (NewsClassifierService L0.2 V4-Flash + yaml prompt + ADR-031 §6 patch) + PR #242 sub-PR 7b.3-v2 (NewsClassifierService.persist real wire + bootstrap factory + requires_litellm_e2e marker)

**触发**: V3 Tier A S3 sprint 起手 prerequisite verify (post sub-PR 10 closure sequential per Constitution §L8.1 (a) sustained, sub-PR 11a/11b/12 S2.5 三块完整闭环 sustained → S3 sprint sequential per Plan v0.1 §A) → user explicit "可以" ack → sub-PR 13 sediment scope.

**沿用**:
- ADR-022 (反 silent overwrite + 反 retroactive content edit): silent overwrite v0.1-v0.7 row 保留 + version history append
- ADR-031 §6 (V4 路由层 sustained DeepSeek + Ollama, 0 智谱 alias) + ADR-032 (caller bootstrap factory): sustained
- ADR-047 (V3 §S1 closure) + ADR-048 (V3 §S2 closure): closure-only ADR sediment 体例 sustained 第 3 case 实证累积扩
- ADR-049 (V3 §S2.5 architecture sediment) + ADR-050 (V3 §S2.5 implementation): sustained
- ADR-052 (V3 §S2.5 AKShare reverse decision NEW, sub-PR 13 sediment): sustained
- LL-098 X10 (反 forward-progress default): sub-PR 13 closure 后 STOP, 反 silent self-trigger S4 起手
- LL-100 (chunked SOP target): sub-PR 13 single bundle体例 sustained sub-PR 12 hotfix bundle precedent
- LL-115 (Phase 0 active discovery + capacity expansion 真值 silent overwrite anti-pattern): sustained
- LL-117 (atomic sediment+wire 体例): sub-PR 13 mixed bundle atomic
- LL-135 (doc-only sediment 体例): 反 fire test 体例 (sub-PR 13 含 production code change, 走 default push pre-push smoke per ADR-049 §5)
- LL-137 + LL-138 (V3 §S1/S2 substantially closed by V2 prior cumulative work + Tier A sprint chain framing 反 silent overwrite from-scratch assumption): sustained 第 3 case 实证累积扩
- LL-141 (post-merge ops checklist gap + Worker imports verify + 1:1 simulation): sustained sub-PR 13 1:1 simulation real-data verify protocol enforce 第 1 实证累积
- LL-142 (RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证, sub-PR 13 sediment): sustained 关联

## Decision

### §1 V3 §S3 acceptance closure 真值

| # | V3 §S3 acceptance | actual state | evidence |
|---|---|---|---|
| 1 | NewsClassifierService 类 + classify 方法 | ✅ DONE | `backend/app/services/news/news_classifier_service.py:175` `class NewsClassifierService` + `:250 def classify` (PR #241 + #242) |
| 2 | V4-Flash routing via LiteLLMRouter | ✅ DONE | ADR-031 §6 patch + LiteLLMRouter call wire (PR #241 sub-PR 7b.2) |
| 3 | 4 profile schema (ultra_short / short / medium / long) | ✅ DONE | `prompts/risk/news_classifier_v1.yaml` v1 — 4 profile + sentiment_score / category / urgency / confidence schema |
| 4 | yaml prompt (system_prompt + user_prompt) | ✅ DONE | `prompts/risk/news_classifier_v1.yaml` system_prompt JSON schema 6 fields + user_prompt 严格 JSON 输出 |
| 5 | persist real wire (news_classified DDL INSERT) | ✅ DONE | PR #242 sub-PR 7b.3-v2 NewsClassifierService.persist real wire + bootstrap factory (LL-115 sediment体例) |
| 6 | requires_litellm_e2e marker (e2e test marker) | ✅ DONE | PR #242 sub-PR 7b.3-v2 — pytest e2e marker 沿用 sub-PR 7c precedent |
| 7 | NewsClassifier integration in NewsIngestionService orchestrator | ✅ DONE | sub-PR 7c (PR #243) — NewsIngestionService DataPipeline → news_raw → NewsClassifier → news_classified persist 闭环 |
| 8 | unit tests | ✅ DONE | V2 cumulative test files (沿用 PR #241/#242 cumulative cite — 11 test files cumulative for News pipeline) |

**Bottom line**: V3 §S3 = 8/8 ✅ DONE (V2 prior cumulative work substantially closed sustained sub-PR 9/10 体例 第 3 case 实证累积扩).

### §2 V3 §S3 closure sub-PR 13 scope

| 项 | 真值 | sediment file delta |
|---|---|---|
| Plan v0.1 §A S3 row patch | scope V2 prior cite + acceptance 8 items expanded with status / file delta retroactive note (V2 cumulative PR #241+#242 cite) / cycle 真值 V2 prior + sub-PR 13 closure <1 day / dependency 加 V2 prior PR #241+#242 cite + 后置 S5 sustained sequential per Constitution §L8.1 (a) | docs/V3_TIER_A_SPRINT_PLAN_v0.1.md (edit) |
| ADR-051 sediment | 本 ADR (V3 §S3 closure acceptance + V2 prior cumulative cite + NewsClassifier ✅ partial fresh re-verify 8/8 ✅ DONE) | docs/adr/ADR-051-...md (NEW) + REGISTRY.md (append row) |
| LL-143 sediment | V3 §S3 substantially closed by V2 prior cumulative work, sustained LL-137/138 plan-then-execute 体例 第 3 case 实证累积扩 | LESSONS_LEARNED.md (append LL-143) |

**Total**: 3 file delta within sub-PR 13 mixed bundle (沿用 sub-PR 12 hotfix bundle体例 sustainable, sub-PR 13 含 RSSHub→AKShare reverse + S3 closure + LL-142 + LL-143 cumulative).

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) skip V3 §S3 closure ADR | declare done by V2 prior work, 不 sediment closure ADR | ❌ 拒 — 反 LL-115 capacity expansion 真值 silent overwrite anti-pattern; sprint chain integrity 损失; 反 sub-PR 9/10 closure-only ADR体例 第 3 case 实证累积扩 sustainability |
| (2) full re-verify with new prompt eval | re-run prompt eval methodology + 历史 news 回测 baseline 实测 | ❌ 拒 — V2 prior cumulative work 真值 sufficient (8/8 ✅ DONE) + prompt eval methodology baseline V2 prior 已 sediment (PR #241 sub-PR 7b.2) + sub-PR 14+ candidate based on real production traffic evidence (沿用 LL-115 sediment体例) |
| **(3) (γ) verify-only + closure-only ADR sediment (本 ADR 采纳)** | 本 sub-PR 13 part: V3 §S3 closure-only ADR + V2 prior cite trail | ✅ 采纳 — 真值 grounded (V2 PR #241+#242 cumulative cite + file path verify 实测) + sustained sub-PR 9 ADR-047 + sub-PR 10 ADR-048 closure-only ADR sediment 体例 第 3 case 实证累积扩; 反 silent forward-progress LL-098 X10 |
| (4) full re-implement | ignore V2 prior work, 从零 implement | ❌ 拒 — 违反 ADR-022 反 silent overwrite + LL-115 capacity expansion 真值 silent overwrite anti-pattern + LL-137/138 反 from-scratch assumption sustained |

## Consequences

### Positive

- **V3 §S3 closure ADR 锁定**: 8/8 ✅ DONE (V2 prior cumulative work substantially closed sustained 体例)
- **plan-then-execute 体例 6th 实证累积**: sub-PR 8/9/10/11a/11b/12 cumulative + sub-PR 13 sediment 7th 实证 (sub-PR 13 = mixed bundle = RSSHub→AKShare reverse + S3 closure + LL-142 + LL-143)
- **Closure-only ADR sediment 体例 sustained**: ADR-047 + ADR-048 + ADR-051 cumulative 第 3 case 实证累积扩 (V2 prior cumulative work ✅ pattern enforcement sustainable)
- **Tier A 真值 net new scope further clarified**: post sub-PR 13 — 真值 net new sprints = S4 (per user 决议 minimal/skip/完整) + S5 (greenfield + integration-first override) + S7 + S9 + S10 + S11 + 部分 残余. sustained Tier A baseline ~14-18 周 estimate from sub-PR 9 §L0.4 baseline 真值再修订
- **NewsClassifier production-ready verify**: 8/8 ✅ DONE evidence 落地, S5 RealtimeRiskEngine sentiment modifier input ready (沿用 V3 §6.4 sentiment modifier sustained)

### Negative / Cost

- **sub-PR 13 mixed bundle 含 production code change** (AkshareCninfoFetcher NEW + integration + tests): 走 default push pre-push smoke (反 ADR-049 §5 doc-only --no-verify exception, ADR-049 §5 反 abuse boundary sustained)
- **Constitution v0.7 → v0.8 已 bumped 在 sub-PR 11b** (sustained), skeleton v0.6 → v0.7 已 bumped 在 sub-PR 11b — sub-PR 13 0 version bump (反 cumulative version inflation, sustained ADR-022 + 反 silent multi-revision)

### Neutral

- **Sequential sustained per Constitution §L8.1 (a)**: V3 §S3 closure sub-PR 13 → STOP gate before S4 起手 (S4 user 决议 BLOCKER skip/minimal/完整 待 user explicit ack), 反 silent self-trigger S4 implementation 体例
- **ADR-051 sediment dependent on AKShare reverse (sub-PR 13 mixed bundle)**: ADR-051 + ADR-052 cumulative atomic in sub-PR 13 — 反 sequential split (反 LL-100 chunked SOP target ~10-13 min for chunked vs single bundle, sustained sub-PR 12 mixed bundle precedent reviewer 0 P0/P1)

## Implementation Plan

### Phase 1 (本 sub-PR 13 part: S3 closure ADR sediment)

1. ✅ Plan v0.1 §A S3 row patch (V2 prior cite + retroactive note + cite reconcile)
2. ✅ ADR-051 NEW (本文件) + REGISTRY.md append ADR-051 row
3. ✅ LESSONS_LEARNED.md append LL-143

### Phase 2 (sub-PR 14+ — S4 implementation per user 决议 minimal/skip/完整, post sub-PR 13 closure)

- per Constitution §L8.1 (a) 关键 scope 决议 — user explicit ack required: (skip) / (minimal CC 推荐) / (完整)
- minimal scope: 8 维 schema + Tushare/AKShare 1 source ingest + smoke (~3-5 files / 1 周 cycle, sub-PR 14 single sub-PR)

### Phase 3 (S5+ — sustained Plan v0.1 §A baseline)

- S5 RealtimeRiskEngine ⭐⭐⭐ (greenfield + integration-first override, 1.5 周 baseline 含 replan 1.5x)
- S6 / S7 / S8 STAGED ⭐⭐⭐ / S9 / S10 paper-mode 5d / S11 ADR sediment

## References

- V3_TIER_A_SPRINT_PLAN_v0.1.md §A S3 row + §E grand total
- V3_IMPLEMENTATION_CONSTITUTION.md §L0.4 baseline + §L8.1 (a) 关键 scope 决议 + §L10 Gate A criteria
- V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md §2.1 S3 row
- backend/app/services/news/news_classifier_service.py:175 + :250 (V2 prior cumulative)
- prompts/risk/news_classifier_v1.yaml (V2 prior)
- PR #241 sub-PR 7b.2 + PR #242 sub-PR 7b.3-v2 (V2 prior cumulative cite)
- ADR-047 + ADR-048 (closure-only ADR sediment体例 第 3 case 实证累积扩)
- ADR-052 (V3 §S2.5 AKShare reverse decision NEW, sub-PR 13 sediment, 关联)
- LL-137 + LL-138 + LL-143 (V3 sprint substantially closed by V2 prior cumulative work 体例 第 3 case 实证累积扩)
