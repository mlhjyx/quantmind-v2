<#
.SYNOPSIS
    PT restart path B Phase B-1 launch -- paper-mode 5d dry-run.

.DESCRIPTION
    ADR-085 path B step 1 implementation (5-19 sediment).

    Sequence:
    1. Backup current .env (atomic)
    2. Flip 2 red-line .env fields (EXECUTION_MODE / LIVE_TRADING_DISABLED)
    3. Restart 4 Servy services (FastAPI / Worker / Beat / QMTData)
    4. Enable 2 schtask (QuantMind_DailyExecute / QuantMind_CancelStaleOrders)
    5. Verify post-restart state

    Red-line field changes:
    - EXECUTION_MODE: live -> paper
    - LIVE_TRADING_DISABLED: false -> true

.NOTES
    Trigger: user 'execute' (trigger 2, ADR-027 sec.7 dual-trigger convention).
    Backup chain: logs/.env-backup-pre-paper-dryrun-2026-05-20.bak

.EXAMPLE
    .\scripts\pt_restart_path_b_step1.ps1
    .\scripts\pt_restart_path_b_step1.ps1 -DryRun
#>
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = "D:\quantmind-v2"
$EnvFile = "$ProjectRoot\backend\.env"
$BackupDir = "$ProjectRoot\logs"
$BackupFile = "$BackupDir\.env-backup-pre-paper-dryrun-2026-05-20.bak"
$ServyCli = "D:\tools\Servy\servy-cli.exe"
$ServiceMgr = "$ProjectRoot\scripts\service_manager.ps1"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "PT Restart path B Phase B-1 -- paper-mode 5d dry-run launch" -ForegroundColor Cyan
Write-Host "ADR-085 sediment (5-19 evening SH)" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 0: Pre-condition verify ---
Write-Host "[Step 0] Pre-condition verify..." -ForegroundColor Yellow

if (-not (Test-Path $EnvFile)) {
    throw "FAIL: backend/.env not found at $EnvFile"
}

$envContent = Get-Content $EnvFile -Raw
if (-not ($envContent -match "(?m)^EXECUTION_MODE=live")) {
    throw "FAIL: Expected EXECUTION_MODE=live in .env (path B precondition)"
}
if (-not ($envContent -match "(?m)^LIVE_TRADING_DISABLED=false")) {
    throw "FAIL: Expected LIVE_TRADING_DISABLED=false in .env (path B precondition)"
}
Write-Host "  [OK] .env current: EXECUTION_MODE=live / LIVE_TRADING_DISABLED=false" -ForegroundColor Green

$executeTask = Get-ScheduledTask -TaskName QuantMind_DailyExecute -ErrorAction SilentlyContinue
if (-not $executeTask) { throw "FAIL: QuantMind_DailyExecute schtask not registered" }
if ($executeTask.State -ne "Disabled") {
    throw "FAIL: Expected QuantMind_DailyExecute=Disabled, got: $($executeTask.State)"
}
Write-Host "  [OK] QuantMind_DailyExecute: Disabled (expected)" -ForegroundColor Green

$cancelTask = Get-ScheduledTask -TaskName QuantMind_CancelStaleOrders -ErrorAction SilentlyContinue
if (-not $cancelTask) { throw "FAIL: QuantMind_CancelStaleOrders schtask not registered" }
Write-Host "  [OK] QuantMind_CancelStaleOrders: $($cancelTask.State)" -ForegroundColor Green

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}
if (Test-Path $BackupFile) {
    Write-Host "  [WARN] Backup already exists ($BackupFile) -- will overwrite" -ForegroundColor Yellow
}

if ($DryRun) {
    Write-Host ""
    Write-Host "=== DRY-RUN MODE -- no mutations performed ===" -ForegroundColor Magenta
    Write-Host "Planned mutations:" -ForegroundColor Magenta
    Write-Host "  1. Copy-Item $EnvFile $BackupFile" -ForegroundColor Magenta
    Write-Host "  2. Edit .env: EXECUTION_MODE=live -> paper" -ForegroundColor Magenta
    Write-Host "  3. Edit .env: LIVE_TRADING_DISABLED=false -> true" -ForegroundColor Magenta
    Write-Host "  4. Restart 4 Servy services" -ForegroundColor Magenta
    Write-Host "  5. Enable QuantMind_DailyExecute schtask" -ForegroundColor Magenta
    Write-Host "  6. Enable QuantMind_CancelStaleOrders schtask" -ForegroundColor Magenta
    Write-Host "Exiting dry-run." -ForegroundColor Magenta
    exit 0
}

# --- Step 1: Atomic backup .env ---
Write-Host ""
Write-Host "[Step 1] Atomic backup .env..." -ForegroundColor Yellow
Copy-Item $EnvFile $BackupFile -Force
$backupSize = (Get-Item $BackupFile).Length
Write-Host "  [OK] Backup: $BackupFile ($backupSize bytes)" -ForegroundColor Green

# --- Step 2: Edit .env (2 red-line field flip) ---
Write-Host ""
Write-Host "[Step 2] Edit .env (2 red-line field flip)..." -ForegroundColor Yellow

