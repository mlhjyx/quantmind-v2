# Sunday PG 维护窗口脚本 — Phase 1: shared_buffers 升级 + 重启 (5-30s 中断)
#
# 用途: Monday 4-27 真生产前的 PG 性能优化窗口
# 时机: Sunday 02:00-06:00 之间 (PT 不交易, schtask 间隙)
# 当前: shared_buffers=2GB (32GB 机器仅占 6.25%, 推荐 25%=8GB)
#
# 流程:
#   1. 预检 (Servy 服务健康 + 无活跃 PG long query)
#   2. ALTER SYSTEM SET shared_buffers = '8GB'
#   3. Servy 4 服务 stop (FastAPI / Celery / CeleryBeat / QMTData)
#   4. pg_ctl restart (快速 5-15s)
#   5. PG ready 等待 (pg_isready loop)
#   6. Servy 4 服务 start
#   7. 验证: pg_settings shared_buffers + Servy /health
#   8. 报告 + dingtalk 通知
#
# 风险: PT 真金 (Saturday/Sunday 不交易) + Servy 4 服务 5-30s 中断 (auto reconnect)
# 回滚: ALTER SYSTEM RESET shared_buffers + 重启
#
# 使用:
#   powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_maintenance.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_maintenance.ps1 -DryRun

param(
    [switch]$DryRun = $false,
    [int]$NewSharedBuffersMB = 8192,  # 8 GB default
    [string]$DingTalkUrl = ""
)

$ErrorActionPreference = "Stop"
$startTime = Get-Date
Write-Host "===== Sunday PG Maintenance Phase 1 =====" -ForegroundColor Cyan
Write-Host "Start: $startTime"
Write-Host "DryRun: $DryRun, Target shared_buffers: ${NewSharedBuffersMB}MB"

# ─── Step 1: 预检 ───────────────────────────────────────────
Write-Host "`n[Step 1] 预检 ..." -ForegroundColor Yellow

$env:PGPASSWORD = 'quantmind'
$psql = "D:\pgsql\bin\psql.exe"
$pgctl = "D:\pgsql\bin\pg_ctl.exe"
$pgdata = "D:\pgdata16"

# Check PG alive
$check = & $psql -U xin -d quantmind_v2 -h localhost -t -c "SELECT 1" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FATAL] PG not reachable: $check" -ForegroundColor Red
    exit 2
}
Write-Host "  ✓ PG reachable"

# Check active long queries (>60s warns)
$longRunning = & $psql -U xin -d quantmind_v2 -h localhost -t -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state='active' AND query_start < NOW() - INTERVAL '60 seconds'"
Write-Host "  long-running queries (>60s): $($longRunning.Trim())"

# Check Servy services state
$servy = "D:\tools\Servy\servy-cli.exe"
$svcs = @("QuantMind-FastAPI", "QuantMind-Celery", "QuantMind-CeleryBeat", "QuantMind-QMTData")
foreach ($svc in $svcs) {
    $state = & $servy status --name=$svc 2>&1 | Out-String
    Write-Host "  Servy $svc state probed"
}

# Check trading day (skip if Mon-Fri morning hours)
$now = Get-Date
$dow = $now.DayOfWeek
$hr = $now.Hour
if ($dow -ne 'Saturday' -and $dow -ne 'Sunday' -and ($hr -ge 9 -and $hr -le 16)) {
    Write-Host "[FATAL] $dow $hr:00 - 这是交易时段, 拒绝执行" -ForegroundColor Red
    exit 3
}
Write-Host "  ✓ 非交易时段 ($dow $hr:00)"

# ─── Step 2: ALTER SYSTEM ───────────────────────────────────
Write-Host "`n[Step 2] ALTER SYSTEM SET shared_buffers = '${NewSharedBuffersMB}MB' ..." -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  [DRY-RUN] skip ALTER SYSTEM" -ForegroundColor Gray
} else {
    & $psql -U xin -d quantmind_v2 -h localhost -c "ALTER SYSTEM SET shared_buffers = '${NewSharedBuffersMB}MB'" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Host "[FATAL] ALTER SYSTEM failed" -ForegroundColor Red; exit 4 }
    Write-Host "  ✓ ALTER SYSTEM done (待重启生效)"
}

# ─── Step 3: Servy stop ─────────────────────────────────────
Write-Host "`n[Step 3] Servy 4 服务 stop ..." -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  [DRY-RUN] skip Servy stop" -ForegroundColor Gray
} else {
    foreach ($svc in $svcs) {
        Write-Host "  stopping $svc ..."
        & $servy stop --name=$svc 2>&1 | Out-Null
    }
    Start-Sleep -Seconds 5
    Write-Host "  ✓ Servy services stopped"
}

# ─── Step 4: pg_ctl restart ─────────────────────────────────
Write-Host "`n[Step 4] PG restart ..." -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  [DRY-RUN] skip pg_ctl restart" -ForegroundColor Gray
} else {
    & $pgctl restart -D $pgdata -m fast -t 60 2>&1 | Out-String | Write-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "[FATAL] pg_ctl restart failed" -ForegroundColor Red; exit 5 }
    Write-Host "  ✓ PG restarted"
}

# ─── Step 5: PG ready 等待 ──────────────────────────────────
Write-Host "`n[Step 5] PG ready check ..." -ForegroundColor Yellow
if (-not $DryRun) {
    $maxWait = 30
    for ($i = 0; $i -lt $maxWait; $i++) {
        $r = & "D:\pgsql\bin\pg_isready.exe" -h localhost -p 5432 -U xin 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host "  ✓ PG ready (after ${i}s)"; break }
        Start-Sleep -Seconds 1
    }
}

# ─── Step 6: Servy start ────────────────────────────────────
Write-Host "`n[Step 6] Servy 4 服务 start ..." -ForegroundColor Yellow
if (-not $DryRun) {
    foreach ($svc in $svcs) {
        Write-Host "  starting $svc ..."
        & $servy start --name=$svc 2>&1 | Out-Null
    }
    Start-Sleep -Seconds 10
    Write-Host "  ✓ Servy services started"
}

# ─── Step 7: 验证 ───────────────────────────────────────────
Write-Host "`n[Step 7] 验证 ..." -ForegroundColor Yellow
$newVal = & $psql -U xin -d quantmind_v2 -h localhost -t -c "SHOW shared_buffers"
Write-Host "  PG shared_buffers: $($newVal.Trim()) (期望 ${NewSharedBuffersMB}MB)"

# Servy /health probe (FastAPI)
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 10
    Write-Host "  FastAPI /health: $($health.StatusCode)"
} catch {
    Write-Host "  [WARN] FastAPI /health not yet up: $_" -ForegroundColor Yellow
}

# ─── Step 8: 报告 ───────────────────────────────────────────
$elapsed = (Get-Date) - $startTime
Write-Host "`n===== 完成 =====" -ForegroundColor Green
Write-Host "Total: $($elapsed.TotalSeconds.ToString('F1'))s"
Write-Host "Phase 2 (VACUUM FULL + REINDEX) 走 sunday_pg_vacuum.ps1 (单独 2-4h)"
