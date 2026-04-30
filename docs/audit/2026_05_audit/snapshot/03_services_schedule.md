# 现状快照 — 服务 + 调度 (类 3)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 3 / snapshot/03
**Date**: 2026-05-01
**Type**: 描述性 + 实测证据 + 🔴 重大 finding

---

## §1 Servy 4 服务 真状态 (CC 5-01 04:16 实测)

| 服务 | 状态 | 实测命令 |
|---|---|---|
| QuantMind-FastAPI | Running ✅ | `D:/tools/Servy/servy-cli.exe status --name=QuantMind-FastAPI -q` |
| QuantMind-Celery | Running ✅ | 同上 |
| QuantMind-CeleryBeat | Running ✅ | 同上 |
| QuantMind-QMTData | Running ✅ | 同上 |

**判定**: ✅ Servy 4 服务全 Running (sprint state sustained ✅).

---

## §2 Celery Beat 调度 真状态 (实测 backend/app/tasks/beat_schedule.py)

### 2.1 真 active entries (CELERY_BEAT_SCHEDULE dict 实测)

| Entry | Schedule | Task |
|---|---|---|
| `gp-weekly-mining` | 周日 22:00 | `app.tasks.mining_tasks.run_gp_mining` |
| `outbox-publisher-tick` | 30s 高频 | `app.tasks.outbox_publisher.outbox_publisher_tick` |
| `daily-quality-report` | 工作日 17:40 | `daily_pipeline.data_quality_report` |
| `factor-lifecycle-weekly` | 周五 19:00 | `daily_pipeline.factor_lifecycle` |

**实测真 active = 4 entries** (sprint state Session 30 写 "5 schedule entries 生产激活" — 数字漂移)

### 2.2 PAUSED entries (sprint period 4-29 暂停)

| Entry | 暂停原因 |
|---|---|
| `risk-daily-check` | T1 sprint .env=paper / DB live 命名空间漂移 → 钉钉刷屏 (LL-081), 真金保护转挂 LIVE_TRADING_DISABLED=true broker 层 |
| `intraday-risk-check` | 同上理由, 5min 高频 72 次/日 钉钉刷屏更甚 |

### 2.3 历史移除 (2026-04-06 / sprint period)

- `daily-health-check` / `daily-signal` / `daily-execute` — 移给 Windows Task Scheduler (schtask)
- `pms-daily-check` — DEPRECATED (ADR-010, PMS 并入 Wave 3 MVP 3.1)
- `dual-write-check-daily` — 退役 (MVP 2.1c Sub3.5, 2026-04-18)

### 2.4 发现

**F-D78-7 [P2]** sprint state Session 30 写 "Risk Framework 5 schedule entries 生产激活" 数字漂移. 实测 active=4 (4-29 暂停 risk-daily-check + intraday-risk-check 后未及时更新 handoff).

---

## §3 Windows Task Scheduler (schtask) 真状态 (PowerShell `Get-ScheduledTask`)

### 3.1 active (Ready) — 13 entries

