# nssm_setup.ps1 — QuantMind V2 Windows 服务注册脚本
#
# 参考: docs/research/R6_production_architecture.md §3.1
# NSSM (Non-Sucking Service Manager) 将 FastAPI + Celery 注册为 Windows 服务，
# 支持崩溃自动重启、stdout/stderr 日志重定向、开机自启。
#
# 用法:
#   以管理员权限运行 PowerShell，执行:
#   .\scripts\nssm_setup.ps1
#
# 注意: 本脚本仅生成服务配置，不会真正安装服务（参数 -WhatIf 模式）。
#        要实际安装，将脚本末尾的 $DryRun = $true 改为 $false。

param(
    [switch]$Install,          # Install services (default: DryRun)
    [switch]$Uninstall,        # Uninstall registered services
    [switch]$Status            # Show service status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# 配置区（根据实际环境调整）
# ---------------------------------------------------------------------------

$ProjectRoot  = "D:\quantmind-v2"
$BackendDir   = "$ProjectRoot\backend"
$PythonExe    = "$ProjectRoot\.venv\Scripts\python.exe"
$LogDir       = "$ProjectRoot\logs"
$NssmDir      = "D:\tools\nssm"
$NssmExe      = "$NssmDir\win64\nssm.exe"
$NssmDownload = "https://nssm.cc/release/nssm-2.24.zip"

# 服务定义
$Services = @(
    @{
        Name        = "QuantMind-FastAPI"
        Exe         = $PythonExe
        Args        = "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
        WorkDir     = $BackendDir
        StdoutLog   = "$LogDir\fastapi-stdout.log"
        StderrLog   = "$LogDir\fastapi-stderr.log"
        RestartMs   = 3000
        Description = "QuantMind V2 FastAPI 服务 (uvicorn)"
        DependsOn   = "Redis"
    },
    @{
        Name        = "QuantMind-Celery"
        Exe         = $PythonExe
        # --pool=solo: Windows 不支持 fork，solo 是 Windows 推荐方案（R6 §3.2）
        Args        = "-m celery -A app.tasks.celery_app worker --pool=solo --concurrency=1 -Q default,factor_calc,data_fetch -n worker-main@%COMPUTERNAME%"
        WorkDir     = $BackendDir
        StdoutLog   = "$LogDir\celery-stdout.log"
        StderrLog   = "$LogDir\celery-stderr.log"
        RestartMs   = 5000
        Description = "QuantMind V2 Celery Worker (pool=solo)"
        DependsOn   = "Redis"
    }
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

function Write-Header {
    param([string]$Title)
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
}

function Ensure-LogDir {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        Write-Host "  [+] 创建日志目录: $LogDir" -ForegroundColor Green
    }
}

function Ensure-NssmDir {
    if (-not (Test-Path $NssmDir)) {
        New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
        Write-Host "  [+] 创建 NSSM 目录: $NssmDir" -ForegroundColor Green
    }
}

function Download-Nssm {
    Write-Header "下载 NSSM"
    Ensure-NssmDir

    if (Test-Path $NssmExe) {
        Write-Host "  [=] NSSM 已存在: $NssmExe" -ForegroundColor Yellow
        return
    }

    $ZipPath = "$NssmDir\nssm.zip"
    Write-Host "  [*] 从 $NssmDownload 下载..."
    try {
        Invoke-WebRequest -Uri $NssmDownload -OutFile $ZipPath -UseBasicParsing
        Expand-Archive -Path $ZipPath -DestinationPath $NssmDir -Force

        # nssm-2.24 解压后目录结构: nssm-2.24\win64\nssm.exe
        $Extracted = Get-ChildItem -Path $NssmDir -Filter "nssm.exe" -Recurse | `
            Where-Object { $_.FullName -like "*win64*" } | Select-Object -First 1
        if ($null -eq $Extracted) {
            $Extracted = Get-ChildItem -Path $NssmDir -Filter "nssm.exe" -Recurse | Select-Object -First 1
        }
        if ($null -ne $Extracted) {
            Copy-Item $Extracted.FullName $NssmExe -Force
            Write-Host "  [+] NSSM 已下载并解压到: $NssmExe" -ForegroundColor Green
        } else {
            Write-Error "  [!] 未找到 nssm.exe，请手动下载并放置到 $NssmExe"
        }
        Remove-Item $ZipPath -Force
    } catch {
        Write-Warning "  [!] 下载失败: $_"
        Write-Host "  请手动下载 NSSM: $NssmDownload"
        Write-Host "  并将 nssm.exe 放置到: $NssmExe"
    }
}

function Install-Service {
    param([hashtable]$Svc)
    $Name = $Svc.Name

    Write-Host "`n  [*] 注册服务: $Name" -ForegroundColor Cyan

    # 如果已存在先停止再删除
    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Write-Host "  [~] 服务已存在，先停止并移除..."
        & $NssmExe stop $Name confirm 2>&1 | Out-Null
        & $NssmExe remove $Name confirm 2>&1 | Out-Null
    }

    # 安装
    & $NssmExe install $Name $Svc.Exe $Svc.Args
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "  [!] 安装失败: $Name (exit=$LASTEXITCODE)"
        return
    }

    # 配置
    & $NssmExe set $Name AppDirectory      $Svc.WorkDir
    & $NssmExe set $Name AppStdout         $Svc.StdoutLog
    & $NssmExe set $Name AppStderr         $Svc.StderrLog
    & $NssmExe set $Name AppStdoutCreationDisposition 4   # 追加模式
    & $NssmExe set $Name AppStderrCreationDisposition 4   # 追加模式
    & $NssmExe set $Name AppRestartDelay   $Svc.RestartMs # 崩溃重启延迟(ms)
    & $NssmExe set $Name Description       $Svc.Description
    & $NssmExe set $Name Start             SERVICE_AUTO_START  # 开机自启

    # 依赖服务（Redis 必须先启动）
    if ($Svc.DependsOn) {
        & $NssmExe set $Name DependOnService $Svc.DependsOn
    }

    # 日志轮转: 单文件超过 100MB 自动轮转
    & $NssmExe set $Name AppRotateFiles    1
    & $NssmExe set $Name AppRotateOnline   1
    & $NssmExe set $Name AppRotateBytes    104857600   # 100 MB

    Write-Host "  [+] 服务已注册: $Name" -ForegroundColor Green

    # 启动服务
    & $NssmExe start $Name
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [+] 服务已启动: $Name" -ForegroundColor Green
    } else {
        Write-Warning "  [!] 启动失败，请检查日志: $($Svc.StderrLog)"
    }
}

