# QuantMind V2 — VACUUM ANALYZE schtask wrapper.
#
# Trigger source: docs/audit/RETROACTIVE_REVIEW_FINDINGS_2026_05_19.md F3 closure
#   + ISSUES_PENDING_REGISTRY §2 F3 (script ready ×4 rounds, schtask NOT registered).
#
# Pattern (反 plaintext password in schtask config — 铁律 35):
#   - schtask /TR points to THIS .ps1 (not python directly + --dsn arg)
#   - .ps1 reads DATABASE_URL from backend/.env at runtime
#   - sets $env:DATABASE_URL for child python process
#   - python script (db_vacuum_analyze.py) sees DATABASE_URL via os.environ
#
# Schedule: Weekly Sunday 03:00 SH (low-traffic, VACUUM ANALYZE 不锁表)
#
# 关联:
#   - scripts/db_vacuum_analyze.py (script body, round-2 P1 hardening 已完成)
#   - scripts/setup_task_scheduler.ps1 §16 QuantMind_VacuumAnalyze (lines 605-633)
#       full register block (Sun 03:00, ExecutionTimeLimit 2h, -Force idempotency)
#       — closed 2026-05-19 Session 57+1 round-5 F3 (iter 29 fresh-verify 2026-05-24).
#   - 红线: 0 broker call (pure DB ops, isolated from trading)

$ErrorActionPreference = "Stop"

$projectRoot = "D:\quantmind-v2"
$envFile = "$projectRoot\backend\.env"
$pythonExe = "$projectRoot\.venv\Scripts\python.exe"
$script = "$projectRoot\scripts\db_vacuum_analyze.py"
$logDir = "$projectRoot\logs"

# Ensure log dir exists (反 silent missing-dir fail)
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = "$logDir\vacuum_analyze_$(Get-Date -Format 'yyyyMMdd').log"

function Log-Msg($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts [VacuumAnalyze] $msg" | Tee-Object -FilePath $logFile -Append
}

Log-Msg "Start (schtask wrapper PID=$PID)"

if (-not (Test-Path $envFile)) {
    Log-Msg "ERROR: .env not found at $envFile"
    exit 1
}

if (-not (Test-Path $pythonExe)) {
    Log-Msg "ERROR: python exe not found at $pythonExe"
    exit 1
}

if (-not (Test-Path $script)) {
    Log-Msg "ERROR: script not found at $script"
    exit 1
}

# Read DATABASE_URL from .env (反 plaintext arg in schtask config)
$dbUrlLine = Get-Content $envFile | Where-Object { $_ -match "^\s*DATABASE_URL\s*=" } | Select-Object -First 1
if (-not $dbUrlLine) {
    Log-Msg "ERROR: DATABASE_URL not found in .env"
    exit 1
}

$dbUrlValue = ($dbUrlLine -split "=", 2)[1].Trim()
# Strip optional surrounding quotes
$dbUrlValue = $dbUrlValue.Trim('"').Trim("'")
$env:DATABASE_URL = $dbUrlValue

# Sanity check (反 placeholder 误用)
if ($env:DATABASE_URL -like "*REPLACE_WITH_ENV*") {
    Log-Msg "ERROR: DATABASE_URL has placeholder value, .env not configured"
    exit 1
}

Log-Msg "DATABASE_URL loaded (length=$($env:DATABASE_URL.Length) chars)"
Log-Msg "Running: $pythonExe $script"

Set-Location $projectRoot
& $pythonExe $script 2>&1 | Tee-Object -FilePath $logFile -Append

$exitCode = $LASTEXITCODE
Log-Msg "Exit code: $exitCode"
exit $exitCode
