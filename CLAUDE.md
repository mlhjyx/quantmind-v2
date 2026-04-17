# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **系统现状**: SYSTEM_STATUS.md（环境/数据库/代码/架构全景）

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase A-F完成, v3.8路线图, Step 0→6-H重构+研究完成, PT配置已更新CORE3+dv_ttm(2026-04-12 WF PASS), Sharpe基线=**WF OOS 0.8659 (CORE3+dv_ttm+SN050, +33% vs CORE5 baseline 0.6521, MDD -13.91%)**
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB(PyTorch cu128), 32GB DDR5
- **PMS**: v1.0阶梯利润保护3层(14:30 Celery Beat检查, v2.0已验证无效不实施)
- **下一步(V4路线图)**: ~~Phase 1.1~~ ✅ → ~~Phase 1.2~~ ✅ → ~~Phase 2.1~~ ❌NO-GO → ~~Phase 2.2~~ ❌NO-GO → ~~Phase 2.3~~ ✅诊断 → ~~Phase 2.4~~ ✅探索+WF PASS → ~~PT配置更新~~ ✅ → **Phase 3 自动化** → Phase 4 PT重启
- **调度链路**: 16:15数据拉取 → 16:25预检 → 16:30因子+信号 → 17:00-17:30收尾(moneyflow/巡检/衰减) → T+1 09:31执行 → 15:10对账

## 技术栈（实际使用，非设计文档）

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + **sync psycopg2** + Celery + Redis |
| 前端 | React 18 + TypeScript + Tailwind 4.1 + ECharts/Recharts + Zustand |
| 数据库 | PostgreSQL 16.8 + TimescaleDB 2.26.0 (D:\pgsql, D:\pgdata16, user=xin, db=quantmind_v2) + Redis 5.0.14.1 |
| 事件总线 | Redis Streams (`qm:{domain}:{event_type}`), StreamBus模块 |
| 服务管理 | Servy v7.6 (`D:\tools\Servy`), 替代NSSM |
| 调度 | Windows Task Scheduler (PT) + Celery Beat (GP) |
| GPU | PyTorch cu128, RTX 5070 12GB (cupy不支持Blackwell sm_120) |
| 缓存 | 本地Parquet快照(backend/data/parquet_cache.py按年分区), factor_values 501M行→TimescaleDB hypertable |
| 交易 | 国金miniQMT (A股) |
| Portfolio优化 | riskfolio-lib 7.2.1 (MVO/RP/BL, 阶段2评估) |
| 向量化回测 | vectorbt 0.28.5 (Numba加速, 待评估快速筛选用) |

## 因子系统

### 因子池状态
| 池 | 数量 | 说明 |
|----|------|------|
| CORE (Active, PT在用) | 4 | turnover_mean_20(-1), volatility_20(-1), bp_ratio(+1), dv_ttm(+1) — **WF OOS Sharpe=0.8659, MDD=-13.91%** (2026-04-12 PASS) |
| CORE5 (前任, 回测基线) | 5 | turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio — regression_test基线对照用 |
| PASS候选 | 32+16 | FACTOR_TEST_REGISTRY.md中PASS状态因子(含Alpha158六+PEAD-SUE) + 16微结构因子(Phase 3E neutral IC PASS+noise ROBUST, 但WF等权加入FAIL) |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非9.1%, v3.4证伪) |
| DEPRECATED | 5 | momentum_5/momentum_10/momentum_60/volatility_60/turnover_std_20 |
| 北向个股RANKING | 15 | nb_ratio_change_5d等, IC反向(direction=-1), G1特征池 |
| LGBM特征集 | 70 | 全部factor_values因子(48核心+15北向+7新因子Phase2.1, DB自动发现) |

### 因子存储 (2026-04-15 S1 audit 实测)
- **factor_values**: **816,408,002 行** (155 GB, TimescaleDB hypertable 151 chunks)
- **factor_ic_history**: 133,125 行, IC唯一入库点(铁律11), 未入库IC视为不存在
- **Parquet缓存**: `_load_shared_data` 30min→1.6s(1000x), `fast_neutralize_batch` 15因子/17.5min
- **minute_bars**: **190,885,634 行** (21 GB, Step 6-B 已统一 code 格式), 5年(2021-2025), Baostock 5分钟K线, 2537只股票(0/3/6开头, 无BJ)
- **klines_daily**: 11,721,768 行 (4 GB, TimescaleDB hypertable 51 chunks)
- **daily_basic**: 11,507,171 行 (3 GB)

### 因子评估流程
1. 经济机制假设(铁律13/14) → 2. IC计算+入库(铁律11) → 3. 画像(factor_profiler, 5维) → 4. 模板匹配(T1-T15) → 5. Gate G1-G8+BH-FDR → 6. 回测验证(paired bootstrap p<0.05)

## 架构分层（DEV_BACKEND §3.1）

```
Router(api/) → Service(services/) → Engine(engines/) + DB
  Router: 参数验证+调用Service+返回Response, 不含业务逻辑
  Service: 所有业务逻辑, 内部不commit, sync psycopg2
  Engine: 纯计算(无IO无DB), 输入/输出DataFrame/dict
```

## 目录结构

