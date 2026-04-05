# QuantMind V2 — Windows Task Scheduler 注册脚本
# 用法: 以管理员权限运行 PowerShell
#   powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
#
# 调度链路(优化后):
#   T日 02:00  QM-DailyBackup                   pg_dump备份
#   T日 16:25  QM-HealthCheck                   健康预检
#   T日 16:30  QuantMind_DailySignal             数据拉取(klines+basic+index)+因子+信号
#   T日 16:35  QuantMind_DailyMoneyflow          moneyflow补拉(信号不依赖,但因子挖掘需要)
#   T日 16:40  QuantMind_DataQualityCheck        数据质量巡检(全表时效+行数验证)
#   T+1 09:00  QuantMind_DailyExecute            miniQMT执行; SimBroker无数据时跳过
#   T+1 15:10  QuantMind_DailyReconciliation      QMT vs DB对账 + fill_rate
#   T+1 17:05  QuantMind_DailyExecuteAfterData   SimBroker执行(收盘数据可用后)
#   T+1 17:30  QuantMind_FactorHealthDaily        因子衰减3级检测

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

# ── 4. QuantMind_DailyExecute: 每日09:00 (QMT live模式) ──
$execAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_paper_trading.py execute --execution-mode live" `
    -WorkingDirectory $ProjectRoot

$execTrigger = New-ScheduledTaskTrigger -Daily -At "09:00"

$execSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyExecute" `
    -Description "QuantMind V2: T+1 09:00 miniQMT live执行(QMT未连接时跳过)" `
    -Action $execAction `
    -Trigger $execTrigger `
    -Settings $execSettings `
    -Force

Write-Host "[OK] QuantMind_DailyExecute registered (daily 09:00)" -ForegroundColor Green

# ── 5. QuantMind_DailyExecuteAfterData: 每日17:05 ────────
$execAfterAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_paper_trading.py execute" `
    -WorkingDirectory $ProjectRoot

$execAfterTrigger = New-ScheduledTaskTrigger -Daily -At "17:05"

$execAfterSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DailyExecuteAfterData" `
    -Description "QuantMind V2: SimBroker模式T+1日17:05执行(收盘数据可用后)" `
    -Action $execAfterAction `
    -Trigger $execAfterTrigger `
    -Settings $execAfterSettings `
    -Force

Write-Host "[OK] QuantMind_DailyExecuteAfterData registered (daily 17:05)" -ForegroundColor Green

# ── 6. QuantMind_DailyMoneyflow: 每日16:35 ───────────────
$mfAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\pull_moneyflow.py" `
    -WorkingDirectory $ProjectRoot

$mfTrigger = New-ScheduledTaskTrigger -Daily -At "16:35"

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

Write-Host "[OK] QuantMind_DailyMoneyflow registered (daily 16:35)" -ForegroundColor Green

# ── 7. QuantMind_DataQualityCheck: 每日16:40 ─────────────
$dqAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\data_quality_check.py" `
    -WorkingDirectory $ProjectRoot

$dqTrigger = New-ScheduledTaskTrigger -Daily -At "16:40"

$dqSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_DataQualityCheck" `
    -Description "QuantMind V2: Data freshness and quality validation" `
    -Action $dqAction `
    -Trigger $dqTrigger `
    -Settings $dqSettings `
    -Force

Write-Host "[OK] QuantMind_DataQualityCheck registered (daily 16:40)" -ForegroundColor Green

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

Write-Host ""
Write-Host "Task Scheduler setup complete. Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName 'QM-*','QuantMind_*' | Format-Table TaskName, State, LastRunTime"
