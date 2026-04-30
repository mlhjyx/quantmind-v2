# Servy Env 注入失败诊断 + Machine setx 修复 — 2026-04-30 (D2.3)

> **范围**: D2.2 推荐 user setx (User scope) 后 FastAPI 仍 down. D2.3 实测 setx scope 真因 + 执行 Machine setx 修复.
> **触发**: D2.2 后 user 执行 `setx SKIP_NAMESPACE_ASSERT 1`, FastAPI 仍 startup_assertions raise. 必须实测 Servy run-as account + env scope.
> **方法**: 先看 log + 实测 (沿用批 1.5 + D2 + D2.1 + D2.2 LL-XXX: audit 必须实测纠错)
> **关联铁律**: 25 (改什么读什么) / 26 (验证不跳过) / 33 (fail-loud) / 34 (SSOT) / 35 (secrets) / 36 (precondition)
> **关联文档**: [fastapi_startup_debug_2026_04_29.md](fastapi_startup_debug_2026_04_29.md) / [api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) / [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md)

---

## 📋 执行摘要

| 检查 | 状态 | 关键发现 |
|---|---|---|
| **9 题诊断** | ✅ 全过 | Q1-Q9 全 ✅, 1 重大新发现 (Servy LocalSystem 不继承 User env) |
| **Servy run-as account** | ✅ 实测 | 4 服务全 **LocalSystem** (Win32_Service.StartName) |
| **setx User scope** | ✅ 加载 | User='1' (D2.2 user 执行的) |
| **setx Machine scope** | ❌ 修复前 | `<NOT SET>` → 修复后设 '1' |
| **Servy CLI 7.6 verbs** | ✅ 实测 | 仅 install/uninstall/start/stop/status/restart/export/import (无 update verb) |
| **Servy --env 参数** | ✅ 支持 | Servy.psm1 `[string] $Env`, 但需经 install/import |
| **修复路径选择** | ✅ X | Machine setx + Servy restart (1 命令, 30 秒) |
| **修复执行** | ✅ 成功 | port 8000 listening, /health 200, auth 401/503 全 PASS |
| **真金风险** | 🟢 0 | LIVE_TRADING_DISABLED guard + admin gate + schtask Disabled 三重保护不动 |

---

## ✅ 9 题逐答

### Q1 — Servy services run-as account

**✅ LocalSystem (4/4 服务全部)**:

```
Name                 State   StartName    ProcessId
QuantMind-Celery     Running LocalSystem      6928
QuantMind-CeleryBeat Running LocalSystem     10952
QuantMind-FastAPI    Running LocalSystem     24044
QuantMind-QMTData    Running LocalSystem      6920
```

**意义**: Windows Service 跑 LocalSystem (NT AUTHORITY\SYSTEM) 时:
- ❌ **不继承当前用户 User scope env**
- ✅ **仅继承 Machine scope env (HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment)**

### Q2 — SKIP_NAMESPACE_ASSERT 在 3 env scope 状态 (修复前)

**实测**:
```
User    scope: '1'         ← D2.2 后 user 执行 setx, User scope 已加载
Machine scope: <NOT SET>   ← 这是 root cause: LocalSystem 看不到 User env
Process scope: <NOT SET>   ← 当前 PowerShell 进程未导入
```

`[System.Environment]::GetEnvironmentVariable($name, 'User'|'Machine'|'Process')` 三 scope 实测.

### Q3 — 修复前当前 FastAPI 状态

**❌ Port 8000 NOT listening**:
- `Get-NetTCPConnection -State Listen | Where LocalPort=8000` → 0 row
- `servy-cli status` → "Service status: Running" (Servy 报 Running 假象, 实际 children 反复 spawn-die)
- 当前 master PID 24044 alive (Servy.Service.CLI.exe), child python.exe (uvicorn workers) 反复 die

### Q4 — stderr.log latest 20 行 (after user setx)

**✅ 仍是同一 NamespaceMismatchError** (setx User scope 没生效):
```
File "D:\quantmind-v2\backend\app\services\startup_assertions.py", line 125
    raise NamespaceMismatchError(
EXECUTION_MODE drift detected: .env=paper but DB position_snapshot recent 30d has {'live': 295}
ERROR:    Application startup failed. Exiting.
```

完全相同的 traceback, 与 D2.2 报告一致.

### Q5 — Servy 配置 EnvironmentVariables 支持

**✅ 支持但需 reinstall**:

实测 Servy.psm1 grep:
```powershell
.PARAMETER Env
    Environment variables for the service process. Format: Name=Value;Name=Value. Optional.
$argsList = Add-Arg $argsList "--env" $Env
```

但 servy-cli 7.6 实测 verb 列表:
```
install / uninstall / start / stop / status / restart / export / import / help / version
```

