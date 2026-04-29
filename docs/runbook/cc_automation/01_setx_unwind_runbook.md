# Runbook 01 — 撤回 D2.3 临时 setx (`SKIP_NAMESPACE_ASSERT=1`)

> **状态**: 存档 (待批 2 P3 完成后调用)
> **预计耗时**: 2-3 min (含验证)
> **真金风险**: 0
> **作者**: D2.3 fix 后归档 (2026-04-30)

---

## 1. 背景

D2.3 修复 FastAPI 启动失败 (`NamespaceMismatchError`) 的临时手段:

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', '1', 'Machine')
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'
```

**根因** (Finding K, D2.3): Servy 4 服务全 LocalSystem, setx User scope 不继承, 必须 Machine setx.

**永久修法** (批 2 P3): `backend/app/services/startup_assertions.py` 中 `run_startup_assertions()` 直读 `os.environ.get(_BYPASS_ENV_VAR)` 那行 → 改用 `settings.SKIP_NAMESPACE_ASSERT` (Pydantic 加载 `.env`, 不污染 system env). 详见 D2.2 Finding G.

> 不写具体行号: 该文件批 2 P3 必修, 行号会漂移. 用 code-quote 引用更稳.

**本 runbook 触发条件**: 批 2 P3 commit merged + FastAPI 重启验证 OK 后, 撤 Machine env 还干净.

---

## 2. 真金 0 风险确认 (前置, 不通过立即 STOP)

**所有命令以 PowerShell 7.6+ (user 默认 `pwsh`, 实测 7.6.1) 或兼容 Windows PowerShell 5.1 (`powershell.exe`, 系统自带 5.1.26100.8115) 在 Windows 11 主机执行** — 本 runbook 用的命令 (`Start-Sleep` / `[Environment]::SetEnvironmentVariable` / `& 'path'` / `Select-String` / 等) 在两版本均兼容. .venv Python 通过 `.venv\Scripts\python.exe` 调.

> 2026-04-30 实测纠错: 原写 "PowerShell 5.1" 是基于"Windows 项目默认"假设, 实测 user 装 PowerShell 7.6.1 为默认. LL-XXX (audit 一阶概括必须实测纠错): 写 runbook 时假设 shell 版本应实测 `powershell.exe -NoProfile -Command "$PSVersionTable.PSVersion.ToString()"` + `pwsh -NoProfile ...`, 不凭 "Windows 默认" 印象.

| # | 检查 | 命令 (PowerShell) | 期望 |
|---|------|------|------|
| 1 | LIVE_TRADING_DISABLED 仍 active | `.venv\Scripts\python.exe -c "from app.config import settings; print(settings.LIVE_TRADING_DISABLED)"` | `True` |
| 2 | EXECUTION_MODE | `.venv\Scripts\python.exe -c "from app.config import settings; print(settings.EXECUTION_MODE)"` | `paper` 或 user 已确认 live cutover |
| 3 | 批 2 P3 commit (informational, 实硬门是 #4) | `git log --oneline main \| Select-String "SKIP_NAMESPACE_ASSERT"` | 至少 1 commit (太宽 grep, 仅辅助参考) |
| 4 | **批 2 P3 完成 detector (硬门)**: `settings.SKIP_NAMESPACE_ASSERT` 真 attr | `.venv\Scripts\python.exe -c "from app.config import settings; print(hasattr(settings, 'SKIP_NAMESPACE_ASSERT'))"` | `True` (必硬门) |

> **检查 #4 是 batch 2 P3 完成 detector** — 该 attr 不存在于 config.py 当前代码, 必须批 2 P3 加 `SKIP_NAMESPACE_ASSERT: bool = False` 字段后才返 `True`. 即便 #3 误命中老 commit, #4 是 code-level 硬门, 防 false-proceed.

**任一检查不满足** → 立即 STOP 反问 user, 不执行撤 setx.

---

## 3. 前置检查清单 (state snapshot, 撤前必录)

### 3.1 系统 env 实测

```powershell
# 当前 Machine env (D2.3 留下的)
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')
# 期望: '1'

# 当前 User env (D2.2 user 操作过)
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'User')
# 期望: '1' 或 '' (取决于 user D2.2 是否真打了 setx)
```

### 3.2 FastAPI 当前状态 (撤 setx 前必须 Running, 防对照失明)

```powershell
& 'D:\tools\Servy\servy-cli.exe' status --name='QuantMind-FastAPI'
# 期望: Running

# /health 当前响应
.venv\Scripts\python.exe -c "import urllib.request, json; r = urllib.request.urlopen('http://localhost:8000/health', timeout=5); print(json.loads(r.read()))"
# 期望: {'status': 'ok', 'execution_mode': 'paper' (或 'live')}
```

### 3.3 DB row count 快照 (验证清单 §5 #6 用)

```powershell
.venv\Scripts\python.exe -c @"
import psycopg2
conn = psycopg2.connect(dbname='quantmind_v2', user='xin', host='127.0.0.1', password='quantmind')
cur = conn.cursor()
cur.execute('SELECT count(*) FROM cb_state'); cb = cur.fetchone()[0]
cur.execute('SELECT count(*) FROM gp_approval_queue'); aq = cur.fetchone()[0]
print(f'cb_state={cb} gp_approval_queue={aq}')
"@
# 记录到本 STATUS_REPORT, e.g. cb_state=10 gp_approval_queue=5
```

> 必须录到 `docs/audit/STATUS_REPORT_<date>_setx_unwind.md` §3 才能在 §5 #6 比对.

**全部通过** → 进入执行. **任一异常** → STOP, 报 user 决议.

---

## 4. 执行步骤 (PowerShell)

### Step 1: 撤 Machine env (D2.3 留)

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')
# 期望: 空白 (无输出 / NULL)
```

