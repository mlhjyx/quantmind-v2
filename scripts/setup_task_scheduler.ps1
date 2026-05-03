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
#   T+1 15:40  QuantMind_DailyReconciliation      QMT vs DB对账 + fill_rate (Session 36 PR-DRECON: 15:10→15:40 align T+0 settle delay)
#   T+1 17:30  QuantMind_FactorHealthDaily        因子衰减3级检测
#   T+1 17:35  QuantMind_PTAudit                 pt_audit 5-check 主动守门 (Stage 4 Session 17)
#   T日 18:00  QuantMind_DailyIC                 每日增量 IC 入库 (CORE, Session 22 Part 2, Mon-Fri)
#   T日 18:15  QuantMind_IcRolling               ic_ma20/60 rolling 刷新 (Session 22 Part 8, Mon-Fri, factor_lifecycle 周五依赖)
#   T日 18:45  QuantMind_RiskFrameworkHealth     Risk Framework Beat dead-man's-switch (Session 44 Step E, Mon-Fri, PR #145)
#   周日 04:00  QuantMind_MVP31SunsetMonitor      MVP 3.1 Sunset Gate A+B+C 周监控 (Session 32 wire, ADR-010 addendum Follow-up #5)
#   每 15min   QuantMind_ServicesHealthCheck     4 Servy 服务 + CeleryBeat 心跳监控 (Session 35 wire, LL-074 fix)
#
# 废除历史:
#   QuantMind_DailyExecuteAfterData (17:05) — Session 17 Stage 4 永久废除
#     原因: ADR-008 P0-δ paper 污染源 (无 --execution-mode 参数默认落 paper 命名空间)
#     替代: DailyReconciliation 15:40 + DailySignal 16:30 已覆盖盘后数据链路
#   QuantMind_GPPipeline (Sat 02:00) — Session 16 (2026-04-16) 活任务删除, Session 32 (2026-04-24) 同步清 ps1 register
#     原因: 与 Celery Beat gp-weekly-mining (Sun 22:00) 双触发 (SCHEDULING_LAYOUT.md 已知问题 #4 / Session 16 已解决 #3)
#     替代: Celery Beat gp-weekly-mining Sunday 22:00 (backend/app/tasks/beat_schedule.py)
#     清理经过: 活任务 2026-04-16 `schtasks /delete /tn QuantMind_GPPipeline /f` 执行, ps1 register
#       代码 L397-420 遗留至 2026-04-24 Session 32 发现 (PR #65 general-audit 实测 live 无此 task).
#       若不清理, 下次 rerun setup_task_scheduler.ps1 会复活双触发.

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

# Session 36 PR-DEXEC reviewer MEDIUM 修复: pre-Register state probe, 防 operator-enabled 被覆写.
# 若 pre-Register state=Ready, 视为 Stage 4.2 解锁后 operator 主动 Enable, 保留不动.
# 若 pre-Register state=Disabled / 任务不存在, 维持 Disabled 默认 (governance bug 修复主路径).
$preRegisterState = (Get-ScheduledTask -TaskName "QuantMind_DailyExecute" -ErrorAction SilentlyContinue).State

Register-ScheduledTask `
    -TaskName "QuantMind_DailyExecute" `
    -Description "QuantMind V2: T+1 09:31 miniQMT live执行(QMT未连接时跳过). Stage 4.2 评估前默认 Disabled." `
    -Action $execAction `
    -Trigger $execTrigger `
    -Settings $execSettings `
    -Force

