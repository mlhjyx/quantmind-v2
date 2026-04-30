# D3.7 调度健康审计 — 2026-04-30

**Scope**: 16 schtask 完整状态 / Beat 4 active entries / scheduler_task_log 30 天 / schtask vs Beat 覆盖
**0 改动**: 纯 read-only schtasks /Query + SQL SELECT

---

## 1. Q7.1 16 schtask 完整状态 (实测)

| Name | Status | Last Run | LastResult | Next Run |
|---|---|---|---|---|
| QuantMind_CancelStaleOrders | Disabled | 4-2 9:05 | 0 | N/A |
| QuantMind_DailyExecute | Disabled | 4-19 9:31 | 0 | N/A |
| QuantMind_DailyIC | Ready | 4-29 18:00 | 0 | 4-30 18:00 |
| QuantMind_DailyMoneyflow | Ready | 4-29 17:30 | 0 | 4-30 17:30 |
| QuantMind_DailyReconciliation | Disabled | 4-28 15:40 | 0 | N/A |
| QuantMind_DailySignal | Disabled | 4-28 16:30 | 0 | N/A |
| **QuantMind_DataQualityCheck** | Ready | 4-29 18:30 | **2** | 4-30 18:30 |
| QuantMind_FactorHealthDaily | Ready | 4-29 17:30 | 0 | 4-30 17:30 |
| QuantMind_IcRolling | Ready | 4-29 18:15 | 0 | 4-30 18:15 |
| QuantMind_IntradayMonitor | Disabled | 4-29 10:25 | 0 | N/A |
| QuantMind_MiniQMT_AutoStart | Ready | 4-29 14:07 | 0 | N/A |
| QuantMind_MVP31SunsetMonitor | Ready | 4-26 4:00 | 0 | 5-3 4:00 |
| **QuantMind_PTAudit** | Ready | 4-29 17:35 | **1** | 4-30 17:35 |
| **QuantMind_PT_Watchdog** | Ready | 4-29 20:00 | **2** | 4-30 20:00 |
| **QuantMind_RiskFrameworkHealth** | Ready | 4-29 18:45 | **1** | 4-30 18:45 |
| **QuantMind_ServicesHealthCheck** | Ready | 4-30 15:45 | **2** | 4-30 16:00 |

**Disabled (5)**: CancelStaleOrders / DailyExecute / DailyReconciliation / DailySignal / IntradayMonitor — PT 暂停 5-task 包络 (D3-A Step 2 决策日志已 confirm)

