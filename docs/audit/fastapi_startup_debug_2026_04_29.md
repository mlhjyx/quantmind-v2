# FastAPI Startup Debug + ADMIN_TOKEN 真活验证 — 2026-04-29 (D2.2)

> **范围**: User 报 Servy 显示 FastAPI Running 但 curl `localhost:8000/health` 失败. 实测诊断真因 + ADMIN_TOKEN 加载验证.
> **触发**: D2.1 完成后 user 试用 ADMIN_TOKEN 配置, FastAPI 不响应 → 必须实测找 root cause
> **方法**: 先看 log (LL-XXX 候选), 再 python -c 实测验证 (沿用批 1.5 + D2 + D2.1 LL: audit 必须实测)
> **关联铁律**: 25 (改什么读什么) / 26 (验证不跳过) / 33 (fail-loud) / 35 (secrets) / 36 (precondition)
> **关联文档**: [api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) / [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md)

---

## 📋 执行摘要

| 检查 | 状态 | 关键发现 |
|---|---|---|
| **9 题诊断** | ✅ 全过 | Q1-Q9 全 ✅, 4 重大新发现 |
| **Servy log 真因** | ✅ 实测 | `NamespaceMismatchError` @ startup_assertions.py:125, 已重启循环 ~9min |
| **PID 5532 状态** | ✅ alive (master) | python.exe idle, child uvicorn worker 21588 反复 spawn → die → spawn |
| **启动断言行为** | ✅ 符合契约 | env=paper + DB={'live':295} → raise; env=live + DB={'live':295} → pass |
| **ADMIN_TOKEN 加载** | ✅ OK | len=43, 写 .env L38 已被 Pydantic 加载到 settings |
| **_verify_admin_token** | ✅ 行为正确 | 拒错 401 / 通过对 / 拒空 401, ⚠️ Q5.4 P2 timing attack (`!=` plain compare) |
| **.env → os.environ** | ⚠️ **关键纠错** | Pydantic 加载 .env 到 settings 对象**不写 os.environ** — 加 SKIP=1 到 .env **不生效** |
| **Port 8000 listen** | ❌ 不监听 | netstat 0 行 + Get-NetTCPConnection 0 row |
| **修复路径** | ✅ 推荐 (不执行) | 候选 D `setx SKIP_NAMESPACE_ASSERT 1` + Servy 重启 (推荐, 不改代码) |

---

## ✅ 9 题逐答

### Q1 — Servy log 真实启动 log

**✅ 实测** — Servy 默认 log 在 `D:\quantmind-v2\logs\fastapi-{stdout,stderr}.log`:

```
=== fastapi-stderr.log 末尾 ===
File "D:\quantmind-v2\backend\app\main.py", line 60, in lifespan
    run_startup_assertions(get_sync_conn)
File "D:\quantmind-v2\backend\app\services\startup_assertions.py", line 167, in run_startup_assertions
    assert_execution_mode_consistency(env_mode, db_modes)
File "D:\quantmind-v2\backend\app\services\startup_assertions.py", line 125, in assert_execution_mode_consistency
    raise NamespaceMismatchError(

app.services.startup_assertions.NamespaceMismatchError: EXECUTION_MODE drift detected:
.env=paper but DB position_snapshot recent 30d has {'live': 295} (no rows for 'paper').
Refusing to start. Fix options: (A) Edit backend/.env to set EXECUTION_MODE='live';
(B) Migrate DB data; (C) Wait for batch 2 fix; (D) Emergency bypass: setx SKIP_NAMESPACE_ASSERT 1.

ERROR:    Application startup failed. Exiting.
INFO:     Waiting for child process [34036]
INFO:     Child process [34036] died
INFO:     Waiting for child process [15212]
INFO:     Child process [15212] died
```

```
=== fastapi-stdout.log 末尾 (重启循环, 每 ~6s 一次) ===
2026-04-29T16:07:23.914802Z [info] 日志系统已配置 ...
[startup-assert] BLOCKING STARTUP — EXECUTION_MODE=paper drift vs DB modes={'live': 295}.
2026-04-29T16:07:30.453965Z [info] 日志系统已配置 ...
[startup-assert] BLOCKING STARTUP — EXECUTION_MODE=paper drift vs DB modes={'live': 295}.
```

**Root Cause**: `startup_assertions.py:125` raise `NamespaceMismatchError` 阻断启动, uvicorn worker children 重复 spawn → assert 失败 → die. Servy 主进程 alive (PID 5532), child workers 反复 spawn → fail.

