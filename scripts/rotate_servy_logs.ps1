# scripts/rotate_servy_logs.ps1
#
# Plan v8 P1-45 closure: Servy stdout/stderr logs 周期 rotation.
#
# Why: backend/app/logging_config.py 用 RotatingFileHandler (app.log 10MB/7 backups)
# 但 Servy 4 service (FastAPI / Celery / CeleryBeat / QMTData) stdout/stderr 是
# raw 重定向到 logs/*.log, 不走 RotatingFileHandler. celery-beat-stderr.log 实测
# 8.8MB 持续增长. P1-45 finding sediment.
#
# Behavior:
# - Scan logs/*.log + logs/*.err
# - If size > MAX_SIZE_MB (default 100MB): rotate to .1, .2, ..., keep last N backups
# - Older than N: delete
# - Skip files in EXCLUDE list (rotated already, or critical .bak)
#
# Usage:
#   .\scripts\rotate_servy_logs.ps1                # Default: 100MB, 7 backups
#   .\scripts\rotate_servy_logs.ps1 -MaxSizeMB 50  # Custom max size
#   .\scripts\rotate_servy_logs.ps1 -DryRun        # Dry run, no actual mv/rm
#
# Schtask register (after user verify dry-run):
#   schtasks /Create /TN "QuantMind_RotateServyLogs" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\quantmind-v2\scripts\rotate_servy_logs.ps1" /SC DAILY /ST 02:00 /F

param(
    [int]$MaxSizeMB = 100,
    [int]$BackupCount = 7,
    [string]$LogDir = "D:\quantmind-v2\logs",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$MaxBytes = $MaxSizeMB * 1024 * 1024

# Exclude patterns (already rotated, .bak files, .dat .dir compiled celery state)
$ExcludePatterns = @(
    "*.bak", "*.dat", "*.dir", "*.json",
    "*-backup-*", "*_backup_*", "*-archived-*",
    "app.log*"  # app.log is already RotatingFileHandler-managed
)

# Files matching these patterns ARE rotated (Servy stdout/stderr + Celery + IC logs)
$RotateTargets = @(
    "celery-beat-stderr.log",
    "celery-stderr.log",
    "celery-beat-stdout.log",
    "celery-stdout.log",
    "fastapi-stderr.log",
    "fastapi-stdout.log",
    "qmt-data-stderr.log",
    "qmt-data-stdout.log",
    "compute_ic_rolling.log",
    "compute_daily_ic.log",
    "data_quality_check.log",
    "backup.log"
)

Write-Host "[rotate_servy_logs] Scanning $LogDir (MaxSize=${MaxSizeMB}MB, Backups=$BackupCount, DryRun=$DryRun)"
Write-Host "============================================================"

$rotated = 0
$skipped = 0
$errors = 0

foreach ($target in $RotateTargets) {
    $filePath = Join-Path $LogDir $target
    if (-not (Test-Path $filePath)) {
        Write-Host "[SKIP] $target -> file not found"
        $skipped++
        continue
    }

    $fileInfo = Get-Item $filePath
    $sizeMB = [math]::Round($fileInfo.Length / 1MB, 2)

    if ($fileInfo.Length -lt $MaxBytes) {
        Write-Host "[OK]   $target ($sizeMB MB) under threshold"
        $skipped++
        continue
    }

    Write-Host "[ROTATE] $target ($sizeMB MB) exceeds $MaxSizeMB MB"

    if ($DryRun) {
        Write-Host "       [DRY] would rotate $target.{1..$BackupCount}"
        $rotated++
        continue
    }

    try {
        # Delete oldest backup if exists
        $oldest = "$filePath.$BackupCount"
        if (Test-Path $oldest) {
            Remove-Item $oldest -Force
        }

        # Shift backups: .6 -> .7, .5 -> .6, ..., .1 -> .2
        for ($i = $BackupCount - 1; $i -ge 1; $i--) {
            $src = "$filePath.$i"
            $dst = "$filePath.$($i + 1)"
            if (Test-Path $src) {
                Move-Item $src $dst -Force
            }
        }

        # Current file -> .1
        # Note: cannot truly rotate while process holds handle on Windows.
        # Strategy: copy current to .1, then truncate (Set-Content empty).
        Copy-Item $filePath "$filePath.1" -Force
        Set-Content -Path $filePath -Value $null -Encoding UTF8

        Write-Host "       [OK] rotated $target -> $target.1 (truncated)"
        $rotated++
    } catch {
        Write-Host "       [ERR] failed: $_"
        $errors++
    }
}

Write-Host "============================================================"
Write-Host "[rotate_servy_logs] Summary: rotated=$rotated, skipped=$skipped, errors=$errors"

if ($errors -gt 0) {
    exit 1
}
exit 0
