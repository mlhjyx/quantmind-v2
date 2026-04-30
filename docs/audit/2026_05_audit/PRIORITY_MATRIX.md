# PRIORITY_MATRIX — SYSTEM_AUDIT_2026_05

**目的**: 全 finding 严重度矩阵 (P0真金/P0治理/P1/P2/P3 5 级), 渐进式填充 (CC 每完成 sub-md 即追加).

**Status**: 🟡 渐进式填充中 (snapshot 5 sub-md done)

---

## 严重度定义 (沿用 GLOSSARY F)

| 级别 | 定义 | SOP |
|---|---|---|
| **P0 真金** | 真金 ¥993K 直接风险 | STOP 反问 user 立即 |
| **P0 治理** | 项目治理崩溃 / sprint period 重大假设推翻 | 沉淀 + (audit 末尾决议是否 STOP 反问 user 扩 scope) |
| **P1** | 重要, 影响下次 sprint period 决策 | 沉淀, audit 末尾汇总 |
| **P2** | 一般, 供战略对话参考 | 沉淀 |
| **P3** | 微小, sprint period anti-pattern 候选 | 沉淀 |

---

## P0 真金

(0 触发 — E5/E6 实测 sustained: LIVE_TRADING_DISABLED=True / EXECUTION_MODE=paper / xtquant 0 持仓 / cash=¥993,520.66.)

---

## P0 治理 ⚠️

| ID | 描述 | 来源 sub-md | 状态 |
|---|---|---|---|
| **F-D78-8** | **5 schtask 持续 LastResult=1/2 失败 cluster (PT_Watchdog / PTDailySummary / DataQualityCheck / RiskFrameworkHealth / ServicesHealthCheck), sprint period sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" 重大假设推翻. RiskFrameworkHealth (PR #145+146 设计的 dead-man's-switch self-health) 4-30 18:45 LastResult=1 自愈机制本身失败 silent failure. ServicesHealthCheck 5-01 4:30 (~2 min ago) LastResult=1 持续失败 (15min 周期).** | snapshot/03_services_schedule §4 | 待 EXECUTIVE_SUMMARY 高亮 |

---

## P1

(待审查中填充. 候选: 5 schtask 单独 root cause 分析可能促 P1 拆分.)

---

## P2

| ID | 描述 | 来源 sub-md | 状态 |
|---|---|---|---|
| F-D78-1 | sprint state handoff 数字漂移 (写 "DB 4-28 stale" 真值 max(trade_date)=2026-04-27, 错 1 天) | snapshot/07_business_state §4 | 沉淀 |
| F-D78-4 | DB live position vs xtquant 真账户 4 trade days stale (T0-19 sprint state sustained known debt, 仍 active) | snapshot/07_business_state §4 | 沉淀 |
| F-D78-5 | 根目录 *.md = 8, 多 3 个未授权 (PROJECT_ANATOMY / PROJECT_DIAGNOSTIC_REPORT / SYSTEM_RUNBOOK), CLAUDE.md §文件归属规则 reactive 治理失败 | snapshot/01_repo_inventory §2 | 沉淀 |
| F-D78-7 | sprint state Session 30 写 "Risk Framework 5 schedule entries 生产激活" 数字漂移 (实测 active=4 + 2 PAUSED) | snapshot/03_services_schedule §2.4 | 沉淀 |
| F-D78-10 | 死表 candidate margin_detail (902 MB / 0 live rows) + northbound_holdings (648 MB / 0 live rows), 未 deprecated 标记 | snapshot/02_db_schema §3 | 沉淀 |
| F-D78-13 | 项目 git 全 history 仅 90 day (741 commits 全集中近 90 day), bus factor 高风险 (单人项目 user 退出后 N 月接手者无 multi-year context) | snapshot/01_repo_inventory §3 | 沉淀 |

---

## P3

| ID | 描述 | 来源 sub-md | 状态 |
|---|---|---|---|
| F-D78-2 | sprint state handoff 用 `cb_state` 别名 + `source` 字段, 真表 `circuit_breaker_state` + `execution_mode` 字段 (alias 漂移, 不影响功能但影响 onboarding) | snapshot/07_business_state §2 + GLOSSARY C | 沉淀 |
| F-D78-3 | DINGTALK_SECRET=空 (signature 验签 disabled, 仅 keyword=xin 1 锁) | E5 实测 / 待 security 领域沉淀 | 沉淀中 |
| F-D78-9 | CLAUDE.md "factor_values hypertable 152 chunks" 数字漂移, 实测 chunk ID 已超 152 | snapshot/02_db_schema §1.3 | 沉淀 |
| F-D78-11 | schtask trigger time 漂移 (DataQualityCheck sprint state 17:45 → 真 18:30) | snapshot/03_services_schedule §5 | 沉淀 |
| F-D78-12 | xtquant cash 4-30 14:54 ¥993,520.16 → 5-01 04:16 ¥993,520.66, 差 ¥0.50 (微小利息或费用, 非 anomaly) | snapshot/07_business_state §4 | 沉淀 |
| F-D78-14 | docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md untracked draft, 与 PR #181 沉淀的 T1_3_RISK_FRAMEWORK_DECISION_DOC.md 关系 sprint state 未明确 | snapshot/01_repo_inventory §6 | 沉淀 |

---

## 统计 (渐进更新)

| 严重度 | 当前数 |
|---|---|
| P0 真金 | 0 |
| **P0 治理** | **1** ⚠️ |
| P1 | 0 |
| P2 | 6 |
| P3 | 6 |
| **小计** | **13** |

---

## sprint period sustained 假设推翻清单 (汇总)

按 sub-md 完成进度渐进更新:

| 假设 | 真值 | 来源 |
|---|---|---|
| sprint state Session 30 "Risk Framework 5 schedule entries 生产激活" | 实测 active=4 + 2 PAUSED (4-29 暂停) | F-D78-7 |
| sprint state Session 45 "DB 4-28 stale 19 行" | 实测 max(trade_date)=2026-04-27, 错 1 天 | F-D78-1 |
| sprint state Session 45 "T0-19 known debt audit-only" | 仍 active (本审查 4-30 + 5-01 实测仍未自愈) | F-D78-4 |
| **sprint state sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅"** | **5 schtask 持续 LastResult=1/2 失败, 含 RiskFrameworkHealth 自愈机制本身失败** | **F-D78-8** ⚠️ |
| CLAUDE.md "factor_values hypertable 152 chunks" | 实测 chunk ID 已超 152 (200+) | F-D78-9 |
| CLAUDE.md §文件归属规则 (根目录 7 上限) | 实测 8 (多 3 个未授权) | F-D78-5 |

---

**文档结束 (渐进填充中)**.
