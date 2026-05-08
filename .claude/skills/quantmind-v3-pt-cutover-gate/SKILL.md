---
name: quantmind-v3-pt-cutover-gate
description: V3 实施期 PT 重启 cutover gate (Gate E) checklist enforce — paper-mode 5d / 元监控 0 P0 / Tier A ADR / 5 SLA / 10 user 决议 5 sub-criteria verify. 反 silent skip + 反 .env paper→live CC 自决 mutation. user 显式授权前置 sustained.
trigger: PT 重启|PT cutover|Gate E|paper→live|.env paper|cutover prerequisite|paper-mode 5d|10 user 决议|5 SLA|cutover gate|cutover checklist
---

# QuantMind V3 PT Cutover Gate SOP

## §1 触发条件

任一发生 → 必走 PT cutover gate (Gate E) checklist (反 silent skip + 反 CC 自决 .env mutation):

- PT 重启 cutover 时机 (V3 全周期 Stage 7 critical path, 沿用 Constitution §L0.2 5 gate)
- Gate E pre-condition verify cycle (paper-mode 5d 跑期 + 后期持续 verify)
- user 显式 push "PT 重启" 触发时 (沿用 Constitution §L8.1 (b) 真生产红线 user 介入)

## §2 Gate E 5 sub-criteria SSOT (沿用 Constitution §L10.5 + §L6.2 pt-cutover-gate 决议)

详见 `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L10.5. Gate E 5 prerequisite (任一不通过 → STOP + push user, 反 CC 自决 .env mutation):

| # | criteria | verifier |
|---|---|---|
| (1) paper-mode 5d 通过 | V3 §15.4 paper-mode 5d 验收 — P0 alert 误报率 / L1 detection latency P99 / L4 STAGED 流程闭环 / 元监控 0 P0 元告警 | `quantmind-v3-tier-a-mvp-gate-evaluator` subagent (沿用 Constitution §L6.2 决议) |
| (2) 元监控 0 P0 | V3 §13 元监控 `risk_metrics_daily` 14 day 持续 0 P0 元告警 | 沿用 (1) verifier |
| (3) Tier A ADR 全 sediment | ADR-019 / ADR-020 / ADR-029 + Tier A 后续 ADR 全 committed (REGISTRY SSOT verify, 沿用 LL-105 SOP-6) | `quantmind-v3-sprint-closure-gate` skill (沿用 Constitution §L6.2 sprint-closure-gate 决议) Gate A criteria |
| (4) 5 SLA 满足 | V3 §13.1 5 SLA — L1 detection latency / News 6 源 / LiteLLM / DingTalk / STAGED 30min, CC 实测每项 | `quantmind-v3-tier-a-mvp-gate-evaluator` subagent |
| (5) 10 user 决议状态 verify | V3 §20.1 10 决议 closed PR #216 sediment, CC 实测 grep + cross-verify | `quantmind-v3-cite-source-lock` skill (沿用 Constitution §L6.2 cite-source-lock 决议) |

→ 5 sub-criteria 全 ✅ → trigger user 显式 .env paper→live 授权流程 (本 skill §3).

## §3 user 显式 .env paper→live 授权流程 (沿用 Constitution §L10.5 + §L8.1 (b))

5 sub-criteria 全 ✅ 后, **本 skill 0 自决 .env mutation** (反 CC 自决 — 真生产红线 user 介入).

user 显式授权 4 项 .env 改动 (本 skill 仅 sediment checklist + push user template, mutation 实际执行 user 手动):

| .env 字段 | 原值 | 改值 | scope |
|---|---|---|---|
| `LIVE_TRADING_DISABLED` | `true` | `false` | 解锁真发单路径 |
| `DINGTALK_ALERTS_ENABLED` | `false` | `true` | 解锁真生产告警 push |
| `EXECUTION_MODE` | `paper` | `live` | 切换 paper / live broker call 路由 |
| `L4_AUTO_MODE_ENABLED` | (V3 §17.2 双锁) | (user 决议) | sustained Constitution §L10.5 双锁体例 |

**0 自动 .env 改动** (沿用 ADR-022 反 anti-pattern + Constitution §L10.5). user 显式 push merge.

## §4 pre-cutover paper-mode 5d cycle (沿用 V3 §15.4)

paper-mode 5d 跑期 daily check (反 silent skip):

| daily | scope |
|---|---|
| Day 1-5 | sustained `EXECUTION_MODE=paper` / `LIVE_TRADING_DISABLED=true` |
| 每 day 闭后 | sediment 5 SLA 实测 row + 元监控 P0 alert count + L1 latency P99 + STAGED 流程 trigger count |
| Day 5 闭后 | 5 sub-criteria sustained verify, push user Gate E 决议 (沿用 Constitution §L8.4 6 块 push template) |

## §5 跟 sprint-closure-gate skill cross-cite (沿用 SSOT 锚点)

| skill | scope |
|---|---|
| `quantmind-v3-sprint-closure-gate` (batch 3 PR #274 sediment, 沿用 Constitution §L6.2 sprint-closure-gate 决议) | 5 gate 全覆盖 (Gate A / B / C / D / E), Gate E 是 5 之一 |
| 本 skill (`quantmind-v3-pt-cutover-gate`) | 仅 Gate E 详细 5 sub-criteria + user 显式授权流程 sediment |

→ 双 skill scope 互补 (sprint-closure-gate = 5 gate 全图, pt-cutover-gate = Gate E 详细). sustained SSOT 锚点 cross-cite, 反 inline cross-cite + 反 duplicate 5 sub-criteria 体例.

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/protect_critical_files.py` (PreToolUse[Edit\|Write] 现 wired) | `.env` / yaml file pattern auto block (沿用 Constitution §L6.2 4 现有扩展决议) |
| 本 skill (CC 主动 invoke 知识层) | PT 重启时机 / Gate E pre-condition verify cycle 期 CC 主动 cite 5 sub-criteria + user 显式授权流程 (反仅依赖 hook auto block) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution §L6.2 pt-cutover-gate 决议).

