# SYSTEM_RUNBOOK.md — QuantMind V2 系统运行手册

> **用途**: 给 Claude Code 的技术实施指南。描述系统**当前真实状态**, 不是设计愿景。
> **更新时间**: 2026-04-10 (Step 6-H 更新)
> **配合文档**: CLAUDE.md (24 条铁律 + 配置), SYSTEM_STATUS.md (现状快照), docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (§第四部分含 Step 0→6-H 重构记录)

---

> ⚠️ 本文档在 Step 6-B 时编写，Step 6-C~H 后部分接口可能有变化。以实际代码为准。

## §1 系统当前状态快照

| 维度 | 实际状态 |
|------|---------|
| 阶段 | Step 0→6-H 完成, PT 已暂停+已清仓 (2026-04-10, 等V4 Phase 2验证后重启) |
| 基线 Sharpe | **0.6095** (5 年 regression 基线) / **0.5309** (12 年 2014-2026) / **0.68** (SN b=0.50 inner) |
| 基线 MDD | -50.75% (5yr) / -56.37% (12yr base) / -39.35% (SN b=0.50 inner) |
| 回测验收 | max_diff=0 (regression_test.py, 铁律 15) |
| 后端 | 297 Python 文件 (backend/), FastAPI + sync psycopg2 + Celery |
| 前端 | 122 TS/TSX 文件, React 18 + Tailwind 4.1 + ECharts, 重构窗口内暂停开发 |
| 脚本 | 46 Python 文件 (scripts/, 不含 archive/) |
| 测试 | 2115 tests / 98 test files (Step 5 新增 48) |
| 调度 | Windows Task Scheduler (PT 主链) + Celery Beat (GP + PMS) |
| 数据库 | PostgreSQL 16.8 + TimescaleDB 2.26.0 @ D:\pgdata16, user=xin, db=quantmind_v2 |
| DB 规模 | factor_values 501M 行, klines_daily 11.7M, **minute_bars 139.3M** |
| code 格式 | **全表统一带后缀** (600519.SH 等) — Step 1 + Step 6-B 完成 |
| 服务管理 | **Servy v7.6** @ `D:\tools\Servy\servy-cli.exe` (不再用 NSSM) |
| 回测引擎 | `backend/engines/backtest/` 8 模块 (Step 4-A 拆分) |
| PT 主脚本 | `scripts/run_paper_trading.py` **345 行编排器** (原 1734, Step 6-A 拆分) |

---

## §2 启动链路

### 2.1 基础服务 (Servy 管理, 开机自启)

| 服务名 | 描述 | 依赖 | 日志 |
|--------|------|------|------|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | Redis, PostgreSQL | `logs/fastapi-std{out,err}.log` |
| QuantMind-Celery | celery worker --pool=solo | Redis | `logs/celery-std{out,err}.log` |
| QuantMind-CeleryBeat | celery beat scheduler (GP + PMS) | Redis, QuantMind-Celery | `logs/celery-beat-std{out,err}.log` |
| QuantMind-QMTData | qmt_data_service.py (QMT→Redis 60s 刷新) | Redis | `logs/qmt-data-std{out,err}.log` |

原生 Windows 服务 (不受 Servy 管):
- PostgreSQL16 @ `D:\pgdata16`, port 5432, user=xin, db=quantmind_v2
- Redis @ port 6379

### 2.2 管理命令

```bash
# 查看全部服务状态
powershell -File scripts\service_manager.ps1 status

# 重启单个服务 (后端代码修改后)
powershell -File scripts\service_manager.ps1 restart fastapi

# 重启所有服务
powershell -File scripts\service_manager.ps1 restart all

# 直接操作 Servy
D:\tools\Servy\servy-cli.exe stop  --name="QuantMind-FastAPI"
D:\tools\Servy\servy-cli.exe start --name="QuantMind-FastAPI"

# Celery worker graceful shutdown 需要 30 秒, 不要强制 kill
```

### 2.3 开发调试 (手动启动)

调试前先停 Servy 服务避免端口冲突:

```bash
D:\tools\Servy\servy-cli.exe stop --name="QuantMind-FastAPI"

cd D:\quantmind-v2\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# 验证: curl http://localhost:8000/api/health → {"status": "ok"}
```

前端:
```bash
cd D:\quantmind-v2\frontend
npm run dev
# 访问: http://localhost:3000
# Vite 代理 /api → 127.0.0.1:8000
```

### 2.4 PostgreSQL 管理

