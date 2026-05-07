---
adr_id: ADR-036
title: BULL/BEAR Agent mapping V4-Flash → V4-Pro (debate reasoning capability + V3§5.5 internal drift 修复)
status: accepted
related_ironlaws: [22, 25, 27, 34]
recorded_at: 2026-05-06
---

## Context

V3§5.5 BULL/BEAR Agent mapping 5-02 sediment 走 V4-Flash (轻量 + 低成本). 5-06 Sprint 2 prerequisite Step 2.5 4 source cross-verify 发现:

- **真生产代码 SSOT** (router.py + types.py): BULL_AGENT + BEAR_AGENT mapping V4-Flash PR #221 sediment
- **V3§5.5 mapping table 文档 cite** (line 660/661/724): "V4-Flash" 5-02 sediment ✅ align 真生产代码
- **V3§11.2 service cite** (line 1228, MarketRegimeService): "LiteLLMRouter (V4-Pro)" — **internal drift 5-02 sediment**
- **V3§19 cost 估算** (line 1589): "V4-Flash | 180 calls/月 | $0.3/月" — align V3§5.5 mapping (V4-Flash)

**5-06 user 决议**: BULL/BEAR mapping V4-Flash → V4-Pro (debate agent **reasoning capability** 需求, 反 V4-Flash 轻量分类). 沿用 V3§11.2 line 1228 service cite 已 V4-Pro 体例修复 V3 internal drift.

**触发**: V3 Tier A Sprint 2 起手前 prerequisite Step 3 (BULL/BEAR mapping 修订 + ADR-033 patch + ADR-035/036 新建). 走单 PR sediment 沿用 ADR-022 集中修订机制.