## §7 反 anti-pattern (沿用 LL-098 X10 + ADR-022 + Constitution §L10.5)

❌ CC 自决 .env paper→live mutation (反 Constitution §L8.1 (b) 真生产红线 user 介入)
❌ silent skip 5 sub-criteria verify (反 Constitution §L10.5 — 任一不通过 → STOP + push user)
❌ silent forward-progress offer cutover schedule (反 LL-098 X10 — sustained PR #171 4-30 实证 case)
❌ duplicate 5 sub-criteria inline body cite (反 SSOT 锚点 only, 沿用 sprint-closure-gate skill SSOT)

✅ 0 .env mutation 自决 — user 显式 push merge sustained
✅ 5 sub-criteria 全 ✅ 才 trigger user 授权流程 (反任一 silent skip)
✅ sustained SSOT 锚点 cross-cite sprint-closure-gate skill Gate E (反 duplicate inline)

## §8 实证 cite

| 实证 | scope |
|---|---|
| 2026-04-30 user 决议清仓 (SHUTDOWN_NOTICE_2026_04_30) | 17 股 emergency_close + 1 股 user GUI sell, PT 暂停 — Gate E 后续重启前置真账户 0 风险 |
| Constitution §L0.2 5 gate Gate E (PT cutover gate ✅) | Gate E SSOT 锚点 — V3 closure 终态 5 之一 |
| Constitution §L10.5 5 prerequisite | 5 sub-criteria 详细 SSOT |
| Constitution §L8.1 (b) 真生产红线 user 介入 | .env paper→live mutation user 显式授权 SSOT |
| LL-098 X10 (反 forward-progress default, PR #171 4-30 case) | 反 CC 自动 offer cutover schedule sustained |
| V3 §20.1 10 user 决议 closed PR #216 sediment | 5 sub-criteria #5 cross-verify SSOT 锚点 |
