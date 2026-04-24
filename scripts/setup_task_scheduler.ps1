# QuantMind V2 — Windows Task Scheduler 注册脚本
# 用法: 以管理员权限运行 PowerShell
#   powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
#
# 调度链路(优化后):
#   T日 06:00  QM-LogRotate                     日志轮转+7天保留
#   T日 02:00  QM-DailyBackup                   pg_dump备份
#   T日 16:25  QM-HealthCheck                   健康预检
#   T日 16:30  QuantMind_DailySignal             数据拉取(klines+basic+index)+因子+信号
#   T日 17:30  QuantMind_DailyMoneyflow          moneyflow补拉 (Session 24 shift 16:35→17:30, tushare moneyflow 16:30 前入库未稳定实测 5 retry 全空)
#   T日 18:30  QuantMind_DataQualityCheck        数据质量巡检 (Session 26 shift 17:45→18:30, 避开 17:30-18:15 dense window, cold-scan hang 事故后硬化)
#   T+1 09:31  QuantMind_DailyExecute            miniQMT执行; SimBroker无数据时跳过
#   T+1 15:10  QuantMind_DailyReconciliation      QMT vs DB对账 + fill_rate
#   T+1 17:30  QuantMind_FactorHealthDaily        因子衰减3级检测
#   T+1 17:35  QuantMind_PTAudit                 pt_audit 5-check 主动守门 (Stage 4 Session 17)
#   T日 18:00  QuantMind_DailyIC                 每日增量 IC 入库 (CORE, Session 22 Part 2, Mon-Fri)
#   T日 18:15  QuantMind_IcRolling               ic_ma20/60 rolling 刷新 (Session 22 Part 8, Mon-Fri, factor_lifecycle 周五依赖)
#
# 废除历史:
#   QuantMind_DailyExecuteAfterData (17:05) — Session 17 Stage 4 永久废除
#     原因: ADR-008 P0-δ paper 污染源 (无 --execution-mode 参数默认落 paper 命名空间)
#     替代: DailyReconciliation 15:10 + DailySignal 16:30 已覆盖盘后数据链路

$PythonExe = "D:\quantmind-v2\.venv\Scripts\python.exe"
$ProjectRoot = "D:\quantmind-v2"

# ── 1. QM-DailyBackup: 每日02:00 ──────────────────────
$backupAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\pg_backup.py" `
    -WorkingDirectory $ProjectRoot

$backupTrigger = New-ScheduledTaskTrigger -Daily -At "02:00"

$backupSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QM-DailyBackup" `
    -Description "QuantMind V2: pg_dump daily backup + 7-day rotation + monthly retention" `
    -Action $backupAction `
    -Trigger $backupTrigger `
    -Settings $backupSettings `
    -Force

Write-Host "[OK] QM-DailyBackup registered (daily 02:00)" -ForegroundColor Green

# ── 2. QM-HealthCheck: 每日16:25 ──────────────────────
$healthAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\health_check.py" `
    -WorkingDirectory $ProjectRoot

$healthTrigger = New-ScheduledTaskTrigger -Daily -At "16:25"

$healthSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QM-HealthCheck" `
    -Description "QuantMind V2: Pre-trading health check (before 16:30 signal generation)" `
    -Action $healthAction `
    -Trigger $healthTrigger `
    -Settings $healthSettings `
    -Force

Write-Host "[OK] QM-HealthCheck registered (daily 16:25)" -ForegroundColor Green

# ── 3. QuantMind_DailySignal: 每日16:30 ──────────────────
$signalAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_paper_trading.py signal" `
    -WorkingDirectory $ProjectRoot

$signalTrigger = New-ScheduledTaskTrigger -Daily -At "16:30"

$signalSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailySignal" `
    -Description "QuantMind V2: T日盘后数据拉取+因子计算+信号生成" `
    -Action $signalAction `
    -Trigger $signalTrigger `
    -Settings $signalSettings `
    -Force

Write-Host "[OK] QuantMind_DailySignal registered (daily 16:30)" -ForegroundColor Green

# ── 4. QuantMind_DailyExecute: 每日09:31 (QMT live模式) ──
$execAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_paper_trading.py execute --execution-mode live" `
    -WorkingDirectory $ProjectRoot

