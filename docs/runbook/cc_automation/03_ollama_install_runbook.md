# Runbook 03 — Ollama D 盘 install + qwen3:8b model pull (S3 PR #225)

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
| RAM | ≥ 16 GB (qwen3:8b inference ~6-8 GB working set, 32 GB 沿用) |
| GPU | RTX 5070 12 GB VRAM (qwen3:8b Q4_K_M ~5 GB VRAM, 自动 CUDA 加速) |
| D 盘 free | ≥ 10 GB (runtime ~500 MB + qwen3:8b 5.2 GB + 余量) |
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
Start-Process "$env:TEMP\OllamaSetup.exe" -ArgumentList '/DIR="D:\Program Files\Ollama"' -Wait
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
```

5/5 PASS → 进入 model pull. 任一 fail → troubleshoot 段.

---

## model pull step (~5-15 min, 看带宽)

```powershell
# qwen3:8b ~5.2 GB (Ollama 官方 library, default Q4_K_M quantization)
ollama pull qwen3:8b

# 验证 model 沿用
ollama list
# 期望: qwen3:8b X.YGB (~5.2 GB)
```

**验证 model 路径走 D:\ollama-models** (反走 `%USERPROFILE%\.ollama\models` C 盘):

```powershell
# 真值 path verify
Get-ChildItem "D:\ollama-models\models\blobs\" | Select-Object -First 3
# 期望: 3 个 sha256-* blob 文件 (qwen3:8b 真 chunks)

# 反例: C 盘 path 真**应空** (反 D 盘 setx 失败)
Test-Path "$env:USERPROFILE\.ollama\models\blobs"
# 期望: False (沿用) 或 True 但**空**
```

D 盘 path 含 blobs ✅ → install 完成. 进入 e2e test 验证.

---

## e2e test 验证 (S3 PR #225 sediment)

```bash
# 跑 1-2 e2e 冒烟 (requires_ollama marker, sustained pyproject.toml)
cd D:/quantmind-v2
.venv/Scripts/python.exe -m pytest backend/tests/test_litellm_e2e.py -m requires_ollama -v
# 期望: 1-2 PASSED (Ollama running + qwen3:8b loaded)
```

---

## troubleshoot section

### Ollama service 不启动

```powershell
# 查 Windows event log (Ollama 跟错误 cite)
Get-EventLog -LogName Application -Source Ollama -Newest 10 -ErrorAction SilentlyContinue

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
# 跑 qwen3:8b 一次, 同时看 ollama 进程 GPU 内存
ollama run qwen3:8b "test" --verbose

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

## uninstall section (运维需要)

```powershell
# 1. PS as admin, 跑 uninstaller
Start-Process "D:\Program Files\Ollama\unins000.exe" -Wait

# 2. 删除模型 cache (沿用 setx path)
Remove-Item -Recurse -Force "D:\ollama-models"

# 3. 删除 system env var
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $null, "Machine")
```

---

## STATUS_REPORT

完成后归档到:
- `docs/audit/STATUS_REPORT_<date>_ollama_install.md`
- 含: install 时间 / 5/5 verify checklist 真值 / qwen3:8b sha256 hash / e2e test 真测 1-2 PASSED 输出 cite / GPU CUDA 加速验证 (nvidia-smi 5 GB VRAM)

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
