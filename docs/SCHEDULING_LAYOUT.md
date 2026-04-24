# QuantMind V2 Scheduling Layout

> **F57/F58 Phase E (2026-04-16)**: 完整调度链路文档，版本控制 Windows Task Scheduler 配置。
> **更新规则**: 增删调度任务时同步更新本文件 (铁律 22)。
>
> ✅ **Session 32 (2026-04-24) 全量 reconcile**: 基于 `Get-ScheduledTask -TaskName 'QM-*','QuantMind_*'`
> 实测数据刷新, 对齐 `scripts/setup_task_scheduler.ps1` + 本地 Task Scheduler live state.
> PR #65 STALE WARNING 中标注的 "可疑停用 3 个" (QM-RollingWF/QM-ICMonitor/QM-PTDailySummary)
> 实测全部 Ready/Active, WARNING 已撤销并在 "已知问题" 区记录真实的 2 项活漂移.
>
> **Canonical Source of Truth 优先级**:
> 1. Windows Task Scheduler live state (实测 `Get-ScheduledTaskInfo` 是最终事实)
> 2. `scripts/setup_task_scheduler.ps1` (register script, 漂移时以 live 为准)
> 3. 本文件 + CLAUDE.md §调度链路 (展示文档, 漂移时反查 live 修正)

---

## 调度时间线 (北京时间, 工作日)

```
T-1 周日
04:00  [TS] QuantMind_MVP31SunsetMonitor → monitor_mvp_3_1_sunset.py (Weekly Sun, Session 32)
22:00  [CB] gp-weekly-mining       → mining_tasks.run_gp_mining (Celery Beat, Sunday)

T 日 (每日)
02:00  [TS] QM-DailyBackup         → pg_backup.py
02:00  [TS] QM-RollingWF           → rolling_wf.py (非交易日内部跳过)
06:00  [TS] QM-LogRotate           → log_rotate.py
09:00-14:55 [CB] intraday-risk-check → risk Framework 批 2 (MVP 3.1, Mon-Fri */5 9-14, 72 trigger/日)
09:35  [TS] QuantMind_IntradayMonitor → intraday_monitor.py (每5min 09:35-15:00)
14:30  [CB] risk-daily-check       → daily_pipeline 14:30 (MVP 3.1 批 1+3, PMSRule + CircuitBreakerRule)
15:40  [TS] QuantMind_DailyReconciliation → daily_reconciliation.py (⚠️ ps1 写 15:10 live 是 15:40, 见 Known #2)
16:25  [TS] QM-HealthCheck         → health_check.py
16:30  [TS] QuantMind_DailySignal  → run_paper_trading.py signal
17:30  [TS] QuantMind_DailyMoneyflow → pull_moneyflow.py (Session 24 shift 16:35→17:30)
17:30  [TS] QuantMind_FactorHealthDaily → factor_health_daily.py
17:35  [TS] QuantMind_PTAudit      → pt_audit.py --alert (Stage 4 Session 17)
17:35  [TS] QM-PTDailySummary      → pt_daily_summary.py (⚠️ 与 PTAudit 同时段, 见 Known #3)
18:00  [TS] QuantMind_DailyIC      → compute_daily_ic.py --core --days 30 (Weekly Mon-Fri, Session 22)
18:15  [TS] QuantMind_IcRolling    → compute_ic_rolling.py (Weekly Mon-Fri, Session 22)
18:30  [TS] QuantMind_DataQualityCheck → data_quality_check.py (Session 26 shift 17:45→18:30)
19:00  [CB] factor-lifecycle-weekly → factor_lifecycle_monitor (Celery Beat, Friday)
20:00  [TS] QM-ICMonitor           → ic_monitor.py (Weekly)
20:00  [TS] QuantMind_PT_Watchdog  → pt_watchdog.py

T+1 日
09:31  [TS] QuantMind_DailyExecute → run_paper_trading.py execute --execution-mode live
       (⚠️ 当前 Disabled, Session 10 P0-α 事件后暂停, 等 Stage 4.2 评估 reenable, 见 Known #1)

Logon 触发
*****  [TS] QuantMind_MiniQMT_AutoStart → XtMiniQmt.exe
```

**图例**: `[TS]` = Windows Task Scheduler, `[CB]` = Celery Beat

---

## 完整任务清单

### Windows Task Scheduler — Active / Ready (18, 实测 2026-04-24 21:50)

