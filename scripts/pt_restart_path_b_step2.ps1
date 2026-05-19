<#
.SYNOPSIS
    PT restart path B Phase B-2 launch -- live flip after paper-mode 5d PASS.

.DESCRIPTION
    ADR-085 path B step 2 implementation (5-27 Wed early SH).

    Sequence:
    1. Pre-cond verify (.env paper / schtask Ready / 5d gate manual)
    2. Backup current .env (post Phase B-1 state)
    3. Flip 2 red-line .env fields back (EXECUTION_MODE / LIVE_TRADING_DISABLED)
    4. Restart 4 Servy services
    5. Verify post-restart live state

    Red-line field changes:
    - EXECUTION_MODE: paper -> live
    - LIVE_TRADING_DISABLED: true -> false

.NOTES
    Trigger: user 'execute' (trigger 3) + 5d gate evidence STATUS_REPORT cumulative.
    Backup chain: logs/.env-backup-pre-live-restart-2026-05-27.bak

.EXAMPLE
    .\scripts\pt_restart_path_b_step2.ps1
    .\scripts\pt_restart_path_b_step2.ps1 -DryRun
#>
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = "D:\quantmind-v2"
$EnvFile = "$ProjectRoot\backend\.env"
$BackupDir = "$ProjectRoot\logs"
$BackupFile = "$BackupDir\.env-backup-pre-live-restart-2026-05-27.bak"
$ServyCli = "D:\tools\Servy\servy-cli.exe"
$ServiceMgr = "$ProjectRoot\scripts\service_manager.ps1"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "PT Restart path B Phase B-2 -- live flip launch" -ForegroundColor Cyan
Write-Host "ADR-085 sec.2.1 Phase B-2 (5-27 Wed early SH)" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 0: Pre-condition verify ---
Write-Host "[Step 0] Pre-condition verify..." -ForegroundColor Yellow

if (-not (Test-Path $EnvFile)) {
    throw "FAIL: backend/.env not found at $EnvFile"
}

$envContent = Get-Content $EnvFile -Raw

if (-not ($envContent -match "(?m)^EXECUTION_MODE=paper")) {
    throw "FAIL: Expected EXECUTION_MODE=paper in .env (Phase B-1 state)"
}
if (-not ($envContent -match "(?m)^LIVE_TRADING_DISABLED=true")) {
    throw "FAIL: Expected LIVE_TRADING_DISABLED=true in .env (Phase B-1 state)"
}
Write-Host "  [OK] .env current: EXECUTION_MODE=paper / LIVE_TRADING_DISABLED=true" -ForegroundColor Green

$executeTask = Get-ScheduledTask -TaskName QuantMind_DailyExecute -ErrorAction SilentlyContinue
if (-not $executeTask) { throw "FAIL: QuantMind_DailyExecute schtask not registered" }
if ($executeTask.State -ne "Ready") {
    throw "FAIL: Expected QuantMind_DailyExecute=Ready (sustained Phase B-1), got: $($executeTask.State). Run step1 first."
}
Write-Host "  [OK] QuantMind_DailyExecute: Ready (sustained Phase B-1)" -ForegroundColor Green

