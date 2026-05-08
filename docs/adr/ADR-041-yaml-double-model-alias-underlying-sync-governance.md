---
adr_id: ADR-041
title: yaml double-model alias-underlying sync governance (反 single-model drift)
status: accepted
related_ironlaws: [22, 25, 27, 34]
related_LL: [109, 110]
recorded_at: 2026-05-08
---

## Context

**Trigger**: 5-07 sub-PR 8a-followup-B-yaml PR #247 sediment + user 决议 #4 反留尾巴 (ADR-DRAFT row 9 candidate, 5-08 chunk C-ADR promote → ADR-041 committed).

**问题 sediment** (反 single-model drift 体例):

`config/litellm_router.yaml` 含 双 model alias path:
- `deepseek-v4-flash` (V4-Flash underlying)
- `deepseek-v4-pro` (V4-Pro underlying)

5-07 sub-PR 8a-followup-B-yaml PR #247 修订时 user 决议规则:
- **双 model path 1+2 不同步切换 → STOP escalate user** (反 单 model 切换 governance 漂移加深)
- 反**flash 切 V4 + pro 沿用 reasoner** alias-underlying inconsistency

**5-07 真生产真值** (yaml 修订 sediment):
- 双 model 同步切换 (deepseek-v4-flash + deepseek-v4-pro 全切 V4 underlying)
- thinking enabled/disabled align V3 §5.5 chat/reasoner semantic 体例
- 反 flash 切 V4 + pro 沿用 reasoner 单 model drift

## Decision

**yaml double-model sync governance** (governance enforcement):

1. **任 yaml model alias-underlying path 修订必双 model 同步**: flash + pro 一起切 (反 单 model 切换)

2. **STOP escalate trigger** (反**审 review 跳过**):
   - flash 切 V4 + pro 沿用 reasoner → STOP escalate user
   - flash 沿用 chat + pro 切 V4 → STOP escalate user
   - 双 model 不同步切换 → STOP escalate user

3. **Cite source canonical** (反 stale CC 误归因):
   - DeepSeek 官方 deprecation map (api-docs.deepseek.com/zh-cn/, 沿用 ADR-040 LL-110 web_fetch verify SOP)
   - yaml model alias canonical (config/litellm_router.yaml, 沿用 ADR-031 router config SSOT)

4. **5-07 真生产 yaml 双 model 同步 sediment cite**:
   - V3 §5.5 chat/reasoner semantic alignment (thinking enabled/disabled)
   - sub-PR 8a-followup-B-yaml PR #247 5-07 sediment

5. **7-24 deadline plan**: deepseek-chat / deepseek-reasoner alias 弃用前必 双 model sync 切换 V4 underlying

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 单 model 切换 (flash 切 + pro 沿用) | 渐进 migration | ❌ 拒 — alias-underlying inconsistency, governance 漂移加深 |
| (2) 双 model 同步切换 (本 ADR 采纳) | flash + pro 一起切 | ✅ 采纳 — V3 §5.5 chat/reasoner semantic align + governance 反 漂移 |
| (3) 全弃用 alias (直接 v4-flash/pro underlying name) | 跳过 alias 层 | ❌ 拒 — 7-24 官方 deprecation map sustained, alias 沿用 至 deadline |
| (4) yaml 反 sync (沿用 5-02 老 config) | 0 mutation | ❌ 拒 — 5-07 真生产 thinking 参数 sediment 必修 (drift catch #14) |

## Consequences

### Positive
- **governance enforcement**: 双 model sync 切换 必走, 反 单 model drift
- **alias-underlying consistency**: V3 §5.5 chat/reasoner semantic align 沿用 ADR-040 layer (a) (b) 体例
- **STOP escalate sediment**: 反 单 model 切换 governance 漂移 PR review 跳过

### Negative / Cost
- **governance enforcement cost**: yaml 修订必双 model 同步, 反 single-model `quick fix` 体例
- **Test cost**: 双 model alias 全 verify 沿用 LiteLLM SDK + DeepSeek API real call 真测 + cost registry verify (沿用 ADR-040 3 层 verify)

### Neutral
- 沿用 LiteLLM 路由层 (ADR-020/031/032) 反**LiteLLM 接入层重写** sustained

## Implementation

**留 7-24 deadline plan governance PR** (LiteLLM SDK 升级 + yaml double-model V4 underlying full migration):
- LiteLLM SDK 升级 verify v4-* registry entry 生效 (沿用 ADR-038 promote target)
- yaml double-model V4 underlying full migration (本 ADR scope)
- vanilla call thinking 参数 SOP enforcement (沿用 ADR-042)

**残余 sub-task** (Sprint 2+ 起手时):
- yaml 双 model 同步切换 PR (V4 underlying full migration, sustained 7-24 deadline)
- 7-24 deadline plan migration governance PR (audit Week 2 batch B 候选)

## References
- [ADR-DRAFT row 9](ADR-DRAFT.md) → 本 ADR (committed) source cite
- [ADR-040](ADR-040-deepseek-api-3-layer-mechanism-watch-sop.md) DeepSeek API 3 层暗藏机制 watch SOP (Layer a/b/c)
- [ADR-031](ADR-031-s2-litellm-router-implementation-path.md) S2 LiteLLM Router implementation path
- [ADR-038 (reserved)](REGISTRY.md) LiteLLM cost registry V4 gap promote target (ADR-DRAFT row 6)
- LL-111 yaml double-model sync governance — 反 single-model drift 体例 (本 ADR 直接来源)
- LL-110 alias-layer vs underlying-layer 双层混淆 (Layer b backend silent routing 上下文)
- DeepSeek 官方 deprecation map: api-docs.deepseek.com/zh-cn/
