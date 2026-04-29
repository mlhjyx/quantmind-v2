# Full Pytest Baseline 验证 — 2026-04-29 (D1)

> **范围**: P0 批 1 (PR #149 merged @ 708944a) 后 backend/tests/ 全 baseline 真跑, 验证铁律 40 测试债务不增长, 纯诊断 0 改动.
> **触发**: P0 批 1 上次只跑 4 个修改文件 (82 pass / 2 xfail), 未跑全 baseline. CLAUDE.md 测试债基线仍在用 S4 时代 (2026-04-15) 的 "32 fail" 数字, 而集合数已从 2100 → 4127 (+97% 平台化新增).
> **铁律覆盖**: **40** (测试债务不增长) / **10b** (生产入口真启动) / **22** (文档跟随代码) / **25** (改什么读什么).
> **git HEAD**: `708944a` docs(P0 batch 1): STATUS_REPORT.md
> **审计员**: AI 自主, 用户 0 接触

---

## 📋 执行摘要

| 检查 | 状态 | 关键数字 |
|---|---|---|
| **N 题清单 8 题** | ✅ 全过 | Q1-Q8 全 ✅, 1 项发现 (Python interpreter 陷阱) |
| **Batch 1 不破 baseline** | ✅ PASS | 4 修改文件 + smoke = 140 pass / 2 xfailed / 0 fail / 64s |
| **Full baseline pytest** | ✅ 完成 | **14 failed / 3932 passed / 47 skipped / 2 xfailed in 12:32**, pass rate **98.4%** |
| **启动断言污染测试** | ✅ 不污染 | 0 处 LifespanManager / 0 处 `with TestClient(app)` (lifespan 不被触发) |
| **F-NEW1 Python interpreter 陷阱** | ⚠️ 沉淀 LL | 系统 Python 无 PROJECT_ROOT, .venv Python 才能 import `from backend.qm_platform.X` |

---

## ✅ N 题清单 8 题逐答

### Q1 — main HEAD 是 708944a?

**✅ 通过** — `git log -1 --oneline` → `708944a docs(P0 batch 1): STATUS_REPORT.md`. 与任务前置一致.

### Q2 — working tree clean?

**✅ 通过** — `git status` → `On branch main / Your branch is up to date with 'origin/main' / nothing to commit, working tree clean`.

### Q3 — PostgreSQL / Redis 服务在跑?

**✅ 通过**:
- `redis-cli ping` → `PONG`
- `D:/pgsql/bin/psql.exe -U xin -d quantmind_v2 -c "SELECT 1"` (with `PGPASSWORD=quantmind`) → 返 `1`
- Servy: `QuantMind-FastAPI` Running, `QuantMind-QMTData` Running

### Q4 — 启动断言是否污染测试? **(KEY)**

**✅ 不污染**, 但保险起见命令行临时设 `SKIP_NAMESPACE_ASSERT=1` 作 safety net (不持久化).

**证据链**:
- [backend/app/main.py:36-72](D:\quantmind-v2\backend\app\main.py) lifespan 中 `run_startup_assertions(get_sync_conn)` 包 try/except + `engine.dispose()`. 在 .env=paper / DB 全 live 漂移下若被触发会 raise `NamespaceMismatchError`.
- 但 lifespan 触发要求**显式 ASGI startup event**:
  - `with TestClient(app) as client:` (Starlette TestClient 进入 `__enter__` 才 startup)
  - `LifespanManager(app)` (asgi_lifespan 包)
  - 或真 uvicorn 启动
- [backend/tests/conftest.py:55](D:\quantmind-v2\backend\tests\conftest.py) `client` fixture 用 `ASGITransport(app=app) + AsyncClient(...)` — **httpx ASGITransport 默认不发送 lifespan events**, 故不触发.
- grep `LifespanManager|asgi_lifespan` in backend/tests/ → 只 import-level 误命中, 0 处真用.
- grep `TestClient(app|with TestClient` in backend/tests/ → 仅 `test_factor_api.py:104` + `test_mining_api.py:58` 用 **裸 `TestClient(app, raise_server_exceptions=False)`, 非 `with` block**, 故 lifespan 不触发.
- Starlette TestClient `__enter__` 源码确认: 只有 context manager 进入才启 portal + send lifespan event.

**结论**: 全 4127 测试中 **0 处会触发 lifespan**, 故启动断言不污染. SKIP_NAMESPACE_ASSERT=1 是 belt-and-suspenders 保险.

### Q5 — 上次 baseline 数字?

**✅ 找到** ([docs/audit/S4_baseline.md](D:\quantmind-v2\docs\audit\S4_baseline.md), 2026-04-15):

| 项 | S4 数字 (2026-04-15) | 当前 (2026-04-29) |
|---|---|---|
| Collected | 2100 | **4127** (+2027, +97%) |
| Passed | 2066 (S4 tail-fix 后) | 待填 |
| Failed | 32 | 待填 |
| Errored | 0 (F72 fix 后) | 待填 |
| Skipped | 1 | 待填 |
| Pass rate | 98.4% | 待填 |
| 总用时 | ~95 min (2100 tests) | 预估 60-90 min (4127 tests) |

**注意**: 集合数差 **+97%** 主要是 Wave 1+2+3 平台化 (16+ MVP PR) + LL-059 9 步闭环跨 80+ session 沉淀新增 tests. **不能直接对比 32 fail 数字**, 本次实质是新基线.

### Q6 — conftest.py 隔离是否安全?

**✅ 通过** — [backend/tests/conftest.py](D:\quantmind-v2\backend\tests\conftest.py):
- `db_session` fixture 每测试用例独立 `create_async_engine(pool_size=1, max_overflow=0)`, 显式 `txn.begin()`, finally `txn.rollback()` + `engine.dispose()`. 不污染生产 DB.
- `client` fixture ASGITransport 不持久 server, 测试完毕 `__aexit__` 关.
- `strategy_id` fixture 用 `uuid.uuid4()` 隔离测试间数据.

### Q7 — 4 contract tests 中 2 xfail strict 行为?

**✅ 通过** — Batch 1 验证显示 `2 xfailed`, 符合设计:
- `test_save_qmt_state_uses_settings_execution_mode` xfail (BATCH 2 BUG)
- `test_save_live_fills_uses_settings_execution_mode` xfail (BATCH 2 BUG)
- `test_save_risk_state_uses_settings_execution_mode` PASS (`_upsert_cb_state_sync` 已合规)
- `test_write_signals_keeps_paper_per_d3` PASS (ADR-008 D3-KEEP 反向守门)

未来批 2 修写路径漂移后, 2 xfail 自动 XPASS strict → fail loud 触发 xfail 移除.

### Q8 — pytest --collect-only 总数?

**✅ 4127 tests collected in 9.33s** (含 backend/tests/smoke/).

---

## 🟢 Batch 1 不破 baseline 验证

### 命令

```bash
cd D:/quantmind-v2
SKIP_NAMESPACE_ASSERT=1 .venv/Scripts/python.exe -m pytest \
  backend/tests/test_risk_rules_pms.py \
  backend/tests/test_run_paper_trading_position_multiplier.py \
  backend/tests/test_startup_assertions.py \
  backend/tests/test_execution_mode_isolation.py \
  backend/tests/smoke/ \
  -m "smoke or not smoke" --tb=line -q --no-header
```

### 结果

```
140 passed, 2 xfailed, 8 warnings in 63.99s (0:01:03)
```

### 4 修改文件状态

| 文件 | tests | 状态 |
|---|---|---|
| `test_risk_rules_pms.py` | (LL-081 三段 guard 升级) | ✅ pass |
| `test_run_paper_trading_position_multiplier.py` | 3 SAST | ✅ pass |
| `test_startup_assertions.py` | 12 (含 SAST main.py) | ✅ pass |
| `test_execution_mode_isolation.py` | 含 4 contract tests | ✅ pass / 2 xfail (设计正确) |
| `backend/tests/smoke/` (29 文件) | 全 smoke marker | ✅ pass |

**结论**: Batch 1 修改不破 baseline ✅, 2 xfail strict 守门正确激活.

---

## ⚠️ F-NEW1: Python Interpreter 陷阱 (诊断中实际遭遇 + LL 候选)

### 现象

第一轮 baseline 用 `python -m pytest backend/tests/smoke/` 结果 **22 fail**, 全部:
```
ModuleNotFoundError: No module named 'backend'
File "backend/qm_platform/backtest/memory_registry.py:28"
  from backend.qm_platform._types import BacktestMode
```

类似断在 `executor.py:12` / `registry.py:31` / `runner.py:39` / `feature_flag.py:61` 等 10+ 处 `from backend.qm_platform.X` import.

### 根因

- 系统 `python` 解析到 `C:\Users\hd\AppData\Local\Programs\Python\Python311\python.exe`, sys.path **不含 PROJECT_ROOT**.
- 项目通过 [.venv/Lib/site-packages/quantmind_v2_project_root.pth](D:\quantmind-v2\.venv\Lib\site-packages\quantmind_v2_project_root.pth) 把 `D:\quantmind-v2` + `D:\quantmind-v2\backend` 注入 sys.path.
- 即 **必须用 `.venv/Scripts/python.exe`** 才能 `from backend.qm_platform.X` 成功.
- pre-push hook 强制用 `.venv/Scripts/python.exe` (config/hooks/pre-push 显式), 故 smoke 历史一直 PASS — 不是撒谎.

### 验证

```bash
.venv/Scripts/python.exe -c "import sys; print(sys.path)"
# → D:\quantmind-v2 + D:\quantmind-v2\backend  ✅

python -c "import sys; print(sys.path)"
# → 无项目目录 ❌
```

第二轮 batch 1 用 .venv Python 跑 → **140 pass / 2 xfailed / 0 fail in 64s** ✅

### LL 候选 (沉淀建议)

- **LL-NEW1**: "诊断 / baseline / smoke 必须用 `.venv/Scripts/python.exe`. 系统 Python 无 PROJECT_ROOT 注入, `from backend.qm_platform.X` 必败. 误用系统 Python 会产 100% 假阳性 fail. 检测方式: `python -c "import sys; print('\n'.join(sys.path))"` 验证含 `D:\quantmind-v2`. CI / pre-push / 任何 baseline 跑都用 .venv."

### F-NEW1 是否 batch 1 引入?

**否**. git blame `memory_registry.py:28` → commit `1096fde3` (2026-04-25 Session 36 周末): `refactor(platform): rename backend.platform → backend.qm_platform — PR-E1 永久消除 stdlib shadow`. 该 PR rename 时把 `from backend.platform.X` 全替换 `from backend.qm_platform.X`. **Batch 1 (PR #149) 0 改动 memory_registry.py**, 仅诊断时误用系统 Python 暴露此预存 path 依赖.

绝对路径写法本身有效 (在 .venv 下), 不需修改, 但**用错 Python 时 fail 模式**会误导诊断 — 故沉淀 LL.

---

## ✅ Full Baseline Pytest (完成)

> **任务 ID**: `bcdv53k36`, log → [docs/audit/baselines/_full_baseline_2026_04_29.log](D:\quantmind-v2\docs\audit\baselines\_full_baseline_2026_04_29.log)
> **实际用时**: 12:32 (远低于 60-90min 预估,4127 串行 0.18s/test 平均)

### 命令 (实际执行)

```bash
cd D:/quantmind-v2
SKIP_NAMESPACE_ASSERT=1 .venv/Scripts/python.exe -m pytest backend/tests/ \
  -p no:cacheprovider --tb=line -q --no-header \
  > docs/audit/baselines/_full_baseline_2026_04_29.log 2>&1
```

### 数字 (最终)

| 项 | 数字 | vs S4 baseline (2026-04-15) |
|---|---|---|
| Collected (collect-only) | 4127 | +2027 (+97%) |
| Run (实际跑) | 3995 | (132 dynamic skip in collect phase) |
| **Passed** | **3932** | +1866 (+90%) |
| **Failed** | **14** | **-18 (-56%)** ⭐ |
| Errored | 0 | 0 |
| xfailed | 2 (Fix 4 contract tests, 设计正确) | +2 |
| xpassed | 0 (无 xfail strict 失效) | 0 |
| Skipped | 47 | +46 |
| 用时 | 752.60s (12:32) | -82min (S4 95min) |
| Pass rate | **98.4%** | = 98.4% |
| 启动断言污染 | ✅ 不污染 (Q4 已证) | N/A |

**铁律 40 守门**: ✅ **PASS** — fail 数 14 < S4 32 (绝对值减少 56%, 集合数翻倍下), batch 1 不引入新 fail.

### 完整 14 Fail 清单

| # | Test | 类别 | 是否 batch 1 引入 | 真因 (sample 验证后) |
|---|---|---|---|---|
| 1 | `test_factor_determinism.py::test_factor_determinism` | 数据/cache | ❌ 历史债 | 第二次运行返 0 行 (`80775 == 0` 断言失败), DB/cache 状态依赖, 非确定性 |
| 2 | `test_factor_health_daily.py::TestFactorHealthIntegration::test_dry_run_normal_date` | DB integration | ❌ 历史债 | factor_health DB 状态 / scheduler_task_log 依赖 |
| 3 | `test_factor_health_daily.py::TestFactorHealthIntegration::test_db_write_scheduler_task_log` | DB integration | ❌ 历史债 | scheduler_task_log 写入校验 |
| 4 | `test_platform_skeleton.py::test_platform_import_has_no_side_effects` | 架构 | ❌ MVP 4.1 PR #131 引入 | platform import 触发 `psycopg2` 加载 (PostgresAlertRouter 顶层 import) |
| 5 | `test_risk_engine.py::TestEngineExecute::test_sell_action_calls_broker` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 已迁 `INSERT INTO risk_event_log` → `event_outbox` (event sourcing 准备), test 未更新 |
| 6 | `test_risk_engine.py::TestEngineExecute::test_bypass_action_logs_but_no_broker_no_notify` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 同 #5 event_outbox 迁移 |
| 7 | `test_risk_engine.py::TestEngineExecute::test_broker_failure_not_raising_logs` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 同 #5 |
| 8 | `test_risk_wiring.py::TestBuildRiskEngine::test_factory_registers_pms_rule` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | factory 默认注册从 `["pms"]` 扩到 `["pms","single_stock_stoploss","holding_time","new_position_volatility"]`, test 期望值落后 |
| 9 | `test_risk_wiring.py::TestBuildRiskEngine::test_factory_accepts_extra_rules` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 同 #8 |
| 10 | `test_risk_wiring.py::TestBuildRiskEngine::test_factory_extra_rules_none_keeps_pms_only` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 同 #8 |
| 11 | `test_risk_wiring.py::TestBuildIntradayRiskEngine::test_factory_registers_4_intraday_rules` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | intraday factory 默认 rule 数变更 |
| 12 | `test_risk_wiring.py::TestBuildIntradayRiskEngine::test_intraday_factory_accepts_extra_rules` | Risk v2 | ❌ Risk v2 PR #143-148 引入 | 同 #11 |
| 13 | `test_services_healthcheck.py::TestSendAlert::test_no_webhook_returns_false_silent` | MVP 4.1 | ❌ MVP 4.1 PR #131 引入 | `psycopg2.errors.UndefinedTable: relation "alert_dedup" does not exist` — alert_dedup 表 migration 未在测试 DB 跑 |
| 14 | `test_services_healthcheck.py::TestSendAlert::test_dingtalk_exception_returns_false` | MVP 4.1 | ❌ MVP 4.1 PR #131 引入 | 同 #13 |

### Batch 1 影响判定 (4 修改文件)

| 文件 | tests 数 | 全跑结果 | 守门有效 |
|---|---|---|---|
| `test_risk_rules_pms.py` | LL-081 三段 guard 5 case | ✅ 全 pass | 单仓 ALL_SKIPPED 错告新增 |
| `test_run_paper_trading_position_multiplier.py` | 3 SAST | ✅ 全 pass | hardcoded 0.5 替换守门 |
| `test_startup_assertions.py` | 12 (含 SAST main.py + bypass) | ✅ 全 pass | 启动断言 + dispose + bypass 三守门 |
| `test_execution_mode_isolation.py` | 含 4 contract tests | ✅ 全 pass / 2 xfailed (设计) | 写路径漂移守门 (xfail strict 等批 2) |

**结论**: Batch 1 (PR #149) 4 文件全绿, 0 fail 引入, 2 xfail strict 守门正确激活. 14 fail 完全是历史债 (Risk v2 PR #143-148 + MVP 4.1 PR #131 + 1 数据状态依赖).

### Risk v2 8 fail 责任链

Risk v2 PR #143-148 是 Session 44 当天 ~14:00-16:00 推的 7 PR (PR #143 历史回放 / #144 scheduler_task_log audit / #145+#146 Beat dead-man's-switch / #147 Position.entry_date 契约 / #148 PositionHoldingTime + NewPositionVolatility 双 rule). 在 main @ `1e11a56` 时合入, 早于 batch 1 PR #149 的 `3bef258`.

这 7 PR 扩了 risk engine 默认注册的 rule 集合 (从 1 → 4) + 把 risk_event 写入迁到 event_outbox (event sourcing 准备), 但 `test_risk_engine.py` / `test_risk_wiring.py` 没同步更新 — Session 44 末 handoff 写"90+ unit tests 全绿" 是基于**修改文件**的局部 pytest, 不是 full baseline.

**测试债判定**: 这 8 fail 是 Session 44 测试债**遗漏**, 非 batch 1 (PR #149) 引入. 应在批 2 启动前一并清理 (建议 batch 1.5 修测试落后, 不需新功能).

---

## 📦 Finding 报告 (N 题外异常)

### F-NEW1 Python interpreter 陷阱 (见上, LL 候选)

### F-NEW2 Risk v2 测试债遗漏 (Session 44 7 PR 测试落后)

8 fail (test_risk_engine 3 + test_risk_wiring 5) 是 PR #143-148 改 risk engine 默认 rule 集合 + 写入路径迁移时未同步更新单测期望值. Session 44 末 handoff 写"90+ unit tests 全绿"基于**修改文件**的 scope-local pytest, 漏跑 full baseline. 建议:
- 批 2 启动前先清这 8 fail (1-2h, 纯 test fixture 更新, 无新逻辑)
- 沉淀 LL: "新功能扩接口 (rule 集合 / 表名迁移) 必跑 full baseline 而非 scope-local pytest"

### F-NEW3 MVP 4.1 PR #131 测试 DB migration 缺失 (alert_dedup 表)

`test_services_healthcheck.py` 2 fail 都是 `alert_dedup` 表不存在. PR #131 (MVP 4.1 batch 1 PostgresAlertRouter) 引入 alert_dedup migration, 但测试 DB 没跑. 修复:
- conftest.py 应自动 apply pending migrations 到测试 DB, 或
- 单测改用 in-memory mock router

### F-NEW4 test_factor_determinism 非确定性 (DB 状态依赖)

`test_factor_determinism` 第二次运行返 0 行而非期望的 80775 行. 单跑可重现, 推测因子计算依赖 DB 当日 trade_date 数据, 测试在 DB 中行情数据耗尽后第二次跑就空. 历史债, 非 batch 1 引入.

### F-NEW5 test_platform_skeleton 架构契约违反 (psycopg2 顶层 import)

PR #131 PostgresAlertRouter 在 `qm_platform/observability/__init__.py` 顶层 import psycopg2, 违反 platform 不持 DB 客户端契约. 应改 lazy import 或 dependency injection. 历史债, 非 batch 1 引入.

---

## 🚀 下一步建议 — D2 live-mode 激活路径扫描 (草稿 prompt)

```text
任务: D2 — Live-Mode 激活路径扫描 (纯诊断 0 改动)

【背景上下文】
- 批 1 已 merge, startup_assertions 上线, 但 .env=paper / DB 全 live 漂移持续
- 写路径漂移源头: pt_qmt_state.save_qmt_state 5 处 hardcoded 'live' (留批 2)
- 用户决策路径 A/B/C 之前需要全面看清 live mode 激活时所有副作用

【目标】
- 全调用方扫描 settings.EXECUTION_MODE == 'live' / settings.is_live() / settings.EXECUTION_MODE 引用
- 副作用分类: 写路径 (DB INSERT/UPDATE) / 调度路径 (schtask trigger) / 读路径 (load_*) / API 路径 (FastAPI router) / Redis 路径 / Broker 路径
- 标记每处: 是否 batch 2 / batch 3 计划修, 还是纯读不动

【强制全面思考】
1. .env 改 paper→live 后第一次 FastAPI 重启时, lifespan 哪些副作用立即发生?
2. 改 live 后 09:31 DailyExecute schtask 触发,  从生产路径走到 broker.sell 全链路有几个 hardcoded live/paper 分支?
3. PMS L1/L2/L3 触发后, LoggingSellBroker.sell() 在 live 下走什么分支? (注意 batch 1 未替换)
4. circuit_breaker_state 当前 paper 行 stale (4-20 L0), live 行如何被读? cb_state load 路径含 mode 过滤吗?
5. risk_event_log INSERT 走 mode 字段, 哪些 rule 写入时绑死 mode='live'?
6. position_snapshot 写路径 (save_qmt_state) 5 处 hardcoded 是否就是写路径漂移全集?
7. signal_service._write_signals 已确定 D3-KEEP 'paper' (反向守门), 此路径在 live 下保持 'paper' 不变, 验证 grep 一致

【硬执行边界】
✅ 允许: grep / glob / 读文件 / git log / 写诊断 doc 到 docs/audit/live_mode_activation_paths_2026_04_29.md
❌ 禁止: 改任何代码 / .env / DB / Redis / 重启服务 / commit / push

【输出】
1. settings.EXECUTION_MODE 全调用方表 (file:line + context + 副作用类型)
2. live 激活 5 维度 (写/调度/读/API/Redis/Broker) 副作用图
3. batch 2/3 修复覆盖率: 每处副作用是否被批 2/3 计划覆盖, 缺口报告
4. 路径 A/B/C 风险评估更新 (基于实测扫描)
5. docs/audit/live_mode_activation_paths_2026_04_29.md
```

---

## 📂 附产物清单

- [docs/audit/full_baseline_2026_04_29.md](D:\quantmind-v2\docs\audit\full_baseline_2026_04_29.md) — 本文档
- [docs/audit/baselines/_full_baseline_2026_04_29.log](D:\quantmind-v2\docs\audit\baselines\_full_baseline_2026_04_29.log) — 完整 pytest log (background 跑中)
- 0 commit / 0 push / 0 PR (纯诊断)

---

> **状态**: D1 阶段 ✅ **完整完成** — N 题清单 + batch 1 验证 + full baseline 跑完 + 5 finding (LL 候选) 全固化.
> **铁律 40 守门结论**: ✅ **PASS** — 14 fail @ 4127 collected vs S4 baseline 32 fail @ 2100 collected, batch 1 (PR #149) 不引入新 fail, 2 xfail strict 守门激活正确.
>
> **下一步 (用户决策, 3 选 1 或并行)**:
> 1. **批 1.5 测试债清理** (建议优先) — 清 8 fail (Risk v2 测试落后) + 2 fail (alert_dedup migration) + 1 fail (platform_skeleton 架构契约), ~2-3h, 0 新逻辑
> 2. **D2 live-mode 激活路径扫描** (本报告下方草稿 prompt) — 为路径 A/B/C 决策铺垫
> 3. **批 2 启动** (写路径漂移消除 + LoggingSellBroker → QMTSellBroker) — 真金风险消除
>
> 推荐顺序: 批 1.5 → D2 → 路径 A/B/C 决策 → 批 2.
