---
name: quantmind-v3-llm-cost-monitor
description: V3 实施期 LLM 月度 cost audit + 上限 + warn enforce (沿用 V3 §16.2 上限 + V3 §20.1 #6 ≥3 month 持续 ≤80% baseline). 反 silent cost overrun + 反 cost data 不足时 silent skip audit.
trigger: LLM 月成本|LLM cost|cost audit|cost cap|月度 audit|V3 §16.2|cost driven upgrade|cost ≤80%|cost baseline|warn enforce|llm_cost_daily|月度 review
---

# QuantMind V3 LLM Cost Monitor SOP

## §1 触发条件

任一发生 → 必走 LLM cost monitor SOP:

- LLM call cost 累积 (任 LiteLLM call sediment 入 `llm_cost_daily` 表后, sustained Sprint 1 PR #223 sediment)
- 月度 audit cycle (每月 1 日 / V3 §20.1 #6 月度 review cadence)
- V3 §16.2 上限 trigger (sustained 月成本 ≥ 上限 80% / 90% / 100% 三档 warn)
- cost-driven model upgrade 决议时机 (沿用 `quantmind-v3-prompt-eval-iteration` skill cross-cite SSOT)

## §2 cost SSOT (沿用 V3 §16.2 + Sprint 1 PR #223 sediment)

详见 `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §16.2 + Constitution §L6.2 llm-cost-monitor 决议. cost data 锚点:

| 数据源 | scope | sediment cite |
|---|---|---|
| `llm_cost_daily` 表 (PostgreSQL) | 每日 LLM call cost aggregate (model / task_type / cost_usd_total / token_count) | Sprint 1 PR #223 BudgetGuard sediment |
| `llm_call_log` 表 (PostgreSQL) | 单 call audit row (含 reasoning_tokens / cache_read / cache_write 详细) | Sprint 1 PR #224 LLMCallLogger sediment |
| `litellm_router.yaml` (config) | model baseline cost cite (V4-Flash / V4-Pro / Ollama qwen3:8b fallback) | Sprint 1 PR #221 LiteLLM SDK sediment |

## §3 月度 audit checklist (沿用 V3 §20.1 #6)

每月 1 日必走 audit checklist (反 silent skip):

- [ ] SQL aggregate `llm_cost_daily` 上月 total cost (CC 实测 SQL row count + sum + cite source 4 元素)
- [ ] cost vs V3 §16.2 上限 比对 (沿用 SSOT 锚点) — 三档 warn:
  - cost ≥ 上限 100% → STOP + push user (sprint 收口决议, Constitution §L8.1 (c))
  - cost ≥ 上限 80% → warn + cost-driven upgrade 决议 trigger (沿用 prompt-eval-iteration skill)
  - cost ≥ 上限 50% → log + sustained 1.5 month 后 candidate upgrade
- [ ] task_type breakdown (NewsClassifier / Bull/Bear / RAG / Reflector 各自 cost share — 沿用 V3 §3.2 / §5.2 / §5.3 / §8.4 SSOT)
- [ ] model breakdown (V4-Flash / V4-Pro / Ollama fallback 各自 cost share)
- [ ] cache hit rate (cache_read vs cache_write ratio, prompt caching 优化空间)
- [ ] sediment monthly audit row (sustained handoff_template + memory `project_sprint_state.md` cite)

## §4 ≥3 month 持续 baseline (沿用 V3 §20.1 #6 + Constitution §L10.4 Gate D)

V3 §20.1 #6 cite "≥3 month 持续 ≤80% baseline" — Gate D (横切层 closed) 5 prerequisite 之一:

| 状态 | scope |
|---|---|
| V3 实施期前期 (S1-S5, ~4-6 周) | cost data 不足 ≥3 month, audit candidate sediment 但 0 trigger Gate D 决议 |
| V3 实施期中期 (S6-S10, ~7-10 周) | cost data ≥1 month 累积, 月度 audit cycle 起手 |
| V3 实施期后期 (S11-S15, ~11-16 周) | cost data ≥3 month 累积候选, Gate D criteria 真测 verify |

→ V3 实施期前期 audit cycle 0 trigger ≥3 month 决议 (反 silent skip — 仍走月度 audit checklist 但 0 promote Gate D 决议).

## §5 cost-driven model upgrade trigger (沿用 prompt-eval-iteration skill cross-cite)

任 cost trigger 满足 → push prompt-eval-iteration skill 决议:

| trigger | 路由 |
|---|---|
| cost ≥ 上限 80% (1 month 持续) | V4-Pro → V4-Flash downgrade candidate (沿用 prompt-eval-iteration skill §4) |
| cost ≤ 上限 50% (1.5 month 持续) | V4-Flash → V4-Pro upgrade candidate (quality > cost) |

→ 沿用 V3 §16.2 + skeleton §5.8 共同 SSOT (反 inline cross-cite).

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| 现 9 hook 0 cost monitor / 月度 audit 直接 trigger 机制层 | — V3 期 0 全新 hook 沿用 ADR-022 反 abstraction premature |
| `QuantMind_LLMCostDaily` schtask (Mon-Fri 20:30, sustained Sprint 1 PR #224 sediment) | 自动 LLM cost daily aggregate (机制层) |
| 本 skill (CC 主动 invoke 知识层) | 月度 audit cycle / cost trigger 决议时 CC 主动 cite checklist + 三档 warn + cross-cite prompt-eval-iteration skill |

→ skill 是知识层, schtask 是机制层 (Windows ops 层, sustained `docs/runbook/cc_automation/` 体例). **互补不替代** (沿用 Constitution §L6.4).

## §7 反 anti-pattern (沿用 LL-098 X10 + ADR-022)

❌ silent skip 月度 audit (反 LL-098 X10 forward-progress default — 沿用 stale cost data 0 surface)
❌ CC 自决 model upgrade / downgrade (反 Constitution §L8.1 (c) sprint 收口决议必 user 介入 ADR sediment)
❌ silent skip Gate D criteria verify (反 Constitution §L10.4 — V3 实施期后期必 ≥3 month cost data verify)

✅ V3 实施期前期 audit cycle 沿用月度 checklist (反 silent skip 因 cost data 不足)
✅ ≥3 month baseline 沿用 V3 §20.1 #6 SSOT (反凭印象 cite)
✅ cost-driven upgrade 决议走 prompt-eval-iteration skill cross-cite (反 inline 决议)

## §8 实证 cite

| 实证 | scope |
|---|---|
| Sprint 1 PR #223 BudgetGuard + llm_cost_daily 表 sediment | cost data SSOT 锚点 |
| Sprint 1 PR #224 LLMCallLogger + audit + daily aggregate | 月度 audit data 锚点 |
| Sprint 1 PR #225 Ollama runbook + ollama_chat fallback | cost-saving fallback path SSOT (反 V4 cost overrun) |
| QuantMind_LLMCostDaily schtask (Mon-Fri 20:30 Ready, sustained Session 51 v7 sediment) | 自动 daily aggregate 机制层 |
| Constitution §L10.4 Gate D (LLM 月成本 ≤ V3 §16.2 上限 ≥3 month 持续 ≤80% baseline) | Gate D closure criteria 5 prerequisite 之一 |
