$logFile = "D:\quantmind-v2\scripts\register_tasks_result.txt"

try {
    $result = ""

    # Delete old tasks if exist
    schtasks /delete /tn "QuantMind_DailySignal" /f 2>$null
    schtasks /delete /tn "QuantMind_DailyExecute" /f 2>$null

    # Signal task: weekdays 16:30
    $action1 = New-ScheduledTaskAction `
        -Execute "D:\quantmind-v2\.venv\Scripts\python.exe" `
        -Argument "D:\quantmind-v2\scripts\run_paper_trading.py signal" `
        -WorkingDirectory "D:\quantmind-v2"

    $trigger1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "16:30"
    $settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    $principal1 = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName "QuantMind_DailySignal" -Action $action1 -Trigger $trigger1 -Settings $settings1 -Principal $principal1 -Description "QuantMind V2 Paper Trading - Signal Phase (T-day 16:30)" -Force
    $result += "Signal task registered.`r`n"

    # Execute task: weekdays 09:00
    $action2 = New-ScheduledTaskAction `
        -Execute "D:\quantmind-v2\.venv\Scripts\python.exe" `
        -Argument "D:\quantmind-v2\scripts\run_paper_trading.py execute" `
        -WorkingDirectory "D:\quantmind-v2"

    $trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:00"
    $settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    $principal2 = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName "QuantMind_DailyExecute" -Action $action2 -Trigger $trigger2 -Settings $settings2 -Principal $principal2 -Description "QuantMind V2 Paper Trading - Execute Phase (T+1 day 09:00)" -Force
    $result += "Execute task registered.`r`n"

    # Verify
    $tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "*QuantMind*" }
    foreach ($t in $tasks) {
        $info = Get-ScheduledTaskInfo -TaskName $t.TaskName
        $result += "TASK: $($t.TaskName) | State=$($t.State) | NextRun=$($info.NextRunTime)`r`n"
    }

    $result += "DONE"
    [System.IO.File]::WriteAllText($logFile, $result, [System.Text.Encoding]::UTF8)
} catch {
    [System.IO.File]::WriteAllText($logFile, "ERROR: $($_.Exception.Message)`r`n$($_.ScriptStackTrace)", [System.Text.Encoding]::UTF8)
}