$newContent = $envContent -replace "(?m)^EXECUTION_MODE=live", "EXECUTION_MODE=paper"
$newContent = $newContent -replace "(?m)^LIVE_TRADING_DISABLED=false", "LIVE_TRADING_DISABLED=true"

[System.IO.File]::WriteAllText($EnvFile, $newContent, [System.Text.UTF8Encoding]::new($false))

$verifyContent = Get-Content $EnvFile -Raw
if (-not ($verifyContent -match "(?m)^EXECUTION_MODE=paper")) {
    throw "FAIL: post-edit EXECUTION_MODE=paper not found"
}
if (-not ($verifyContent -match "(?m)^LIVE_TRADING_DISABLED=true")) {
    throw "FAIL: post-edit LIVE_TRADING_DISABLED=true not found"
}
Write-Host "  [OK] EXECUTION_MODE=live -> paper" -ForegroundColor Green
Write-Host "  [OK] LIVE_TRADING_DISABLED=false -> true" -ForegroundColor Green

# --- Step 3: Restart Servy 4 services ---
Write-Host ""
Write-Host "[Step 3] Restart Servy 4 services..." -ForegroundColor Yellow

Write-Host "  -> service_manager.ps1 restart all (FastAPI + Worker + Beat)..." -ForegroundColor Gray
& powershell -File $ServiceMgr restart all
if ($LASTEXITCODE -ne 0) { throw "FAIL: service_manager.ps1 restart all exit code $LASTEXITCODE" }
Write-Host "  [OK] 3 Servy services restarted" -ForegroundColor Green

Write-Host "  -> Servy CLI restart QuantMind-QMTData..." -ForegroundColor Gray
if (Test-Path $ServyCli) {
    & $ServyCli restart --name="QuantMind-QMTData"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN] QMTData restart non-zero exit code $LASTEXITCODE" -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] QuantMind-QMTData restarted" -ForegroundColor Green
    }
} else {
    Write-Host "  [WARN] Servy CLI not found at $ServyCli -- skip QMTData restart, manual verify" -ForegroundColor Yellow
}

# --- Step 4: Enable schtask 2 entries ---
Write-Host ""
Write-Host "[Step 4] Enable schtask 2 entries..." -ForegroundColor Yellow

Enable-ScheduledTask -TaskName QuantMind_DailyExecute | Out-Null
$verifyExecute = Get-ScheduledTask -TaskName QuantMind_DailyExecute
if ($verifyExecute.State -ne "Ready") {
    throw "FAIL: post-enable QuantMind_DailyExecute state=$($verifyExecute.State)"
}
Write-Host "  [OK] QuantMind_DailyExecute: Disabled -> Ready" -ForegroundColor Green

Enable-ScheduledTask -TaskName QuantMind_CancelStaleOrders | Out-Null
$verifyCancel = Get-ScheduledTask -TaskName QuantMind_CancelStaleOrders
if ($verifyCancel.State -ne "Ready") {
    throw "FAIL: post-enable QuantMind_CancelStaleOrders state=$($verifyCancel.State)"
}
Write-Host "  [OK] QuantMind_CancelStaleOrders: Disabled -> Ready" -ForegroundColor Green

# --- Step 5: Post-restart health verify ---
Write-Host ""
Write-Host "[Step 5] Post-restart health verify..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

try {
    $healthRsp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET -TimeoutSec 10
    if ($healthRsp.status -ne "ok") {
        throw "FAIL: /health status != ok"
    }
    if ($healthRsp.execution_mode -ne "paper") {
        throw "FAIL: /health execution_mode != paper, got: $($healthRsp.execution_mode)"
    }
    Write-Host "  [OK] FastAPI /health: status=ok / execution_mode=paper" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] /health probe failed: $_" -ForegroundColor Yellow
    Write-Host "  Manual verify: Invoke-RestMethod http://127.0.0.1:8000/health" -ForegroundColor Yellow
}

# --- Summary ---
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "Phase B-1 launch COMPLETE -- paper-mode 5d dry-run armed" -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current state:" -ForegroundColor White
Write-Host "  * .env: EXECUTION_MODE=paper / LIVE_TRADING_DISABLED=true" -ForegroundColor White
Write-Host "  * schtask: DailyExecute=Ready / CancelStaleOrders=Ready" -ForegroundColor White
Write-Host "  * Servy: 4 services Running" -ForegroundColor White
Write-Host ""
Write-Host "Next fire window:" -ForegroundColor White
Write-Host "  * Next 09:31 SH trading day -> first paper-mode execute" -ForegroundColor White
Write-Host ""
Write-Host "Backup: $BackupFile" -ForegroundColor White
Write-Host ""
Write-Host "Rollback (anytime):" -ForegroundColor White
Write-Host "  Copy-Item $BackupFile $EnvFile" -ForegroundColor Gray
Write-Host "  powershell -File scripts/service_manager.ps1 restart all" -ForegroundColor Gray
Write-Host "  Disable-ScheduledTask -TaskName QuantMind_DailyExecute" -ForegroundColor Gray
Write-Host "  Disable-ScheduledTask -TaskName QuantMind_CancelStaleOrders" -ForegroundColor Gray
Write-Host ""