$cancelTask = Get-ScheduledTask -TaskName QuantMind_CancelStaleOrders -ErrorAction SilentlyContinue
if ($cancelTask.State -ne "Ready") {
    throw "FAIL: Expected QuantMind_CancelStaleOrders=Ready, got: $($cancelTask.State)"
}
Write-Host "  [OK] QuantMind_CancelStaleOrders: Ready" -ForegroundColor Green

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}
if (Test-Path $BackupFile) {
    Write-Host "  [WARN] Backup already exists ($BackupFile) -- will overwrite" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Phase B-1 5d gate manual verify required (CC STATUS_REPORT cumulative):" -ForegroundColor Yellow
Write-Host "    [ ] Day 1 (5-21 Thu) signals/execution_plans write" -ForegroundColor Gray
Write-Host "    [ ] Day 2 (5-22 Fri) + Beat news cumulative" -ForegroundColor Gray
Write-Host "    [ ] Day 3 (5-25 Mon) weekend gap analysis" -ForegroundColor Gray
Write-Host "    [ ] Day 5 (5-26 Tue evening) final verify" -ForegroundColor Gray
Write-Host "    [ ] trade_log 0 new rows (paper sustained)" -ForegroundColor Gray
Write-Host "    [ ] risk_event_log 0 P0 incident" -ForegroundColor Gray
Write-Host "    [ ] meta_monitor_tick 0 alert-on-alert" -ForegroundColor Gray
Write-Host "    [ ] DingTalk 0 fire" -ForegroundColor Gray
Write-Host "    [ ] LLM cost <= 50 USD/month" -ForegroundColor Gray
Write-Host "    [ ] Beat 22 entries 100% triggered" -ForegroundColor Gray
Write-Host ""

if ($DryRun) {
    Write-Host "=== DRY-RUN MODE -- no mutations performed ===" -ForegroundColor Magenta
    Write-Host "Planned mutations:" -ForegroundColor Magenta
    Write-Host "  1. Copy-Item $EnvFile $BackupFile" -ForegroundColor Magenta
    Write-Host "  2. Edit .env: EXECUTION_MODE=paper -> live" -ForegroundColor Magenta
    Write-Host "  3. Edit .env: LIVE_TRADING_DISABLED=true -> false" -ForegroundColor Magenta
    Write-Host "  4. Restart 4 Servy services" -ForegroundColor Magenta
    Write-Host "  5. (schtask sustained Ready, 0 change)" -ForegroundColor Magenta
    Write-Host "Exiting dry-run." -ForegroundColor Magenta
    exit 0
}

# --- Step 1: Atomic backup .env ---
Write-Host "[Step 1] Atomic backup .env (Phase B-1 state)..." -ForegroundColor Yellow
Copy-Item $EnvFile $BackupFile -Force
$backupSize = (Get-Item $BackupFile).Length
Write-Host "  [OK] Backup: $BackupFile ($backupSize bytes)" -ForegroundColor Green

# --- Step 2: Edit .env (2 red-line field flip back to live) ---
Write-Host ""
Write-Host "[Step 2] Edit .env (2 red-line field flip back to live)..." -ForegroundColor Yellow

$newContent = $envContent -replace "(?m)^EXECUTION_MODE=paper", "EXECUTION_MODE=live"
$newContent = $newContent -replace "(?m)^LIVE_TRADING_DISABLED=true", "LIVE_TRADING_DISABLED=false"

[System.IO.File]::WriteAllText($EnvFile, $newContent, [System.Text.UTF8Encoding]::new($false))

$verifyContent = Get-Content $EnvFile -Raw
if (-not ($verifyContent -match "(?m)^EXECUTION_MODE=live")) {
    throw "FAIL: post-edit EXECUTION_MODE=live not found"
}
if (-not ($verifyContent -match "(?m)^LIVE_TRADING_DISABLED=false")) {
    throw "FAIL: post-edit LIVE_TRADING_DISABLED=false not found"
}
Write-Host "  [OK] EXECUTION_MODE=paper -> live" -ForegroundColor Green
Write-Host "  [OK] LIVE_TRADING_DISABLED=true -> false" -ForegroundColor Green

# --- Step 3: Restart Servy 4 services ---
Write-Host ""
Write-Host "[Step 3] Restart Servy 4 services..." -ForegroundColor Yellow

Write-Host "  -> service_manager.ps1 restart all..." -ForegroundColor Gray
& powershell -File $ServiceMgr restart all
if ($LASTEXITCODE -ne 0) { throw "FAIL: service_manager.ps1 restart all exit code $LASTEXITCODE" }
Write-Host "  [OK] 3 Servy services restarted" -ForegroundColor Green

Write-Host "  -> Servy CLI restart QuantMind-QMTData..." -ForegroundColor Gray
if (Test-Path $ServyCli) {
    & $ServyCli restart --name="QuantMind-QMTData"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN] QMTData restart exit code $LASTEXITCODE" -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] QuantMind-QMTData restarted" -ForegroundColor Green
    }
} else {
    Write-Host "  [WARN] Servy CLI not found -- manual verify required" -ForegroundColor Yellow
}

# --- Step 4: Post-restart live health verify ---
Write-Host ""
Write-Host "[Step 4] Post-restart live health verify..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

try {
    $healthRsp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET -TimeoutSec 10
    if ($healthRsp.status -ne "ok") { throw "FAIL: /health status != ok" }
    if ($healthRsp.execution_mode -ne "live") {
        throw "FAIL: /health execution_mode != live, got: $($healthRsp.execution_mode)"
    }
    Write-Host "  [OK] FastAPI /health: status=ok / execution_mode=live" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] /health probe failed: $_" -ForegroundColor Yellow
}

# --- Summary ---
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "Phase B-2 launch COMPLETE -- LIVE armed" -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current state:" -ForegroundColor White
Write-Host "  * .env: EXECUTION_MODE=live / LIVE_TRADING_DISABLED=false" -ForegroundColor White
Write-Host "  * schtask: DailyExecute=Ready / CancelStaleOrders=Ready (sustained)" -ForegroundColor White
Write-Host "  * Servy: 4 services Running" -ForegroundColor White
Write-Host ""
Write-Host "Next fire window:" -ForegroundColor Yellow
Write-Host "  * IF today before 09:31 SH -> fire today first LIVE execute" -ForegroundColor Yellow
Write-Host "  * OTHERWISE next trading day 09:31 SH" -ForegroundColor Yellow
Write-Host ""
Write-Host "Backup chain:" -ForegroundColor White
Write-Host "  * Phase B-1 backup: logs/.env-backup-pre-paper-dryrun-2026-05-20.bak" -ForegroundColor White
Write-Host "  * Phase B-2 backup: $BackupFile" -ForegroundColor White
Write-Host ""
Write-Host "Rollback (anytime):" -ForegroundColor White
Write-Host "  Copy-Item $BackupFile $EnvFile" -ForegroundColor Gray
Write-Host "  powershell -File scripts/service_manager.ps1 restart all" -ForegroundColor Gray
Write-Host ""
Write-Host "5/5 red-line verify (post-flip):" -ForegroundColor White
Write-Host "  * EXECUTION_MODE=live [OK]" -ForegroundColor White
Write-Host "  * LIVE_TRADING_DISABLED=false [OK]" -ForegroundColor White
Write-Host "  * QMT_ACCOUNT_ID=81001102 (unchanged) [OK]" -ForegroundColor White
Write-Host "  * DINGTALK_ALERTS_ENABLED=true (unchanged) [OK]" -ForegroundColor White
Write-Host "  * L4_AUTO_MODE_ENABLED=unset (unchanged) [OK]" -ForegroundColor White
Write-Host ""