$execTrigger = New-ScheduledTaskTrigger -Daily -At "09:31"

$execSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyExecute" `
    -Description "QuantMind V2: T+1 09:31 miniQMT live执行(QMT未连接时跳过)" `
    -Action $execAction `
    -Trigger $execTrigger `
    -Settings $execSettings `
    -Force

Write-Host "[OK] QuantMind_DailyExecute registered (daily 09:31)" -ForegroundColor Green

# ── 5. [已废除 Session 17 Stage 4] QuantMind_DailyExecuteAfterData (17:05) ────────
# 废除原因: ADR-008 P0-δ paper 污染源 (原 --Argument "... execute" 无 --execution-mode 默认 paper)
# 替代: DailyReconciliation 15:10 + DailySignal 16:30 已覆盖盘后数据链路
# 手工清理 (已跑的机器需执行): schtasks /delete /tn "QuantMind_DailyExecuteAfterData" /f

# ── 6. QuantMind_DailyMoneyflow: 每日17:30 (Session 24 shift 16:35→17:30) ────
# 时段选择: tushare moneyflow 接口无官方 update time (daily_basic 15-17, daily
# 15-16). 实测 2026-04-22 16:35 schtask 5 retry × 120s 全空 + DingTalk 告警.
# docs/archive/PROGRESS.md 历史曾用 17:00 work. 17:30 保守稳妥, 对齐 Tushare
# 社区经验 17:00+ 稳定窗口.
# reviewer MEDIUM 采纳: 与 Section 10 FactorHealthDaily 同 17:30 触发, 表无交集
# (moneyflow_daily 写 vs factor_ic_history/factor_registry 读), 无锁无并发风险.
# 两 Python 进程 ~200MB + 2 DB conn, 32GB RAM 无压力.
$mfAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\pull_moneyflow.py" `
    -WorkingDirectory $ProjectRoot

$mfTrigger = New-ScheduledTaskTrigger -Daily -At "17:30"

$mfSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyMoneyflow" `
    -Description "QuantMind V2: Pull daily moneyflow data from Tushare" `
    -Action $mfAction `
    -Trigger $mfTrigger `
    -Settings $mfSettings `
    -Force

Write-Host "[OK] QuantMind_DailyMoneyflow registered (daily 17:30)" -ForegroundColor Green

# ── 7. QuantMind_DataQualityCheck: 每日18:30 (Session 26 shift 17:45→18:30) ──
# 时段选择: 避开 17:30-18:15 dense window (moneyflow/factor_health 17:30 + pt_audit 17:35 +
# daily_ic 18:00 + ic_rolling 18:15 = 5 task). 4-22/4-23 连 2 天 hang 事故根因为 17:45
# 冷启动 COUNT SQL 被并发 query 驱逐索引 out of shared_buffers → cold scan 17s → 超过
# PG statement_timeout=0 无上限 → schtask 5min kill. Session 26 fix 已硬化脚本 (60s
# timeout + per-step probe + future-date guard), 本 schtask 配合打散到 18:30 留 15min
# buffer 给 IcRolling 18:15 完成 + PG shared_buffers 稳定.
# ExecutionTimeLimit 5 → 10 min 增容: 未来 DB 增长 (目前 839M factor_values 行) 冷扫可能变慢,
# 10min 对 shared_buffers 冷况 safety 3x (60s statement_timeout × 3 checks × 3 tables).
$dqAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\data_quality_check.py" `
    -WorkingDirectory $ProjectRoot

$dqTrigger = New-ScheduledTaskTrigger -Daily -At "18:30"

$dqSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DataQualityCheck" `
    -Description "QuantMind V2: Data freshness and quality validation (Session 26 hardened)" `
    -Action $dqAction `
    -Trigger $dqTrigger `
    -Settings $dqSettings `
    -Force

Write-Host "[OK] QuantMind_DataQualityCheck registered (daily 18:30)" -ForegroundColor Green

# ── 8. QuantMind_IntradayMonitor: 09:35起每5分钟 ─────────
$imAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\intraday_monitor.py" `
    -WorkingDirectory $ProjectRoot

$imTrigger = New-ScheduledTaskTrigger -Daily -At "09:35"
$imTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At "09:35" `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Hours 5 -Minutes 25) `
).Repetition

$imSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_IntradayMonitor" `
    -Description "QuantMind V2: Intraday risk monitor every 5min (09:35-15:00)" `
    -Action $imAction `
    -Trigger $imTrigger `
    -Settings $imSettings `
    -Force

Write-Host "[OK] QuantMind_IntradayMonitor registered (09:35, every 5min)" -ForegroundColor Green

# ── 9. QuantMind_DailyReconciliation: 15:10 ──────────────
$reconAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\daily_reconciliation.py" `
    -WorkingDirectory $ProjectRoot

$reconTrigger = New-ScheduledTaskTrigger -Daily -At "15:10"

$reconSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyReconciliation" `
    -Description "QuantMind V2: QMT vs DB position reconciliation + fill_rate" `
    -Action $reconAction `
    -Trigger $reconTrigger `
    -Settings $reconSettings `
    -Force

Write-Host "[OK] QuantMind_DailyReconciliation registered (daily 15:10)" -ForegroundColor Green

# ── 10. QuantMind_FactorHealthDaily: 每日17:30 ───────────
$fhAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\factor_health_daily.py" `
    -WorkingDirectory $ProjectRoot

$fhTrigger = New-ScheduledTaskTrigger -Daily -At "17:30"

$fhSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_FactorHealthDaily" `
    -Description "QuantMind V2: Factor decay 3-level detection (L0/L1/L2)" `
    -Action $fhAction `
    -Trigger $fhTrigger `
    -Settings $fhSettings `
    -Force

Write-Host "[OK] QuantMind_FactorHealthDaily registered (daily 17:30)" -ForegroundColor Green

# ── 10b. QuantMind_PTAudit: 每日17:35 (Stage 4 主动守门) ─────
# C1 st_leak (P0) / C2 mode_mismatch (P1) / C3 turnover_abnormal (P1)
# C4 rebalance_date_mismatch (P2) / C5 db_drift (P1)
# 依赖链: DailySignal 16:30 → save_qmt_state ~17:00 → pt_audit 17:35 对齐 (C5 可查当日 snapshot)
$auditAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\pt_audit.py --alert" `
    -WorkingDirectory $ProjectRoot

$auditTrigger = New-ScheduledTaskTrigger -Daily -At "17:35"

$auditSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_PTAudit" `
    -Description "QuantMind V2: pt_audit 5-check post-trade guard + DingTalk aggregated alert (Stage 4 Session 17)" `
    -Action $auditAction `
    -Trigger $auditTrigger `
    -Settings $auditSettings `
    -Force

Write-Host "[OK] QuantMind_PTAudit registered (daily 17:35)" -ForegroundColor Green

# ── 10c. QuantMind_DailyIC: Mon-Fri 18:00 (Session 22 Part 2 — 铁律 11 gap 关闭) ─
# 每日增量 IC 入库 factor_ic_history (CORE 4: turnover_mean_20/volatility_20/bp_ratio/dv_ttm)
# 30 日 rolling 窗口 upsert, horizons=(5,10,20), 走 DataPipeline 铁律 17 合规
# 时段选择: 17:35 PTAudit 结束后留 25 min 缓冲; 20:00 PT_Watchdog 前 2h 余地
# 周六/日 skip (Mon-Fri): A 股非交易日 ic_calculator 无 forward return, 跑了也无效
# PR #37 (`31af40b`) 已交付 scripts/compute_daily_ic.py, 本条仅 wire schtask
$icAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\compute_daily_ic.py --core --days 30" `
    -WorkingDirectory $ProjectRoot

$icTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "18:00"

$icSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyIC" `
    -Description "QuantMind V2: Daily incremental IC upsert (CORE factors, 30-day rolling, Mon-Fri 18:00, Session 22)" `
    -Action $icAction `
    -Trigger $icTrigger `
    -Settings $icSettings `
    -Force

Write-Host "[OK] QuantMind_DailyIC registered (Mon-Fri 18:00)" -ForegroundColor Green