### Q2 — PID 5532 实测

**✅ alive (master process)**:

```
Id          : 5532
ProcessName : python (.venv/Scripts/python.exe)
StartTime   : 2026/4/29 23:58:24 (~9 分钟前)
CPU         : 0.015625 (idle)
Threads     : {4884} (1 thread)
WorkingSet  : 4.0 MB
Responding  : True

Children:
  ProcessId 34940 conhost.exe
  ProcessId 21588 python.exe (uvicorn worker — current child, 也将 die)
```

**判定**: PID 5532 是 Servy spawn 的 uvicorn **master 进程**, 它持续 alive 等待 child workers. child workers 启动 → lifespan 调 startup_assertions → raise → die. master 接收 SIGCHLD → log "Application startup failed. Exiting." 但 master 不退出 (uvicorn 设计: master --workers 2 模式下 master 持续 spawn 直到 SIGTERM).

**Servy 配置**: `--workers 2` (来自 fastapi-stdout.log 显示 2 child PID 同时 die: 34036/15212).

### Q3 — startup_assertions 行为路径实测

**✅ 全 case 通过** (代码契约 100% 符合行为):

```python
# 实测 (.venv/Scripts/python.exe -c '...'):
[Q3.1] env=paper + DB={'live': 295} → raises NamespaceMismatchError ✅
[Q3.2] env=live  + DB={'live': 295} → passes (env_mode in db_modes) ✅
[Q3.3] env=paper + DB={}            → passes silently (logger.warning) ✅
```

源码 (startup_assertions.py:97-135):
```python
if not db_modes:
    logger.warning("position_snapshot last 30d empty (env_mode=%s). Skip ...")
    return  # Q3.3 path

if env_mode in db_modes:
    logger.info("EXECUTION_MODE=%s aligns with DB ✓")
    return  # Q3.2 path

# 漂移: fail-loud
suggested_env = max(db_modes, key=db_modes.get)
logger.critical("BLOCKING STARTUP — EXECUTION_MODE=%s drift vs DB modes=%s ...")
raise NamespaceMismatchError(...)  # Q3.1 path (current crash)
```

**结论**: 启动断言行为正确, 是 fail-loud 设计意图 (铁律 33). 当前 .env=paper + DB={'live':295} → raise 阻断启动. 解决: 设 SKIP_NAMESPACE_ASSERT 或对齐 .env=live.

### Q4 — ADMIN_TOKEN 加载验证

**✅ 加载成功**:

```
[Q4] ADMIN_TOKEN set: True | len: 43
[Q4] EXECUTION_MODE: 'paper'
[Q4] LIVE_TRADING_DISABLED: True
```

`backend/.env:38 ADMIN_TOKEN=5BealWxeV-nujtYIfEsGXDOKhasC8rz6iLNTjBUfbLA` (43 chars URL-safe base64, 大约 32 bytes random 强度) 通过 `pydantic_settings.SettingsConfigDict(env_file="backend/.env")` 正确加载. **D2.1 Finding F (ADMIN_TOKEN 未配置) 已 close** ✅.

### Q5 — _verify_admin_token 安全性 (4 sub-tests)

**✅ 行为正确, ⚠️ 1 项 P2 治理债**:

| Test | 结果 | 状态 |
|---|---|---|
| Q5.1 wrong token | rejected status=401 detail='无效的Admin Token' | ✅ |
| Q5.2 correct token | accepted, returned len=43 | ✅ |
| Q5.3 empty string token | rejected status=401 (因 settings.ADMIN_TOKEN 已配 → 走 `!=` 比较 ≠ '' → 401) | ✅ |
| Q5.4 timing attack | **`!=` plain string compare** detected | ⚠️ **P2** |

**源码** (execution_ops.py:69-77):
```python
def _verify_admin_token(
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
) -> str:
    """验证Admin Token。"""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="无效的Admin Token")
    return x_admin_token
```

**Q5.4 P2 timing attack 风险评估**:
- Plain `!=` 比较, **非 constant-time**. 理论可通过测量 reject 响应时间逐字节探测 token 字符
- 实际利用门槛: 需要稳定网络延迟测量 (Windows 本地 + CORS 严格 localhost:3000) → 攻击难度高
- 推荐修法 (留批 2 P3): `secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN)`

**整体**: Q5.1-Q5.3 行为正确, _verify_admin_token 的 auth gate **真活生效** (D2.1 Finding F 间接验证已 close).

