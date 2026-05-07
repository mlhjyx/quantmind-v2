---
adr_id: ADR-040
title: DeepSeek API 3 层暗藏机制 watch SOP (alias-pass-through + backend silent routing + LiteLLM cost registry gap)
status: accepted
related_ironlaws: [1, 22, 25, 27, 34, 36]
related_LL: [109, 110]
recorded_at: 2026-05-08
---

## Context

**Trigger**: 5-07 sub-PR 8a-followup-B Phase 1 真测真值 sediment + drift catch case #12/#13/#14 汇总 (ADR-DRAFT row 8 candidate, 5-08 chunk C-ADR promote → ADR-040 committed).

**3 层暗藏机制** (DeepSeek API 真测真值 sediment):

### Layer (a) alias-pass-through layer
DeepSeek API echoes caller-sent model name as `response.model` field (反 underlying provider/model name). 真测 evidence:
- caller send `model="deepseek-chat"` → response `model="deepseek-chat"`
- caller send `model="deepseek-v4-flash"` → response `model="deepseek-v4-flash"`
- 沿用 OpenAI API 体例 (echo caller model name)

### Layer (b) backend silent routing layer
`deepseek-chat` / `deepseek-reasoner` 是 **legacy alias** 走 V4 underlying via `thinking` 参数 on/off:
- `deepseek-chat` (thinking=disabled) → V4-Flash underlying
- `deepseek-reasoner` (thinking=enabled) → V4-Pro underlying
- **dual-mode model** 沿用 DeepSeek 官方 7-24 deprecation map (api-docs.deepseek.com/zh-cn/)
- vanilla `litellm.completion(model="deepseek-chat")` 漏 `thinking` 参数 → 默认 `thinking=enabled` → reasoning_content 出现 → 误归因 "silent routing reasoner"

### Layer (c) LiteLLM cost registry layer
`deepseek/deepseek-v4-flash` + `deepseek/deepseek-v4-pro` **0 entry** in LiteLLM model_cost registry:
- BudgetGuard cost_usd_total 永 0 for v4-* (V3 §20.1 #6 $50/月 budget cap **反 trigger**)
- 7-24 deadline: deepseek-chat / deepseek-reasoner 弃用前 LiteLLM SDK 升级 prerequisite
- 5-07 真生产 evidence: sub-PR 8a-followup-B Phase 1 8 path 真测 cost_usd=None for v4-*

## Decision

**DeepSeek API watch SOP** (governance enforcement):

1. **任 3rd-party API frame finding/修复必 web_fetch 官方文档 verify prerequisite** (沿用 LL-110 sediment, 反 vanilla SDK call 默认参数误归因 silent semantic drift)

2. **Cite source canonical**: `api-docs.deepseek.com/zh-cn/` (反 stale Stack Overflow / blog / 二手 cite)

3. **3 层 layer 跨 SDK 验证**:
   - Layer (a) alias-pass-through: response.model field 真值 verify (反 "underlying model" 假设)
   - Layer (b) backend silent routing: `thinking` 参数显式声明 (反 vanilla SDK 默认值假设)
   - Layer (c) cost registry: LiteLLM model_cost dict 真值 grep verify (反 "cost tracked" 假设)

4. **Drift catch case sediment**: drift catch case #12 (alias-pass-through) + #13 (backend silent routing) + #14 (LiteLLM cost registry gap) 沿用 ADR-DRAFT 体例 sediment

5. **7-24 deadline plan governance** (V4-Pro/V4-Flash full migration):
   - LiteLLM SDK 升级 verify v4-* registry entry 生效 (sediment ADR-DRAFT row 6 promote → ADR-038)
   - deepseek-chat / deepseek-reasoner 弃用前 yaml double-model sync (沿用 ADR-041)
   - vanilla call thinking 参数 verify SOP enforcement (沿用 ADR-042)

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 沿用 vanilla SDK call 默认参数 | thinking 参数省略, 沿用 SDK 默认 | ❌ 拒 — drift catch #14 第 7 push back 后才修正 (CC 误归因 3 次, user 7 push back 后 web_fetch 官方文档 verify) |
| (2) Stack Overflow / blog cite verify | 沿用 二手文档 cite | ❌ 拒 — 二手文档常 stale, 误归因 risk |
| (3) cite 官方 API docs (web_fetch) | api-docs.deepseek.com/zh-cn/ canonical | ✅ 采纳 — 真测真值 sediment, 反 vanilla SDK 默认参数 silent semantic drift |
| (4) 全 弃用 deepseek-chat/reasoner alias | 直接 v4-flash/v4-pro 用 underlying name | ❌ 拒 — 7-24 官方 deprecation map sustained, alias 沿用 至 7-24 deadline |

## Consequences

### Positive
- **drift catch case #12/#13/#14 闭环**: 3 层暗藏机制 sediment + governance enforcement
- **3rd-party API spec watch SOP**: 沿用 ADR-037 §Context 第 7 漂移类型 (3rd-party API 默认参数误归因 silent semantic drift)
- **7-24 deadline plan prerequisite**: LiteLLM SDK 升级 + yaml double-model sync (ADR-041) + vanilla call SOP (ADR-042) 三联动

### Negative / Cost
- **governance enforcement cost**: 任 DeepSeek API frame 修复必 web_fetch verify prerequisite, 反 `quick fix` 体例
- **Drift catch sediment cost**: drift catch case #12-14 ADR-DRAFT sediment + ADR-040 ADR sediment cost

### Neutral
- 沿用 LiteLLM 路由层 (ADR-020 reserved + ADR-031 + ADR-032) 反**LiteLLM 接入层重写** sustained

## Implementation

**留 sub-PR 8b-llm-fix Pydantic propagate primary path + sub-PR 8b-rsshub** sediment cite:
- ADR-038 (LiteLLM cost registry V4 gap reserve, ADR-DRAFT row 6 promote target, 等 LiteLLM SDK 升级 verify 时 sediment)
- ADR-041 (yaml double-model alias-underlying sync, 本 PR sediment)
- ADR-042 (vanilla LiteLLM call thinking 参数 verify SOP, 本 PR sediment)

**残余 sub-task** (审 audit Week 2 batch B):
- 7-24 deadline plan governance PR (LiteLLM SDK 升级 + v4-* underlying full migration)

## References
- [ADR-DRAFT row 8](ADR-DRAFT.md) → 本 ADR (committed) source cite
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) §Context 第 7 漂移类型 candidate (3rd-party API 默认参数误归因)
- [ADR-031](ADR-031-s2-litellm-router-implementation-path.md) S2 LiteLLM Router implementation path
- [ADR-032](ADR-032-s4-caller-bootstrap-factory.md) S4 caller bootstrap factory
- LL-109 hook governance reverse case
- LL-110 web_fetch verify SOP
- DeepSeek 官方 API docs: api-docs.deepseek.com/zh-cn/
