# PRIORITY_MATRIX — SYSTEM_AUDIT_2026_05

**目的**: 全 finding 严重度矩阵 (P0真金/P0治理/P1/P2/P3 5 级), 渐进式填充 (CC 每完成 sub-md 即追加).

**Status**: 🟡 渐进式填充中

---

## 严重度定义 (沿用 GLOSSARY F)

| 级别 | 定义 | SOP |
|---|---|---|
| **P0 真金** | 真金 ¥993K 直接风险 | STOP 反问 user 立即 |
| **P0 治理** | 项目治理崩溃 / sprint period 重大假设推翻 | 沉淀 + STOP 反问 user 是否扩 scope |
| **P1** | 重要, 影响下次 sprint period 决策 | 沉淀, audit 末尾汇总 |
| **P2** | 一般, 供战略对话参考 | 沉淀 |
| **P3** | 微小, sprint period anti-pattern 候选 | 沉淀 |

---

## P0 真金 (sprint period sustained 真金保护 verify)

(待审查中填充. E5/E6 实测 sustained: LIVE_TRADING_DISABLED=True / EXECUTION_MODE=paper / xtquant 0 持仓 / cash=¥993,520.66 — 0 P0 真金触发. 后续 audit 中如发现 P0 真金 立即追加并 STOP 反问 user.)

---

## P0 治理

(待审查中填充. WI 0 framework_self_audit 0 P0 治理触发, sprint period 6 块基石待 governance/risk/operations 领域 review verify.)

---

## P1

(待审查中填充)

---

## P2

| ID | 描述 | 来源 sub-md | 状态 |
|---|---|---|---|
| F-D78-1 | sprint state handoff 数字漂移 (写 "DB 4-28 stale" 真值 max(trade_date)=2026-04-27, 错 1 天) | E1-E9 实测 / 待沉淀 governance | 沉淀中 |
| F-D78-4 | DB live position_snapshot vs xtquant 真账户 4 trade days stale (T0-19 sprint state sustained known debt, 仍 active) | E8 实测 / 待沉淀 operations | 沉淀中 |

---

## P3

| ID | 描述 | 来源 sub-md | 状态 |
|---|---|---|---|
| F-D78-2 | sprint state handoff 用 `cb_state` 别名 + `source` 字段, 真表 `circuit_breaker_state` + `execution_mode` 字段 (alias 漂移, 不影响功能但影响 onboarding) | E7 实测 / 待沉淀 governance | 沉淀中 |
| F-D78-3 | DINGTALK_SECRET=空 (signature 验签 disabled, 仅 keyword=xin 1 锁) | E5 实测 / 待沉淀 security | 沉淀中 |

---

## 统计 (渐进更新)

| 严重度 | 当前数 |
|---|---|
| P0 真金 | 0 |
| P0 治理 | 0 |
| P1 | 0 |
| P2 | 2 |
| P3 | 2 |
| **小计** | **4** |

---

**文档结束 (渐进填充中)**.
