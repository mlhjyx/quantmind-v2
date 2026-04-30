# Operations Review — 真账户对账 (CC 扩领域)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 4 / operations/01
**Date**: 2026-05-01
**Type**: 评判性 + 跨源 reconciliation (CC 主动扩领域, sustained framework_self_audit §3.1 D7)

---

## §0 元说明

framework_self_audit §3.1 D7 决议: "真账户对账 (broker 报告 vs cb_state 跨源 verify) — F-D78-4 sprint period 4-day stale 印证, 已纳入 §2.11 + §3.6 部分 cover, 但加深: 跨源 verify SOP".

本 md 是 CC 扩领域 - sustained framework 13 领域漏维度 (与"风控"+"运维"重叠但 cross-source verify 独立).

---

## §1 跨源 ground truth 真测 (CC 5-01 04:16 实测)

| 源 | 时间 | NAV/cash | positions | market_value |
|---|---|---|---|---|
| **xtquant 真账户 (broker)** | 5-01 04:16 | cash=¥993,520.66 | 0 | ¥0 |
| **circuit_breaker_state (DB)** | 4-30 19:48 (updated) | trigger_metrics.nav=¥993,520.16 | (字段无) | (字段无) |
| **position_snapshot (DB)** | max trade_date=4-27 | (字段无) | 19 持仓 / 70,600 股 | ¥901,554 |

---

## §2 真账户 vs cb_state 真一致性

| 维度 | 真值 vs DB | 一致性 |
|---|---|---|
| nav | xtquant=993,520.66 / cb_state=993,520.16 | ✅ 差 ¥0.50 (微小利息或费用, ≤ ¥10 阈值) |
| 时间戳 | xtquant 5-01 04:16 / cb_state 4-30 19:48 | ⚠️ 8.5h gap (4-30 update 后 0 update) |
| current_level | (broker 无) / cb_state=0 | (无 cross-validate 可能) |

**判定**: ✅ cb_state 与 broker 真值大致 sustained, 微小 nav drift (¥0.50) 在容忍范围内

---

## §3 真账户 vs position_snapshot 真一致性 🔴

| 维度 | 真值 vs DB | 一致性 |
|---|---|---|
| positions | xtquant=0 / position_snapshot.live max=19 | 🔴 严重 drift (差 19 持仓) |
| 时间戳 | xtquant 5-01 04:16 / position_snapshot max=4-27 | 🔴 4 trade days stale (4-27 → 5-01) |
| market_value | xtquant=¥0 / position_snapshot=¥901,554 | 🔴 差 ¥901,554 |

**判定**: 🔴 **严重 drift** — sprint period sustained "T0-19 known debt audit-only" sustained sustained, 但本审查实测**stale 仍 active 跨 4-30/5-01 双日**.

**真原因 candidate**:
- 4-29 PT 暂停后, position_snapshot 写入 path 0 触发 (沿用 sprint state Session 44 PT 暂停沉淀)
- DailyReconciliation schtask Disabled (snapshot/03_services_schedule §3.2)
- T0-19 sprint state "已 closed PR #168+#170" 仅代码层 closed, 真生产层未触发清 stale snapshot

---

## §4 跨源 verify SOP 真测 (sprint period sustained 0 SOP)

实测真值:
- broker (xtquant) → DB cb_state: ✅ 自动 update (sprint period 4-30 19:48 "PT restart gate cleanup" 沉淀)
- broker (xtquant) → DB position_snapshot: ❌ 0 自动 update (4-29 暂停后 stale 4 day)
- broker → DB 跨源 SOP: ❌ 0 sustained (本审查 grep / SQL 0 命中跨源 reconciliation runbook)

**finding**:
- F-D78-50 [P1] 跨源 reconciliation SOP 沉淀 0, broker (xtquant) → DB position_snapshot path 4-29 后 0 触发, sprint state sustained "T0-19 已 closed" 仅代码层

---

## §5 broker 视角 unknown unknowns (沿用 blind_spots/04 §1.1)

实测未深查:
- broker 端 4-29 -29% 跌停事件 alert 真触发? (vs 项目端 0 risk_event_log 30 day)
- broker 月报 / 季报 vs cb_state 真一致性
- broker 端真金分类 (已结算 vs 待结算 vs 冻结) vs cash 字段
- broker 合规标记 (个人账户 自动化 vs 监管)

**finding**:
- F-D78-35 (复) [P2] broker 视角看项目状态未深查

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-4 (复) | P2 | DB live position vs xtquant 真账户 4 trade days stale (T0-19 sustained) |
| **F-D78-50** | **P1** | 跨源 reconciliation SOP 沉淀 0, broker (xtquant) → DB position_snapshot path 4-29 后 0 触发, sprint state sustained "T0-19 已 closed" 仅代码层 |
| F-D78-35 (复) | P2 | broker 视角看项目状态未深查 |

---

**文档结束**.
