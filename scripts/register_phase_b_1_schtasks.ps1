# scripts/register_phase_b_1_schtasks.ps1
#
# Plan v8 — Schtask register batch script (留 user trigger after Phase B-1 Day 1 验证)
#
# Bundles 6 schtask registers from Plan v8 closure batch (code review HIGH fix 5-20):
# 1. QuantMind_RotateServyLogs (P1-45, daily 02:00)
# 2. QuantMind_SchtaskFreshnessProbe (P0-6, daily 09:00)
# 3. QuantMind_BeatHeartbeatProbe (P0-5, every 5 min)
# 4. QuantMind_MarketOpenWatcher (P0-15, daily 09:31)
# 5. QuantMind_CeleryNightlyRestart (ADR-086 Tier 1, daily 03:30)
# 6. QuantMind_AuditCadenceQuarterly (§VIII #29, Jan 1 03:00)
#
# Usage:
#   .\scripts\register_phase_b_1_schtasks.ps1                # All 6, prompt per task
#   .\scripts\register_phase_b_1_schtasks.ps1 -Auto         # Skip prompts, register all
#   .\scripts\register_phase_b_1_schtasks.ps1 -DryRun       # Show commands, don't execute
#
# Run as Administrator on Windows.

param(
    [switch]$Auto,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$PYTHON_EXE = "D:\quantmind-v2\.venv\Scripts\python.exe"
$POWERSHELL_EXE = "powershell.exe"

$tasks = @(
    @{
        Name = "QuantMind_RotateServyLogs"
        Description = "Plan v8 P1-45: Rotate Servy stdout/stderr logs (100MB threshold)"
        Schedule = "DAILY"
        StartTime = "02:00"
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -File D:\quantmind-v2\scripts\rotate_servy_logs.ps1"
    },
    @{
        Name = "QuantMind_SchtaskFreshnessProbe"
        Description = "Plan v8 P0-6: Daily schtask LastResult + LastRunTime audit"
        Schedule = "DAILY"
        StartTime = "09:00"
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"$PYTHON_EXE D:\quantmind-v2\scripts\audit_schtask_freshness.py`""
    },
    @{
        Name = "QuantMind_BeatHeartbeatProbe"
        Description = "Plan v8 P0-5: Celery Beat death external probe (LL-181 robust)"
        Schedule = "MINUTE"
        Modifier = 5
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"$PYTHON_EXE D:\quantmind-v2\scripts\audit_beat_heartbeat.py`""
    },
    @{
        Name = "QuantMind_MarketOpenWatcher"
        Description = "Plan v8 P0-15: 09:31 SH market open health watcher"
        Schedule = "DAILY"
        StartTime = "09:31"
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"$PYTHON_EXE D:\quantmind-v2\scripts\audit_market_open_watcher.py`""
    },
    @{
        Name = "QuantMind_CeleryNightlyRestart"
        Description = "ADR-086 Tier 1: Celery solo pool nightly restart (LL-189 memory leak prevention)"
        Schedule = "DAILY"
        StartTime = "03:30"
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"D:\tools\Servy\servy-cli.exe restart --name=QuantMind-Celery`""
    },
    @{
        Name = "QuantMind_AuditCadenceQuarterly"
        Description = "Plan v8 §VIII #29: Quarterly audit cadence reminder (Jan/Apr/Jul/Oct 1st)"
        Schedule = "MONTHLY"
        Modifier = "1"
        Months = "JAN,APR,JUL,OCT"
        StartTime = "03:00"
        Command = $POWERSHELL_EXE
        Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"$PYTHON_EXE D:\quantmind-v2\scripts\audit_design_doc_smoke.py --strict`""
    }
)

function Register-Task {
    param([hashtable]$Task)

    Write-Host ""
    Write-Host "=== $($Task.Name) ===" -ForegroundColor Cyan
    Write-Host "Description: $($Task.Description)"
    Write-Host "Schedule: $($Task.Schedule)"
    if ($Task.StartTime) {
        Write-Host "StartTime: $($Task.StartTime)"
    }
    if ($Task.Modifier) {
        Write-Host "Modifier: $($Task.Modifier)"
    }
    Write-Host "Command: $($Task.Command)"
    Write-Host "Arguments: $($Task.Arguments)"

    # Plan v8 code review MEDIUM fix (5-20): properly quote executable path within /TR value
    # for future-proofing against paths with spaces (e.g. C:\Program Files\...).
    $trValue = "`"\`"$($Task.Command)\`" $($Task.Arguments)`""
    $cmdArgs = @(
        "/Create",
        "/TN", $Task.Name,
        "/TR", $trValue,
        "/SC", $Task.Schedule,
        "/F"
    )
    if ($Task.StartTime) {
        $cmdArgs += "/ST"
        $cmdArgs += $Task.StartTime
    }
    if ($Task.Modifier) {
        $cmdArgs += "/MO"
        $cmdArgs += $Task.Modifier
    }
    if ($Task.Months) {
        $cmdArgs += "/M"
        $cmdArgs += $Task.Months
    }

    $cmdString = "schtasks $($cmdArgs -join ' ')"

    if ($DryRun) {
        Write-Host "[DRY-RUN] Would execute: $cmdString" -ForegroundColor Yellow
        return
    }

    if (-not $Auto) {
        $response = Read-Host "Register this task? [Y/n]"
        if ($response -eq "n" -or $response -eq "N") {
            Write-Host "  SKIPPED" -ForegroundColor Yellow
            return
        }
    }

    try {
        & schtasks @cmdArgs
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Registered $($Task.Name)" -ForegroundColor Green
        } else {
            Write-Host "  [ERR] schtasks exit=$LASTEXITCODE" -ForegroundColor Red
        }
    } catch {
        Write-Host "  [ERR] $_" -ForegroundColor Red
    }
}

Write-Host "[register_phase_b_1_schtasks] Registering $($tasks.Count) Plan v8 schtasks"
Write-Host "Mode: Auto=$Auto, DryRun=$DryRun"
Write-Host ""

foreach ($task in $tasks) {
    Register-Task $task
}

Write-Host ""
Write-Host "[register_phase_b_1_schtasks] Done. Verify with: schtasks /Query /TN QuantMind_*" -ForegroundColor Cyan
