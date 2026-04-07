# 注册数据质量巡检 Task Scheduler 任务
# 每日17:00运行（Tushare入库后）
# 以管理员身份运行此脚本

$TaskName = "QuantMind_DataQualityCheck"
$PythonExe = "D:\quantmind-v2\.venv\Scripts\python.exe"
$ScriptPath = "D:\quantmind-v2\scripts\data_quality_check.py"
$WorkDir = "D:\quantmind-v2"

# 删除已有同名任务
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[INFO] 已删除旧任务: $TaskName"
}

# 创建触发器：每日17:00
$Trigger = New-ScheduledTaskTrigger -Daily -At "17:00"

# 创建操作
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $ScriptPath `
    -WorkingDirectory $WorkDir

# 设置：错过则尽快执行、电源策略
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# 注册任务（当前用户）
Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $Trigger `
    -Action $Action `
    -Settings $Settings `
    -Description "QuantMind V2 数据质量自动巡检（每日17:00）" `
    -RunLevel Highest

Write-Host "[OK] 任务已注册: $TaskName"
Write-Host "     触发: 每日 17:00"
Write-Host "     脚本: $ScriptPath"