### Step 2: 撤 User env (D2.2 user 留)

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'User')
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'User')
# 期望: 空白
```

### Step 3: Servy restart QuantMind-FastAPI (load 新 env state — 现 settings.SKIP 生效)

```powershell
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'
```

### Step 4: 等 FastAPI 启动 + /health 验证 (settings 生效, 不依赖 env)

```powershell
# 等 FastAPI 启动 ~5s
Start-Sleep -Seconds 5

# 健康检查
.venv\Scripts\python.exe -c "import urllib.request, json; r = urllib.request.urlopen('http://localhost:8000/health', timeout=5); print(json.loads(r.read()))"
# 期望: {'status': 'ok', 'execution_mode': 'paper'} (或 live)

# Servy status
& 'D:\tools\Servy\servy-cli.exe' status --name='QuantMind-FastAPI'
# 期望: Running, PID > 0
```

### Step 5: admin gate auth 验证 (PR #152 + 后续守门)

```powershell
# 5.1: 401 (无 token)
.venv\Scripts\python.exe -c "import urllib.request, urllib.error; req = urllib.request.Request('http://localhost:8000/api/execution/cancel-all', method='POST'); 
try:
    urllib.request.urlopen(req, timeout=5)
except urllib.error.HTTPError as e:
    print(f'status={e.code}')"
# 期望: status=401

# 5.2: 503 (有正确 token, QMT 未连)
# 必须先从 settings 读取 ADMIN_TOKEN (不依赖 shell 隐式状态)
$ADMIN_TOKEN = (.venv\Scripts\python.exe -c "from app.config import settings; print(settings.ADMIN_TOKEN)").Trim()
if (-not $ADMIN_TOKEN) {
    Write-Host "skip 5.2: ADMIN_TOKEN 未配置 (settings.ADMIN_TOKEN='')"
} else {
    .venv\Scripts\python.exe -c "
import urllib.request, urllib.error, sys
req = urllib.request.Request('http://localhost:8000/api/execution/cancel-all', method='POST', headers={'X-Admin-Token': '$ADMIN_TOKEN'})
try:
    r = urllib.request.urlopen(req, timeout=5); print(f'status={r.status}')
except urllib.error.HTTPError as e:
    print(f'status={e.code}')
"
    # 期望: status=503 (QMT 未连接) 或 status=200 (QMT 真连)
}
```

> **注意**: `$ADMIN_TOKEN` 必须从 `settings.ADMIN_TOKEN` 显式读取, 不依赖 `$env:ADMIN_TOKEN` 或其他 shell 隐式状态. 如 `settings.ADMIN_TOKEN=''` (未配置), 跳过 5.2 (test 不可比对).

---

## 5. 验证清单 (硬门, 任一 fail → 失败回滚 §6)

| # | 检查 | 期望 | 状态 |
|---|------|------|------|
| 1 | Machine env SKIP=NULL | empty | ☐ |
| 2 | User env SKIP=NULL | empty | ☐ |
| 3 | FastAPI Running | PID > 0 | ☐ |
| 4 | /health 200 | `{'status':'ok'}` | ☐ |
| 5 | admin gate 401 (no token) | status=401 | ☐ |
| 6 | DB 行数 == §3.3 snapshot | cb_state / gp_approval_queue 不变 | ☐ |

**全 ✅** → 撤 setx 完成, 写 STATUS_REPORT.
**任一 ❌** → 进 §6 失败回滚.

---

## 6. 失败回滚

### 场景 A: Step 4 FastAPI 不起来 (settings.SKIP 没生效或别的原因)

```powershell
# 立即恢复 Machine env (D2.3 配置)
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', '1', 'Machine')
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'

# 验证恢复
Start-Sleep -Seconds 5
.venv\Scripts\python.exe -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://localhost:8000/health', timeout=5).read()))"
# 期望: 恢复 {'status':'ok'}
```

回滚后 STOP, 报 user — 真因可能是批 2 P3 commit 有 bug 或 settings.SKIP 没真活, 不要重试撤 setx.

### 场景 B: /health OK 但 admin gate 异常 (返 500 / 200 with no token)

```powershell
# 不回滚 setx (env 跟 admin gate 无关)
# 直接报 user — 可能是无关 PR 把 ADMIN_TOKEN 配置改了
```

---

## 7. STATUS_REPORT 输出

`docs/audit/STATUS_REPORT_<YYYY_MM_DD>_setx_unwind.md` 必含:

1. **触发条件** (批 2 P3 commit hash + merged 时间)
2. **§3 前置检查实测结果** (3.1 env / 3.2 FastAPI / 3.3 DB row count snapshot)
3. **§4 执行步骤实测命令 + stdout** (5 步全)
4. **§5 验证清单** (6 项 ✅/❌)
5. **失败回滚是否触发** (是 / 否) + 触发场景 + 还原状态
6. **后续清单** (无 — 撤 setx 是终点)

---

## 8. 关联

- **D2.2** ([STATUS_REPORT_2026_04_29_D2_2.md](../../audit/STATUS_REPORT_2026_04_29_D2_2.md)): FastAPI 启动失败诊断 + Finding G (startup_assertions 改用 settings)
- **D2.3** ([STATUS_REPORT_2026_04_30_D2_3.md](../../audit/STATUS_REPORT_2026_04_30_D2_3.md)): Servy LocalSystem env scope 实测 + Machine setx 修复 + Finding K
- **批 2 P3 commit**: 待批 2 完成时填写 commit hash
- **铁律 35** (CLAUDE.md): secrets 环境变量唯一 — 撤 setx 后 SKIP 不再污染 Machine env, 走 .env → Pydantic settings 单一来源
