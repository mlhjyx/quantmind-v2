---
name: quantmind-v3-sprint-replan
description: V3 实施期 sprint 实际时长超 baseline 1.5x → CC 主动 push user (sprint 收口决议) + replan template. 沿用 Constitution §L0.4 timeline baseline + §L8.1 (c) 治理债累积超阈值. 反 silent 沿用 stale baseline.
trigger: sprint 超时|baseline 1.5x|replan|sprint 收口决议|治理债 累积|stage transition|超阈值|超 baseline|timeline 漂移|scope creep
---

# QuantMind V3 Sprint Replan SOP

## §1 触发条件

任一发生 → 必 invoke replan template + push user (反 silent 沿用 stale baseline):

- sprint 实际时长 > baseline × 1.5 (Constitution §L0.4 timeline baseline cite)
- 治理债累积超阈值 (sub-task creep / cross-sprint debt / governance gap)
- stage transition gate 不通过 (沿用 `quantmind-v3-sprint-closure-gate` skill, Constitution §L6.2 决议)
- Tier B / cutover 时间窗口需重谈 (Constitution §L8.1 (c) sprint 收口决议)

## §2 baseline cite (沿用 Constitution §L0.4)

V3 timeline baseline:

| scope | baseline cite source |
|---|---|
| V3 全周期 | progress report Part 4 cite (~12-16 周, Constitution §L0.4 sediment) |
| 单 sprint baseline | V3 §12.3 sprint 验收策略 (per sprint scope 决议时锁定) |
| stage baseline | Constitution §L0.2 5 gate (Stage 1-7 各自 closure criteria) |

## §3 replan template (沿用 Constitution §L0.4)

任 trigger 满足 → push user 6 块 replan template (沿用 §L8.4):

| 块 | scope |
|---|---|
| (1) 治理债 surface | 当前 sprint / stage 累积治理债 cite (sub-task creep / cross-sprint debt / governance gap) |
| (2) sub-task creep cite | 实际 sub-task vs 起手 plan 漂移度 cite + 漂移类型 (沿用 SESSION_PROTOCOL §3.3 5 类) |
| (3) remaining stage timeline 修订 | 剩余 stage timeline 重新估算 + 新 baseline 锁定 |
| (4) Tier B / cutover 时间窗口重谈 | 沿用 Constitution §L0.2 Gate C (Tier B) + Gate E (PT cutover) 时间窗口 |
| (5) replan trigger 真值 cite | 实际时长 / baseline / 漂移倍数 (CC 实测 cite source 4 元素) |
| (6) decision option | option A (sustained baseline) / B (修订 baseline) / C (sprint scope 缩减) / D (sprint 拆分) — user 决议 |

## §4 CC 主动 push 时机 (沿用 Constitution §L8.1 (c))

任 trigger 满足 → CC 主动 push user, 反等 user 触发:

- sprint 闭前 closure gate 不通过 (沿用 `quantmind-v3-sprint-closure-gate` skill, Constitution §L6.2 决议)
- sprint 实际超 baseline 1.5x (本 skill 主触发)
- 治理债累积超阈值 (本 skill + sprint-closure-gate skill 协同)
- stage transition gate 不通过 (本 skill + sprint-closure-gate skill 协同)

## §5 反 anti-pattern (沿用 LL-098 X10 + ADR-022)

❌ silent 沿用 stale baseline (反 LL-098 X10 forward-progress default — sprint 超时 不 surface, 沿用累积漂移)
❌ CC 自决 baseline 修订 (反 Constitution §L8.1 (c) — sprint 收口决议必 user 介入)
❌ silent skip replan template (反 6 块结构, 反 cite source 4 元素)

✅ 沿用 §L8.1 (c) — 任 sprint 收口决议必 user 介入 push template, CC 0 自决
✅ baseline 修订走 ADR-022 集中机制 (沿用反 silent overwrite — 新 baseline append-only sediment, 反整套 overwrite)
✅ replan template 走 6 块结构 (沿用 Constitution §L8.4 user 介入 push template)

## §6 跟 sprint-closure-gate skill 互补

| skill | 触发时机 | scope |
|---|---|---|
| `quantmind-v3-sprint-closure-gate` (沿用 Constitution §L6.2 sprint-closure-gate 决议) | sprint / stage **闭前** | 5 gate criteria 机器可验证清单 + push user gate 不通过时 |
| 本 skill (`quantmind-v3-sprint-replan`) | sprint **执行中** 时长超 baseline 1.5x / 治理债累积 | replan template + push user (sprint 收口决议) |

→ 闭前 vs 执行中 触发时机互补, 0 scope 重叠.

## §7 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| 现 9 hook 0 sprint timeline / replan trigger 机制层 (本 skill 0 hook 直接对应) | — |
| 本 skill (CC 主动 invoke 知识层) | sprint 执行中 CC 主动 monitor 时长 + 治理债 + 触发 push user template |

→ skill 是知识层, V3 期 0 全新 hook 对应 — 沿用 Constitution §L6.2 反 abstraction premature 决议.

## §8 实证 cite

| 实证 | scope |
|---|---|
| Constitution §L0.4 timeline baseline + replan trigger | baseline 1.5x SSOT 锚点 |
| Constitution §L8.1 (c) sprint 收口决议 user 介入 3 类 | replan trigger 时 user 介入 3 类决议 |
| Constitution §L8.4 user 介入 push template | 6 块 push user template SSOT |
| LL-098 X10 (反 forward-progress default) | 反 silent 沿用 stale baseline anti-pattern |
| ADR-022 (反 silent overwrite + 集中机制) | baseline 修订走 append-only, 反整套 overwrite |
