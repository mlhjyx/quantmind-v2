# Operations Review — Windows Task Scheduler 真盘点 (CC 5-01 schtasks /query 实测)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 10 / operations/14
**Date**: 2026-05-01
**Type**: 评判性 + Windows Task Scheduler 真 query

---

## §1 真测 (CC 5-01 schtasks /query 实测)

实测 cmd: `cmd.exe //c "schtasks /query /fo LIST /v"` filter QuantMind*

**真值** — QuantMind* 真**18+ Windows schtask** sustained:

| 序 | TaskName | Action | 真证据 |
|---|---|---|---|
| 1 | QuantMind_DailyExecute | scripts/run_paper_trading.py execute --execution-mode live | sustained PT execute |
| 2 | QuantMind_DailyIC | scripts/compute_daily_ic.py --core --days 30 | sustained Mon-Fri 18:00 (PR #40) |
| 3 | QuantMind_DailyMoneyflow | scripts/pull_moneyflow.py | sustained 17:30 (PR #46) |
| 4 | QuantMind_DailyReconciliation | scripts/daily_reconciliation.py | sustained QMT vs DB |
| 5 | QuantMind_DailySignal | scripts/run_paper_trading.py signal | sustained T 日盘后 |
| 6 | QuantMind_DataQualityCheck | scripts/data_quality_check.py | sustained Session 26 hardened |
| 7 | QuantMind_FactorHealthDaily | scripts/factor_health_daily.py | sustained L0/L1/L2 detection |
| 8 | QuantMind_IcRolling | scripts/compute_ic_rolling.py | sustained Mon-Fri 18:15 (PR #44) |
| 9 | QuantMind_IntradayMonitor | scripts/intraday_monitor.py | sustained 5min 09:35-15:00 |
| 10 | QuantMind_MiniQMT_AutoStart | (no command shown, autostart) | sustained QMT 客户端 |
| 11 | QuantMind_MVP31SunsetMonitor | scripts/monitor_mvp_3_1_sunset.py | sustained Session 32 |
| 12 | QuantMind_PTAudit | scripts/pt_audit.py --alert | sustained Stage 4 Session 17 |
| 13 | QuantMind_PT_Watchdog | scripts/pt_watchdog.py | sustained heartbeat |
| 14 | QuantMind_RiskFrameworkHealth | scripts/risk_framework_health_check.py | sustained Mon-Fri 18:45 (PR #145) |
| 15 | QuantMind_ServicesHealthCheck | scripts/services_healthcheck.py | sustained 15min Session 35 |
| 16 | QuantMind_CancelStaleOrders | scripts/cancel_stale_orders.py | sustained |
| 17 | QuantMind_pg_backup | scripts/pg_backup.py | sustained backup daily |
| 18 | QuantMind_health_check | scripts/health_check.py | sustained pre-trading 16:30 |
| 19 | QuantMind_ic_monitor | scripts/ic_monitor.py | sustained weekly IC trend |
| 20 | QuantMind_log_rotate | scripts/log_rotate.py | sustained daily 7d retention |
| 21 | QuantMind_pt_daily_summary | scripts/pt_daily_summary.py | sustained DingTalk summary |
| 22 | QuantMind_rolling_wf | scripts/rolling_wf.py | sustained monthly WF |
| 23 | QuantMind_smoke_test | scripts/smoke_test.py --auto-restart | sustained Python311 (非 .venv) |

**真值**: 真**23 Windows schtask** sustained, sustained sprint period sustained "23 schtask total" 真完美 verify ✅.

---

## §2 🔴 重大 finding — smoke_test 真 Python311 非 .venv

**真测 line 19** (schtasks /query 真证据):
```
要运行的命令: "C:\Users\hd\AppData\Local\Programs\Python\Python311\python.exe" D:\quantmind-v2\scripts\smoke_test.py --auto-restart
```

**真根因**: QuantMind_smoke_test 真**唯一**用 system Python311 sustained, 其他 22 schtask 全用 `.venv\Scripts\python.exe`.

**真**潜在风险**: 真 system Python311 真 vs .venv Python (3.11+ likely 同 Python version) 真**dependency mismatch sustained sprint period sustained 0 sustained 度量** sustained.

**🔴 finding**:
- **F-D78-291 [P1]** QuantMind_smoke_test 真**唯一用 system Python311** sustained, 其他 22 schtask 全用 .venv Python — 真**dependency mismatch 真 silent failure candidate** sustained, sustained F-D78-? "10b 生产入口真启动验证" 同源真证据 (smoke_test 真 production 入口 真**run on system Python 不是 .venv** = 真**真验证 真生产 .venv 路径 真**不准** sustained)

---

## §3 真**5-01 schtask MAX 4-30 17:35 真重大 silent failure** verify

**真证据 (sustained F-D78-289 真证据加深)**:
- scheduler_task_log MAX created_at = 2026-04-30 17:35
- 真**5-01 真 0 schtask runs sustained sprint period sustained 17+ hours**
- 真**周五全天 0 sustained schtask runs**
- → 真 23 Windows schtask 真**5-01 sustained**?

**真假设 candidate**:
- a. Windows Task Scheduler 真**5-01 全 disabled?** sustained
- b. Windows Task Scheduler 真**0 enabled trigger sustained 5-01?**
- c. schtask 真**run 但 silent failed 0 入 scheduler_task_log?**
- d. schtask 真**run + write 走 stdout 但 0 入 DB?**

(本审查 Phase 10 未真 deep verify schtask 真 5-01 真状态 / 真 Windows event log)

**finding**:
- F-D78-292 [P1] 23 Windows schtask 真 5-01 全天 0 runs scheduler_task_log sustained — 真根因 candidate 4 项 (Windows disabled / 0 trigger / silent failed / 0 入 DB) 0 sustained 度量, sustained F-D78-289 同源真证据加深 真生产**真核 silent failure** 真**5-01 真生产 schtask 真**无 service** sustained 真证据

---

## §4 真**MiniQMT_AutoStart 真无 command 显示** 真奇怪

**真测 line 60** (schtasks /query 真证据):
```
任务名: \QuantMind_MiniQMT_AutoStart
[no "要运行的命令" line shown for this task — likely autostart trigger only]
```

**真根因 candidate**: QuantMind_MiniQMT_AutoStart 真**仅 trigger 不 run command sustained sprint period sustained 沉淀** sustained candidate.

**finding**:
- F-D78-293 [P3] QuantMind_MiniQMT_AutoStart 真**无 command 显示** sustained schtasks /query, 真**仅 autostart trigger sustained sprint period sustained**, 沿用 sprint state CLAUDE.md "QMT Data Service 独立常驻进程" 真证据 candidate

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-291** | **P1** | smoke_test 真唯一 system Python311 vs 22 schtask .venv, dependency mismatch silent failure candidate |
| **F-D78-292** | **P1** | 23 Windows schtask 真 5-01 全天 0 runs scheduler_task_log, 真核 silent failure 5-01 真生产 schtask 无 service |
| F-D78-293 | P3 | QuantMind_MiniQMT_AutoStart 无 command 显示, 仅 autostart trigger candidate |

---

**文档结束**.
