---
name: quantmind-v3-sprint-closure-gate
description: V3 实施期 sprint 闭前 stage gate criteria 机器可验证清单 enforce. 沿用 Constitution §L10 5 gate (Tier A / T1.5 / Tier B / 横切层 / PT cutover) + V3 §12.3 sprint 验收 SSOT. 任一 gate criteria 不通过 → STOP + push user (sprint 收口决议).
trigger: sprint 闭前|stage gate|closure gate|gate criteria|sprint 验收|Tier A closed|Tier B closed|cutover gate|V3 §10|V3 §12.3|sprint 收口决议|sprint chain
---

# QuantMind V3 Sprint Closure Gate SOP

## §1 触发条件

任 sprint / stage 闭前 invoke (反 silent merge sprint 后 closure 检查):

- 任 V3 sprint S1-S15 闭前 (Constitution §L0.2 + §L10 5 gate trigger)
- 任 stage transition 前 (Constitution skeleton §4.2 stage 7 transitions)
- sprint 期 LL/ADR candidate sediment 决议时机 (反 sprint 内 silent skip)

## §2 5 gate criteria SSOT (沿用 Constitution §L10)

详见 `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L10. 任 gate trigger 必走对应 verifier:

| Gate | scope | verifier subagent (Constitution §L6.2) |
|---|---|---|
| **A: Tier A closed** | V3 §12.1 Sprint S1-S11 全 closed + paper-mode 5d ✅ + 元监控 0 P0 + Tier A ADR 全 committed | `quantmind-v3-tier-a-mvp-gate-evaluator` |
| **B: T1.5 closed** | V3 §11.4 backtest_adapter 实现 + 12 年 counterfactual replay 跑通 + WF 5-fold 全正 STABLE | `quantmind-risk-domain-expert` + `quantmind-v3-sprint-closure-gate-evaluator` |
| **C: Tier B closed** | V3 §12.2 Sprint S12-S15 全 closed + L2 Bull/Bear / RAG / RiskReflector production-active | `quantmind-risk-domain-expert` |
| **D: 横切层 closed** | V3 §13 元监控 + §14 失败模式 12 项 + §17.1 CI lint + prompts/risk eval ≥1 round | `quantmind-v3-sprint-closure-gate-evaluator` + `quantmind-v3-pt-cutover-gate` skill |
| **E: PT cutover gate ✅** | paper-mode 5d 通过 + 元监控 0 P0 + Tier A ADR 全 sediment + 5 SLA 满足 + 10 user 决议 verify + user 显式 .env paper→live 授权 | `quantmind-v3-pt-cutover-gate` skill |

## §3 sprint 闭前 closure checklist (沿用 Constitution skeleton §4.1 + V3 §12.3)

每 sprint 闭前必走机器可验证清单:

- [ ] V3 §12.3 测试策略 per Sprint 验收 (Unit ≥ baseline / Integration smoke / pre-push hook PASS / STATUS_REPORT 沉淀)
- [ ] sub-PR 全 closed (CC 实测 git log + PR # cite + ADR REGISTRY committed verify, 沿用 LL-105 SOP-6)
- [ ] 5/5 红线 sustained (沿用 `quantmind-v3-redline-verify` skill, Constitution §L6.2)
- [ ] sprint 期 LL append candidate / ADR-DRAFT row candidate sediment cite (沿用 ADR-022 反 silent overwrite)
- [ ] memory `project_sprint_state.md` handoff sediment (沿用铁律 37 + handoff_template.md)
- [ ] sprint 实际时长超 baseline 1.5x → STOP + push user replan (沿用 Constitution §L0.4 + `quantmind-v3-sprint-replan` skill)

任一不通过 → STOP + push user (sprint 收口决议, 沿用 Constitution §L8.1 (c)).

## §4 stage 7 transition gate (沿用 Constitution skeleton §4.2)

V3 实施 7 stage transition gate verifier:

| transition | gate criteria source |
|---|---|
| Stage 1 → Stage 2 (S4-S8) | S4 决议 closed + capacity expansion sub-PR closed (Constitution §L8.1 (a) user 介入) |
| Stage 2 → Stage 3 (S9-S11) | S5+S8 4-29 痛点 fix 主体闭环 (跌停 detection 秒级 + 决策权升级) |
| Stage 3 → Stage 4 (T1.5 12 年回测) | Gate A — Constitution §L10.1 |
| Stage 4 → Stage 5 (Tier B) | Gate B — Constitution §L10.2 |
| Stage 5 → Stage 6 (横切 §13-§17 显式 sprint 化) | Gate C — Constitution §L10.3 |
| Stage 6 → Stage 7 (PT 重启 critical path) | Gate D — Constitution §L10.4 |
| Stage 7 closed | Gate E — Constitution §L10.5 (user 显式 .env paper→live 授权) |

## §5 user 介入 push template (沿用 Constitution §L8.4)

任 gate criteria 不通过 → push user 6 块结构 (反 silent skip):

| 块 | scope |
|---|---|
| (1) 背景 | sprint / stage / sub-PR 当前真值 cite source 4 元素 |
| (2) 决议项 | option A / B / C 列举 + 我倾向 + 论据 |
| (3) 主动发现 | 识别到的盲区 / 跨域影响 / 未提决议项 |
| (4) 挑战假设 | 上次决议矛盾 cite + 当前决议是否需修正前决议 |
| (5) 边界 + 风险 | 真账户 / CC 误执行 / STOP 够吗 / 长期影响 |
| (6) 输出含 finding | sub-PR / sprint / stage closure status + next prompt 草稿 + STATUS_REPORT |

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/verify_completion.py` (Stop matcher, 现 wired) | sub-PR 闭后 doc 同步提醒 + (V3 期合并 sediment-poststop 扩展候选) |
| 本 skill (CC 主动 invoke 知识层) | sprint / stage 闭前 CC 主动 cite 5 gate criteria + 6 块 push user template (反仅依赖 hook 事后 reject) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution §L6.2 sprint-closure-gate 决议).

## §7 实证 cite

| 实证 | scope |
|---|---|
| Constitution §L0.2 5 gate sediment (5-08 PR #271 v0.2) | V3 closure 终态 5 gate SSOT 锚点 |
| skeleton §4.2 stage 7 transitions (5-08 PR #271 v0.1) | stage transition gate verifier mapping |
| LL-098 X10 (反 forward-progress default) | sprint 闭前 0 自动 offer next sprint, 等 user 显式触发 |
| Constitution §L8.1 (c) sprint 收口决议 user 介入 3 类 | gate 不通过时必 push user, 反 CC 自决 |