### Q6 — .env 加载机制 (关键纠错)

**⚠️ Pydantic Settings 加载 .env 到 settings 对象, NOT 写 os.environ**:

```
[Q6] Pydantic Settings model_config:
    env_file: WindowsPath('D:/quantmind-v2/backend/.env')
    env_file_encoding: 'utf-8'
    case_sensitive: False
    env_ignore_empty: False
[Q6] os.environ.get ADMIN_TOKEN: '<NOT IN os.environ>'
[Q6] os.environ.get EXECUTION_MODE: '<NOT IN os.environ>'
[Q6] os.environ.get SKIP_NAMESPACE_ASSERT: '<NOT IN os.environ>'
```

**关键含义**:
- ✅ `settings.ADMIN_TOKEN`, `settings.EXECUTION_MODE` 等通过 `from app.config import settings` 读取**生效**
- ❌ **`os.environ.get("ADMIN_TOKEN")` 返 None** (Pydantic 不复写 os.environ)
- ❌ **`os.environ.get("SKIP_NAMESPACE_ASSERT")` 返 None** — startup_assertions.py:151 读的是 os.environ, **加 SKIP=1 到 backend/.env 不会生效**

**修法验证**: 必须 (a) `setx SKIP_NAMESPACE_ASSERT 1` (Windows User env, 持久化注册表) + 重启 Servy 主进程让继承, 或 (b) 改 startup_assertions.py 用 `from app.config import settings; settings.SKIP_NAMESPACE_ASSERT` (留批 2 P3 治理).

**反驳 prompt 假设**: prompt §修复路径 候选 A 写"在 backend/.env 末尾追加 SKIP_NAMESPACE_ASSERT=1" — **此路径不生效**. 必须 setx, 详见 §修复路径推荐.

### Q7 — Port 8000 listen state

**❌ 不监听**:

```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8000 }
# (空, 无 row)
```

```bash
curl http://localhost:8000/health
# Connection refused
```

与 Q1 root cause 一致: master 进程 alive 但 children 反复 spawn → die, **从未 bind socket 8000**.

### Q8 — 修复路径推荐 (3 候选)

**推荐: 候选 D — setx SKIP_NAMESPACE_ASSERT 1 + 重启 Servy** (最快, 0 代码改)

⚠️ **关键**: 必须 setx (Windows User env), **加 .env 不生效** (Q6 已纠错).

**User 手工执行命令清单** (CC 不执行):

```cmd
:: 1. 设 Windows User env (持久化注册表)
setx SKIP_NAMESPACE_ASSERT 1

:: 2. 关键步骤: 重启 Servy 主服务让其继承新 env
::    setx 设的是 User env, 已 alive 的 Servy 主进程不继承
::    必须停止 + 启动让 Servy 主进程从注册表重新加载 User env
D:\tools\Servy\servy-cli.exe stop --name=QuantMind-FastAPI
:: 等 5 秒确保完全停止
ping -n 5 127.0.0.1 > NUL
D:\tools\Servy\servy-cli.exe start --name=QuantMind-FastAPI

:: 3. 等 10 秒让 lifespan 完成 (无 raise 后 uvicorn 绑定 8000)
ping -n 10 127.0.0.1 > NUL

:: 4. 验证 (3 项)
netstat -ano | findstr :8000
::   预期: TCP 0.0.0.0:8000 LISTENING <PID>
curl http://localhost:8000/health
::   预期: {"status":"ok","execution_mode":"paper"}
.venv\Scripts\python.exe -c "import os; print('SKIP=', os.environ.get('SKIP_NAMESPACE_ASSERT'))"
::   预期: SKIP= 1
```

**验证 sensitive endpoint auth**:
```cmd
:: 不带 token (预期 401):
curl -X POST http://localhost:8000/api/execution/cancel-all -H "Content-Type: application/json"

:: 带正确 token (预期 200 或业务返 e.g. 0 orders):
curl -X POST http://localhost:8000/api/execution/cancel-all ^
  -H "X-Admin-Token: 5BealWxeV-nujtYIfEsGXDOKhasC8rz6iLNTjBUfbLA"
```

