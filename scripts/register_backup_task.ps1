# 注册 pg_dump 每日自动备份到 Task Scheduler
# 每日凌晨 02:00 执行，保留7天

$taskName = "QuantMind_DailyBackup"
$pythonPath = "D:\quantmind-v2\.venv\Scripts\python.exe"
$scriptPath = "D:\quantmind-v2\scripts\pg_backup.py"
$workDir = "D:\quantmind-v2"

# 删除已有任务(如果存在)
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建触发器: 每日02:00
$trigger = New-ScheduledTaskTrigger -Daily -At 02:00

# 创建操作
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $scriptPath `
    -WorkingDirectory $workDir

# 设置: 即使未登录也运行, 最长运行30分钟
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# 注册任务(以当前用户身份运行)
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Description "QuantMind V2 PostgreSQL每日备份 (02:00, 保留7天)" `
    -RunLevel Highest

Write-Host "Task '$taskName' registered successfully."
Write-Host "Schedule: Daily at 02:00"
Write-Host "Script: $scriptPath"