```
quantmind-v2/
├── CLAUDE.md                    ← 本文件
├── SYSTEM_STATUS.md             ← ⭐ 系统现状全景（重构前体检产出）
├── LESSONS_LEARNED.md           ← 经验教训（49条, LL-001~052）
├── FACTOR_TEST_REGISTRY.md      ← 因子测试注册表（74条）
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql  ← ⭐ 建表来源（DDL 47张+代码动态建表26张=DB实际73张, 2026-04-15 S1 audit 实测）
│   ├── QUANTMIND_V2_SYSTEM_BLUEPRINT.md ← ⭐ 唯一设计真相源 (791行, 2026-04-16)
│   ├── IMPLEMENTATION_MASTER.md    ← 已归档至docs/archive/
│   ├── archive/TEAM_CHARTER_V3.3.md ← 团队运营参考（已归档）
│   ├── DEV_BACKEND.md              ← 后端设计(分层/数据流/协同矩阵)
│   ├── DEV_BACKTEST_ENGINE.md      ← 回测引擎(Hybrid架构/34项决策)
│   ├── DEV_FACTOR_MINING.md        ← 因子计算(预处理/IC定义)
│   ├── DEV_FRONTEND_UI.md          ← 前端设计
│   ├── DEV_SCHEDULER.md            ← 调度设计(A股T1-T17/外汇FX1-FX11)
│   ├── DEV_PARAM_CONFIG.md         ← 参数配置(220+可配置参数)
│   ├── DEV_AI_EVOLUTION.md         ← AI闭环设计(4Agent+Pipeline, 0% 实现)
│   ├── DEV_FOREX.md                ← Forex 外汇交易模块设计
│   ├── DEV_NOTIFICATIONS.md        ← 通知系统设计
│   ├── GP_CLOSED_LOOP_DESIGN.md    ← GP最小闭环(FactorDSL+WarmStart)
│   ├── RISK_CONTROL_SERVICE_DESIGN.md ← 风控(L1-L4状态机)
│   └── TUSHARE_DATA_SOURCE_CHECKLIST.md ← ⭐ 数据源接入必读
├── backend/
│   └── app/
│       ├── main.py              # FastAPI入口
│       ├── config.py            # pydantic-settings
│       ├── api/                 # API路由
│       ├── core/                # 核心基础设施
│       │   └── stream_bus.py    # Redis Streams统一数据总线
│       ├── services/            # ⭐ 业务逻辑层（主 sync psycopg2, 遗留 async: mining/backtest_service, S1 audit F18）
│       │   ├── signal_service.py
│       │   ├── execution_service.py
│       │   ├── risk_control_service.py
│       │   ├── factor_onboarding.py  # 因子入库pipeline
│       │   ├── factor_repository.py  # ⭐ Phase C C2 (2026-04-16): 因子计算数据加载层 (load_daily/load_bulk*/load_pead*), Engine 不再读 DB. **load_forward_returns DEPRECATED (Phase D D1 2026-04-16, 走 ic_calculator.compute_forward_excess_returns 铁律 19)**
│       │   ├── factor_compute_service.py  # ⭐ Phase C C3 (2026-04-16): 因子计算编排层 (compute_daily/compute_batch/save_daily), compute_batch 走 DataPipeline 铁律 17 合规
│       │   ├── config_loader.py      # ⭐ Step 4-B: YAML策略配置加载
│       │   ├── pt_data_service.py    # ⭐ Step 6-A: PT并行数据拉取
│       │   ├── pt_monitor_service.py # ⭐ Step 6-A: PT开盘跳空检测
│       │   ├── pt_qmt_state.py       # ⭐ Step 6-A: QMT↔DB状态同步
│       │   ├── shadow_portfolio.py   # ⭐ Step 6-A: LightGBM影子选股
│       │   ├── db.py                 # sync psycopg2连接器
│       │   └── trading_calendar.py   # 交易日工具
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic请求/响应
│       ├── tasks/               # Celery任务
│       │   ├── celery_app (或 __init__.py)
│       │   ├── mining_tasks.py  # GP挖掘Celery封装
│       │   └── beat_schedule.py # 定时调度配置
│       └── data_fetcher/        # 数据拉取
│           ├── contracts.py     # ⭐ Step 3-A: Data Contract (10张表schema+单位)
│           ├── pipeline.py      # ⭐ Step 3-A: DataPipeline统一入库管道(铁律17)
│           ├── tushare_fetcher.py
│           ├── tushare_client.py
│           └── data_loader.py
├── backend/platform/            # ⭐ MVP 1.1-1.3c (2026-04-17/18) Wave 1 完结: Platform SDK 骨架 + concrete 实现
│   ├── __init__.py              #   统一导出 67 符号 (12 Framework 对外 API + 共享类型)
│   ├── _types.py                #   Signal/Order/Verdict/BacktestMode/Severity/ResourceProfile/Priority
│   ├── data/                    #   #1 Data Framework
│   │   ├── interface.py         #     DataSource/DataContract/DataAccessLayer/FactorCacheProtocol (MVP 1.1)
│   │   └── access_layer.py      #     ⭐ MVP 1.2a: PlatformDataAccessLayer (read_factor/ohlc/fundamentals/registry) + DALError
│   ├── factor/                  #   #2 Factor Framework
│   │   ├── interface.py         #     FactorRegistry/OnboardingPipeline/LifecycleMonitor (MVP 1.1, MVP 1.3a 扩展 FactorMeta 18 字段)
│   │   ├── registry.py          #     ⭐ MVP 1.3b+1.3c: DBFactorRegistry full concrete (get_direction + register G9/G10 + get_active + update_status + novelty_check + _default_ast_jaccard)
│   │   └── lifecycle.py         #     ⭐ MVP 1.3c: PlatformLifecycleMonitor (纯规则 copy, 不 import engines, CRITICAL 不落 DB 改 critical_alert 事件)
│   ├── strategy/interface.py    #   #3 Strategy: Strategy(ABC)/Registry/CapitalAllocator
│   ├── signal/interface.py      #   #6 Signal/Exec: SignalPipeline/OrderRouter/AuditTrail
│   ├── backtest/interface.py    #   #5 Backtest: BacktestRunner/Registry/BatchExecutor
│   ├── eval/interface.py        #   #4 Eval: EvaluationPipeline/StrategyEvaluator/GateResult
│   ├── observability/interface.py # #7 Observability: MetricExporter/AlertRouter/EventBus
│   ├── config/                  #   #8 Config Management
│   │   ├── interface.py         #     ConfigSchema/Loader/Auditor/FeatureFlag abstract (MVP 1.1)
│   │   ├── schema.py            #     ⭐ MVP 1.2: 7 Pydantic + RootConfigSchema + PlatformConfigSchema (60+ 字段)
│   │   ├── loader.py            #     ⭐ MVP 1.2: PlatformConfigLoader (env>yaml>default 三层合并)
│   │   ├── auditor.py           #     ⭐ MVP 1.2: PlatformConfigAuditor (check_alignment Schema 驱动 + dump_on_startup) + ConfigDriftError
│   │   └── feature_flag.py      #     ⭐ MVP 1.2: DBFeatureFlag (binary + removal_date 过期守护) + FlagNotFound/Expired
│   ├── ci/interface.py          #   #9 CI/Test: TestRunner/CoverageGate/SmokeTestSuite
│   ├── knowledge/interface.py   #   #10 Knowledge: ExperimentRegistry/FailedDirectionDB/ADRRegistry
│   ├── resource/interface.py    #   #11 Resource (ROF, U6): ResourceManager/AdmissionController/BudgetGuard
│   └── backup/interface.py      #   #12 Backup & DR: BackupManager/DisasterRecoveryRunner
├── backend/migrations/          # ⭐ SQL migration 集中 (MVP 1.2 + 1.3a 新增, 幂等 + rollback 配对)
│   ├── feature_flags.sql        #   MVP 1.2: feature_flags 表 + trigger 维护 updated_at
│   ├── factor_registry_v2.sql   #   MVP 1.3a: ALTER factor_registry ADD pool + ic_decay_ratio + 2 索引
│   └── factor_registry_v2_rollback.sql  # MVP 1.3a emergency rollback
├── backend/data/                # ⭐ Step 5新增: Data层(本地缓存/快照, 无业务逻辑)
│   └── parquet_cache.py         # BacktestDataCache 按年分区Parquet缓存
├── backend/engines/             # ⭐ 核心计算引擎（纯计算无IO）
│   ├── factor_engine/           # ⭐ Phase C C1+C2 (2026-04-16) 拆分: 铁律 31 纯计算分层
│   │   ├── __init__.py          #   shim re-export + compute_*/save_daily_factors (C3 处理)
│   │   ├── _constants.py        #   direction 字典 + FUNDAMENTAL_*_META (pure data)
│   │   ├── calculators.py       #   30 个 calc_* 纯函数 (无 IO, 可单测)
│   │   ├── alpha158.py          #   Alpha158 helpers + wide-format 复合因子
│   │   ├── preprocess.py        #   preprocess_mad/fill/neutralize/zscore/pipeline + calc_ic
│   │   └── pead.py              #   calc_pead_q1_from_announcements (C2 纯化)
│   ├── factor_profiler.py       # 因子画像V2（48+15因子, 12章节报告）
│   ├── fast_neutralize.py       # 批量中性化（Parquet写入, 17.5min/15因子）
│   ├── backtest/                # ⭐ Step 4-A: 回测引擎8模块拆分
│   │   ├── engine.py            #   核心事件循环(562行)
│   │   ├── runner.py            #   run_hybrid_backtest/run_composite_backtest入口(281行)
│   │   ├── broker.py            #   成本模型+SimBroker(309行)
│   │   ├── validators.py        #   涨跌停/停牌/完整性过滤链(105行)
│   │   ├── executor.py          #   事件执行器(81行)
│   │   ├── types.py             #   BacktestResult/Fill/Order数据类(92行)
│   │   └── config.py            #   BacktestConfig(49行)
│   ├── config_guard.py          # 基线配置断言(PT启动前检查)
│   ├── slippage_model.py        # 三因素滑点模型(R4研究)
│   ├── neutralizer.py           # FactorNeutralizer共享模块
│   └── mining/                  # GP因子挖掘子包
│       ├── gp_engine.py         # GP引擎(DEAP+WarmStart+岛屿模型)
│       ├── pipeline_utils.py    # GP管道公开函数
│       ├── factor_dsl.py        # FactorDSL算子集
│       └── pipeline_orchestrator.py  # 闭环编排(部分实现)
├── configs/                     # ⭐ Step 4-B新增: YAML配置
│   ├── pt_live.yaml             # PT生产配置(5因子等权Top-20月度+PMS v1.0)
│   ├── backtest_12yr.yaml       # 12年基线回测
│   └── backtest_5yr.yaml        # 5年回测(历史基线比对用)
├── frontend/src/                # React前端
│   ├── api/                     # API调用层
│   ├── pages/                   # 35个页面
│   ├── components/              # 53个共享组件
│   └── store/                   # Zustand 4个store
├── scripts/
│   ├── run_paper_trading.py     # ⭐ PT主脚本(345行编排器, Step 6-A拆分后)
│   ├── run_backtest.py          # ⭐ 回测脚本(345行, Step 4-B改造为YAML驱动: --config configs/pt_live.yaml)
│   ├── fetch_minute_bars.py     # ⭐ Step 6-B: Baostock 5分钟拉取(走DataPipeline)
│   ├── build_backtest_cache.py  # Step 5: 构建Parquet缓存
│   ├── qmt_data_service.py      # QMT数据同步→Redis(Servy常驻)
│   ├── health_check.py          # 盘前健康检查
│   ├── monitor_factor_ic.py     # 因子IC监控
│   ├── pt_watchdog.py           # PT心跳监控
│   ├── pg_backup.py             # 数据库备份
│   ├── data_quality_check.py    # 数据巡检
│   ├── approve_l4.py            # L4熔断恢复CLI(紧急)
│   ├── cancel_stale_orders.py   # QMT紧急撤单(紧急)
│   ├── registry/                # ⭐ MVP 1.3a+1.3b+1.3c Platform Registry 工具
│   │   ├── backfill_factor_registry.py   # MVP 1.3a: 3 层合并, 回填 287 行 (dry-run 默认)
│   │   ├── audit_direction_conflicts.py  # MVP 1.3b: direction 冲突审计 (dry-run + --apply + --rollback)
│   │   └── register_feature_flags.py     # MVP 1.3c: FeatureFlag 注册/list/disable (use_db_direction=True 已 apply)
│   ├── archive/                 # 126个归档脚本(零生产引用, S1 audit F13 验证可删除)
│   └── research/                # 研究脚本(验证/回测实验)
├── cache/                       # Parquet缓存（profiler/中性化用）
├── docs/research-kb/            # 研究知识库（failed/findings/decisions）
├── .claude/skills/              # 7个自定义skills(factor-discovery/research/overnight/db-safety/performance/research-kb/omc-reference)
└── backend/tests/               # 98 个 test 文件（真实 pytest 通过数待 S4 动态验证填回）
```

