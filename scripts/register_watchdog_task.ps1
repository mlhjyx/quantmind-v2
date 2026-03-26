# 注册PT心跳watchdog到Windows Task Scheduler
# 每日20:00运行，检测当天PT是否执行
# Sprint 1.11 Task 5

$taskName = "QuantMind_PT_Watchdog"
$pythonPath = "D:\quantmind-v2\.venv\Scripts\python.exe"
$scriptPath = "D:\quantmind-v2\scripts\pt_watchdog.py"

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory "D:\quantmind-v2"
$trigger = New-ScheduledTaskTrigger -Daily -At "20:00"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "PT心跳watchdog: 检测Paper Trading是否今日运行" -Force

Write-Host "已注册: $taskName (每日20:00)"