```bash
# PG 不走 Servy, 用原生 Windows Service Manager 或 pg_ctl
D:\pgsql\bin\pg_ctl.exe -D D:\pgdata16 status
D:\pgsql\bin\pg_ctl.exe -D D:\pgdata16 restart

# 连接数据库
D:\pgsql\bin\psql.exe -U xin -d quantmind_v2 -h 127.0.0.1
```

---

## §3 调度链路

### 3.1 Task Scheduler (PT 主链)

> PT 已暂停+已清仓 (2026-04-10)。以下调度任务描述保留供PT重启后参考。

| 时间 | 任务名 | 执行命令 | 用途 |
|------|--------|---------|------|
| 每小时 | QM-SmokeTest | `python scripts/smoke_test.py --auto-restart` | 62 个 GET 端点冒烟 + 自动重启 |
| 02:00 | QM-DailyBackup | `python scripts/pg_backup.py` | pg_dump 全量备份 (7 天滚动 + 月永久) |
| 09:05 | QuantMind_CancelStaleOrders | `python scripts/cancel_stale_orders.py` | QMT 撤单 |
| 09:31 | QuantMind_DailyExecute | `python scripts/run_paper_trading.py execute --execution-mode live` | QMT live 执行 |
| 09:35 | QuantMind_IntradayMonitor | `python scripts/intraday_monitor.py` (每 5 分钟) | 盘中风控 |
| 15:10 | QuantMind_DailyReconciliation | `python scripts/daily_reconciliation.py` | 收盘对账 + live 持仓快照 + performance_series |
| 16:25 | QM-HealthCheck | `python scripts/health_check.py` | 盘前 → health_checks 表 |
| 16:40 | QuantMind_DataQualityCheck | `python scripts/data_quality_check.py` | 数据完整性巡检 |
| 17:00 | QuantMind_DailyMoneyflow | `python scripts/pull_moneyflow.py` | moneyflow 拉取 (内建重试 3×10min) |
| 17:15 | QuantMind_DailySignal | `python scripts/run_paper_trading.py signal` | T 日信号生成 (内含 daily/basic/index 拉取) |
| 17:30 | QuantMind_FactorHealthDaily | `python scripts/factor_health_daily.py` | 因子衰减检测 (L0/L1/L2) |
| 20:00 | QuantMind_PTWatchdog | `python scripts/pt_watchdog.py` | 心跳监控 (DB 级 3 维度 + 钉钉 P0) |

### 3.2 Celery Beat (GP + PMS)

| 任务 | 触发 | 说明 |
|------|------|------|
| PMS 阶梯利润保护检查 | 每日 14:30 (仅交易日) | v1.0 三层, 非交易日自动跳过 |
| GP 因子挖掘 | 每周日 22:00 | population=100, generations=50 |

手动触发 GP:
```bash
celery -A backend.app.tasks.celery_app call backend.app.tasks.mining_tasks.run_gp_evolution
```

### 3.3 数据依赖链 (T 日执行顺序)

```
16:25 HealthCheck → 16:40 DataQualityCheck → 17:00 Moneyflow →
17:15 Signal (内含 klines/basic/index 并行拉取) → 17:30 FactorHealthDaily
```

---

## §4 架构分层

```
┌─ Router (backend/app/api/) ────────────────────────────┐
│   参数验证 (Pydantic) + 调用 Service + 返回 Response    │
│   不包含业务逻辑, 不直接访问 DB                          │
├─ Service (backend/app/services/) ──────────────────────┤
│   业务逻辑 + 调用 Engine + 调用其他 Service              │
│   sync psycopg2, 内部不 commit, 调用方管理事务           │
│   子目录: dispatchers/                                  │
├─ Engine (backend/engines/) ────────────────────────────┤
│   纯计算: 输入 DataFrame/dict → 输出 DataFrame/dict     │
│   无 IO, 无 DB 访问, 无外部 API 调用                     │
│   子包: backtest/ (8 模块), mining/, strategies/,       │
│         modifiers/                                      │
├─ Data (backend/data/) ─ ⭐ Step 5 新增 ────────────────┤
│   本地 Parquet 缓存, 按年分区                            │
│   不访问 DB, 不含业务逻辑                                │
│   当前只有 parquet_cache.py                             │
├─ Integration (backend/app/data_fetcher/) ──────────────┤
│   外部 API 封装 (Tushare/QMT), 重试/超时/错误            │
│   contracts.py + pipeline.py 定义统一入库契约            │
└─ DB: PostgreSQL 16.8 + TimescaleDB                    ┘
```