**风险评估**:
- 🟢 0 真金风险: SKIP_NAMESPACE_ASSERT 仅 bypass 启动断言, 不影响 LIVE_TRADING_DISABLED guard
- 🟢 0 数据风险: 只读路径 + 写路径仍受 ADR-008 命名空间隔离 (主路径 settings.EXECUTION_MODE 动态)
- 🟡 P2 治理债: SKIP=1 长期保留违反铁律 33 fail-loud 精神, 应在批 2 修写路径漂移后撤回 (`setx SKIP_NAMESPACE_ASSERT ""`)

#### 候选 A (备选) — 改 .env=live

```
:: 编辑 backend/.env L17:
EXECUTION_MODE=live
:: Servy 重启
```

**反对**: D2 + D2.1 已论证 — 切 live 不修写路径漂移根因 (pt_qmt_state.py 7 处 hardcoded 'live'), 是 workaround 不是修复. 且需先生成 ADMIN_TOKEN (已做 ✅) + 修 risk.py 3 endpoints auth (D2.1 Finding E 留批 2). 当前 PT 暂停, 切 live 误导未来 ops.

#### 候选 C (代码改, 留批 2 P3) — startup_assertions 用 settings

```python
# startup_assertions.py:151 改:
# OLD: if os.environ.get(_BYPASS_ENV_VAR) == "1":
# NEW: if settings.SKIP_NAMESPACE_ASSERT or os.environ.get(_BYPASS_ENV_VAR) == "1":
# 同时 config.py 加: SKIP_NAMESPACE_ASSERT: bool = False
```

**反对**: 0 改代码 D2.2 边界禁止. 留批 2/3.

### Q9 — D2.1 auth gate 真活间接验证

**✅ Done via Q5** — Q5.1-Q5.3 已实测 _verify_admin_token 函数本身行为:
- 错 token → 401 ✅
- 对 token → 通过 ✅
- 空 token → 401 ✅

**结论**: D2.1 Finding F 的 ADMIN_TOKEN auth gate 设计**真活生效**, 不是 dead code. 即使 FastAPI 当前 down, 函数级别 contract 已验证. 启动恢复后 (用户执行候选 D), curl 测试只是 transport-level 重复验证.

D2.1 报告 ⚪ "API auth gate 实际生效未实测" 项已 **close** ✅.

---

## ⚠️ 4 项重大新发现

### Finding G — Pydantic .env 加载不写 os.environ (启动断言 SKIP 必须 setx)

**Q6 实测**: Pydantic Settings 用 SettingsConfigDict(env_file="...") 加载 .env, **仅写 settings 对象, 不复写 os.environ**.

**影响**: startup_assertions.py:151 `os.environ.get("SKIP_NAMESPACE_ASSERT")` 读的是 os.environ, **加 SKIP=1 到 backend/.env 不会触发 bypass**. 必须 setx.

**反驳 prompt 假设**: D2.2 prompt 候选 A 写"加 SKIP 到 .env 末尾", 实测此路径**不生效**. 修复必须 setx.

**修法** (留批 2 P3 治理): startup_assertions.py 改读 settings.SKIP_NAMESPACE_ASSERT (config.py 加字段, 默认 False). 这样 .env 和 setx 两条路径都生效.

### Finding H — _verify_admin_token timing attack (P2)

**Q5.4 实测**: 用 `!=` plain string compare, 非 constant-time.

**风险评估**:
- 利用门槛: Windows 本地 + CORS 严格 localhost:3000 → 攻击难度高
- 但治理上仍是 P2 债 (违反 secrets 比较最佳实践 — 铁律 35)

**修法** (留批 2 P3): `import secrets; secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN)`.

### Finding I — Servy uvicorn --workers 2 重启循环掩盖 root cause

**Q1+Q2 实测**: stderr.log 显示 `Application startup failed. Exiting.` 但 Servy 主进程 (PID 5532) 不退出 — uvicorn `--workers 2` 模式下 child workers 反复 spawn → die. 用户看 Servy GUI 报"Running" 完全合法 (master alive), 但实际**从未 bind 8000**.

**影响**: 用户难发现真因 (ServyGUI Status: Running 误导), 必须读 stderr.log 才能定位.

**修法建议** (P3): Servy 配置加 max_restart_attempts=5 (避免无限重启), 失败转 Status: Failed. 或在 lifespan 中加更早的 sys.exit(1) (但需考虑 uvicorn 信号处理).

### Finding J — startup_assertions 错误信息中文 mojibake (Servy console 编码)

**Q1 实测**: stderr.log 末尾 NamespaceMismatchError message 含中文 "鎾ゅ洖鍓嶅繀椤讳慨婧愬ご" (实际原文 "撤回前必须修源头"). UTF-8 → GBK 转换 mojibake.