# Session 36 PR-DEXEC (2026-04-25): Stage 4.2 评估前默认 Disabled, 防 ps1 rerun silent 复活.
# 与 PR-DRECON (15:10/15:40 漂移修复) 同 governance pattern: ps1 + live 状态对齐文档意图.
# 解锁 reenable: 见 SCHEDULING_LAYOUT.md Known #1 Stage 4.2 评估 checklist.
# reviewer LOW 修复: -ErrorAction Stop 防 Register 部分失败时 Disable 静默吞错 (铁律 33 fail-loud).
if ($preRegisterState -eq "Ready") {
    Write-Host "[WARN] QuantMind_DailyExecute registered (daily 09:31) — kept Enabled (operator-set State=Ready preserved, Stage 4.2 unlock detected)" -ForegroundColor Cyan
} else {
    Disable-ScheduledTask -TaskName "QuantMind_DailyExecute" -ErrorAction Stop | Out-Null
    Write-Host "[OK] QuantMind_DailyExecute registered (daily 09:31, Disabled — 等 Stage 4.2 评估)" -ForegroundColor Yellow
}

# ── 5. [已废除 Session 17 Stage 4] QuantMind_DailyExecuteAfterData (17:05) ────────
# 废除原因: ADR-008 P0-δ paper 污染源 (原 --Argument "... execute" 无 --execution-mode 默认 paper)
# 替代: DailyReconciliation 15:40 + DailySignal 16:30 已覆盖盘后数据链路
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

# ── 9. QuantMind_DailyReconciliation: 15:40 ──────────────
$reconAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\daily_reconciliation.py" `
    -WorkingDirectory $ProjectRoot

$reconTrigger = New-ScheduledTaskTrigger -Daily -At "15:40"

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

Write-Host "[OK] QuantMind_DailyReconciliation registered (daily 15:40)" -ForegroundColor Green

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

# ── 10e. QuantMind_RiskFrameworkHealth: Mon-Fri 18:45 (Session 44 Step E — Beat dead-man's-switch) ─
# 消费 Phase 2 PR #144 写入的 scheduler_task_log → 检测 Beat / Celery worker silent 挂掉.
# 4 类 finding (per task): missing P0 / errored P1 / stale P1 / under_count P1 → DingTalk.
# **不走 Celery Beat — 要监控 Celery 自己挂的场景, 不能依赖被监控对象** (设计核心约束).
# 时段选择:
#   - 18:15 IcRolling 实测 0.7-1.6s (Mon-Fri), 15 min 缓冲足够
#   - 19:00 Friday Celery Beat factor-lifecycle-weekly 前 15 min 余地
#   - 14:30 risk_daily_check + */5 9-14 intraday 全部已跑完 (4h+ buffer)
# Mon-Fri 仅: 周末非交易日 risk task 自动 skipped, monitor 检查无意义 (only false-positive 风险)
# 脚本 earliest_check_utc_hour: risk_daily=6 (14:00 CST), intraday=2 (10:00 CST)
#   18:45 CST = 10:45 UTC, 远超两个阈值, 无 too-early 误报
# ExecutionTimeLimit 5 min: 脚本实测 < 2s, 主体是 2 SQL queries + 1 optional DingTalk
# PR #145 (`c560580`+`1b2ee0a`) 已交付 scripts/risk_framework_health_check.py, 本条仅 wire schtask
$rfhAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\risk_framework_health_check.py" `
    -WorkingDirectory $ProjectRoot

$rfhTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "18:45"

$rfhSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_RiskFrameworkHealth" `
    -Description "QuantMind V2: Risk Framework Beat dead-man's-switch — scheduler_task_log audit 消费 + DingTalk P0/P1 (Mon-Fri 18:45, Session 44 Step E, PR #145)" `
    -Action $rfhAction `
    -Trigger $rfhTrigger `
    -Settings $rfhSettings `
    -Force

Write-Host "[OK] QuantMind_RiskFrameworkHealth registered (Mon-Fri 18:45)" -ForegroundColor Green

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