| TaskName | LastRun | LastResult | NextRun | 状态 |
|---|---|---|---|---|
| QM-DailyBackup | 2026/5/1 2:00 | **0** ✅ | 2026/5/2 2:00 | OK |
| QM-PTDailySummary | 2026/4/30 17:35 | **1** ⚠️ | 2026/5/1 17:35 | 失败 |
| QuantMind_DailyIC | 2026/4/30 18:00 | **0** ✅ | 2026/5/1 18:00 | OK |
| QuantMind_DailyMoneyflow | 2026/4/30 17:30 | **0** ✅ | 2026/5/1 17:30 | OK |
| QuantMind_DataQualityCheck | 2026/4/30 18:30 | **2** 🔴 | 2026/5/1 18:30 | 失败 (sprint state Session 24/25/26 hang REPRO 未修) |
| QuantMind_FactorHealthDaily | 2026/4/30 17:30 | **0** ✅ | 2026/5/1 17:30 | OK |
| QuantMind_IcRolling | 2026/4/30 18:15 | **0** ✅ | 2026/5/1 18:15 | OK |
| QuantMind_MiniQMT_AutoStart | 2026/4/29 14:07 | **0** ✅ | (no NextRun) | trigger 缺? |
| QuantMind_MVP31SunsetMonitor | 2026/4/26 4:00 | **0** ✅ | 2026/5/3 4:00 | OK (周一周三周五) |
| QuantMind_PTAudit | 2026/4/30 17:35 | **0** ✅ | 2026/5/1 17:35 | OK |
| QuantMind_PT_Watchdog | 2026/4/30 20:00 | **1** ⚠️ | 2026/5/1 20:00 | 失败 |
| QuantMind_RiskFrameworkHealth | 2026/4/30 18:45 | **1** ⚠️ | 2026/5/1 18:45 | 失败 (sprint period MVP 4.1 batch 2.1 PR #145+146 设计的 dead-man's-switch self-health) |
| QuantMind_ServicesHealthCheck | 2026/5/1 4:30 | **1** ⚠️ | 2026/5/1 4:45 | 失败 (15min 周期, 最新一次失败) |

### 3.2 Disabled — 5 entries

| TaskName | 状态 | 备注 |
|---|---|---|
| QuantMind_CancelStaleOrders | Disabled | 2026/4/2 LastRun (历史) |
| QuantMind_DailyExecute | Disabled | 沿用 PT 暂停 4-29 |
| QuantMind_DailyReconciliation | Disabled | T0-19 sustained known debt 同源? |
| QuantMind_DailySignal | Disabled | 沿用 PT 暂停 4-29 |
| QuantMind_IntradayMonitor | Disabled | 沿用 PT 暂停 4-29 |

---

## §4 🔴 重大 finding cluster — 5 schtask 持续失败

**F-D78-8 [P0 治理]** schtask silent failure cluster, sprint state handoff 完全未捕捉:

| Task | LastResult | sprint period 沿用假设 | 真值 |
|---|---|---|---|
| QM-PTDailySummary | 1 (失败) | 沿用 PR #167 PT 监控完整 | 4-30 17:35 失败, 5-01 17:35 next 仍配置 |
| QuantMind_DataQualityCheck | 2 (失败) | sprint state Session 24/25/26 提到 "hang REPRO 17:45" | 实测 18:30 trigger 仍 LastResult=2 失败 (与 sprint state 17:45 不符, 时点漂移) |
| QuantMind_PT_Watchdog | 1 (失败) | 沿用 sprint period MVP 4.1 batch 2 watchdog 沉淀 | 4-30 20:00 失败 |
| QuantMind_RiskFrameworkHealth | 1 (失败) | sprint period MVP 4.1 batch 2.1 PR #145+146 设计 18:45 dead-man's-switch self-health 完工 | **实测最新 4-30 18:45 LastResult=1 失败 — 自愈机制本身失败 silent failure!** |
| QuantMind_ServicesHealthCheck | 1 (失败) | sprint period MVP 4.1 batch 1 health check 沉淀 | **5-01 4:30 (~2 min ago) LastResult=1, 15min 周期, 持续失败** |

**判定**: 
- sprint period sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" — **真状态: 5/13 active schtask 失败 (38% 失败率), Observability 自身机制持续失败** 
- LL-098 第 13 次 stress test 同源风险 (forward-progress offer 反 anti-pattern) 印证: sprint state 沉淀"完工"仅停留在代码 merge, 真生产 enforce 持续失败
- **本审查 P0 治理 finding** (沿用 framework_self_audit §3.4): sprint period sustained "完工" 假设 重大推翻

---

## §5 schtask 真触发时间 vs sprint state handoff drift

sprint state Session 24 (4-22) 写: `DailyMoneyflow 16:35→17:30`, `DataQualityCheck 16:40→17:45`. 实测:
- DailyMoneyflow NextRun 17:30 ✅ (sustained)
- DataQualityCheck NextRun 18:30 (sprint state 17:45 漂移, 真 18:30)

**F-D78-11 [P3]** schtask trigger time 漂移 (DataQualityCheck sprint state 17:45 → 真 18:30, sprint period 后续未及时同步 handoff)

---

## §6 跨调度边界 (Beat + schtask 失败传播)

**调度边界 cross-validate**:
- Beat 4 active entries 状态? Servy CeleryBeat Running 但 entry 真 trigger 真值未实测 (留 sub-md 16_alert_trigger_history)
- schtask 13 active 中 5 持续失败 — 失败传播下游 (RiskFrameworkHealth 失败 → 风控自愈失败 → silent risk vacuum)

---

## §7 实测证据 cite

- 实测时间: 2026-05-01 04:32 (PowerShell Get-ScheduledTask)
- 实测命令:
  ```powershell
  Get-ScheduledTask | Where-Object { $_.TaskName -like '*Quant*' -or $_.TaskName -like '*Daily*' -or $_.TaskName -like '*IcRoll*' } | Select-Object TaskName, State, ...
  ```
- 实测 Beat: backend/app/tasks/beat_schedule.py 全文读 (123 行)

---

## §8 发现汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-7 | P2 | sprint state Session 30 "Risk Framework 5 schedule entries" 数字漂移 (实测 active=4) |
| F-D78-8 | **P0 治理** | 5 schtask 持续 LastResult=1/2 失败 cluster, sprint state handoff 未捕捉, sprint period sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" 重大假设推翻 |
| F-D78-11 | P3 | schtask trigger time 漂移 (DataQualityCheck sprint state 17:45 → 真 18:30) |

---

**文档结束**.