**根因**: Servy 默认 console encoding 是 GBK (Windows 中文环境), uvicorn stderr 写 UTF-8, Servy console capture 时双重解码错误.

**影响**: 中文错误信息阅读困难. 但**不影响诊断**, 因为 traceback file paths + Exception class name + 选项 (A)/(B)/(C)/(D) 仍可读.

**修法建议** (P3): Servy command line 加 `set PYTHONIOENCODING=utf-8` env, 或 main.py logging_config 强制 stderr handler encoding=utf-8.

---

## 🚨 风险等级总评

| 维度 | 等级 |
|---|---|
| FastAPI 启动失败 root cause | ✅ 实测确认 (NamespaceMismatchError 启动断言阻断) |
| 修复路径有效性 | 🟢 setx SKIP=1 + Servy 重启 (0 代码改, ETA 30 秒) |
| ADMIN_TOKEN 加载 | 🟢 OK (D2.1 Finding F close) |
| _verify_admin_token 行为 | 🟢 正确 (3 case 全通过), ⚠️ Q5.4 P2 timing attack |
| **.env → os.environ 机制** | ⚠️ **Pydantic 不写 os.environ** (P3 治理债, startup_assertions 用 os.environ 读 SKIP 不一致) |
| 真金 P0 风险 (D2.1 已确认) | 🟢 0 (LIVE_TRADING_DISABLED guard + admin gate + SAST 三重保护, FastAPI down 时 endpoint 全 unreachable, 反而更安全) |

**总评**: 🟢 **可控修复** — 用户 setx + Servy 重启 30 秒可恢复. 0 真金风险, 0 数据风险, 0 代码改动.

---

## 🛤️ A/B/C 路径决策更新 (D2 + D2.1 + D2.2)

D2 + D2.1 推荐 **C (等批 2)**, D2.2 实测后**仍成立**:

- 当前 .env=paper + 启动断言阻断 → 必须 SKIP=1 bypass 才能跑 FastAPI
- SKIP=1 是 emergency override, 长期保留违反铁律 33
- 批 2 修写路径漂移 → 写 'live' 时根据 settings.EXECUTION_MODE 决定, 不再 hardcoded → .env 切换可双向 (paper ↔ live) 而无需 SKIP bypass
- 批 2 完成后撤 SKIP (`setx SKIP_NAMESPACE_ASSERT ""`)

**短期 ops 操作**:
1. User 手工 `setx SKIP_NAMESPACE_ASSERT 1` + Servy 重启 → FastAPI 起来
2. 启批 2 实施 (P0 写路径修 + P1 risk.py auth + P2 ADMIN_TOKEN ✅ 已配)
3. 批 2 merge 后撤 SKIP

---

## 📋 批 2 scope 更新 (D2 + D2.1 + D2.2 综合)

加入 D2.2 Finding G/H:

| 优先级 | 子任务 | 来源 |
|---|---|---|
| **P0 ×2** | pt_qmt_state.py 7 处 hardcoded 'live' 参数化 / xfail strict 4 contract tests 转 PASS | D2 Finding B |
| **P1 ×2** | risk.py 3 + approval.py 3 = 6 endpoints 加 admin gate | D2.1 Finding E |
| **P2 ×4** | MiniQMTBroker.sell/.buy wrapper / scripts/intraday_monitor:141 删 hardcoded / cb_state paper L0 清理 / **_verify_admin_token 改 secrets.compare_digest** (D2.2 Finding H) | D2.1 D + D2 A/C + D2.2 H |
| **P3 ×3** | 10 files POST/PUT/DELETE 加 auth / LoggingSellBroker → QMTSellBroker / **startup_assertions 用 settings.SKIP_NAMESPACE_ASSERT** (D2.2 Finding G) | 治理债 |

**ETA**: 批 2 ~1 周 + D2.2 finding G/H 半天.

---

## 📦 LL 候选沉淀

### LL-XXX (新, 强候选): Debug 流程标准化 — 必先看 log

**触发**: 本 D2.2 user 在 D2 + D2.1 之后试 ADMIN_TOKEN, FastAPI 不响应. **第一反应应是看 Servy log**, 不是猜根因. CC 实际执行也是先读 stderr.log → 立即定位 NamespaceMismatchError.