**沿用**:
- ADR-020 (Claude 边界 + LiteLLM 路由, reserved): V4 路由层走 LiteLLM Router 沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制): V3 internal drift 走集中修订
- ADR-031 §6 (S2 LiteLLMRouter implementation path): V4 路由层 mapping SSOT
- ADR-035 (智谱 News#1 + V4 路由层 0 智谱): 单 PR 跟随 sediment

## Decision

**BULL_AGENT + BEAR_AGENT mapping**: V4-Flash (`deepseek-v4-flash`) → **V4-Pro** (`deepseek-v4-pro`)

| TASK_TO_MODEL_ALIAS | 5-02 sediment | 5-06 修订 (本 ADR) |
|---|---|---|
| RiskTaskType.NEWS_CLASSIFY | "deepseek-v4-flash" | |
| RiskTaskType.FUNDAMENTAL_SUMMARIZE | "deepseek-v4-flash" | |
| **RiskTaskType.BULL_AGENT** | **"deepseek-v4-flash"** | **"deepseek-v4-pro"** |
| **RiskTaskType.BEAR_AGENT** | **"deepseek-v4-flash"** | **"deepseek-v4-pro"** |
| RiskTaskType.EMBEDDING | "deepseek-v4-flash" | |
| RiskTaskType.JUDGE | "deepseek-v4-pro" | |
| RiskTaskType.RISK_REFLECTOR | "deepseek-v4-pro" | |

### V3 internal drift 修复 cite

| 文档 location | 5-02 sediment | 5-06 修订 (本 ADR) |
|---|---|---|
| V3§5.5 line 660 (Bull Agent cite) | "(V4-Flash)" | "(V4-Pro)" |
| V3§5.5 line 661 (Bear Agent cite) | "(V4-Flash)" | "(V4-Pro)" |
| V3§5.5 line 724 (mapping table) | "Bull Agent / Bear Agent | V4-Flash" | "Bull Agent / Bear Agent | V4-Pro" |
| V3§5.5 line 724 cost | "$0.03/天" | "~$0.013/天 (V4-Pro full price) / ~$0.003/天 (75% discount 走 2026-05-31)" |
| V3§11.2 line 1228 (MarketRegimeService) | "LiteLLMRouter (V4-Pro)" | ✅ (本 PR align target) |
| V3§19 line 1589 (cost 估算) | "V4-Flash | 180 | $0.3/月" | "V4-Pro | 180 | ~$0.39/月 (full) / ~$0.10/月 (discount 中)" |

### 真生产代码 SSOT patch (本 PR)

```python
# backend/qm_platform/llm/_internal/router.py line 56-67
TASK_TO_MODEL_ALIAS: dict[RiskTaskType, str] = {
    RiskTaskType.NEWS_CLASSIFY:        "deepseek-v4-flash",
    RiskTaskType.FUNDAMENTAL_SUMMARIZE: "deepseek-v4-flash",
    RiskTaskType.BULL_AGENT:           "deepseek-v4-pro",   # ← 本 PR 修订 (V4-Flash → V4-Pro)
    RiskTaskType.BEAR_AGENT:           "deepseek-v4-pro",   # ← 本 PR 修订 (V4-Flash → V4-Pro)
    RiskTaskType.EMBEDDING:            "deepseek-v4-flash",
    RiskTaskType.JUDGE:                "deepseek-v4-pro",
    RiskTaskType.RISK_REFLECTOR:       "deepseek-v4-pro",
}
```

```python
# backend/qm_platform/llm/types.py line 33-34
BULL_AGENT = "bull_agent"   # L2.3 V4-Pro (ADR-036, debate reasoning capability)
BEAR_AGENT = "bear_agent"   # L2.3 V4-Pro (ADR-036, debate reasoning capability)
```

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 沿用 V4-Flash | 5-02 sediment | ❌ 拒 — debate agent reasoning capability 需求, V4-Flash 轻量分类反足. V3§11.2 service cite 已 V4-Pro, internal drift. |
| (2) BULL→V4-Flash + BEAR→V4-Pro 不对称 | 反对称 mapping | ❌ 拒 — debate symmetry 反破, agent 路由层 0 logic 区分 BULL/BEAR reasoning |
| (3) BULL/BEAR → 新 V4-Mid alias (中等推理) | LiteLLM yaml 加新 alias | ❌ 拒 — DeepSeek 0 V4-Mid model, 反 yaml + router 加 alias 沿用 PR #221 sediment 体例 |
| **(4) BULL/BEAR → V4-Pro (本 ADR 采纳)** | 沿用 JUDGE + RISK_REFLECTOR 体例 | ✅ 采纳 — debate reasoning capability + V3§11.2 align + 修复 V3§5.5 internal drift + cost 仍 << $50 cap |

## Consequences

### Positive

- **debate reasoning capability 提升**: V4-Pro (deepseek-v4-pro = R1 reasoning) nuanced reasoning capability, 反 V4-Flash (deepseek-v4-chat 轻量分类). Bull/Bear 论据 / Judge 加权决策走 V4-Pro 沿用 reasoning 体例 (V3§5.5 + ADR-028 §2 反思 reasoning quality 体例延伸).
- **V3§5.5 align V3§11.2 修复 internal drift**: V3§11.2 line 1228 service cite 已 V4-Pro 5-02 sediment, V3§5.5 mapping table V4-Flash drift. 本 PR 沿用 V3§11.2 修订 V3§5.5, 修复 V3 internal drift.
- **0 caller 改 / 0 test 改**: TASK_TO_MODEL_ALIAS 走 dict get (audit.py + budget.py 引用), 反 hardcode mapping caller. test BULL/BEAR 走 enum 引用 (test_litellm_router_core.py:193), 反 hardcode mapping. mapping 改 router.py 真值 + 跟 PRIMARY_MODEL_SUBSTRINGS 沿用兼容 (反 alias 改).
- **cost 仍 << V3§20.1 #6 $50 cap**: BULL/BEAR daily 6 calls × 3K input + 1K output × 30 天 = ~$0.39/月 (V4-Pro full price) / ~$0.10/月 (75% discount 走 2026-05-31). 远低 $50 cap.

### Negative / Cost

- **cost +30% (V4-Flash $0.30/月 → V4-Pro $0.39/月 full price)**: 沿用 V3§19 cost 估算 patch. 远低 $50 cap, 0 risk break.
- **DeepSeek discount cliff 2026-05-31**: discount 后 cost 走 full price ~$0.39/月. user 决议 sediment 候选 (audit Week 2 batch).
- **BudgetGuard CAPPED_100 触发概率沿用 0 影响**: cost 远低 cap, 反触 CAPPED_100. PR #223 sediment.

### Neutral

- **router.py PRIMARY_MODEL_SUBSTRINGS 0 改**: alias `deepseek-v4-flash` + `deepseek-v4-pro` resolve substring 沿用 PR #221 sediment.
- **LiteLLM yaml 0 改**: model_list alias, 反加新 alias (反 V4-Mid 候选). yaml fallback chain PR #221 体例.
- **Sprint S12 (V3 line 1329) cite "L2 Bull/Bear 2-Agent debate (V4-Flash + V4-Pro Judge)" 0 patch**: Sprint 名 cite 沿用 5-02 sediment, 反 mapping detail. 走 audit Week 2 batch sediment 候选 (LL drift 候选).

## Implementation

| Step | scope | 接触方 | 时机 |
|---|---|---|---|
| Step 1 | router.py TASK_TO_MODEL_ALIAS line 60-61 patch (V4-Flash → V4-Pro) | CC (本 PR) | 5-06 ✅ |
| Step 2 | types.py BULL/BEAR comment line 33-34 patch | CC (本 PR) | 5-06 ✅ |
| Step 3 | V3§5.5 line 660/661/724 patch (mapping cite + cost) | CC (本 PR) | 5-06 ✅ |
| Step 4 | V3§19 line 1589 cost 估算 patch | CC (本 PR) | 5-06 ✅ |
| Step 5 | ADR-036 sediment (本 file) | CC (本 PR) | 5-06 ✅ |
| Step 6 | REGISTRY/README +1 row (ADR-036) | CC (本 PR) | 5-06 ✅ |
| Step 7 | test mock re-run verify (48 mock + 2 e2e + smoke 55) | CC (本 PR) | 5-06 ✅ |
| Step 8 | Sprint 2 implementation BULL/BEAR caller 真生产 verify | CC (Sprint 2 implementation 起手时) | 留 Step 5 user 决议 |

## References

- V3§5.5 (LiteLLM 路由层 mapping table) — 本 PR line 660/661/724 patch
- V3§11.2 (Service contract, MarketRegimeService line 1228) — V4-Pro, 本 PR align target
- V3§19 (cost 估算 line 1589) — 本 PR BULL/BEAR cost 重估
- ADR-020 (Claude 边界 + LiteLLM 路由, reserved) — V4 路由层走 LiteLLM Router 沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制) — V3 internal drift 走集中修订
- ADR-031 §6 (S2 LiteLLMRouter implementation path) — V4 路由层 mapping SSOT
- ADR-035 (智谱 News#1 + V4 路由层 0 智谱) — 单 PR 跟随 sediment
- LL-098 X10 (反 forward-progress default) — 本 PR 0 user 接触 implementation
- LL-119 候选 (memory cite vs 真生产 yaml/官网现役 cross-verify SOP) — 本 PR V3 internal drift 修复实证
- TradingAgents (5-Agent 反思模式, 沿用 V3§5.3 借鉴) — Bull/Bear/Judge debate 模式 reasoning capability cite source
- 5-06 user 决议 BULL/BEAR mapping V4-Flash → V4-Pro
- 5-06 Sprint 2 prerequisite Step 2.5 4 source cross-verify (V3 internal drift finding)
