# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **系统现状**: SYSTEM_STATUS.md（环境/数据库/代码/架构全景）
> **铁律 SSOT (v3.0, 2026-04-30)**: [IRONLAWS.md](IRONLAWS.md) — 完整铁律 (1-44 + X9 + X10) + tier 标识 (T1/T2/T3) + LL/ADR backref. 本文件铁律段已 reference 化, 详 [ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md).
> **D 决议 (4-30 user 决议)**: D-1=A 硬 scope (仅铁律段 reference) / D-2=A 仅 X10 inline / D-3=A ADR-021 编号锁定.

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase A-F完成, v3.8路线图, Step 0→6-H重构+研究完成, PT配置已更新CORE3+dv_ttm(2026-04-12 WF PASS), Sharpe基线=**WF OOS 0.8659 (CORE3+dv_ttm+SN050, +33% vs CORE5 baseline 0.6521, MDD -13.91%)**
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB(PyTorch cu128), 32GB DDR5
- **PMS**: v1.0阶梯利润保护3层(14:30 Celery Beat检查, v2.0已验证无效不实施)
- **下一步(V4路线图, 已被 Wave 平台化主线替代)**: ~~Phase 1.1~~ ✅ → ~~Phase 1.2~~ ✅ → ~~Phase 2.1~~ ❌NO-GO → ~~Phase 2.2~~ ❌NO-GO → ~~Phase 2.3~~ ✅诊断 → ~~Phase 2.4~~ ✅探索+WF PASS → ~~PT配置更新~~ ✅ → ~~Phase 3 自动化~~ ✅ **(已被 Wave 3 MVP 3.1-3.5 全 ✅ 替代)** → ~~Phase 4 PT重启~~ ⚠️ **(user 2026-04-29 决议"全清仓暂停 PT", 真账户 0 持仓; 重启 gate prerequisite 见 [SHUTDOWN_NOTICE_2026_04_30 §9](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md))**. 当前主线 → **Wave 4 MVP 4.1 Observability 进行中** (batch 1+2.1+2.2 ✅ + 3.x 13/17 ✅, 详 §当前进度 + QPB v1.16).
- **调度链路**: 09:00-14:55 **intraday-risk-check Celery Beat `*/5 9-14 * * 1-5`** (MVP 3.1 批 2, Session 29-30, 72 trigger/日, IntradayPortfolioDrop3/5/8% + QMTDisconnectRule, Redis 24h TTL dedup fail-open) → **(次日)** T+1 09:31执行 → **14:30 risk-daily-check Celery Beat** (MVP 3.1 批 1+3, Session 28+30, PMSRule L1/L2/L3 + CircuitBreakerRule Hybrid adapter 方案 C) → 15:40对账 → 16:15数据拉取 → 16:25预检 → 16:30因子+信号 → 17:30 moneyflow+factor_health → **17:35 pt_audit 主动守门** → **18:00 DailyIC (每日增量 IC 入库 CORE 4, Session 22 Part 2)** → **18:15 IcRolling (ic_ma20/60 rolling 刷新, Session 22 Part 8)** → **18:30 DataQualityCheck (Session 26 shift 17:45→18:30, 避 dense window + 脚本硬化)** → 周五 19:00 factor-lifecycle Beat → **周日 04:00 MVP31SunsetMonitor (Session 32, ADR-010 addendum Follow-up #5, Sunset Gate A+B+C 周监控)**. **17:05 DailyExecuteAfterData 已永久废除 (Stage 4 Session 17, ADR-008 P0-δ 污染源)**. **铁律 11 + 17 每日 IC 全链完工** (Session 23 Part 1+2): 3 脚本分工 (compute_daily_ic / compute_ic_rolling / fast_ic_recompute) + 2 schtask wire + 实战 rehearsal 验证 GO. **MVP 3.1 Risk Framework 正式完结** (Session 30 2026-04-24, 批 1+2+3 全 merged PR #55/#57/#58/#59/#60/#61 6 PR + 1 spike #54, Celery Beat 5 schedule entries 生产激活, 首次真生产触发 2026-04-27 Monday 09:00 intraday + 14:30 daily).

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
| 缓存 | 本地Parquet快照(backend/data/parquet_cache.py按年分区), factor_values 840M行→TimescaleDB hypertable |
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
- **factor_values**: **840,478,083 行** (~172 GB, TimescaleDB hypertable 152 chunks) — 2026-04-30 Session 45 D3-B 实测 (+1.05M vs Session 5 839,425,275 baseline, 自然增长)
- **factor_ic_history**: **145,894 行** (~36 MB) — 2026-04-30 Session 45 D3-B 实测 (+1099 vs Session 5 144,795 baseline), IC唯一入库点(铁律11), 未入库IC视为不存在
- **Parquet缓存**: `_load_shared_data` 30min→1.6s(1000x), `fast_neutralize_batch` 15因子/17.5min
- **minute_bars**: **190,885,634 行** (~36 GB) — 2026-04-30 Session 45 D3-B 实测 (Step 6-B 已统一 code 格式, 行数稳定但 size 36GB vs 历史 21GB est), 5年(2021-2025), Baostock 5分钟K线, 2537只股票(0/3/6开头, 无BJ)
- **klines_daily**: 11,776,616 行 (~4 GB / 3966 MB, TimescaleDB hypertable 53 chunks) — Session 45 D3-B 实测
- **daily_basic**: 11,681,799 行 (~3.7 GB / 3805 MB) — Session 45 D3-B 实测

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
├── LESSONS_LEARNED.md           ← 经验教训（51条, LL-001~054）
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
│       │   ├── stream_bus.py    # Redis Streams统一数据总线
│       │   └── platform_bootstrap.py  # ⭐ MVP 1.3b wiring 补全 (2026-04-17): bootstrap_platform_deps() 注入 DBFactorRegistry+DBFeatureFlag 到 signal_engine (3 入口: FastAPI lifespan / run_paper_trading main() / celery_app worker 启动), 幂等+fail-safe (失败自动回 Layer 0 hardcoded, 铁律 33 read-path 允许)
│       ├── services/            # ⭐ 业务逻辑层（主 sync psycopg2, 遗留 async: mining/backtest_service, S1 audit F18）
│       │   ├── signal_service.py
│       │   ├── execution_service.py
│       │   ├── risk_control_service.py
│       │   ├── factor_onboarding.py  # 因子入库pipeline
│       │   ├── factor_repository.py  # ⭐ Phase C C2 (2026-04-16): 因子计算数据加载层 (load_daily/load_bulk*/load_pead*), Engine 不再读 DB. **load_forward_returns DEPRECATED (Phase D D1 2026-04-16, 走 ic_calculator.compute_forward_excess_returns 铁律 19)**
│       │   ├── factor_compute_service.py  # ⭐ Phase C C3 (2026-04-16): 因子计算编排层 (compute_daily/compute_batch/save_daily), compute_batch 走 DataPipeline 铁律 17 合规
│       │   ├── config_loader.py      # ⭐ Step 4-B: YAML策略配置加载
│       │   ├── pt_data_service.py    # ⭐ Step 6-A: PT并行数据拉取(337行, 实测2026-04-18 Session 6 verify)
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
├── backend/platform/            # ⭐ MVP 1.1-1.4 + 2.1a/b/c (Sub1+Sub2+Sub3 all) + 2.2 Sub1+Sub2 (2026-04-18) Wave 1 完结 7/7 + MVP 2.1c ✅ 完整结案, Wave 2 剩 MVP 2.3
│   ├── __init__.py              #   统一导出 67 符号 (12 Framework 对外 API + 共享类型)
│   ├── _types.py                #   Signal/Order/Verdict/BacktestMode/Severity/ResourceProfile/Priority
│   ├── data/                    #   #1 Data Framework
│   │   ├── interface.py         #     DataSource/DataContract/DataAccessLayer/FactorCacheProtocol (MVP 1.1)
│   │   ├── access_layer.py      #     ⭐ MVP 1.2a: PlatformDataAccessLayer (read_factor/ohlc/fundamentals/registry) + DALError
│   │   ├── cache_coherency.py   #     ⭐ MVP 2.1a: CacheCoherencyPolicy + MaxDateChecker + TTLGuard + check_stale (铁律 30 显式契约)
│   │   ├── base_source.py       #     ⭐ MVP 2.1a: BaseDataSource Template method + ContractViolation
│   │   └── sources/             #     ⭐ MVP 2.1b (2026-04-18): 3 concrete fetcher 继承 BaseDataSource
│   │       ├── baostock_source.py  #       BaostockDataSource + MINUTE_BARS_DATA_CONTRACT + code 格式 SH/SZ/BJ
│   │       ├── qmt_source.py       #       QMTDataSource + 3 DataContract (positions/assets/ticks), Redis sink 特殊 (不走 DataPipeline)
│   │       └── tushare_source.py   #       TushareDataSource + 3 DataContract (klines_daily/daily_basic/moneyflow), RAW 单位留 DataPipeline 转
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
│   ├── knowledge/               #   #10 Knowledge Registry
│   │   ├── interface.py         #     ExperimentRegistry/FailedDirectionDB/ADRRegistry (MVP 1.1)
│   │   └── registry.py          #     ⭐ MVP 1.4: DBExperimentRegistry + DBFailedDirectionDB + DBADRRegistry full concrete
│   ├── resource/interface.py    #   #11 Resource (ROF, U6): ResourceManager/AdmissionController/BudgetGuard
│   └── backup/interface.py      #   #12 Backup & DR: BackupManager/DisasterRecoveryRunner
├── backend/migrations/          # ⭐ SQL migration 集中 (MVP 1.2 + 1.3a + 1.4 新增, 幂等 + rollback 配对)
│   ├── feature_flags.sql        #   MVP 1.2: feature_flags 表 + trigger 维护 updated_at
│   ├── factor_registry_v2.sql   #   MVP 1.3a: ALTER factor_registry ADD pool + ic_decay_ratio + 2 索引
│   ├── factor_registry_v2_rollback.sql  # MVP 1.3a emergency rollback
│   ├── knowledge_registry.sql   #   ⭐ MVP 1.4: platform_experiments + failed_directions + adr_records + 10 索引 + trigger
│   └── knowledge_registry_rollback.sql  # MVP 1.4 emergency rollback
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
│   # fetch_minute_bars.py 已删 MVP 2.1c Sub3.3 (2026-04-18), 用 BaostockDataSource SDK 替代. 参考 SYSTEM_RUNBOOK §7.3
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
│   ├── knowledge/               # ⭐ MVP 1.4 Knowledge migration (一次性迁移 markdown → DB)
│   │   ├── migrate_research_kb.py  # CLAUDE.md L474 表格 + docs/research-kb/ → failed_directions/platform_experiments
│   │   └── register_adrs.py        # docs/adr/ADR-*.md frontmatter → adr_records
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

## 铁律（v3.0 reference, 完整内容见 [IRONLAWS.md](IRONLAWS.md)）

> **本段已 reference 化** ([ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md), 2026-04-30 Step 6.2). 完整铁律 (1-44 编号 + X9 + X10 + 候选 X1/X3/X4/X5 + 跳号 X2/X6/X7 + 撤销 X8 历史决议) 沉淀到 [IRONLAWS.md](IRONLAWS.md) 作 SSOT.
>
> **历史编号保持不变** (防其他文档引用漂移). DEPRECATED 占位保留 (条目 2 合并入 25).
> **测试**: 10 年后此条仍成立? "是, 只是实现方式变了" → 保留. "否, 某阶段后不适用" → 不该是铁律 (应入 Blueprint).

### Tier 索引 (T1 强制 / T2 警告 / T3 建议)

- **T1 强制 (31 条, 违反 → block PR / 真金风险)**: 1 / 4 / 5 / 6 / 7 / 8 / 9 / 10 / 10b / 11 / 12 / 13 / 14 / 15 / 16 / 17 / 18 / 19 / 20 / 25 / 29 / 30 / 31 / 32 / 33 / 34 / 35 / 36 / 41 / 42 / 43
- **T2 警告 (14 条, 违反 → 提示 + commit message 写 reason)**: 3 / 21 / 22 / 23 / 24 / 26 / 27 / 28 / 37 / 38 / 39 / 40 / 44 (X9) / **X10 (新)**
- **T3 建议**: 本版本 0 条 (留 Step 6.2.5+ promote)
- **DEPRECATED**: 条目 2 (合并入 25)
- **候选未 promote (Step 6.2.5+)**: X1 (Claude 边界) / X3 (.venv fail-loud) / X4 (死码月度 audit) / X5 (文档单源化)
- **跳号 / 撤销 (历史决议保留)**: X2 / X6 / X7 (跳号未定义) / X8 (撤销, T0-17 撤销同源)

### 编号简述索引 (link IRONLAWS.md §X.YY 完整)

#### 工作原则类 (1-3) — IRONLAWS.md §2

1. [T1] 不靠猜测做技术判断 — 外部 API/数据接口必须先读官方文档确认
2. [DEPRECATED] ~~下结论前验代码~~ — 已并入 25
3. [T2] 不自行决定范围外改动 — 先报告建议和理由

#### 因子研究类 (4-6) — IRONLAWS.md §3

4. [T1] 因子验证用生产基线+中性化 — raw IC + neutralized IC 并列, 衰减>50%标记虚假 alpha (LL-013/014)
5. [T1] 因子入组合前回测验证 — paired bootstrap p<0.05 vs 基线 (LL-017)
6. [T1] 因子评估前确定匹配策略 — RANKING/FAST_RANKING/EVENT 框架不混用 (LL-027)

#### 数据与回测类 (7-8) — IRONLAWS.md §4

7. [T1] IC/回测前确认数据地基 — universe 对齐 + 无前瞻偏差 + 数据质量
8. [T1] 任何策略改动必须 OOS 验证 — walk-forward / paired bootstrap p<0.05 硬门槛

#### 系统安全类 (9-11) — IRONLAWS.md §5

9. [T1] 所有资源密集任务必须经资源仲裁 — 全局原则 (PG OOM 2026-04-03)
10. [T1] 基础设施改动后全链路验证 — 清明改造教训
    - **10b** 生产入口真启动验证 — `pytest -m smoke` 必须全绿 (MVP 1.1b shadow fix)
11. [T1] IC 必须有可追溯的入库记录 — factor_ic_history 唯一入库点 (mf_divergence 教训)

#### 因子质量类 (12-13) — IRONLAWS.md §6

12. [T1] G9 Gate 新颖性可证明性 — AST 相似度 > 0.7 拒绝 (AlphaAgent KDD 2025)
13. [T1] G10 Gate 市场逻辑可解释性 — 必须附带「市场行为→因子信号→预测方向」 (reversal_20 教训)

#### 重构原则类 (14-17, Step 6-B) — IRONLAWS.md §7

14. [T1] 回测引擎不做数据清洗 — DataPipeline 入库验证, Engine 不猜单位
15. [T1] 任何回测结果必须可复现 — `(config_yaml_hash, git_commit)` + max_diff=0
16. [T1] 信号路径唯一且契约化 — 生产/回测/研究走同一 SignalComposer→PortfolioBuilder 路径
17. [T1] 数据入库必须通过 DataPipeline — 禁裸 INSERT (ADR-0009). **例外条款**: subset-column UPSERT 走手工 partial UPSERT (LL-066, PR #43/#45)

#### 成本对齐 (18) — IRONLAWS.md §8

18. [T1] 回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核

#### IC 口径统一 (19, Step 6-E) — IRONLAWS.md §9

19. [T1] IC 定义全项目统一 — 走 `backend/engines/ic_calculator.py` (`neutral_value_T1_excess_spearman` v1.0.0)

#### 因子噪声鲁棒性 (20, Step 6-F) — IRONLAWS.md §10

20. [T1] 因子噪声鲁棒性 G_robust — 5% 噪声 retention ≥ 0.95 / 20% ≥ 0.50

#### 工程纪律类 (21-24, Step 6-H 后) — IRONLAWS.md §11

21. [T2] 先搜索开源方案再自建 — Qlib/RD-Agent/alphalens (90% 重叠)
22. [T2] 文档跟随代码 — CLAUDE.md/SYSTEM_STATUS/DEV_*/Blueprint 同步或 `NO_DOC_IMPACT`
23. [T2] 每个任务独立可执行 — 不允许任务依赖未实现模块
24. [T2] 设计文档必须按抽象层级聚焦 — MVP ≤2页 / Framework ≤5页 / Blueprint TOC 必含

#### CC 执行纪律类 (25-28) — IRONLAWS.md §12

25. [T1] 代码变更前必读当前代码验证 — 改什么读什么 (含铁律 2 合并)
26. [T2] 验证不可跳过不可敷衍 — 读完整代码 + 交叉对比 + 明确结论
27. [T2] 结论必须明确 (✅/❌/⚠️) 不准模糊 — 不接受"大概没问题"
28. [T2] 发现即报告不选择性遗漏 — 范围外异常也报告

#### 数据完整性类 (29-30, P0-4 2026-04-12) — IRONLAWS.md §13

29. [T1] 禁止写 float NaN 到 DB — RSQR_20 11.5M 行教训
30. [T1] 缓存一致性必须保证 — 下一交易日内生效, 否则视为过期

#### 工程基础设施类 (31-35, S1-S4 审计沉淀) — IRONLAWS.md §14

31. [T1] Engine 层纯计算 — `backend/engines/**` 不读写 DB/HTTP/Redis (Phase C 落地)
32. [T1] Service 不 commit — 事务边界由调用方 (Router/Celery) 管
33. [T1] 禁止 silent failure — fail-safe / fail-loud / `# silent_ok` 注释三选一
34. [T1] 配置 single source of truth — `config_guard` 启动硬 raise
35. [T1] Secrets 环境变量唯一 — 0 fallback 默认值 / `.env` 必 `.gitignore`

#### 实施者纪律类 (36-41, 2026-04-17 新增) — IRONLAWS.md §15

36. [T1] 代码变更前必核 precondition — 依赖 / 老路径 / 测试数据三项核
37. [T2] Session 关闭前必写 handoff — `memory/project_sprint_state.md` 顶部
38. [T2] Platform Blueprint 是唯一长期架构记忆 — QPB 跨 session 真相源
39. [T2] 双模式思维 — 架构/实施切换必须显式声明
40. [T2] 测试债务不得增长 — 新增 fail 禁合入 (baseline 沿用 pre-push diff)
41. [T1] 时间与时区统一 — UTC 内部 + Asia/Shanghai 展示 + TradingDayProvider

#### PR 治理类 (42) — IRONLAWS.md §16

42. [T1] PR 分级审查制 (Auto mode 缓冲层) — `docs/**` 直 push / `backend/**` 必走 PR + reviewer + AI 自 merge

#### schtask 硬化类 (43) — IRONLAWS.md §17

43. [T1] schtask Python 脚本 fail-loud 硬化标准 — 4 项清单 (PG timeout / FileHandler delay / boot probe / 顶层 try/except)

#### X 系列治理类 (44 X9 + X10 新) — IRONLAWS.md §18

44. [T2] **(X9)** Beat schedule / config 注释 ≠ 真停服, 必显式 restart — schedule 类 PR 必含 post-merge ops checklist (LL-097)

**X10 (新, 2026-04-30 Step 6.2 PR 落地)** [T2]: **AI 自动驾驶 detection — 末尾不写 forward-progress offer**
- **主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作. 等 user 显式触发. 反例 → STOP.
- **子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件. 必须显式核 D 决议链全部前置, 才能进入下一步.
- **触发 case**: PR #171 PT 重启 gate 7/7 PASS 后 CC 自动 offer "schedule agent 5d dry-run reminder", user 4-30 撤回 + 强制走 Step 5/6/7/T1.4-7 完整路径. 详 [LL-098](LESSONS_LEARNED.md) + [IRONLAWS.md §18](IRONLAWS.md).

### 引用规范

- **新引用**: 直接 link `IRONLAWS.md §X.YY` (e.g. `IRONLAWS.md §18 X10`)
- **历史引用** (CLAUDE.md inline 时代写的 "铁律 33"): 沿用编号, 仍可走本段 reference 找到 link

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

**因子健康状态（2026-04-18 Session 5 factor_lifecycle 补跑后实测）:**
- turnover_mean_20: ✅ active (IC=-0.091, direction=-1)
- volatility_20: ✅ active (IC=-0.114, direction=-1)
- bp_ratio: ✅ active (IC=+0.107, direction=+1)
- dv_ttm: ⚠️ **active → warning** (Session 5 lifecycle 补跑, |IC_MA20|/|IC_MA60|=0.517 < 0.8 阈值).
  **PT 生产配置仍包含此因子**. 下周五 19:00 lifecycle 再评估, 如持续 warning 考虑 CORE3 only (去 dv_ttm) 或加新因子. ~~"可能关联本周 -10.2% 回撤"~~ Session 10 证伪 — 本周 NAV 实际 +0.5%, 见下方 PT 状态更新.
- amihud_20: 降级→CORE5基线保留 (仍在factor_values, 不参与PT信号)
- reversal_20: ⚠️ **active → warning** (Session 5 lifecycle 补跑, ratio=0.430 < 0.8, Session 4 handoff 预测 "待 beat 激活落库", 今天补跑 DB 状态更新. 不参与 PT 信号, 仅 CORE5 基线保留, 不影响生产)

**PT 状态 (2026-04-19 Session 10 末, 修正 Session 5 记录错误 + 暂停实盘)**:

**当前状态** (2026-04-20 Session 20 末, execution_mode=live 生产 cutover 完成):
  - **`.env:17 EXECUTION_MODE=paper→live`** (Session 20 17:47 sed + Servy restart 4 服务, `/health` 返 `{"execution_mode":"live"}`). F17 根因消除. 备份 `backend/.env.bak.20260420-session20-cutover`
  - **F14 已自愈 (Session 20 20:38 手工 bootstrap)**: `_tmp_bootstrap_cb_state_live_session20.py` 调 `_upsert_cb_state_sync(level=0)` 写 live L0 首行 (trigger_reason='Session 20 cutover bootstrap — F14 self-heal verification'). 当前 cb_state: paper L0 @16:30:24 + live L0 @20:38:04. 4-21 16:30 schtasks 仅 upsert refresh (level=0 不变), 17:35 pt_audit C4 check → PASS
  - **F18 撤回**: Session 19 误报, `signal_service.py:278/436` hardcoded 'paper' 是 **ADR-008 D3-KEEP 有意设计** (signals 表跨模式共享, `test_execution_mode_isolation.py:471/479` 强制契约). 详见 LL-060
  - `QuantMind_DailyExecute` (09:31 live) — 默认 disabled, 等 Stage 4.2 评估 reenable (依赖 F14 自愈 + Session 21 F19 phantom 清理). **Session 36 PR-DEXEC governance 修复**: ps1 加 `Disable-ScheduledTask` 紧跟 Register, rerun 后保持 Disabled, 防 PR-DRECON 同 pattern silent 复活 (实测 ps1 rerun 复活为 State=Ready, 04/19 LastResult=0 Sunday 内部跳过, 但下个交易日 09:31 真金触发风险). Stage 4.2 解锁 checklist 见 SCHEDULING_LAYOUT.md Known #1
  - `QuantMind_DailySignal` (16:30 signal) — **reenabled Stage 4 Session 17** (PR-A 动态 execution_mode + D2-a 蒸发 guard 双重守护, DB 写路径不触 QMT)
  - `QuantMind_DailyExecuteAfterData` (17:05 paper 污染源) — **永久废除 Stage 4 Session 17** (从 setup_task_scheduler.ps1 源头删除, P0-δ 不再能复现)
  - `QuantMind_PTAudit` (17:35) — **新增 Stage 4 Session 17** (5-check 主动守门 + 聚合钉钉 + scheduler_task_log). 4-20 首次自动跑 exit=2 P1 alert, 捕获 F19 5 phantom 码 (db_drift 24 vs snapshot 19)
  - QMT Data Service + PT_Watchdog 等只读任务保留
  - **findings 累计 19** (Session 19 18 - F18 + F21 + F22 + F23 候选撤回 = 19). 下 Session 21 优先级: F21 pt_watchdog L128 修 + reenable → F15 moneyflow silent failure 根因 → F19 phantom DELETE + F20 trade_log 完整性 → F16 LGBM shadow
  - **Session 20 末 Redis 实测 NAV = ¥1,010,376.08** (20:21:53, cash=¥110,624 + 持仓 19). DB `performance_series` 4-20 live = ¥1,007,775 (16:30 signal_phase 签到快照), 差 +¥2,601 = **QMT 盘后结算时点差** (非 bug, 符合历史模式). **PT 状态取值源协议**: 实时 NAV → Redis; 历史日 NAV → DB perf_series; QMT 对账 → `query_asset` 直连
  - **🔴 Session 45 末 (2026-04-30 14:54) xtquant 真账户实测**: positions=0 / cash=¥993,520.16 / market_value=0. **清仓 v4 hybrid narrative** (PR #169): 17 股 CC 4-29 10:43:54 emergency_close_all_positions.py 实战 sell + 1 股 (688121.SH 卓然新能 4500 股) 4-29 跌停 cancel (status=57, MARKET_SH_CONVERT_5_CANCEL 撮合规则) → 4-30 user GUI 手工 sell. DB 4-28 19 股 stale snapshot 是历史快照. Audit log: `risk_event_log id=67beea84-e235-4f77-b924-a9915dc31fb2` (P0 ll081_silent_drift_2026_04_29). 详 [SHUTDOWN_NOTICE_2026_04_30 §12 v4 修订](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md). PT 重启 gate 见 §9 prerequisites (T0-15/16/18 + F-D3A-1 + DB stale 清 + paper-mode 5d dry-run + .env paper→live 用户授权; **T0-19 已落地 PR #168**).

**本周实测 NAV 曲线 (performance_series, 推翻 Session 5 "-10.2% 回撤" 误读)**:

| 日 | NAV | 真实 daily_return (手工算) | DB daily_return 字段 ⚠️ | DB drawdown ⚠️ |
|---|---|---|---|---|
| 4-13 | ¥1,003,313 | N/A (周起点) | +0.35% | 0 |
| 4-14 调仓 | ¥1,002,113 | **-0.12%** ✓ | -0.12% | -0.12% |
| 4-15 | ¥1,001,187 | **-0.09%** | +0.12% ✗ | -0.21% |
| 4-16 | ¥1,003,401 | **+0.22%** | +0.34% ✗ | 0 |
| 4-17 | ¥1,008,299 | **+0.49%** | +0.83% ✗ | -0.17% ✗ |

**周净变化**: 4-13 → 4-17 NAV +0.497% (涨). 最大真实单日 dd -0.12% (4-14 调仓). 建仓期回撤 4-02~4-03 -3.1% 已恢复. 自 4-02 建仓 989K → 4-17 1,008K = **+1.9%** 实盘累计.

⚠️ **新发现 P1-c `save_qmt_state` daily_return / drawdown 字段 bug**: DB 字段值 (4-15/16/17 三天) 与 NAV 手工 pct_change 不匹配. 根因推测: `run_paper_trading.py:225` `SELECT nav FROM performance_series WHERE execution_mode='paper'` → paper 命名空间永远 empty → `prev_nav` fallback 到 `PAPER_INITIAL_CAPITAL=1,000,000` 而非前一日真实 NAV. 即 P0-β 命名空间根因的**又一个症状**. 阶段 2 PR-A 修 paper→live 动态后自愈. drawdown 字段同理 (peak_nav 算法也读 execution_mode='live' 但 prev_nav 来源污染传导).

**Session 5 "-10.2%" 误读根因** (铁律 22/25 违反): 混淆 `market_value` (持仓市值) 与 `nav`. 4-14 卖 10 只 BJ 股 → cash 从 0% 升 11% → mv 降 10%, 但 NAV 没跌. 未来更新 PT 状态必须实测 `performance_series` + Redis + QMT 三源, 不凭印象.

**时间线** (保留):
  - 2026-04-02 ~ 04-13: 9 → 17 股持仓
  - 2026-04-14 调仓 17 → 21 股 36 笔 (清 10 只 BJ 遗留 + 补新 top)
  - 04-15/16/17: 22/22/19 股, 每日 8-20 笔换仓 (**每日换仓非预期, Session 10 定位为 P0-β 根因, 见下**)

**Session 10 发现的致命 bug (live 裸奔 2 周, 今晚已止血暂停)**:

| P0 | 问题 | 根因 | 影响 | 修复 |
|---|---|---|---|---|
| **α** | **熔断 L1-L4 live 彻底失效** | `risk_control_service` hardcoded 读 `execution_mode='paper'`, live 模式永远返 L0 "首次运行" | 真金 ¥1M 2 周无熔断保护, 本周 +0.5% 是运气 | ADR-008 阶段 2 PR-A |
| β | execution_mode 读写不对称 | 写 'live' 读 'paper' (paper_broker/signal_service/pt_monitor hardcoded) | load_state 永远 empty → 每日当首次建仓 | 同上 |
| γ | 每日换仓 | P0-β 表象 (不是 dv_ttm 衰减) | 换手 3× NAV, 成本放大 | P0-β 修后自愈 |
| δ | 17:05 paper 污染 | `DailyExecuteAfterData` 无 `--execution-mode` 默认 paper, 向 live strategy_id 写 20 行 paper trade_log | 成本分析污染 | **永久废除 Stage 4 Session 17** (setup ps1 删除 + schtasks /delete) |
| ε | ST 过滤漏 688184.SH | `load_universe` INNER JOIN race condition (status_date 覆盖率不全) | 4-14 买 → 4-15 卖, 双向成本 | ADR-008 阶段 2 PR-B (Session 14 PR #26) |
| P1-a | 组合跳空检测 live 失效 | `pt_monitor_service:57-58` hardcoded 'paper' | 单股告警 OK, 组合告警 silently 0 | ADR-008 阶段 2 PR-A (Session 11 PR #23) |
| P1-b | position_snapshot 4-17 缺失 | 16:30 signal_phase 预检失败, 20:58 重跑时 QMTClient 读 0 持仓 → save_qmt_state 写 0 持仓 | DB 状态滞后, QMT 真实持仓正确 | D2-a guard (Session 13 PR #25) + D2-c 补录 24 rows (Session 15 PR #27) |
| P1-c | save_qmt_state daily_return / drawdown 字段错 | prev_nav 查询 `execution_mode='paper'` 永远 empty → fallback 到 initial_capital | DB daily_return 4-15/16/17 与 NAV 手工算不一致 | P0-β 修后自愈 (PR-A) |

详见 `docs/adr/ADR-008-execution-mode-namespace-contract.md` + Session 10 memory handoff.

**QMT vs DB 4-16 对账** (Session 10 实测): QMT 真实 19 股 (NAV ¥1,008,299 cash ¥110,624), DB 4-16 snapshot 22 股. 差异源自 4-17 执行了 20 笔 QMT 真实下单 (8 新买 + 11 卖 + 3 加减仓), snapshot 未写入 (P1-b).

> ℹ️ **历史快照说明** (2026-04-30 Session 45 D3-B 加注, PR #169 v4 修订): 上述 4-16 / 4-17 数字是 Session 10 时点真实快照, 自此 user 2026-04-29 决策清仓. **v4 hybrid 真相** (PR #169): 17 股 CC 4-29 10:43:54 emergency_close + 1 股 (688121 卓然新能) 4-29 跌停 cancel → 4-30 user GUI sell. 真账户当前 0 持仓 + cash ¥993,520.16 (xtquant API 4-30 14:54 实测). 详 [SHUTDOWN_NOTICE_2026_04_30 §12 v4](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md).

配置 **CORE3+dv_ttm Top-20 月度 + SN b=0.50** (pt_live.yaml + .env 一致).

⚠️ 旧记录 "PT 已暂停+已清仓 (2026-04-10)" 错误 (Session 5 修正). Session 5 "-10.2% 回撤" 也错误 (Session 10 修正). 两次铁律 22/25 违反, **未来更新 PT 状态前必须实测 `performance_series` + Redis + QMT**, 不凭 Redis portfolio:current 的 market_value 反推.

## 文档查阅索引

| 你要做什么 | 读这个 |
|-----------|--------|
| **系统总设计/架构全景** | **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md** ⭐ (唯一设计真相源, 791行, 16章节) |
| **平台化演进蓝图 (下阶段主线)** | **docs/QUANTMIND_PLATFORM_BLUEPRINT.md** ⭐ (QPB v1.16, 12 Framework + 6 升维 + 4 Wave, 2026-04-17) |
| MVP 设计文档 (Wave 1+) | `docs/mvp/MVP_*.md` (每个 MVP ≤ 2 页, 铁律 24) |
| 了解系统现状/模块怎么对接 | **SYSTEM_STATUS.md** ⭐ |
| 建数据库表 | docs/QUANTMIND_V2_DDL_FINAL.sql ⭐ |
| 接入数据源 | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md ⭐ |
| **新环境 bootstrap** (`.pth` + Servy + hooks) | **docs/SETUP_DEV.md** ⭐ (铁律 10b + MVP 1.1b 沉淀) |
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
| **CC 自动化操作 (runbook)** | **`docs/runbook/cc_automation/00_INDEX.md`** ⭐ (撤 setx / Servy 重启 / 等 ops runbook) |
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
- ✅ Step 6-B: minute_bars格式统一(190M行 实测 Session 45 D3-B) + 7份文档全面更新 + 重构遗留项收尾
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
- 🟢 **Session 21+22+23 铁律 11/17 全链完工** (2026-04-21 → 04-22 跨日, 28 commits / 16 PR #31~#45)
  - **Phase 1 每日增量 IC**: PR #37 `compute_daily_ic.py` (DataPipeline, HORIZONS=5/10/20, 铁律 17/32/19 合规) + PR #40 schtask Mon-Fri 18:00 + PR #42 holiday guard (ZoneInfo Asia/Shanghai)
  - **Phase 2 Rolling MA**: PR #43 `compute_ic_rolling.py` (铁律 17 **例外**: 手工 partial UPSERT 只 SET ic_ma20/60, 保护 ic_5d/10d/20d) + PR #44 schtask Mon-Fri 18:15 + 本地 register NextRun 验证
  - **Phase 3 历史重算**: PR #45 `fast_ic_recompute.py` (铁律 17 **例外**: 手工 partial UPSERT 只 SET ic_5d/10d/20d/ic_abs_5d, 保护 ic_ma20/60/decay_level, **reviewer CRITICAL 防数据破坏 bug**)
  - **实战 rehearsal GO** (Session 23 Part 2, 02:30): `schtasks /Run DailyIC` (80 rows upserted 1.5s) → `schtasks /Run IcRolling` (3 updates 0.8s), schtask → Python → DB → rolling → DB 整链路生产级验证
  - **F19/F20 根因消灭 + 历史 backfill**: PR #39 QMT_STATUS[55] final→pending 1 字节修复 + PR #41 9538 股 trade_log backfill + verify 100% 匹配 QMT
  - **PMS 死码处置**: ADR-010 PMS 并入 Wave 3 MVP 3.1 Risk Framework + PR #34 停 Beat + 去重 (daily_pipeline + api/pms 两处)
  - **F22 NULL ratio guard**: PR #36 DataPipeline ColumnSpec.null_ratio_max + daily_basic.dv_ttm/pe_ttm=0.05 (铁律 33 fail-loud)
  - **新 LL 入册**: LL-059 (9 步闭环), LL-060 (Scan 验证 3 步), LL-061/062 (cutover + bootstrap), LL-063 (假装健康死码), LL-064 (走流程允许绕过), LL-065 (AI summary 数字反证), **LL-066 (DataPipeline subset-column 破坏性)**, **LL-067 (reviewer agent 救场)**
  - **LL-059 9 步闭环连续 10 次实战** (PR #31/#32/#33/#34/#35/#40/#42/#43/#44/#45 全 AI 自主 merge, user ≤ 5 次接触)
  - **铁律 17 例外条款** (LL-066 沉淀) 已补入 CLAUDE.md 铁律 17 段, 未来 subset-column writer 必 check
- 详见 docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md §16

### 平台化主线 (下阶段, 2026-04-17 启动)
- ⭐ **Platform Blueprint v1.16** (`docs/QUANTMIND_PLATFORM_BLUEPRINT.md`): 12 Framework + 6 升维 + 17 MVP (27-36.5 周)
- 🟢 **Wave 1 正式完结 7/7** (2026-04-17 已交付): Platform Skeleton (MVP 1.1 ✅) + Config (1.2 ✅) + DAL (1.2a ✅) + Registry 回填 (1.3a ✅) + Direction DB 化 (1.3b ✅ **+ wiring 补全** — `app/core/platform_bootstrap.py` 挂 FastAPI/PT/Celery 3 入口, 铁律 10 全链路验证) + Factor Framework 收尾 (1.3c ✅) + **Knowledge Registry (1.4 ✅, 3 concrete + 5 ADR + 39+25+5 行入库)**
- 🟢 **Wave 2 正式完结** (Session 9 末 2026-04-19): Data Framework 基础 + Data Lineage + MVP 2.1c 完整结案 + **MVP 2.3 Sub1 6 PR 全链 ✅ 正式完结** (核心 3 PR + SDK 成熟扩 3 PR + 3 生产 scripts 迁 SDK). **2.1a ✅** / **2.1b ✅ 3/3** / **2.1c ✅ 完整交付** (Session 6 末) / **MVP 2.2 Data Lineage (U3) ✅ Sub1+Sub2 全交付** / **MVP 2.3 Sub1 5 PR ✅** (Session 7 PR #11 `a0e01db` ALTER migration + ColumnSpec + ADR-007 / PR #13 `89a925e` PlatformBacktestRunner + DBBacktestRegistry + SerialBacktestExecutor + U3 lineage 集成 + 30 tests + 9 P1 review fixes / PR #14 `f57cf2c` SDK 成熟度 1: direction_provider + ParquetBaselineLoader + BacktestCacheLoader + soft deprecation + 10 tests + 4 P1/P2 review fixes / Session 8 PR #15 `a731caa` SDK 成熟度 2 infra-only: BacktestResult.engine_artifacts + InMemoryBacktestRegistry + LSP abstract `**kwargs` 扩 + `__post_init__` 浅拷贝隔离 + max_history=0 bug 修 + 14 tests + 6 HIGH/MEDIUM reviewer fixes / **Session 8 PR #16 `dc6a13c` SDK 成熟度 3 + run_backtest.py 迁 SDK (修 PR B SN=0 silent bug) + 14 tests + 10 HIGH/MEDIUM/LOW reviewer fixes / **Session 8 PR #17 `4a07491` Sub1 收尾: regression_test.py + profile_backtest.py 迁 Platform SDK** — regression 铁律 15 CI gate bit-identical 验证 (5yr max_diff=0 Sharpe=0.6095 + Deterministic YES / 12yr max_diff=0 Sharpe=0.3594 + Deterministic YES) + ParquetBaselineLoader 替 closure + 2 reviewer blocking config_hash stability 修 (isinstance 死分支 + factor_pool sorted)). **铁律 10b 全面落地** / **Session 6 governance 升级**: 铁律 42 PR 分级审查制 + LL-055/056/057/058 / **Session 7+8 workflow 成熟**: LL-059 9 步闭环实战 **6 次** (PR A/B/C1/C2/C3/C4), AI 自 merge 0 用户接触. **MVP 2.3 Sub1 正式完结**: 5 SDK 成熟 PR + 3 生产 scripts 全迁 Platform SDK (run_backtest / regression_test / profile_backtest) + engines.backtest.runner soft deprecated 保纯 engine 入口.
- 🟢 **MVP 2.3 Sub3 重定义完结** (Session 9 2026-04-19, PR #18 `39dd18d`): 原 Sub3 假设 (消 Phase 2.1 sim-to-real gap 282%) 被 Phase 1 3 Explore agent 9 维实测否决 — PT 和 research 已共享同一 SignalComposer+PortfolioBuilder 路径 (铁律 16 早已实现), 282% gap 根因是 E2E Fusion 可微 Sharpe loss 不能内嵌 discrete cost model (与 path divergence 无关). 真实 gap = **Config SSOT drift** (铁律 34). **Sub3 重定义为 Config SSOT 统一**: (1) Platform `BacktestConfig` 扩 12 字段 + 3 frozen 嵌套 value object (UniverseFilter/SlippageConfig/PMSConfig 镜像 engines); (2) signal_engine.py 消 3 处 hardcoded (factor_names sentinel + YAML 权威 + rebalance_freq/turnover_cap 从 YAML); (3) Runner `_build_engine_config` fallback 5→14 字段全映射, 消 Sub1 PR C3 `engine_config_builder` callable 绕 fallback 技术债 (Sub2 批量迁 scripts 解锁硬依赖). C3 SKIPPED (auditor.py 已正确处理). 47 新 unit + 1 rewritten + regression 5yr+12yr max_diff=0 + 5yr --twice Deterministic YES + full pytest 24 fail baseline 保持 + run_backtest bit-identical Sharpe=0.38 + 2 reviewer (code + python) 0 P1 blocking + 6 P2 + 2 P3 全修. LL-059 9 步闭环第 7 次, user 0 接触.
- 🟢 **MVP 2.3 Sub2 完结 (方案 C 极简)** (Session 9 2026-04-19, PR #20 `add41bb`): 3 P0 生产/CI 基线 scripts 迁 Platform SDK (`build_12yr_baseline.py` + `yearly_breakdown_backtest.py` + `wf_equal_weight_oos.py`). 采纳方案 C 极简 (非 A 全迁 31 / B 务实 8): **Wave 2 完备性 = P0 链路完整** (build_12yr_baseline 迁 Platform SDK 证明 SDK 能 round-trip 生成 regression_test 锚点), 其余 36 research scripts (Phase 2.1/2.2/3D/3E-ML/Step 6-F/G/H 多已 CLOSED) 保持 engines.backtest 直调按需迁 (铁律 23 不预设抽象). 硬门全绿: build_12yr_baseline **md5 bit-identical** (5 parquets 全匹配 pre-migration) + regression 5yr/12yr max_diff=0 Sharpe=0.6095/0.3594 + pytest full 24 fail baseline (2864 pass) + smoke 28 PASS (+3 oneshot_script_pre_main_imports) + ruff Sub2 clean. 2 reviewer (code + python) 0 P1 blocking + 3 P2 (1 误报) + 3 P3 全决议. LL-059 9 步闭环第 8 次, user 0 接触. **Wave 2 正式完结** — 进 Wave 3 规划.
- 🟡 **Wave 3 1/5 完结** (Session 30 末 2026-04-24, MVP 3.1 Risk Framework ✅): **MVP 3.1 Risk Framework ✅** (Session 28-30, 批 0 spike PR #54 + 批 1 PR #55/#57/#58 Framework core + PMSRule L1/L2/L3 + daily_pipeline 14:30 Beat / 批 2 PR #59/#60 intraday 4 rules + Beat `*/5 9-14` 72/日 + Redis 24h TTL dedup fail-open / 批 3 PR #61 CircuitBreakerRule Hybrid adapter 方案 C 包 `check_circuit_breaker_sync` 1640 行 sync API, **铁律 31 例外** ADR-010 addendum 接受, rule_id 动态 `cb_escalate_l{N}` / `cb_recover_l{N}`, Sunset gate A+B+C 条件. 6 PR / 2575 行 / 65 新 tests / 0 regression / 50 reviewer findings 49 采纳 98%. **2 P1 HIGH 捕获**: PR #60 `mark_alerted` 顺序 bug (防永久抑制告警) + PR #61 `_TrackedConnection` 连接泄漏 (psycopg2 `with` 只 commit/rollback 不 close). 生产激活 Celery Beat 5 schedule entries, 首次真生产触发 2026-04-27 Monday 09:00 intraday + 14:30 daily. LL-059 9 步闭环第 33-40 次, user ~6 次接触). **剩 4/5**: MVP 3.2 Strategy Framework (multi-strategy 一等公民 3-4 周) + MVP 3.3 Signal-Exec + MVP 3.4 Event Sourcing + MVP 3.5 Eval Gate (+ MVP 3.0 ROF + MVP 3.0a PEAD 为前置子项, 不计入 5 主 MVP 计数)
- 🟢 **MVP 3.3 Signal-Exec Framework ✅ 完结** (Session 37-40, 跨 5 sessions, ~13 PR 累计): **batch 1 ✅** PR #107 / **batch 2.1 ✅** PR #108 / **batch 3 ✅** PR #109 / **batch 2.2 Step 2 ✅** PR #110 (warn-only dual-run) / **Step 2.5 ✅** PR #111 (STRICT raise) / **Step 2.5 verification ✅** PR #112 (14/14 trade_dates bit-identical + STRICT flip live) / **Stage 3.0 真切换 ✅** PR #116 (Session 40, signal_service.generate_signals 内部走 PlatformSignalPipeline.generate(S1, ctx), 替 composer+SN+builder 三步 → SDK, 业务包络 factor coverage / Beta / industry / overlap / is_rebalance / _write_signals 全保留, regression 5yr+12yr max_diff=0 Sharpe=0.6095/0.3594, 25 trade_dates bit-identical 含调仓日). LL-082/083/084/085/086 + LL-087/088 (Session 39+40) 入册. **5-day gate 撤销** (用户挑战驱动 "为什么要等一周" → 实测 25 days bit-identical 证 STRICT path 完整覆盖, artificial gate 不必). 解锁 Wave 3 剩 MVP 3.4 Event Sourcing + 3.5 Eval Gate. LL-059 9 步闭环跨 sessions 78+ → 81+ (今日 +3 PR #113/#115/#116).
- 🟢 **Session 40 生产值守 + Stage 3.0 完结 (2026-04-28 Tuesday)**: (1) 10:00 钉钉 false-positive 告警 → **PR #113** 撤销 `qm:qmt:status` stream check (transition-only event ≠ heartbeat, LL-087 入册, -197 行). (2) 14:30 sanity scan 发现 DailySignal Mon 4-27 16:30 LastResult=0xC0000142 STATUS_DLL_INIT_FAILED → 4-27 数据 + 因子 backfill 修复. (3) 15:30 sanity scan 发现 celery worker `_active_count` counter 假泄漏 222/日 → **PR #115** `_TrackedConnection.__del__` finalizer 兜底 GC 路径, LL-088 入册 (resource counter 4 步 design checklist). (4) 16:00 用户挑战 "为什么要等一周" → 调仓日历史 scan 25 trade_dates bit-identical → **PR #116 Stage 3.0 真切换 merged**. 共 4 PR + 2 LL + 1 backfill, MVP 3.3 完结提前.
- 🟡 **Wave 4 启动 (Session 43 2026-04-28~29)**: MVP 4.1 Observability 进行中 (4 batches)
  - **batch 1 ✅ PR #131 merged** (`4536192` + `2bf9cec`, ~1351 行): PostgresAlertRouter cross-process PG dedup (alert_dedup 表 ON CONFLICT + SELECT FOR UPDATE) + DingTalkChannel + Channel Protocol + AlertDispatchError fail-loud + 双签名 fire(Alert, dedup_key) / alert(severity, payload) (interface.py + Blueprint #7 字面). 23 unit + 1 smoke. 3 reviewer (python+db+code) 4 P1 + 5 P2 + 2 LOW 全采纳: LSP 签名错位 / Tx rollback 吞 AlertDispatchError / sink_failed 永久抑制 P0 真金 (升 P1) / DB CHECK constraints. 设计稿 `docs/mvp/MVP_4_1_observability.md` (含 Part 1 双角色切换 + Pattern A/C/D Usage + 4 特征 Platform-App 判定).
  - **batch 2.1 ✅ PR #132 merged** (`bc06b50` + `043ccde`, ~700 行): PostgresMetricExporter (gauge / counter / histogram + Blueprint emit) + platform_metrics TimescaleDB hypertable + 30d retention + 4-phase migration (BEGIN/CREATE → hypertable → indexes → DO guard 对齐 risk_event_log.sql). 23 unit + 1 smoke. 2 reviewer (python+db) 1 CRITICAL + 3 HIGH + 2 P3 全采纳: PG NaN CHECK 真 bug (`value=value` 在 PG DOUBLE PRECISION 上永真, 改 `value!='NaN'::float8`) / rollback 缺 remove_retention_policy / query_recent conn 泄漏 / counter 0 reject.
  - **batch 2.2 ✅ PR #133 merged** (`1c52530` + `11f98d3`, ~700 行): AlertRulesEngine yaml-driven routing (rules.py ~250 行 + 15 默认规则 configs/alert_rules.yaml 覆盖 17 scripts) + B6 Framework `.health()` (HealthReport frozen + safe_check 防 endpoint 自杀 + aggregate_status ok/degraded/down/empty=down). 28 unit + 1 smoke + 4 reviewer fix tests. 1 reviewer (python) 1 P1 + 2 P2 全采纳: format_dedup_key alert.details silent shadow source/severity 真 bug (反转 ctx 顺序, top-level 永远赢) / HealthReport.details mutable despite frozen=True (包 MappingProxyType) / Empty rules engine silent no-op (logger.warning 提示运维).
  - **batch 3.x (待开, 风险拆细)**: 17 scripts 串行迁 SDK, 单 script 1 PR (高风险 P0) 或 2 scripts 1 PR (低风险 P1/P2). dry-run payload 比对 + schtask 真触发 verify 替代日历观察期.
  - **batch 4 (可选)**: PlatformEventBus wrap StreamBus + B10 OTel correlation_id 评估
- ⬜ **Wave 4 剩**: MVP 4.2 Performance Attribution + MVP 4.3 CI/CD + MVP 4.4 Backup & DR
- **MVP 串行交付**: 完成一个再 plan 下一个, 不预批量写设计稿 (铁律 23/24)

📋 系统蓝图: `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` (当前真相) + `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (演进规划)
📊 测试: 2800+ tests collected / 100+ test files (Session 9 末 Sub2 PR #20 post-merge 2026-04-19 实测: full pytest **2864 pass / 24 fail** [+50 new cumulative Session 9 含 Sub3 47 + Sub2 3, 铁律 40 baseline 保持], regression 5yr max_diff=0 Sharpe=0.6095 + 12yr max_diff=0 Sharpe=0.3594 [铁律 15], ruff Sub2 文件 clean) + **铁律 10b smoke 29 total / pre-push 28 PASS + 1 deselected (live_tushare)** (Wave 1+2+2.3 Sub1+Sub3+Sub2 全覆盖, +3 oneshot_script_pre_main_imports) + **MVP 2.1b 55 新 unit** (Baostock 17 + QMT 15 + Tushare 23) + **MVP 2.1c Sub1+Sub2+Sub3-prep 36 新 unit** (DAL 21 + Pipeline Contract 9 + Sub3-prep tushare 6) + **MVP 2.2 Sub1+Sub2 25 新 unit** + **MVP 2.3 Sub1 PR B+C1+C2+C3 新 unit 合计**: Runner 32 + Registry 9 + Loaders 7 + MemoryRegistry 11 = 59 (PR C3 +8 cumulative: builder 4 + signal_config fallback 4) + **Phase 3 MVP A 26 + MVP 1.3c 39 + MVP 1.4 38 + MVP 2.1a 29 + bootstrap 6 tests**
---

## CC 自动化操作

`docs/runbook/cc_automation/` 集中存放可触发的 CC ops runbook (e.g. 撤 setx / Servy 全重启 / DB 命名空间修复 / 等). 索引见 [`docs/runbook/cc_automation/00_INDEX.md`](docs/runbook/cc_automation/00_INDEX.md).

**触发模式**: user 一句话 → CC 加载对应 runbook → 自主执行 (前置检查 + 真金 0 风险确认 + 验证清单 + 失败回滚) → STATUS_REPORT 归档. user 0 手工操作.

跟 `docs/audit/` (一次性诊断) / `docs/adr/` (架构决议) / `docs/mvp/` (功能设计) 区分: runbook 是**可重复触发**的运维资产.

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
- **平台化蓝图 (未来 6 月主线)**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` ⭐ (QPB v1.16)
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
