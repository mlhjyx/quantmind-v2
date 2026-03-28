# GP Pipeline Weekly Task Scheduler Registration
# 每周六02:00自动运行GP因子挖掘Pipeline
# R6: Task Scheduler做主调度，OS级可靠性
# 依赖: scripts/run_gp_pipeline.py (arch在Sprint 1.17实现)

$logFile = "D:\quantmind-v2\scripts\register_gp_task_result.txt"

try {
    $result = ""

    # Delete old task if exists
    schtasks /delete /tn "QuantMind_GPPipeline" /f 2>$null

    # GP Pipeline: Saturday 02:00 (avoid PT signal/execute windows)
    $action = New-ScheduledTaskAction `
        -Execute "D:\quantmind-v2\.venv\Scripts\python.exe" `
        -Argument "D:\quantmind-v2\scripts\run_gp_pipeline.py --generations 50 --population 100 --islands 3 --output-dir D:\quantmind-v2\gp_results" `
        -WorkingDirectory "D:\quantmind-v2"

    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "02:00"
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
        -RestartCount 1 `
        -RestartInterval (New-TimeSpan -Minutes 10)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask `
        -TaskName "QuantMind_GPPipeline" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "QuantMind V2 GP Factor Mining Pipeline - Weekly Saturday 02:00 (max 4h)" `
        -Force

    $result += "GP Pipeline task registered: Saturday 02:00, max 4h`r`n"
    $result += "Command: python run_gp_pipeline.py --generations 50 --population 100 --islands 3`r`n"
    $result += "Output: D:\quantmind-v2\gp_results\`r`n"

    $result | Out-File $logFile -Encoding utf8
    Write-Host "GP Pipeline task registered successfully. See $logFile"
} catch {
    $_.Exception.Message | Out-File $logFile -Encoding utf8
    Write-Host "ERROR: $($_.Exception.Message)"
    exit 1
}