# ── 12. [已废除 Session 16 2026-04-16 + Session 32 清 ps1 Register] QuantMind_GPPipeline ───
# Sat 02:00 ps1 register 原与 Celery Beat gp-weekly-mining Sun 22:00 双触发. Session 16 活任务
# schtasks /delete, 保留 Celery Beat 单一 GP 入口 (backend/app/tasks/beat_schedule.py).
# Session 32 (2026-04-24) PR #66 从 ps1 删除 Register 代码防下次 rerun 复活 (SCHEDULING_LAYOUT.md
# 已知问题 #4 关闭).

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

# ── 14. QuantMind_MVP31SunsetMonitor: 周日04:00 (Session 32 — ADR-010 addendum Follow-up #5) ──
# MVP 3.1 Risk Framework 批 3 adapter live 后 Sunset Gate A+B+C 周监控.
# 满足任一条件 (A 30日+真事件 / B L4审批跑通 / C Wave 4 启动) 发钉钉推荐启动批 3b
# (inline 重审消铁律 31 例外 + DROP 老 circuit_breaker_state/log 表).
# 时段选择: 周日 04:00 低峰, 1/week 频次足够 (Sunset Gate 天粒度判定, 条件 A 最早
#   2026-05-24 满足 = adapter live 2026-04-24 + 30日). 避开 02:00 QM-DailyBackup
#   + 06:00 QM-LogRotate (GPPipeline Sat 02:00 ps1 task 已废除 Session 32, Celery Beat
#   gp-weekly-mining Sun 22:00 距本 task 周日 04:00 有 18h gap). 独立窗口无资源竞争.
# 脚本硬化: scripts/monitor_mvp_3_1_sunset.py (PR #64 交付, 铁律 43 4项硬化:
#   PG statement_timeout=30s / FileHandler delay=True (stdout-only 实际豁免) /
#   boot stderr probe / 顶层 try/except exit=2). 钉钉 notifications 表去重
#   (category='mvp_3_1_sunset_gate') 防重复告警.
# exit code: 0=未到 sunset / 1=可启动 批 3b / 2=error (铁律 43 d)
$sunsetAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\monitor_mvp_3_1_sunset.py" `
    -WorkingDirectory $ProjectRoot

$sunsetTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "04:00"

$sunsetSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_MVP31SunsetMonitor" `
    -Description "QuantMind V2: MVP 3.1 Sunset Gate A+B+C weekly monitor (Session 32, ADR-010 addendum Follow-up #5)" `
    -Action $sunsetAction `
    -Trigger $sunsetTrigger `
    -Settings $sunsetSettings `
    -Force

Write-Host "[OK] QuantMind_MVP31SunsetMonitor registered (weekly Sunday 04:00)" -ForegroundColor Green

# ── 15. QuantMind_ServicesHealthCheck: 每 15min 24/7 (Session 35 — LL-074) ──
# 4 Servy 服务 (FastAPI/Celery/CeleryBeat/QMTData) + celerybeat-schedule.dat
# 心跳新鲜度 (10min stale 阈值) 监控. PT_Watchdog 1/日 (20:00) 检测频次远不够 —
# Session 34 抓出 CeleryBeat 04-24 19:26 → 04-25 02:20 静默死亡 ~7h 0 logs 0 检测,
# Monday 4-27 09:00 首次生产触发 + 14:30 risk-daily-check 全 missed 风险.
# 本任务 1/15min = 96/日, 检测延迟 ≤ 15min, 钉钉 dedup 1h 防 spam.
# 时段选择: 24/7 (含周末), Beat 凌晨死亡也要 15min 内告警, 不限交易日.
# 不开 PG conn (核心设计): PG 挂时本脚本仍能告警, 不被 PG 拖死.
# 脚本硬化: scripts/services_healthcheck.py (铁律 43:
#   (a) N/A 无 PG conn (b) FileHandler delay=True (c) boot stderr probe
#   (d) 顶层 try/except → exit 2). file-based dedup (logs/services_healthcheck_state.json).
# exit code: 0=ok / 1=degraded(已发或 dedup) / 2=fatal (铁律 43 d)
$svcAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\services_healthcheck.py" `
    -WorkingDirectory $ProjectRoot

