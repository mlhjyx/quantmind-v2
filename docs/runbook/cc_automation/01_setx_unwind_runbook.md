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

**永久修法** (批 2 P3): `backend/app/services/startup_assertions.py:151` 直读 `os.environ.get("SKIP_NAMESPACE_ASSERT")` → 改用 `settings.SKIP_NAMESPACE_ASSERT` (Pydantic 加载 `.env`, 不污染 system env). 详见 D2.2 Finding G.

**本 runbook 触发条件**: 批 2 P3 commit merged + FastAPI 重启验证 OK 后, 撤 Machine env 还干净.

---

## 2. 真金 0 风险确认 (前置, 不通过立即 STOP)

| 检查 | 命令 | 期望 |
|------|------|------|
| LIVE_TRADING_DISABLED 仍 active | `.venv/Scripts/python.exe -c "from app.config import settings; print(settings.LIVE_TRADING_DISABLED)"` | `True` |
| EXECUTION_MODE | `.venv/Scripts/python.exe -c "from app.config import settings; print(settings.EXECUTION_MODE)"` | `paper` 或 user 已确认 live cutover |
| 批 2 P3 commit 已 merged | `git log --oneline main \| grep -i "startup_assertions.*settings"` | 至少 1 commit |
| settings.SKIP_NAMESPACE_ASSERT 真活 | `.venv/Scripts/python.exe -c "from app.config import settings; print(hasattr(settings, 'SKIP_NAMESPACE_ASSERT'))"` | `True` |

**任一不满足** → 立即 STOP 反问 user, 不执行撤 setx.

---

## 3. 前置检查清单 (state snapshot)

```bash
# 1. 当前 Machine env 实测
powershell.exe -Command "[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')"
# 期望: '1' (D2.3 留下的)

# 2. 当前 User env 实测 (D2.2 user 操作过)
powershell.exe -Command "[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'User')"
# 期望: '1' 或 '' (取决于 user D2.2 是否真打了 setx)

# 3. FastAPI 当前状态 (撤 setx 前必须 Running, 防对照失明)
& 'D:\tools\Servy\servy-cli.exe' status --name='QuantMind-FastAPI'
# 期望: Running

# 4. /health 当前响应
curl -s http://localhost:8000/health
# 期望: {"status":"ok",...}
```

**全 4 通过** → 进入执行. **任一异常** → STOP, 报 user 决议.

---

## 4. 执行步骤

### Step 1: 撤 Machine env (D2.3 留)

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')
```

验证:
```powershell
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'Machine')
# 期望: 空白 (无输出 / NULL)
```

### Step 2: 撤 User env (D2.2 user 留)

```powershell
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'User')
```

验证:
```powershell
[System.Environment]::GetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', 'User')
# 期望: 空白
```

### Step 3: Servy restart (load 新 env state — 现 settings.SKIP 生效)

```powershell
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'
```

### Step 4: 验证 FastAPI 起来 (settings 生效, 不依赖 env)

```bash
# 等 FastAPI 启动 ~5s
sleep 5

# 健康检查
curl -s http://localhost:8000/health
# 期望: {"status":"ok","execution_mode":"paper"} (或 live)

# Servy status
& 'D:\tools\Servy\servy-cli.exe' status --name='QuantMind-FastAPI'
# 期望: Running, PID > 0
```

### Step 5: 验证 admin gate auth 仍生效 (PR #152 + #155 等)

```bash
# 401 (无 token)
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/execution/cancel-all
# 期望: 401

# 503 (有 token, QMT 未连)
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/execution/cancel-all -H "X-Admin-Token: $ADMIN_TOKEN"
# 期望: 503 (QMT 未连接) 或 200 (如果 QMT 真连)
```

---

## 5. 验证清单 (硬门, 任一 fail → 失败回滚)

| 检查 | 期望 | 状态 |
|------|------|------|
| Machine env SKIP=NULL | empty | ☐ |
| User env SKIP=NULL | empty | ☐ |
| FastAPI Running | PID > 0 | ☐ |
| /health 200 | `{"status":"ok"}` | ☐ |
| admin gate 401 (no token) | 401 | ☐ |
| 现有 cb_state / approval queue 行数不变 (DB 不污染) | DB 行数 == before | ☐ |

**全 ✅** → 撤 setx 完成, 写 STATUS_REPORT.
**任一 ❌** → 进 §6 失败回滚.

---

## 6. 失败回滚

### 场景 A: Step 4 FastAPI 不起来 (settings.SKIP 没生效或别的原因)

```powershell
# 立即恢复 Machine env (D2.3 配置)
[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', '1', 'Machine')
& 'D:\tools\Servy\servy-cli.exe' restart --name='QuantMind-FastAPI'

# 验证
curl -s http://localhost:8000/health
# 期望: 恢复 {"status":"ok"}
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

1. 触发条件 (批 2 P3 commit hash + merged 时间)
2. §3 前置检查实测结果 (4 项)
3. §4 执行步骤实测命令 + stdout
4. §5 验证清单 (6 项 ✅/❌)
5. 失败回滚是否触发 (是 / 否) + 触发场景 + 还原状态
6. 后续清单 (无 — 撤 setx 是终点)

---

## 8. 关联

- **D2.2** ([STATUS_REPORT_2026_04_29_D2_2.md](../../audit/STATUS_REPORT_2026_04_29_D2_2.md)): FastAPI 启动失败诊断 + Finding G (startup_assertions 改用 settings)
- **D2.3** ([STATUS_REPORT_2026_04_30_D2_3.md](../../audit/STATUS_REPORT_2026_04_30_D2_3.md)): Servy LocalSystem env scope 实测 + Machine setx 修复 + Finding K
- **批 2 P3 commit**: 待批 2 完成时填写 commit hash
- **铁律 35** (CLAUDE.md): secrets 环境变量唯一 — 撤 setx 后 SKIP 不再污染 Machine env, 走 .env → Pydantic settings 单一来源