# ── 10d. QuantMind_IcRolling: Mon-Fri 18:15 (Session 22 Part 8 — factor_lifecycle 依赖刷新) ─
# ic_ma20/ic_ma60 rolling 刷新 factor_ic_history (pandas rolling 窗口 20/60, min_periods 5/10)
# PR #43 (`09b5e92`) 已交付 scripts/compute_ic_rolling.py, 本条仅 wire schtask
# 时段选择: 18:00 DailyIC 实测 1-2min 内跑完 (CORE 30-day incremental), 18:15 留 13 min buffer
#   充分 (Session 22 Part 7 实测 113 factors 全量重算仅 1.6s). 19:00 Celery Beat
#   factor-lifecycle-weekly Friday 触发前 45 min 缓冲, 确保 lifecycle 读到最新 ic_ma20/60.
# 周六/日 skip (Mon-Fri): rolling 纯幂等重算, 节假日跑也无害但浪费 schtask 资源 + 误告警
#   rolling 不依赖当日 forward return (区别 DailyIC), 但 ic_20d 由 DailyIC 产出 → Mon-Fri 对齐
# 数据链路: 18:00 DailyIC 写 ic_5d/10d/20d → 18:15 IcRolling 读 ic_20d 回算 ic_ma20/60
# 无 --core: default 读 factor_registry WHERE status IN ('active','warning') 282 factors,
#   其中实有 ic_20d 的 113 factors 进入 rolling, 余下 skip (内部逻辑已保证)
# reviewer MEDIUM 采纳: 删 RestartCount/RestartInterval (脚本幂等+0.7-1.6s, 失败下次周
# 期自愈 > 5min retry), 加 DontStopOnIdleEnd + AllowStartIfOnBatteries (对齐全文件
# 其他 14 section 一致性)
$irAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\compute_ic_rolling.py" `
    -WorkingDirectory $ProjectRoot

$irTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "18:15"

$irSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_IcRolling" `
    -Description "QuantMind V2: ic_ma20/ic_ma60 rolling refresh (factor_lifecycle dependency, Mon-Fri 18:15, Session 22 Part 8)" `
    -Action $irAction `
    -Trigger $irTrigger `
    -Settings $irSettings `
    -Force

Write-Host "[OK] QuantMind_IcRolling registered (Mon-Fri 18:15)" -ForegroundColor Green

# ── 11. QuantMind_PT_Watchdog: 每日20:00 ─────────────
$wdAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\pt_watchdog.py" `
    -WorkingDirectory $ProjectRoot

$wdTrigger = New-ScheduledTaskTrigger -Daily -At "20:00"

$wdSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_PT_Watchdog" `
    -Description "QuantMind V2: PT heartbeat watchdog — check daily execution" `
    -Action $wdAction `
    -Trigger $wdTrigger `
    -Settings $wdSettings `
    -Force

Write-Host "[OK] QuantMind_PT_Watchdog registered (daily 20:00)" -ForegroundColor Green

# ── 12. QuantMind_GPPipeline: 每周六02:00 ────────────
$gpAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_gp_pipeline.py --generations 50 --population 100 --islands 3 --output-dir $ProjectRoot\gp_results" `
    -WorkingDirectory $ProjectRoot

$gpTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "02:00"

$gpSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_GPPipeline" `
    -Description "QuantMind V2: GP Factor Mining Pipeline — weekly Saturday 02:00 (max 4h)" `
    -Action $gpAction `
    -Trigger $gpTrigger `
    -Settings $gpSettings `
    -Force

Write-Host "[OK] QuantMind_GPPipeline registered (Saturday 02:00)" -ForegroundColor Green

# ── 13. QM-LogRotate: 每日06:00 ─────────────────────
$lrAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\log_rotate.py" `
    -WorkingDirectory $ProjectRoot

$lrTrigger = New-ScheduledTaskTrigger -Daily -At "06:00"

$lrSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QM-LogRotate" `
    -Description "QuantMind V2: Daily log rotation + 7-day retention" `
    -Action $lrAction `
    -Trigger $lrTrigger `
    -Settings $lrSettings `
    -Force

Write-Host "[OK] QM-LogRotate registered (daily 06:00)" -ForegroundColor Green

Write-Host ""
Write-Host "Task Scheduler setup complete (15 tasks; Stage 4: -DailyExecuteAfterData +PTAudit; Session 22 Part 2: +DailyIC; Session 22 Part 8: +IcRolling). Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName 'QM-*','QuantMind_*' | Format-Table TaskName, State, LastRunTime"