**没有 `update` verb** — 改 env 必须 export → 编辑 → uninstall → install (with --env). 4 步骤, ETA ~5 分钟. 比 Machine setx 重.

### Q6 — Servy 服务注册表 Environment 字段

**✅ 实测全空** (4 服务的 `HKLM:\SYSTEM\CurrentControlSet\Services\<svc>\Environment`):
```
QuantMind-FastAPI: ImagePath, ObjectName=LocalSystem, Environment: (empty), Type: 16
QuantMind-Celery:  ... Environment: (empty)
QuantMind-CeleryBeat: ... Environment: (empty)
QuantMind-QMTData: ... Environment: (empty)
```

确认: Servy 没在 SCM Environment 字段注入 SKIP=1, 必须经 (a) Machine env 或 (b) reinstall with --env.

### Q7 — 修复路径选择 (X/Y/Z 对比)

**推荐 X — Machine setx**:

| 候选 | 操作 | 真金 | 数据 | 持久 | 撤回 | ETA |
|---|---|---|---|---|---|---|
| **X (推荐)** | `[Environment]::SetEnvironmentVariable("SKIP_NAMESPACE_ASSERT","1","Machine")` + Servy restart | 🟢 0 | 🟢 0 | 是 (注册表) | 1 命令 | **30 秒** |
| Y (--env) | export → uninstall → install --env | 🟢 0 | 🟢 0 | 是 (Servy db) | 重 install | 5 分钟 (需 user 批 diff) |
| Z (code) | startup_assertions 改用 settings.SKIP_NAMESPACE_ASSERT | 🟢 0 | 🟢 0 | 是 (代码) | revert PR | 30+ 分钟 (PR + reviewer) |

**X 最低侵入**:
- 1 命令, 30 秒
- 0 代码改 / 0 .env 改 / 0 Servy 配置改
- 撤回 1 命令 (`SetEnvironmentVariable("SKIP_NAMESPACE_ASSERT", $null, "Machine")`)

### Q8 — 修复路径风险评估

**X (Machine setx) 风险评估**:

| 维度 | 风险 |
|---|---|
| 真金 (LIVE_TRADING_DISABLED guard) | 🟢 0 — 设的是 SKIP_NAMESPACE_ASSERT, broker_qmt guard 默认 True 不动 |
| 数据 (DB / Redis 改) | 🟢 0 — 仅改注册表 env, 0 DB write |
| 启动断言 bypass | 🟡 P3 治理债 — 长期保留违反铁律 33 fail-loud, 应在批 2 修写路径漂移后撤回 |
| Machine env 污染 | 🟡 P3 治理债 — 全用户可见此 env, 但 SKIP_NAMESPACE_ASSERT 名字明确, 0 安全风险 |
| 撤回成本 | 🟢 1 命令 |

**0 真金 / 0 数据 / 0 代码 / 0 .env 改动**.

### Q9 — 0 真金风险确认

**✅ 4 项保留不动**:
- ✅ `LIVE_TRADING_DISABLED=true` (config.py:36 default) → broker_qmt place_order/cancel_order guard 仍拦
- ✅ `EXECUTION_MODE=paper` (.env:17) → 写读路径仍 paper namespace
- ✅ Beat schedule risk-daily-check + intraday-risk-check 仍 PAUSED (链路停止 PR)
- ✅ schtask DailyExecute / IntradayMonitor / DailySignal / DailyReconciliation / CancelStaleOrders 仍 Disabled
- ✅ ADMIN_TOKEN auth 仍生效 (D2.2 实测 len=43)

执行 X 仅 bypass 启动断言 (fail-secure 设计的 emergency override), 真金保护链路不变.

---

## 🚀 执行 X — Machine setx + Servy restart

