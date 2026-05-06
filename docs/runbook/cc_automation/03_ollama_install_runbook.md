# Runbook 03 — Ollama D 盘 install + qwen3.5:9b model pull (S3 PR #225)

**触发场景**: Sprint 1 S3 sub-task — 启用 BudgetAwareRouter Capped100 fallback path. user 跑装 + ollama pull, CC 0 触碰 install (沿用 LL-098 X10).

**真金 0 风险**:
- LLM fallback 路径 0 broker call (反 LiteLLMRouter / BudgetAwareRouter 跟 broker.place_order/cancel_order 0 接触)
- LIVE_TRADING_DISABLED guard 沿用
- Ollama service 本地 listening 11434 (反对外暴露)

---

## prerequisite

| 项 | 期望 |
|---|---|
| OS | Win11 (业界沿用 Ollama Win 10/11 GA) |
| RAM | ≥ 16 GB (qwen3.5:9b inference ~8-10 GB working set, 32 GB 沿用) |
| GPU | RTX 5070 12 GB VRAM (qwen3.5:9b Q4_K_M ~9.6 GB VRAM peak, 自动 CUDA 加速, 5-06 stress test 实测 78% 利用率 ~2.6 GB headroom) |
| D 盘 free | ≥ 12 GB (runtime ~500 MB + qwen3.5:9b 6.6 GB + 余量) |
| admin 权限 | UAC click 1 次 (install + setx /M) |
| LIVE_TRADING_DISABLED | 沿用 .env true |
| EXECUTION_MODE | 沿用 .env paper |

---

## install steps (3 步, ~15-20 min wall-clock)

### Step 1: 下载 OllamaSetup.exe

**Option A (PS 命令)**:

```powershell
# PS 7+ 沿用. PS 5.1 一致跑 (Invoke-WebRequest 内置).
$url = "https://ollama.com/download/OllamaSetup.exe"
$dst = "$env:TEMP\OllamaSetup.exe"
Invoke-WebRequest -Uri $url -OutFile $dst
Write-Host "下载完成: $dst"
```

**Option B (浏览器)**:

打开 https://ollama.com/download/windows → click "Download for Windows" → 保存到下载目录 (e.g. `D:\Downloads\OllamaSetup.exe`).

期望: ~200 MB OllamaSetup.exe 落本地.

---

### Step 2: PS as admin 跑 install (D 盘 + UAC click)

**先以管理员身份打开 PowerShell** (右键 PS 图标 → "以管理员身份运行"). UAC 弹窗 1 次 → click "Yes".

```powershell
# /DIR 参数沿用 GitHub issue #2776 PR #6967 GA (Ollama 官方支持自定义 install 路径).
Start-Process "$env:TEMP\OllamaSetup.exe" -ArgumentList '/DIR="D:\tools\Ollama"' -Wait
```

(若 Step 1 走 Option B 浏览器下载, 把 `$env:TEMP\OllamaSetup.exe` 改成实际下载路径, e.g. `D:\Downloads\OllamaSetup.exe`.)

期望:
- 安装向导 GUI 弹出 → click "Install" → 进度条跑完 → click "Finish"
- ~30s install
- 自动注册 Windows service "Ollama" + 自启
- 任务栏右下角出现 Ollama tray 图标

---

### Step 3: PS as admin 设 OLLAMA_MODELS env var (system-level)

**沿用 Step 2 admin PS 窗口**:

```powershell
# /M flag 走 system-level (Machine, sustained Ollama service 启动时读 system env).
# 反 user-level (HKEY_CURRENT_USER) — service 不读 user env.
setx OLLAMA_MODELS "D:\ollama-models" /M

# 验证 system-level env 已写
[Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine")
# 期望输出: D:\ollama-models
```

期望: 输出 `D:\ollama-models`.

**重启 Ollama service 走新 env**:

```powershell
# Ollama tray + service 必重启走 new env (沿用官方 Ollama Windows docs).
# 方法 A (CLI, 推荐):
Restart-Service Ollama

# 方法 B (GUI):
# 任务栏右下角 Ollama tray 图标 → 右键 "Quit Ollama" → 开始菜单 "Ollama" 启动
```

---

## post-install verify checklist

跑下面 5 项 (任一 fail → troubleshoot):

```powershell
# 1. install 成功 + version cite
ollama --version
# 期望: ollama version is X.Y.Z (X >= 0.5)

# 2. service 启动 + 0 model loaded (initial)
ollama list
# 期望: NAME ID SIZE MODIFIED 表头 + 空 row (or 仅 header)

# 3. API listening 11434
Test-NetConnection localhost -Port 11434
# 期望: TcpTestSucceeded : True

# 4. Windows service 注册沿用
Get-Service Ollama
# 期望: Status=Running, StartType=Automatic

# 5. system-level env var 沿用
[Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine")
# 期望: D:\ollama-models

# 6. install 路径走 D 盘 (反 fall back C 盘默认 path)
Test-Path "D:\tools\Ollama\ollama.exe"
# 期望: True (沿用 /DIR= 参数生效)
```