# 起点 = 当前时间 + 60min 后截到整点 (next o'clock), Repetition 每 15min, 持续 indefinite.
# Reviewer code-P1 fix (Session 35): 原 `(Get-Date).AddMinutes(15).Date.AddHours((Get-
# Date).AddMinutes(15).Hour + 1)` 在 23:47-23:59 时段触发跨日 bug — `now+15min` 跨午夜
# 后 `.Date` = 次日 0 点, `.Hour` = 0, `+1 = 1`, 起点 = 次日 01:00 (45min gap, 漏首次).
# 新公式: AddMinutes(60) 强制跨过当前分钟到下一整点, ToString 截 HH:00:00 后 ParseExact
# 反序列化, 跨日由 AddMinutes 自动处理 ([datetime] 类型支持负数+跨日).
$svcStartBoundary = [datetime]::ParseExact(
    (Get-Date).AddMinutes(60).ToString("yyyy-MM-dd HH:00:00"),
    "yyyy-MM-dd HH:00:00",
    $null
)
$svcTrigger = New-ScheduledTaskTrigger -Once -At $svcStartBoundary `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$svcSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_ServicesHealthCheck" `
    -Description "QuantMind V2: Servy 4 services + CeleryBeat heartbeat 15min monitor (Session 35, LL-074 fix)" `
    -Action $svcAction `
    -Trigger $svcTrigger `
    -Settings $svcSettings `
    -Force

Write-Host "[OK] QuantMind_ServicesHealthCheck registered (every 15min, 24/7)" -ForegroundColor Green

# ── 16. QuantMind_LLMCostDaily: Mon-Fri 20:30 (Session 51 PR #224 — S2.3 LLM 成本 daily aggregate) ──
# 沿用决议 6 (a) S5 退役合并 S2.3 — daily aggregate report + DingTalk push (V3 §16.2 cite).
# 时段选择 (沿用 S2.3 plan-mode finding 17:30 真冲突 — DailyMoneyflow + FactorHealthDaily 占用):
#   - 20:30 真 PT_Watchdog 20:00 后 30min, 全 dense window (17:30-18:45) 后 0 资源争抢
#   - 反 17:30 (cadence 真 2 task 占用, table 无交集但本 LLM 路径无表交集风险)
# Mon-Fri 仅: A 股非交易日 LLM 路径 (Bull/Bear/Judge cadence) 真无活动, 周末跑只产 0 row 噪声.
# Action: scripts/llm_cost_daily_report.py (沿用 compute_daily_ic.py 体例, 铁律 41/43 d).
# DingTalk push: webhook_url 0 set 时真 noop (沿用决议 (I) stub 反 break local dev).
$llmcostAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\llm_cost_daily_report.py" `
    -WorkingDirectory $ProjectRoot

$llmcostTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "20:30"

$llmcostSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "QuantMind_LLMCostDaily" `
    -Description "QuantMind V2: LLM cost daily aggregate report + DingTalk push (Session 51 PR #224, S2.3 沿用决议 6 (a) S5 退役合并)" `
    -Action $llmcostAction `
    -Trigger $llmcostTrigger `
    -Settings $llmcostSettings `
    -Force

Write-Host "[OK] QuantMind_LLMCostDaily registered (Mon-Fri 20:30)" -ForegroundColor Green

Write-Host ""
Write-Host "Task Scheduler setup complete (17 tasks; Stage 4: -DailyExecuteAfterData +PTAudit; Session 22 Part 2: +DailyIC; Session 22 Part 8: +IcRolling; Session 32 PR #65: +MVP31SunsetMonitor; Session 32 PR #66: -GPPipeline ps1 register; Session 35: +ServicesHealthCheck; Session 51 PR #224: +LLMCostDaily). Verify with:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName 'QM-*','QuantMind_*' | Format-Table TaskName, State, LastRunTime"
