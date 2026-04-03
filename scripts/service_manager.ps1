<#
.SYNOPSIS
    QuantMind V2 服务管理脚本 (Servy)
.DESCRIPTION
    管理所有QuantMind Windows服务的启动、停止、重启和状态查询。
    服务启动顺序: Redis/PostgreSQL(原生) -> FastAPI -> Celery Worker -> Celery Beat
.EXAMPLE
    .\service_manager.ps1 status
    .\service_manager.ps1 start all
    .\service_manager.ps1 restart fastapi
    .\service_manager.ps1 stop worker
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action,

    [Parameter(Position=1)]
    [ValidateSet("all", "fastapi", "worker", "beat")]
    [string]$Service = "all"
)

$ServyCli = "D:\tools\Servy\servy-cli.exe"

# 服务定义（启动顺序）
$Services = [ordered]@{
    fastapi = "QuantMind-FastAPI"
    worker  = "QuantMind-Celery"
    beat    = "QuantMind-CeleryBeat"
}

# 原生服务（只查状态，不管理）
$NativeServices = @("Redis", "PostgreSQL16")

function Write-ColorStatus {
    param([string]$Name, [string]$Status)
    $color = if ($Status -eq "Running") { "Green" } elseif ($Status -eq "Stopped") { "Red" } else { "Yellow" }
    Write-Host "  $Name" -NoNewline
    Write-Host (" " * [Math]::Max(1, 30 - $Name.Length)) -NoNewline
    Write-Host $Status -ForegroundColor $color
}

function Get-ServiceDetail {
    param([string]$ServiceName)
    $svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
    if (-not $svc) { return $null }

    $proc = $null
    if ($svc.ProcessId -and $svc.ProcessId -ne 0) {
        $proc = Get-Process -Id $svc.ProcessId -ErrorAction SilentlyContinue
    }

    return @{
        Name      = $svc.Name
        Display   = $svc.DisplayName
        Status    = $svc.State
        PID       = if ($svc.ProcessId -and $svc.ProcessId -ne 0) { $svc.ProcessId } else { "-" }
        Memory    = if ($proc) { "{0:N0} MB" -f ($proc.WorkingSet64 / 1MB) } else { "-" }
        StartMode = $svc.StartMode
    }
}

function Show-Status {
    Write-Host "`n=== QuantMind V2 Service Status ===" -ForegroundColor Cyan
    Write-Host "`n--- Native Services (not managed) ---" -ForegroundColor DarkGray

    foreach ($name in $NativeServices) {
        $detail = Get-ServiceDetail $name
        if ($detail) {
            Write-ColorStatus $detail.Display $detail.Status
            Write-Host "    PID: $($detail.PID)  Memory: $($detail.Memory)" -ForegroundColor DarkGray
        } else {
            Write-ColorStatus $name "Not Found"
        }
    }

    Write-Host "`n--- Servy-Managed Services ---"
    foreach ($key in $Services.Keys) {
        $svcName = $Services[$key]
        $detail = Get-ServiceDetail $svcName
        if ($detail) {
            Write-ColorStatus $detail.Display $detail.Status
            Write-Host "    PID: $($detail.PID)  Memory: $($detail.Memory)  StartMode: $($detail.StartMode)" -ForegroundColor DarkGray
        } else {
            Write-ColorStatus $svcName "Not Registered"
        }
    }

    # Health check (use curl for reliability)
    Write-Host "`n--- Health Check ---"
    try {
        $raw = & curl.exe -s --max-time 5 "http://localhost:8000/api/system/health" 2>&1
        $health = $raw | ConvertFrom-Json -ErrorAction Stop
        $color = if ($health.overall_status -eq "ok") { "Green" } else { "Red" }
        Write-Host "  API Health: $($health.overall_status)" -ForegroundColor $color
        Write-Host "    PG: $($health.pg.ok)  Redis: $($health.redis.ok)  Celery: $($health.celery.ok) (workers: $($health.celery.worker_count))" -ForegroundColor DarkGray
        Write-Host "    Disk: $($health.disk.free_gb)GB free  Memory: $($health.memory.used_gb)/$($health.memory.total_gb)GB ($($health.memory.percent)%)" -ForegroundColor DarkGray
    } catch {
        Write-Host "  API Health: UNREACHABLE" -ForegroundColor Red
    }
    Write-Host ""
}

function Invoke-ServiceAction {
    param([string]$ActionName, [string]$ServiceKey)

    if ($ServiceKey -eq "all") {
        # 停止时反序: beat -> worker -> fastapi
        $orderedKeys = if ($ActionName -eq "stop") {
            @("beat", "worker", "fastapi")
        } else {
            @("fastapi", "worker", "beat")
        }

        foreach ($key in $orderedKeys) {
            Invoke-ServiceAction $ActionName $key
        }
        return
    }

    $svcName = $Services[$ServiceKey]
    if (-not $svcName) {
        Write-Host "Unknown service: $ServiceKey" -ForegroundColor Red
        return
    }

    switch ($ActionName) {
        "start" {
            Write-Host "Starting $svcName..." -NoNewline
            & $ServyCli start --name="$svcName" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED" -ForegroundColor Red
            }
        }
        "stop" {
            Write-Host "Stopping $svcName..." -NoNewline
            & $ServyCli stop --name="$svcName" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED (may already be stopped)" -ForegroundColor Yellow
            }
        }
        "restart" {
            Write-Host "Restarting $svcName..." -NoNewline
            & $ServyCli restart --name="$svcName" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED" -ForegroundColor Red
            }
        }
    }
}

# Main
if ($Action -eq "status") {
    Show-Status
} else {
    Invoke-ServiceAction $Action $Service
    if ($Action -ne "stop") {
        Start-Sleep -Seconds 3
    }
    Show-Status
}