6/6 PASS → 进入 model pull. 任一 fail → troubleshoot 段.

---

## model pull step (~5-15 min, 看带宽)

```powershell
# qwen3.5:9b ~6.6 GB (Ollama 官方 library, default Q4_K_M quantization, 5-06 ADR-034 sediment)
ollama pull qwen3.5:9b

# 验证 model 沿用
ollama list
# 期望: qwen3.5:9b X.YGB (~6.6 GB)
```

**验证 model 路径走 D:\ollama-models** (反走 `%USERPROFILE%\.ollama\models` C 盘):

```powershell
# 真值 path verify
Get-ChildItem "D:\ollama-models\models\blobs\" | Select-Object -First 3
# 期望: 3 个 sha256-* blob 文件 (qwen3.5:9b 真 chunks)

# 反例: C 盘 path 真**应空** (反 D 盘 setx 失败)
Test-Path "$env:USERPROFILE\.ollama\models\blobs"
# 期望: False (沿用) 或 True 但**空**
```

D 盘 path 含 blobs ✅ → install 完成. 进入 e2e test 验证.

---

## VRAM stress test 验证 (5-06 ADR-034 sediment, RTX 5070 12 GB fit verify)

```powershell
# 1. nvidia-smi baseline (model 0 loaded)
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits
# 期望 baseline: ~1.5-2 GB / 12.2 GB (~13%, 仅桌面 + 别的 app)

# 2. qwen3.5:9b stress test (短 prompt + --verbose 拿 token/s)
"你好, 请用 100 字介绍下量化交易策略" | ollama run qwen3.5:9b --verbose
# 期望 verbose stat:
#   total duration:       ~10s
#   load duration:        ~5s (model load 进 VRAM)
#   prompt eval rate:     ~470 tokens/s
#   eval count:           ~300-400 tokens
#   eval rate:            ~70-75 tokens/s

# 3. nvidia-smi peak (model loaded + keepalive 沿用)
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits
# 期望 peak: ~9.6 GB / 12.2 GB (~78% utilization, ~2.6 GB headroom 反 OOM)
```

3/3 PASS → VRAM fit RTX 5070 12 GB ✅. 任一 fail (peak > 11 GB / OOM / token rate < 50 t/s) → troubleshoot 段 GPU 0 加速 / 重启 service.

> **stress test 真值 5-06 实测**: VRAM 1643 MB baseline → **9592 MB peak (78%, ~2.6 GB headroom)** / GPU 27% idle post-load / total duration 9.8s / load 5.0s / prompt eval 472.57 t/s / **eval 73.36 t/s** / 343 output tokens. 沿用 ADR-034 §4 Positive cite.

---

## e2e test 验证 (S3 PR #225 sediment)

```powershell
# 跑 1-2 e2e 冒烟 (requires_ollama marker, sustained pyproject.toml)
# 沿用 reviewer Chunk B P3-3: powershell fence + backslash path 跟全文件一致
Set-Location D:\quantmind-v2
.\.venv\Scripts\python.exe -m pytest backend\tests\test_litellm_e2e.py -m requires_ollama -v
# 期望: 1-2 PASSED (Ollama running + qwen3.5:9b loaded)
```

---

## troubleshoot section

### Ollama service 不启动

```powershell
# 查 Windows event log (Ollama 跟错误 cite, 沿用 reviewer Chunk B P3-2 fallback)
Get-EventLog -LogName Application -Source Ollama -Newest 10 -ErrorAction SilentlyContinue
# 若 0 result (Ollama 可能未注册 classic Event Log source) → 走 Get-WinEvent fallback:
Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Ollama'} -MaxEvents 10 -ErrorAction SilentlyContinue

# 手工启动 service
Start-Service Ollama

# 看 service 状态
Get-Service Ollama | Format-List Status, StartType, Description
```

### port 11434 占用

```powershell
# 查 11434 沿用进程
Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue
# 若沿用进程不是 ollama.exe → 换 OLLAMA_HOST env var port:
# setx OLLAMA_HOST "localhost:11435" /M (system-level), 重启 service

# 同步改 backend/.env OLLAMA_BASE_URL=http://localhost:11435
```

### GPU 0 加速 (CPU 模式跑)

```powershell
# 跑 qwen3.5:9b 一次, 同时看 ollama 进程 GPU 内存
ollama run qwen3.5:9b "test" --verbose

# 另一窗口:
nvidia-smi
# 期望: ollama.exe 沿用 ~5 GB VRAM (CUDA 加速). 若 0 → 检查驱动 + CUDA toolkit
```

### model 下载到 C 盘 (反 D 盘)

OLLAMA_MODELS env var 0 system-level 写入 (走 user-level), service 0 读到. 修复:

```powershell
# 重设 system-level (沿用 /M flag)
setx OLLAMA_MODELS "D:\ollama-models" /M

# 重启 service
Restart-Service Ollama

# 手工迁移 C 盘老 model 到 D 盘 (反 re-download)
Move-Item "$env:USERPROFILE\.ollama\models" "D:\ollama-models\models" -Force
```

---

## 失败回滚 (per-step rollback, sustained 00_INDEX 模板字段 6)

| step fail | 真值现象 | 回滚操作 |
|---|---|---|
| Step 1 (下载 .exe fail) | Invoke-WebRequest 真**timeout / 404** | 手工浏览器走 https://ollama.com/download/windows 下载, 或 retry PS 命令 |
| Step 2 (PS Start-Process install fail) | UAC denied / `/DIR=` 0 生效 / 安装向导 abort | (a) 若 install 路径 partial: `Get-ChildItem "D:\tools\Ollama"` 查看真值, 跑现 unins000.exe 清理 (`Start-Process "D:\tools\Ollama\unins000.exe" -Wait`), 反 ls 0 file → 手工 `Remove-Item -Recurse -Force "D:\tools\Ollama"` (b) 0 install 痕迹 → 重 Step 2 (反 admin PS / UAC click) |
| Step 3 (setx /M fail) | 0 admin / `Access denied` | (a) 验证 admin: `whoami /priv \| Select-String SeIncreaseQuotaPrivilege` (b) 重新打开 PS as admin → 重 Step 3 (c) 备选 GUI: 控制面板 → 系统 → 高级 → 环境变量 → 系统变量 → 新建 `OLLAMA_MODELS` |
| Step 3 (Restart-Service fail) | service 0 known / Stop hang | (a) `Get-Service Ollama` 验证 service 注册 (Step 2 install 沿用) (b) 手工 GUI 退 tray → 开始菜单 Ollama 启动 (c) 反生效 → reboot Win11 后 service 自启 |
| model pull fail | `ollama pull` 真**network timeout / disk full** | (a) 验证 D 盘 free space `Get-PSDrive D` (≥10 GB) (b) 验证 OLLAMA_MODELS 沿用: `[Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine")` (c) `Restart-Service Ollama` + 重 pull (d) 反 fall back C 盘 → 删 partial cache `Remove-Item -Recurse -Force "$env:USERPROFILE\.ollama\models" -ErrorAction SilentlyContinue` |
| 部分 install + 完全卸载 | 多 step fail 累积 / install state 漂移 | 走 ## uninstall section 真 3 步完整还原 (uninstaller + rm models + setenv null), 沿用全 reset |

**沿用原则**:
- 反 silent partial state (沿用铁律 33 fail-loud)
- 反**force push** / **destructive action** without verify (沿用 SOP-2)
- uninstall section 真**最终 fallback** (任何 step fail 走完整 reset 后 retry)

---

## uninstall section (运维需要)

```powershell
# 1. PS as admin, 跑 uninstaller
# 注: 沿用 Inno Setup 默认 uninstaller 名 unins000.exe. 若 Ollama 未来版本改 filename
# (e.g. Uninstall.exe), 先 ls 确认: Get-ChildItem "D:\tools\Ollama" -Filter "unins*.exe"
Start-Process "D:\tools\Ollama\unins000.exe" -Wait

# 2. 删除模型 cache (沿用 setx path)
Remove-Item -Recurse -Force "D:\ollama-models"

# 3. 删除 system env var
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $null, "Machine")
```

---

## STATUS_REPORT

完成后归档到:
- `docs/audit/STATUS_REPORT_<date>_ollama_install.md`
- 含: install 时间 / 5/5 verify checklist 真值 / qwen3.5:9b sha256 hash / e2e test 真测 1-2 PASSED 输出 cite / GPU CUDA 加速验证 (nvidia-smi 5 GB VRAM)

---

## 关联

- [config/litellm_router.yaml](../../../config/litellm_router.yaml) (S3 PR #225 ollama→ollama_chat patch)
- [backend/tests/test_litellm_e2e.py](../../../backend/tests/test_litellm_e2e.py) (1-2 e2e 冒烟)
- [docs/LLM_IMPORT_POLICY.md §10.8](../../LLM_IMPORT_POLICY.md)
- ADR-031 §6 (S2 渐进 deprecate plan, S3 Ollama wire 沿用)
- V3 §20.1 #6 line 1769 (LLM 月预算 + 100% Ollama fallback 沿用)
- [GitHub issue #2776](https://github.com/ollama/ollama/issues/2776) (custom install dir support)
- [Ollama qwen3 Library](https://ollama.com/library/qwen3) (5.2 GB Q4_K_M)
- [LiteLLM Ollama Provider Docs](https://docs.litellm.ai/docs/providers/ollama) (ollama_chat better responses)
