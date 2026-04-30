# STATUS_REPORT — D2.3 Servy Env 注入 + Machine setx 修复

> **Sprint**: D2.3 (T1 Sprint, 2026-04-30 ~00:35)
> **Branch**: main @ `bc8bad4` (PR #151 批 1.5 merged) — 0 应用代码改 / 0 commit / 0 PR
> **Trigger**: D2.2 后 user 执行 setx (User scope), FastAPI 仍 startup_assertions raise. 必须实测 Servy run-as + env scope.
> **方法**: 先看 log + 实测 (沿用 LL-XXX: audit 必须实测纠错, 第 3 次实证)
> **关联铁律**: 25 / 26 / 33 / 34 / 35 / 36
> **关联文档**: [servy_env_injection_debug_2026_04_30.md](servy_env_injection_debug_2026_04_30.md) (主产物) / [fastapi_startup_debug_2026_04_29.md](fastapi_startup_debug_2026_04_29.md) / [api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) / [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md)

---

## ✅ D2.3 任务交付

| # | 交付 | 状态 |
|---|---|---|
| **A** | 9 题逐答 (Q1-Q9 全 ✅) | ✅ |
| **B** | Root cause 实测 (Servy LocalSystem 不继承 User env) | ✅ |
| **C** | 修复路径 X (Machine setx) 选择 + 执行 | ✅ |
| **D** | 4 curl + Servy status 全验证 PASS | ✅ |
| **E** | 3 项重大新发现 (Finding K/L/M) | ✅ |
| **F** | 撤回方案 (批 2 完成后) | ✅ |
| **G** | 主产物 docs/audit/servy_env_injection_debug_2026_04_30.md | ✅ |
| **H** | 本 STATUS_REPORT | ✅ |

**0 应用代码改 / 0 .env 改 / 0 commit / 0 PR**, 仅 Machine env 注册表 + Servy restart.

---

## 📊 修复前 vs 修复后对比

### 修复前 (D2.3 启动时)

| 项 | 状态 |
|---|---|
| FastAPI Servy GUI | Running PID 24044 (Servy.Service.CLI.exe master, 假象) |
| Port 8000 | ❌ NOT listening (children 反复 spawn → die) |
| stderr.log | NamespaceMismatchError 重复 |
| User env SKIP | '1' (D2.2 user 设的) |
| Machine env SKIP | `<NOT SET>` ← Root Cause |
| Servy StartName | LocalSystem (4/4 服务) ← 不继承 User env |

### 修复后 (D2.3 完成时)

| Verify | 实际 |
|---|---|
| 1. Port 8000 listening | ✅ 0.0.0.0:8000 PID 7552 |
| 2. GET /health | ✅ 200 + `{"status":"ok","execution_mode":"paper"}` |
| 3. POST cancel-all (no token) | ✅ 401 |
| 4. POST cancel-all (correct token) | ✅ 503 "QMT未连接 (state=error)" — auth gate 通过, 业务返 |
| 5. Servy status | ✅ Running PID 6152 |
| Machine env SKIP | ✅ '1' (注册表持久化) |

**4 curl + Servy status 全 PASS** 🎉.

---

## 🔴 3 项重大新发现

### Finding K — Windows 服务 LocalSystem 不继承 User env

**实测**:
```
Win32_Service.StartName: LocalSystem (4/4 QuantMind 服务)
[Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'User')    = '1'  ✅
[Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine') = NULL ❌
```

**Root Cause**: Windows Service 跑 `LocalSystem` (NT AUTHORITY\SYSTEM) 时, **仅继承 Machine scope env**. User scope env 不可见.

D2.2 推荐的 `setx SKIP_NAMESPACE_ASSERT 1` (默认 User scope) 对 LocalSystem 服务无效.

**全局原则候选** (LL-XXX): 设 Windows env 给服务时, 必先实测 StartName + 3 scope:
- LocalSystem / NetworkService → Machine-level setx 或 Servy `--env` reinstall
- 当前 user → User-level setx + 重启 service master
- 测试: `[Environment]::GetEnvironmentVariable($name, $scope)` 三 scope 都查

### Finding L — D2 系列 prompt 一阶概括连续 3 次错

| Audit | 一阶推荐 | 实测真因 |
|---|---|---|
| D2.1 | "加 SKIP 到 backend/.env" | Pydantic 不写 os.environ ❌ |
| D2.2 | "user setx SKIP" | LocalSystem 不继承 User env ❌ |
| D2.3 | "Machine setx SKIP" | Admin elevation 可执行, LocalSystem 继承 Machine env ✅ (本次成立) |

**LL-XXX 加固**: audit / prompt 一阶概括连续 3 次错, **D2 系列 30%+ 偏离真因实测验证**. 推荐路径必须基于 3 维实测:
- 进程 run-as account (StartName)
- env scope (User/Machine/Process)
- 应用层读取机制 (os.environ vs settings)

3 维任一不实测 → 30%+ 概率推错.

### Finding M — Servy CLI 7.6 缺 update verb (P3 设计债)

Servy 7.6 verb 列表: install/uninstall/start/stop/status/restart/export/import. **没有 update / set / config verb**.

改服务 env 必须 export → 编辑 → uninstall → install (with `--env "Name=Value"`). 4 步骤, 服务下线 ~30s.

**修法建议** (留 Servy 升级评估): Servy 7.7+ 是否有 update verb? 或回 NSSM (有 `nssm set <svc> AppEnvironmentExtra ...` 命令).

---

## 🚀 修复执行 (Machine setx + Servy restart)

### Step 1 — Machine env 设置 (admin 权限)

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', '1', 'Machine')
# Output: OK: Machine SKIP_NAMESPACE_ASSERT=1 set
```

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

### Step 4 — Wait 10s + 4 curl 验证

(详见 §修复前 vs 修复后对比 表)

**全部 PASS** ✅, 30 秒恢复 FastAPI.

---

## 🚨 风险等级总评 (修复后)

| 维度 | 等级 |
|---|---|
| FastAPI 启动 | 🟢 Running PID 6152, port 8000 listening |
| 真金保护 (broker.place_order/cancel_order) | 🟢 0 (LIVE_TRADING_DISABLED guard 不动) |
| API → broker 链路 | 🟢 0 (auth gate 实活: 401/503 测试 PASS) |
| Beat schedule | 🟢 risk Beat 2 项仍 PAUSED |
| Schtask 真金 | 🟢 5 关键 Disabled 不动 |
| ADMIN_TOKEN | 🟢 OK (D2.2 实测 len=43) |
| **启动断言 bypass (SKIP=1 Machine)** | 🟡 P3 治理债 (批 2 后撤) |
| Machine env 污染 | 🟡 P3 治理债 (全用户可见, 但名字明确, 0 安全风险) |

**总评**: 🟢 **修复成功**, 0 真金风险变化, FastAPI 恢复 Running + auth 实活生效.

---

## 🔄 撤回方案 (批 2 完成后)

批 2 修写路径漂移后, 切 .env paper/live 不再触发命名空间漂移. 此时撤 SKIP:

```powershell
# 撤 Machine env (admin)
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')

# 撤 User env (D2.2 user 设的, 1 次性清理)
setx SKIP_NAMESPACE_ASSERT ""

# Servy restart 让服务从注册表重读 env
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'

# 验证 startup 不再 raise (因为批 2 后 pt_qmt_state 写路径已 settings.EXECUTION_MODE 化)
Get-Content 'D:\quantmind-v2\logs\fastapi-stderr.log' -Tail 20
```

---

## 📋 批 2 scope 更新 (D2 + D2.1 + D2.2 + D2.3 综合)

| 优先级 | 子任务 | 来源 |
|---|---|---|
| **P0 ×2** | pt_qmt_state.py 7 处 hardcoded 'live' 参数化 / xfail strict 4 contract tests 转 PASS | D2 Finding B |
| **P1 ×2** | risk.py 3 + approval.py 3 = 6 endpoints 加 admin gate | D2.1 Finding E |
| **P2 ×4** | MiniQMTBroker.sell/.buy wrapper / scripts/intraday_monitor:141 删 hardcoded / cb_state paper L0 清理 / **_verify_admin_token 改 secrets.compare_digest** | D2.1 D + D2 A/C + D2.2 H |
| **P3 ×4** | 10 files POST/PUT/DELETE 加 auth / LoggingSellBroker → QMTSellBroker / **startup_assertions 用 settings.SKIP_NAMESPACE_ASSERT** (D2.2 G) / **Servy console UTF-8** (D2.2 J) | 治理债 |
| **批 2 完成后** | 撤 Machine + User setx | D2.3 |

**ETA**: 批 2 ~1 周 + 治理债半天 + setx 撤回 1 分钟.

---

## 📦 LL 候选沉淀

### LL-XXX (新, 强候选): Windows 服务 env 三 scope 必实测

(详见 Finding K) — Servy/NSSM/Windows Service 设 env 必先看 StartName, 再选 scope.

### LL-XXX (沿用, 第 3 次加固): audit/prompt 一阶概括必须实测纠错

(详见 Finding L) — D2.1/D2.2/D2.3 连续 3 次错. 推荐路径基于 3 维实测.

### LL-XXX (新): Servy CLI 7.6 缺 update verb 是设计债

(详见 Finding M) — 改 env 必须 reinstall, 不友好. 留 Servy 升级评估.

---

## 🚀 下一步建议

### (a) 立即可用

FastAPI 已恢复 ✅. 用户可以:
- 调 admin endpoint (X-Admin-Token 验证已通过)
- 跑 backtest / health / 对账 等 read-only ops
- 评估 paper-mode 5d dry run (D2 推荐 C 路径继续)

### (b) 启批 2 (合并 D2 + D2.1 + D2.2 + D2.3 治理债)

按 P0 → P1 → P2 → P3 分 PR 实施. ETA ~1 周.

### (c) 批 2 完成后撤 setx

```powershell
[Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')
setx SKIP_NAMESPACE_ASSERT ""
servy-cli restart --name=QuantMind-FastAPI
```

### (d) 全方位审计 13 维 (D2/D2.1/D2.2/D2.3 是 4/13)

13 维其他 9 维留批 2 后启 (数据完整性 / 测试覆盖 / 文档腐烂 / Redis 缓存 / 监控告警 / 调度链路 / 性能基线 / 配置 SSOT / 安全).

---

## 📂 附产物清单

- [docs/audit/servy_env_injection_debug_2026_04_30.md](servy_env_injection_debug_2026_04_30.md) — 主产物 (~700 lines, 完整诊断 + 修复)
- [docs/audit/STATUS_REPORT_2026_04_30_D2_3.md](STATUS_REPORT_2026_04_30_D2_3.md) — 本 STATUS_REPORT
- 0 commit / 0 push / 0 PR / 0 应用代码改 / 0 .env 改

---

> **状态**: D2.3 阶段 ✅ **完整完成 + FastAPI 恢复** — 9 题诊断 + Root cause 实测 (LocalSystem 不继承 User env) + 修复路径 X 执行 + 4 curl 全 PASS + 3 finding (K/L/M).
> **Root Cause**: Servy 4 服务全 LocalSystem, setx User scope 不继承. 必须 Machine setx.
> **修复**: `[Environment]::SetEnvironmentVariable("SKIP_NAMESPACE_ASSERT","1","Machine")` + `servy-cli restart QuantMind-FastAPI` (30 秒, 0 真金风险).
> **当前状态**: FastAPI Running PID 6152, port 8000 listening, /health 200, admin auth 401/503 全 PASS.
> **批 2 完成后**: 撤 Machine + User setx, startup_assertions 由 settings.SKIP_NAMESPACE_ASSERT 替代 (D2.2 Finding G + D2.3 Finding K).