| 任务名 | 时间 | 频率 | 脚本 | 用途 | 依赖 |
|--------|------|------|------|------|------|
| QM-DailyBackup | 02:00 | Daily | `scripts/pg_backup.py` | PG数据库备份 | PostgreSQL |
| QM-RollingWF | 02:00 | Daily | `scripts/rolling_wf.py` | 滚动Walk-Forward验证 | PostgreSQL |
| QM-LogRotate | 06:00 | Daily | `scripts/log_rotate.py` | 日志轮转 | 无 |
| QuantMind_IntradayMonitor | 09:35 | Daily (每5min 09:35-15:00) | `scripts/intraday_monitor.py` | 盘中监控 (ps1 层, 与 MVP 3.1 批 2 Celery Beat 并存) | QMT, Redis |
| QuantMind_DailyReconciliation | **15:40** (live) | Daily | `scripts/daily_reconciliation.py` | QMT vs DB对账 + fill_rate | PostgreSQL, QMT |
| QM-HealthCheck | 16:25 | Daily | `scripts/health_check.py` | 盘前预检 | PostgreSQL, Redis |
| QuantMind_DailySignal | 16:30 | Daily | `scripts/run_paper_trading.py signal` | T日数据拉取+因子+信号 | PostgreSQL |
| QuantMind_DailyMoneyflow | **17:30** | Daily | `scripts/pull_moneyflow.py` | 资金流数据拉取 | Tushare, PostgreSQL |
| QuantMind_FactorHealthDaily | 17:30 | Daily | `scripts/factor_health_daily.py` | 因子衰减3级检测 | PostgreSQL |
| QuantMind_PTAudit | 17:35 | Daily | `scripts/pt_audit.py --alert` | PT 5-check 主动守门 (Stage 4 Session 17) | PostgreSQL |
| QM-PTDailySummary | 17:35 | Daily | `scripts/pt_daily_summary.py` | PT日报 (⚠️ 与 PTAudit 同时段, 见 Known #3) | PostgreSQL |
| QuantMind_DailyIC | 18:00 | Weekly (Mon-Fri) | `scripts/compute_daily_ic.py --core --days 30` | 每日增量 IC 入库 (铁律 11, Session 22 Part 2) | PostgreSQL |
| QuantMind_IcRolling | 18:15 | Weekly (Mon-Fri) | `scripts/compute_ic_rolling.py` | ic_ma20/60 rolling 刷新 (factor_lifecycle 依赖, Session 22 Part 8) | PostgreSQL |
| QuantMind_DataQualityCheck | **18:30** | Daily | `scripts/data_quality_check.py` | 数据巡检 (Session 26 shift 17:45→18:30, 脚本硬化 Session 26 LL-068) | PostgreSQL |
| QM-ICMonitor | 20:00 | Weekly | `scripts/ic_monitor.py` | IC监控告警 | PostgreSQL |
| QuantMind_PT_Watchdog | 20:00 | Daily | `scripts/pt_watchdog.py` | PT心跳监控 | PostgreSQL |
| QuantMind_MiniQMT_AutoStart | Logon | On logon | `XtMiniQmt.exe` | QMT客户端自启 | 无 |
| QuantMind_MVP31SunsetMonitor | **04:00 Sun** | Weekly (Sunday) | `scripts/monitor_mvp_3_1_sunset.py` | MVP 3.1 Sunset Gate A+B+C 周监控 (ADR-010 addendum Follow-up #5, Session 32 wire) | PostgreSQL |

### Windows Task Scheduler — Disabled (3)

| 任务名 | 脚本 | 原因 |
|--------|------|------|
| QM-SmokeTest | `scripts/smoke_test.py` | 一次性测试, 已完成 |
| QuantMind_CancelStaleOrders | `scripts/cancel_stale_orders.py` | 紧急撤单, 手动触发 |
| QuantMind_DailyExecute | `scripts/run_paper_trading.py execute --execution-mode live` | Session 10 P0-α 熔断 live 失效事件后暂停 (CLAUDE.md L549). 等 Stage 4.2 评估 reenable, 依赖 F14 自愈 + F19 phantom 清理 |

### 已删除历史 (ps1 残留 register 待清理)

| 任务名 | ps1 位置 | 删除时间 | 状态 |
|--------|---------|---------|------|
| QuantMind_DailyExecuteAfterData | Section 5 (已标注 "[已废除]") | Session 17 Stage 4 (2026-04-19) | ✅ ps1 已清 register, 手工 delete 已执行, ADR-008 P0-δ 污染源消除 |
| QuantMind_GPPipeline | Section 12 (L397-420, **仍有 Register 代码**) | 2026-04-16 (已知问题区) | ⚠️ Session 32+ TODO: ps1 需清 register 防下次 rerun 复活 |

### Celery Beat (5 活跃 + 2 历史)

| 任务名 | 时间 | 频率 | 函数 | 用途 | Session |
|--------|------|------|------|------|---------|
| risk-daily-check | 14:30 | Mon-Fri | `daily_pipeline.run_daily_risk_check` | MVP 3.1 批 1+3 PMSRule L1/L2/L3 + CircuitBreakerRule Hybrid adapter | 28/30 |
| intraday-risk-check | `*/5 9-14 * * 1-5` | 每5min (09:00-14:55, 72 trigger/日) | `daily_pipeline.run_intraday_risk_check` | MVP 3.1 批 2 IntradayPortfolioDrop3/5/8% + QMTDisconnectRule | 29/30 |
| factor-lifecycle-weekly | 19:00 | Friday | `mining_tasks.factor_lifecycle_monitor` | 因子生命周期状态判定 (active/warning/stale) | Phase 3 MVP A |
| gp-weekly-mining | 22:00 | Sunday | `mining_tasks.run_gp_mining` | GP因子挖掘 | F57/F58 |
| data-quality-report | (任务级) | Daily | `mining_tasks.data_quality_report` | 数据质量报告 | Session 21 |

**历史已废**:
- ~~pms-daily-check 14:30~~ — MVP 3.1 批 1 合并后取代 (ADR-010, 并入 risk-daily-check)

### Servy 常驻服务 (4)

| 服务名 | 描述 | 日志 |
|--------|------|------|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | logs/fastapi-std{out,err}.log |
| QuantMind-Celery | celery worker --pool=solo | logs/celery-std{out,err}.log |
| QuantMind-CeleryBeat | celery beat scheduler | logs/celery-beat-std{out,err}.log |
| QuantMind-QMTData | QMT数据同步 (60s interval) | logs/qmt-data-std{out,err}.log |

---

## 已知问题

### 当前开放 (Session 32+ 待解决)

1. **QuantMind_DailyExecute Disabled 待 reenable**
   - 状态: Disabled (Session 10 P0-α 熔断 live 失效事件后暂停)
   - 依赖: F14 自愈完成 (Session 20 ✅) + F19 phantom trade_log 清理 (Session 22 Part 3 ✅)
   - 阻塞项: Stage 4.2 独立评估门 (含 dry-run + 首日监控计划)
   - 目标 Session: Session 35+ 评估, 非紧急

2. **QuantMind_DailyReconciliation 时间漂移 ps1=15:10 vs live=15:40 (30 min)**
   - ps1 `$reconTrigger = New-ScheduledTaskTrigger -Daily -At "15:10"` (L232)
   - CLAUDE.md L16 调度链路: "15:10对账"
   - Task Scheduler live NextRun: 2026/4/25 15:40:00
   - 根因推测: 某次 Session 手工 `schtasks /change` 未同步 ps1 (无 session handoff 记录)
   - 影响: ps1 rerun 会 reset 回 15:10, 手工 15:40 配置会丢失
   - 建议: 实测 15:40 工作正常且对 T+0 settlement 延迟更合理 → 更新 ps1 + CLAUDE.md 对齐 15:40
   - 工作量: 小 PR (setup_task_scheduler.ps1 + CLAUDE.md 2 处 diff)

3. **QM-PTDailySummary + QuantMind_PTAudit 同 17:35 时段重复**
   - 2 任务同时触发, `QM-PTDailySummary` LastResult=1 (非 0 退出) 可能 PTAudit 已取代
   - 历史: Session 17 Stage 4 引入 PTAudit 作为 "5-check 主动守门", PTDailySummary 是 Session 17 前的老日报任务
   - 建议: 实测 `QM-PTDailySummary` 有无生产消费方 (前端 / 邮件告警), 若无 → disable + 独立 PR 清理 ps1/setup (ps1 实际并未 register 这条, 是历史遗留 schtask)
   - 工作量: 独立 PR (调查消费方 + disable/delete + 归档)

4. **QuantMind_GPPipeline ps1 残留 register 代码 (latent bug)**
   - Session 16 (2026-04-16) 已 `schtasks /delete` 删除活任务 (避 Celery Beat gp-weekly-mining 双触发)
   - 但 `scripts/setup_task_scheduler.ps1` L397-420 **仍有 Register-ScheduledTask 代码**, 下次 rerun 会复活
   - 建议: 独立 PR 从 ps1 删除 Section 12 + 头注 "废除历史" 区加记录
   - 工作量: 小 PR (~40 行删除 + 1 行头注记录)

5. **非交易日**: 大部分任务内部有交易日判断 (非交易日快速退出), 但 TS 层面没有节假日过滤 (历史已知)

### 已解决 (历史参考)

6. ~~重复任务 QuantMind_DailyBackup~~ — 已删除 (2026-04-16)
7. ~~重复任务 QuantMind_PTWatchdog (weekly)~~ — 已删除 (2026-04-16)
8. ~~GP 双触发 QuantMind_GPPipeline (TS)~~ — 活任务已删 (2026-04-16), 保留 Celery Beat `gp-weekly-mining` (但 ps1 register 残留见 #4)

---

## 交叉引用

- CLAUDE.md §调度链路 (L16): 每日链路文字描述, 本文件是对齐的完整任务清单
- `scripts/setup_task_scheduler.ps1`: Windows Task Scheduler Register script (canonical)
- `backend/app/tasks/beat_schedule.py`: Celery Beat 配置源码 (canonical)
- `docs/DEV_SCHEDULER.md`: 调度设计文档 (A股T1-T17 / 外汇FX1-FX11, 架构层)
- `docs/adr/ADR-010-addendum-cb-feasibility.md` §5: MVP 3.1 Sunset Gate 监控机制来源
- `memory/project_sprint_state.md`: 各 Session handoff 记录时间漂移事件
