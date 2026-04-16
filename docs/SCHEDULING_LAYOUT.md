# QuantMind V2 Scheduling Layout

> **F57/F58 Phase E (2026-04-16)**: 完整调度链路文档，版本控制 Windows Task Scheduler 配置。
> **更新规则**: 增删调度任务时同步更新本文件 (铁律 22)。

---

## 调度时间线 (北京时间, 工作日)

```
02:00  [TS] QM-DailyBackup         → pg_backup.py (daily)
02:00  [TS] QM-RollingWF           → rolling_wf.py (daily, 非交易日内部跳过)
02:00  [TS] QuantMind_GPPipeline   → run_gp_pipeline.py (weekly Sun)
06:00  [TS] QM-LogRotate           → log_rotate.py (daily)
09:31  [TS] QuantMind_DailyExecute → run_paper_trading.py execute --execution-mode live
09:35  [TS] QuantMind_IntradayMonitor → intraday_monitor.py (daily)
14:30  [CB] pms-daily-check        → daily_pipeline.pms_check (Celery Beat, Mon-Fri)
15:10  [TS] QuantMind_DailyReconciliation → daily_reconciliation.py (daily)
16:25  [TS] QM-HealthCheck         → health_check.py (daily)
16:30  [TS] QuantMind_DailySignal  → run_paper_trading.py signal
16:35  [TS] QuantMind_DailyMoneyflow → pull_moneyflow.py (daily)
16:40  [TS] QuantMind_DataQualityCheck → data_quality_check.py (daily)
17:05  [TS] QuantMind_DailyExecuteAfterData → run_paper_trading.py execute
17:30  [TS] QuantMind_FactorHealthDaily → factor_health_daily.py (daily)
17:35  [TS] QM-PTDailySummary      → pt_daily_summary.py (daily)
20:00  [TS] QM-ICMonitor           → ic_monitor.py (weekly)
20:00  [TS] QuantMind_PT_Watchdog  → pt_watchdog.py (daily)
22:00  [CB] gp-weekly-mining       → mining_tasks.run_gp_mining (Celery Beat, Sunday)
```

**图例**: `[TS]` = Windows Task Scheduler, `[CB]` = Celery Beat

---

## 完整任务清单

### Windows Task Scheduler — Active (19)

| 任务名 | 时间 | 频率 | 脚本 | 用途 | 依赖 |
|--------|------|------|------|------|------|
| QM-DailyBackup | 02:00 | Daily | `scripts/pg_backup.py` | PG数据库备份 | PostgreSQL |
| QM-RollingWF | 02:00 | Daily | `scripts/rolling_wf.py` | 滚动Walk-Forward验证 | PostgreSQL |
| QuantMind_GPPipeline | 02:00 | Weekly (Sun) | `scripts/run_gp_pipeline.py` | GP因子挖掘 | PostgreSQL, Redis |
| QM-LogRotate | 06:00 | Daily | `scripts/log_rotate.py` | 日志轮转 | 无 |
| QuantMind_DailyExecute | 09:31 | Daily | `scripts/run_paper_trading.py execute --execution-mode live` | T+1 调仓执行 | QMT, Redis, PostgreSQL |
| QuantMind_IntradayMonitor | 09:35 | Daily | `scripts/intraday_monitor.py` | 盘中监控 | QMT, Redis |
| QuantMind_DailyReconciliation | 15:10 | Daily | `scripts/daily_reconciliation.py` | 对账 | PostgreSQL, QMT |
| QM-HealthCheck | 16:25 | Daily | `scripts/health_check.py` | 盘前预检 | PostgreSQL, Redis |
| QuantMind_DailySignal | 16:30 | Daily | `scripts/run_paper_trading.py signal` | T日信号生成 | PostgreSQL |
| QuantMind_DailyMoneyflow | 16:35 | Daily | `scripts/pull_moneyflow.py` | 资金流数据拉取 | Tushare, PostgreSQL |
| QuantMind_DataQualityCheck | 16:40 | Daily | `scripts/data_quality_check.py` | 数据巡检 | PostgreSQL |
| QuantMind_DailyExecuteAfterData | 17:05 | Daily | `scripts/run_paper_trading.py execute` | 补充执行(数据到位后) | PostgreSQL |
| QuantMind_FactorHealthDaily | 17:30 | Daily | `scripts/factor_health_daily.py` | 因子健康检查 | PostgreSQL |
| QM-PTDailySummary | 17:35 | Daily | `scripts/pt_daily_summary.py` | PT日报 | PostgreSQL |
| QM-ICMonitor | 20:00 | Weekly | `scripts/ic_monitor.py` | IC监控告警 | PostgreSQL |
| QuantMind_PT_Watchdog | 20:00 | Daily | `scripts/pt_watchdog.py` | PT心跳监控 | PostgreSQL |
| QuantMind_MiniQMT_AutoStart | Logon | On logon | `XtMiniQmt.exe` | QMT客户端自启 | 无 |
| QuantMind_DailyBackup | 02:00 | Daily | `scripts/pg_backup.py` | **重复** (与 QM-DailyBackup) |  |
| QuantMind_PTWatchdog | 20:00 | Weekly | `scripts/pt_watchdog.py` | **重复** (与 PT_Watchdog) |  |

### Windows Task Scheduler — Disabled (2)

| 任务名 | 脚本 | 原因 |
|--------|------|------|
| QM-SmokeTest | `scripts/smoke_test.py` | 一次性测试, 已完成 |
| QuantMind_CancelStaleOrders | `scripts/cancel_stale_orders.py` | 紧急撤单, 手动触发 |

### Celery Beat (2)

| 任务名 | 时间 | 频率 | 函数 | 用途 |
|--------|------|------|------|------|
| pms-daily-check | 14:30 | Mon-Fri | `daily_pipeline.pms_check` | PMS阶梯利润保护 |
| gp-weekly-mining | 22:00 | Sunday | `mining_tasks.run_gp_mining` | GP因子挖掘 |

### Servy 常驻服务 (4)

| 服务名 | 描述 | 日志 |
|--------|------|------|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | logs/fastapi-std{out,err}.log |
| QuantMind-Celery | celery worker --pool=solo | logs/celery-std{out,err}.log |
| QuantMind-CeleryBeat | celery beat scheduler | logs/celery-beat-std{out,err}.log |
| QuantMind-QMTData | QMT数据同步 (60s interval) | logs/qmt-data-std{out,err}.log |

---

## 已知问题

1. **重复任务**: `QM-DailyBackup` 与 `QuantMind_DailyBackup` 都跑 `pg_backup.py` 在 02:00 → 建议删除其一
2. **重复任务**: `QuantMind_PTWatchdog` (weekly) 与 `QuantMind_PT_Watchdog` (daily) → 建议删除 weekly 版
3. **GP 双触发**: `QuantMind_GPPipeline` (TS Sunday 02:00) 与 `gp-weekly-mining` (CB Sunday 22:00) → 两处都触发 GP, 建议保留一处
4. **非交易日**: 大部分任务内部有交易日判断 (非交易日快速退出), 但 TS 层面没有节假日过滤

---

## 交叉引用

- CLAUDE.md §调度链路: `16:15数据拉取 → 16:25预检 → 16:30因子+信号 → 17:00-17:30收尾 → T+1 09:31执行 → 15:10对账`
- CLAUDE.md §Servy管理的服务: 4 个常驻服务
- `backend/app/tasks/beat_schedule.py`: Celery Beat 配置源码
- `docs/DEV_SCHEDULER.md`: 调度设计文档 (A股T1-T17 / 外汇FX1-FX11)