---

## §5 核心数据流

### 5.1 PT 信号生成 (T 日 17:15 signal phase)

`scripts/run_paper_trading.py signal` → 345 行编排器, 业务逻辑委托 4 个 Service:

```
run_signal_phase(trade_date):
  Step 0   health_check.run_health_check()         → health_checks 表
  Step 0.5 config_guard.assert_baseline_config()    → PAPER_TRADING_CONFIG 一致性
  Step 1   pt_data_service.fetch_daily_data()       → 并行 klines/basic/index
             → DataPipeline.ingest(KLINES_DAILY)    [铁律 17]
             → DataPipeline.ingest(DAILY_BASIC)
             → DataPipeline.ingest(INDEX_DAILY)
  Step 1.5 QMTClient.get_positions()/get_nav()      → Redis
           pt_qmt_state.save_qmt_state()            → position_snapshot + performance_series
  Step 1.6 risk_control_service.check_circuit_breaker_sync()
  Step 2   factor_engine.compute_daily_factors()    → factor_values 表
  Step 3   SignalService.generate_signals()         [铁律 16 唯一路径]
             → SignalComposer.compose(factor_df, universe, industry)
             → Top-20 等权 → signals 表
  Step 3.5 shadow_portfolio.generate_shadow_lgbm_*() (可选, 失败不阻塞)
  Step 5   收尾: scheduler_task_log.success
```

### 5.2 PT 执行 (T+1 日 09:31 execute phase)

`scripts/run_paper_trading.py execute --execution-mode live`:

```
run_execute_phase(exec_date):
  (live 模式) qmt_manager.startup()
  Step 5   读 signals 表最新信号 (signal_date = T)
  Step 5.5 pt_data_service.fetch_daily_data() (如未拉取)
  Step 5.7 QMT drift 检测: 若 actual < target×0.5 视为首次建仓
  Step 5.8 pt_monitor_service.check_opening_gap()
           单股 >5% 告 P1, 组合加权 >3% 告 P0
  Step 5.9 risk_control_service.check_circuit_breaker_sync()
  Step 6   ExecutionService.execute_rebalance()
             → 撤未完成订单 → QMT 下单 → fills
           写 trade_log + 更新 position_snapshot
```

### 5.3 回测 (配置驱动)

```bash
python scripts/run_backtest.py --config configs/backtest_12yr.yaml
```

内部流程:
```
load_strategy_config(yaml_path) → (BacktestConfig, SignalConfig, config_hash)
BacktestDataCache.load(start, end) → price/factor/benchmark DataFrame
                                      (30 min DB → 20 sec Parquet 90x 加速)
run_hybrid_backtest(factor_df, directions, price_data, config)  [runner.py]
  Phase A (向量化): SignalComposer.compose() → target_portfolios dict
  Phase B (事件驱动): BacktestEngine 日循环 → Fill → BacktestResult
写 backtest_run (含 config_yaml_hash + git_commit)  [铁律 15]
写 backtest_daily_nav / backtest_trades / backtest_holdings
```

### 5.4 GP 因子挖掘

```
Celery Beat 周日 22:00 → mining_tasks.run_gp_evolution()
  → pipeline_utils.py (5 个公开函数)
  → GPEngine.evolve():
      FactorDSL 28 算子 (Qlib Alpha158 兼容)
      DEAP 进化 + Warm Start (5 因子模板变体)
      适应度: SimBroker 回测结果
  → 写 pipeline_runs 表 (status: running → completed/failed)
  → 候选因子 → gp_approval_queue → 人工审批
  → 审批通过 → FactorOnboardingService.onboard_factor()
      → factor_registry + 历史值计算 + IC 计算 + Gate 统计更新
```

---

## §6 重构后的模块边界 (Step 0→6-B)

### 6.1 回测引擎: backend/engines/backtest/ (Step 4-A)

```
backend/engines/backtest/
├── __init__.py       (18 行, 公开符号导出)
├── engine.py         (562 行) 核心事件循环
├── broker.py         (309 行) SimBroker + 三因素成本
├── runner.py         (281 行) run_hybrid_backtest() 公开入口
├── validators.py     (105 行) ValidatorChain (涨跌停/停牌/完整性)
├── types.py          ( 92 行) BacktestResult / Fill / Order
├── executor.py       ( 81 行) 事件执行器
└── config.py         ( 49 行) BacktestConfig
```

