# 注册 miniQMT 开机自启到 Task Scheduler
# 系统启动时自动运行miniQMT客户端

$taskName = "QuantMind_MiniQMT_AutoStart"
$qmtExe = "E:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe"
$workDir = "E:\国金QMT交易端模拟\bin.x64"

# 删除已有任务(如果存在)
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建触发器: 用户登录时
$trigger = New-ScheduledTaskTrigger -AtLogOn

# 创建操作
$action = New-ScheduledTaskAction `
    -Execute $qmtExe `
    -WorkingDirectory $workDir

# 设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 24)

# 注册任务
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Description "QuantMind V2: miniQMT交易端开机自启动(模拟环境)" `
    -RunLevel Highest

Write-Host "Task '$taskName' registered successfully."
Write-Host "Trigger: At user logon"
Write-Host "Executable: $qmtExe"
Write-Host ""
Write-Host "NOTE: miniQMT启动后需手动登录模拟账户81001102"
Write-Host "      后续可配置自动登录(需账户密码参数)"