## 编码规则（强制）

### Python
- 类型注解 + Google style docstring（中文）
- **sync psycopg2**, Service内部不commit, 调用方管理事务
- Engine层 = 纯计算, 无IO, 无数据库访问
- 金融金额用 `Decimal`
- 提交前: `ruff check` + `ruff format`
- 测试: `pytest`

### React/TypeScript
- 函数组件 + Hooks
- API调用统一通过 `src/api/` 层，**必须做响应格式转换**（LL-035）
- 新组件必须 `?.` null-safe 防御
- 状态管理: Zustand, 异步请求: @tanstack/react-query

### xtquant/miniQMT 规则（清明改造后）

- **唯一允许 `import xtquant` 的生产入口**: `scripts/qmt_data_service.py`（QMT Data Service独立进程）
- **其他模块读QMT数据**: 通过 `QMTClient` (`app/core/qmt_client.py`) 从Redis缓存读取，**不直接import xtquant**
- **路径管理**: 统一使用 `app/core/xtquant_path.py` 的 `ensure_xtquant_path()`
- **降级路径**: QMTClient读Redis超时时可降级直连xtquant（应急通道）
- xtquant安装在 `.venv/Lib/site-packages/Lib/site-packages`，用 `append` 不是 `insert`

### Redis Streams 数据总线规则

- 命名规范: `qm:{domain}:{event_type}`（如 `qm:signal:generated`）
- 发布: `from app.core.stream_bus import get_stream_bus; bus.publish_sync(stream, data, source="module_name")`
- publish失败不阻塞主流程（try/except包裹）
- maxlen=10000，防止Stream无限增长
- 调试: `redis-cli XRANGE qm:signal:generated - + COUNT 5`
- 管理端点: `GET /api/system/streams`

### PMS 阶梯利润保护规则

- 14:30 Celery Beat执行检查（非交易日自动跳过）
- 三层保护: L1(浮盈>30%+回撤>15%), L2(>20%+>12%), L3(>10%+>10%)
- 配置在.env: `PMS_ENABLED`, `PMS_LEVEL{1,2,3}_GAIN`, `PMS_LEVEL{1,2,3}_DRAWDOWN`
- PMS卖出后自动更新`position_snapshot`，确保信号生成看到最新持仓
- 触发记录写`position_monitor`表，通过StreamBus广播`qm:pms:protection_triggered`
- 前端页面: `/pms`