**Ready 11 含 5 LastResult ≠ 0**:
- DataQualityCheck=2 (4-29 18:30 fail)
- PTAudit=1 (4-29 17:35 fail, D3-A Step 3 已分析为 alert_dedup raise)
- PT_Watchdog=2 (4-29 20:00 fail)
- RiskFrameworkHealth=1 (4-29 18:45 fail, MVP 4.1 batch 1 PR #146 wired)
- ServicesHealthCheck=2 (4-30 15:45 fail, 30 min ago)

→ **F-D3B-10 (P1)**: 5/11 schtask Ready 但 LastResult ≠ 0 (45% fail rate). D3-A Step 3 仅识别 PTAudit 1 例 (~33% scope 漂移). 全 5 例真因待 D3-C / 批 2 调查 (推测多与 alert_dedup / platform_metrics missing 联动 — F-D3A-1 P0).

---

## 2. Q7.2 Beat 4 active entries 健康度

D3-A Step 5 已实测 Beat 4 active entries:
- gp-weekly-mining (周日 22:00) — 4-30 周四不触发, 待 5-3 周日
- outbox-publisher-tick (30s) — 高频
- daily-quality-report (17:40 周一-五) — 待 4-30 17:40
- factor-lifecycle-weekly (周五 19:00) — 5-1 是周五 (五一假期? 待验证)

**Beat 4-30 15:35:51 restart 后** (PR #161): 实测 14:55 之后 0 stderr "primary source failed" — 注释生效.

**F-D3B-11 (P3)**: Beat 4 active entries 自 4-30 15:35:51 restart 后未跑过 daily-quality-report (Next 17:40), factor-lifecycle (周五), gp-weekly (周日). outbox-publisher-tick 跑了 ~120 次 (30s 周期 × 1h). 真健康度待 D3-C 整合 (4-30 18:00+ 观察 daily-quality-report 触发).

---

## 3. Q7.3 Beat schedule 注释段 git blame

`grep -E "PAUSE T1_SPRINT_2026_04_29" backend/app/tasks/beat_schedule.py` 实测 (D3-A Step 5 Q1(c) 已读):
- L59-73 risk-daily-check 注释
- L74-84 intraday-risk-check 注释
- L53-58 pms-daily-check deprecated (ADR-010 Session 21 2026-04-21)

git blame 推: 4-29 ~20:39 commit `626d343` (PR #150 link-pause T1-sprint), 注释延续 36h+ 至本 audit.

→ **F-D3B-12 (INFO)**: 注释延续 36h+, T1 sprint 期间正常. 取消注释 prerequisite 见 SHUTDOWN_NOTICE §9 (T0-15/16/17/18 修 + DB stale 清).

---

## 4. Q7.4 schtask vs Beat 任务覆盖

PT 主链分工:
| 时段 | 任务 | 调度 | 当前状态 |
|---|---|---|---|
| 09:31 | DailyExecute | schtask | Disabled |
| 14:30 | risk-daily-check | Beat | 注释 |
| */5 9-14 | intraday-risk-check | Beat | 注释 |
| 15:40 | DailyReconciliation | schtask | Disabled |
| 16:30 | DailySignal | schtask | Disabled |
| 17:30 | DailyMoneyflow / FactorHealthDaily | schtask | Ready |
| 17:35 | PTAudit | schtask | Ready (LastResult=1) |
| 17:40 | daily-quality-report | Beat | active |
| 18:00 | DailyIC | schtask | Ready |
| 18:15 | IcRolling | schtask | Ready |
| 18:30 | DataQualityCheck | schtask | Ready (LastResult=2) |
| 18:45 | RiskFrameworkHealth | schtask | Ready (LastResult=1) |
| 19:00 周五 | factor-lifecycle-weekly | Beat | active |
| 20:00 | PT_Watchdog | schtask | Ready (LastResult=2) |
| 周日 22:00 | gp-weekly-mining | Beat | active |
| 周日 04:00 | MVP31SunsetMonitor | schtask | Ready |

✅ 0 重复 (schtask 与 Beat 无同任务双调度)
⚠️ 4 schtask LastResult ≠ 0 (F-D3B-10)

**F-D3B-13 (INFO)**: PT 主链 schtask 仅 2 active (DailyMoneyflow / FactorHealthDaily) 写真路径, 其他 7 ops/audit ready 但 5 fail. PT 重启 gate 前 audit/health task 需先全绿.

---

## 5. Q7.5 scheduler_task_log 30 天分布

```sql
SELECT task_name, status, COUNT(*) FROM scheduler_task_log 
WHERE start_time > NOW() - INTERVAL '30 days' GROUP BY 1,2;
```

| task | status | runs | last |
|---|---|---|---|
| **intraday_risk_check** | **error** | **73** | 4-30 14:55 |
| risk_daily_check | retry | 2 | 4-30 14:31 |
| pending_monthly_rebalance | executed | 186 | 4-30 01:27 |
| pending_monthly_rebalance | expired | 93 | 4-30 01:27 |
| factor_health_daily | warning | 5 | 4-30 00:56 |
| intraday_risk_check | success | 9 | 4-29 14:55 |
| risk_daily_check | success | 1 | 4-29 14:30 |
| intraday_risk_check | disabled | 1 | 4-29 12:53 |
| risk_daily_check | disabled | 1 | 4-29 12:53 |
| pt_audit | success | 6 | 4-28 17:35 |
| signal_phase | success | 17 | 4-28 16:31 |
| reconciliation | success | 21 | 4-28 15:40 |

### F-D3B-14 (P0 cross-link D3-A Step 5)

**intraday_risk_check error 73 次** + last 4-30 14:55 — **直接证实 D3-A Step 5 F-D3A-NEW-6 PR #150 link-pause 失效** (Beat 跑旧 schedule cache 跑了 73 次失败). 4-30 14:55 是 last error trigger, 之后 PR #161 restart Beat 后停 (实测 stderr 0 entry 自 14:55).

**pending_monthly_rebalance 33% expired (93/279)** — D3-A Step 4 已知 (PT 暂停期间正常副作用).

**factor_health_daily warning 5** + risk_daily_check retry 2 — 待 D3-C / 批 2 调查 (低优).

---

## 6. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3B-10 | 5/11 Ready schtask LastResult ≠ 0 (D3-A Step 3 仅识 PTAudit 1 例, 33% scope 漂移). 真因推测 alert_dedup/platform_metrics missing | P1 |
| F-D3B-11 | Beat 4 active entries 4-30 15:35:51 restart 后健康度待 18:00+ 观察 | P3 |
| F-D3B-12 | Beat schedule 注释延续 36h+ T1 sprint 正常 | INFO |
| F-D3B-13 | PT 主链 schtask 2 active 真路径 + 5 audit/health LastResult≠0 (PT 重启 gate prerequisite) | INFO |
| **F-D3B-14** | **scheduler_task_log intraday_risk_check error 73 次实测证实 D3-A Step 5 F-D3A-NEW-6 PR #150 link-pause 失效** | **P0 cross-link** |

---

## 7. 处置建议

- **批 2 PR**: 修 5 LastResult≠0 schtask (alert_dedup migration apply 后预期 4 个自愈, 1 个 ServicesHealthCheck 待独立调查)
- **D3-C 整合**: F-D3B-11 4 active Beat 健康度真实测 (18:00+ 观察 daily-quality-report 触发)
- **PT 重启 gate prerequisite**: 全 schtask LastResult=0 + 全 Beat entry 健康