### Step 1 — Machine env

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', '1', 'Machine')
```

输出: `OK: Machine SKIP_NAMESPACE_ASSERT=1 set` ✅

⚠️ **需 Admin elevation**: PowerShell 进程必须 elevated. 实测当前 PowerShell admin 即可执行.

### Step 2 — Verify Machine env

```powershell
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')
# Output: '1'
```

### Step 3 — Servy restart

```powershell
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'
# Output: Service restarted successfully.
```

Servy 重启 master 进程 → master 从 Machine env 重新加载 SKIP=1 → spawn child uvicorn workers → workers 继承 SKIP=1 → startup_assertions:151 检测 SKIP → bypass + warning log → lifespan 完成 → uvicorn bind port 8000.

### Step 4 — Wait 10s

`Start-Sleep -Seconds 10` 让 lifespan 完成 (实测 < 10s 即 ready).

### Step 5 — 4 curl + Servy status 全验证

| Verify | Expected | Actual | 状态 |
|---|---|---|---|
| 1. Port 8000 listen | 0.0.0.0:8000 LISTENING | OwningProcess=7552 | ✅ |
| 2. GET /health | 200 + execution_mode | `{"status":"ok","execution_mode":"paper"}` | ✅ |
| 3. POST /api/execution/cancel-all (no token) | 401 | 401 | ✅ |
| 4. POST /api/execution/cancel-all (correct token) | 200 或 503 (auth pass) | **503** "QMT未连接 (state=error)" — **auth gate 通过, 业务返** | ✅ |
| 5. Servy status | Running | Running PID 6152 | ✅ |

**全部 PASS** 🎉.

---

## ⚠️ 重大新发现 (本 D2.3)

### Finding K — Windows 服务 LocalSystem 不继承 User env (LL-XXX 候选)

**触发**: D2.2 推荐 user 执行 `setx SKIP_NAMESPACE_ASSERT 1` (默认 User scope), 但 Servy 服务跑 LocalSystem, **不继承 User env**.

**实测验证**:
- Win32_Service.StartName = "LocalSystem" (4/4 服务)
- User scope env = '1' ✅ 已设
- Machine scope env = `<NOT SET>` ❌ 真因
- LocalSystem 进程仅看 Machine env

**全局原则**: 设 Windows env 给服务时, 必先实测服务 StartName:
- **LocalSystem / NetworkService**: 必须 Machine-level setx 或 Servy `--env` reinstall
- **当前 user**: User-level setx 可用 (但要重启服务主进程让继承)
- **测试方法**: `[System.Environment]::GetEnvironmentVariable($name, $scope)` 三 scope 都查

**升级铁律候选** (X7 月度 audit): "Debug Windows service env 必先实测 StartName + 3 scope".

### Finding L — D2.2 推荐路径 prompt 一阶概括第 2 次错

D2.1 错: "加 SKIP 到 .env" (D2.2 实测纠错: Pydantic 不写 os.environ)
D2.2 错: "user setx" (D2.3 实测纠错: User scope, LocalSystem 不继承)

**LL-XXX 加固**: audit / prompt 一阶概括连续 2 次错, **D2 系列 prompt 30%+ 偏离真因实测验证**. 推荐路径必须基于实测 (StartName / scope / Pydantic 行为), 不凭直觉.

### Finding M — Servy CLI 7.6 无 update verb (P3 设计债)

Servy CLI 7.6 verbs: install/uninstall/start/stop/status/restart/export/import. **没有 update 或 set verb**. 改服务配置 (含 env) 必须 export → 编辑 → uninstall → install. 4 步骤, 服务下线 ~30s.

**修法建议** (留 Servy 升级评估): Servy 7.7+ 是否有 update verb? 或考虑回 NSSM (有 nssm set 命令).

---

## 🚨 风险等级总评 (修复后)

| 维度 | 修复前 | 修复后 |
|---|---|---|
| FastAPI 启动 | ❌ 启动断言 raise, port 8000 不监听 | ✅ Running PID 6152, port 8000 listening |
| GET /health | ❌ Connection refused | ✅ 200 + paper mode |
| POST cancel-all (no token) | N/A | ✅ 401 |
| POST cancel-all (correct token) | N/A | ✅ 503 "QMT未连接" (auth pass, QMT 未配预期) |
| 真金风险 (broker.place_order) | 🟢 0 | 🟢 0 (LIVE_TRADING_DISABLED guard 不动) |
| Beat schedule | risk Beat PAUSED ✅ | 不变 ✅ |
| Schtask | 5 关键 Disabled ✅ | 不变 ✅ |
| ADMIN_TOKEN | OK ✅ | OK ✅ |
| 启动断言 bypass | N/A | 🟡 P3 治理债 (批 2 后撤) |

**总评**: 🟢 **修复成功**, 0 真金风险变化, FastAPI 恢复 Running + 4 curl 全 PASS.

---

## 🔄 撤回方案 (批 2 完成后)

批 2 修写路径漂移 (pt_qmt_state.py 7 处 hardcoded 'live' 参数化) 后, .env 切 paper/live 不再触发命名空间漂移, 启动断言不再 raise. 此时撤 SKIP:

```powershell
# 撤 Machine env (admin 权限)
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')

# 验证
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')
# 预期: $null

# Servy restart
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'