公开入口: `from backend.engines.backtest.runner import run_hybrid_backtest, run_composite_backtest`

### 6.2 PT 服务: backend/app/services/pt_* (Step 6-A)

```
backend/app/services/
├── pt_data_service.py     (104 行) 并行数据拉取 (ThreadPoolExecutor max_workers=3)
├── pt_monitor_service.py  ( 90 行) 开盘跳空检测
├── pt_qmt_state.py        ( 84 行) QMT↔DB 状态同步
└── shadow_portfolio.py    (238 行) LightGBM 影子选股 (失败不阻塞)
```

### 6.3 数据层: backend/data/ (Step 5)

```
backend/data/
└── parquet_cache.py  (233 行) BacktestDataCache 按年分区 Parquet
```

路径: `cache/backtest/{YEAR}/{price_data,factor_data,benchmark}.parquet`

### 6.4 Data Contract + Pipeline: backend/app/data_fetcher/ (Step 3-A)

```
backend/app/data_fetcher/
├── contracts.py          (11 张表 Contract: KLINES_DAILY/DAILY_BASIC/
│                          MONEYFLOW_DAILY/INDEX_DAILY/FACTOR_VALUES/
│                          NORTHBOUND_HOLDINGS/SYMBOLS/EARNINGS_ANNOUNCEMENTS/
│                          STOCK_STATUS_DAILY/MINUTE_BARS)
├── pipeline.py           DataPipeline.ingest(df, contract)  [铁律 17 唯一入库]
├── tushare_client.py     (TushareDataSource / pt_data_service 使用; fetch_base_data.py 已删 MVP 2.1c Sub3.2)
├── tushare_fetcher.py    (日增量)
└── data_loader.py        (通用 upsert, 已被 DataPipeline 覆盖)
```

### 6.5 配置: configs/

```
configs/
├── pt_live.yaml         PT 生产配置 (5 因子等权 Top-20 月度 + PMS v1.0)
├── backtest_12yr.yaml   12 年基线回测
└── backtest_5yr.yaml    5 年回测 (历史比对)
```

加载器: `backend/app/services/config_loader.py::load_config()` → BacktestConfig + SignalConfig + config_hash

---

## §7 常见操作手册

### 7.1 后端代码修改后

```bash
powershell -File scripts\service_manager.ps1 restart fastapi
# Or: D:\tools\Servy\servy-cli.exe restart --name="QuantMind-FastAPI"
```

### 7.2 跑基线回测 (可复现性验证)

```bash
# 12 年基线, max_diff=0 才算通过
python scripts/regression_test.py
# 或直接跑
python scripts/run_backtest.py --config configs/backtest_12yr.yaml
```

预期: Sharpe=0.6095, MDD=-50.75%, 耗时 80s, max_diff=0.0 vs `cache/baseline/nav_5yr.parquet`

### 7.3 拉取分钟数据 (Step 6-B 后的正确路径)

```bash
python scripts/fetch_minute_bars.py --start 2026-01-01 --end 2026-04-09
# 分片并行:
python scripts/fetch_minute_bars.py --shard 0 --total-shards 4
python scripts/fetch_minute_bars.py --shard 1 --total-shards 4
python scripts/fetch_minute_bars.py --shard 2 --total-shards 4
python scripts/fetch_minute_bars.py --shard 3 --total-shards 4
```

(走 DataPipeline.ingest(MINUTE_BARS), code 字段自动带后缀)

### 7.4 数据库备份

```bash
# 手动 pg_dump
python scripts/pg_backup.py

# 每日 02:00 自动备份 (Task Scheduler QM-DailyBackup)
# 7 天滚动 + 每月 1 日永久保留
# 位置: D:/quantmind-v2/backups/daily/
```

### 7.5 PT 恢复 (重构完成后)

```bash
# 1. 验证全链路
python scripts/regression_test.py  # 确认 max_diff=0
pytest backend/tests/               # 确认 2115 测试全通过
python scripts/health_check.py      # 确认服务健康

# 2. 启用 Task Scheduler 任务
# 3. 启动 CeleryBeat
powershell -File scripts\service_manager.ps1 start celerybeat

# 4. 撤销 PT 暂停记录, 刷新 CLAUDE.md 当前状态
```

### 7.6 紧急撤单 / L4 熔断恢复

```bash
python scripts/cancel_stale_orders.py   # QMT 紧急撤单
python scripts/approve_l4.py            # L4 熔断人工审批恢复
```

