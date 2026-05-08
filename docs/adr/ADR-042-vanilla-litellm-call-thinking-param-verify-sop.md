---
adr_id: ADR-042
title: vanilla LiteLLM call thinking 参数 verify SOP (web_fetch 官方文档 prerequisite)
status: accepted
related_ironlaws: [1, 22, 25, 27, 36]
related_LL: [109, 110]
recorded_at: 2026-05-08
---

## Context

**Trigger**: 5-07 sub-PR 8a-followup-B Phase 1 drift catch case #14 sediment (ADR-DRAFT row 10 candidate, 5-08 chunk C-ADR promote → ADR-042 committed).

**问题 sediment** (drift catch case #14 真测真值):

CC vanilla `litellm.completion(model="deepseek-chat")` call:
- **0 thinking 参数** in call body
- DeepSeek API 默认 `thinking=enabled`
- response → `reasoning_content` field 出现
- CC 第 1-3 push back 误归因: "DeepSeek 静默 routing reasoner model"
- user 第 7 push back catch correctly:
  - web_fetch DeepSeek 官方 API docs (api-docs.deepseek.com/zh-cn/)
  - 真测真值: deepseek-chat alias 走 V4 + thinking 参数 on/off 决定 V4-Flash vs V4-Pro underlying
  - vanilla call 漏 thinking 参数 → 默认 enabled → 触发 V4-Pro underlying

**5 push back history** (沿用 LL-109 hook governance reverse case):
- push back #1-3: CC 沿用 stale Stack Overflow / blog cite + 误归因 silent routing
- push back #4-6: CC 反 web_fetch 官方文档 prerequisite, 沿用 vanilla SDK 默认参数假设
- push back #7: user catch + decision: web_fetch DeepSeek 官方 API docs verify

## Decision

**vanilla LiteLLM call thinking 参数 verify SOP** (governance enforcement):

1. **任 3rd-party API frame finding/修复必 web_fetch 官方文档 verify prerequisite**:
   - 沿用 LL-110 web_fetch verify SOP
   - 反 vanilla SDK call 默认参数误归因
   - 反 stale Stack Overflow / blog 二手 cite

2. **Vanilla call default 参数 silent drift detection**:
   - vanilla `litellm.completion(model=...)` 漏 thinking → DeepSeek 默认 enabled
   - DeepSeek alias-pass-through (response.model 反 underlying name) → 误归因 "silent routing"
   - 沿用 ADR-040 Layer (a) + (b) 3 层 verify (alias-pass-through + backend silent routing + LiteLLM cost registry gap)

3. **3rd-party API spec watch SOP** (governance):
   - 任 3rd-party API frame 修复 → web_fetch 官方文档 verify prerequisite
   - 沿用 ADR-037 §Context 第 7 漂移类型 candidate (3rd-party API 默认参数误归因 silent semantic drift)
   - 反 LL backlog dump 沿用 stale cite

4. **vanilla call thinking 参数 显式声明 enforcement**:
   - 任 LiteLLM call DeepSeek model 必显式 thinking= 声明
   - 反 沿用 vanilla SDK 默认参数假设
   - test coverage: thinking=enabled / disabled 双 path 真测

5. **LL sediment**: 沿用 LESSONS_LEARNED.md (chunk B 候选, 真预约 chunk C-LL):
   - LL-109 hook governance reverse case (web_fetch verify SOP)
   - LL-110 web_fetch DeepSeek API docs verify SOP

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) vanilla SDK 默认参数沿用 | thinking 参数省略, 沿用 SDK 默认 | ❌ 拒 — drift catch case #14 7 push back 误归因 (CC 沿用 stale cite) |
| (2) Stack Overflow / blog cite | 二手文档 cite | ❌ 拒 — 二手文档常 stale, 误归因 risk |
| (3) Cite 官方 API docs (web_fetch) (本 ADR 采纳) | api-docs.deepseek.com/zh-cn/ canonical | ✅ 采纳 — 真测真值 sediment, 反 vanilla SDK 默认参数 silent semantic drift |
| (4) 显式 thinking 参数 声明 enforcement | 任 LiteLLM call DeepSeek 必显式 thinking= | ✅ 采纳 — 反 vanilla call 默认参数 silent drift |

## Consequences

### Positive
- **drift catch case #14 闭环**: vanilla call 漏 thinking 参数 silent semantic drift sediment + governance enforcement
- **3rd-party API spec watch SOP**: 沿用 ADR-037 第 7 漂移类型 + ADR-040 Layer (a)(b) verify 体例
- **LL-109/110 sediment 真预约 chunk C-LL**: web_fetch verify SOP + DeepSeek API docs cite

### Negative / Cost
- **governance enforcement cost**: 任 3rd-party API frame 修复必 web_fetch prerequisite, 反 `quick fix` 体例
- **vanilla call enforcement cost**: 任 LiteLLM call DeepSeek model 显式 thinking= 声明 cost (反 SDK 默认沿用 cost)
- **test coverage cost**: thinking=enabled / disabled 双 path 真测 (沿用 ADR-040 Layer b verify)

### Neutral
- 沿用 LiteLLM 路由层 (ADR-020/031/032) 反**LiteLLM 接入层重写** sustained

## Implementation

**留 sub-PR 9 真预约**:
- LL-109 + LL-110 LL sediment 加 LESSONS_LEARNED.md (chunk C-LL 真预约)
- vanilla call thinking 参数 enforcement test (LiteLLM call test coverage)

**残余 sub-task** (Sprint 2+ 起手时):
- vanilla call 显式 thinking= 参数 enforcement (LLMCallLogger / NewsClassifier 体例)
- web_fetch verify SOP enforcement (任 3rd-party API frame 修复 prerequisite)

## References
- [ADR-DRAFT row 10](ADR-DRAFT.md) → 本 ADR (committed) source cite
- [ADR-040](ADR-040-deepseek-api-3-layer-mechanism-watch-sop.md) DeepSeek API 3 层暗藏机制 watch SOP (Layer a/b/c verify)
- [ADR-041](ADR-041-yaml-double-model-alias-underlying-sync-governance.md) yaml double-model alias-underlying sync governance
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) §Context 第 7 漂移类型 candidate
- LL-109 hook governance 4 days production 0 catch sediment
- LL-110 alias-layer vs underlying-layer 双层混淆 — DeepSeek API 3 层暗藏机制 sediment
- LL-112 vanilla 3rd-party SDK call 漏默认参数误归因 silent semantic drift (drift catch case #14, 本 ADR 直接来源)
- DeepSeek 官方 API docs: api-docs.deepseek.com/zh-cn/