### 部署规则（Servy服务管理）
- **服务管理工具**: Servy v7.6 (`D:\tools\Servy\servy-cli.exe`)，替代NSSM（2026-04-04迁移）
- 后端代码修改后重启: `powershell -File scripts\service_manager.ps1 restart fastapi`
- 重启所有服务: `powershell -File scripts\service_manager.ps1 restart all`
- 查看服务状态: `powershell -File scripts\service_manager.ps1 status`
- 前端代码修改后: `npm run build`（生产模式）或确认dev server自动热更新
- 开发调试时可手动启动: `cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- 调试前需先停止Servy服务: `D:\tools\Servy\servy-cli.exe stop --name="QuantMind-FastAPI"`，避免端口冲突
- **Celery Worker graceful shutdown需要30秒，不要强制kill**

#### Servy管理的服务（启动顺序）
| 服务名 | 描述 | 依赖 | 日志 |
|--------|------|------|------|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | Redis, PostgreSQL 16.8 | logs/fastapi-std{out,err}.log |
| QuantMind-Celery | celery worker --pool=solo | Redis | logs/celery-std{out,err}.log |
| QuantMind-CeleryBeat | celery beat scheduler | Redis, QuantMind-Celery | logs/celery-beat-std{out,err}.log |
| QuantMind-QMTData | QMT数据同步→Redis缓存(60s) | Redis | logs/qmt-data-std{out,err}.log |

#### QMT数据架构（A-lite方案, 2026-04-04）
- **QMT Data Service** (`scripts/qmt_data_service.py`): 独立常驻进程，唯一允许 `import xtquant` 的生产入口
- 每60秒同步: 持仓→`portfolio:current` (Hash), 资产→`portfolio:nav` (JSON), 价格→`market:latest:{code}` (TTL=90s)
- 其他模块通过 `QMTClient` (`app/core/qmt_client.py`) 读取Redis缓存，**不直接import xtquant**
- xtquant路径统一管理: `app/core/xtquant_path.py` 的 `ensure_xtquant_path()`
- 连接状态通过StreamBus广播 `qm:qmt:status`

#### PT核心参数（.env驱动）
- `PT_TOP_N`: 选股数量（默认20, 改后重启服务生效）
- `PT_INDUSTRY_CAP`: 行业上限（默认1.0=不限, 改后重启服务生效）
- 读取路径: `.env` → `config.py:Settings` → `signal_engine.py:PAPER_TRADING_CONFIG`
- config_guard验证因子列表一致性（不验证top_n/industry_cap，因为是可配置的）

#### 回滚到NSSM（紧急）
NSSM配置备份在 `config/nssm-backup/`，包含注册表导出文件(.reg)和审计文档。

### 并发限制（32GB内存硬约束，2026-04-03 OOM事件）
- **最多同时运行2个**加载全量价格数据的Python进程
- 每个进程估计占用3-4GB内存（加载7M行price_data）
- PG shared_buffers=2GB是固定开销
- 违反此规则会导致PG OOM崩溃（Windows error 1455 + postgres.exe 0xc0000409）
- 因子计算、回测等重数据任务必须串行或最多2并发
- 轻量任务（API测试、IC计算等<500MB）不受此限制
- PG安装路径: `D:\pgsql\bin\pg_ctl.exe`, 数据目录: `D:\pgdata16`, db=quantmind_v2

### SQL
- SQLAlchemy text() 中用 `CAST(:param AS type)`，**禁止** `::type` 语法（LL-034）
- 所有 (symbol_id, date) 组合必须有联合索引
- 金额字段列注释标明单位

### 研究任务资源调度
- 启动前检查: `tasklist | grep python` + `nvidia-smi` (Windows)
- CPU密集(回测/IC): RAM可用<8GB时不启动新重型任务
- GPU任务(LightGBM/PyTorch): VRAM可用<4GB时不启动
- DB密集(大表SELECT): 同时最多1个(PG连接池限制)
- 32GB机器禁止同时跑两个>4GB的Python进程
- 铁律9: 重数据max 2并发

---

## 铁律（违反即停, 40 条全局原则, v2 2026-04-17）

> **全局性要求**: 每条铁律必须是"永恒原则", 而不是"某阶段后失效"的临时规则.
> **测试**: 10 年后此条仍成立? "是, 只是实现方式变了" → 保留. "否, 某阶段后不适用" → 不该是铁律 (应入 Blueprint).
>
> **历史编号保持不变** (防止其他文档引用漂移). 合并/删除条目以 DEPRECATED 占位保留.

### 工作原则类
1. **不靠猜测做技术判断** — 外部API/数据接口必须先读官方文档确认
2. **[DEPRECATED, 合并入 25]** ~~下结论前验代码~~ — 已并入铁律 25 的作用域定义
3. **不自行决定范围外改动** — 先报告建议和理由，等确认后再执行

### 因子研究类
4. **因子验证用生产基线+中性化** — raw IC和neutralized IC并列展示，衰减>50%标记虚假alpha（LL-013/014）
5. **因子入组合前回测验证** — paired bootstrap p<0.05 vs 基线，不是只看Sharpe数字（LL-017）
6. **因子评估前确定匹配策略** — RANKING→月度，FAST_RANKING→周度，EVENT→触发式，不能用错框架评估（LL-027）

### 数据与回测类
7. **IC/回测前确认数据地基** — universe与回测对齐+无前瞻偏差+数据质量检查（IC偏差教训）
8. **任何策略改动必须OOS验证** — ML训练/验证/测试三段分离; 非ML策略/因子/参数改动必须walk-forward或时间序列holdout, paired bootstrap p<0.05硬门槛。IS(in-sample)好看不算证据。违反→"IS强OOS崩"反复发生 (详细教训见 `LESSONS_LEARNED.md`).

### 系统安全类
9. **所有资源密集任务必须经资源仲裁** — 全局原则: 禁止裸并发消耗共享资源 (RAM/GPU/DB连接/API quota). 实现方式 (ROF Framework #11 或人工判断) 是实施细节. 当前环境约束: 32GB RAM → 重数据 Python 进程 max 2 并发. 违反→PG OOM崩溃（2026-04-03事件）
10. **基础设施改动后全链路验证** — PASS才能上线，不跳过验证直接部署（清明改造教训）
11. **IC必须有可追溯的入库记录** — factor_ic_history表无记录的IC视为不存在，不可用于决策（mf_divergence"IC=9.1%"实为-2.27%教训）

### 因子质量类
12. **新颖性可证明性（G9 Gate）** — 新候选因子与现有因子AST相似度>0.7直接拒绝，不进入IC评估。未经新颖性验证的因子视为变体（AlphaAgent KDD 2025：无此Gate有效因子比例低81%）
    > 补充: 相似因子不是新因子。GP/LLM产出的候选因子IC计算前必须先过G9 Gate，48个量价因子的窗口变体不算新因子。
13. **市场逻辑可解释性（G10 Gate）** — 新因子注册必须附带经济机制描述「[市场行为]→[因子信号]→[预测方向]」。IC显著不是充分理由，无法解释预测力来源的因子不允许进入Active池（reversal_20在momentum regime下反转的教训）
    > 补充: 新因子必须有可解释的市场逻辑假设, 不接受"IC显著就行"。经济机制假设必须与因子表达式语义对齐。

### 重构原则类（Step 6-B, 2026-04-09）
14. **回测引擎不做数据清洗** — 数据必须在入库时通过 DataPipeline 验证和标准化。回测引擎不猜单位、不推断ST、不计算adj_close。DataFeed 提供什么就用什么。违反→数据契约被冲破，回测不可复现。
15. **任何回测结果必须可复现** — 每次回测必须记录 `(config_yaml_hash, git_commit)` 到 backtest_run 表。`regression_test.py` 能验证同一输入产出完全相同的 NAV (max_diff=0)。违反→策略迭代失去基准比对能力。
16. **信号路径唯一且契约化** — 全局原则: 生产/回测/研究必走**同一信号路径契约**, 禁止绕路的简化信号/回测代码. 具体路径随策略架构演进 (当前单策略: SignalComposer → PortfolioBuilder → BacktestEngine; 未来多策略: Strategy → SignalPipeline → OrderRouter). 违反→PT 与回测结果不一致 (原历史问题: `load_factor_values`/`vectorized_signal` 各读各的字段).
17. **数据入库必须通过 DataPipeline** — 禁止直接 `INSERT INTO` 生产表。`DataPipeline.ingest(df, Contract)` 负责 rename → 列对齐 → 单位转换 → 值域验证 → FK 过滤 → Upsert。违反→重新引入单位混乱/code 格式不一致等历史技术债。

### 成本对齐
18. **回测成本实现必须与实盘对齐** — 新策略正式评估前必须确认 H0 验证通过 (理论成本 vs QMT 实盘误差 <5bps). **周期性复核**: 每季度重跑 H0 验证 (成本会 drift: 券商费率 / 印花税调整 / 滑点模型失效), 误差 >5bps 需重新校准 + 全部现有回测重跑. 违反→成本失真导致策略 sim-to-real gap.

### IC 口径统一（Step 6-E, 2026-04-09）
19. **IC 定义全项目统一** — 所有 IC 计算必须走 `backend/engines/ic_calculator.py` 共享模块:
    - 因子值: `neutral_value` (MAD → fill → WLS 行业+ln市值 → zscore → clip±3)
    - 前瞻收益: T+1 买入到 T+horizon 卖出的**超额收益** (相对 CSI300)
    - IC 类型: Spearman Rank IC
    - Universe: 排除 ST/BJ/停牌/新股 (调用方负责 filter)
    - 标识符: `neutral_value_T1_excess_spearman` (version 1.0.0)

    **raw_value 的 IC 只作参考对比, 不作入池/淘汰依据**。未经 `ic_calculator` 计算的 IC 数字视为不可追溯, 不允许写入 factor_ic_history / factor_profile / factor_registry 作决策依据。违反→口径漂移 (IVOL 在 registry 写+0.067, 实测 -0.103 反向) 重新出现。

### 因子噪声鲁棒性（Step 6-F, 2026-04-10）
20. **因子噪声鲁棒性 G_robust** — 新候选因子必须通过噪声鲁棒性测试:
    - 方法: 对截面因子值加 N(0, σ) 高斯噪声, σ = noise_pct × cross_section_std
    - 重算 IC, 计算 retention = |noisy_IC| / |clean_IC|
    - **5% 噪声 retention < 0.95**: 警告 (信号质量下降)
    - **20% 噪声 retention < 0.50**: 标记 fragile, 不得进入 Active 池
    - 工具: `scripts/research/noise_robustness.py --noise-pct 0.20`
    - 实证: 21 个 PASS 因子在 5% 噪声下 retention 全部 ≥ 0.94 (无 fragile),
      在 20% 噪声下 retention 仍全部 ≥ 0.59 (最弱: nb_new_entry 0.591). CORE 5 因子全部稳健 (retention ≥ 0.96 @ 20%)

### 工程纪律类（Step 6-H后, 2026-04-10）
21. **先搜索开源方案再自建** — 任何新功能开发前先花半天搜索成熟开源实现（Qlib/RD-Agent/alphalens等）。自建引擎90%功能已被Qlib覆盖的教训。违反→重复造轮子浪费数月。
22. **文档跟随代码** — 全局原则: 代码变更必须同步受影响文档 (CLAUDE.md / SYSTEM_STATUS.md / DEV_*.md / Blueprint). 具体要求: (a) 代码 PR 必须同时更新, 或在 commit message 声明 `NO_DOC_IMPACT`; (b) 引用已删除文件/函数/表的链接必须在同一次 commit 修复; (c) 数字类声明 (行数/测试数/表数) 变更时同步更新. 执行机制: CI 强制 (未来) + 人工自律 (现在). 违反→文档与代码不一致导致错误决策 (5yr/12yr Sharpe 混淆 + S1 审计 10+ 条文档腐烂).
23. **每个任务独立可执行** — 不允许任务依赖未实现的模块。如果存在依赖，先实现依赖或拆分为独立可执行的子任务。违反→依赖死锁导致整个功能链条卡住（11份设计文档80%未实现的根因）。
24. **设计文档必须按抽象层级聚焦** — 全局原则: 单个设计文档只覆盖一个抽象层级, 不同层级不混在一个文档. 层级规模经验 (非硬门, 但超出需警觉): MVP 级 ≤ 2 页 / Framework 级 ≤ 5 页 / Platform Blueprint 不限页数但必须含 TOC + 章节索引 + Quickstart ≤ 2 页. 每个设计必须含验收标准. 违反→过度设计无法落地 (DEV_AI_EVOLUTION 705 行 0% 实现教训).

### CC执行纪律类
25. **代码变更前必读当前代码验证 (含铁律 2 合并)** — 全局原则: 任何修改/新建/删除代码的操作前, 必须读目标代码的**当前实际内容** (文件路径+行号+实际内容), 不依赖记忆或文档. 关键 claim (引用具体行数/语义) 决策前至少 1 次代码验证. 架构讨论可凭 Blueprint+memory 推理, 但做出**代码变更决策**前仍须验证. 违反→基于过期记忆改代码 (LL-019 + 本 session 多次自报"3085 行" 实际 1218 行的教训).
26. **验证不可跳过不可敷衍** — 验证=读完整代码+理解上下文+交叉对比+明确结论, 跳过=任务失败. 违反→P0 SN未生效就是验证缺失的直接后果.
27. **结论必须明确（✅/❌/⚠️）不准模糊** — 不接受"大概没问题""应该是对的". 违反→模糊结论掩盖真实问题.
28. **发现即报告不选择性遗漏** — 执行中发现的任何异常不管是否在任务范围内都必须报告. 违反→问题被发现又被埋没.

### 数据完整性类（P0-4, 2026-04-12）
29. **禁止写 float NaN 到 DB** — 所有写入 factor_values 的代码必须将 NaN 转为 None (SQL NULL)。float NaN 在 PostgreSQL NUMERIC 列中不等于 NULL，导致 `COALESCE(neutral_value, raw_value)` 返回 NaN 而非回退到 raw_value。违反→因子数据静默损坏（RSQR_20事件: 11.5M行NaN未被发现）。
    > 验证工具: `python scripts/factor_health_check.py <factor_name>`
30. **缓存一致性必须保证** — 全局原则: 源数据 (DB factor_values / klines_daily / 其他) 变更后, 下游所有缓存 (Parquet / Redis / 内存) 必须在**下一个交易日内生效**, 否则视为数据过期. 实现路径 (DAL Cache Coherency Protocol 自动 / 手动 `build_backtest_cache.py` 重建) 是细节, 原则是"缓存不得与源脱节". 违反→回测使用旧数据 (Phase 1.2 SW1迁移后缓存过期2天未发现).
    > 入库体系文档: `docs/FACTOR_ONBOARDING_SYSTEM.md`

### 工程基础设施类（S1-S4 审计沉淀, 2026-04-15）

> 这 5 条铁律是 S1-S4 审计 54 条 findings 里 P0/P1 集中爆发的根因抽象。前 30 条铁律主要由因子研究教训驱动, 基础设施类教训欠账在 S 轮补齐 (铁律总数 30→35)。**2026-04-17 v2 扩展**: 加实施者纪律类 4 条 (36-39) + 补漏 2 条 (40-41), 总数 35→40. 另铁律 2 DEPRECATED 合并入 25.

31. **Engine 层纯计算** — `backend/engines/**` 下所有模块不允许读写 DB, 不允许 HTTP/Redis 调用, 不允许读写本地文件（Parquet 缓存除外）。输入/输出必须是 DataFrame/dict/原生 Python 类型。数据必须在入库时通过 DataPipeline 验证和标准化, Engine 只负责纯计算。违反→分层崩塌, 纯计算与 IO 耦合导致无法单测 + 重构不敢动（F31 factor_engine.py 2034 行教训 + 审计 F43 配套问题）。
    > **Phase C C1+C2+C3 全部完成 (2026-04-16)**: `backend/engines/factor_engine.py` → `backend/engines/factor_engine/` package. C1: 30 个 calc_* 纯函数迁至 `calculators.py`, preprocess 管道迁至 `preprocess.py`, Alpha158 helpers 迁至 `alpha158.py`, direction/metadata 迁至 `_constants.py`. C2: load_* 8 个数据加载函数搬家到 `backend/app/services/factor_repository.py`, calc_pead_q1 拆为 `factor_repository.load_pead_announcements` (DB) + `factor_engine/pead.calc_pead_q1_from_announcements` (纯函数). **C3: `save_daily_factors` / `compute_daily_factors` / `compute_batch_factors` 搬家到 `backend/app/services/factor_compute_service.py`, compute_batch_factors 内部原 `execute_values(INSERT INTO factor_values)` + `conn.commit()` 改走 `DataPipeline.ingest(FACTOR_VALUES)`, 关闭 F86 最后一条 factor_engine known_debt (铁律 17), `check_insert_bypass --baseline` 从 3→2**. `__init__.py` 从 2049 → 416 行 (−80%), 25 个调用方零改动. 见 docs/audit/PHASE_C_F31_PREP.md.
    > 铁律 14 "回测引擎不做数据清洗" 是本条在回测引擎维度的特例, 本条覆盖所有 Engine 模块。

32. **Service 不 commit** — Service 层所有函数不允许调用 `conn.commit()` / `cur.execute("COMMIT")`。事务边界由调用方（Router / Celery task）管理。Service 发现错误必须 raise, 由调用方决定 rollback 或 retry。违反→事务边界错乱, partial write 风险 + 失败后 DB 状态不可预测（F16 Service 层 20+ 处违规, 等着 partial write 事故）。
    > 检测: `grep -rn "\.commit()" backend/app/services/ | grep -v test_`

33. **禁止 silent failure** — 所有 `except Exception: pass` / `except Exception: return default` 必须满足:
    - (a) 日志层面: `logger.error(...)` 或 `logger.warning(..., exc_info=True)`, 不允许裸 `pass`
    - (b) 生产链路（PT 执行 / 数据入库 / 信号生成 / 风控）: **fail-safe**（拒绝动作, 如 F76 无 tick 就拒单）或 **fail-loud**（raise）, 禁止静默返回 default
    - (c) 读路径 API fallback 允许, 但必须有 `logger.warning`
    - (d) 静默 pass 必须附 `# silent_ok: <具体原因>` 注释, 说明为什么吃掉异常是安全的
    违反→可观测性崩塌, 生产事故根因无法追溯（F76 涨停保护可能 silently bypass / F77 撤单查询失败被归类成超时 / F78-F81 共 6 处 silent swallow 教训）。

34. **配置 single source of truth** — 每个可配置参数（SN_beta / top_n / industry_cap / factor_list / rebalance_freq / commission / slippage_model）必须有唯一权威来源, 其他地方只能读不能独立设置默认值。`config_guard` 启动时必须检查 `.env` + `configs/pt_live.yaml` + Python 常量（如 `signal_engine.PAPER_TRADING_CONFIG`）三处对齐, 不一致必须 RAISE, **不允许只报 warning**。违反→配置漂移静默降级（F45 config_guard 缺检查 / F62 SN default=0.0 / F40 SignalConfig 默认漂移 教训）。
    > 扩展: 铁律 15 "回测可复现" 是本条在回测维度的对偶, 本条覆盖 PT 生产配置。
    > **已落地 (2026-04-15 Phase B M3)**: `backend/engines/config_guard.py::check_config_alignment()` + `ConfigDriftError` 硬校验 6 参数 (top_n / industry_cap / size_neutral_beta / turnover_cap / rebalance_freq / factor_list), PT 启动 (`run_paper_trading.py` Step 0.5) + `health_check.py` 双路径集成, 24 单测 + 5 把尺子全绿. F45 关闭.

35. **Secrets 环境变量唯一** — 源码禁止出现 API key / 数据库密码 / token 的 fallback 默认值（包括占位符、弱密码、测试值、注释掉的旧值）。必须 `os.environ.get + 未设置 raise`。`.env` 禁止提交（`.gitignore` 必须包含）。定期 `git log -p | grep -iE "key|token|password|secret"` 扫描历史泄漏, 发现必须 rotate。违反→秘密泄漏用户需 rotate 所有 key + 历史 commit 永久污染（F32 API token 源码泄漏 5 处 + F15/F65 硬编码 DB 密码 教训）。

### 实施者纪律类（2026-04-17 新增, 给自己定下的全局规则）

36. **代码变更前必核 precondition** — 全局原则: 所有代码变更前必显式核对 3 项: (a) 依赖模块已交付 (不是"有设计"); (b) 老路径保留 + regression 锚点在 (max_diff=0); (c) 测试/验证数据可获得. 任一 failed → 拆分任务 / 补依赖 / 回滚, 不硬上. 违反→依赖链整体崩 (11 份设计文档 80% 未实现的根因).

37. **Session 关闭前必写 handoff** — 全局原则: 每个 session 关闭前必更新 `memory/project_sprint_state.md` 顶部, 记录: 已完成 / 未完成 / 下 session 入口 / Git 状态 (commits ahead + working tree 状态) / 阻塞项 / 待决策. 违反→跨 session 工作凭空消失, 后续 session 无法恢复上下文.

38. **Platform Blueprint 是唯一长期架构记忆** — 全局原则: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (QPB) 是跨 session 的架构真相源. (a) 任何违反 Blueprint 的实施决策 → 先写 ADR (入 Blueprint Part X 或 `docs/adr/`), 再执行; (b) 新 Session 开始必读: Blueprint Part 0 + 当前 Sprint 对应 Part 4 MVP + `memory/project_sprint_state.md`; (c) 每 Wave 完成必 bump version + 回填实际 vs 预期差异. Blueprint 过时即事故源. 违反→跨 session 实施漂移, 后 session 看不见前 session 判断.

39. **双模式思维 — 架构/实施切换必须显式声明** — 全局原则: 工作分两种模式, 心态不同:
    - **架构模式** (设计/评估/推理): 允许基于 Blueprint + memory + 综合判断, 不强制每句话 grep. 决策**关键 claim** 前验证 1 次 (铁律 25 的最小粒度).
    - **实施模式** (代码变更): 100% 遵守铁律 25, 改什么就读什么.
    - 切换模式时必须显式声明 (如: "进入实施模式, 开始修改 X 文件").
    违反→架构时陷入冗余 grep 秀 / 实施时凭印象改代码 (本 session 多次靠记忆说"3085 行"实际 1218 行的教训).

40. **测试债务不得增长** — 全局原则: 新代码变更不能让 `pytest` fail 数增加. 历史 fail (如当前 32 DEPRECATED 路径遗留) 允许暂不修, 但**新增 fail 禁止合入**. 每次 pre-push 前必 diff `pytest` 结果, fail 数 ↑ 则阻断. 违反→测试债务无底线累积 (S4 审计 32 fail 全是"历史债", 再累积会吞噬核心路径信心).

41. **时间与时区统一** — 全局原则:
    - 所有 timestamp **内部存储必须 UTC**, 展示层再转 Asia/Shanghai
    - 所有 timestamp 必须带 timezone, 禁止 naive datetime
    - 交易日判断必须走 `TradingDayProvider` (或 `trading_calendar` 统一接口), 禁止散落 `date` 字符串比较
    - 日期常量定义必须标注是**自然日**还是**交易日**
    - 测试中 `freeze_time` 必须用 UTC 值
    违反→Phase 2.1 sim-to-real gap 根因之一 + timezone bug 反复踩 (如 T+1 判定错在 UTC/CST 切换日).

## 因子审批硬标准

- t > 2.5 硬性下限（Harvey Liu Zhu 2016）
- BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数（当前M=84，87条-2 CANCELLED #70/#72 - 1重复 #65 = 84）
- 与现有Active因子 corr < 0.7, 选股月收益 corr < 0.3
- 中性化后IC必须验证（原始IC和中性化IC并列展示）
- 因子预处理顺序: **去极值(MAD 5σ) → 填充(行业中位数) → 中性化(行业+市值WLS) → z-score**（不可变）

## 因子画像评估协议（Factor Profiler V2, 2026-04-05）

1. **模板推荐须经多维度验证** — IC显著性+衰减速率+单调性+成本可行性+冗余性五维联合判定，不可单凭IC选模板
2. **Regime切换仅限方向反转** — `sign(ic_bull) ≠ sign(ic_bear)` 才推荐模板12，幅度差异（regime_sensitivity>0.03但同方向）不构成regime切换理由
3. **成本可行性一票否决高频** — `annual_cost > estimated_alpha × 0.5` 的因子不可作为独立策略的主因子，只能作为ML特征或Modifier输入
4. **冗余因子标记不可绕过** — `|corr| > 0.85` 的因子对中，IC较低者标记 `keep_recommendation=drop`，不得同时进入Active组合（镜像对corr<-0.85取绝对值后同理）
5. **FMP候选须经聚类验证** — 独立组合候选因子必须满足与所有其他聚类代表 `|corr| < 0.3`，不可凭主观判断跳过相关性检查

## 性能规范

| 优化项 | 基线 | 优化后 | 方法 |
|--------|------|--------|------|
| 数据加载(`_load_shared_data`) | 30min(DB) | 1.6s | Parquet缓存, 按日期分区 |
| 因子中性化 | 慢(逐因子DB读写) | 15因子/17.5min | `fast_neutralize_batch` Parquet批量 |
| GPU矩阵运算 | CPU numpy | 6.2x加速(5000×5000 matmul) | PyTorch cu128, RTX 5070 12GB |
| Pipeline Step1 | 串行拉取 | 三API并行 | klines+daily_basic+moneyflow并行 |
| 时间范围查询 | 全表扫描 | chunk exclusion | TimescaleDB hypertable自动分区 |
| 回测Phase A信号生成 | 841s(12yr) | ~15s | groupby预索引+bisect O(logN)替代O(N×M)全表扫描 |

- **Parquet缓存路径**: 本地快照, 按日期分区, `_load_shared_data`自动检测缓存有效性
- **cupy**: 不支持Blackwell架构(sm_120), 暂不可用, 用PyTorch替代
- **分钟数据**: Baostock 5min全A股x5年, 本地Parquet分片存储

## 已知失败方向（不可重复）

| 方向 | 结论 | 来源 |
|------|------|------|
| 风险平价/最小方差权重 | 等权最优, 降风险=降Alpha(小盘暴露) | G2 7组实验 |
| 动态仓位(20d momentum) | 新基线上无效 | G2.5 3组实验 |
| 双周调仓 | Sharpe 0.91→0.73 | G2实验 |
| 基本面因子(等权框架) | 10种方式8 FAIL | Sprint 1.5 |
| 量价因子窗口变体 | IC天花板0.05-0.06, 边际收益极低 | 暴力枚举Layer 1-2 |
| PMS v2.0组合级保护 | p=0.655等于随机, 2022慢熊0触发 | v3.6验证 |
| LLM自由生成因子 | IC=0.006-0.008, 需数据驱动prompt | 5次测试 |
| mf_divergence独立策略 | IC=-2.27%(非9.1%), 14组回测全负 | GA2证伪 |
| 同因子换ML模型 | ML Sharpe=0.68 vs 等权0.83, 瓶颈在数据维度 | G1 LightGBM |
| LightGBM 17因子WF | OOS IC=0.067正但弱, 月度回测Sharpe=0.09, 再次确认ML无效 | Step 6-H |
| IC加权/Lasso等下游优化 | 因子信息量不够时优化下游无效, IC_IR加权Sharpe=0.27(等权0.62), turnover权重最大放大流动性风险 | v3.5原则16 + Phase 2.2 |
| MVO(riskfolio-lib) | 40股×60日协方差不稳定, 94%失败率fallback等权, Sharpe=0.26 | Phase 2.2 |
| LambdaRank替代regression | 排名优化Sharpe=0.56+SN(>regression 0.44)但仍<等权0.62, 方向正确但增量不足 | Phase 2.2 |
| Regime动态beta(RSV) | static b=0.50 Sharpe=0.6287 > dynamic 0.5253 > binary 0.5669 | Step 6-H |
| Vol-targeting/DD-aware | 无改善或更差, Partial SN是唯一有效Modifier | Step 6-G |
| 完全Size-neutral(b=1.0) | 损11% Sharpe, 过度惩罚小盘暴露 | Step 6-F |
| 因子替换turnover_stability_20 | paired bootstrap p=0.92不显著, 非真alpha | Step 6-F |
| Regime线性检测(5指标) | 5指标全p>0.05, 线性方法无法捕捉regime | Step 6-E |
| 组合Modifier(Vol+DD叠加) | 叠加更差, Modifier相互干扰 | Step 6-G |
| RD-Agent集成 | Docker硬依赖+Windows bug+Claude不支持, 三重阻断 | 阶段0调研(2026-04-10) |
| Qlib数据层/回测引擎迁移 | .bin格式需双份数据, 回测无PMS/涨跌停/历史税率, 迁移=倒退 | 阶段0调研(2026-04-10) |
| predict-then-optimize两阶段独立策略 | IC正但Sharpe≈0: 问题在portfolio构建层(排名→Top-N等权丢失alpha)不在预测层; LightGBM预测能力保留为融合系统层1 | G1+Step 6-H两次验证 |
| E2E可微Sharpe Portfolio优化 | val_sharpe=1.26但实盘Sharpe=-0.99, sim-to-real gap 282%. A股交易成本(min佣金¥5/印花税/滑点/隔夜跳空)不可微分 | Phase 2.1 Layer2 |
| 增加因子提升LightGBM IC | Exp-A(+QTLU+RSQR)=零增量, Exp-B(+11因子)IC从0.09降到0.069(-25%). CORE5是IC天花板 | Phase 2.1 Exp-A/B |
| 完美预测+MVO vs 等权 | 完美预测下MVO=等权(Sharpe均3.02), portfolio优化在预测完美时无增量 | Phase 2.1 A.8 |
| Universe filter替代SN | Alpha 100%微盘, 非微盘区间Sharpe全部≈0或为负, 收窄universe毁灭alpha | Phase 2.4 Part 1 |
| LambdaRank作为等权因子 | CORE5+LR+SN Sharpe=0.48(-27%), LR信号与等权CORE5冲突 | Phase 2.4 Part 2.5 |
| RSQR_20/QTLU_20单独加CORE5 | 零增量(Sharpe=0.6652不变), 中性化后截面信息被消除 | Phase 2.4 Part 2.2 |
| RSQR_20加入CORE3+dv | 有害(-0.089 Sharpe), direction=-1与正IC冲突. CORE3+dv=1.03 > CORE3+RSQR+dv=0.95 | P0-3 re-evaluation |
| 第5因子加入CORE3+dv_ttm | 8个P1候选全FAIL: 最佳price_volume_corr_20 OOS=0.7737(-0.092), 最差rsrs_raw_18=0.5993(-0.267). 加第5因子稀释信号质量, 4因子=等权上限 | Phase 3B WF (2026-04-13) |
| Phase 3D LightGBM ML Synthesis | 4实验全FAIL: A-REG(11因子)=0.54最优, B-REG(33因子)=0.30, A-LR=0.14~0.28不可复现, B-LR=0.04. 全部大幅落后基线0.87. 更多因子=更差. ML仅学CORE4非线性变体,无新alpha. **ML预测层CLOSED** | Phase 3D (2026-04-14) |
| Phase 3E微结构因子等权加入 | 17因子IC筛选16/17 PASS, 噪声16/16 ROBUST, CORE4相关性全独立. 但WF 0/6 PASS: 最佳+vol_autocorr(0.5755,-0.034), 最差+skewness(0.4115,-0.198). 真alpha但等权框架无法利用, 4因子=等权上限(与Phase 3B一致) | Phase 3E-II (2026-04-15) |

## 策略配置（CORE3+dv_ttm WF PASS, PT配置已更新 2026-04-12）
# 基线演进: 1.24(虚高)→0.94(Phase 1加固)→0.6095(5yr regression)→0.5309(12yr)→0.6521(SN WF OOS)→**0.8659(CORE3+dv_ttm WF OOS)**
# 配置来源: configs/pt_live.yaml (Step 4-B, 铁律15要求YAML驱动)
# 回测入口: python scripts/run_backtest.py --config configs/pt_live.yaml

```
因子: turnover_mean_20(-1) / volatility_20(-1) / bp_ratio(+1) / dv_ttm(+1)  [CORE3+dv_ttm, 2026-04-12 WF PASS]
合成: 等权平均
选股: Top 20 (PT_TOP_N=20)
调仓: 月度（月末最后交易日）
Modifier: Partial Size-Neutral b=0.50 (adj_score = score - 0.50*zscore(ln_mcap), Step 6-H验证, .env PT_SIZE_NEUTRAL_BETA=0.50)
约束: 行业上限=无(PT_INDUSTRY_CAP=1.0), 换手率上限 50%, 100股整手(floor), 日均成交额≥5000万(20日均)
排除: 北交所BJ股 + ST + 停牌 + 新股(list<60天)

基线历史演进:
  旧值1: 5年回测, Sharpe=0.91, Top-15+行业25%, WLS+volume_impact无流动性过滤, MDD=-43.03%
  旧值2(Phase 1加固, 5年): Sharpe=0.94, 年化22.57%, MDD=-40.77%, Calmar=0.55, Sortino=1.19, IR=1.09
    - Phase 1修复(2026-04-07): 印花税历史税率(2023前0.1%)+overnight_gap三因素+z-score clip±3+DataFeed校验
    - 1.24→0.94, 旧值因缺印花税历史税率+缺overnight_gap而虚高
  5年基线(`regression_test.py`, 2021-01~2025-12): Sharpe=0.6095, MDD=-50.75%, 1212天
    - 来源: cache/baseline/nav_5yr.parquet + metrics_5yr.json
    - 用途: CI回归固定锚点, max_diff=0 验收铁律15可复现
  12年真实基线(Phase B M2 重建, 2014-01~2026-04-14): **Sharpe=0.3594, MDD=-63.44%**, 2984天
    - 来源: cache/baseline/{nav_12yr,metrics_12yr,factor_data_12yr,price_data_12yr,benchmark_12yr}.parquet
    - Phase B M2 (2026-04-15) bootstrap: build_12yr_baseline.py 首次保存 aggregated 输入 parquets, regression_test --years 12 可复现验证 max_diff=0
    - 年化6.28%, 总收益110.59%, NAV 1M→2.11M, 3947 trades
    - **⚠️ 历史值漂移**: Step 6-D (2026-04-09) 首跑时记录 Sharpe=0.5309 / MDD=-56.37% / Annual 13.06% / Total 347.9% / 4617 trades (来自当时的 cache/backtest/* 快照)
    - **漂移原因**: cache/backtest/YEAR/*.parquet 于 2026-04-15 15:20 被 build_backtest_cache.py 重建 (F66 NaN 清理后 + 新增数据增量), Step 6-D 时代的 cache 已被覆盖不可复现. 这不是代码 bug, 是数据快照漂移: 5yr 用独立冻结的 factor_data_5yr.parquet 未动 (max_diff=0), 12yr 以前每次从 cache/backtest/* 重读所以漂移. M2 保存 factor_data_12yr.parquet 等 aggregated 快照后已修复此缺口.
    - WF 5-fold OOS (仅覆盖 2021-02~2026-04): chain-link Sharpe=0.6336, std=1.52 UNSTABLE (历史值, 未随 M2 重算)
    - 结论: regime-dependent, 小盘牛/熊市杀, 非alpha强策略 (FF3归因见 cache/baseline/ff3_attribution.json)
  SN b=0.50 inner (Step 6-H, 2014-01~2026-04): **Sharpe=0.68, MDD=-39.35%**
    - 来源: cache/baseline/wf_sn050_result.json
    - WF 5-fold OOS: Sharpe=0.6521, MDD=-30.23% (优于base 0.6336/-45.7%)
    - 唯一有效Modifier, PT已激活 (pt_live.yaml size_neutral_beta=0.50)

成本: 佣金万0.854(国金实际, min 5元) + 印花税(2023-08-28前0.1%,后0.05%) + 过户费0.001% + 三因素滑点(spread+impact+overnight_gap)
```

**因子健康状态（2026-04-12 PT配置更新后）:**
- turnover_mean_20: ✅ active (IC=-0.091, direction=-1)
- volatility_20: ✅ active (IC=-0.114, direction=-1)
- bp_ratio: ✅ active (IC=+0.107, direction=+1)
- dv_ttm: ✅ **NEW active** (股息率, direction=+1, DB 11.7M行, neutral_value 11.6M有效)
- amihud_20: 降级→CORE5基线保留 (仍在factor_values, 不参与PT信号)
- reversal_20: 降级→CORE5基线保留 (IC方向反转问题, 不参与PT信号)

**PT状态**: 已暂停+已清仓 (2026-04-10), **配置已更新为CORE3+dv_ttm** (2026-04-12)。WF OOS Sharpe=0.8659 > 基线0.6521 ✅, MDD=-13.91% < 40% ✅。重启前: health_check + regression_test + 首日dry-run确认。

## 文档查阅索引

| 你要做什么 | 读这个 |
|-----------|--------|
| **系统总设计/架构全景** | **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md** ⭐ (唯一设计真相源, 791行, 16章节) |
| **平台化演进蓝图 (下阶段主线)** | **docs/QUANTMIND_PLATFORM_BLUEPRINT.md** ⭐ (QPB v1.0, 10 Framework + 5 升维 + 4 Wave, 2026-04-17) |
| MVP 设计文档 (Wave 1+) | `docs/mvp/MVP_*.md` (每个 MVP ≤ 2 页, 铁律 24) |
| 了解系统现状/模块怎么对接 | **SYSTEM_STATUS.md** ⭐ |
| 建数据库表 | docs/QUANTMIND_V2_DDL_FINAL.sql ⭐ |
| 接入数据源 | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md ⭐ |
| 写后端Service/理解分层 | docs/DEV_BACKEND.md (§3分层/§4数据流/§5协同矩阵) |
| 写回测引擎/理解Hybrid架构 | docs/DEV_BACKTEST_ENGINE.md (§3Hybrid/§4接口) |
| 写因子计算 | docs/DEV_FACTOR_MINING.md |
| 写前端页面 | docs/DEV_FRONTEND_UI.md |
| 写调度任务 | docs/DEV_SCHEDULER.md |
| 写GP相关 | docs/GP_CLOSED_LOOP_DESIGN.md (FactorDSL/WarmStart) |
| 写风控 | docs/RISK_CONTROL_SERVICE_DESIGN.md (L1-L4状态机) |
| 写AI闭环/因子发现 | docs/DEV_AI_EVOLUTION.md (V2.1, 705行) |
| 写外汇模块(⏳) | docs/DEV_FOREX.md (682行, DEFERRED) |
| ML Walk-Forward设计/G1结论 | docs/ML_WALKFORWARD_DESIGN.md (v2.1, 1096行) |
| 研究知识库(防重复失败) | `docs/research-kb/` (19条目: 8 failed + 6 findings + 5 decisions) |
| 性能优化最佳实践 | `.claude/skills/quantmind-performance/` |
| 路线图(历史, 已归档) | docs/archive/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8, 被Blueprint替代) |

## 当前进度

### 累计完成
- ✅ Phase A-F全部完成（185新测试, 904全量通过, 0回归）
- ✅ R1-R7 研究完成（7份报告, 73项可落地）
- ✅ G1 LightGBM Walk-Forward完成（ML Sharpe=0.68 vs 等权同期0.83）
- ✅ G2风险平价+G2.5动态仓位: 均无效, 等权是最优权重方案
- ✅ 因子画像V2完成（48因子全量画像, 模板T1=33/T2=4/T11=6/T12=5）
- ✅ 北向研究三轮完成
- ✅ 性能优化（TimescaleDB 2.26.0 + Parquet缓存1000x + GPU 6.2x）
- ✅ 清明改造完成（Servy+Redis5.0+StreamBus+QMT A-lite+PMS v1.0）
- ✅ 回测引擎Phase 1加固(印花税+三因素滑点+z-score clip+DataFeed校验)

### Step 0→6-H 重构 + OOS 验证 + 研究收束 (2026-04-09~10)
- ✅ Step 0: PT暂停+备份+基线建立(Sharpe=0.94, 5年)
- ✅ Step 1: DB全表code格式统一带后缀 + 缓存重建
- ✅ Step 2: 信号路径统一为SignalComposer(铁律16)
- ✅ Step 3-A: Data Contract + DataPipeline统一入库管道(铁律17) + 单位标准化
- ✅ Step 3-B: stock_status_daily表 + adj_close + 日期级过滤 + is_suspended完整检测
- ✅ Step 4-A: backtest_engine.py拆分为backend/engines/backtest/ 8模块
- ✅ Step 4-B: YAML配置驱动 + config_loader + run_backtest改造
- ✅ Step 5: Parquet缓存系统(`cache/backtest/2014-2026/`, 12年×3文件) + 48新测试
- ✅ Step 6-A: run_paper_trading.py拆分1734→345行 + 4个pt_* Service
- ✅ Step 6-B: minute_bars格式统一(139M行) + 7份文档全面更新 + 重构遗留项收尾
- ✅ Step 6-C: 冒烟测试8/8 + PT重启 + 6 runtime bug修复
- ✅ Step 6-D: walk_forward.py修复 + 12年首次真跑(Sharpe=0.5309) + WF 5-fold OOS + 逐年度分解 + FF3归因
- ✅ Step 6-E: IC基础设施修复 (ic_calculator统一口径 + 铁律19) + Alpha衰减归因
- ✅ Step 6-F: 因子替换无效 + Size-neutral有效 + 噪声鲁棒性全PASS + 铁律20
- ✅ Step 6-G: Modifier层实验 (Vol-targeting/DD-aware无效, Partial SN是唯一有效Modifier)
- ✅ Step 6-H: SN inner实现(Sharpe=0.68) + WF验证(0.6521) + Regime CLOSED + LightGBM CLOSED + PT激活SN b=0.50

### 已解决的遗留项(Step 6-B~6-H期间)
- ✅ BJ股过滤: `load_universe()` 已过滤 `board != 'bse'`, PT+回测+WF三路径全覆盖
- ✅ is_st标记: stock_status_daily已有552K/12M条is_st=true记录
- ✅ 12年OOM: Parquet缓存+groupby替代pivot_table, Step 6-D成功跑通12年(2980天)

### 待办(V4路线图)
- ✅ 阶段0: Qlib + RD-Agent 技术调研完成 → 路线C(混合): 自建核心 + Alpha158因子借鉴 + riskfolio-lib (2026-04-10)
- ✅ **Phase 1.1**: 回测Phase A优化（841s→14.6s, groupby+bisect替代O(N×M)全表扫描, 2026-04-10）
- ✅ **Phase 1.2**: 新信号维度（Alpha158六因子6/6 PASS + 行业动量2/2 PASS + 北向V2 15因子 + PEAD方向修正为-1 + SW1中性化迁移53因子, 2026-04-11）
- ❌ **Phase 2.1**: 融合E2E NO-GO（IC天花板0.09, Layer2 sim-to-real gap 282%, commit f47349b, 2026-04-11）
  - Exp-C(CORE5) IC=0.0912最佳, Exp-A(7因子)=零增量, Exp-B(16因子)=IC降25%
  - PortfolioNetwork val_sharpe=1.26→实盘-0.99, 可微Sharpe在A股不可行
  - 7新因子入库(QTLU/RSQR/HVP/IMAX/IMIN/CORD/RESI, 12yr neutralized)
  - 60月窗口比24月提升36%(唯一有效改进)
- ❌ **Phase 2.2**: Gate验证NO-GO — 6方法全败(LambdaRank+SN=0.56最佳, IC加权=0.27, MVO=0.26, 均<基线0.62)
  - 等权+SN(0.6211)不可超越, portfolio构建层已无优化空间
  - IC_IR加权反而更差: turnover权重最大→放大流动性风险
  - MVO 94%失败率(40股×60日协方差不稳定)
  - 瓶颈确认在信号层(5因子信息量不足), 非portfolio构建层
- ✅ **Phase 2.3**: 市值诊断 — 无SN=纯微盘91.5%, Alpha 100%微盘, 因子真alpha但微盘放大3-4x (2026-04-11)
- ✅ **Phase 2.4**: Research Exploration — 36实验5改善方向, **最佳Sharpe=1.04** (CORE3+dv_ttm) (2026-04-12)
  - dv_ttm(股息率)关键突破: +30% Sharpe, MDD -19.5%
  - P0修正: RSQR_20有害(-0.089), 移除; 最终配置4因子CORE3+dv_ttm
  - 已关闭: universe filter(Alpha=微盘), LambdaRank因子(冲突), RSQR/QTLU单独加入(零增量)
- ✅ **WF验证**: CORE3+dv_ttm+SN050 5-fold WF OOS **Sharpe=0.8659, MDD=-13.91%** PASS (2026-04-12)
  - 0 negative folds, overfit_ratio=0.84, STABLE
  - Config 2(CORE5+dv) MARGINAL 0.6992, Config 3(CORE3+dv Top25 Quarterly) MARGINAL 0.7034
- ✅ **PT配置更新**: CORE5→CORE3+dv_ttm, pt_live.yaml+signal_engine+parquet_cache+.env全部更新 (2026-04-12)
- ✅ **Phase 3B**: 因子特征分析+P1评估 — 32因子画像, 8 P1候选WF全FAIL, **CORE3+dv_ttm确认为等权框架alpha上限** (2026-04-13)
  - 报告修正: mf_divergence移除(INVALIDATED), momentum镜像移除, ic_1d bug修复, kbar_kup outlier修复
  - PIT调查: 基础因子正确(ann_date), 衍生计算(diff/ranking)有bias, 已记录修复方案
  - WF结果: 最佳price_volume_corr_20 OOS=0.7737(-0.092), 最差rsrs_raw_18=0.5993(-0.267), 加第5因子=稀释信号
- ❌ **Phase 3D**: ML Synthesis NO-GO — 4实验全FAIL, A-REG(11因子)=0.54最优但远低于基线0.87, B-REG(33因子)=0.30更差, LambdaRank不可复现, **ML预测层CLOSED** (2026-04-14)
  - 修复3个Bug: amount列缺失(致命,500bps→正常滑点), SN尺度不匹配, 全局quantile标签
  - 第5次独立验证ML无法超越等权(G1/6-H/2.1/2.2/3D)
  - 报告: docs/research-kb/findings/phase3d-ml-synthesis.md
- ❌ **Phase 3E-II**: 微结构因子验证 — 16/17 neutral IC PASS + 16/16 noise ROBUST + CORE4独立, 但WF 0/6 PASS (2026-04-15)
  - Track 1 PT加固 + Track 3 全链路诊断: 0 FAIL / 36 PASS / 8 WARN, 6个P0/P1修复
  - Track 2 因子验证: 真alpha(IC 0.05-0.10, 负衰减, 噪声稳健), 但等权5因子全降低Sharpe
  - 结论: 4因子=等权框架alpha上限(Phase 3B+3E双重确认), 微结构因子保留为PASS候选
- 🟡 **Phase 3 MVP A**: 因子生命周期自动化落地 (2026-04-17)
  - `backend/engines/factor_lifecycle.py` 纯规则 + 26/26 tests PASS
  - `scripts/factor_lifecycle_monitor.py` + Celery task + 周五 19:00 调度
  - Dry-run 检测 `reversal_20: active→warning` (ratio=0.43, 真实衰减)
  - 待 GP 完成后重启 beat 激活 + MVP B/C (Rolling WF 周度 + IC 监控告警) 后续
- ⬜ **Phase 4**: PT重启（前提: health_check + dry-run确认 + 首日监控）
- 详见 docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md §16

### 平台化主线 (下阶段, 2026-04-17 启动)
- ⭐ **Platform Blueprint v1.0** (`docs/QUANTMIND_PLATFORM_BLUEPRINT.md`, 3085 行): 10 Framework + 5 升维 + 4 Wave × 14 MVP (18-23 周)
- 🟢 **Wave 1 完结** (2026-04-17 已交付): Platform Skeleton (MVP 1.1 ✅) + Config (1.2 ✅) + DAL (1.2a ✅) + Registry 回填 (1.3a ✅) + Direction DB 化 (1.3b ✅) + Factor Framework 收尾 (1.3c ✅) → **Wave 1 下一步 MVP 1.4 Knowledge Registry**
- ⬜ **Wave 2** (5-6 周): Data Framework + Data Lineage + Backtest/Parity
- ⬜ **Wave 3** (6-8 周): Strategy Framework + Signal/Exec + Event Sourcing + Eval Gate
- ⬜ **Wave 4** (3-4 周): Observability + Performance Attribution + CI/CD
- **MVP 串行交付**: 完成一个再 plan 下一个, 不预批量写设计稿 (铁律 23/24)

📋 系统蓝图: `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` (当前真相) + `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (演进规划)
📊 测试: 2100+ tests collected / 100+ test files (2026-04-17 MVP 1.3c 后实测: MVP 1.1-1.3c 锚点 298 PASS / 无回归 / ruff clean, regression max_diff=0 Sharpe 0.6095; 全量 pytest baseline 34 fail 全为历史债-post-refactor+deprecated路径, Platform 新增 0 fail) + **Phase 3 MVP A 新增 26 tests PASS (factor_lifecycle)** + **MVP 1.3c 新增 21+12+6 = 39 tests PASS (lifecycle/registry 扩展/onboarding gates)**
---

## 文件归属规则（防腐）

### 根目录只允许以下文件
CLAUDE.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / pyproject.toml / .gitignore
- 新审计/盘点报告 → `docs/reports/`
- 新研究报告 → `docs/research/`
- 回测输出 → 用完即删，不留根目录
- 临时文件/artifact → 用完即删

### 引用完整性规则
- 引用文件必须用完整相对路径
- 归档/移动文件后 `grep -r "文件名" --include="*.md" --include="*.py"` 更新所有引用
- 重构函数/重命名后检查所有import方

### 数字同步规则
- CLAUDE.md中的统计数字（表数/因子数/测试数）变更时同步更新
- 不确定的数字标注"约"或"截至日期"
- 因子池状态以FACTOR_TEST_REGISTRY.md为唯一真相源

### 文档层级（固定）
- **总设计 (当前真相)**: `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` ⭐
- **平台化蓝图 (未来 6 月主线)**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` ⭐ (QPB v1.0)
- **MVP 设计**: `docs/mvp/MVP_*.md` (每个 ≤ 2 页, 铁律 24)
- **系统现状**: `SYSTEM_STATUS.md`
- **入口导航**: `CLAUDE.md`（本文件）
- **Schema定义**: `docs/QUANTMIND_V2_DDL_FINAL.sql`
- DESIGN_V5/ROADMAP_V3 已归档至 docs/archive/, SYSTEM_BLUEPRINT 是当前总设计 + PLATFORM_BLUEPRINT 是演进规划

## 执行标准流程

1. 读本文件了解全局
2. **读 SYSTEM_STATUS.md** 了解系统现状、模块怎么对接
3. 根据任务类型读对应DEV文档（见查阅索引）
4. 编码 → 测试 → 验证
5. 发现需要偏离指令的地方 → **先报告，等确认**
6. 任务完成后更新 SYSTEM_STATUS.md 对应章节（保持文档与代码一致）