---

## §8 已知差异与技术债

### 8.1 重构完成 (已解决)

- ✅ Step 1 + 6-B: DB 全表 code 格式统一带后缀 (包含 minute_bars 139M)
- ✅ Step 2: PT/回测信号路径统一 (SignalComposer)
- ✅ Step 3-A: Data Contract + DataPipeline 统一入库
- ✅ Step 3-B: stock_status_daily 日期级状态
- ✅ Step 4-A: backtest_engine.py 拆分 8 模块
- ✅ Step 4-B: YAML 配置驱动
- ✅ Step 5: Parquet 缓存 12 年回测跑通 (80s)
- ✅ Step 6-A: run_paper_trading.py 拆分 (1734 → 345)
- ✅ Step 6-B: minute_bars 格式统一 + 文档全面更新

### 8.2 开放技术债

| 项 | 优先级 | 说明 |
|----|-------|------|
| BJ 股过滤未落地 | 高 | signal_service 生产 + 回测默认, 当前配置里 exclude_bj=true 是临时方案 |
| is_st 全 false | 中 | klines_daily.is_st 未补拉, stock_status_daily 暂用 volume=0 推断 |
| 回测 12 年事件驱动 OOM | 中 | Phase A 向量化 OK (80s), Phase B 事件驱动模式仍 OOM, 需 DataHandler 模式 |
| minute_bars 只 2021-2025 | 低 | 5 年数据, 如需 12 年对齐需扩拉 2014-2020 |
| 两个 Tushare 客户端 | 低 | TushareClient + TushareFetcher, 重试/限流逻辑不一致 |
| 两个备份任务重复 | 低 | QM-DailyBackup 与 QuantMind_DailyBackup 指向同一脚本 |
| 两个 notification_service.py | 低 | `backend/app/services/` 和 `backend/services/` 各一份, 后者可能是废弃 |
| 24 张空表 | 低 | forex/AI/GP 预留表, 长期未使用 |

### 8.3 不要做的事 (重构后)

- ❌ 不要直接 `INSERT INTO` 生产核心表 → 走 `DataPipeline.ingest(df, Contract)` (铁律 17)
- ❌ 不要写独立的简化回测或信号生成 → 走 `SignalComposer` + `run_hybrid_backtest` (铁律 16)
- ❌ 不要在回测引擎内做 ST 推断 / 单位猜测 / adj_close 计算 → 靠 DataFeed 提供 (铁律 14)
- ❌ 不要硬编码策略参数 → 写到 `configs/*.yaml`, 通过 `config_loader` 加载 (铁律 15)
- ❌ 不要并发超过 2 个重数据 Python 进程 → PG OOM 历史教训 (铁律 9)
- ❌ 不要用 `::type` SQL 语法 → 用 `CAST(:param AS type)` (LL-034)
- ❌ 不要引用 `docs/archive/` 下的文档 (IMPLEMENTATION_MASTER / DESIGN_DECISIONS / TECH_DECISIONS / DEV_FOREX 等)
- ❌ 不要引用 `PROGRESS.md` (已废弃, 改看 `git log` + Roadmap V3 §第四部分)

---

## §9 文档导航

| 你要做什么 | 看这里 |
|-----------|-------|
| 了解系统现状 | `SYSTEM_STATUS.md` (含 §0 重构完成状态) |
| 查 24 条铁律 | `CLAUDE.md` |
| 查 Step 0→6-B 重构历史/决策 | `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md §第四部分` |
| 建数据库表 / 看 schema | `docs/QUANTMIND_V2_DDL_FINAL.sql` |
| 后端架构/分层 | `docs/DEV_BACKEND.md §0` (重构后的新分层) |
| 回测引擎内部模块 | `docs/DEV_BACKTEST_ENGINE.md §0` (模块拆分) |
| 因子计算 | `docs/DEV_FACTOR_MINING.md` |
| GP 闭环 | `docs/GP_CLOSED_LOOP_DESIGN.md` |
| 风控 L1-L4 | `docs/RISK_CONTROL_SERVICE_DESIGN.md` |
| ML Walk-Forward | `docs/ML_WALKFORWARD_DESIGN.md` |
| 因子测试注册表 (BH-FDR M) | `FACTOR_TEST_REGISTRY.md` |
| 教训 | `LESSONS_LEARNED.md` (36 条) |
| 研究知识库 | `docs/research-kb/` (19 条目) |
