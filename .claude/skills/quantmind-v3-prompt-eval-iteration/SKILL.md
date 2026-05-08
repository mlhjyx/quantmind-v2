---
name: quantmind-v3-prompt-eval-iteration
description: V3 实施期 prompts/risk/*.yaml prompt eval methodology + V4-Flash → V4-Pro upgrade 决议. 沿用 V3 §3.2 NewsClassifier + §5.2 Bull/Bear + §5.3 RAG retrieval + §8.4 RiskReflector prompts cross-sprint eval iteration. 反 silent prompt drift.
trigger: prompts/risk|prompt iteration|prompt eval|V4-Flash|V4-Pro|model upgrade|prompt methodology|reflector_v1.yaml|news_classifier|prompt eval iteration|cost-driven upgrade
---

# QuantMind V3 Prompt Eval Iteration SOP

## §1 触发条件

任一发生 → 必走 prompt eval iteration SOP:

- prompts/risk/*.yaml 任一 yaml file 改动前 (V3 §3.2 / §5.2 / §5.3 / §8.4 prompt scope)
- V4-Flash → V4-Pro upgrade 决议 (cost-driven model upgrade trigger)
- prompt eval ≥1 round 沉淀触发 (Constitution §L10.4 Gate D criteria)
- cross-sprint prompt iteration cycle (e.g. S3 NewsClassifier prompt iteration → S12 Bull/Bear → S14 Reflector)

## §2 prompt scope SSOT (沿用 V3 设计 + Constitution §L6.2)

详见 `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` § respective sections + skeleton §5.4 prompts/risk eval / iteration. prompt scope 4 类:

| Sprint | prompt yaml scope | 起手 model |
|---|---|---|
| **S3** L0.2 NewsClassifier | `prompts/risk/news_classifier_v1.yaml` | V4-Flash (sentiment + reasoning) |
| **S12** L2 Bull/Bear 2-Agent debate | `prompts/risk/bull_bear_v1.yaml` (2 prompt) | V4-Pro (debate quality 高) |
| **S13** L2 RAG retrieval | `prompts/risk/rag_retrieval_v1.yaml` | V4-Flash (cost-sensitive) |
| **S14** L5 RiskReflector 5 维反思 | `prompts/risk/reflector_v1.yaml` | V4-Pro (5 维反思 quality 高) |

## §3 prompt eval methodology (沿用 V3 §15.6 合成场景 + skeleton §5.4)

每 prompt iteration 必走 5 步 eval methodology:

| 步 | scope |
|---|---|
| (1) baseline 锁定 | 起手 prompt + V4 model + 合成场景 fixture (V3 §15.6 ≥7 类) baseline 跑 |
| (2) iteration trigger 类型 | drift cite (LL-103 SOP-4 跨 system finding) / cost-driven (sustained ≤80% baseline 触发 V4-Pro→Flash) / quality-driven (false positive 累积 / false negative 累积) |
| (3) iteration scope 锁定 | 仅改 prompt yaml / 仅改 model / 双改 — sub-PR 起手时锁定 (反 silent scope creep) |
| (4) eval ≥1 round | 跑合成场景 fixture + 实际 News raw fixture + paper-mode 5d shadow eval (V3 S10 dry-run 期触发) |
| (5) ADR sediment | iteration 决议 ADR-XXX promote (CC 实测决议 next free 沿用 LL-105 SOP-6) — 反 silent overwrite (ADR-022) |

## §4 V4-Flash vs V4-Pro 路由决议 (沿用 V3 §5.5 + §16.2)

cost-driven model upgrade 决议体例:

| trigger | 路由方向 | 沿用 SSOT |
|---|---|---|
| sustained 月成本 ≤ V3 §16.2 上限 50% (1.5 month 持续) | candidate Pro upgrade (quality > cost) | V3 §16.2 + skeleton §5.8 |
| sustained 月成本 ≥ V3 §16.2 上限 80% (1 month 持续) | candidate Flash downgrade (cost > quality) | V3 §16.2 + Constitution §L10.4 Gate D |
| paper-mode 5d false positive ≥ baseline 1.5x | quality-driven Pro upgrade (反 cost-driven) | V3 §15.4 paper-mode 5d 验收 + §13.1 5 SLA |
| paper-mode 5d false negative ≥ baseline 1.5x | quality-driven Pro upgrade (反 cost-driven) | 同上 |

→ 任 model upgrade / downgrade 必走 ADR sediment (沿用 ADR-022 集中机制).

## §5 跟 prompt-design-laws skill 0 overlap (沿用 Constitution §L6.2 双 skill 决议)

| skill | scope |
|---|---|
| `quantmind-v3-prompt-design-laws` (batch 2 PR #273 sediment) | prompt 写出前 0 hardcoded 4 类决议 (Claude.ai vs CC 跨 system 沟通 prompt 设计) — sustained Constitution §L6.2 prompt-design-laws 决议 |
| 本 skill (`quantmind-v3-prompt-eval-iteration`) | prompts/risk/*.yaml prompt iteration methodology + V4-Flash → V4-Pro upgrade 决议 (LLM call effectiveness eval) — sustained Constitution §L6.2 prompt-eval-iteration 决议 |

→ 双 skill scope 0 overlap, sustained SSOT 锚点 cross-cite (反 inline cross-cite, 沿用 ADR-022).

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| 现 9 hook 0 prompt eval / iteration 直接 trigger 机制层 (本 skill 0 hook 直接对应) | — V3 期 0 全新 hook 沿用 ADR-022 反 abstraction premature |
| 本 skill (CC 主动 invoke 知识层) | prompt 改动前 / model upgrade 决议时 CC 主动 cite 5 步 eval methodology + 4 类 trigger 路由 |

→ skill 是知识层, V3 期 0 hook 对应 — 沿用 Constitution §L6.2 prompt-eval-iteration 决议.

## §7 跟 llm-cost-monitor skill 协同

| skill | trigger 时机 |
|---|---|
| `quantmind-v3-llm-cost-monitor` (沿用 Constitution §L6.2 llm-cost-monitor 决议) | LLM call cost 累积 / 月度 audit / V3 §16.2 上限 enforce |
| 本 skill (`quantmind-v3-prompt-eval-iteration`) | prompt iteration / cost-driven model upgrade 决议时 |

→ 双 skill cost-driven model upgrade 决议 scope 强相关, sustained SSOT 锚点 cross-cite (V3 §16.2 + skeleton §5.8 共同 SSOT).

## §8 实证 cite

| 实证 | scope |
|---|---|
| V3 §3.2 NewsClassifier (S3 prompt) | NewsClassifier v1 起手 model V4-Flash, prompt iteration cycle SSOT 锚点 |
| Constitution §L10.4 Gate D (prompts/risk eval ≥1 round) | 横切层 closure criteria 含 prompt eval iteration |
| skeleton §5.4 prompts/risk eval / iteration 横切层归属 | 跨 sprint sediment SSOT (S3 / S12 / S13 / S14 各 sprint 触发) |
| LL-098 X10 (反 forward-progress default) | iteration 决议必 user 介入 ADR sediment, 反 CC 自决 |
