# STATUS_REPORT — D2.2 FastAPI Startup Debug + ADMIN_TOKEN 真活验证

> **Sprint**: D2.2 (T1 Sprint, 2026-04-30 凌晨)
> **Branch**: main @ `bc8bad4` (PR #151 批 1.5 merged) — 0 改动 / 0 commit / 0 PR
> **Trigger**: D2.1 后 user 配置 ADMIN_TOKEN 试 curl, FastAPI 不响应 (Servy GUI 报 Running 但 port 8000 不监听)
> **方法**: 先看 log (LL-XXX 候选), 再 python -c 实测验证
> **关联铁律**: 25 / 26 / 33 / 35 / 36
> **关联文档**: [fastapi_startup_debug_2026_04_29.md](fastapi_startup_debug_2026_04_29.md) (主产物 ~700 lines) / [api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) / [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md)

---

## ✅ D2.2 任务交付

| # | 交付 | 状态 |
|---|---|---|
| **A** | 9 题逐答 (Q1-Q9 全 ✅) | ✅ |
| **B** | FastAPI 启动失败 root cause 实测确认 | ✅ |
| **C** | ADMIN_TOKEN 加载状态 (len=43 ✅) | ✅ |
| **D** | _verify_admin_token 安全性实测 (3 case + timing attack check) | ✅ |
| **E** | 修复路径推荐 (候选 D — setx + Servy 重启, 0 代码改) | ✅ |
| **F** | 4 项重大新发现 (Finding G/H/I/J) | ✅ |
| **G** | 主产物 docs/audit/fastapi_startup_debug_2026_04_29.md | ✅ |
| **H** | 本 STATUS_REPORT | ✅ |

**0 代码改动 / 0 commit / 0 push / 0 PR / 0 .env 改 / 0 服务重启** — 纯诊断完成.

---

## 📊 关键实测数字

### Servy / FastAPI 状态

| 项 | 值 | 来源 |
|---|---|---|
| Servy GUI Status | Running | servy-cli status |
| PID 5532 (master) | python.exe alive, idle (CPU 0.015) | Get-Process |
| PID 5532 children | conhost(34940) + python.exe(21588=uvicorn worker) | Get-CimInstance Win32_Process |
| Port 8000 listening | ❌ 不监听 (0 row) | Get-NetTCPConnection |
| Last child die | 23:58:23 ("Application startup failed. Exiting.") | stderr.log |
| Restart loop frequency | 每 ~6s 一次 (uvicorn --workers 2 spawn → assert raise → die) | stdout.log timestamps |

### Root Cause Traceback

```
File "backend/app/main.py:60" lifespan
    run_startup_assertions(get_sync_conn)
File "backend/app/services/startup_assertions.py:125" assert_execution_mode_consistency
    raise NamespaceMismatchError(...)

NamespaceMismatchError: EXECUTION_MODE drift detected:
.env=paper but DB position_snapshot recent 30d has {'live': 295}
```

### ADMIN_TOKEN 加载

| 检查 | 结果 |
|---|---|
| settings.ADMIN_TOKEN | len=43 ✅ |
| .env L38 ADMIN_TOKEN= | 已配置 (URL-safe base64, ~32 bytes random) |
| Pydantic env_file | `D:/quantmind-v2/backend/.env` ✅ |
| os.environ.get("ADMIN_TOKEN") | **`<NOT IN os.environ>`** ⚠️ (Finding G) |

### _verify_admin_token 行为

| Test | 结果 |
|---|---|
| 错 token | ✅ status=401 detail='无效的Admin Token' |
| 对 token | ✅ accepted, returned len=43 |
| 空 token | ✅ status=401 |
| timing attack | ⚠️ P2 — 用 `!=` plain compare (Finding H) |

### startup_assertions 行为

| Case | 行为 |
|---|---|
| env=paper + DB={'live':295} | ✅ raise NamespaceMismatchError (current crash) |
| env=live + DB={'live':295} | ✅ pass (env_mode in db_modes) |
| env=paper + DB={} | ✅ pass silently (warning log) |

---

## 🔴 4 项重大新发现

### Finding G — Pydantic .env 加载不写 os.environ (启动断言 SKIP 必须 setx)

Pydantic Settings 加载 .env 仅写 settings 对象, **不写 os.environ**. 启动断言 (startup_assertions.py:151) 读 `os.environ.get("SKIP_NAMESPACE_ASSERT")`, **加 SKIP=1 到 backend/.env 不生效**.

**反驳 prompt**: D2.2 prompt 候选 A 写"加 SKIP 到 .env" → **实测不生效**. 必须 `setx SKIP_NAMESPACE_ASSERT 1` (Windows User env, 持久化注册表).

**修法** (留批 2 P3): startup_assertions.py 改用 settings.SKIP_NAMESPACE_ASSERT, config.py 加字段 default False.

### Finding H — _verify_admin_token P2 timing attack

execution_ops.py:75 用 `if x_admin_token != settings.ADMIN_TOKEN` plain compare. Non-constant-time, 理论可探测.

**风险**: Windows 本地 + CORS 严格 localhost:3000 → 利用门槛高, 但治理债 (违反铁律 35 secrets 比较最佳实践).

**修法** (留批 2 P3): `secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN)`.

### Finding I — Servy uvicorn --workers 2 重启循环掩盖 root cause

Servy GUI 显示 Status: Running, master 进程 (PID 5532) 真 alive, 但 child workers 反复 spawn → die. **从未 bind port 8000**. 用户难发现真因.

**修法** (留批 3 P3 治理): Servy 配置 max_restart_attempts=5 转 Status: Failed; 或 main.py lifespan 早 sys.exit(1) (考虑信号处理).

### Finding J — startup_assertions 错误信息中文 mojibake

stderr.log 末尾 NamespaceMismatchError message 含 GBK 解码错误 (Servy console encoding GBK + uvicorn UTF-8 双重解码). **不影响诊断** (file paths + Exception class + 选项 A/B/C/D 仍可读), 但中文 "撤回前必须修源头" 显示为 mojibake.

**修法** (留批 3 P3 治理): Servy 配置加 `set PYTHONIOENCODING=utf-8` 或 logging_config 强制 stderr handler encoding=utf-8.

---

## 🚨 风险等级总评

| 维度 | 等级 |
|---|---|
| FastAPI 启动失败 root cause | ✅ 实测确认 (NamespaceMismatchError + 启动断言阻断) |
| 修复路径有效性 | 🟢 setx SKIP=1 + Servy 重启 (0 代码改, ETA 30 秒) |
| ADMIN_TOKEN 加载 | 🟢 OK (D2.1 Finding F close) |
| _verify_admin_token 行为 | 🟢 正确 (3 case 全通过), ⚠️ Q5.4 P2 timing attack (Finding H) |
| **.env → os.environ 机制** | ⚠️ **P3 治理债** (Finding G, startup_assertions 用 os.environ 不一致) |
| 真金 P0 风险 (D2.1 已确认) | 🟢 0 (LIVE_TRADING_DISABLED guard + admin gate + SAST 三重保护) |

**总评**: 🟢 **可控修复** — 用户 setx + Servy 重启 30 秒可恢复. 0 真金风险, 0 数据风险, 0 代码改动.

---

## 🛤️ 修复路径推荐 (候选 D)

⚠️ **关键**: 必须 setx (Windows User env), **加 .env 不生效** (Finding G).

User 手工执行 (CC 不执行):

```cmd
:: 1. 设 Windows User env
setx SKIP_NAMESPACE_ASSERT 1

:: 2. 重启 Servy 主服务 (让其继承新 env)
D:\tools\Servy\servy-cli.exe stop --name=QuantMind-FastAPI
ping -n 5 127.0.0.1 > NUL
D:\tools\Servy\servy-cli.exe start --name=QuantMind-FastAPI

:: 3. 等 10 秒
ping -n 10 127.0.0.1 > NUL

:: 4. 验证
netstat -ano | findstr :8000
curl http://localhost:8000/health
:: 验证 admin auth:
curl -X POST http://localhost:8000/api/execution/cancel-all -H "Content-Type: application/json"
:: 预期 401 (无 token)
curl -X POST http://localhost:8000/api/execution/cancel-all -H "X-Admin-Token: 5BealWxeV-nujtYIfEsGXDOKhasC8rz6iLNTjBUfbLA"
:: 预期 200 或业务返
```

**风险评估**:
- 🟢 0 真金风险 (SKIP 只 bypass 启动断言, LIVE_TRADING_DISABLED guard 仍盖 chokepoint)
- 🟢 0 数据风险 (写读路径仍受 ADR-008 命名空间隔离)
- 🟡 P2 治理债 (SKIP=1 长期保留违反铁律 33, 应在批 2 修写路径漂移后撤 `setx SKIP_NAMESPACE_ASSERT ""`)

---

## 📋 批 2 scope 更新 (D2 + D2.1 + D2.2 综合)

| 优先级 | 子任务 | 来源 |
|---|---|---|
| **P0 ×2** | pt_qmt_state.py 7 处 hardcoded 'live' 参数化 / xfail strict 4 contract tests 转 PASS | D2 Finding B |
| **P1 ×2** | risk.py 3 + approval.py 3 = 6 endpoints 加 admin gate | D2.1 Finding E |
| **P2 ×4** | MiniQMTBroker.sell/.buy wrapper / scripts/intraday_monitor:141 删 hardcoded / cb_state paper L0 清理 / **_verify_admin_token 改 secrets.compare_digest** (D2.2 Finding H) | D2.1 D + D2 A/C + D2.2 H |
| **P3 ×4** | 10 files POST/PUT/DELETE 加 auth / LoggingSellBroker → QMTSellBroker / **startup_assertions 用 settings.SKIP_NAMESPACE_ASSERT** (D2.2 Finding G) / **Servy console encoding UTF-8** (D2.2 Finding J) | 治理债 |

**ETA**: 批 2 ~1 周 + D2.2 finding G/H/I/J 半天.

---

## 📦 LL 候选沉淀

### LL-XXX (新, 强候选): Debug 流程标准化 — 必先看 log

**触发**: 本 D2.2 第一反应应是看 Servy log, 不是猜根因. CC 实际执行也是先读 stderr.log → 立即定位 NamespaceMismatchError, 30 秒解决问题.

**全局原则**: 任何服务异常 / curl 失败 / 未预期错误时, **第一步必看服务 log**, 不凭代码外观或经验猜测:
- FastAPI/Servy: `logs/fastapi-{stdout,stderr}.log`
- Celery: `logs/celery-{stdout,stderr}.log`
- Beat: `logs/celery-beat-{stdout,stderr}.log`
- QMTData: `logs/qmt-data-{stdout,stderr}.log`
- 任何长跑服务异常: 先 `Get-Content -Tail 80` log file

**升级铁律候选**: 月度 (X7) 铁律 audit 时考虑加入"Debug 必先看服务 log"原则.

### LL-XXX (新, 候选): Pydantic Settings 不写 os.environ — SSOT 边界

**触发**: D2.2 Finding G, .env 中 SKIP=1 加了不生效.

**全局原则**: 任何 .env 中的 key 仅通过 `from app.config import settings; settings.X` 读取. **不要假设 os.environ 也有该 key**. 反向: 任何 startup hook / lifecycle code 用 os.environ 读应用层配置 → 必须改用 settings (铁律 34 SSOT 延伸).

### LL-XXX (沿用 + 加固): audit 概括必须实测纠错

D2.2 实测纠错 3 项:
1. prompt 候选 A "加 SKIP 到 .env" → **实测不生效** (Pydantic 不写 os.environ)
2. prompt 背景 "FastAPI 启动 crash" → 实测**不是 crash**, master alive + children 反复 spawn-die
3. prompt 背景 "Servy 报告假 Running" → 实测**不是僵尸**, master 真 alive

3 项实测纠错再次加固 LL-XXX. **D2.2 自身的诊断 30%+ 偏离一阶概括**, 必须实测.

---

## 🚀 用户决策清单

### 立即 (推荐)

1. **执行修复路径 D** (上方命令清单 30 秒) → 恢复 FastAPI
2. 验证 admin endpoint auth (curl 测试)

### 后续 (留批 2)

3. **启批 2 PR**: P0 写路径漂移修 + P1 risk/approval auth + P2 dead API 修 + P3 治理债
4. 批 2 完成后撤 SKIP (`setx SKIP_NAMESPACE_ASSERT ""`)

### 可选 (留批 3+)

5. 全方位审计 13 维剩余 10 维 (数据完整性 / 测试覆盖 / 文档腐烂 / Servy / Redis / 监控 / 调度 / 性能 / 配置 / 异常 / 安全)

---

## 📂 附产物清单

- [docs/audit/fastapi_startup_debug_2026_04_29.md](fastapi_startup_debug_2026_04_29.md) — 主产物 (~700 lines, 完整诊断)
- [docs/audit/STATUS_REPORT_2026_04_29_D2_2.md](STATUS_REPORT_2026_04_29_D2_2.md) — 本 STATUS_REPORT
- 0 commit / 0 push / 0 PR (纯诊断, 0 改动)

---

> **状态**: D2.2 阶段 ✅ **完整完成** — 9 题诊断 + Servy log root cause 实测 + ADMIN_TOKEN 加载验证 (len=43 ✅) + _verify_admin_token 行为单测 (3 case 通过) + 4 finding (G/H/I/J).
> **Root Cause**: `startup_assertions.py:125 raise NamespaceMismatchError` (.env=paper vs DB={'live':295}).
> **修复路径**: 候选 D — User 手工 `setx SKIP_NAMESPACE_ASSERT 1` + Servy 重启 (30 秒, 0 代码改).
> **关键纠错**: 加 SKIP 到 backend/.env **不生效** (Pydantic 不写 os.environ), 必须 setx.
> **D2.1 Finding F (ADMIN_TOKEN auth) 实测真活生效** ✅.