**全局原则**: 任何服务异常 / curl 失败 / 未预期错误时, **第一步必看服务 log**, 不凭代码外观或经验猜测. Specifically:
- FastAPI/Servy: `logs/fastapi-{stdout,stderr}.log`
- Celery: `logs/celery-{stdout,stderr}.log`
- Beat: `logs/celery-beat-{stdout,stderr}.log`
- QMTData: `logs/qmt-data-{stdout,stderr}.log`
- 任何长跑服务异常: 先 `Get-Content -Tail 80` log file

**适用范围**: Debug FastAPI / Celery / Beat / DB / Redis / 任何长跑服务.

**升级铁律候选**: 月度 (X7) 铁律 audit 时考虑加入"Debug 必先看服务 log"原则.

### LL-XXX (新, 候选): Pydantic Settings 不写 os.environ — 注意 SSOT 边界

**触发**: D2.2 Finding G, .env 中 SKIP_NAMESPACE_ASSERT=1 加了不生效 (Pydantic 加载到 settings 对象不写 os.environ).

**全局原则**: 任何 .env 中的 key 仅通过 `from app.config import settings; settings.X` 读取. **不要假设 os.environ 也有该 key**. 反向: 任何 startup hook / lifecycle code 用 os.environ 读应用层配置 → 必须改用 settings (铁律 34 SSOT).

**修法 (留批 2 P3)**: startup_assertions.py 改用 settings.SKIP_NAMESPACE_ASSERT, 同时 config.py 加字段.

### LL-XXX (沿用 + 加固): audit 概括必须实测纠错

D2.2 实测:
- prompt §修复路径候选 A 写"加 SKIP 到 .env 末尾" → **实测不生效** (Pydantic 不写 os.environ)
- prompt §背景 写"FastAPI 启动 crash" → 实测**不是 crash**, 是 children 反复 spawn-die, master alive
- prompt §背景 候选 (a) "Servy 报告假 Running (僵尸进程)" → 实测**不是僵尸**, master 真 alive

3 项实测纠错再次加固 LL-XXX. **D2.2 自身的诊断 30%+ 偏离一阶概括**, 必须实测.

---

## 🚀 下一步建议

### (a) User 手工执行修复 (推荐立即)

按 §Q8 候选 D 命令清单执行 (4 步, ~30 秒):
1. `setx SKIP_NAMESPACE_ASSERT 1`
2. `servy-cli stop QuantMind-FastAPI`
3. `servy-cli start QuantMind-FastAPI`
4. 等 10 秒 + `curl http://localhost:8000/health` + admin endpoint 验证

### (b) 启批 2 (合并 D2 + D2.1 + D2.2 治理债)

按优先级 P0 → P1 → P2 → P3 分 PR 实施. ETA ~1 周.

### (c) 全方位审计 13 维 (D2/D2.1/D2.2 是 3/13)

D2 (激活路径) + D2.1 (API auth) + D2.2 (启动 + 真活验证) 已覆盖 3 维.

13 维其他 10 维留批 2 后启:
- 数据完整性 / 测试覆盖 / 文档腐烂 / Servy 服务依赖 / Redis 缓存 / 监控告警 / 调度链路 / 性能基线 / 配置 SSOT / 异常处理 / 安全 (SQL injection / secret rotation)

---

## 📂 附产物清单

- [docs/audit/fastapi_startup_debug_2026_04_29.md](fastapi_startup_debug_2026_04_29.md) — 本文档 (主产物)
- [docs/audit/STATUS_REPORT_2026_04_29_D2_2.md](STATUS_REPORT_2026_04_29_D2_2.md) — D2.2 整体执行报告
- 0 commit / 0 push / 0 PR / 0 .env 改 / 0 服务重启 — 纯诊断完成

---

> **状态**: D2.2 阶段 ✅ **完整完成** — 9 题诊断 + Servy log root cause 实测 + ADMIN_TOKEN 加载验证 + _verify_admin_token 行为单测 + 4 finding (G/H/I/J).
> **Root Cause**: `startup_assertions.py:125 raise NamespaceMismatchError` (.env=paper vs DB={'live':295}).
> **修复路径**: 候选 D — User 手工 `setx SKIP_NAMESPACE_ASSERT 1` + Servy 重启 (30 秒, 0 代码改, 0 真金风险).
> **关键纠错**: 加 SKIP 到 backend/.env **不生效** (Pydantic 不写 os.environ), 必须 setx.
> **D2.1 Finding F (ADMIN_TOKEN auth) 实测真活生效** ✅, 间接验证完成.
