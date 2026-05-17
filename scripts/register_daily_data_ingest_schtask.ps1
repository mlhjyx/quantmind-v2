# Register QuantMind_DailyDataIngest 2-pass schtask in DISABLED state.
#
# Per ADR-082 D4 + LL-175 lesson 4 — fills the data ingestion architectural debt
# left by `pull_full_data.py` archive (4-08) without DataOrchestrator wiring completion.
#
# Schedule (per Phase 0 Finding #26 Tushare timing research):
#   - QuantMind_DailyDataIngest_Preopen   — 09:25 SH M-F  (T-1 adj_factor refresh)
#   - QuantMind_DailyDataIngest_Postclose — 17:30 SH M-F  (T-day daily + daily_basic + stk_limit + adj_factor)
#
# Both registered DISABLED tonight (Sat 2026-05-17). Manually enable Mon evening
# post 09:31 live-fire confirmed clean:
#   Enable-ScheduledTask -TaskName QuantMind_DailyDataIngest_Postclose
#   Enable-ScheduledTask -TaskName QuantMind_DailyDataIngest_Preopen
#
# Sustained 铁律 43 hardening pattern (DontStopOnIdleEnd + AllowStartIfOnBatteries).
#
# Run as Administrator or Local System.

$PYTHON = "D:\quantmind-v2\.venv\Scripts\python.exe"
$SCRIPT = "D:\quantmind-v2\scripts\daily_data_ingest.py"
$WORKDIR = "D:\quantmind-v2"

$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 0

# ── Pass 1: Postclose 17:30 SH M-F (T-day full ingest) ──────────────────────────
Write-Output "=== Register QuantMind_DailyDataIngest_Postclose (17:30 SH M-F) ==="
$action_post = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "$SCRIPT --pass postclose --apply" `
    -WorkingDirectory $WORKDIR

$trigger_post = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $weekdays `
    -At "17:30"

Register-ScheduledTask `
    -TaskName "QuantMind_DailyDataIngest_Postclose" `
    -Action $action_post `
    -Trigger $trigger_post `
    -Settings $settings `
    -Description "Tushare 17:30 SH M-F post-close ingest (T-day daily + daily_basic + stk_limit + available adj_factor). ADR-082 D4. Disabled until Mon live-fire confirmed clean." `
    -Force | Out-Null

Disable-ScheduledTask -TaskName "QuantMind_DailyDataIngest_Postclose" | Out-Null
Write-Output "  ✅ Registered + Disabled (NextRun pending Enable)"

# ── Pass 2: Preopen 09:25 SH M-F (T-1 adj_factor refresh) ───────────────────────
Write-Output ""
Write-Output "=== Register QuantMind_DailyDataIngest_Preopen (09:25 SH M-F) ==="
$action_pre = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument "$SCRIPT --pass preopen --apply" `
    -WorkingDirectory $WORKDIR

$trigger_pre = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek $weekdays `
    -At "09:25"

Register-ScheduledTask `
    -TaskName "QuantMind_DailyDataIngest_Preopen" `
    -Action $action_pre `
    -Trigger $trigger_pre `
    -Settings $settings `
    -Description "Tushare 09:25 SH M-F pre-open ingest (T-1 adj_factor refresh after Tushare publishes 09:15-09:20). ADR-082 D4. Disabled until Mon live-fire confirmed clean." `
    -Force | Out-Null

Disable-ScheduledTask -TaskName "QuantMind_DailyDataIngest_Preopen" | Out-Null
Write-Output "  ✅ Registered + Disabled (NextRun pending Enable)"

# ── Verify final state ──────────────────────────────────────────────────────────
Write-Output ""
Write-Output "=== Final state ==="
Get-ScheduledTask | Where-Object { $_.TaskName -like "QuantMind_DailyDataIngest*" } | ForEach-Object {
    $info = Get-ScheduledTaskInfo -TaskName $_.TaskName
    "  {0,-45} State={1,-9} NextRun={2}" -f $_.TaskName, $_.State, $info.NextRunTime
}

Write-Output ""
Write-Output "✅ Registration complete. Both schtasks DISABLED — enable manually post Mon live-fire:"
Write-Output "   Enable-ScheduledTask -TaskName QuantMind_DailyDataIngest_Postclose"
Write-Output "   Enable-ScheduledTask -TaskName QuantMind_DailyDataIngest_Preopen"
