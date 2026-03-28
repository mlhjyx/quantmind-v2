# 注册 pg_dump 每日自动备份到 Task Scheduler (R6 §6.1)
# 任务名: QuantMind-PG-Backup
# 每日凌晨 02:00 执行，保留7天，月初额外保留到monthly/
#
# 用法（管理员 PowerShell）:
#   .\scripts\register_backup_task.ps1
#   .\scripts\register_backup_task.ps1 -RunAsSystem   # 以 SYSTEM 账户运行

param(
    [switch]$RunAsSystem
)

$taskName    = "QuantMind-PG-Backup"
$pythonPath  = "D:\quantmind-v2\.venv\Scripts\python.exe"
$scriptPath  = "D:\quantmind-v2\scripts\pg_backup.py"
$workDir     = "D:\quantmind-v2"
$logPath     = "D:\quantmind-v2\logs\backup_task.log"

# 确保日志目录存在
New-Item -ItemType Directory -Force -Path "D:\quantmind-v2\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "D:\quantmind-v2\backups\daily" | Out-Null
New-Item -ItemType Directory -Force -Path "D:\quantmind-v2\backups\monthly" | Out-Null
New-Item -ItemType Directory -Force -Path "D:\quantmind-v2\backups\parquet" | Out-Null

# 删除已有同名任务
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 触发器: 每日 02:00
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"

# 操作: python scripts/pg_backup.py
# 将 stdout/stderr 重定向到日志文件（Task Scheduler 本身不捕获 stdout）
$argument = "`"$scriptPath`" >> `"$logPath`" 2>&1"
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $argument `
    -WorkingDirectory $workDir

# 设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 60) `
    -MultipleInstances IgnoreNew

# 注册
if ($RunAsSystem) {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Description "QuantMind V2 PostgreSQL每日备份 (02:00 | 7天滚动+月度永久+Parquet)" `
        -RunLevel Highest `
        -User "SYSTEM"
} else {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Description "QuantMind V2 PostgreSQL每日备份 (02:00 | 7天滚动+月度永久+Parquet)" `
        -RunLevel Highest
}

Write-Host ""
Write-Host "已注册任务: $taskName"
Write-Host "  调度时间: 每日 02:00"
Write-Host "  执行命令: $pythonPath $scriptPath"
Write-Host "  工作目录: $workDir"
Write-Host "  备份目录: D:\quantmind-v2\backups\"
Write-Host "  日志文件: $logPath"
Write-Host ""
Write-Host "立即测试运行（可选）:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  或: python $scriptPath --dry-run"