function Uninstall-QuantMindServices {
    Write-Header "卸载 QuantMind 服务"
    foreach ($Svc in $Services) {
        $Name = $Svc.Name
        $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            Write-Host "  [*] 停止并移除: $Name"
            & $NssmExe stop $Name confirm 2>&1 | Out-Null
            & $NssmExe remove $Name confirm
            Write-Host "  [+] 已移除: $Name" -ForegroundColor Green
        } else {
            Write-Host "  [=] 服务不存在: $Name" -ForegroundColor Yellow
        }
    }
}

function Show-ServiceStatus {
    Write-Header "QuantMind Service Status"
    foreach ($Svc in $Services) {
        $Name = $Svc.Name
        $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            $color = if ($existing.Status -eq "Running") { "Green" } else { "Yellow" }
            Write-Host ("  {0,-30} {1}" -f $Name, $existing.Status) -ForegroundColor $color
        } else {
            Write-Host ("  {0,-30} {1}" -f $Name, "Not Registered") -ForegroundColor Red
        }
    }

    # 显示日志目录
    Write-Host "`n  日志目录: $LogDir"
    if (Test-Path $LogDir) {
        Get-ChildItem $LogDir -Filter "*.log" | ForEach-Object {
            $SizeMB = [math]::Round($_.Length / 1MB, 2)
            Write-Host ("  {0,-35} {1} MB" -f $_.Name, $SizeMB)
        }
    }
}

function Show-DryRunPlan {
    Write-Header "DryRun — 以下命令将在 -Install 时执行"
    Write-Host "  NSSM 路径: $NssmExe"
    Write-Host "  日志目录:  $LogDir"
    Write-Host ""
    foreach ($Svc in $Services) {
        Write-Host "  服务: $($Svc.Name)" -ForegroundColor Cyan
        Write-Host "    Exe:     $($Svc.Exe)"
        Write-Host "    Args:    $($Svc.Args)"
        Write-Host "    WorkDir: $($Svc.WorkDir)"
        Write-Host "    Stdout:  $($Svc.StdoutLog)"
        Write-Host "    Stderr:  $($Svc.StderrLog)"
        Write-Host "    Restart: $($Svc.RestartMs) ms"
        Write-Host "    Depends: $($Svc.DependsOn)"
        Write-Host ""
    }
    Write-Host "  要实际安装，以管理员权限执行:" -ForegroundColor Yellow
    Write-Host "    .\scripts\nssm_setup.ps1 -Install" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

Write-Header "QuantMind V2 — NSSM 服务管理器"
Write-Host "  项目根目录: $ProjectRoot"
Write-Host "  Python 解释器: $PythonExe"

if ($Status) {
    Show-ServiceStatus
    exit 0
}

if ($Uninstall) {
    # 卸载需要 NSSM
    if (-not (Test-Path $NssmExe)) {
        Write-Error "NSSM 未找到: $NssmExe"
    }
    Uninstall-QuantMindServices
    exit 0
}

if ($Install) {
    # 验证前置条件
    Write-Header "前置条件检查"

    if (-not (Test-Path $PythonExe)) {
        Write-Error "Python 解释器未找到: $PythonExe`n请先创建虚拟环境: python -m venv .venv"
    }
    Write-Host "  [+] Python: $PythonExe" -ForegroundColor Green

    if (-not (Test-Path $BackendDir)) {
        Write-Error "Backend 目录未找到: $BackendDir"
    }
    Write-Host "  [+] Backend: $BackendDir" -ForegroundColor Green

    # 检查管理员权限
    $IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if (-not $IsAdmin) {
        Write-Error "需要管理员权限！请以管理员身份运行 PowerShell。"
    }
    Write-Host "  [+] 管理员权限: OK" -ForegroundColor Green

    # 准备工作
    Ensure-LogDir
    Download-Nssm

    if (-not (Test-Path $NssmExe)) {
        Write-Error "NSSM 安装失败，请手动下载: $NssmDownload"
    }

    # 安装各服务
    Write-Header "安装 Windows 服务"
    foreach ($Svc in $Services) {
        Install-Service -Svc $Svc
    }

    Write-Header "安装完成"
    Show-ServiceStatus
} else {
    # 默认: DryRun，只打印计划
    Show-DryRunPlan
}