# 验证 startup 不再 raise (因为批 2 后 pt_qmt_state 写路径已 settings.EXECUTION_MODE 化)
```

D2.2 报告中 user-level setx ('1') 也建议同时清理:
```powershell
setx SKIP_NAMESPACE_ASSERT ""
```

---

## 📋 批 2 scope 更新 (D2 + D2.1 + D2.2 + D2.3 综合)

| 优先级 | 子任务 | 来源 |
|---|---|---|
| **P0 ×2** | pt_qmt_state.py 7 处 hardcoded 'live' 参数化 / xfail strict 4 contract tests 转 PASS | D2 Finding B |
| **P1 ×2** | risk.py 3 + approval.py 3 = 6 endpoints 加 admin gate | D2.1 Finding E |
| **P2 ×4** | MiniQMTBroker.sell/.buy wrapper / scripts/intraday_monitor:141 删 hardcoded / cb_state paper L0 清理 / **_verify_admin_token 改 secrets.compare_digest** | D2.1 D + D2 A/C + D2.2 H |
| **P3 ×4** | 10 files POST/PUT/DELETE 加 auth / LoggingSellBroker → QMTSellBroker / **startup_assertions 用 settings.SKIP_NAMESPACE_ASSERT** (D2.2 G) / **Servy console UTF-8** (D2.2 J) | 治理债 |
| **批 2 完成后** | 撤 Machine setx + 撤 user setx ('1') | 本 D2.3 |

**ETA**: 批 2 ~1 周 + D2.2/D2.3 治理债半天 + setx 撤回 1 分钟.

---

## 📦 LL 候选沉淀

### LL-XXX (新, 强候选): Windows 服务 env 三 scope 必实测

(详见 Finding K)

**全局原则**: 设 Windows env 给服务时, 必先实测服务 StartName + 3 scope:
- LocalSystem / NetworkService → Machine-level setx 或 Servy `--env` reinstall
- 当前 user → User-level setx + 重启 service master
- 测试: `[Environment]::GetEnvironmentVariable($name, $scope)` 三 scope 都查

### LL-XXX (沿用 + 第 3 次加固): audit/prompt 一阶概括必须实测纠错

D2.1 + D2.2 + D2.3 三次连续实测纠错:
1. D2.1 prompt "加 SKIP 到 .env" → 实测 Pydantic 不写 os.environ ❌
2. D2.2 推 "user setx" → 实测 LocalSystem 不继承 User env ❌
3. D2.3 推 "Machine setx" → 实测 Admin elevation OK + LocalSystem 继承 Machine env ✅ (本次成立)

**全局原则加固**: 任何 ops 推荐路径必须基于**实测的 3 维**:
- 进程的 run-as account (StartName)
- env 的 scope (User/Machine/Process)
- 应用层的读取机制 (os.environ vs settings)

3 维任一不实测 → 30%+ 概率推荐错误.

### LL-XXX (新, 候选): Servy CLI 缺 update verb 是设计债

(详见 Finding M)

Servy 7.6 改服务 env 必须 export+uninstall+install. 不友好. 留 Servy 升级评估.

---

## 🚀 下一步建议

### (a) 立即可用

FastAPI 已恢复. 用户可以:
- 调 admin endpoint (有 ADMIN_TOKEN)
- 启动 PT 评估 paper-mode dry run (D2 推荐 C 路径继续)
- 跑 backtest / health / 对账等 read-only ops

### (b) 启批 2 (合并 D2 + D2.1 + D2.2 + D2.3 治理债)

按优先级 P0 → P1 → P2 → P3 分 PR 实施. ETA ~1 周.

### (c) 批 2 完成后撤 setx

```powershell
[Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')
setx SKIP_NAMESPACE_ASSERT ""  # User scope
servy-cli restart --name=QuantMind-FastAPI
```

### (d) 全方位审计 13 维 (D2/D2.1/D2.2/D2.3 是 4/13)

D2 (激活路径) + D2.1 (API auth) + D2.2 (启动 + 真活验证) + D2.3 (Servy env) 已覆盖 4 维. 13 维其他 9 维留批 2 后启.

---

## 📂 附产物清单

- [docs/audit/servy_env_injection_debug_2026_04_30.md](servy_env_injection_debug_2026_04_30.md) — 本文档 (主产物)
- [docs/audit/STATUS_REPORT_2026_04_30_D2_3.md](STATUS_REPORT_2026_04_30_D2_3.md) — D2.3 整体执行报告
- 0 commit / 0 push / 0 PR / 0 .env 改 / 0 应用代码改 — 仅 Machine env 注册表 + Servy restart

---

> **状态**: D2.3 阶段 ✅ **完整完成 + FastAPI 恢复** — 9 题诊断 + Root cause 实测 (LocalSystem 不继承 User env) + 修复路径 X 执行 + 4 curl 全 PASS + 3 finding (K/L/M).
> **Root Cause**: Servy 4 服务全 LocalSystem, setx User scope 不继承. 必须 Machine setx 或 Servy --env reinstall.
> **修复**: `[Environment]::SetEnvironmentVariable("SKIP_NAMESPACE_ASSERT","1","Machine")` + `servy-cli restart QuantMind-FastAPI` (30 秒, 0 真金风险).
> **当前状态**: FastAPI Running PID 6152, port 8000 listening, /health 200, admin auth 401/503 全 PASS.
> **批 2 完成后**: 撤 Machine + User setx, 启动断言由 settings.SKIP_NAMESPACE_ASSERT 替代 (Finding G + 本 LL).
